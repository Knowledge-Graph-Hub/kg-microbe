#!/usr/bin/env python
"""
Annotate BacDive isolation-source enums with ENVO ``meaning:`` CURIEs.

Grounds the permissible values of the enums in
``schema/bacdive_isolation_source_enums.yaml`` against ENVO, using the locally
downloaded ``data/raw/envo.json`` (OBO Graph JSON) as the term source -- no
network calls.

Matching is deliberately conservative: a BacDive value is matched only when its
label (the value with the leading ``#`` stripped) equals a non-obsolete ENVO
term's primary label, or one of its *exact* synonyms (case-insensitive).
Primary labels win over synonyms, and broad/related/narrow synonyms are ignored
(those produced homonym false positives such as the body-site "mouth" matching
the river-mouth synonym of *estuary*). Many BacDive categories are
host/medical/condition concepts with no ENVO equivalent; those are left
unannotated rather than fuzzy-matched.

For each matched value the script sets ``meaning`` (the ENVO CURIE) and a
``title`` (the ENVO primary label). It rewrites the enums file in place and
prints a per-enum coverage report.

Usage::

    python scripts/annotate_isolation_enums_envo.py \
        --envo data/raw/envo.json \
        --schema schema/bacdive_isolation_source_enums.yaml
"""

import argparse
import json
import re

import yaml

ENVO_IRI = re.compile(r"^http://purl\.obolibrary\.org/obo/(ENVO_\d+)$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def build_envo_index(envo_json_path: str):
    """
    Return ``{normalized_text: (CURIE, primary_label)}`` for non-obsolete ENVO terms.

    Two passes so primary labels always win over synonyms, and only exact
    synonyms are indexed (broad/related/narrow synonyms cause homonym errors).
    """
    with open(envo_json_path) as fh:
        graph = json.load(fh)["graphs"][0]

    envo_nodes = []
    for node in graph["nodes"]:
        m = ENVO_IRI.match(node.get("id", ""))
        if not m or not node.get("lbl"):
            continue
        meta = node.get("meta", {}) or {}
        if meta.get("deprecated") or node["lbl"].lower().startswith("obsolete"):
            continue
        envo_nodes.append((m.group(1).replace("_", ":"), node["lbl"], meta))

    index = {}
    # pass 1: primary labels
    for curie, label, _meta in envo_nodes:
        index.setdefault(_norm(label), (curie, label))
    # pass 2: exact synonyms only (do not override a primary label)
    for curie, label, meta in envo_nodes:
        for syn in meta.get("synonyms", []) or []:
            if syn.get("pred") == "hasExactSynonym" and syn.get("val"):
                index.setdefault(_norm(syn["val"]), (curie, label))
    return index


def strip_hash(value: str) -> str:
    """Strip the leading '#' that BacDive prefixes onto each category value."""
    return value[1:].strip() if value.startswith("#") else value.strip()


def main():
    """Parse args, build the ENVO index, annotate the enums, and rewrite the schema."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--envo", default="data/raw/envo.json")
    ap.add_argument("--schema", default="schema/bacdive_isolation_source_enums.yaml")
    args = ap.parse_args()

    index = build_envo_index(args.envo)
    print(f"ENVO terms indexed (labels + synonyms): {len(index)}")

    with open(args.schema) as fh:
        schema = yaml.safe_load(fh)

    total_matched = 0
    for enum_name, enum in schema.get("enums", {}).items():
        pvs = enum.get("permissible_values") or {}
        matched = 0
        for value, body in pvs.items():
            body = body or {}
            # idempotent: drop any prior ENVO annotation before re-matching
            body.pop("meaning", None)
            body.pop("title", None)
            hit = index.get(_norm(strip_hash(value)))
            if hit:
                curie, label = hit
                body["meaning"] = curie
                body["title"] = label
                matched += 1
            pvs[value] = body
        total_matched += matched
        print(f"  {enum_name}: {matched}/{len(pvs)} values mapped to ENVO")

    # ensure ENVO prefix is declared
    schema.setdefault("prefixes", {}).setdefault("ENVO", "http://purl.obolibrary.org/obo/ENVO_")

    with open(args.schema, "w") as fh:
        yaml.safe_dump(schema, fh, sort_keys=False, allow_unicode=True, width=100)
    print(f"total: {total_matched} permissible values annotated -> {args.schema}")


if __name__ == "__main__":
    main()
