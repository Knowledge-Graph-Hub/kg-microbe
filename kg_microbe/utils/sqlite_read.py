"""Open a SQLite database for one block of reads, and always close it (#1637)."""

import sqlite3
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


@contextmanager
def read_only_sqlite(uri: str, refusal: Optional[Callable[[], Exception]] = None) -> Iterator[sqlite3.Connection]:
    """
    Yield a connection to the SQLite ``uri`` and close it when the block ends, however it ends.

    ``with sqlite3.connect(...)`` only commits or rolls back: the connection stays open
    until its frame is collected, and a traceback held on an error path keeps that
    frame alive (#1637). With ``refusal``, a ``sqlite3.Error`` from connecting or from
    the block is raised as ``refusal()``, chained to the SQLite error, so a reader
    refuses a file SQLite cannot read with the exception it uses for its other contract
    failures (#1636). Every other exception passes through unchanged.

    :param uri: A ``file:`` URI; the caller chooses ``mode=ro`` or ``immutable=1``.
    :param refusal: Builds the exception that replaces a SQLite error, or ``None`` to
        let SQLite errors through.
    :raises Exception: ``refusal()`` in place of a ``sqlite3.Error``.
    """
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        if refusal is None:
            raise
        raise refusal() from error
    try:
        yield connection
    except sqlite3.Error as error:
        if refusal is None:
            raise
        raise refusal() from error
    finally:
        connection.close()
