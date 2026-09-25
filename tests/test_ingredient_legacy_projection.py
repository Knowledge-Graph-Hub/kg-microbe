"""Original legacy broader mappings survive real MediaDive emission and KGX merge."""

import csv
import hashlib
import json
import shutil
import sqlite3
from multiprocessing.pool import ThreadPool
from pathlib import Path
from unittest import mock

import pytest

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.source_finalization import graph_rows
from tests.test_ingredient_bundle import reset_lookup_cache as reset_lookup_cache
from tests.test_merge_source_freshness import merge_config, prepare_source, record_source

pytestmark = pytest.mark.usefixtures("local_source_schema")
RESOURCE = Path(__file__).parent / "resources/ingredient_bundle/native"
CHILD = "kgmicrobe.compound:2-oxobutyric_acid_sodium_salt"
PARENT = "CHEBI:16763"


def test_original_legacy_broad_mapping_survives_mediadive_and_merge(tmp_path, monkeypatch):
    """A test recipe selects an existing reviewed alignment; no subclass is inferred from it."""
    origin = json.loads((RESOURCE / "legacy-broad-origin.json").read_text())
    mappings = RESOURCE / "legacy-broad.sssom.tsv"
    assert hashlib.sha256(mappings.read_bytes()).hexdigest() == origin["fixture_sha256"]
    loader = ChemicalMappingLoader(mappings)
    assert loader.get_parents(CHILD) == [PARENT]
    assert loader.find_chebi_by_xref(CHILD) != PARENT
    ontology = prepare_source(tmp_path, "ontologies")
    bacdive = prepare_source(tmp_path, "bacdive")
    raw = tmp_path / "raw"
    statements = RESOURCE / "legacy-closure-statements.json"
    closure_origin = json.loads(statements.with_name("legacy-closure-origin.json").read_text())
    assert hashlib.sha256(statements.read_bytes()).hexdigest() == closure_origin["fixture_sha256"]
    payload = json.loads(statements.read_text())
    assert payload["columns"] == ["stanza", "subject", "predicate", "object", "value", "datatype", "language", "graph"]
    with sqlite3.connect(raw / "chebi.db") as connection:
        connection.execute("CREATE TABLE statements(stanza,subject,predicate,object,value,datatype,language,graph)")
        connection.executemany("INSERT INTO statements VALUES (?,?,?,?,?,?,?,?)", payload["statements"])
        connection.execute("CREATE INDEX subject_idx ON statements(subject)")
    for name in ("mediadive.json", "bacdive.tsv"):
        shutil.copyfile(Path(__file__).parent / "resources/provenance_serialization" / name, raw / name)
    medium = json.loads((raw / "mediadive.json").read_text())
    for row in medium["data"]:
        for field in (
            mod.MEDIADIVE_SOURCE_COLUMN,
            mod.MEDIADIVE_LINK_COLUMN,
            mod.MEDIADIVE_MIN_PH_COLUMN,
            mod.MEDIADIVE_MAX_PH_COLUMN,
            mod.MEDIADIVE_REF_COLUMN,
            mod.MEDIADIVE_DESC_COLUMN,
        ):
            row.setdefault(field, "")
    (raw / "mediadive.json").write_text(json.dumps(medium))
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", raw)
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)
    with (
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(mod.MediaDiveTransform, "_load_micromediaparam_mappings"),
        mock.patch.object(mod.MediaDiveTransform, "_load_bulk_data"),
        mock.patch.object(mod, "ChemicalMappingLoader", return_value=loader),
    ):
        source = mod.MediaDiveTransform(raw, tmp_path / "transformed")
    source.using_bulk_data = True

    def fixture_response(path, endpoint, directory):
        """Select a software-only occurrence of the unmodified broader source mapping."""
        return {} if endpoint.startswith(mod.MEDIUM_STRAINS) else {"solutions": [{"id": 1, "name": "Test solution"}]}

    monkeypatch.setattr(source, "get_json_object", fixture_response)
    monkeypatch.setattr(
        source,
        "get_compounds_of_solution",
        lambda value: {"2-oxobutyric acid sodium salt": {"id": CHILD, "amount": 1, "unit": "g/l"}},
    )
    source.run(show_status=False)
    before = [row for row in graph_rows(source.output_edge_file) if row["subject"] == CHILD and row["object"] == PARENT]
    assert len(before) == 1 and before[0]["predicate"] == "biolink:broad_match"
    source.finalize(fresh_run=True)
    record_source(source)
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    config = merge_config(tmp_path, [ontology, bacdive, source])
    merge_kg.load_and_merge(str(config), processes=1)
    with (tmp_path / "published/fixture_edges.tsv").open() as stream:
        edges = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    result = [row for row in edges if row["subject"] == CHILD and row["object"] == PARENT]
    assert len(result) == 1
    assert result[0]["predicate"] == "biolink:broad_match"
    assert result[0]["relation"] == "skos:broadMatch"
