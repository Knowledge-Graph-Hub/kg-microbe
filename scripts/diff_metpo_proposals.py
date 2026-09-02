#!/usr/bin/env python3
"""
Diff the kg-microbe METPO proposal templates against a released METPO.

Answers one question on demand: of the terms we have proposed upstream, which
have landed, which have landed changed, and which are still outstanding. The
previous version of this report lived in /tmp, so the instruction it carried --
"rerun whenever a new METPO release ships" -- could not be followed (#901).

Usage:
    poetry run python scripts/diff_metpo_proposals.py            # against METPO_VERSION
    poetry run python scripts/diff_metpo_proposals.py --release 2026-06-12
    poetry run python scripts/diff_metpo_proposals.py --json     # machine-readable
"""

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSES_TSV = REPO_ROOT / "mappings" / "metpo_proposal_classes_robot.tsv"
PROPERTIES_TSV = REPO_ROOT / "mappings" / "metpo_proposal_properties_robot.tsv"
RELEASE_JSON = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/{release}/metpo.json"
_TERM_IRI = re.compile(r"https://w3id\.org/metpo/(\d+)$")


def _curie(iri: str) -> Optional[str]:
    match = _TERM_IRI.match(iri)
    return "METPO:" + match.group(1) if match else None


def load_release(release: str, cache: Optional[Path] = None) -> Dict[str, dict]:
    """
    Load a released METPO as ``{CURIE: {label, definition, parents, deprecated}}``.

    :param release: Release tag, e.g. ``2026-06-12``.
    :param cache: Optional local metpo.json to read instead of fetching.
    :return: Mapping of CURIE to term facts.
    """
    if cache and cache.is_file():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        # Timeout on purpose: this is a script people are told to run, and a
        # hung fetch with no ceiling looks identical to a slow one.
        url = RELEASE_JSON.format(release=release)
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    graph = payload["graphs"][0]
    terms: Dict[str, dict] = {}
    for node in graph.get("nodes", []):
        curie = _curie(node["id"])
        if not curie:
            continue
        meta = node.get("meta", {}) or {}
        terms[curie] = {
            "label": node.get("lbl"),
            "definition": (meta.get("definition") or {}).get("val"),
            "deprecated": bool(meta.get("deprecated")),
            "parents": [],
        }
    for edge in graph.get("edges", []):
        if edge.get("pred") != "is_a":
            continue
        subject, obj = _curie(edge["sub"]), _curie(edge["obj"])
        if subject in terms and obj:
            terms[subject]["parents"].append(obj)
    return terms


def _rows(path: Path) -> List[dict]:
    """Read a ROBOT template, skipping the directive row beneath the header."""
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))[1:]


def compare(rows: List[dict], terms: Dict[str, dict], parent_field: str) -> dict:
    """
    Bucket proposed rows against a release.

    :param rows: Proposal template rows.
    :param terms: Release terms from :func:`load_release`.
    :param parent_field: Template column naming the parent/superproperty.
    :return: ``{"missing": [...], "differs": [...], "identical": [...]}``.
    """
    missing, differs, identical = [], [], []
    for row in rows:
        curie = row.get("proposed_id") or ""
        if not curie:
            continue
        term = terms.get(curie)
        if term is None:
            missing.append({"id": curie, "label": row.get("label"), "priority": row.get("priority")})
            continue
        deltas = []
        if row.get("label") and term["label"] and row["label"] != term["label"]:
            deltas.append(("label", row["label"], term["label"]))
        if row.get("definition") and term["definition"] and row["definition"] != term["definition"]:
            deltas.append(("definition", row["definition"], term["definition"]))
        proposed_parent = (row.get(parent_field) or "").strip()
        if proposed_parent and term["parents"] and proposed_parent not in term["parents"]:
            deltas.append(("parent", proposed_parent, "|".join(term["parents"])))
        entry = {"id": curie, "label": row.get("label"), "deltas": deltas, "deprecated": term["deprecated"]}
        (differs if deltas else identical).append(entry)
    return {"missing": missing, "differs": differs, "identical": identical}


def main() -> int:
    """Render the diff. Returns 0 always; this reports, it does not gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=None, help="METPO release tag (default: METPO_VERSION)")
    parser.add_argument("--cache", type=Path, default=None, help="Local metpo.json to use instead of fetching")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = parser.parse_args()

    release = args.release
    if release is None:
        sys.path.insert(0, str(REPO_ROOT))
        from kg_microbe.transform_utils.constants import METPO_VERSION

        release = METPO_VERSION

    terms = load_release(release, args.cache)
    result = {
        "release": release,
        "classes": compare(_rows(CLASSES_TSV), terms, "parent"),
        "properties": compare(_rows(PROPERTIES_TSV), terms, "domain"),
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"# METPO proposal vs release {release}\n")
    # A generated file must say it is generated and how. #901 existed because a
    # report told the reader to rerun a script that no longer existed; emitting
    # the command here keeps the answer with the artifact rather than in a second
    # document the reader has to know about (#921).
    print("Generated by `scripts/diff_metpo_proposals.py`. Do not edit by hand — regenerate with:\n")
    print("```bash")
    print(f"poetry run python scripts/diff_metpo_proposals.py --release {release} \\")
    print("    > docs/metpo/metpo_proposal_release_diff.md")
    print("```\n")
    print(
        "The proposal itself is generated too: edit `scripts/extract_metpo_proposals.py`, "
        "never the `mappings/metpo_proposal_*.tsv` artifacts.\n"
    )
    for kind in ("classes", "properties"):
        bucket = result[kind]
        total = sum(len(bucket[k]) for k in ("missing", "differs", "identical"))
        print(f"## {kind} ({total} proposed)\n")
        print(f"- landed unchanged: {len(bucket['identical'])}")
        print(f"- landed with differences: {len(bucket['differs'])}")
        print(f"- not in the release: {len(bucket['missing'])}\n")
        if bucket["missing"]:
            print("### Not in the release\n")
            for entry in bucket["missing"]:
                print(f"- `{entry['id']}` {entry['label']} ({entry['priority'] or 'no priority'})")
            print()
        if bucket["differs"]:
            print("### Landed, but our template disagrees\n")
            for entry in bucket["differs"]:
                flag = " **[deprecated upstream]**" if entry["deprecated"] else ""
                print(f"- `{entry['id']}` {entry['label']}{flag}")
                for field, ours, theirs in entry["deltas"]:
                    print(f"    - {field}: ours `{ours[:80]}` / release `{theirs[:80]}`")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
