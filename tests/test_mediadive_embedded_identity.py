"""Enforce the same finite ingredient identity policy across every fallback namespace (#1155)."""

import hashlib
import json
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive import mediadive
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table


def _transform(data, mappings=None, unified=None):
    """Build only the hermetic ingredient resolver, without reading repository outputs."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: unified)
    transform.compound_mappings = mappings or {}
    transform.compounds_data = {"99": data}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    return transform


def test_pinned_pubchem_parent_and_salt_authorities_remain_distinct():
    """Native primary-source payload supports rejection, without live test dependencies."""
    path = Path(__file__).parent / "resources/pubchem_cysteine_scope.json"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == "3a6a21b65b509f290c812ea4640c54e97103e6b9611fbcd7d2db89abc82eabfe"
    )
    records = {row["CID"]: row for row in json.loads(path.read_text())["PropertyTable"]["Properties"]}
    assert records[5862]["MolecularFormula"] == "C3H7NO2S"
    assert records[60960]["MolecularFormula"] == "C3H8ClNO2S"
    assert records[5862]["Title"] == "L-(+)-Cysteine"
    assert "hydrochloride" in records[60960]["IUPACName"]
    for cid, row in records.items():
        assert ingredient_mapping_allowed(row["Title"], f"pubchem.compound:{cid}")


@pytest.mark.parametrize(
    "key,value,prefix",
    [
        ("ChEBI", "1", "CHEBI:"),
        ("KEGG-Compound", "C00001", "KEGG:"),
        ("PubChem", "123", "PubChem:"),
        ("CAS-RN", "123-45-6", "CAS-RN:"),
    ],
)
@pytest.mark.parametrize("explicit_name", [True, False])
def test_each_embedded_namespace_checks_original_ingredient_name(monkeypatch, key, value, prefix, explicit_name):
    """A synthetic policy rejection exercises the branch, not any live chemical identity."""
    calls = []

    def reject(name, target):
        calls.append((name, target))
        return False

    monkeypatch.setattr(mediadive, "ingredient_mapping_allowed", reject)
    transform = _transform({key: value, "name": "fixture ingredient"})
    assert (
        transform.standardize_compound_id("99", "fixture ingredient" if explicit_name else None)
        == "mediadive.ingredient:99"
    )
    assert calls == [("fixture ingredient", prefix + value)]


@pytest.mark.parametrize("target", ["PubChem:5862", "pubchem.compound:5862", "PUBCHEM:5862"])
@pytest.mark.parametrize("name", ["Cysteine-HCl", " Cysteine HCl ", "L-Cysteine x HCl"])
def test_legacy_and_canonical_pubchem_prefixes_cannot_hide_parent_salt_mismatch(target, name):
    """The finite PubChem alias is namespace normalization, not a chemical equivalence guess."""
    assert not ingredient_mapping_allowed(name, target)
    assert ingredient_mapping_allowed("L-Cysteine", target)
    assert ingredient_mapping_allowed("L-cysteine hydrochloride", "pubchem.compound:60960")
    for route in ["unified", "legacy"]:
        transform = _transform(
            {}, {name.lower().strip(): target} if route == "legacy" else None, target if route == "unified" else None
        )
        assert transform.standardize_compound_id("99", name) == "mediadive.ingredient:99"


def test_mixed_cysteine_routes_cannot_select_free_parent_or_unrelated_drug():
    """Reject actual distinct false targets across unified, legacy and embedded fallbacks."""
    transform = _transform(
        {"ChEBI": "5862", "PubChem": "5862"}, {"cysteine-hcl": "PubChem:5862"}, "pubchem.compound:5862"
    )
    assert transform.standardize_compound_id("99", "Cysteine-HCl") == "mediadive.ingredient:99"
    assert transform.api_calls_avoided == 1
    native_free = _transform({"PubChem": "5862"})
    assert native_free.standardize_compound_id("99", "L-Cysteine") == "PubChem:5862"


def test_rejected_embedded_target_can_use_later_independently_supplied_salt():
    """A supported embedded salt remains usable; the resolver does not invent it."""
    transform = _transform({"ChEBI": "5862", "PubChem": "60960"})
    assert transform.standardize_compound_id("99", "L-cysteine HCl") == "PubChem:60960"


def test_cas_legacy_prefix_obeys_existing_recipe_instruction_policy():
    """The all-namespace contract must apply existing canonical CAS rules to CAS-RN too."""
    assert not ingredient_mapping_allowed("autoclaved", "cas:9000-40-2")
    assert not ingredient_mapping_allowed("autoclaved", "CAS-RN:9000-40-2")
    transform = _transform({"CAS-RN": "9000-40-2"})
    assert transform.standardize_compound_id("99", "autoclaved") == "mediadive.ingredient:99"
    assert transform.standardize_compound_id("99", "locust bean gum") == "CAS-RN:9000-40-2"


@pytest.mark.parametrize(
    "name,target,native",
    [
        ("D-Glucose", "CHEBI:42758", "aldehydo-D-glucose"),
        ("D-Glucose", "CHEBI:4167", "D-glucopyranose"),
        ("Sodium citrate", "CHEBI:32142", "sodium citrate dihydrate"),
        ("Sodiumcitrate", "CHEBI:32142", "sodium citrate dihydrate"),
        ("0.2% Thiamine pyrophosphate", "CHEBI:9532", "thiamine(1+) diphosphate"),
    ],
)
@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_remaining_original_788_pairs_cannot_add_unreported_scope(name, target, native, route):
    """Known native subtype/hydrate/preparation distinctions survive every active resolver route."""
    assert not ingredient_mapping_allowed(name, target)
    assert ingredient_mapping_allowed(native, target)
    transform = _transform(
        {"ChEBI": target.split(":", 1)[1]} if route == "embedded" else {},
        {name.lower(): target} if route == "legacy" else None,
        target if route == "unified" else None,
    )
    assert transform.standardize_compound_id("99", name) == "mediadive.ingredient:99"


def test_legacy_false_rows_are_rejected_before_duplicate_name_selection(tmp_path):
    """A later independently supplied generic mapping is not hidden by a wrong first row."""
    path = tmp_path / "legacy.tsv"
    path.write_text(
        "original\tmapped\nD-Glucose\tCHEBI:42758\nD-Glucose\tCHEBI:17634\n"
        "aldehydo-D-glucose\tCHEBI:42758\nCysteine-HCl\tPubChem:5862\nL-Cysteine\tPubChem:5862\n"
    )
    transform = _transform({})
    rows = transform._load_mapping_file(path, "immutable fixture")
    assert rows == {"d-glucose": "CHEBI:17634", "aldehydo-d-glucose": "CHEBI:42758", "l-cysteine": "PubChem:5862"}


THIAMINE = {
    "CHEBI:18290": "thiamine(1+) diphosphate chloride",
    "CHEBI:45931": "thiamine(1+) diphosphate(1-)",
    "CHEBI:9532": "thiamine(1+) diphosphate",
}


@pytest.mark.parametrize("ordered", list(permutations(THIAMINE)))
def test_bare_thiamine_hold_cannot_choose_an_alternate_native_scope(tmp_path, monkeypatch, ordered):
    """The demonstrated three-way native alias must not choose charge/salt scope by row order."""
    rows = []
    for target in ordered:
        native = THIAMINE[target]
        rows.extend(
            [
                _row("kgm.name:" + target.replace(":", "_"), target, native, name=native, comment="canonical_name"),
                _row(
                    "kgm.name:thiamine_pyrophosphate", target, native, name="thiamine pyrophosphate", comment="synonym"
                ),
            ]
        )
    rows.extend(
        [
            _row("kgm.name:thr-pro-pro", "CHEBI:164196", "Thr-Pro-Pro", name="Thr-Pro-Pro", comment="canonical_name"),
            _row("kgm.name:tpp", "CHEBI:164196", "Thr-Pro-Pro", name="TPP", comment="synonym"),
        ]
    )
    path = tmp_path / "ambiguous-thiamine.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    for mode in [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}]:
        assert runtime.find_chebi_by_name("thiamine pyrophosphate", **mode) is None
        for target, native in THIAMINE.items():
            assert runtime.find_chebi_by_name(native, **mode) == target
    assert runtime.find_chebi_by_name("TPP") == "CHEBI:164196"
    assert runtime.find_chebi_by_name("Co-carboxylase") is None
    transform = _transform({"ChEBI": "9532"}, {"thiamine pyrophosphate": "CHEBI:45931"}, "CHEBI:18290")
    assert transform.standardize_compound_id("99", "thiamine pyrophosphate") == "mediadive.ingredient:99"


@pytest.mark.parametrize("generic_present", [True, False])
def test_generic_glucose_does_not_fall_back_to_narrower_native_forms(tmp_path, monkeypatch, generic_present):
    """Only an independently declared generic identity can answer the generic ingredient query."""
    records = {"CHEBI:4167": "D-glucopyranose", "CHEBI:42758": "aldehydo-D-glucose"}
    if generic_present:
        records["CHEBI:17634"] = "D-glucose"
    rows = []
    for target, native in records.items():
        rows.extend(
            [
                _row("kgm.name:" + target.replace(":", "_"), target, native, name=native, comment="canonical_name"),
                _row("kgm.name:d-glucose", target, native, name="D-Glucose", comment="synonym"),
            ]
        )
    path = tmp_path / "native-glucose.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    for mode in [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}]:
        assert runtime.find_chebi_by_name("D-Glucose", **mode) == ("CHEBI:17634" if generic_present else None)
        assert runtime.find_chebi_by_name("D-glucopyranose", **mode) == "CHEBI:4167"
        assert runtime.find_chebi_by_name("aldehydo-D-glucose", **mode) == "CHEBI:42758"


@pytest.mark.parametrize("mode", [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}])
def test_stale_unified_salt_alias_does_not_override_native_free_cysteine(tmp_path, monkeypatch, mode):
    """The false CID5862 alias is blocked without suppressing its valid free-amino-acid name."""
    path = tmp_path / "historical-cysteine.tsv"
    metadata = _metadata()
    metadata["curie_map"]["pubchem.compound"] = "https://pubchem.ncbi.nlm.nih.gov/compound/"
    _table(
        path,
        FIELDS,
        [
            _row(
                "kgm.name:l-cysteine",
                "pubchem.compound:5862",
                "L-Cysteine",
                name="L-Cysteine",
                comment="canonical_name",
            ),
            _row(
                "kgm.name:cysteine-hcl",
                "pubchem.compound:5862",
                "",
                "mediadive_compounds",
                "skos:closeMatch",
                "Cysteine-HCl",
                "synonym",
            ),
        ],
        metadata,
    )
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("Cysteine-HCl", **mode) is None
    assert runtime.find_chebi_by_name("L-Cysteine", **mode) == "pubchem.compound:5862"
