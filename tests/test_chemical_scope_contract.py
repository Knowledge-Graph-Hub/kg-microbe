"""Keep reviewed ingredient scopes through stale imports, lookup and producers."""

import csv
import io

import pytest

from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import accepted_name_scope
from tests.test_consolidate_chemical_mappings import _load_module
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

LOCAL = "kgmicrobe.ingredient:sorbitan_monooleate"
ENTITIES = {
    "NCIT:C61894": "Polymyxin B",
    "CHEBI:8309": "polymyxin B1",
    "NCIT:C61895": "Polymyxin B Sulfate",
    "CHEBI:26580": "rifamycins",
    "CHEBI:29673": "rifamycin SV",
    "NCIT:C29406": "Rifamycin",
    "CHEBI:15318": "xanthine",
    "CHEBI:17712": "9H-xanthine",
    "CHEBI:183688": "sorbitan monooleate",
    "CHEBI:53426": "polysorbate 80",
    LOCAL: "Sorbitan Monooleate",
}


@pytest.fixture(params=[False, True])
def scoped_mapping(tmp_path, monkeypatch, request):
    """Exercise both row orders, including adversarial old aliases and xrefs."""
    rows = [
        _row("kgm.name:" + key.replace(":", "_"), key, label, name=label, comment="canonical_name")
        for key, label in ENTITIES.items()
    ]
    for target, alias in [
        ("CHEBI:8309", "Polymyxin B"),
        ("CHEBI:29673", "rifamycin"),
        ("CHEBI:17712", "xanthine"),
        ("CHEBI:53426", "sorbitan monooleate"),
    ]:
        rows.append(
            _row("kgm.name:stale_" + target.replace(":", "_"), target, ENTITIES[target], name=alias, comment="synonym")
        )
    for subject, target in [
        ("MIM:Xanthine", "CHEBI:15318"),
        ("MIM:Xanthine", "CHEBI:17712"),
        ("cas:69-89-6", "CHEBI:15318"),
        ("CHEBI:17712", "CHEBI:15318"),
        ("cas:6998-60-3", "CHEBI:26580"),
        ("NCIT:C61894", "CHEBI:8309"),
        ("cas:1338-43-8", LOCAL),
        ("cas:9005-65-6", LOCAL),
        ("MIM:Sorbitan_Monooleate", "CHEBI:183688"),
        ("MIM:Sorbitan_Monooleate", LOCAL),
    ]:
        rows.append(_row(subject, target, ENTITIES[target]))
    rows.append(_row("CHEBI:17712", "CHEBI:15318", "xanthine", predicate="skos:broadMatch"))
    rows.append(_row("kgm.name:tween80", "CHEBI:53426", "polysorbate 80", name="Tween 80", comment="synonym"))
    if request.param:
        rows.reverse()
    path = tmp_path / "scopes.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    return path


def test_generic_and_explicit_scopes_survive_row_order(scoped_mapping):
    """Generic names and specific identifiers must resolve independently."""
    for query, expected in [
        ("Polymyxin B", "NCIT:C61894"),
        ("polymyxin_b1", "CHEBI:8309"),
        ("Polymyxin B Sulfate", "NCIT:C61895"),
        ("rifamycin", "CHEBI:26580"),
        ("Rifamycin SV", "CHEBI:29673"),
        ("Xanthine", "CHEBI:15318"),
        ("9H-xanthine", "CHEBI:17712"),
        ("sorbitan monooleate", LOCAL),
        ("Tween 80", "CHEBI:53426"),
    ]:
        assert runtime.find_chebi_by_name(query) == expected
    for cas, expected in [
        ("1404-26-8", "NCIT:C61894"),
        ("4135-11-9", "CHEBI:8309"),
        ("6998-60-3", "CHEBI:29673"),
        ("69-89-6", "CHEBI:17712"),
    ]:
        assert runtime.find_chebi_by_name(cas) == expected
        assert runtime.find_chebi_by_xref("CAS:" + cas) == expected
        assert "cas:" + cas in runtime.get_node_enrichment(expected)["xref"].split("|")
    assert runtime.find_chebi_by_xref("MIM:Xanthine") == "CHEBI:17712"
    assert runtime.find_chebi_by_xref("MIM:Sorbitan_Monooleate") == LOCAL
    assert runtime.get_parents("CHEBI:17712") == ["CHEBI:15318"]
    assert "CHEBI:17712" not in runtime.get_xrefs("CHEBI:15318")
    assert "cas:69-89-6" not in runtime.get_node_enrichment("CHEBI:15318")["xref"].split("|")
    assert not any(x.startswith("cas:") for x in runtime.get_node_enrichment(LOCAL)["xref"].split("|"))
    assert "sorbitan monooleate" not in runtime.get_synonyms("CHEBI:53426")


