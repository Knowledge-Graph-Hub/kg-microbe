"""DuckDB database loader for KG-Microbe knowledge graph."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, Iterable, Union

import duckdb

SOURCE_METADATA_TABLE = "kg_microbe_source_metadata"
REQUIRED_COLUMNS = {
    "nodes": {"id", "category", "name", "synonym"},
    "edges": {"subject", "predicate", "object", "relation", "primary_knowledge_source"},
}


def get_or_create_database(
    nodes_path: Union[str, Path] = "data/merged/merged-kg_nodes.tsv",
    edges_path: Union[str, Path] = "data/merged/merged-kg_edges.tsv",
    db_path: Union[str, Path] = "data/merged/kg-microbe.duckdb",
    force_reload: bool = False,
) -> duckdb.DuckDBPyConnection:
    """
    Load or connect to a DuckDB database built from KGX TSV files.

    Existing databases are reused only when their recorded source path, size,
    and nanosecond mtime match both input files. Rebuilds happen at a temporary
    sibling path and replace the advertised database atomically.

    :param nodes_path: Path to nodes TSV file.
    :param edges_path: Path to edges TSV file.
    :param db_path: Path to DuckDB database file.
    :param force_reload: Force rebuild from TSV files.
    :return: Open DuckDB connection.
    """
    nodes_path = Path(nodes_path).resolve()
    edges_path = Path(edges_path).resolve()
    db_path = Path(db_path).resolve()

    for label, source_path in (("Nodes", nodes_path), ("Edges", edges_path)):
        if not source_path.is_file():
            raise FileNotFoundError(f"{label} file not found: {source_path}")

    fingerprints = _source_fingerprints(nodes_path, edges_path)
    if not force_reload and db_path.is_file():
        conn = _open_current_database(db_path, fingerprints)
        if conn is not None:
            print(f"  Using existing database: {db_path}")
            return conn

    print("  Building DuckDB database directly from TSV files...")
    print(f"    - Nodes: {nodes_path}")
    print(f"    - Edges: {edges_path}")
    _rebuild_database(nodes_path, edges_path, db_path, fingerprints)
    print(f"  ✅ Database created: {db_path}")
    return duckdb.connect(str(db_path))


def _source_fingerprints(nodes_path: Path, edges_path: Path) -> Dict[str, tuple[str, int, int]]:
    """Return stable-enough freshness metadata without scanning multi-GB files."""
    result = {}
    for kind, path in (("nodes", nodes_path), ("edges", edges_path)):
        stat = path.stat()
        result[kind] = (str(path), stat.st_size, stat.st_mtime_ns)
    return result


def _open_current_database(
    db_path: Path,
    fingerprints: Dict[str, tuple[str, int, int]],
) -> duckdb.DuckDBPyConnection | None:
    """Open an existing database only if it is complete and current."""
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        conn.execute("SELECT 1 FROM nodes LIMIT 1")
        conn.execute("SELECT 1 FROM edges LIMIT 1")
        rows = conn.execute(
            f"SELECT source_kind, source_path, source_size, source_mtime_ns FROM {SOURCE_METADATA_TABLE}"
        ).fetchall()
        recorded = {kind: (path, size, mtime_ns) for kind, path, size, mtime_ns in rows}
        if recorded == fingerprints:
            return conn
    except duckdb.Error:
        pass
    if conn is not None:
        conn.close()
    return None


def _rebuild_database(
    nodes_path: Path,
    edges_path: Path,
    db_path: Path,
    fingerprints: Dict[str, tuple[str, int, int]],
) -> None:
    """Build at a temporary sibling path, then atomically publish it."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_name(f".{db_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _create_database_from_tsv(nodes_path, edges_path, temp_path, fingerprints).close()
        os.replace(temp_path, db_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_header(path: Path, table_name: str) -> list[str]:
    """Read and deduplicate a TSV header, validating query-required columns."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw_header = handle.readline().rstrip("\r\n").split("\t")
    if not raw_header or raw_header == [""]:
        raise ValueError(f"{path} has no TSV header")

    columns = []
    seen: Dict[str, int] = {}
    for raw_name in raw_header:
        name = raw_name.strip()
        if not name:
            raise ValueError(f"{path} contains an empty column name")
        occurrence = seen.get(name, 0)
        seen[name] = occurrence + 1
        columns.append(name if occurrence == 0 else f"{name}_{occurrence}")

    missing = REQUIRED_COLUMNS[table_name] - set(columns)
    if missing:
        raise ValueError(f"{path} is missing required {table_name} columns: {sorted(missing)}")
    return columns


def _load_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
    columns: Iterable[str],
) -> int:
    """Load one TSV through DuckDB's streaming CSV reader with VARCHAR schema."""
    schema = {column: "VARCHAR" for column in columns}
    relation = conn.read_csv(
        str(path),
        header=False,
        skiprows=1,
        columns=schema,
        delimiter="\t",
        quotechar="",
        escapechar="",
        strict_mode=True,
    )
    relation.create(table_name)
    return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


def _create_database_from_tsv(
    nodes_path: Path,
    edges_path: Path,
    db_path: Path,
    fingerprints: Dict[str, tuple[str, int, int]] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Create a database using DuckDB-native, bounded-memory TSV ingestion."""
    node_columns = _read_header(nodes_path, "nodes")
    edge_columns = _read_header(edges_path, "edges")
    fingerprints = fingerprints or _source_fingerprints(nodes_path, edges_path)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("SET memory_limit='16GB'")
        print("    Loading nodes table...")
        node_count = _load_table(conn, "nodes", nodes_path, node_columns)
        print(f"      Loaded {node_count:,} nodes")
        print("    Loading edges table...")
        edge_count = _load_table(conn, "edges", edges_path, edge_columns)
        print(f"      Loaded {edge_count:,} edges")

        conn.execute("CREATE INDEX idx_nodes_id ON nodes(id)")
        conn.execute("CREATE INDEX idx_nodes_name ON nodes(name)")
        conn.execute("CREATE INDEX idx_nodes_category ON nodes(category)")
        conn.execute("CREATE INDEX idx_edges_subject ON edges(subject)")
        conn.execute("CREATE INDEX idx_edges_predicate ON edges(predicate)")
        conn.execute("CREATE INDEX idx_edges_object ON edges(object)")
        conn.execute("CREATE INDEX idx_edges_sub_pred ON edges(subject, predicate)")

        conn.execute(
            f"CREATE TABLE {SOURCE_METADATA_TABLE} ("
            "source_kind VARCHAR PRIMARY KEY, source_path VARCHAR, "
            "source_size UBIGINT, source_mtime_ns UBIGINT)"
        )
        conn.executemany(
            f"INSERT INTO {SOURCE_METADATA_TABLE} VALUES (?, ?, ?, ?)",
            [(kind, *values) for kind, values in fingerprints.items()],
        )
        conn.execute("CHECKPOINT")
        return conn
    except Exception:
        conn.close()
        db_path.unlink(missing_ok=True)
        raise
