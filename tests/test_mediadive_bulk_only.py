"""Bulk MediaDive lookups must not silently consume YAML or HTTP fallbacks (#681)."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive import mediadive as mod


@pytest.fixture
def bulk_source(tmp_path, monkeypatch):
    """Build only the lookup surface, with every cache/API fallback forbidden."""
    source = mod.MediaDiveTransform.__new__(mod.MediaDiveTransform)
    source.bulk_data_dir = tmp_path / "raw" / "mediadive"
    source.using_bulk_data = True
    source.media_detailed = {}
    source.media_strains = {}
    source.solutions_data = {}
    source.compounds_data = {}
    source.compound_mappings = {}
    source.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda name: None)
    source.translation_table = str.maketrans(mod.TRANSLATION_TABLE_FOR_LABELS)
    source.api_calls_avoided = source.api_calls_made = 0

    def reject_fallback(*args, **kwargs):
        """Fail before any HTTP session or YAML parser can be used."""
        raise AssertionError("bulk lookup touched a YAML/HTTP fallback")

    real_is_file = Path.is_file

    def guarded_is_file(path):
        """Even testing whether an old YAML cache exists is unnecessary in bulk mode."""
        if path.suffix == ".yaml" and path.is_relative_to(tmp_path):
            raise AssertionError("bulk lookup inspected a YAML cache")
        return real_is_file(path)

    monkeypatch.setattr(source, "_get_mediadive_json", reject_fallback)
    monkeypatch.setattr(source, "_http_session", reject_fallback)
    monkeypatch.setattr(source, "download_yaml_and_get_json", reject_fallback)
    monkeypatch.setattr(mod.yaml, "safe_load", reject_fallback)
    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    return source


@pytest.mark.parametrize("medium_id", ["P11", "123"])
@pytest.mark.parametrize("cached", [False, True])
def test_missing_medium_detail_fails_before_cache_or_http(bulk_source, tmp_path, medium_id, cached):
    """Partial bulk coverage is not repaired by an old YAML file or an API call."""
    path = tmp_path / f"{medium_id}.yaml"
    payload = b"medium: {name: Contradictory old cache}\nsolutions: [{id: 99}]\n"
    if cached:
        path.write_bytes(payload)
    with pytest.raises(FileNotFoundError, match=medium_id):
        bulk_source.get_json_object(path, mod.MEDIUM + medium_id, tmp_path)
    assert bulk_source.api_calls_made == 0
    assert bulk_source.api_calls_avoided == 0
    assert path.read_bytes() == payload if cached else not path.exists()


@pytest.mark.parametrize("solutions", [None, [], [{"id": 7, "name": "Known solution"}]])
def test_present_medium_detail_preserves_its_actual_shape(bulk_source, tmp_path, solutions):
    """Known no-solutions public media stay distinct from missing and empty details."""
    detail = {"medium": {"id": "P1", "name": "Known public medium"}}
    if solutions is not None:
        detail[mod.SOLUTIONS_KEY] = solutions
    original = copy.deepcopy(detail)
    bulk_source.media_detailed["P1"] = detail
    actual = bulk_source.get_json_object(tmp_path / "P1.yaml", mod.MEDIUM + "P1", tmp_path)
    assert actual == original
    assert bulk_source.media_detailed == {"P1": original}
    assert (mod.SOLUTIONS_KEY in actual) is (solutions is not None)
    assert bulk_source.api_calls_avoided == 1
    assert bulk_source.api_calls_made == 0


@pytest.mark.parametrize("associations", [None, [], [{"id": 7, "growth": 0}, {"id": 8, "growth": 1}]])
def test_strain_lookup_retains_absence_and_original_polarity(bulk_source, tmp_path, associations):
    """Absent strain keys already mean no bulk associations, never a cache request."""
    original = copy.deepcopy(associations)
    if associations is not None:
        bulk_source.media_strains["P1"] = associations
    actual = bulk_source.get_json_object(tmp_path / "P1.yaml", mod.MEDIUM_STRAINS + "P1", tmp_path)
    assert actual == ([] if original is None else original)
    assert bulk_source.media_strains == ({} if original is None else {"P1": original})
    assert bulk_source.api_calls_avoided == 1
    assert bulk_source.api_calls_made == 0


@pytest.mark.parametrize("method", ["get_solution_recipe_occurrences", "get_compounds_of_solution"])
def test_missing_requested_solution_fails_before_http(bulk_source, method):
    """The compatibility view must not turn failed remote retrieval into an empty recipe."""
    with pytest.raises(FileNotFoundError, match="77"):
        getattr(bulk_source, method)("77")
    assert bulk_source.api_calls_made == 0
    assert bulk_source.api_calls_avoided == 0


@pytest.mark.parametrize("detail", [{"name": "Known solution without recipe"}, {"recipe": []}])
def test_present_solution_without_occurrences_stays_empty(bulk_source, detail):
    """A present source record without recipe items is not a missing solution record."""
    bulk_source.solutions_data["1"] = copy.deepcopy(detail)
    assert bulk_source.get_solution_recipe_occurrences("1") == []
    assert bulk_source.solutions_data == {"1": detail}
    assert bulk_source.api_calls_made == 0


def test_nested_local_occurrence_survives_until_missing_child_is_expanded(bulk_source):
    """A missing child recipe must not delete or re-identify its parent's full occurrence."""
    item = {
        "solution_id": 77,
        "solution": "Unresolved nested solution",
        "amount": 50,
        "unit": "ml",
        "g_l": None,
        "mmol_l": 0,
        "optional": True,
        "reference": "fixture citation",
    }
    bulk_source.solutions_data["1"] = {"recipe": [copy.deepcopy(item)]}
    (actual,) = bulk_source.get_solution_recipe_occurrences("1")
    assert actual[mod.ID_COLUMN] == mod.MEDIADIVE_SOLUTION_PREFIX + "77"
    assert actual[mod.NAME_COLUMN] == item[mod.SOLUTION_KEY]
    assert actual[mod.SOURCE_ASSERTION_ID_COLUMN] == "mediadive.solution:1#recipe/1"
    assert json.loads(actual[mod.SOURCE_RECORD_COLUMN]) == item
    for field in (mod.AMOUNT_COLUMN, mod.UNIT_COLUMN, mod.GRAMS_PER_LITER_COLUMN, mod.MMOL_PER_LITER_COLUMN):
        assert actual[field] == item[field]
    with pytest.raises(FileNotFoundError, match="77"):
        bulk_source.get_solution_recipe_occurrences("77")
    assert bulk_source.solutions_data == {"1": {"recipe": [item]}}
    assert bulk_source.api_calls_made == 0


