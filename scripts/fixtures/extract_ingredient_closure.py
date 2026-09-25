"""Extract exact SemSQL rows needed to finalize the legacy broader-mapping fixture."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def sha256(path):
    """Fingerprint the complete source using bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    """Retain source statements for both seeds and their asserted ancestors or replacements."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = sha256(args.database)
    selected, pending = set(), {"CHEBI:16763", "CHEBI:60004"}
    rows = []
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(statements)")]
        while pending:
            subject = pending.pop()
            if subject in selected:
                continue
            selected.add(subject)
            for row in connection.execute("SELECT * FROM statements WHERE subject=?", (subject,)):
                rows.append(list(row))
                record = dict(zip(columns, row, strict=True))
                if record["predicate"] in {"rdfs:subClassOf", "IAO:0100001"} and record["object"]:
                    pending.add(record["object"])
    if before != sha256(args.database):
        raise ValueError("Authority changed during extraction")
    payload = {"columns": columns, "statements": sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "legacy-closure-statements.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    origin = {
        "source": "data/raw/chebi.db",
        "source_sha256": before,
        "source_bytes": args.database.stat().st_size,
        "seed_ids": ["CHEBI:16763", "CHEBI:60004"],
        "selected_subjects": sorted(selected),
        "closure": "All asserted rdfs:subClassOf ancestors and IAO:0100001 replacements; full original statement rows",
        "statements": len(rows),
        "fixture_sha256": sha256(path),
        "notes": "The database hash is independent of the ChEBI JSON excerpt; no full production closure is certified.",
    }
    (args.output / "legacy-closure-origin.json").write_text(json.dumps(origin, indent=2, sort_keys=True) + "\n")
    print(json.dumps(origin, indent=2))


if __name__ == "__main__":
    main()
