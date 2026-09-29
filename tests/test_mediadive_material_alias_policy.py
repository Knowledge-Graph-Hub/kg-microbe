"""Keep eight reviewed material/molecule holds finite across existing routes (#1262)."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    AMOUNT_COLUMN,
    CHEBI_KEY,
    GRAMS_PER_LITER_COLUMN,
    ID_COLUMN,
    MEDIADIVE_INGREDIENT_PREFIX,
    MEDIADIVE_SOLUTION_PREFIX,
    MMOL_PER_LITER_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
    SYNONYM_COLUMN,
    UNIT_COLUMN,
)
from kg_microbe.utils import chemical_mapping_utils as mapping
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed, ingredient_xref_allowed
from tests.test_chemical_mapping_utils import reset_cache as reset_cache_fixture
from tests.test_consolidate_chemical_mappings import _load_module
from tests.test_mediadive_recipe_occurrences import _resolver
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _row, _table

reset_cache = reset_cache_fixture

# These are the eight explicitly reviewed name/target pairs, not replacement
# identities. Additional native declarations are bound to the immutable fixture.
PAIRS = (
    ("CHEBI:1387", "3,4-dihydroxyphenylethyleneglycol", ("SL10", "SL-10", "sl_10")),
    (
        "CHEBI:1784",
        "biphenyl-4-amine",
        (
            "Trace vitamins (see Medium No. 197)",
            "Trace vitamin (see Medium No.197)",
            "Trace vitamins (See Medium No.197)",
            "Trace vitamins* (see Medium No. 197)",
            "Trace vitamins(see Medium No.197)",
        ),
    ),
    ("CHEBI:748", "12alpha-Hydroxyamoorstatin", ("Mueller-Hinton broth", "Mueller_Hinton_broth")),
    (
        "CHEBI:2216",
        "6-Methylpenicillin",
        ("Difco Marine Broth 2216", "Difco marine broth (Difco2216)", "Difco marine broth (Difco 2216)"),
    ),
    ("CHEBI:1881", "4-Hydroxypheoxyacetate", ("Malted wheat meal", "malted_wheat_meal")),
    ("CHEBI:1895", "4-methylbenzyl alcohol", ("K2HSO4", "k2hso4")),
    (
        "CHEBI:1941",
        "4-(trimethylammonio)butanoic acid",
        ("Leibovitz's L-15 medium", "Leibovitz’s L-15 medium", "Leibovitzs_L_15_medium"),
    ),
    ("CHEBI:88", "(S)-(-)-citronellol", ("Selenite-tungstate solution", "Selenite-Tungstate Solution:")),
)
ALIASES = [(target, alias) for target, _, aliases in PAIRS for alias in aliases]
INDEPENDENT = "mediadive.ingredient:synthetic-independent-control"
FIXTURE = Path(__file__).parent / "resources/mediadive/material_aliases_1262.json"
CATALOGUE = Path(__file__).parents[1] / "mappings/mediadive_material_grounding_review.json"


def _saved():
    """Read the immutable full native/source/mapping excerpt, never current production output."""
    payload = FIXTURE.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "e6db6174173a12101875104c33478f1868f4454ddd296db8e46b47ab6119f126"
    return json.loads(payload)


def _catalogue():
    """Read the reviewed finite source-name list without inventing new aliases."""
    return json.loads(CATALOGUE.read_text())


def _native_metadata(rows):
    """Supply test-only CURIE bases for the unchanged excerpt's existing namespaces."""
    metadata = _metadata()
    for row in rows:
        for field in ("subject_id", "object_id", "object_source"):
            prefix = row[field].split(":", 1)[0]
            metadata["curie_map"].setdefault(prefix, "https://example.org/" + prefix + "/")
    return metadata


def _rows():
    """Build only tiny synthetic claims while preserving the reviewed pair spellings."""
    native, withheld = [], []
    for index, (target, label, aliases) in enumerate(PAIRS):
        native.append(_row(f"kgm.name:native-{index}", target, label, name=label, comment="canonical_name"))
        native.append(_row(target, target, label, name=label, comment="attribute_carrier"))
        for position, alias in enumerate(aliases):
            withheld.append(
                _row(
                    f"kgm.name:material-{index}-{position}",
                    target,
                    label,
                    name=alias,
                    comment="synonym",
                    predicate="skos:closeMatch",
                )
            )
    return native, withheld