@pytest.mark.parametrize("name", [None, "Unresolved fixture compound"])
def test_missing_compound_keeps_existing_local_identity_without_http(bulk_source, name):
    """Absent external mapping metadata is not grounds to discard an ingredient."""
    assert bulk_source.standardize_compound_id("99", name) == mod.MEDIADIVE_INGREDIENT_PREFIX + "99"
    assert bulk_source.api_calls_made == 0


def test_complete_recipe_retains_missing_compound_occurrences_and_multiplicity(bulk_source):
    """No compound endpoint exists; equal source occurrences still remain distinct."""
    item = {"compound_id": 99, "compound": "Unresolved", "amount": 0, "unit": "g", "g_l": 0, "mmol_l": 0}
    bulk_source.solutions_data["1"] = {"recipe": [copy.deepcopy(item), copy.deepcopy(item)]}
    actual = bulk_source.get_solution_recipe_occurrences("1")
    assert len(actual) == 2
    assert [row[mod.ID_COLUMN] for row in actual] == [mod.MEDIADIVE_INGREDIENT_PREFIX + "99"] * 2
    assert [row[mod.SOURCE_ASSERTION_ID_COLUMN] for row in actual] == [
        "mediadive.solution:1#recipe/1",
        "mediadive.solution:1#recipe/2",
    ]
    assert [json.loads(row[mod.SOURCE_RECORD_COLUMN]) for row in actual] == [item, item]
    for row in actual:
        for field in (mod.AMOUNT_COLUMN, mod.UNIT_COLUMN, mod.GRAMS_PER_LITER_COLUMN, mod.MMOL_PER_LITER_COLUMN):
            assert row[field] == item[field]
    assert bulk_source.solutions_data == {"1": {"recipe": [item, item]}}
    assert bulk_source.api_calls_made == 0
