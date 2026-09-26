"""Reject the three finite legacy identities exposed by original-name recipe lookup."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed
from scripts import mim_conservative_refresh as refresh
from tests.test_mediadive_embedded_identity import _transform
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _metadata, _node, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs

EVIDENCE = json.loads((Path(__file__).parent / "resources" / "recipe_scope_1169.json").read_text())
CASES = EVIDENCE["cases"]
SPELLINGS = [
    ("Tris(hydroxymethyl)methylamine", "CHEBI:44356"),
    ("Trishydroxymethylmethylamine", "CHEBI:44356"),
    (" tris(hydroxymethyl)methylamine ", "CHEBI:44356"),
    ("(NH4) citrate", "CHEBI:63037"),
    ("(NH4)citrate", "CHEBI:63037"),
    ("NH4 citrate", "CHEBI:63037"),
    ("nh4citrate", "CHEBI:63037"),
    ("(NH4)2S4", "CHEBI:62946"),
    ("NH42S4", "CHEBI:62946"),
    (" (nh4)2s4 ", "CHEBI:62946"),
]


@pytest.mark.parametrize("name,target", SPELLINGS)
@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_original_and_normalized_queries_cannot_use_unsafe_fallbacks(name, target, route):
    """Every existing MediaDive lookup route enforces the same finite scope hold."""
    assert not ingredient_mapping_allowed(name, target)
    value = _transform(
        {"ChEBI": target.split(":")[1]} if route == "embedded" else {},
        {name.strip().lower(): target} if route == "legacy" else {},
        target if route == "unified" else None,
    )
    assert value.standardize_compound_id("99", name) == "mediadive.ingredient:99"


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("route", ["compound", "solution"])
def test_real_recipe_occurrence_remains_local_without_losing_quantities(case, route):
    """Hold every stale route together, preserving raw source spelling and amounts."""
    name, target = case["source_name"], case["target_id"]
    value = _transform({"ChEBI": target.split(":")[1]}, {name.lower(): target}, target)
    value.translation_table = str.maketrans("", "", "()")
    item = deepcopy(case["source"])
    item[route] = item.pop("compound")
    item[route + "_id"] = item.pop("compound_id")
    value.solutions_data = {"1": {"recipe": [item]}}
    before = deepcopy(value.solutions_data)
    actual = value.get_compounds_of_solution("1")[name.translate(value.translation_table)]
    expected_prefix = "mediadive.ingredient:" if route == "compound" else "mediadive.solution:"
    assert actual == {
        "id": expected_prefix + str(case["compound_id"]),
        "amount": item["amount"],
        "unit": item["unit"],
        "g_l": item.get("g_l"),
        "mmol_l": item.get("mmol_l"),
    }
    assert value.solutions_data == before


@pytest.mark.parametrize("stale_canonical", [False, True])
@pytest.mark.parametrize("mode", [{}, {"fuzzy_hydrate": True}, {"fuzzy_stereochemistry": True}])
def test_stale_unified_alias_or_object_label_does_not_reinstate_false_scope(
    tmp_path, monkeypatch, stale_canonical, mode
):
    """Reader admission rejects bad names while retaining each actual native authority."""
    rows = []
    for case in CASES:
        name, target, native = case["source_name"], case["target_id"], case["native_label"]
        label = name if stale_canonical else native
        rows.extend(
            [
                _row(
                    "kgm.name:bad" + case["target_id"].split(":")[1],
                    target,
                    label,
                    name=name,
                    comment="canonical_name" if stale_canonical else "synonym",
                ),
                _row(
                    "kgm.name:native" + case["target_id"].split(":")[1],
                    target,
                    label,
                    name=native,
                    comment="synonym" if stale_canonical else "canonical_name",
                ),
            ]
        )
    path = tmp_path / "stale.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    for name, _ in SPELLINGS:
        assert runtime.find_chebi_by_name(name, **mode) is None
    for case in CASES:
        assert runtime.find_chebi_by_name(case["native_label"], **mode) == case["target_id"]


@pytest.mark.parametrize("case", CASES)
def test_native_identities_and_explicit_salt_scope_remain_allowed(case):
    """The finite policy does not become an ontology-ID or formula-family ban."""
    target = case["target_id"]
    for native in [case["native_label"], *case["native_synonyms"]]:
        assert ingredient_mapping_allowed(native, target)
    for name, correct in [
        ("(NH4)2 citrate", "CHEBI:63076"),
        ("(NH4)3 citrate", "CHEBI:63037"),
        ("(NH4)2SO4", "CHEBI:62946"),
        ("Tris(hydroxymethyl)methylamine", "CHEBI:9754"),
    ]:
        assert ingredient_mapping_allowed(name, correct)
    value = _transform({})
    value.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda name: target)
    assert value.standardize_compound_id("99", case["native_label"]) == target


def test_legacy_table_rejects_wrong_pairs_before_any_fallback(tmp_path):
    """Both real priority files use the same lexical policy without repairing a source label."""
    path = tmp_path / "legacy.tsv"
    path.write_text("original\tmapped\n" + "".join(name + "\t" + target + "\n" for name, target in SPELLINGS))
    value = _transform({})
    assert value._load_mapping_file(path, "strict fixture") == {}
    assert value._load_mapping_file(path, "hydrate fixture") == {}


def test_candidate_quarantines_originals_restores_native_authorities_and_converges(inputs):
    """A supported-only rebuild cannot regenerate these historical bad lexical claims."""
    originals = [
        _row(
            "kgm.name:bad" + str(case["compound_id"]),
            case["target_id"],
            case["source_name"],
            name=case["source_name"],
            comment="canonical_name",
        )
        for case in CASES
    ]
    _table(inputs["baseline"], FIELDS, [*refresh._rows(inputs["baseline"]), *originals], _metadata())
    authority = inputs["ontology_paths"][0]
    natives = [_node(case["target_id"], case["native_label"], "|".join(case["native_synonyms"])) for case in CASES]
    _table(authority, NODE_FIELDS, [*[row for _, row in refresh._native_rows((authority,))], *natives])
    result = refresh.build_conservative_candidate(**inputs)
    candidate, quarantine = _read(result.candidate_path), _read(result.quarantine_path)
    for original in originals:
        assert original not in candidate
        assert dict(original, quarantine_reason="reviewed_identity_policy_name") in quarantine
    for case in CASES:
        assert any(
            row["object_id"] == case["target_id"] and row["subject_label"] == case["native_label"] for row in candidate
        )
        assert not any(
            row["object_id"] == case["target_id"]
            and not ingredient_mapping_allowed(row["subject_label"], case["target_id"])
            for row in candidate
        )
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=result.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert second.candidate_path.read_bytes() == result.candidate_path.read_bytes()


def test_native_scope_fixture_distinguishes_tris_from_tes_and_unknown_salt_scope():
    """Pinned source quantities support only the stated comparison, not guessed replacements."""
    tris, citrate, oxygen_free = CASES
    assert tris["source"]["g_l"] * 1000 / tris["source"]["mmol_l"] == pytest.approx(121.14, abs=0.01)
    assert tris["native_cas"] == "7365-44-8"
    assert EVIDENCE["independent_comparisons"][0]["cas"] == "77-86-1"
    assert "mmol_l" not in citrate["source"] and "mmol_l" not in oxygen_free["source"]
    assert "(NH4)2SO4" in oxygen_free["native_synonyms"]
    assert oxygen_free["source_name"] == "(NH4)2S4"
