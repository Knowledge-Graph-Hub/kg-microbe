#!/usr/bin/env python3
"""
Fix remaining issues in unified_chemical_mappings.tsv.gz:

1. Fix 4 confirmed label mismatches
2. Remove 28 malformed-format CHEBI IDs (leading zeros or >7 digits)
3. OLS batch lookup for 99 normal-format rows with empty canonical names:
   - Found → fill canonical_name
   - Not found → remove (invalid MediaDive CHEBI IDs)
"""

import gzip
import json
import re
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import urlopen, Request

HERE = Path(__file__).parent
MAPPINGS_FILE = HERE / "unified_chemical_mappings.tsv.gz"
TAG_FIX = "manual_corrections[2026-04-08]"
COLS = ["chebi_id", "canonical_name", "formula", "synonyms", "xrefs", "sources"]

# ── 1. Label mismatches ──────────────────────────────────────────────────────
# CHEBI:26130: "pigmented" → "biological pigment" (correct OLS label)
# CHEBI:37766: wrong CHEBI for "phenazine"; OLS label is "azinic acid" — remove synonym
# CHEBI:46850: wrong CHEBI for "poly-L-lysine"; OLS label is "organoammonium salt" — remove synonym
# CHEBI:77041: wrong CHEBI for "3-nitropropanoic acid"; OLS label is "3-oxotetradecanedioyl-CoA(5-)" — remove synonym

LABEL_FIXES = {
    "CHEBI:26130": "biological pigment",  # correct OLS label; synonyms are fine
}

# Remove wrong synonyms from these entries (wrong CHEBI IDs used in metatraits)
REMOVE_WRONG_SYNS = {
    "CHEBI:37766": {"phenazine", "phenazines"},          # azinic acid, not phenazine
    "CHEBI:46850": {"poly-l-lysine", "poly(l-lysine) polymer"},  # organoammonium salt, not poly-L-lysine
    "CHEBI:77041": {"3-nitropropanoic acid", "3-nitropropanoate"},  # wrong compound entirely
}


# ── OLS helper ───────────────────────────────────────────────────────────────
OLS_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms"


def ols_fetch(chebi_id: str) -> dict | None:
    """Return OLS term dict or None on failure."""
    num = chebi_id.replace("CHEBI:", "")
    iri = f"http://purl.obolibrary.org/obo/CHEBI_{num}"
    url = f"{OLS_BASE}?iri={iri}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        terms = data.get("_embedded", {}).get("terms", [])
        return terms[0] if terms else None
    except (URLError, HTTPError, json.JSONDecodeError, KeyError):
        return None


def is_ols_quirk_label(label: str, chebi_id: str) -> bool:
    """OLS4 sometimes returns 'CHEBI_NNNNN' as label — not a real mismatch."""
    num = chebi_id.replace("CHEBI:", "")
    return label == f"CHEBI_{num}"


# ── Malformed ID check ───────────────────────────────────────────────────────
MALFORMED_RE = re.compile(r"^CHEBI:0\d+|^CHEBI:\d{8,}")


def is_malformed(chebi_id: str) -> bool:
    return bool(MALFORMED_RE.match(chebi_id))


def norm(s: str) -> str:
    return s.strip().lower()


