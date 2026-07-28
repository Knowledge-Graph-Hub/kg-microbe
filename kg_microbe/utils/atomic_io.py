"""Atomic writes for derived caches, so a failed run leaves no half-written file."""

import csv
import itertools
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Union

# Distinguishes concurrent writers within one process; os.getpid() covers
# across processes. itertools.count is atomic under the GIL.
_COUNTER = itertools.count()


@contextmanager
def atomic_write(path: Union[str, Path], mode: str = "w", mark_complete: bool = False, **open_kwargs):
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
        marker = Path(f"{path}.complete")
        if mark_complete or marker.exists():
            # A cache can be legitimately empty. Row count alone cannot tell
            # "correctly produced nothing" from "truncated", so completion is
            # recorded explicitly rather than inferred from content. The marker
            # records the size it certifies: an empty marker vouched for
            # whatever later occupied the path, so a header-only file dropped in
            # afterwards was re-certified as complete.
            #
            # It is refreshed on *any* atomic rewrite, not only when the caller
            # asks to mark. Legitimate post-processing follows some of these
            # writes — annotate() commits a result and drop_duplicates then
            # rewrites it — and a stale size would condemn a perfectly good
            # cache to be regenerated on every future run.
            stat = path.stat()
            marker.write_text(f"{stat.st_size}:{stat.st_mtime_ns}")
        _sweep_stale_partials(path)
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


# Partials older than this are assumed to be from a process that died without
# unwinding (SIGKILL, os._exit, power loss) — nothing else can clean them, since
# the writer that would have is gone.
#
# Age is a proxy for "the writer is dead", and an imperfect one: a writer that
# stalls or legitimately runs longer than this loses its temp file's pathname
# and will fail its rename. Accepted deliberately. The alternative — asking
# whether some process still holds the descriptor — has no portable answer, and
# the failure mode here is a failed rename on an already-pathological run, not
# a corrupted or lost cache. The window is generous precisely so ordinary long
# writes stay well inside it.
_STALE_PARTIAL_SECONDS = 24 * 60 * 60


def _sweep_stale_partials(path: Path) -> None:
    """
    Remove long-dead sibling ``.partial`` files.

    Per-writer temp names stop concurrent writers colliding, but they mean a
    process killed mid-write strands its temp file forever — potentially several
    GB beside a node file. Only files older than a day are touched, so a
    concurrently-running writer's temp is never removed.

    :param path: The final destination path whose siblings to sweep.
    """
    try:
        # Wall clock, not the target's mtime: a target with a future timestamp
        # made the cutoff future too and swept a live writer's temp, while an
        # old target left genuinely stranded partials in place forever.
        cutoff = time.time() - _STALE_PARTIAL_SECONDS
        for sibling in path.parent.glob(f"{path.name}.*.partial"):
            try:
                if os.path.getmtime(sibling) < cutoff:
                    os.unlink(sibling)
            except OSError:
                continue
    except OSError:
        return


def cache_is_complete(path: Union[str, Path], delimiter: str = "\t") -> bool:
    """
    Report whether a derived cache was completely produced.

    Complete means either an explicit completion marker written by
    :func:`atomic_write` (``mark_complete=True``), or — for caches written before
    markers existed — at least one data row. The marker is what lets a
    legitimately *empty* result count as finished: judging on row count alone,
    a run that correctly produced zero annotations looked identical to a
    truncated one and was regenerated on every subsequent run forever.

    :param path: Cache path.
    :param delimiter: Field delimiter of the cache.
    :return: True if the cache exists and is known to be complete.
    """
    path = Path(path)
    if not path.exists():
        return False
    marker = Path(f"{path}.complete")
    if marker.exists():
        try:
            certified = marker.read_text().strip()
            stat = path.stat()
            # Size *and* modification time. Size alone certified any unrelated
            # file that happened to be the same length, and an empty marker —
            # the interim format — certified anything at all, so a legacy marker
            # beside a broken file read as complete. An empty or unparsable
            # marker now proves nothing and falls through to the content check.
            if certified and certified == f"{stat.st_size}:{stat.st_mtime_ns}":
                return True
        except (OSError, ValueError):
            return False
    return has_data_rows(path, delimiter)
