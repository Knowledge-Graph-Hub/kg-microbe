#!/usr/bin/env python3
"""
Phase 2: Validate manually-curated rows in unified_chemical_mappings.tsv.gz
against EBI OLS4 ChEBI API.

For each CHEBI ID from non-chebi_xrefs sources, checks:
1. canonical_name matches OLS rdfs:label
2. Synonyms in our file are all in OLS (flag spurious)
3. Whether any OLS synonyms are missing from our file

Writes: mappings/manual_mapping_audit_report.tsv
"""

import gzip
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

HERE = Path(__file__).parent
MAPPINGS_FILE = HERE / "unified_chemical_mappings.tsv.gz"
REPORT_FILE = HERE / "manual_mapping_audit_report.tsv"
OLS_BASE = "https://www.ebi.ac.uk/ols4/api/ontologies/chebi/terms"


def ols_fetch(chebi_id: str) -> dict | None:
    """Fetch OLS4 term data for a CHEBI ID. Returns None on failure."""
    num = chebi_id.replace("CHEBI:", "")
    iri = f"http://purl.obolibrary.org/obo/CHEBI_{num}"
    url = f"{OLS_BASE}?iri={iri}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        terms = data.get("_embedded", {}).get("terms", [])
        if not terms:
            return None
        return terms[0]
    except (URLError, HTTPError, json.JSONDecodeError, KeyError):
        return None


def get_ols_synonyms(term: dict) -> set[str]:
    """Extract all synonym strings from an OLS term."""
    syns = set()
    anno = term.get("annotation", {})
    for key in ("hasExactSynonym", "hasRelatedSynonym", "hasBroadSynonym", "hasNarrowSynonym"):
        for s in anno.get(key, []):
            syns.add(s.strip())
    # Also add the label itself
    label = term.get("label", "")
    if label:
        syns.add(label.strip())
    return syns


def norm(s: str) -> str:
    return s.strip().lower()


def main() -> None:
    # Read file
    rows_by_id: dict[str, dict] = {}
    with gzip.open(MAPPINGS_FILE, "rt", encoding="utf-8") as f:
        header = f.readline()
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            chebi_id, canonical_name, formula, synonyms, xrefs, sources = parts[:6]
            rows_by_id[chebi_id] = {
                "canonical_name": canonical_name,
                "formula": formula,
                "synonyms": synonyms,
                "sources": sources,
            }

    # Identify rows to validate:
    # 1. Rows with NO chebi_xrefs source at all (purely manual, 208 rows)
    # 2. Rows with metatraits_chemical_synonyms manual source (75 rows)
    # Skip rows that are primarily backed by chebi_xrefs (authoritative ChEBI data)
    to_validate = {}
    for chebi_id, row in rows_by_id.items():
        src = row["sources"]
        src_parts = [s.strip() for s in src.split("|") if s.strip()]
        has_xrefs = any("chebi_xrefs" in s for s in src_parts)
        is_metatraits_manual = any("metatraits_chemical_synonyms" in s or
                                   "metatraits_special_chemicals" in s for s in src_parts)
        # Include: no chebi_xrefs, or metatraits manual entries
        if not has_xrefs or is_metatraits_manual:
            to_validate[chebi_id] = row

    print(f"Rows to validate: {len(to_validate)}", flush=True)

    results = []
    errors = []

    for i, (chebi_id, row) in enumerate(sorted(to_validate.items())):
        if i % 50 == 0:
            print(f"  {i}/{len(to_validate)} ...", flush=True)

        stored_name = row["canonical_name"]
        stored_syns_raw = [s.strip() for s in row["synonyms"].split("|") if s.strip()]
        stored_syns_norm = {norm(s) for s in stored_syns_raw}

        term = ols_fetch(chebi_id)
        time.sleep(0.12)  # ~8 req/s, well within OLS limits

        if term is None:
            results.append({
                "chebi_id": chebi_id,
                "stored_name": stored_name,
                "ols_name": "NOT_FOUND",
                "label_status": "NOT_FOUND",
                "spurious_synonyms": "",
                "ols_only_synonyms": "",
                "source": row["sources"][:80],
            })
            errors.append(chebi_id)
            continue

        ols_label = term.get("label", "").strip()
        ols_syns = get_ols_synonyms(term)
        ols_syns_norm = {norm(s) for s in ols_syns}

        # Label check
        if not stored_name:
            label_status = "EMPTY_STORED"
        elif norm(stored_name) == norm(ols_label):
            label_status = "OK"
        else:
            label_status = "MISMATCH"

        # Spurious: in our file but not in OLS
        spurious = [s for s in stored_syns_raw if norm(s) not in ols_syns_norm]

        # Missing: in OLS but not in our file (informational)
        ols_only = [s for s in sorted(ols_syns) if norm(s) not in stored_syns_norm][:5]  # cap at 5

        results.append({
            "chebi_id": chebi_id,
            "stored_name": stored_name,
            "ols_name": ols_label,
            "label_status": label_status,
            "spurious_synonyms": "|".join(spurious),
            "ols_only_synonyms": "|".join(ols_only),
            "source": row["sources"][:80],
        })

    # Write report
    cols = ["chebi_id", "stored_name", "ols_name", "label_status",
            "spurious_synonyms", "ols_only_synonyms", "source"]
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in results:
            f.write("\t".join(r.get(c, "") for c in cols) + "\n")

    # Summary
    label_ok = sum(1 for r in results if r["label_status"] == "OK")
    label_mismatch = sum(1 for r in results if r["label_status"] == "MISMATCH")
    label_empty = sum(1 for r in results if r["label_status"] == "EMPTY_STORED")
    not_found = sum(1 for r in results if r["label_status"] == "NOT_FOUND")
    has_spurious = sum(1 for r in results if r["spurious_synonyms"])

    print(f"\n=== Phase 2 Audit Report ===")
    print(f"Total validated: {len(results)}")
    print(f"  Label OK:         {label_ok}")
    print(f"  Label MISMATCH:   {label_mismatch}")
    print(f"  Empty stored:     {label_empty}")
    print(f"  NOT_FOUND in OLS: {not_found}")
    print(f"  Has spurious syns:{has_spurious}")
    print(f"\nReport written to: {REPORT_FILE}")

    if label_mismatch:
        print("\n--- Label mismatches ---")
        for r in results:
            if r["label_status"] == "MISMATCH":
                print(f"  {r['chebi_id']}: stored={r['stored_name']!r} | ols={r['ols_name']!r}")

    if has_spurious:
        print("\n--- Spurious synonyms ---")
        for r in results:
            if r["spurious_synonyms"]:
                print(f"  {r['chebi_id']} ({r['stored_name'][:25]}): {r['spurious_synonyms'][:80]}")


if __name__ == "__main__":
    main()
