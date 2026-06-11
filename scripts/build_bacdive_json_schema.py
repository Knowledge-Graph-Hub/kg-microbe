#!/usr/bin/env python
"""
Build the LinkML schema for the full BacDive per-strain JSON.

End-to-end, reproducible pipeline:

1. Stream ``data/raw/bacdive_strains.json`` (a top-level array) and take an
   N-record sample, prefixing leading-digit keys with ``x`` so schema-automator
   can form valid class names (``16S sequences`` -> ``X16SSequence``; the API
   substrate codes ``2KG``/``2KT``/``3MDG``/``3OBU``/``5KG``).
2. Run schema-automator ``generalize-json`` on the sample (via ``uvx``) to get a
   baseline nested schema.
3. Refine the baseline against the sample's actual shapes:
   - object-valued fields -> their nested classes (``inlined``); list-bearing
     fields -> ``multivalued`` (BacDive's single-object-vs-list-of-objects
     inconsistency);
   - scalar leaves -> ``string`` (BacDive types numeric leaves inconsistently --
     pubmed/year/Chebi_ID as ints, GC content as ranges);
   - keys reused as both an object group and a scalar value -> ``slot_usage``
     overrides the scalar use to string inside the group class;
   - sample-derived enums are kept as documentation but not enforced;
   - the spurious tree-root/unique_keys are removed and a proper
     ``BacDiveStrainCollection`` container is added.

The schema validates JSON produced by ``scripts/normalize_bacdive_json.py``
(which applies the same key transforms + singleton-wrapping + leaf stringify).
Coverage is bounded by the sample size: fields absent from the first N records
are not modelled. Raise ``--sample-size`` to widen coverage.

Usage::

    python scripts/build_bacdive_json_schema.py \
        --input data/raw/bacdive_strains.json \
        --output schema/bacdive_strain_full.yaml \
        --sample-size 500
"""

import argparse
import json
import re
import subprocess
import tempfile
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

import ijson
import yaml

CONSTRAINTS = [
    "any_of",
    "exactly_one_of",
    "all_of",
    "none_of",
    "pattern",
    "minimum_value",
    "maximum_value",
    "equals_string",
    "equals_number",
]


