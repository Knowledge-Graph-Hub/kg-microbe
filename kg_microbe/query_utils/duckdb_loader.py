"""DuckDB database loader for KG-Microbe knowledge graph."""

from pathlib import Path
from typing import Union

import duckdb
import pandas as pd


def get_or_create_database(
    nodes_path: Union[str, Path] = "data/merged/merged-kg_default_nodes.tsv",
    edges_path: Union[str, Path] = "data/merged/merged-kg_default_edges.tsv",
    db_path: Union[str, Path] = "data/merged/kg-microbe.duckdb",
    force_reload: bool = False,
) -> duckdb.DuckDBPyConnection:
    """
    Load or connect to DuckDB database from KG TSV files.

    :param nodes_path: Path to nodes TSV file
    :param edges_path: Path to edges TSV file
    :param db_path: Path to DuckDB database file
    :param force_reload: Force rebuild from TSV files
    :return: DuckDB connection object
    """
    nodes_path = Path(nodes_path)
    edges_path = Path(edges_path)
    db_path = Path(db_path)

    # Check if source files exist
    if not nodes_path.exists():
        raise FileNotFoundError(f"Nodes file not found: {nodes_path}")
    if not edges_path.exists():
        raise FileNotFoundError(f"Edges file not found: {edges_path}")

    # Determine if we need to rebuild
    needs_rebuild = force_reload or not db_path.exists()

    if needs_rebuild:
        print(f"  Building DuckDB database from TSV files...")
        print(f"    - Nodes: {nodes_path}")
        print(f"    - Edges: {edges_path}")

        # Remove old database if exists
        if db_path.exists():
            db_path.unlink()

        # Create new database
        conn = _create_database_from_tsv(nodes_path, edges_path, db_path)
        print(f"  ✅ Database created: {db_path}")
    else:
        print(f"  Using existing database: {db_path}")
        # Verify database has required tables
        try:
            conn = duckdb.connect(str(db_path))
            # Quick check that tables exist
            conn.execute("SELECT COUNT(*) FROM nodes LIMIT 1;")
            conn.execute("SELECT COUNT(*) FROM edges LIMIT 1;")
        except Exception as e:
            print(f"  Database appears corrupted: {e}")
            print("  Rebuilding...")
            db_path.unlink()
            conn = _create_database_from_tsv(nodes_path, edges_path, db_path)

    return conn


def _create_database_from_tsv(
    nodes_path: Path, edges_path: Path, db_path: Path
) -> duckdb.DuckDBPyConnection:
    """
    Create DuckDB database from TSV files with indexes.

    Uses Pandas to robustly read TSV files, then loads into DuckDB.

    :param nodes_path: Path to nodes TSV file
    :param edges_path: Path to edges TSV file
    :param db_path: Path to output database file
    :return: DuckDB connection object
    """
    # Connect to database (creates file)
    conn = duckdb.connect(str(db_path))

    try:
        # Set memory limit for large datasets
        conn.execute("SET memory_limit='16GB';")

        # Load nodes table via Pandas (more robust to format issues)
        print("    Loading nodes table...")
        nodes_df = pd.read_csv(
            nodes_path,
            sep="\t",
            dtype=str,
            na_values=[""],
            keep_default_na=False,
            low_memory=False,
        )
        conn.execute("CREATE TABLE nodes AS SELECT * FROM nodes_df;")
        print(f"      Loaded {len(nodes_df):,} nodes")

        # Create node indexes
        print("    Creating node indexes...")
        conn.execute("CREATE INDEX idx_nodes_id ON nodes(id);")
        conn.execute("CREATE INDEX idx_nodes_name ON nodes(name);")
        conn.execute("CREATE INDEX idx_nodes_category ON nodes(category);")

        # Load edges table via Pandas
        print("    Loading edges table...")
        # Read raw file and preprocess to remove embedded \r characters
        with open(edges_path, "r", newline="\n") as f:
            # Read first line (header) with embedded \r removed
            header_line = f.readline().replace("\r", "").strip()
            raw_header = header_line.split("\t")

            # Deduplicate column names by adding suffix
            cleaned_header = []
            seen = {}
            for col in raw_header:
                col = col.strip()
                if col in seen:
                    seen[col] += 1
                    cleaned_header.append(f"{col}_{seen[col]}")
                else:
                    seen[col] = 0
                    cleaned_header.append(col)

        print(f"      Detected {len(cleaned_header)} columns in edges file")

        # Load with cleaned header and explicit line terminator
        edges_df = pd.read_csv(
            edges_path,
            sep="\t",
            dtype=str,
            na_values=[""],
            keep_default_na=False,
            low_memory=False,
            names=cleaned_header,
            skiprows=1,  # Skip original header
            lineterminator="\n",  # Use only \n as line terminator, ignore \r
        )
        conn.execute("CREATE TABLE edges AS SELECT * FROM edges_df;")
        print(f"      Loaded {len(edges_df):,} edges")

        # Create edge indexes
        print("    Creating edge indexes...")
        conn.execute("CREATE INDEX idx_edges_subject ON edges(subject);")
        conn.execute("CREATE INDEX idx_edges_predicate ON edges(predicate);")
        conn.execute("CREATE INDEX idx_edges_object ON edges(object);")
        conn.execute("CREATE INDEX idx_edges_sub_pred ON edges(subject, predicate);")

        return conn

    except Exception as e:
        # Clean up partial database on error
        conn.close()
        if db_path.exists():
            db_path.unlink()
        raise e
