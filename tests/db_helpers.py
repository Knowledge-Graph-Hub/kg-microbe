"""Shared fixtures for tests that need a genuinely openable SQLite file."""

import os
import sqlite3
import tempfile
from pathlib import Path

_VALID_DB_BASE = None


# The schema a real `semsql make` emits, kept beside this module as data.
# Hand-written partial shapes drifted from the production gate three rounds
# running: each time the gate learned of another object, four fixtures had to be
# found and corrected. Loading the whole captured schema makes a partial fixture
# impossible by construction.
_SCHEMA_PATH = Path(__file__).parent / "semsql_schema.sql"


def _load_schema_statements(path):
    """
    Parse the captured schema file into individual statements.

    Comment lines are stripped *before* splitting: leaving them in glued the
    header to the first statement, which the filter then discarded, silently
    producing a 99-of-100-object fixture that failed the gate for a reason that
    looked like a code bug.

    :param path: Path to the .sql file.
    :return: Tuple of DDL statements.
    """
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return tuple(s.strip() for s in "\n".join(lines).split(";") if s.strip())


SEMSQL_DDL = _load_schema_statements(_SCHEMA_PATH)

SEMSQL_SEED = (
    "INSERT INTO statements (subject, predicate, object, value) VALUES ('obo:x', 'rdfs:label', NULL, 'x')",
    "INSERT INTO entailed_edge VALUES ('obo:x', 'rdfs:subClassOf', 'obo:root')",
    # Ontology identity rows. Production refuses a database that does not contain
    # the ontology it was asked for — `ncbitaxon.db` pointing at a copy of
    # `chebi.db` used to pass every other check while taxon lookups returned
    # nothing. One helper backs the NCBITaxon, ChEBI, GO and EC suites, so it
    # claims all four; tests that care about mismatch use the real databases.
    # rdf:type rather than owl:versionInfo: the identity check only needs the
    # subject to exist, and seeding a version here would collide with the
    # release-stamp tests that set their own.
    "INSERT INTO statements (subject, predicate, object, value) "
    "VALUES ('obo:ncbitaxon.owl', 'rdf:type', 'owl:Ontology', NULL)",
    "INSERT INTO statements (subject, predicate, object, value) "
    "VALUES ('obo:chebi.owl', 'rdf:type', 'owl:Ontology', NULL)",
    "INSERT INTO statements (subject, predicate, object, value) "
    "VALUES ('obo:go.owl', 'rdf:type', 'owl:Ontology', NULL)",
    "INSERT INTO statements (subject, predicate, object, value) "
    "VALUES ('obo:eccode.owl', 'rdf:type', 'owl:Ontology', NULL)",
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
