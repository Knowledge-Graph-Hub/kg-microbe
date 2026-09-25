"""Reproduce a legacy mapping excerpt without changing its rows or metadata semantics."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


def main():
    """Select all incident rows using the recorded source hash and endpoint IDs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    origin = json.loads(args.origin.read_text())
    digest = hashlib.sha256()
    with args.source_file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != origin["source_sha256"]:
        raise ValueError("Legacy source differs from the recorded pin")
    selected = set(origin["selected_endpoints"])
    with gzip.open(args.source_file, "rt") as stream:
        metadata = []
        for line in stream:
            if not line.startswith("#"):
                header = line.rstrip("\n").split("\t")
                break
            metadata.append(line)
        reader = csv.DictReader(stream, fieldnames=header, delimiter="\t")
        rows = [row for row in reader if row["subject_id"] in selected or row["object_id"] in selected]
    with args.output.open("w", newline="") as stream:
        stream.writelines(metadata)
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if hashlib.sha256(args.output.read_bytes()).hexdigest() != origin["fixture_sha256"]:
        raise ValueError("Regenerated excerpt differs from the recorded fixture")
    print(f"Reproduced {len(rows)} legacy rows byte for byte.")


if __name__ == "__main__":
    main()
