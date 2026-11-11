#!/usr/bin/env python3
"""
Report source BacDive enzyme observations without EC annotations, offline.

Purpose: extract the useful diagnostic from legacy branch unmapped-enzymes,
commit 8785cb497; no graph edits or ontology resolution. Date: 2026-10-13.
Inputs: a local BacDive JSON array or record-keyed object.
Outputs: observations.tsv, labels.tsv, summary.json in a new report directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import closing
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = (
    "source_coordinate_json",
    "source_path_json",
    "bacdive_id",
    "ec_status",
    "enzyme_label_json",
    "enzyme_json",
    "classification_json",
)


def literal_json(value):
    """Encode JSON evidence without rounding decimal numbers or changing their type."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite source number")
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + literal_json(v) for k, v in sorted(value.items())) + "}"
    if isinstance(value, list):
        return "[" + ",".join(literal_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class UniqueObject(dict):
    """Flag duplicate keys without raising inside a C parser callback."""

    def __setitem__(self, key, value):
        """Remember duplicate keys so the complete record can be rejected."""
        if key in self:
            self.duplicate_key = key
        super().__setitem__(key, value)


def reject_duplicate_keys(value):
    """Reject duplicate nested keys after parsing, including the C parser backend."""
    if isinstance(value, dict):
        if hasattr(value, "duplicate_key"):
            raise ValueError(f"Duplicate JSON key: {value.duplicate_key!r}")
        for item in value.values():
            reject_duplicate_keys(item)
    elif isinstance(value, list):
        for item in value:
            reject_duplicate_keys(item)


def iter_records(stream):
    """Yield one array or object record at a time, including its native coordinate."""
    try:
        import ijson
    except ImportError as error:
        raise RuntimeError("ijson is required; run this diagnostic in the project's Poetry environment") from error
    first = b""
    while not first:
        char = stream.read(1)
        if not char:
            raise ValueError("Empty input JSON")
        if not char.isspace():
            first = char
    stream.seek(0)
    try:
        if first == b"[":
            records = enumerate(ijson.items(stream, "item", map_type=UniqueObject))
        elif first == b"{":
            records = ijson.kvitems(stream, "", map_type=UniqueObject)
        else:
            raise ValueError("Expected a JSON record array or record-keyed object")
        for coordinate, record in records:
            reject_duplicate_keys(record)
            yield coordinate, record
    except ijson.JSONError as error:
        raise ValueError("Malformed or truncated source JSON") from error


def source_hash(path):
    """Fingerprint source bytes using bounded reads."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_signature(path):
    """Detect replacement or in-place source writes, even when content is restored."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def ec_status(enzyme):
    """Separate missing annotations from malformed types; do not validate EC identities."""
    if "ec" not in enzyme:
        return "absent"
    value = enzyme["ec"]
    if value is None:
        return "null"
    if not isinstance(value, str):
        return "invalid_type"
    return "blank" if not value.strip() else "present"


def observations(record, coordinate):
    """Yield enzyme evidence without assigning identities or interpreting activity."""
    if not isinstance(record, dict):
        raise ValueError(f"Record {coordinate!r} is not an object")
    section = record.get("Physiology and metabolism")
    if section is None:
        return
    if not isinstance(section, dict):
        raise ValueError(f"Record {coordinate!r} has a non-object physiology section")
    enzymes = section.get("enzymes")
    if enzymes is None:
        return
    if not isinstance(enzymes, (dict, list)):
        raise ValueError(f"Record {coordinate!r} has an invalid enzymes container")
    general = record.get("General")
    identifier = general.get("BacDive-ID") if isinstance(general, dict) else None
    identifier = str(identifier) if type(identifier) in (str, int) else ""
    entries = enumerate(enzymes) if isinstance(enzymes, list) else [(None, enzymes)]
    for index, enzyme in entries:
        if not isinstance(enzyme, dict):
            raise ValueError(f"Record {coordinate!r} has a non-object enzyme at {index!r}")
        path = ["Physiology and metabolism", "enzymes"]
        if index is not None:
            path.append(index)
        yield {
            "source_coordinate_json": literal_json(coordinate),
            "source_path_json": literal_json(path),
            "bacdive_id": identifier,
            "ec_status": ec_status(enzyme),
            "enzyme_label_json": literal_json({"value": enzyme["value"]} if "value" in enzyme else {}),
            "enzyme_json": literal_json(enzyme),
            "classification_json": literal_json(record.get("Name and taxonomic classification")),
        }


def publish_directory(staging, destination):
    """Publish into an owned empty reservation, preserving other writers and original failures."""
    destination.mkdir()
    reserved = destination.lstat()

    def owned():
        """Recognize this process's reservation without following substituted symlinks."""
        current = destination.lstat()
        return (current.st_dev, current.st_ino, current.st_mode) == (reserved.st_dev, reserved.st_ino, reserved.st_mode)

    try:
        if not owned() or any(destination.iterdir()):
            raise ValueError("Output reservation changed; refusing to replace it")
        os.replace(staging, destination)
    except BaseException:
        try:
            if owned():
                destination.rmdir()  # Only our still-empty reservation, never another writer's content.
        except OSError:
            pass  # Cleanup must not mask the publication exception or remove populated directories.
        raise


def write_report(raw, output):
    """Publish a complete report atomically; never overwrite a prior report or source."""
    raw = Path(raw).resolve(strict=True)
    output = Path(output).absolute()
    if not raw.is_file():
        raise ValueError("Input must be a regular JSON file")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Report destination already exists: {output}")
    if output.resolve() == raw or output.resolve() in raw.parents:
        raise ValueError("Report destination must not contain the input")
    before_signature = source_signature(raw)
    before = source_hash(raw)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".missing-ec-", dir=output.parent) as temporary:
        stage = Path(temporary)
        report = stage / "report"
        report.mkdir()
        counts = Counter()
        with closing(sqlite3.connect(stage / "counts.sqlite")) as db, raw.open("rb") as stream:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("CREATE TABLE coordinates (coordinate TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE affected_ids (id TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE labels (label TEXT, status TEXT, n INTEGER, PRIMARY KEY(label, status))")
            with (report / "observations.tsv").open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for coordinate, record in iter_records(stream):
                    try:
                        db.execute("INSERT INTO coordinates VALUES (?)", (literal_json(coordinate),))
                    except sqlite3.IntegrityError as error:
                        raise ValueError(f"Duplicate source record key: {coordinate!r}") from error
                    counts["source_records"] += 1
                    affected = False
                    for row in observations(record, coordinate):
                        counts["enzyme_observations"] += 1
                        counts[row["ec_status"]] += 1
                        if row["ec_status"] == "present":
                            continue
                        affected = True
                        writer.writerow(row)
                        if row["bacdive_id"]:
                            db.execute("INSERT OR IGNORE INTO affected_ids VALUES (?)", (row["bacdive_id"],))
                        db.execute(
                            "INSERT INTO labels VALUES (?, ?, 1) ON CONFLICT(label, status) DO UPDATE SET n=n+1",
                            (row["enzyme_label_json"], row["ec_status"]),
                        )
                    counts["affected_source_records"] += int(affected)
                    if counts["source_records"] % 1000 == 0:
                        db.commit()
            with (report / "labels.tsv").open("w", encoding="utf-8", newline="") as target:
                writer = csv.writer(target, delimiter="\t", lineterminator="\n")
                writer.writerow(["enzyme_label_json", "ec_status", "observations"])
                writer.writerows(db.execute("SELECT label,status,n FROM labels ORDER BY n DESC,label,status"))
            unique_ids = db.execute("SELECT COUNT(*) FROM affected_ids").fetchone()[0]
        if source_hash(raw) != before or source_signature(raw) != before_signature:
            raise ValueError("Source changed while the report was being written")
        summary = {
            "schema_version": 1,
            "source": {"path": str(raw), "sha256": before, "bytes": before_signature[2]},
            "counts": {
                key: counts[key]
                for key in (
                    "source_records",
                    "enzyme_observations",
                    "affected_source_records",
                    "absent",
                    "null",
                    "blank",
                    "invalid_type",
                    "present",
                )
            },
            "distinct_reported_bacdive_ids": unique_ids,
            "interpretation": (
                "Absent/null/blank EC is a source annotation gap, not proof of an unmapped enzyme. "
                "invalid_type is reported separately. present means nonblank string, not validated EC identity. "
                "Activity is not filtered or interpreted. Counts concern observations and source records, not strains."
            ),
        }
        (report / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        publish_directory(report, output)
    return summary


def main(argv=None):
    """Run the diagnostic on explicit local input and report paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/bacdive_strains.json")
    parser.add_argument("--out", type=Path, default=ROOT / "data/reports/bacdive-missing-ec")
    args = parser.parse_args(argv)
    try:
        summary = write_report(args.raw, args.out)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Report failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