@pytest.mark.parametrize("target,alias", ALIASES)
@pytest.mark.parametrize("variant", ["original", "uppercase", "outer_space", "separators"])
def test_only_reviewed_material_target_is_held(target, alias, variant):
    """Existing normalization forms reject a pair, never every target of a name."""
    query = {
        "original": alias,
        "uppercase": alias.upper(),
        "outer_space": "  " + alias + "  ",
        "separators": alias.replace(" ", "_"),
    }[variant]
    assert not ingredient_mapping_allowed(query, target)
    assert not ingredient_mapping_allowed(query, target.lower())
    assert ingredient_mapping_allowed(query, INDEPENDENT)
    for other, _, _ in PAIRS:
        if other != target:
            assert ingredient_mapping_allowed(query, other)


@pytest.mark.parametrize("target,label,aliases", PAIRS)
def test_authority_names_identifiers_and_unreviewed_extended_names_remain_allowed(target, label, aliases):
    """Valid native chemicals and differently qualified material names are not globally banned."""
    for name in (label, target, target.lower(), aliases[0] + " independently qualified control"):
        assert ingredient_mapping_allowed(name, target)
    assert ingredient_xref_allowed(target, target)
    resolver = _resolver({})
    resolver.compound_mappings = {target.lower(): target, label.lower(): target}
    assert resolver.standardize_compound_id("fixture", target) == target
    assert resolver.standardize_compound_id("fixture", label) == target


@pytest.mark.parametrize("synonyms", [False, True])
@pytest.mark.parametrize("stale_route", ["canonical_name", "synonym"])
def test_cold_actual_reader_rejects_stale_aliases_but_keeps_native_declarations(tmp_path, synonyms, stale_route):
    """Use the actual tiny SSSOM reader in both modes, not a mocked name-index oracle."""
    native, aliases = _rows()
    for row in aliases:
        row["comment"] = stale_route
    path = tmp_path / "tiny.sssom.tsv"
    _table(path, FIELDS, [*native, *aliases], _metadata())
    loader = mapping.ChemicalMappingLoader(path)
    for target, label, names in PAIRS:
        assert loader.find_chebi_by_name(label, synonyms=synonyms) == target
        assert loader.get_canonical_name(target) == label
        for name in names:
            assert loader.find_chebi_by_name(name, synonyms=synonyms) is None


@pytest.mark.parametrize("target,label,aliases", PAIRS)
@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_actual_compound_fallbacks_and_nested_solutions_keep_source_identity(target, label, aliases, route):
    """A stale route cannot restore the false pair or collapse distinct solution IDs."""
    name = aliases[0]
    raw = {"compound": name, "compound_id": 41, "amount": 0, "unit": "g", "g_l": 0, "mmol_l": None}
    nested = [
        {"solution": name, "solution_id": value, "amount": value, "unit": "ml", "attribute": False}
        for value in (17, 18)
    ]
    recipes = {"1": {"recipe": [raw, *nested, dict(raw)]}}
    resolver = _resolver(recipes)
    resolver.chebi_labels = {target: label}
    if route == "unified":
        resolver.chemical_loader.find_chebi_by_name = lambda query: target
    elif route == "legacy":
        resolver.compound_mappings = {name.lower(): target}
    else:
        resolver.compounds_data = {"41": {"compound": name, CHEBI_KEY: target.split(":")[1]}}
    actual = resolver.get_solution_recipe_occurrences("1")
    assert [item[ID_COLUMN] for item in actual] == [
        MEDIADIVE_INGREDIENT_PREFIX + "41",
        MEDIADIVE_SOLUTION_PREFIX + "17",
        MEDIADIVE_SOLUTION_PREFIX + "18",
        MEDIADIVE_INGREDIENT_PREFIX + "41",
    ]
    assert [json.loads(item[SOURCE_RECORD_COLUMN]) for item in actual] == recipes["1"]["recipe"]
    assert [item[SOURCE_ASSERTION_ID_COLUMN] for item in actual] == [
        MEDIADIVE_SOLUTION_PREFIX + f"1#recipe/{position}" for position in range(1, 5)
    ]
    assert actual[0][AMOUNT_COLUMN] == actual[0][GRAMS_PER_LITER_COLUMN] == 0
    assert actual[0][MMOL_PER_LITER_COLUMN] is None
    assert resolver.solutions_data == recipes


