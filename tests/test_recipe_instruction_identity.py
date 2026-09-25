"""Keep reviewed recipe instructions out of chemical identity routes (#1009)."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import (
    ingredient_authority_label,
    ingredient_mapping_allowed,
    ingredient_xref_allowed,
)
from scripts import mim_conservative_refresh as refresh
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table


def _cases():
    """Read the reviewed finite cohort, including historically propagated targets."""
    with (Path(__file__).parent / "resources/recipe_instruction_names.tsv").open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["target_id"] + ":" + case["name"])
def test_recipe_name_exclusions_are_target_scoped(case):
    """Block raw and reader-normalized forms without globally deleting labels."""
    name, target = case["name"], case["target_id"]
    assert not ingredient_mapping_allowed(name, target)
    assert not ingredient_mapping_allowed(runtime.normalize_name(name), target)
    assert ingredient_mapping_allowed(case["authority_label"], target)
    assert ingredient_mapping_allowed(name, "CHEBI:15377")


@pytest.mark.parametrize("name", ["(8Z,11Z,14Z)-5,6-epoxyicosatrienoyl-CoA(4-)", "(3R,7S)-12-OH-JA-Ile(1-)", "(m-CPP)"])
def test_parenthesized_chemical_names_are_not_a_recipe_filter(name):
    """No heuristic based on parentheses can reject legitimate chemical syntax."""
    for case in _cases():
        assert ingredient_mapping_allowed(name, case["target_id"])


def test_recipe_aliases_cannot_enter_runtime_or_fresh_evidence(tmp_path, monkeypatch):
    """Both old unified rows and newly read source aliases obey the same policy."""
    rows = []
    evidence = refresh._Evidence({"CHEBI", "FOODON", "NCIT", "cas"})
    for position, case in enumerate(_cases()):
        target, label, name = case["target_id"], case["authority_label"], case["name"]
        rows.append(_row(f"kgm.name:recipe_{position}", target, label, name=name, comment="synonym"))
        evidence.add(target, label, names=[name], source="reviewed_fixture")
        assert name not in evidence.records[target].names
        assert label in evidence.records[target].names
    path = tmp_path / "recipe.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    for case in _cases():
        assert runtime.find_chebi_by_name(case["name"]) is None
        assert case["name"] not in runtime.get_synonyms(case["target_id"])
        assert runtime.get_canonical_name(case["target_id"]) == case["authority_label"]


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_mediadive_recipe_instruction_cannot_fall_back_to_chemical(route):
    """Source-specific identity survives instead of restoring an instruction alias."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: "CHEBI:62969" if route == "unified" else None
    )
    transform.compound_mappings = {"autoclaved": "CHEBI:62969"} if route == "legacy" else {}
    transform.compounds_data = {"99": {"ChEBI": "62969"}} if route == "embedded" else {}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", "autoclaved") == "mediadive.ingredient:99"


def test_historical_salt_and_dye_regressions_remain_distinct():
    """Reject the known #788 mistakes without guessing new generic identities."""
    assert not ingredient_mapping_allowed("Berberine", "CHEBI:31271")
    assert ingredient_mapping_allowed("Berberine chloride", "CHEBI:31271")
    assert ingredient_mapping_allowed("Berberine", "CHEBI:16118")
    assert not ingredient_xref_allowed("MIM:Berberine", "CHEBI:31271")
    assert not ingredient_xref_allowed("CHEBI:91247", "CHEBI:52891")
    assert not ingredient_xref_allowed("CHEBI:52891", "CHEBI:91247")
    for name in ["Cysteine-HCl", "L-cysteine hydrochloride", "L-Cysteine x HCl x H2O solution", "Cysteine.HCl"]:
        assert not ingredient_mapping_allowed(name, "CHEBI:52891")
    assert ingredient_mapping_allowed("QSY9 succinimidyl ester(1+)", "CHEBI:52891")


def test_nitrate_recipe_aliases_do_not_equate_drug_and_metric_prefix():
    """Reject native-label contradictions without mapping the ambiguous NaNO string."""
    for name in ["NaNO3(CAS: 7631-99-4)", "NaNO3(Fisher BP360-500)", "NaNO3"]:
        for target in ["CHEBI:34545", "NCIT:C54713"]:
            assert not ingredient_mapping_allowed(name, target)
            assert not ingredient_mapping_allowed(runtime.normalize_name(name), target)
    assert not ingredient_xref_allowed("CHEBI:34545", "NCIT:C54713")
    assert not ingredient_mapping_allowed("NaNO", "CHEBI:34545")
    assert ingredient_mapping_allowed("Azimilide", "CHEBI:34545")
    assert ingredient_mapping_allowed("Nano", "NCIT:C54713")


def test_curated_authority_labels_match_immutable_native_excerpt():
    """Repair labels from native records rather than inventing replacement chemistry."""
    path = Path(__file__).parent / "resources/chemical_grounding_authorities.tsv"
    with path.open() as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            label = ingredient_authority_label(row["id"])
            if label:
                assert label == row["name"]
            assert ingredient_mapping_allowed(row["name"], row["id"])
