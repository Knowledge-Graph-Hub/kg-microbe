"""A read-only SQLite block always closes its connection and can refuse SQLite errors (#1636, #1637)."""

import sqlite3

import pytest

from kg_microbe.utils.sqlite_read import read_only_sqlite


class Refused(ValueError):
    """A reader's own contract failure."""


def _database(tmp_path):
    """Return the URI of a one-table database."""
    path = tmp_path / "authority.db"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE statements(subject)")
        connection.execute("INSERT INTO statements VALUES ('GO:1')")
    connection.close()
    return path.as_uri() + "?mode=ro&immutable=1"


def _closed(connection):
    """Report whether a connection has been closed."""
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_the_connection_is_closed_when_the_block_ends(tmp_path):
    """`with sqlite3.connect()` leaves it open; this does not."""
    with read_only_sqlite(_database(tmp_path)) as connection:
        assert connection.execute("SELECT subject FROM statements").fetchall() == [("GO:1",)]
    assert _closed(connection)


def test_the_connection_is_closed_when_the_block_fails(tmp_path):
    """An error path closes it too, even while the exception is still held."""
    with pytest.raises(Refused) as info:
        with read_only_sqlite(_database(tmp_path)) as connection:
            raise Refused("wrong release")
    assert info.value.__cause__ is None
    assert _closed(connection)


def test_a_query_error_becomes_the_readers_refusal(tmp_path):
    """A SQLite error in the block is raised as the refusal, chained to it."""
    with pytest.raises(Refused, match="cannot be read") as info:
        with read_only_sqlite(_database(tmp_path), lambda: Refused("cannot be read")) as connection:
            connection.execute("SELECT * FROM missing")
    assert isinstance(info.value.__cause__, sqlite3.OperationalError)
    assert _closed(connection)


def test_a_connect_error_becomes_the_readers_refusal(tmp_path):
    """A file that cannot be opened at all is refused the same way."""
    missing = (tmp_path / "absent.db").as_uri() + "?mode=ro"
    with pytest.raises(Refused) as info:
        with read_only_sqlite(missing, lambda: Refused("cannot be read")):
            pass
    assert isinstance(info.value.__cause__, sqlite3.OperationalError)


def test_without_a_refusal_sqlite_errors_pass_through(tmp_path):
    """Callers that already convert SQLite errors themselves see them unchanged."""
    with pytest.raises(sqlite3.OperationalError):
        with read_only_sqlite(_database(tmp_path)) as connection:
            connection.execute("SELECT * FROM missing")
    assert _closed(connection)


def test_a_file_that_is_not_a_database_is_refused_at_its_first_query(tmp_path):
    """Under immutable=1 SQLite opens anything; the first query is where it fails."""
    path = tmp_path / "go.db"
    path.write_bytes(b"<html>Service unavailable</html>" * 64)
    with pytest.raises(Refused):
        with read_only_sqlite(path.as_uri() + "?mode=ro&immutable=1", lambda: Refused("cannot be read")) as c:
            c.execute("SELECT 1 FROM statements")