@pytest.mark.parametrize("target,label,aliases", PAIRS)
def test_rejected_unified_candidate_does_not_hide_independent_legacy_route(target, label, aliases):
    """Synthetic positive evidence proves the hold is not an unconditional local-node guard."""
    name = aliases[0]
    resolver = _resolver({"1": {"recipe": [{"solution": name, "solution_id": 17}]}})
    resolver.chemical_loader.find_chebi_by_name = lambda query: target
    resolver.compound_mappings = {name.lower(): INDEPENDENT}
    assert resolver.standardize_compound_id("41", name) == INDEPENDENT
    assert resolver.get_solution_recipe_occurrences("1")[0][ID_COLUMN] == INDEPENDENT


@pytest.mark.parametrize("target,label,aliases", PAIRS)
def test_cold_reader_can_select_explicit_independent_candidate(tmp_path, target, label, aliases):
    """A separately supplied synthetic candidate survives both reader and producer policy checks."""
    name = aliases[0]
    rows = [
        _row("kgm.name:native", target, label, name=label, comment="canonical_name"),
        _row("kgm.name:stale", target, label, name=name, comment="synonym", predicate="skos:closeMatch"),
        _row("kgm.name:independent", INDEPENDENT, name, name=name, comment="canonical_name"),
    ]
    path = tmp_path / "independent.tsv"
    _table(path, FIELDS, rows, _native_metadata(rows))
    loader = mapping.ChemicalMappingLoader(path)
    assert loader.find_chebi_by_name(name) == INDEPENDENT
    assert loader.find_chebi_by_name(name, synonyms=False) == INDEPENDENT
    resolver = _resolver({"1": {"recipe": [{"solution": name, "solution_id": 17}]}})
    resolver.chemical_loader = loader
    assert resolver.standardize_compound_id("41", name) == INDEPENDENT
    assert resolver.get_solution_recipe_occurrences("1")[0][ID_COLUMN] == INDEPENDENT


def test_native_identity_writer_removes_only_full_reviewed_claims_and_is_stable(tmp_path):
    """The actual writer preserves every retained byte/order and duplicate weak assertion."""
    native, withheld = _rows()
    weak = [dict(row, predicate_id="skos:broadMatch") for row in withheld]
    retained = [*native, *weak, weak[0]]
    rows = [*native, *withheld, *weak, weak[0]]
    source, first, second = (tmp_path / name for name in ("source.tsv", "first.tsv.gz", "second.tsv.gz"))
    _table(source, FIELDS, rows, _metadata())
    original = source.read_bytes()
    original_lines = [line for line in original.splitlines(keepends=True) if not line.startswith(b"#")]
    removed = {tuple(row[field] for field in FIELDS) for row in withheld}
    expected = [original_lines[0]] + [
        line
        for line, row in zip(original_lines[1:], rows, strict=True)
        if tuple(row[field] for field in FIELDS) not in removed
    ]
    writer = _load_module()
    assert writer.refresh_identity_policy(source, first) == {
        "rows_read": len(rows),
        "rows_removed": len(withheld),
        "rows_relabelled": 0,
    }
    assert writer.refresh_identity_policy(first, second) == {
        "rows_read": len(retained),
        "rows_removed": 0,
        "rows_relabelled": 0,
    }
    with gzip.open(first, "rb") as stream:
        actual = [line for line in stream if not line.startswith(b"#")]
    assert actual == expected
    assert Counter(actual[1:]) == Counter(expected[1:])
    assert first.read_bytes() == second.read_bytes()
    assert source.read_bytes() == original


def test_complete_saved_name_cohort_and_native_synonyms_have_separate_scope():
    """All saved aliases are held, but every saved native name/synonym remains admissible."""
    fixture, catalogue = _saved(), _catalogue()
    assert {item["target_id"] for item in catalogue["dispositions"]} == {target for target, _, _ in PAIRS}
    assert len(catalogue["historical_claims"]) == 13
    for disposition in catalogue["dispositions"]:
        target = disposition["target_id"]
        assert disposition["authority_label"] == fixture["native_nodes"][target][NAME_COLUMN]
        for name in disposition["source_names"]:
            assert not ingredient_mapping_allowed(name, target)
            assert ingredient_mapping_allowed(name, INDEPENDENT)
    for target, node in fixture["native_nodes"].items():
        for name in [node[NAME_COLUMN], *node[SYNONYM_COLUMN].split("|")]:
            if name:
                assert ingredient_mapping_allowed(name, target)


