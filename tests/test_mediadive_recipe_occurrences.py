"""Keep individual MediaDive recipe assertions and quantities through KGX (#1171)."""

import ast
import copy
import csv
import hashlib
import io
import json
import sqlite3
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.source_finalization import graph_rows

RESOURCE = Path(__file__).parent / "resources"


def _loader():
    """No guessed external identity is needed to test source-occurrence preservation."""
    return SimpleNamespace(
        find_chebi_by_name=lambda name: None,
        get_canonical_name=lambda identifier: "",
        get_node_enrichment=lambda identifier: {"xref": "", "synonym": ""},
        get_parents=lambda identifier: [],
        get_category=lambda identifier: "",
    )


def _resolver(recipes):
    """Build an offline resolver over copied raw source records."""
    value = mod.MediaDiveTransform.__new__(mod.MediaDiveTransform)
    value.using_bulk_data = True
    value.solutions_data = copy.deepcopy(recipes)
    value.compounds_data = {}
    value.compound_mappings = {}
    value.chebi_labels = {}
    value.chemical_loader = _loader()
    value.translation_table = str.maketrans(mod.TRANSLATION_TABLE_FOR_LABELS)
    value.api_calls_avoided = value.api_calls_made = 0
    return value


def test_raw_nickel_occurrences_keep_all_values_and_source_positions():
    """The observed 284 mg and 166 mg rows must not overwrite one another."""
    raw = json.loads((RESOURCE / "mediadive_solution_5787.json").read_text())
    transform = _resolver({"5787": raw})
    actual = transform.get_solution_recipe_occurrences("5787")
    assert len(actual) == len(raw["recipe"]) == 11
    assert actual == transform.get_solution_recipe_occurrences("5787")
    assert transform.solutions_data["5787"] == raw
    for position, (item, original) in enumerate(zip(actual, raw["recipe"], strict=True), 1):
        assert item["source_assertion_id"] == f"mediadive.solution:5787#recipe/{position}"
        assert json.loads(item["source_record"]) == original
        assert item["id"] == f"mediadive.ingredient:{original['compound_id']}"
        for column in ("amount", "unit", "g_l", "mmol_l"):
            assert item[column] == original.get(column)
    nickel = [item for item in actual if item["id"] == "mediadive.ingredient:981"]
    assert [(item["amount"], item["unit"], item["g_l"], item["mmol_l"]) for item in nickel] == [
        (284, "mg", 0.284, 2.19138),
        (166, "mg", 0.166, 1.28087),
    ]
    with pytest.raises(ValueError, match="duplicate recipe display name.*get_solution_recipe_occurrences"):
        transform.get_compounds_of_solution("5787")


def _collision_recipe():
    """Synthetic rows distinguish identity, name cleanup, kind and raw-list order."""
    return [
        {"compound": "Same(name)", "compound_id": 1, "amount": 2, "unit": "g", "recipe_order": 5},
        {"compound": "Samename", "compound_id": 2, "amount": 3, "unit": "g", "recipe_order": 5},
        {"solution": "Samename", "solution_id": 3, "amount": 4, "unit": "ml"},
        {"instruction": "software-only noningredient entry"},
        {"compound": "Samename", "compound_id": 1, "amount": 0, "unit": "g", "g_l": 0, "mmol_l": 0},
    ]


def test_same_display_name_never_controls_identity_or_source_order():
    """Raw positions distinguish nested solutions, repeated order values and skipped rows."""
    raw = _collision_recipe()
    transform = _resolver({"1": {"recipe": raw}})
    actual = transform.get_solution_recipe_occurrences("1")
    assert [row["id"] for row in actual] == [
        "mediadive.ingredient:1",
        "mediadive.ingredient:2",
        "mediadive.solution:3",
        "mediadive.ingredient:1",
    ]
    assert {row["name"] for row in actual} == {"Samename"}
    assert [row["source_assertion_id"] for row in actual] == [
        f"mediadive.solution:1#recipe/{position}" for position in (1, 2, 3, 5)
    ]
    assert [json.loads(row["source_record"]) for row in actual] == [raw[index] for index in (0, 1, 2, 4)]
    assert actual[-1]["amount"] == actual[-1]["g_l"] == actual[-1]["mmol_l"] == 0
    with pytest.raises(ValueError, match="duplicate recipe display name"):
        transform.get_compounds_of_solution("1")
    assert transform.solutions_data == {"1": {"recipe": raw}}


def test_unique_name_compatibility_view_retains_the_original_shape():
    """Existing callers with unique display labels still receive the same mapping."""
    transform = _resolver({"1": {"recipe": [{"compound": "Test", "compound_id": 7, "amount": 0, "unit": "g"}]}})
    assert transform.get_compounds_of_solution("1") == {
        "Test": {"id": "mediadive.ingredient:7", "amount": 0, "unit": "g", "g_l": None, "mmol_l": None}
    }


