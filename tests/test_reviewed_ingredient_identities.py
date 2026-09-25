"""Protect reviewed CAS annotations and unresolved material scope at runtime."""

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from tests.test_consolidate_chemical_mappings import _load_module
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

LOCAL = "kgmicrobe.ingredient:lysozyme"
CASES = [
    ("Anabasine Hydrochloride", "NCIT:C216370", "53912-89-3"),
    ("Cotarnine Chloride", "NCIT:C79997", "10018-19-6"),
    ("Pretomanid", "NCIT:C166606", "187235-37-6"),
    ("Sutezolid", "NCIT:C152482", "168828-58-8"),
    ("Bovine Serum Albumin", "NCIT:C85253", "9048-46-8"),
    ("Sunflower Oil", "NCIT:C1241", "8001-21-6"),
    ("Zymosan", "NCIT:C183132", "9010-72-4"),
    ("Locust Bean Gum", "FOODON:03413132", "9000-40-2"),
    ("Tara Gum", "FOODON:03413299", "39300-88-4"),
    ("Sodium Adipate", "FOODON:03413240", "7486-38-6"),
    ("Acriflavine", "NCIT:C76253", "65589-70-0"),
]


@pytest.fixture(params=[False, True])
def identity_mapping(tmp_path, monkeypatch, request):
    """Load both row orders with stale CAS and food-additive equivalence claims."""
    entities = [(name, target) for name, target, _ in CASES] + [("Lysozyme", LOCAL), ("lysozyme", "FOODON:03413135")]
    rows = [
        _row("kgm.name:" + target.replace(":", "_"), target, name, name=name, comment="canonical_name")
        for name, target in entities
    ]
    for subject, target, label in [
        ("cas:8048-52-0", "NCIT:C76253", "Acriflavine"),
        ("MIM:Lysozyme", "FOODON:03413135", "lysozyme"),
        ("MIM:Lysozyme", LOCAL, "Lysozyme"),
        ("FOODON:03413135", LOCAL, "Lysozyme"),
        ("cas:2650-88-3", LOCAL, "Lysozyme"),
        ("cas:12650-88-3", LOCAL, "Lysozyme"),
    ]:
        rows.append(_row(subject, target, label))
    for target, label, alias in [("NCIT:C76253", "Acriflavine", "CAS:8048-52-0"), (LOCAL, "Lysozyme", "CAS:2650-88-3")]:
        rows.append(_row("kgm.name:stale_" + target.replace(":", "_"), target, label, name=alias, comment="synonym"))
    if request.param:
        rows.reverse()
    path = tmp_path / "identities.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    return path


def test_current_cas_is_a_node_annotation_without_new_equivalence(identity_mapping):
    """Current RN lookup and node enrichment must not synthesize identity xrefs."""
    for name, target, cas in CASES:
        assert runtime.find_chebi_by_name(name) == target
        assert runtime.find_chebi_by_xref("CAS:" + cas) == target
        assert runtime.find_chebi_by_name(cas) == target
        assert "cas:" + cas in runtime.get_node_enrichment(target)["xref"].split("|")
        assert "cas:" + cas not in runtime.get_xrefs(target)


def test_historical_and_guessed_cas_do_not_reenter_current_nodes(identity_mapping):
    """Superseded and unsupported RNs remain history, never current aliases."""
    assert runtime.find_chebi_by_name("Lysozyme") == LOCAL
    assert runtime.find_chebi_by_xref("MIM:Lysozyme") == LOCAL
    assert runtime.find_chebi_by_xref("cas:2650-88-3") is None
    assert runtime.find_chebi_by_xref("cas:8048-52-0") is None
    assert runtime.find_chebi_by_name("CAS:2650-88-3") is None
    assert runtime.find_chebi_by_name("CAS:8048-52-0") is None
    assert not any(x.lower().startswith("cas:") for x in runtime.get_node_enrichment(LOCAL)["xref"].split("|"))
    assert "cas:8048-52-0" not in runtime.get_node_enrichment("NCIT:C76253")["xref"].split("|")
    assert "FOODON:03413135" not in runtime.get_xrefs(LOCAL)


def test_consolidator_cannot_restore_rejected_cas_equivalence(identity_mapping, monkeypatch):
    """A stale seed cannot propagate historical RNs into these current identities."""
    module = _load_module()
    monkeypatch.setattr(module, "_build_mangle_blacklist", lambda *_: set())
    consolidator = module.ChemicalMappingConsolidator()
    consolidator.load_existing_unified(identity_mapping)
    consolidator.propagate_synonyms_via_xrefs()
    assert "cas:8048-52-0" not in consolidator.chemicals["NCIT:C76253"]["xrefs"]
    assert "CAS:8048-52-0" not in consolidator.chemicals["NCIT:C76253"]["synonyms"]
    assert not consolidator.chemicals[LOCAL]["xrefs"] & {"cas:12650-88-3", "cas:2650-88-3", "FOODON:03413135"}


def test_missing_local_lysozyme_does_not_infer_food_additive_scope(tmp_path, monkeypatch):
    """Missing reviewed material must remain unresolved even with a native name match."""
    path = tmp_path / "foodon-only.tsv"
    _table(
        path,
        FIELDS,
        [_row("kgm.name:lysozyme", "FOODON:03413135", "lysozyme", name="lysozyme", comment="canonical_name")],
        _metadata(),
    )
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("lysozyme") is None
    assert runtime.get_canonical_name("FOODON:03413135") == "lysozyme"