@pytest.mark.parametrize("synonyms", [False, True])
def test_actual_reader_over_original133_rows_preserves_all_native_controls(tmp_path, synonyms):
    """Cold read the saved complete rows, retaining molecular names and supported controls."""
    fixture = _saved()
    rows = [item["row"] for item in fixture["unified_target_rows"]]
    assert len(rows) == 133
    path = tmp_path / "native-excerpt.tsv"
    _table(path, FIELDS, rows, _native_metadata(rows))
    loader = mapping.ChemicalMappingLoader(path)
    for target, node in fixture["native_nodes"].items():
        assert loader.find_chebi_by_name(node[NAME_COLUMN], synonyms=synonyms) == target
        assert loader.get_canonical_name(target) == node[NAME_COLUMN]
        if synonyms:
            for name in node[SYNONYM_COLUMN].split("|"):
                if name:
                    assert loader.find_chebi_by_name(name, synonyms=True) == target
    for disposition in _catalogue()["dispositions"]:
        for name in disposition["source_names"]:
            assert loader.find_chebi_by_name(name, synonyms=synonyms) is None


def test_original133_row_identity_refresh_removes_exact13_and_preserves_full120(tmp_path):
    """Full immutable original rows, metadata columns and order survive both native writer cycles."""
    fixture, catalogue = _saved(), _catalogue()
    rows = [item["row"] for item in fixture["unified_target_rows"]]
    held = Counter(tuple(item["row"][field] for field in FIELDS) for item in catalogue["historical_claims"])
    assert sum(held.values()) == 13
    source, first, second = (tmp_path / name for name in ("source.tsv", "first.tsv.gz", "second.tsv.gz"))
    _table(source, FIELDS, rows, _native_metadata(rows))
    original = source.read_bytes()
    lines = [line for line in original.splitlines(keepends=True) if not line.startswith(b"#")]
    expected = [lines[0]]
    for line, row in zip(lines[1:], rows, strict=True):
        key = tuple(row[field] for field in FIELDS)
        if held[key]:
            held[key] -= 1
        else:
            expected.append(line)
    assert not any(held.values()) and len(expected) == 121
    writer = _load_module()
    assert writer.refresh_identity_policy(source, first) == {"rows_read": 133, "rows_removed": 13, "rows_relabelled": 0}
    assert writer.refresh_identity_policy(first, second) == {"rows_read": 120, "rows_removed": 0, "rows_relabelled": 0}
    with gzip.open(first, "rb") as stream:
        assert [line for line in stream if not line.startswith(b"#")] == expected
    assert first.read_bytes() == second.read_bytes() and source.read_bytes() == original


def test_all_saved289_occurrences_preserve_distinct_raw_local_identities():
    """Actual source ordinals/quantities and seven nested solution IDs survive finite rejection."""
    fixture = _saved()
    recipes = {}
    target_by_name = {}
    for item in fixture["occurrences"]:
        owner, ordinal = item[SOURCE_ASSERTION_ID_COLUMN].split("#recipe/")
        owner = owner.removeprefix(MEDIADIVE_SOLUTION_PREFIX)
        raw = item["raw"]
        recipe = recipes.setdefault(owner, {"recipe": []})["recipe"]
        while len(recipe) < int(ordinal):
            recipe.append({"instruction": "synthetic noningredient ordinal placeholder"})
        recipe[int(ordinal) - 1] = raw
        name = raw.get("compound", raw.get("solution"))
        target_by_name[name] = item["edge"][OBJECT_COLUMN]
    resolver = _resolver(recipes)
    resolver.chemical_loader.find_chebi_by_name = target_by_name.get
    actual = {
        item[SOURCE_ASSERTION_ID_COLUMN]: item
        for owner in recipes
        for item in resolver.get_solution_recipe_occurrences(owner)
    }
    assert len(actual) == len(fixture["occurrences"]) == 289
    nested = set()
    for item in fixture["occurrences"]:
        resolved = actual[item[SOURCE_ASSERTION_ID_COLUMN]]
        assert resolved[ID_COLUMN] == item["local_identity"]
        assert json.loads(resolved[SOURCE_RECORD_COLUMN]) == item["raw"]
        for field in (AMOUNT_COLUMN, UNIT_COLUMN, GRAMS_PER_LITER_COLUMN, MMOL_PER_LITER_COLUMN):
            assert resolved[field] == item["raw"].get(field)
        if resolved[ID_COLUMN].startswith(MEDIADIVE_SOLUTION_PREFIX):
            nested.add(resolved[ID_COLUMN])
    assert nested == {MEDIADIVE_SOLUTION_PREFIX + key for key in fixture["nested_solution_records"]}
    assert resolver.solutions_data == recipes
