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
            conn.execute("CREATE TABLE statements (subject TEXT, predicate TEXT, object TEXT, value TEXT)")
            # At least one row: a build that creates the SemSQL schema and loads
            # nothing into it is not a usable database, and the post-build gate
            # now says so. A fixture standing in for a healthy build has to be
            # one.
            conn.execute("INSERT INTO statements VALUES ('obo:x', 'rdfs:label', NULL, 'x')")
            conn.commit()
            conn.close()
            _VALID_DB_BASE = Path(p).read_bytes()
    return _VALID_DB_BASE + marker + (b"\0" * pad)
