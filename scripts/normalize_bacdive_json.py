#!/usr/bin/env python
"""
Normalize the full BacDive JSON so it conforms to ``bacdive_strain_full.yaml``.

The BacDive per-strain JSON (``data/raw/bacdive_strains.json``, a top-level array
of strain records) has three features that block direct LinkML validation:

1. **Single-vs-multiple inconsistency.** ~45 fields are a single object when a
   strain has one value and a list of objects when it has several. The schema
   models them ``multivalued``; this script wraps singleton objects in a list.
2. **Leading-digit keys.** A few keys (``16S sequence``/``16S sequences`` and the
   API substrate codes ``2KG``/``2KT``/``3MDG``/``3OBU``/``5KG``) cannot become
   valid LinkML class names; the schema prefixes them with ``x``, and so does this.
3. **Punctuation in keys.** LinkML maps slot names to JSON-Schema property names
   via ``underscore()`` (hyphens/spaces/commas -> ``_``; ``@``/``$`` kept), so
   ``BacDive-ID`` becomes ``BacDive_ID``. This script applies the same transform
   to the data keys so they match the generated schema.

The set of multivalued fields is read from the schema, so the two stay in sync.

Usage::

    python scripts/normalize_bacdive_json.py \
        --input data/raw/bacdive_strains.json \
        --output data/processed/bacdive_strains_normalized.json \
        [--limit N] [--container]
"""

import argparse
import json
import re
from decimal import Decimal

import ijson
import yaml
from linkml_runtime.utils.formatutils import underscore


def clean_key(k: str) -> str:
    """Match a JSON key to the schema's property name (x-prefix digits, then underscore())."""
    k = "x" + k if re.match(r"^\d", str(k)) else str(k)
    return underscore(k)


def multivalued_slot_names(schema_path: str) -> set:
    """Collect every multivalued slot/attribute name (as a JSON property name) from the schema."""
    s = yaml.safe_load(open(schema_path))
    names = set()
    for name, sd in (s.get("slots") or {}).items():
        if sd and sd.get("multivalued"):
            names.add(underscore(name))
    for cd in (s.get("classes") or {}).values():
        for name, sd in (cd.get("attributes") or {}).items():
            if sd and sd.get("multivalued"):
                names.add(underscore(name))
    return names


def normalize(obj, multivalued: set):
    """Recursively normalize keys (x-prefix + underscore) and wrap singleton multivalued objects."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = clean_key(k)
            v = normalize(v, multivalued)
            # wrap a singleton object into a list for multivalued fields
            if key in multivalued and isinstance(v, dict):
                v = [v]
            out[key] = v
        return out
    if isinstance(obj, list):
        return [normalize(x, multivalued) for x in obj]
    # scalar leaf: stringify. BacDive types numeric leaves inconsistently
    # (pubmed/year/Chebi_ID as ints, GC content as ranges), so the schema models
    # every leaf as a string and the data is coerced to match.
    if isinstance(obj, bool):
        return str(obj).lower()
    if isinstance(obj, (int, float, Decimal)):
        d = Decimal(str(obj))
        return str(int(d)) if d == d.to_integral_value() else str(float(d))
    return obj


def main():
    """Stream the BacDive JSON, normalize each record, and write the result."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/raw/bacdive_strains.json")
    ap.add_argument("--output", default="data/processed/bacdive_strains_normalized.json")
    ap.add_argument("--schema", default="schema/bacdive_strain_full.yaml")
    ap.add_argument(
        "--limit", type=int, default=0, help="only process the first N records (0 = all)"
    )
    ap.add_argument("--container", action="store_true", help="wrap records as {'strains': [...]}")
    args = ap.parse_args()

    mv = multivalued_slot_names(args.schema)
    records = []
    with open(args.input) as fh:
        for rec in ijson.items(fh, "item"):
            records.append(normalize(rec, mv))
            if args.limit and len(records) >= args.limit:
                break
    payload = {"strains": records} if args.container else records
    from pathlib import Path

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(args.output, "w"))
    print(f"normalized {len(records)} records -> {args.output} ({len(mv)} multivalued fields)")


if __name__ == "__main__":
    main()
