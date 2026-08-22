"""File I/O primitives for the MetaTraits transform."""

import csv
import gzip
from pathlib import Path
from typing import IO, List


def open_maybe_gzipped(path: Path) -> IO[str]:
    """Open gzip input while tolerating a misnamed plain-text Google Drive file."""
    if path.name.endswith(".gz"):
        handle = None
        try:
            handle = gzip.open(path, "rt", encoding="utf-8")
            handle.read(1)
            handle.seek(0)
        except Exception:  # noqa: BLE001 -- any failed gzip probe falls back
            if handle is not None:
                handle.close()
            return path.open("r", encoding="utf-8")
        return handle
    return path.open("r", encoding="utf-8")


def open_jsonl(path: Path) -> IO[str]:
    """Open JSONL input through the tolerant gzip reader."""
    return open_maybe_gzipped(path)


class StreamingRowWriter:
    """Write TSV rows incrementally without accumulating a graph in memory."""

    def __init__(self, output_file: Path, header: List[str]):
        """Store the output path and ordered header."""
        self.output_file = output_file
        self.header = header
        self.file_handle: IO[str] | None = None
        self.writer = None

    def __enter__(self):
        """Open the output and write its header."""
        self.output_file.parent.mkdir(exist_ok=True, parents=True)
        self.file_handle = self.output_file.open("w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file_handle, delimiter="\t")
        self.writer.writerow(self.header)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the output handle."""
        if self.file_handle:
            self.file_handle.close()

    def write_row(self, row: List) -> None:
        """Write one ordered TSV row."""
        if self.writer:
            self.writer.writerow(row)