def main() -> None:
    # Read all rows
    with gzip.open(MAPPINGS_FILE, "rt", encoding="utf-8") as f:
        header_line = f.readline()
        data_lines = f.readlines()

    rows = []
    for line in data_lines:
        parts = line.rstrip("\n").split("\t")
        d = {col: (parts[i] if i < len(parts) else "") for i, col in enumerate(COLS)}
        rows.append(d)

    by_id = {r["chebi_id"]: r for r in rows}

    stats = {
        "label_fixed": 0,
        "wrong_syns_removed": 0,
        "malformed_removed": 0,
        "empty_name_filled": 0,
        "empty_name_removed": 0,
    }

    # ── Step 1: Fix label mismatches ─────────────────────────────────────────
    for chebi_id, correct_name in LABEL_FIXES.items():
        if chebi_id in by_id:
            r = by_id[chebi_id]
            old_name = r["canonical_name"]
            r["canonical_name"] = correct_name
            # Ensure correct name is in synonyms
            syns = [s for s in r["synonyms"].split("|") if s.strip()]
            syns_norm = {norm(s) for s in syns}
            if norm(correct_name) not in syns_norm:
                syns.insert(0, correct_name)
            r["synonyms"] = "|".join(syns)
            src = r["sources"]
            if TAG_FIX not in src:
                r["sources"] = f"{src}|{TAG_FIX}" if src else TAG_FIX
            stats["label_fixed"] += 1
            print(f"  Label fixed: {chebi_id}: {old_name!r} → {correct_name!r}")

    # ── Step 2: Remove wrong synonyms from mismatched CHEBI IDs ─────────────
    for chebi_id, bad_syns_norm in REMOVE_WRONG_SYNS.items():
        if chebi_id in by_id:
            r = by_id[chebi_id]
            syns = [s for s in r["synonyms"].split("|") if s.strip()]
            before = len(syns)
            syns = [s for s in syns if norm(s) not in bad_syns_norm]
            removed = before - len(syns)
            if removed:
                r["synonyms"] = "|".join(syns)
                src = r["sources"]
                if TAG_FIX not in src:
                    r["sources"] = f"{src}|{TAG_FIX}" if src else TAG_FIX
                stats["wrong_syns_removed"] += removed
                print(f"  Wrong syns removed from {chebi_id}: {removed} synonym(s)")

    # ── Step 3: Identify malformed IDs to remove ─────────────────────────────
    malformed_ids = {r["chebi_id"] for r in rows if is_malformed(r["chebi_id"])}
    print(f"\nMalformed IDs to remove: {len(malformed_ids)}")

    # ── Step 4: OLS lookup for normal-format empty canonical names ────────────
    empty_name_rows = [r for r in rows
                       if not r["canonical_name"].strip()
                       and not is_malformed(r["chebi_id"])
                       and re.match(r"^CHEBI:\d{1,7}$", r["chebi_id"])]
    print(f"Normal-format empty canonical name rows to query: {len(empty_name_rows)}")

    remove_ids = set(malformed_ids)
    fill_results = {}

    for i, row in enumerate(empty_name_rows):
        chebi_id = row["chebi_id"]
        if i % 20 == 0:
            print(f"  OLS lookup {i}/{len(empty_name_rows)} ...", flush=True)
        term = ols_fetch(chebi_id)
        time.sleep(0.12)
        if term is None:
            remove_ids.add(chebi_id)
            stats["empty_name_removed"] += 1
            print(f"    NOT_FOUND → remove {chebi_id} ({row['synonyms'][:40]!r})")
        else:
            label = term.get("label", "").strip()
            if not label or is_ols_quirk_label(label, chebi_id):
                remove_ids.add(chebi_id)
                stats["empty_name_removed"] += 1
                print(f"    OLS quirk label → remove {chebi_id}")
            else:
                fill_results[chebi_id] = label
                stats["empty_name_filled"] += 1

    # Fill canonical names
    for chebi_id, label in fill_results.items():
        if chebi_id in by_id:
            by_id[chebi_id]["canonical_name"] = label
            src = by_id[chebi_id]["sources"]
            if TAG_FIX not in src:
                by_id[chebi_id]["sources"] = f"{src}|{TAG_FIX}" if src else TAG_FIX
            print(f"  Filled {chebi_id}: {label!r}")

    # ── Write back ────────────────────────────────────────────────────────────
    kept_rows = [r for r in rows if r["chebi_id"] not in remove_ids]
    removed_count = len(rows) - len(kept_rows)
    print(f"\nRemoving {removed_count} rows total ({len(remove_ids)} unique IDs)")

    with gzip.open(MAPPINGS_FILE, "wt", encoding="utf-8") as f:
        f.write(header_line)
        for r in kept_rows:
            f.write("\t".join(r.get(c, "") for c in COLS) + "\n")

    print(f"\n=== Fix Summary ===")
    print(f"  Labels fixed:         {stats['label_fixed']}")
    print(f"  Wrong syns removed:   {stats['wrong_syns_removed']}")
    print(f"  Malformed IDs removed:{stats['malformed_removed'] or len(malformed_ids)}")
    print(f"  Empty name filled:    {stats['empty_name_filled']}")
    print(f"  Empty name removed:   {stats['empty_name_removed']}")
    print(f"  Total rows after:     {len(kept_rows)}")


if __name__ == "__main__":
    main()
