"""Raw GOLD discovery shares producer syntax without weakening native/admission readers (#1349)."""

import csv
import json

import pytest

from kg_microbe.transform_utils.gold.taxon_dispositions import gold_reference_requests
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.graph_schema import CANONICAL_NODE_HEADER
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    _producer_reference_rows,
    graph_rows,
)
from tests import test_gold_taxon_dispositions as gold_fixtures

gold_source = gold_fixtures.source

NODE_HEADER = ["id", "name", "category"]
NODE_ROW = ["gold:Go0039676", "Parser example", "biolink:NamedThing"]
EDGE_HEADER = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
EDGE_ROW = ["fixture:1", "biolink:related_to", "gold:Go0039676", "skos:related", "infores:test"]


def _write(path, header, rows, *, quoting=csv.QUOTE_NONE):
    """Write small parser perturbations, not new ontology or scientific evidence."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(
            stream,
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _request(path, *, nodes=False, raw=True, quoting=csv.QUOTE_NONE, own_gold=False):
    """Select the explicit raw adapter or untouched strict finalized/native default."""
    return gold_reference_requests(
        [path] if nodes else [],
        [] if nodes else [path],
        row_reader=_producer_reference_rows if raw else None,
        quoting=quoting,
        own_gold=own_gold,
    )


@pytest.mark.parametrize("column", ["subject", "object", "relation", "primary_knowledge_source"])
@pytest.mark.parametrize("blank", [None, "first", "last"])
def test_raw_duplicate_edge_columns_preserve_exact_requests(tmp_path, column, blank):
    """Discovery coalesces only identical or blank/nonblank complete-row cells."""
    values = [*EDGE_ROW, EDGE_ROW[EDGE_HEADER.index(column)]]
    if blank is not None:
        values[EDGE_HEADER.index(column) if blank == "first" else -1] = ""
    path = _write(tmp_path / "edges.tsv", [*EDGE_HEADER, column], [values])
    before = path.read_bytes()
    assert _request(path) == {"gold:Go0039676"}
    assert path.read_bytes() == before
    with pytest.raises(SourceFinalizationRequired, match="Invalid GOLD disposition input header"):
        _request(path, raw=False)


@pytest.mark.parametrize("column", ["id", "name"])
@pytest.mark.parametrize("blank", [None, "first", "last"])
def test_raw_duplicate_node_columns_preserve_exact_requests(tmp_path, column, blank):
    """Node request discovery uses the same full-row duplicate policy as edge discovery."""
    values = [*NODE_ROW, NODE_ROW[NODE_HEADER.index(column)]]
    if blank is not None:
        values[NODE_HEADER.index(column) if blank == "first" else -1] = ""
    path = _write(tmp_path / "nodes.tsv", [*NODE_HEADER, column], [values])
    assert _request(path, nodes=True) == {"gold:Go0039676"}
    with pytest.raises(SourceFinalizationRequired, match="Invalid GOLD disposition input header"):
        _request(path, nodes=True, raw=False)


@pytest.mark.parametrize("column", ["subject", "object", "relation", "primary_knowledge_source", "id", "name"])
def test_raw_conflicting_duplicate_fields_refuse_even_after_selected_row(tmp_path, column):
    """A found GOLD endpoint never short-circuits complete-row conflict checks."""
    nodes = column in NODE_HEADER
    header, row = (NODE_HEADER, NODE_ROW) if nodes else (EDGE_HEADER, EDGE_ROW)
    values = [*row, row[header.index(column)]]
    path = _write(tmp_path / "table.tsv", [*header, column], [values, [*row, "contradictory"]])
    with pytest.raises(SourceFinalizationRequired, match=f"Conflicting duplicate column {column}"):
        _request(path, nodes=nodes)


@pytest.mark.parametrize("nodes,missing", [(True, "id"), (True, "name"), (False, "subject"), (False, "object")])
@pytest.mark.parametrize("raw", [True, False])
def test_missing_required_header_fields_refuse_header_only_tables(tmp_path, nodes, missing, raw):
    """A truthful zero cohort still requires its selected structural header fields."""
    header = NODE_HEADER if nodes else EDGE_HEADER
    path = _write(tmp_path / "table.tsv", [field for field in header if field != missing], [])
    with pytest.raises(SourceFinalizationRequired, match="header|fields"):
        _request(path, nodes=nodes, raw=raw)


@pytest.mark.parametrize("nodes", [True, False])
@pytest.mark.parametrize("raw", [True, False])
def test_complete_header_only_tables_preserve_truthful_zero(tmp_path, nodes, raw):
    """Do not invent requests or require native GOLD for structurally valid empty inputs."""
    path = _write(tmp_path / "table.tsv", NODE_HEADER if nodes else EDGE_HEADER, [])
    assert _request(path, nodes=nodes, raw=raw) == set()


@pytest.mark.parametrize("nodes", [True, False])
@pytest.mark.parametrize("change", ["short", "long"])
@pytest.mark.parametrize("raw", [True, False])
def test_malformed_late_row_refuses_complete_scan(tmp_path, nodes, change, raw):
    """Both raw and strict readers reject width defects after a valid selected row."""
    header, row = (NODE_HEADER, NODE_ROW) if nodes else (EDGE_HEADER, EDGE_ROW)
    malformed = row[:-1] if change == "short" else [*row, "extra"]
    path = _write(tmp_path / "table.tsv", header, [row, malformed])
    with pytest.raises(SourceFinalizationRequired, match="[Mm]alformed"):
        _request(path, nodes=nodes, raw=raw)


@pytest.mark.parametrize("nodes", [True, False])
@pytest.mark.parametrize("location", ["header", "late"])
@pytest.mark.parametrize("quoting", [csv.QUOTE_NONE, csv.QUOTE_MINIMAL])
def test_nul_refuses_before_csv_in_both_raw_dialects(tmp_path, nodes, location, quoting):
    """Raw discovery preserves the ValueError-family NUL refusal across Python CSV versions."""
    header, row = (NODE_HEADER, NODE_ROW) if nodes else (EDGE_HEADER, EDGE_ROW)
    path = _write(tmp_path / "table.tsv", header, [row, row], quoting=quoting)
    data = path.read_bytes()
    path.write_bytes(data.replace(b"\t", b"\x00\t", 1) if location == "header" else data + b"\x00\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="NUL"):
        _request(path, nodes=nodes, quoting=quoting)
    assert path.read_bytes() == before


@pytest.mark.parametrize("quoting", [csv.QUOTE_NONE, csv.QUOTE_MINIMAL])
def test_raw_and_strict_requests_preserve_literal_dialect_and_own_gold_rules(tmp_path, quoting):
    """Retain exact ID-only scope and own-GOLD blank-name semantics without lexical inference."""
    nodes = _write(
        tmp_path / "nodes.tsv",
        [*NODE_HEADER, "xref"],
        [
            ["gold:Go0039676", 'Literal "quoted" name', "biolink:NamedThing", "gold:ignored_xref"],
            ["gold:Go0531699", "", "biolink:NamedThing", ""],
            ["gold.ecosystem:example", "Site", "biolink:NamedThing", ""],
        ],
        quoting=quoting,
    )
    edges = _write(
        tmp_path / "edges.tsv",
        EDGE_HEADER,
        [["gold:edge_only", *EDGE_ROW[1:]]],
        quoting=quoting,
    )
    for reader in (None, _producer_reference_rows):
        assert gold_reference_requests([nodes], [edges], quoting=quoting, row_reader=reader) == {
            "gold:Go0039676",
            "gold:Go0531699",
            "gold:edge_only",
        }
        assert gold_reference_requests([nodes], [edges], quoting=quoting, row_reader=reader, own_gold=True) == {
            "gold:Go0531699"
        }
    selected = list(_producer_reference_rows(nodes, ("id", "name"), quoting=quoting))
    assert selected[0]["row"]["name"] == 'Literal "quoted" name'


def test_actual_native_gold_consumer_finalization_keeps_duplicate_audit_and_proof(gold_source):
    """Compatibility parsing still requires the genuine exact native GOLD declaration contract."""
    gold_source.run()
    gold_source.finalize(fresh_run=True)
    consumer = Transform("fixture", gold_source.input_base_dir, gold_source.output_base_dir)
    ordinary = {"id": "fixture:1", "name": "One", "category": "biolink:NamedThing"}
    _write(consumer.output_node_file, CANONICAL_NODE_HEADER, [[ordinary.get(key, "") for key in CANONICAL_NODE_HEADER]])
    header = [*EDGE_HEADER, "primary_knowledge_source"]
    values = [*EDGE_ROW, "infores:test"]
    _write(consumer.output_edge_file, header, [values])
    report = consumer.finalize(fresh_run=True)
    assert report["gold_reference_declarations"]["requested_ids"] == ["gold:Go0039676"]
    proof_nodes = [row for row in graph_rows(consumer.output_node_file) if row["id"] == "gold:Go0039676"]
    assert len(proof_nodes) == 1
    native = next(row for row in graph_rows(gold_source.output_node_file) if row["id"] == "gold:Go0039676")
    assert {key: proof_nodes[0][key] for key in ("category", "name", "provided_by", "xref")} == {
        key: native[key] for key in ("category", "name", "provided_by", "xref")
    }
    audit = list(graph_rows(consumer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    original = json.loads(next(row["original_row_json"] for row in audit if row["file"] == "edges.tsv"))
    assert original == {"original_header": header, "original_values": values}
    assert next(graph_rows(consumer.output_edge_file))["primary_knowledge_source"] == "infores:test"
    assert Transform("fixture", gold_source.input_base_dir, gold_source.output_base_dir).finalize() == report