def _conv(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def prefix_digit_keys(obj):
    """Prefix leading-digit keys with 'x' (recursively) for valid class names."""
    if isinstance(obj, dict):
        return {
            ("x" + k if re.match(r"^\d", str(k)) else k): prefix_digit_keys(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [prefix_digit_keys(x) for x in obj]
    return obj


def extract_sample(input_path: str, n: int):
    """Return the first n records with leading-digit keys prefixed."""
    out = []
    with open(input_path) as fh:
        for rec in ijson.items(fh, "item"):
            out.append(prefix_digit_keys(rec))
            if len(out) >= n:
                break
    return out


def classify(sample):
    """Return (object-keys, scalar-keys, list-of-object keys) seen anywhere in the sample."""
    obj, scal, lst = set(), set(), set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, dict):
                    obj.add(k)
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    obj.add(k)
                    lst.add(k)
                else:
                    scal.add(k)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for rec in sample:
        walk(rec)
    return obj, scal, lst


def _singular(n: str) -> str:
    if n.endswith("ies"):
        return n[:-3] + "y"
    if n.endswith(("ses", "xes", "zes", "ches", "shes")):
        return n[:-2]
    if n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    return n


def refine(baseline: dict, sample) -> dict:
    """Apply the data-driven refinement described in the module docstring."""
    classes = baseline["classes"]
    slots = baseline.get("slots", {})
    obj_keys, scal_keys, list_keys = classify(sample)

    def norm(x):
        return re.sub(r"[^a-z0-9]", "", x.lower())

    cbn = {}
    for cn in classes:
        cbn.setdefault(norm(cn), cn)

    def cls_for(name):
        n = norm(name)
        return cbn.get(n) or cbn.get(_singular(n))

    def set_range(name, sd):
        for c in CONSTRAINTS:
            sd.pop(c, None)
        cand = cls_for(name)
        mv = name in list_keys or sd.get("multivalued")
        if name in obj_keys and cand:
            sd["range"] = cand
            if mv:
                sd["multivalued"] = True
                sd["inlined_as_list"] = True
                sd.pop("inlined", None)
            else:
                sd["inlined"] = True
        else:
            sd["range"] = "string"
            if name in list_keys:
                sd["multivalued"] = True

    for name, sd in slots.items():
        if sd:
            set_range(name, sd)
    for cd in classes.values():
        for an, ad in (cd.get("attributes") or {}).items():
            if ad:
                set_range(an, ad)

    # disambiguate keys used as both an object group and a scalar value
    for key in sorted(obj_keys & scal_keys):
        c = cls_for(key)
        if c:
            classes[c].setdefault("slot_usage", {})[key] = {
                "range": "string",
                "inlined": False,
                "inlined_as_list": False,
                "multivalued": False,
            }

    if "_id" in slots:
        slots["_id"]["description"] = "MongoDB document id wrapper ({$oid: ...})."

    # metadata
    baseline["name"] = "BacDive"
    baseline["id"] = "https://w3id.org/kg-microbe/bacdive-strain-full"
    baseline["title"] = "BacDive strain (full JSON)"
    baseline["description"] = (
        "LinkML schema for the full BacDive per-strain JSON export "
        "(data/raw/bacdive_strains.json; a top-level array of strain records). "
        "Bootstrapped with schema-automator generalize-json over a sample, then refined "
        "(scripts/build_bacdive_json_schema.py): object fields are typed to their nested classes "
        "(inlined), list-bearing fields are multivalued (BacDive's single-object-vs-list-of-objects "
        "inconsistency), and scalar leaves are strings (BacDive types numeric leaves inconsistently). "
        "A few keys reused as both an object group and a scalar value are disambiguated with slot_usage. "
        "Sample-derived enums are kept as documentation but not enforced. Raw JSON must be normalized to "
        "validate -- see scripts/normalize_bacdive_json.py. Coverage is bounded by the build sample size. "
        "Sections: General; Name and taxonomic classification; Morphology; Culture and growth conditions; "
        "Physiology and metabolism; Isolation, sampling and environmental information; Safety information; "
        "Sequence information; Genome-based predictions; External links; Reference; _id."
    )
    baseline["prefixes"] = {
        "linkml": "https://w3id.org/linkml/",
        "BacDive": "https://w3id.org/kg-microbe/bacdive-strain-full/",
    }
    baseline["default_prefix"] = "BacDive"
    baseline["default_range"] = "string"
    baseline.setdefault("imports", ["linkml:types"])

    # restructure root: the generated tree-root is actually the record
    root = classes.pop("BacDiveStrainCollection")
    root.pop("tree_root", None)
    root.pop("unique_keys", None)
    root["description"] = "One BacDive strain record (one item of the top-level JSON array)."
    classes["BacDiveStrain"] = root
    classes["BacDiveStrainCollection"] = {
        "tree_root": True,
        "description": "Container for a set of BacDive strain records.",
        "attributes": {
            "strains": {
                "range": "BacDiveStrain",
                "multivalued": True,
                "inlined_as_list": True,
                "description": "The strain records.",
            }
        },
    }
    for cd in classes.values():
        cd.pop("unique_keys", None)

    ordered = OrderedDict()
    for k in [
        "name",
        "title",
        "id",
        "description",
        "prefixes",
        "default_prefix",
        "default_range",
        "imports",
        "classes",
        "slots",
        "enums",
    ]:
        if k in baseline:
            ordered[k] = baseline[k]
    for k in baseline:
        if k not in ordered:
            ordered[k] = baseline[k]
    return ordered


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(OrderedDict, lambda d, data: d.represent_dict(data.items()))


def main():
    """Run the sample -> generalize-json -> refine pipeline and write the schema."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/raw/bacdive_strains.json")
    ap.add_argument("--output", default="schema/bacdive_strain_full.yaml")
    ap.add_argument("--sample-size", type=int, default=500)
    args = ap.parse_args()

    sample = extract_sample(args.input, args.sample_size)
    print(f"sampled {len(sample)} records")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sf:
        json.dump(sample, sf, default=_conv)
        sample_path = sf.name
    baseline_path = sample_path + ".schema.yaml"
    cmd = [
        "uvx",
        "--from",
        "schema-automator",
        "schemauto",
        "generalize-json",
        sample_path,
        "-n",
        "BacDive",
        "--container-class-name",
        "BacDiveStrainCollection",
        "--omit-null",
        "-o",
        baseline_path,
    ]
    subprocess.run(cmd, check=True)  # noqa: S603 - fixed, trusted schema-automator call via uvx
    baseline = yaml.safe_load(open(baseline_path))
    schema = refine(baseline, sample)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        yaml.dump(schema, fh, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    print(
        f"wrote {args.output}: {len(schema['classes'])} classes, {len(schema.get('enums', {}))} enums"
    )


if __name__ == "__main__":
    main()
