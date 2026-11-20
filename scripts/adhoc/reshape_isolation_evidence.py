#!/usr/bin/env python
"""
Preserve record-scoped BacDive isolation evidence without biological interpretation.

Purpose: regroup a local isolation-source CSV without dropping source occurrences.
Inputs: explicit UTF-8 CSV with the nine documented export columns.
Outputs: one no-clobber JSON evidence document; private temporary SQLite grouping.
Date: 2026-10-13.

No network access, ontology grounding, production transform or graph emission.
The input is copied to an immutable parser snapshot and hashed; the original
must still have identical bytes before the completed output can be published.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

FORMAT = "bacdive-isolation-evidence-v1"
HEADERS = {
    "id": "ID",
    "species": "Species",
    "culture_collection_number": "Culture collection number",
    "isolation_source": "Isolation source",
    "country": "Country",
    "continent": "Continent",
    "category_1": "Category 1",
    "category_2": "Category 2",
    "category_3": "Category 3",
}
VALUE_FIELDS = ("species", "culture_collection_number", "isolation_source", "country", "continent")
MULTIVALUED = frozenset({"isolation_source", "country", "continent"})
SCALAR_FIELDS = ("species", "culture_collection_number")
CHUNK_SIZE = 1024 * 1024


def _json(value):
    """Serialize source strings reversibly, including quotes, tabs and newlines."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _identity(path, destination=None):
    """Hash complete bytes, optionally snapshot them, and reject a changing read."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
        after = os.fstat(stream.fileno())
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in stable):
        raise ValueError("Input changed while being read")
    return {"sha256": digest.hexdigest(), "bytes": before.st_size}


def _columns(headers):
    """Accept documented export or canonical column names, never positional guesses."""
    aliases = {value: key for key, value in HEADERS.items()} | {key: key for key in HEADERS}
    if not headers or any(header not in aliases for header in headers):
        raise ValueError("Missing or unknown CSV header")
    columns = {aliases[header]: header for header in headers}
    if len(headers) != len(HEADERS) or len(columns) != len(headers) or set(columns) != set(HEADERS):
        raise ValueError("Duplicate or missing CSV columns")
    return columns


def _initialize(database):
    """Keep grouping and distinct-value indexes on private disk, not whole-input lists."""
    database.executescript(
        """
        PRAGMA temp_store=FILE;
        PRAGMA cache_size=-8192;
        CREATE TABLE rows (seq INTEGER PRIMARY KEY, id TEXT, line_start INTEGER, line_end INTEGER, raw TEXT);
        CREATE INDEX row_ids ON rows (id, seq);
        CREATE TABLE vals (id TEXT, field TEXT, value TEXT, seq INTEGER, position INTEGER,
                           PRIMARY KEY (id, field, value));
        CREATE TABLE paths (id TEXT, value TEXT, seq INTEGER, PRIMARY KEY (id, value));
        """
    )


def _ingest(database, snapshot):
    """Keep every CSV occurrence; derive only explicitly labeled structural views."""
    original_limit = csv.field_size_limit()
    csv.field_size_limit(16 * CHUNK_SIZE)
    try:
        with snapshot.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, None)
            columns = _columns(headers)
            count = 0
            while True:
                start = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                if len(row) != len(headers):
                    raise ValueError(f"CSV field count changed at physical line {start}")
                raw = dict(zip(headers, row, strict=True))
                values = {key: raw[header] for key, header in columns.items()}
                identifier = values["id"]
                if not re.fullmatch(r"[1-9][0-9]*", identifier):
                    raise ValueError(f"Missing or noncanonical BacDive ID at physical line {start}")
                count += 1
                database.execute(
                    "INSERT INTO rows VALUES (?, ?, ?, ?, ?)", (count, identifier, start, reader.line_num, _json(raw))
                )
                for field in VALUE_FIELDS:
                    tokens = values[field].split("###") if field in MULTIVALUED else [values[field]]
                    for position, token in enumerate(tokens):
                        # Derived list items are trimmed only for the documented
                        # delimiter columns. The raw cell always remains exact.
                        value = token.strip() if field in MULTIVALUED else token
                        if value:
                            database.execute(
                                "INSERT OR IGNORE INTO vals VALUES (?, ?, ?, ?, ?)",
                                (identifier, field, value, count, position),
                            )
                path = {key: values[key] for key in ("category_1", "category_2", "category_3")}
                if any(path.values()):
                    database.execute("INSERT OR IGNORE INTO paths VALUES (?, ?, ?)", (identifier, _json(path), count))
            if not count:
                raise ValueError("The CSV contains no source records")
        database.commit()
        return headers, columns, count
    finally:
        csv.field_size_limit(original_limit)


def _array(stream, values):
    """Write one JSON array incrementally from a cursor or iterator."""
    stream.write("[")
    for index, value in enumerate(values):
        if index:
            stream.write(",")
        stream.write(_json(value))
    stream.write("]")


def _occurrences(database, identifier):
    """Yield exact parsed cells and their source record/physical line coordinates."""
    for seq, start, end, raw in database.execute(
        "SELECT seq, line_start, line_end, raw FROM rows WHERE id=? ORDER BY seq", (identifier,)
    ):
        yield {"source_record": seq, "line_start": start, "line_end": end, "raw_fields": json.loads(raw)}


def _write_document(database, stream, source, count):
    """Stream the grouped document without collecting the full input or a full group."""
    stream.write('{"format":' + _json(FORMAT) + ',"source":' + _json(source) + ',"records":[')
    record_groups = conflicts = duplicate_rows = 0
    for identifier, _first in database.execute("SELECT id, MIN(seq) FROM rows GROUP BY id ORDER BY MIN(seq)"):
        if record_groups:
            stream.write(",")
        record_groups += 1
        conflicting_fields = [
            field
            for field in SCALAR_FIELDS
            if database.execute("SELECT COUNT(*) FROM vals WHERE id=? AND field=?", (identifier, field)).fetchone()[0]
            > 1
        ]
        conflicts += bool(conflicting_fields)
        duplicates = database.execute(
            "SELECT COUNT(*)-COUNT(DISTINCT raw) FROM rows WHERE id=?", (identifier,)
        ).fetchone()[0]
        duplicate_rows += duplicates
        stream.write('{"bacdive_id":' + _json(identifier) + ',"conflicting_fields":' + _json(conflicting_fields))
        stream.write(',"duplicate_rows":' + str(duplicates) + ',"values":{')
        for index, field in enumerate(VALUE_FIELDS):
            stream.write(("," if index else "") + _json(field) + ":")
            _array(
                stream,
                (
                    row[0]
                    for row in database.execute(
                        "SELECT value FROM vals WHERE id=? AND field=? ORDER BY seq, position", (identifier, field)
                    )
                ),
            )
        stream.write('},"category_paths":')
        _array(
            stream,
            (
                json.loads(row[0])
                for row in database.execute("SELECT value FROM paths WHERE id=? ORDER BY seq, value", (identifier,))
            ),
        )
        stream.write(',"occurrences":')
        _array(stream, _occurrences(database, identifier))
        stream.write("}")
    summary = {
        "source_records": count,
        "distinct_bacdive_ids": record_groups,
        "duplicate_rows": duplicate_rows,
        "conflicting_bacdive_ids": conflicts,
    }
    stream.write('],"summary":' + _json(summary) + "}\n")
    return summary


def export_evidence(input_path, output_path):
    """Publish a complete evidence file atomically, never replacing an existing path."""
    source_path = Path(input_path).resolve(strict=True)
    output = Path(output_path).absolute()
    if os.path.lexists(output):
        raise FileExistsError(f"Output already exists: {output}")
    if not source_path.is_file() or not output.parent.is_dir():
        raise ValueError("Input must be a file and the output parent must already exist")
    # The temporary file and destination share a filesystem. link() atomically
    # publishes only a complete file and refuses concurrent/existing targets.
    with tempfile.TemporaryDirectory(prefix=".isolation-evidence-", dir=output.parent) as private:
        private = Path(private)
        snapshot = private / "input.csv"
        with snapshot.open("wb") as stream:
            identity = _identity(source_path, stream)
        with closing(sqlite3.connect(private / "grouping.sqlite")) as database:
            _initialize(database)
            headers, columns, count = _ingest(database, snapshot)
            source = {"path": str(source_path), **identity, "headers": headers, "columns": columns}
            staged = private / "evidence.json"
            with staged.open("w", encoding="utf-8", newline="\n") as stream:
                summary = _write_document(database, stream, source, count)
                stream.flush()
                os.fsync(stream.fileno())
        if _identity(source_path) != identity:
            raise ValueError("Input bytes changed before publication")
        os.link(staged, output)
    return summary


def main(argv=None):
    """Run the explicit offline evidence export, without any pipeline activation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    print(_json(export_evidence(arguments.input, arguments.output)))


if __name__ == "__main__":
    main()