def test_three_unspecified_rifamycin_observations_use_family(scoped_mapping):
    """Production and resistance observations do not acquire SV specificity."""
    decoder = MicrobeDecoderTransform.__new__(MicrobeDecoderTransform)
    decoder.chemical_loader = runtime.ChemicalMappingLoader(scoped_mapping)
    writer = csv.writer(io.StringIO())
    for source_column in [
        "BacDive_Metabolite_production",
        "BacDive_Metabolite_production",
        "BacDive_Antibiotic_resistance",
    ]:
        assert decoder._resolve_chemical_curie("rifamycin", writer, source_column) == "CHEBI:26580"
    assert decoder._resolve_chemical_curie("rifamycin SV", writer, "BacDive_Antibiotic_resistance") == "CHEBI:29673"
    assert runtime.get_xrefs("CHEBI:26580") == []


def test_missing_scoped_target_cannot_fall_back_to_specific_synonym(tmp_path, monkeypatch):
    """A missing generic concept must fail closed instead of inventing specificity."""
    path = tmp_path / "missing.tsv"
    _table(
        path,
        FIELDS,
        [_row("kgm.name:xanthine", "CHEBI:17712", "Xanthine", name="Xanthine", comment="canonical_name")],
        _metadata(),
    )
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("Xanthine", fuzzy_stereochemistry=True) is None
    assert runtime.find_chebi_by_xref("cas:1404-26-8") is None
    assert runtime.find_chebi_by_name("9H-xanthine") == "CHEBI:17712"


def test_reseed_and_propagation_cannot_merge_reviewed_scopes(scoped_mapping, monkeypatch):
    """Rejected xrefs must not reintroduce false aliases after consolidation."""
    module = _load_module()
    monkeypatch.setattr(module, "_build_mangle_blacklist", lambda *_: set())
    consolidator = module.ChemicalMappingConsolidator()
    consolidator.load_existing_unified(scoped_mapping)
    consolidator.propagate_synonyms_via_xrefs()
    assert "NCIT:C61894" not in consolidator.chemicals["CHEBI:8309"]["xrefs"]
    assert "Polymyxin B" not in consolidator.chemicals["CHEBI:8309"]["synonyms"]
    assert "sorbitan monooleate" not in consolidator.chemicals["CHEBI:53426"]["synonyms"]
    assert "CHEBI:17712" not in consolidator.chemicals["CHEBI:15318"]["xrefs"]


@pytest.mark.parametrize(
    "subject,target,resolved,explicit",
    [
        ("MIM:Other", "CHEBI:17712", "CHEBI:15318", "CHEBI:17712"),
        ("MIM:Xanthine", "CHEBI:17712", "CHEBI:8309", "CHEBI:17712"),
        ("MIM:Xanthine", "CHEBI:17712", "CHEBI:15318", "CHEBI:15318"),
        ("MIM:Xanthine", "CHEBI:17712", None, "CHEBI:17712"),
    ],
)
def test_scope_acceptance_cannot_hide_a_wrong_route(subject, target, resolved, explicit):
    """Accept only the exact reviewed distinction when the MIM subject also works."""
    assert accepted_name_scope("MIM:Xanthine", "CHEBI:17712", "CHEBI:15318", "CHEBI:17712")
    assert not accepted_name_scope(subject, target, resolved, explicit)
