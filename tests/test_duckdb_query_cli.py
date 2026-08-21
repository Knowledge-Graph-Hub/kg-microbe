"""Hermetic tests for DuckDB ingestion and the query-organism CLI."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
from click.testing import CliRunner

from kg_microbe.query_utils import duckdb_loader
from kg_microbe.query_utils.duckdb_loader import get_or_create_database
from kg_microbe.run import main

NODE_HEADER = "id\tcategory\tname\tsynonym\n"
EDGE_HEADER = "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"


def _write_graph(tmp_path: Path, newline: str = "\n") -> tuple[Path, Path]:
    nodes = tmp_path / "nodes.tsv"
    edges = tmp_path / "edges.tsv"
    node_rows = [
        "NCBITaxon:562\tbiolink:OrganismTaxon\tEscherichia coli\tE. coli",
        "METPO:1000699\tbiolink:PhenotypicQuality\tgram negative\t",
        "mediadive.medium:1\tMETPO:1004005\tTest medium\t",
    ]
    edge_rows = [
        "NCBITaxon:562\tbiolink:has_phenotype\tMETPO:1000699\tRO:0002200\tinfores:test",
        "NCBITaxon:562\tbiolink:located_in\tmediadive.medium:1\tMETPO:2000517\tinfores:test",
    ]
    nodes.write_bytes((NODE_HEADER.rstrip("\n") + newline + newline.join(node_rows) + newline).encode())
    edges.write_bytes((EDGE_HEADER.rstrip("\n") + newline + newline.join(edge_rows) + newline).encode())
    return nodes, edges


def test_direct_loader_handles_crlf_and_records_fingerprints(tmp_path: Path) -> None:
    """DuckDB-native parsing must not retain carriage returns in final columns."""
    nodes, edges = _write_graph(tmp_path, newline="\r\n")
    db_path = tmp_path / "graph.duckdb"
    conn = get_or_create_database(nodes, edges, db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
        sources = conn.execute(
            "SELECT source_kind, source_path FROM kg_microbe_source_metadata ORDER BY source_kind"
        ).fetchall()
        assert sources == [("edges", str(edges.resolve())), ("nodes", str(nodes.resolve()))]
        assert conn.execute("SELECT MAX(primary_knowledge_source) FROM edges").fetchone()[0] == "infores:test"
    finally:
        conn.close()


def test_changed_source_rebuilds_database(tmp_path: Path) -> None:
    """An existing database must not hide newer TSV content."""
    nodes, edges = _write_graph(tmp_path)
    db_path = tmp_path / "graph.duckdb"
    get_or_create_database(nodes, edges, db_path).close()
    with edges.open("a", encoding="utf-8") as handle:
        handle.write("NCBITaxon:562\tbiolink:related_to\tNCBITaxon:562\tRO:0002321\tinfores:test\n")

    conn = get_or_create_database(nodes, edges, db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 3
    finally:
        conn.close()


def test_failed_rebuild_preserves_last_valid_database(tmp_path: Path, monkeypatch) -> None:
    """A failed force reload cannot replace the last usable database."""
    nodes, edges = _write_graph(tmp_path)
    db_path = tmp_path / "graph.duckdb"
    get_or_create_database(nodes, edges, db_path).close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    def fail_edges(conn, table_name, path, columns):
        if table_name == "edges":
            raise ValueError("synthetic ingest failure")
        return original_load_table(conn, table_name, path, columns)

    original_load_table = duckdb_loader._load_table
    monkeypatch.setattr(duckdb_loader, "_load_table", fail_edges)
    try:
        get_or_create_database(nodes, edges, db_path, force_reload=True)
    except ValueError as error:
        assert "synthetic ingest failure" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("force reload unexpectedly succeeded")

    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    conn = duckdb.connect(str(db_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
    finally:
        conn.close()


def test_query_organism_failure_is_nonzero(tmp_path: Path) -> None:
    """Missing inputs are operational failures, not successful empty queries."""
    result = CliRunner().invoke(
        main,
        [
            "query-organism",
            "Escherichia coli",
            "--nodes-path",
            str(tmp_path / "missing-nodes.tsv"),
            "--edges-path",
            str(tmp_path / "missing-edges.tsv"),
        ],
    )
    assert result.exit_code != 0
    assert "Error loading database" in result.output


def test_query_organism_success_writes_report(tmp_path: Path) -> None:
    """A successful query exits zero and creates the requested artifact."""
    nodes, edges = _write_graph(tmp_path)
    report = tmp_path / "report.md"
    result = CliRunner().invoke(
        main,
        [
            "query-organism",
            "Escherichia coli",
            "--nodes-path",
            str(nodes),
            "--edges-path",
            str(edges),
            "--db-path",
            str(tmp_path / "graph.duckdb"),
            "--output",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.output
    assert report.is_file()
    assert "# Organism Report: Escherichia coli" in report.read_text(encoding="utf-8")
    assert "Report saved" in result.output


def test_holdouts_is_not_advertised_until_implemented() -> None:
    """The former success-with-no-output command must not be dispatchable."""
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "holdouts" not in result.output
