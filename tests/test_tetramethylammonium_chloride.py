"""Resolve a reviewed salt spelling without guessing its parent or other salts (#1242)."""

import json
from pathlib import Path

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_cas_annotations, ingredient_name_target
from tests import test_mim_conservative_refresh as refresh_tests
from tests.test_mediadive_recipe_occurrences import _resolver
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

FIXTURE = Path(__file__).parent / "resources/tetramethylammonium_chloride.json"
SALT_NAME = "Tetramethyl ammonium chloride"
PARENT_NAME = "Tetramethyl ammonium"
PARENT_ID = "kgmicrobe.compound:tetramethyl_ammonium"
inputs = refresh_tests.inputs
bundle = refresh_tests.bundle


def _load_selected(tmp_path, monkeypatch, *, salt=True, reverse=False, wrong_alias=False):
    """Use only two explicitly declared targets and the native salt synonym."""
    evidence = json.loads(FIXTURE.read_text())
    native = evidence["native_projection"]
    rows = [_row("kgm.name:parent", PARENT_ID, PARENT_NAME, name=PARENT_NAME, comment="canonical_name")]
    if wrong_alias:
        rows.append(_row("kgm.name:wrong_old_alias", PARENT_ID, PARENT_NAME, name=SALT_NAME, comment="synonym"))
    if salt:
        rows.extend(
            _row("kgm.name:" + key, native["id"], native["name"], name=native[key], comment=comment)
            for key, comment in (("name", "canonical_name"), ("synonym", "synonym"))
        )
    if reverse:
        rows.reverse()
    path = tmp_path / "selected-declarations.tsv"
    _table(path, FIELDS, rows, _metadata())
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    return runtime.ChemicalMappingLoader(path)


@pytest.mark.parametrize("synonyms", [True, False])
@pytest.mark.parametrize("reverse", [True, False])
@pytest.mark.parametrize("salt_first", [True, False])
def test_finite_alias_and_parent_are_order_independent(tmp_path, monkeypatch, synonyms, reverse, salt_first):
    """Both lookup modes honor the finite spelling without changing its parent."""
    loader = _load_selected(tmp_path, monkeypatch, reverse=reverse)
    queries = [(SALT_NAME, "CHEBI:7070"), (PARENT_NAME, PARENT_ID)]
    if not salt_first:
        queries.reverse()
    for name, expected in queries:
        assert loader.find_chebi_by_name(name, synonyms=synonyms) == expected
    assert loader.find_chebi_by_name("Tetramethylammonium chloride") == "CHEBI:7070"
    assert ingredient_name_target(PARENT_NAME) is None


@pytest.mark.parametrize("synonyms", [True, False])
def test_missing_salt_declaration_stays_unresolved(tmp_path, monkeypatch, synonyms):
    """A reviewed scope is a query route, not permission to manufacture a target."""
    loader = _load_selected(tmp_path, monkeypatch, salt=False)
    assert loader.find_chebi_by_name(SALT_NAME, synonyms=synonyms) is None
    assert loader.find_chebi_by_name(PARENT_NAME, synonyms=synonyms) == PARENT_ID


@pytest.mark.parametrize("salt", [True, False])
def test_wrong_historical_alias_cannot_replace_approved_scope(tmp_path, monkeypatch, salt):
    """A stale parent alias cannot win or invent a registry relationship."""
    loader = _load_selected(tmp_path, monkeypatch, salt=salt, wrong_alias=True)
    for synonyms in (True, False):
        assert loader.find_chebi_by_name(SALT_NAME, synonyms=synonyms) == ("CHEBI:7070" if salt else None)
        assert loader.find_chebi_by_name(PARENT_NAME, synonyms=synonyms) == PARENT_ID
    assert loader.find_chebi_by_xref("cas:75-57-0") is None
    assert loader.find_chebi_by_name("75-57-0") is None
    assert ingredient_cas_annotations("CHEBI:7070") == []