def _run_transform(tmp_path, monkeypatch, recipes):
    """Run the real writer against small source recipes, without external services."""
    raw = tmp_path / "raw"
    raw.mkdir()
    # Reuse immutable native closure evidence for the transform's existing
    # solution -> CHEBI:60004 assertion; do not mock strict finalization.
    authority_path = RESOURCE / "ingredient_bundle/native/legacy-closure-statements.json"
    authority_origin = json.loads(authority_path.with_name("legacy-closure-origin.json").read_text())
    assert hashlib.sha256(authority_path.read_bytes()).hexdigest() == authority_origin["fixture_sha256"]
    authority = json.loads(authority_path.read_text())
    with sqlite3.connect(raw / "chebi.db") as connection:
        connection.execute("CREATE TABLE statements(stanza,subject,predicate,object,value,datatype,language,graph)")
        connection.executemany("INSERT INTO statements VALUES (?,?,?,?,?,?,?,?)", authority["statements"])
        connection.execute("CREATE INDEX subject_idx ON statements(subject)")
    medium = {"id": 1, "name": "Occurrence fixture", "complex_medium": False}
    for field in (
        mod.MEDIADIVE_SOURCE_COLUMN,
        mod.MEDIADIVE_LINK_COLUMN,
        mod.MEDIADIVE_MIN_PH_COLUMN,
        mod.MEDIADIVE_MAX_PH_COLUMN,
        mod.MEDIADIVE_REF_COLUMN,
        mod.MEDIADIVE_DESC_COLUMN,
    ):
        medium[field] = ""
    (raw / "mediadive.json").write_text(json.dumps({"data": [medium]}))
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", RESOURCE / "provenance_serialization")
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)
    with (
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(mod.MediaDiveTransform, "_load_micromediaparam_mappings"),
        mock.patch.object(mod.MediaDiveTransform, "_load_bulk_data"),
        mock.patch.object(mod, "ChemicalMappingLoader", return_value=_loader()),
    ):
        value = mod.MediaDiveTransform(raw, tmp_path / "transformed")
    value.using_bulk_data = True
    value.solutions_data = copy.deepcopy(recipes)

    def response(path, endpoint, directory):
        """Supply only the fixture medium's own solutions; no strain growth is needed."""
        return (
            {}
            if endpoint.startswith(mod.MEDIUM_STRAINS)
            else {"solutions": [{"id": int(identifier), "name": "Fixture solution"} for identifier in recipes]}
        )

    monkeypatch.setattr(value, "get_json_object", response)

    def reject_legacy_view(identifier):
        """Production must never request a dictionary that cannot represent repetitions."""
        raise AssertionError("lossy compatibility view used by production emitter")

    monkeypatch.setattr(value, "get_compounds_of_solution", reject_legacy_view)
    value.run(show_status=False)
    return value


@pytest.mark.usefixtures("local_source_schema")
def test_actual_emission_finalization_and_archive_preserve_equal_occurrences(tmp_path, monkeypatch):
    """Even identical targets and quantities remain distinct by raw occurrence position."""
    raw = json.loads((RESOURCE / "mediadive_solution_5787.json").read_text())
    repeated = {"compound": "Repeated", "compound_id": 20, "amount": 1, "unit": "g", "g_l": 2, "mmol_l": 3}
    alternatives = json.loads((RESOURCE / "mediadive_recipe_alternatives.json").read_text())["excerpts"]
    recipes = {"5787": raw, "1": {"recipe": [repeated, copy.deepcopy(repeated)]}, "2": {"recipe": _collision_recipe()}}
    recipes.update({identifier: {"recipe": items} for identifier, items in alternatives.items()})
    transform = _run_transform(tmp_path, monkeypatch, recipes)
    # The producer's pandas deduplication writes conventional CSV quoting;
    # source finalization below is the boundary to literal canonical TSVs.
    with transform.output_edge_file.open() as stream:
        before = [row for row in csv.DictReader(stream, delimiter="\t") if row.get("source_assertion_id")]
    assert len(before) == 21
    assert len({row["source_assertion_id"] for row in before}) == 21
    declared = {row["id"] for row in graph_rows(transform.output_node_file)}
    assert {"mediadive.ingredient:1", "mediadive.ingredient:2", "mediadive.solution:3"} <= declared
    with (tmp_path / "mediadive.tsv").open() as stream:
        intermediate = next(csv.DictReader(stream, delimiter="\t"))
    assert len(ast.literal_eval(intermediate[mod.INGREDIENTS_COLUMN])) == 21
    for edge in before:
        original = json.loads(edge["source_record"])
        assert float(edge["value"]) == original["amount"]
        assert edge["unit"] == original.get("unit", "")
        for column in ("g_l", "mmol_l"):
            assert float(edge[column]) == original[column] if column in original else edge[column] == ""
    transform.finalize(fresh_run=True)
    finalized = [row for row in graph_rows(transform.output_edge_file) if row.get("source_assertion_id")]
    assert {row["source_assertion_id"]: row["source_record"] for row in finalized} == {
        row["source_assertion_id"]: row["source_record"] for row in before
    }
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.merge_kg import merge

    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(tmp_path)},
                "merged_graph": {
                    "source": {
                        "mediadive": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(transform.output_node_file), str(transform.output_edge_file)],
                            }
                        }
                    },
                    "destination": {"tsv": {"format": "tsv", "compression": "tar.gz", "filename": "occurrences"}},
                },
            }
        )
    )
    merge(str(config), processes=1)
    with tarfile.open(tmp_path / "occurrences.tar.gz") as archive:
        with archive.extractfile("occurrences_edges.tsv") as handle:
            result = [
                row
                for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t")
                if row.get("source_assertion_id")
            ]
    columns = ("subject", "object", "value", "unit", "source_record", "g_l", "mmol_l")
    assert {row["source_assertion_id"]: tuple(row[column] for column in columns) for row in result} == {
        row["source_assertion_id"]: tuple(row[column] for column in columns) for row in finalized
    }
    assert len([row for row in result if row["subject"] == "mediadive.solution:1"]) == 2
    for identifier, items in alternatives.items():
        actual = [row for row in result if row["subject"] == f"mediadive.solution:{identifier}"]
        assert len(actual) == 2
        assert [
            json.loads(row["source_record"]) for row in sorted(actual, key=lambda row: row["source_assertion_id"])
        ] == items
    assert transform.solutions_data == recipes
