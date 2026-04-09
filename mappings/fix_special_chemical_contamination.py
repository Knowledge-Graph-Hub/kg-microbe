#!/usr/bin/env python3
"""
Fix spurious synonyms in unified_chemical_mappings.tsv.gz introduced when
special_chemical_mappings.tsv had wrong CHEBI IDs (metatraits_special_chemicals[manual_2026-04-07]).

Each spurious synonym is moved from the wrong CHEBI ID to the correct one.
CHEBI:4767 (Elastin) and CHEBI:26835 (sulfur molecular entity) are added as new rows
since they were missing from the file.
"""

import gzip
from pathlib import Path

HERE = Path(__file__).parent
MAPPINGS_FILE = HERE / "unified_chemical_mappings.tsv.gz"
TAG = "metatraits_special_chemicals[corrected_2026-04-08]"
OLD_TAG = "metatraits_special_chemicals[manual_2026-04-07]"

# Spurious synonyms: wrong_chebi → [synonyms to remove]
REMOVE_FROM = {
    "CHEBI:26833": ["sulfur compounds"],
    "CHEBI:82594": ["amorphous iron (iii) oxide", "amorphous fe(iii) oxyhydroxid"],
    "CHEBI:42191": ["ethylenediaminetetraacetatoferrate"],
    "CHEBI:53248": ["elastin"],
    "CHEBI:52701": ["4-nitrophenyl beta-D-galactopyranoside"],
    "CHEBI:422":   ["lactate"],
    "CHEBI:68499": ["3-O-methylgallate"],
    "CHEBI:17895": ["casein"],          # correct ID is FOODON, so just remove
    "CHEBI:87626": ["4-nitrophenyl-alpha-D-maltopyranoside"],  # no valid CHEBI, just remove
    "CHEBI:16240": ["1,2-propandiol"],
    "CHEBI:4806":  ["esculin"],
}

# Correct synonyms to add: correct_chebi → [synonyms to add]
ADD_TO = {
    "CHEBI:26835": ["sulfur compounds"],
    "CHEBI:192761": ["amorphous iron (iii) oxide", "amorphous fe(iii) oxyhydroxid"],
    "CHEBI:30729": ["ethylenediaminetetraacetatoferrate"],
    "CHEBI:4767":  ["elastin"],
    "CHEBI:355715": ["4-nitrophenyl beta-D-galactopyranoside"],
    "CHEBI:16651": ["lactate"],
    "CHEBI:28647": ["3-O-methylgallate"],
    "CHEBI:16997": ["1,2-propandiol"],
    "CHEBI:4853":  ["esculin"],
}

# New rows to add (CHEBI IDs not yet in the file)
NEW_ROWS = {
    "CHEBI:4767":  "Elastin",
    "CHEBI:26835": "sulfur molecular entity",
}

COLS = ["chebi_id", "canonical_name", "formula", "synonyms", "xrefs", "sources"]


def norm(s: str) -> str:
    return s.strip().lower()


def parse_line(line: str) -> list[str]:
    """Split a TSV line preserving all columns (no quoting)."""
    return line.rstrip("\n").split("\t")


def row_to_dict(parts: list[str]) -> dict:
    d = {}
    for i, col in enumerate(COLS):
        d[col] = parts[i] if i < len(parts) else ""
    return d


def dict_to_line(d: dict) -> str:
    return "\t".join(d.get(c, "") for c in COLS) + "\n"


def main() -> None:
    # Read all lines
    with gzip.open(MAPPINGS_FILE, "rt", encoding="utf-8") as f:
        lines = f.readlines()

    header_line = lines[0]
    data_lines = lines[1:]

    # Parse into dicts
    rows = []
    for line in data_lines:
        parts = parse_line(line)
        rows.append(row_to_dict(parts))

    # Index by chebi_id
    by_id: dict[str, dict] = {}
    for r in rows:
        by_id[r["chebi_id"]] = r

    chebi_ids_in_file = set(by_id.keys())
    stats = {"removed": 0, "added": 0, "new_rows": 0}

    # --- Step 1: Remove spurious synonyms ---
    for chebi_id, bad_syns in REMOVE_FROM.items():
        if chebi_id not in by_id:
            print(f"WARN: {chebi_id} not found, skipping removal")
            continue
        row = by_id[chebi_id]
        syns = [s for s in row["synonyms"].split("|") if s.strip()] if row["synonyms"] else []
        bad_norm = {norm(s) for s in bad_syns}
        before = len(syns)
        syns = [s for s in syns if norm(s) not in bad_norm]
        removed = before - len(syns)
        if removed:
            row["synonyms"] = "|".join(syns)
            src = row.get("sources", "")
            if OLD_TAG in src:
                src = src.replace(OLD_TAG, TAG)
            elif TAG not in src:
                src = f"{src}|{TAG}" if src else TAG
            row["sources"] = src
            stats["removed"] += removed
            print(f"  Removed {removed} spurious synonym(s) from {chebi_id} ({row['canonical_name']})")

    # --- Step 2: Add correct synonyms to existing rows ---
    for chebi_id, good_syns in ADD_TO.items():
        if chebi_id not in chebi_ids_in_file:
            continue  # handled as new row below
        row = by_id[chebi_id]
        syns = [s for s in row["synonyms"].split("|") if s.strip()] if row["synonyms"] else []
        existing_norm = {norm(s) for s in syns}
        added = 0
        for s in good_syns:
            if norm(s) not in existing_norm:
                syns.append(s)
                existing_norm.add(norm(s))
                added += 1
        if added:
            row["synonyms"] = "|".join(syns)
            src = row.get("sources", "")
            if TAG not in src:
                src = f"{src}|{TAG}" if src else TAG
            row["sources"] = src
            stats["added"] += added
            print(f"  Added {added} synonym(s) to {chebi_id} ({row['canonical_name']})")

    # --- Step 3: Add new rows ---
    for chebi_id, canonical_name in NEW_ROWS.items():
        if chebi_id in chebi_ids_in_file:
            continue  # synonyms already handled above
        good_syns = ADD_TO.get(chebi_id, [])
        new_row = {
            "chebi_id":       chebi_id,
            "canonical_name": canonical_name,
            "formula":        "",
            "synonyms":       "|".join(good_syns),
            "xrefs":          "",
            "sources":        TAG,
        }
        rows.append(new_row)
        by_id[chebi_id] = new_row
        stats["new_rows"] += 1
        print(f"  Added new row: {chebi_id} ({canonical_name}) synonyms={good_syns}")

    # --- Write back ---
    with gzip.open(MAPPINGS_FILE, "wt", encoding="utf-8") as f:
        f.write(header_line)
        for row in rows:
            f.write(dict_to_line(row))

    print(f"\nDone. Removed: {stats['removed']}, Added: {stats['added']}, New rows: {stats['new_rows']}")
    print(f"Total rows: {len(rows)}")


if __name__ == "__main__":
    main()
