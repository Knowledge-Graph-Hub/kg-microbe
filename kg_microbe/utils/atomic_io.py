"""Atomic writes for derived caches, so a failed run leaves no half-written file."""

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
