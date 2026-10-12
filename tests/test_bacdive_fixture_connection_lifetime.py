"""Require actual SQLite fixture builders to close their owned handles deterministically."""

import sqlite3
from contextlib import closing

import pytest

from tests import bacdive_fallback_fixtures as native_fixture
from tests import bacdive_synthetic_fallback_context as synthetic_fixture
from tests import test_bacdive_taxonomy_evidence as taxonomy_fixture

BUILDERS = ("taxonomy", "native", "synthetic")


def build(name, path):
    """Call the unchanged public fixture builder with its actual immutable or synthetic input."""
    if name == "taxonomy":
        return taxonomy_fixture.database(path)
    if name == "native":
        return native_fixture.native_database(path)
    return synthetic_fixture.create_database(path, {"NCBITaxon:20": "Fixture child"})


@pytest.fixture
def actual_connections(monkeypatch):
    """Retain real returned connections so garbage collection cannot conceal missing closure."""
    connect = sqlite3.connect
    opened = []

    def observed_connect(*args, **kwargs):
        """Observe a genuine SQLite handle without replacing query, transaction, or close behavior."""
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    try:
        yield connect, opened
    finally:
        for connection in opened:
            connection.close()


@pytest.mark.parametrize("builder", BUILDERS)
def test_builder_commits_then_closes_actual_sqlite_connection(tmp_path, actual_connections, builder):
    """A successful fixture remains readable while its retained original handle is genuinely closed."""
    connect, opened = actual_connections
    path = tmp_path / "authority.db"
    assert build(builder, path) == path
    assert len(opened) == 1
    assert isinstance(opened[0], sqlite3.Connection)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    with closing(connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as fresh:
        assert fresh.execute("SELECT COUNT(*) FROM statements").fetchone()[0] > 0
        assert fresh.execute("SELECT value FROM statements WHERE predicate='owl:versionInfo'").fetchone()
        if builder == "taxonomy":
            assert fresh.execute("SELECT object FROM entailed_edge WHERE subject='NCBITaxon:20'").fetchall() == [
                ("NCBITaxon:10",)
            ]
        elif builder == "native":
            assert fresh.execute("SELECT COUNT(*) FROM entailed_edge").fetchone()[0] > 0
        else:
            assert fresh.execute("SELECT COUNT(*) FROM entailed_edge").fetchone()[0] == 0
            assert fresh.execute(
                "SELECT value FROM statements WHERE subject='NCBITaxon:20' AND predicate='rdfs:label'"
            ).fetchall() == [("Fixture child",)]


@pytest.mark.parametrize("builder", BUILDERS)
def test_builder_failure_also_closes_actual_sqlite_connection(tmp_path, actual_connections, builder):
    """An authentic SQLite setup error propagates while the builder still releases its own handle."""
    connect, opened = actual_connections
    path = tmp_path / "authority.db"
    with closing(connect(path)) as existing, existing:
        existing.execute("CREATE TABLE statements (already_exists TEXT)")
        existing.execute("INSERT INTO statements VALUES ('preserved')")
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        build(builder, path)
    assert len(opened) == 1
    assert isinstance(opened[0], sqlite3.Connection)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    with closing(connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as fresh:
        assert fresh.execute("SELECT * FROM statements").fetchall() == [("preserved",)]
