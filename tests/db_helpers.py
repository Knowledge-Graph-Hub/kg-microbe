"""Shared fixtures for tests that need a genuinely openable SQLite file."""

import os
import sqlite3
import tempfile
from pathlib import Path

_VALID_DB_BASE = None


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
            p = os.path.join(d, "base.db")
            conn = sqlite3.connect(p)
            # The minimal shape the post-build gate requires. A build that
            # creates part of the SemSQL schema and loads nothing into it is not
            # a usable database, and a fixture standing in for a healthy build
            # has to be one. entailed_edge in particular: without it labels and
            # search still work while ancestors/descendants fail, which is
            # exactly the replacement that used to displace a good copy.
            conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
            conn.execute("CREATE TABLE entailed_edge (subject TEXT, predicate TEXT, object TEXT)")
            conn.execute("CREATE VIEW edge AS SELECT subject, predicate, object FROM statements")
            conn.execute("CREATE VIEW rdfs_label_statement AS SELECT * FROM statements WHERE predicate = 'rdfs:label'")
            conn.execute("INSERT INTO statements VALUES ('obo:x', 'rdfs:label', NULL, 'x')")
            conn.execute("INSERT INTO entailed_edge VALUES ('obo:x', 'rdfs:subClassOf', 'obo:root')")
            conn.commit()
            conn.close()
            _VALID_DB_BASE = Path(p).read_bytes()
    return _VALID_DB_BASE + marker + (b"\0" * pad)
