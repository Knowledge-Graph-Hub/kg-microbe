#!/usr/bin/env python3
"""
Profile an immutable KG-Microbe snapshot for the 2026-11-03 curation plan.

Inputs: snapshot directory containing KGX TSVs and manifest.json; optional prior profile.
Output: new JSON counts, field coverage, byte hashes and optional comparison.
Purpose: size the edge-curation architecture; literal TSV repair for #1719, 2026-11-04.
"""

import argparse
import csv
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def profile(snapshot, max_rows):
    """Stream records with bounded-memory counters, preserving raw field values."""
    manifest_path = snapshot / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    result = {
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": str(snapshot.resolve()),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "provenance": manifest.get("provenance", {}),
        "max_rows_per_file": max_rows,
        "members": {},
    }
    for name in ("merged-kg_edges.tsv", "merged-kg_nodes.tsv"):
        path = snapshot / name
        started = time.monotonic()
        digest = hashlib.sha256()
        counters = {}
        nonempty = Counter()
        source_predicate = Counter()
        row_width_errors = 0
        rows = 0
        byte_count = 0
        complete = True
        before = path.stat()
        with path.open("rb") as handle:

            def lines(current_digest=digest):
                """Hash exact physical lines before interpreting their literal TSV cells."""
                nonlocal byte_count
                for line in handle:
                    current_digest.update(line)
                    byte_count += len(line)
                    yield line.decode("utf-8")

            reader = csv.reader(lines(), delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None)
            header = next(reader)
            fields = (
                ("predicate", "relation", "primary_knowledge_source", "knowledge_level", "agent_type")
                if name.endswith("edges.tsv")
                else ("category",)
            )
            indexes = {field: header.index(field) for field in fields}
            counters = {field: Counter() for field in fields}
            if name.endswith("edges.tsv"):
                counters["predicate_namespace"] = Counter()
            for row in reader:
                rows += 1
                if len(row) != len(header):
                    row_width_errors += 1
                for field, value in zip(header, row, strict=False):
                    if value:
                        nonempty[field] += 1
                for field, index in indexes.items():
                    counters[field][row[index] if index < len(row) else "<missing>"] += 1
                if name.endswith("edges.tsv") and len(row) == len(header):
                    predicate = row[indexes["predicate"]]
                    source = row[indexes["primary_knowledge_source"]]
                    source_predicate[(source, predicate)] += 1
                    counters["predicate_namespace"][predicate.split(":", 1)[0]] += 1
                if max_rows and rows >= max_rows:
                    complete = False
                    break
        after = path.stat()
        expected = manifest["members"][name]
        stable = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        # A partial scan never claims to verify the complete member hash.
        result["members"][name] = {
            "rows": rows,
            "bytes_read": byte_count,
            "file_bytes": before.st_size,
            "complete_scan": complete,
            "source_unchanged_during_scan": stable,
            "sha256": digest.hexdigest() if complete else None,
            "matches_manifest": (
                stable
                and digest.hexdigest() == expected["sha256"]
                and rows == expected["rows"]
                and byte_count == expected["bytes"]
            )
            if complete
            else None,
            "row_width_errors": row_width_errors,
            "header": header,
            "nonempty_fields": dict(nonempty),
            "counts": {field: dict(count.most_common()) for field, count in counters.items()},
            "source_predicate_counts": [
                {"source": source, "predicate": predicate, "rows": count}
                for (source, predicate), count in source_predicate.most_common()
            ],
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    return result


def compare_profiles(baseline, current):
    """Compare measured fields only after both scans verify the same source snapshot."""
    if baseline["manifest_sha256"] != current["manifest_sha256"]:
        raise ValueError("Profile comparison requires the same source manifest")
    if set(baseline["members"]) != set(current["members"]):
        raise ValueError("Profile comparison requires the same source members")
    if not all(
        member["complete_scan"] is True and member["matches_manifest"] is True
        for profile_result in (baseline, current)
        for member in profile_result["members"].values()
    ):
        raise ValueError("Profile comparison requires complete manifest-verified scans")
    fields = (
        "rows",
        "bytes_read",
        "file_bytes",
        "sha256",
        "row_width_errors",
        "header",
        "nonempty_fields",
        "counts",
        "source_predicate_counts",
    )
    members = {}
    for name, member in current["members"].items():
        previous = baseline["members"][name]
        changed = [field for field in fields if previous[field] != member[field]]
        members[name] = {
            "changed_fields": changed,
            "raw_counts_equal": previous["counts"] == member["counts"],
            "nonempty_fields_equal": previous["nonempty_fields"] == member["nonempty_fields"],
            "statistics_equal": not changed,
        }
    return {
        "same_source_manifest": True,
        "members": members,
        "statistics_equal": all(member["statistics_equal"] for member in members.values()),
    }


def main():
    """Write a bounded or complete profile to the requested output path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--compare-profile", type=Path, help="Compare complete verified counts with a prior profile")
    args = parser.parse_args()
    if args.max_rows < 0:
        parser.error("--max-rows must be nonnegative")
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists; use a new profile path")
    baseline_bytes = args.compare_profile.read_bytes() if args.compare_profile else None
    baseline = json.loads(baseline_bytes) if baseline_bytes is not None else None
    csv.field_size_limit(16 * 1024 * 1024)
    result = profile(args.snapshot, args.max_rows)
    if baseline is not None:
        result["comparison"] = compare_profiles(baseline, result)
        result["comparison"].update(
            baseline_path=str(args.compare_profile.resolve()),
            baseline_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    summary = {
        name: {key: value[key] for key in ("rows", "complete_scan", "matches_manifest", "elapsed_seconds")}
        for name, value in result["members"].items()
    }
    if "comparison" in result:
        summary["comparison"] = result["comparison"]
    print(json.dumps(summary, indent=2))
    if "comparison" in result and not result["comparison"]["statistics_equal"]:
        parser.exit(1, "Profile statistics changed; inspect the saved comparison before reusing prior numbers.\n")


if __name__ == "__main__":
    main()
