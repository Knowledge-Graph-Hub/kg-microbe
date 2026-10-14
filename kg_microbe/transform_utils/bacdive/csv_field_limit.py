"""Read BacDive audits whose cells can outgrow CSV's field limit (#1571, #1575)."""

import csv
from contextlib import contextmanager


@contextmanager
def csv_field_limit_at_least(size):
    """
    Raise CSV's process-wide field limit to at least ``size`` for the block, then restore it.

    The audits embed native BacDive records, and a cell can exceed CSV's default
    of 131,072 characters. Pass the size in bytes of the file being read: no
    cell is longer than its file. The caller's limit is never lowered, and is
    restored even when the read fails.

    Consume the reader inside the block. A generator such as ``graph_rows``
    resumed after it would parse at the caller's limit again.

    :param size: The size in bytes of the file the block reads.
    """
    previous = csv.field_size_limit()
    csv.field_size_limit(max(previous, size))
    try:
        yield
    finally:
        csv.field_size_limit(previous)
