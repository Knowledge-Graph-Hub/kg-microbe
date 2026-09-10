r"""
One place that decides how KG-Microbe writes a TSV.

``csv.writer``'s default ``lineterminator`` is ``"\r\n"`` on every platform,
and it is emitted literally regardless of the ``newline`` argument to
``open()``. Four transforms and both merge normalizers used that default, so
every line of the shipped merged graph ended with a carriage return and the
last column of every row carried it as data -- an "empty" trailing field was
``"\r"``, which inverts a truthiness test on it (#1041, and the corruption
open issue #541 describes in the DuckDB loader).

Use :func:`tsv_writer` instead of constructing ``csv.writer`` directly for any
file another tool will parse. ``tests/test_tsv_line_endings.py`` fails on a
graph-writing module that goes back to the bare constructor.
"""

import csv
from typing import Any

#: The only line terminator KG-Microbe writes.
LINE_TERMINATOR = "\n"


def tsv_writer(handle: Any, **kwargs: Any):
    r"""
    Return a tab-delimited ``csv.writer`` that terminates lines with ``\n``.

    :param handle: A file opened with ``newline=""`` (so the text layer does
        not translate what the writer emits).
    :param kwargs: Passed through to ``csv.writer``; ``delimiter`` and
        ``lineterminator`` default to tab and newline.
    :return: The configured writer.
    """
    kwargs.setdefault("delimiter", "\t")
    kwargs.setdefault("lineterminator", LINE_TERMINATOR)
    return csv.writer(handle, **kwargs)


def tsv_dict_writer(handle: Any, fieldnames, **kwargs: Any):
    r"""
    Return a tab-delimited ``csv.DictWriter`` terminating lines with ``\n``.

    :param handle: A file opened with ``newline=""``.
    :param fieldnames: Column names, in order.
    :param kwargs: Passed through to ``csv.DictWriter``.
    :return: The configured writer.
    """
    kwargs.setdefault("delimiter", "\t")
    kwargs.setdefault("lineterminator", LINE_TERMINATOR)
    return csv.DictWriter(handle, fieldnames=fieldnames, **kwargs)


__all__ = ["LINE_TERMINATOR", "tsv_dict_writer", "tsv_writer"]
