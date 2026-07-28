"""Atomic writes for derived caches, so a failed run leaves no half-written file."""

import csv
import itertools
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Union

# Distinguishes concurrent writers within one process; os.getpid() covers
# across processes. itertools.count is atomic under the GIL.
_COUNTER = itertools.count()


@contextmanager
def atomic_write(path: Union[str, Path], mode: str = "w", **open_kwargs):
    """
    Write to ``path`` via a temp file that is renamed into place only on success.

    Several derived caches in this repo are generated once and then guarded by a
    bare ``path.exists()`` on every later run. Writing them in place makes any
    mid-write failure permanent: the header lands, the generator raises, the
    context manager closes a truncated file, and every subsequent run sees a file
    that exists and skips regeneration. ``go_category_trees.tsv`` is the case
    that bit us — a header-only file makes ``prepare_go_dictionary`` return ``{}``,
    which drops every protein→GO edge and logs every GO term as obsolete, with a
    zero exit code, forever.

    ``os.replace`` is atomic on POSIX and Windows, so a reader either sees the
    old file or the complete new one, never a partial. The temp file is removed
    on *any* unwind — including ``BaseException``, which is what the fatal
    ontology errors are — because the cleanup lives in ``finally``.

    Callers that need the old file left intact on failure get that for free: it
    is never touched until the rename.

    :param path: Final destination path.
    :param mode: Mode for the underlying ``open``; must be a writing mode.
    :param open_kwargs: Passed through to ``open`` (encoding, newline, ...).
    :yield: The open file handle to write to.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique per writer. A shared "<name>.partial" is not actually atomic under
    # concurrent writers: B truncates the same inode A is writing, renames it
    # into place, and A then continues writing through its descriptor — which
    # now refers to the *published* file — before failing its own rename.
    # Same directory, so os.replace stays a same-filesystem rename.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{next(_COUNTER)}.partial")
    committed = False
    try:
        with open(tmp, mode, **open_kwargs) as handle:
            yield handle
        os.replace(tmp, path)
        committed = True
    finally:
        if not committed:
            try:
                os.unlink(tmp)
            except OSError:
                # Nothing to clean up, or it is not ours to remove.
                pass


def has_data_rows(path: Union[str, Path], delimiter: str = "\t") -> bool:
    """
    Report whether a delimited cache exists and holds at least one data row.

    The companion to :func:`atomic_write`. Atomicity stops a cache from being
    poisoned *again*, but it cannot repair one poisoned before the fix landed —
    and every consumer of these caches guards regeneration with a bare
    ``.exists()``, so a header-only file is accepted forever. Checking for
    content is what lets an already-poisoned cache heal on the next run instead
    of requiring the user to know which file to delete.

    Conservative on error: an unreadable file reports False, so the caller
    regenerates rather than trusting something it could not inspect.

    :param path: Cache path.
    :param delimiter: Field delimiter of the cache.
    :return: True if the file exists and has a row beyond the header.
    """
    path = Path(path)
    if not path.exists():
        return False
    try:
        with open(path, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            next(reader, None)  # header
            return next(reader, None) is not None
    except OSError:
        return False
