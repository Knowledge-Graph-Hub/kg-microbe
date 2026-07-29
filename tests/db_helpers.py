"""Shared fixtures for tests that need a genuinely openable SQLite file."""

import os
import sqlite3
import tempfile
from pathlib import Path

_VALID_DB_BASE = None


# The minimal SemSQL shape the production gate requires, in one place. Four
# separate fixtures used to declare their own partial version, and every time
# the gate learned about another object or column, all four had to be found and
# updated. Kept in sync with _SEMSQL_STRUCTURE_PROBES in ontology_utils.
SEMSQL_DDL = (
    "CREATE TABLE statements (stanza TEXT, subject TEXT, predicate TEXT, object TEXT, "
    "value TEXT, datatype TEXT, language TEXT, graph TEXT)",
    "CREATE TABLE entailed_edge (subject TEXT, predicate TEXT, object TEXT)",
    "CREATE VIEW edge AS SELECT subject, predicate, object FROM statements",
    "CREATE VIEW rdfs_label_statement AS SELECT stanza, subject, predicate, object, value, "
    "datatype, language, graph FROM statements WHERE predicate = 'rdfs:label'",
    "CREATE VIEW node_to_value_statement AS SELECT stanza, subject, predicate, object, value, "
    "datatype, language, graph FROM statements WHERE value IS NOT NULL",
)

SEMSQL_SEED = (
    "INSERT INTO statements (subject, predicate, object, value) VALUES ('obo:x', 'rdfs:label', NULL, 'x')",
    "INSERT INTO entailed_edge VALUES ('obo:x', 'rdfs:subClassOf', 'obo:root')",
)


def write_semsql_db(path, extra_statements=()):
    """
    Create a genuinely usable minimal SemSQL database at ``path``.

    :param path: Destination path.
    :param extra_statements: Extra (sql, params) pairs to execute, for tests that
        need a version stamp or particular rows.
    :return: The path written.
    """
    conn = sqlite3.connect(str(path))
    try:
        for ddl in SEMSQL_DDL:
            conn.execute(ddl)
        for seed in SEMSQL_SEED:
            conn.execute(seed)
        for sql, params in extra_statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
    return path


def valid_db_bytes(marker: bytes = b"", pad: int = 0) -> bytes:
    """
    Return the bytes of a genuinely openable SQLite file.

    Every "is this DB any good" decision now probes that the file actually opens,
    so filler bytes no longer stand in for a healthy DB. Tests that assert a DB
    is *reused*, *restored* or *accepted* have to supply something SQLite can
    read; tests that assert a stub or partial is rejected should keep writing
    junk. ``marker`` and ``pad`` let callers make otherwise-identical DBs
    distinguishable for identity assertions.

    :param marker: Byte string appended so different fixtures differ.
    :param pad: Extra padding bytes appended after the marker.
    :return: Bytes of a valid SQLite database.
    """
    global _VALID_DB_BASE
    if _VALID_DB_BASE is None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "base.db")
            write_semsql_db(path)
            _VALID_DB_BASE = Path(path).read_bytes()
    return _VALID_DB_BASE + marker + (b"\0" * pad)
