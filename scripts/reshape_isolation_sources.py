#!/usr/bin/env python
"""
Reshape the flat BacDive isolation-sources export into per-strain records.

The export (data/raw/bacdive_isolation_sources.csv) is denormalized: one row
per ``strain x isolation-source category path``. The strain-level fields
(species, culture collection number, isolation_source, country, continent)
appear only on a strain's first row; each row carries one category path
(category_1 > category_2 > category_3). BacDive joins multiple values within a
cell using the ``###`` delimiter.

This script collapses the rows into one record per BacDive ID, conforming to
the ``Strain`` class in ``schema/bacdive_strain.yaml``. It writes the full set
as JSON Lines and a small YAML sample (a ``StrainCollection``) for validation.

Usage::

    python scripts/reshape_isolation_sources.py \
        --input data/raw/bacdive_isolation_sources.csv \
        --jsonl data/processed/bacdive_strains.jsonl \
        --sample-yaml schema/examples/bacdive_strains_sample.yaml \
        --sample-size 50
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

COLUMNS = [
    "id",
    "species",
    "culture_collection_number",
    "isolation_source",
    "country",
    "continent",
    "category_1",
    "category_2",
    "category_3",
]
MULTIVALUED = ["isolation_source", "country", "continent"]
DELIM = "###"


def _split_multi(value):
    """Split a BacDive '###'-delimited cell into a de-duplicated, ordered list."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    out, seen = [], set()
    for part in str(value).split(DELIM):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def _first(series):
    """First non-null value in a column (strain-level fields live on row 1)."""
    for v in series:
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            return str(v).strip()
    return None


def reshape(df: pd.DataFrame) -> list:
    """Collapse the flat rows into one record per BacDive ID."""
    strains = []
    for sid, grp in df.groupby("id", sort=False):
        rec = {"id": int(sid)}
        species = _first(grp["species"])
        if species:
            rec["species"] = species
        ccn = _first(grp["culture_collection_number"])
        if ccn:
            rec["culture_collection_number"] = ccn
        for col in MULTIVALUED:
            vals = []
            seen = set()
            for cell in grp[col]:
                for part in _split_multi(cell):
                    if part not in seen:
                        seen.add(part)
                        vals.append(part)
            if vals:
                rec[col] = vals
        # one category path per row (dedupe identical paths)
        paths, seen_paths = [], set()
        for _, row in grp.iterrows():
            path = {}
            for lvl in ("category_1", "category_2", "category_3"):
                v = row[lvl]
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    path[lvl] = str(v).strip()
            if path:
                key = tuple(sorted(path.items()))
                if key not in seen_paths:
                    seen_paths.add(key)
                    paths.append(path)
        if paths:
            rec["isolation_source_categories"] = paths
        strains.append(rec)
    return strains


def main():
    """Parse args, reshape the CSV, and write the JSONL set plus a YAML sample."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/raw/bacdive_isolation_sources.csv")
    ap.add_argument("--jsonl", default="data/processed/bacdive_strains.jsonl")
    ap.add_argument("--sample-yaml", default="schema/examples/bacdive_strains_sample.yaml")
    ap.add_argument("--sample-size", type=int, default=50)
    args = ap.parse_args()

    df = pd.read_csv(args.input, dtype=str)
    df.columns = COLUMNS
    strains = reshape(df)
    print(f"reshaped {len(df)} rows -> {len(strains)} strain records")

    jsonl_path = Path(args.jsonl)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w") as fh:
        for rec in strains:
            fh.write(json.dumps(rec) + "\n")
    print(f"wrote {jsonl_path}")

    sample = {"strains": strains[: args.sample_size]}
    sample_path = Path(args.sample_yaml)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    with sample_path.open("w") as fh:
        yaml.safe_dump(sample, fh, sort_keys=False, allow_unicode=True, width=100)
    print(f"wrote {sample_path} ({len(sample['strains'])} strains)")


if __name__ == "__main__":
    main()