def test_candidate_cycles_preserve_the_same_finite_runtime_route(inputs, monkeypatch):
    """The real tiny conservative refresh retains scope semantics and is byte-stable."""
    native = json.loads(FIXTURE.read_text())["native_projection"]
    metadata = _metadata()
    metadata["curie_map"]["kgmicrobe.compound"] = "https://w3id.org/kg-microbe/compound/"
    rows = [
        *refresh_tests.refresh._rows(inputs["baseline"]),
        _row("kgm.name:parent", PARENT_ID, PARENT_NAME, name=PARENT_NAME, comment="canonical_name"),
        _row("kgm.name:wrong_old_alias", PARENT_ID, PARENT_NAME, name=SALT_NAME, comment="synonym"),
        _row("kgm.name:salt", native["id"], native["name"], name=native["name"], comment="canonical_name"),
    ]
    _table(inputs["baseline"], FIELDS, rows, metadata)
    before = inputs["baseline"].read_bytes()
    first = refresh_tests.refresh.build_conservative_candidate(**inputs)
    second = refresh_tests.refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert inputs["baseline"].read_bytes() == before
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    loader = runtime.ChemicalMappingLoader(second.candidate_path)
    assert loader.find_chebi_by_name(SALT_NAME) == native["id"]
    assert loader.find_chebi_by_name(PARENT_NAME) == PARENT_ID
    assert loader.find_chebi_by_name("Tetramethyl ammonium bromide") is None
    assert loader.find_chebi_by_name(SALT_NAME + " monohydrate", fuzzy_hydrate=True) is None
    assert loader.find_chebi_by_xref("cas:75-57-0") is None


@pytest.mark.parametrize(
    "name",
    [
        "Tetramethyl ammonium bromide",
        "Tetramethyl ammonium hydroxide",
        "Tetramethyl ammonium chloride monohydrate",
        "Trimethyl ammonium chloride",
        "Tetra methyl ammonium chloride",
    ],
)
def test_scope_does_not_guess_other_counterions_hydrates_or_spellings(tmp_path, monkeypatch, name):
    """No substring match, generic space deletion, or parent-to-salt inference is added."""
    loader = _load_selected(tmp_path, monkeypatch)
    assert ingredient_name_target(name) is None
    assert loader.find_chebi_by_name(name, fuzzy_hydrate=True, fuzzy_stereochemistry=True) is None


def test_actual_occurrences_preserve_raw_record_position_and_quantities(tmp_path, monkeypatch):
    """Change the supported salt target only; do not insert public CAS metadata."""
    evidence = json.loads(FIXTURE.read_text())
    loader = _load_selected(tmp_path, monkeypatch)
    recipes = {}
    for occurrence in evidence["occurrences"]:
        # Only selected raw records are copied from the source. Padding keeps
        # their positions and is explicitly synthetic, not invented ingredients.
        padding = [{"instruction": "Synthetic position padding"}] * occurrence["array_index"]
        recipes[occurrence["solution_id"]] = {"recipe": padding + [occurrence["raw"]]}
    transform = _resolver(recipes)
    transform.chemical_loader = loader
    for occurrence in evidence["occurrences"]:
        records = transform.get_solution_recipe_occurrences(occurrence["solution_id"])
        assert len(records) == 1
        actual, raw = records[0], occurrence["raw"]
        assert actual["id"] == occurrence["expected_target"]
        assert actual["source_assertion_id"] == (
            f"mediadive.solution:{occurrence['solution_id']}#recipe/{occurrence['array_index'] + 1}"
        )
        assert json.loads(actual["source_record"]) == raw
        assert actual["name"] == raw["compound"]
        for column in ("amount", "unit", "g_l", "mmol_l"):
            assert actual[column] == raw.get(column)
        assert not any("cas" in field.lower() for field in json.loads(actual["source_record"]))
    assert transform.solutions_data == recipes
