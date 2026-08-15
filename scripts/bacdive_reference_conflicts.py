#!/usr/bin/env python3
"""
Report BacDive strains whose per-reference phenotype observations disagree (#737).

BacDive stores some phenotype blocks as an **array of per-reference observations**.
Since #474 traverses those arrays, references that disagree produce contradictory
edges for the same strain — and nothing in ``edges.tsv`` marks them as such: both
rows carry the same ``primary_knowledge_source`` and there is no slot for the
``@ref`` that would tell them apart.

Issue #737 quoted "4,278 strains" from an ad-hoc measurement that was never
persisted. This script re-derives that number, writes the offending rows to a TSV
so they can be inspected, and — the part the original count missed — **separates
genuine contradictions from mere differences in specificity**.

That distinction matters. ``anaerobe`` vs ``obligate anaerobe`` is not a
conflict: METPO already relates the two (``METPO:1000607 obligately anaerobic``
``subclass_of`` ``METPO:1000603 anaerobic``), so a strain can truthfully bear
both edges and a resolver that picked one would discard a true statement.
``yes`` vs ``no`` motility is a real contradiction. Only the latter needs a
policy.

Measured 2026-08-15 against the full dump, restricted to #737's eight fields,
this reproduces its 4,278 exactly — and splits it:

* **specificity 955** — all oxygen tolerance, and it is *not* the majority
  there. 854 are ``aerobe | obligate aerobe`` and 101 ``anaerobe | obligate
  anaerobe``: 36% of oxygen-tolerance disagreements, 22% of the 4,278. An
  earlier guess that subsumption explained most of #737 was wrong; the
  dominant oxygen-tolerance patterns are genuine contradictions
  (``aerobe | facultative anaerobe`` 440, ``anaerobe | microaerophile`` 299).
* **contradiction 3,342 strains** — the set that needs a policy.
* **unresolved** — a value with no METPO term, so the relation cannot be
  judged. Evidence of a mapping gap, not of a conflict.

The script also scans four fields #737 did not (``colony color``,
``colony shape``, ``type of spore``, ``forms multicellular complex``), which
add 1,793 more disagreeing observations. ``colony color`` alone contributes
1,196, every one ``unresolved`` — colours have no METPO terms, so that field is
a curation gap rather than a contradiction, and should not be folded into a
conflict headline.

Usage::

    poetry run python scripts/bacdive_reference_conflicts.py
    poetry run python scripts/bacdive_reference_conflicts.py --out /tmp/conflicts.tsv

Exit codes: 0 always — this reports, it does not gate. Wire it into CI only once
the counts are expected to be stable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO_ROOT / "data" / "raw" / "bacdive_strains.json"
DEFAULT_OUT = REPO_ROOT / "data" / "transformed" / "bacdive" / "reference_conflicts.tsv"
METPO_NODES = REPO_ROOT / "data" / "transformed" / "ontologies" / "metpo_nodes.tsv"
METPO_EDGES = REPO_ROOT / "data" / "transformed" / "ontologies" / "metpo_edges.tsv"

#: The eight phenotype paths #737 measured: (section, key).
PHENOTYPE_PATHS: Tuple[Tuple[str, str], ...] = (
    ("Physiology and metabolism", "oxygen tolerance"),
    ("Safety information", "risk assessment"),
    ("Morphology", "cell morphology"),
    ("Morphology", "colony morphology"),
    ("Physiology and metabolism", "spore formation"),
    ("Physiology and metabolism", "nutrition type"),
    ("Physiology and metabolism", "halophily"),
    ("Morphology", "multicellular morphology"),
)

#: Within a block, the field carrying the observation. BacDive is not uniform:
#: the block key is not always the value key (``risk assessment`` holds
#: ``biosafety level``), and morphology blocks pack several observations into
#: one dict, so each is treated as its own comparable field.
VALUE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "oxygen tolerance": ("oxygen tolerance",),
    "risk assessment": ("biosafety level",),
    "cell morphology": ("cell shape", "motility", "gram stain"),
    "colony morphology": ("colony color", "colony shape"),
    "spore formation": ("spore formation", "type of spore"),
    "nutrition type": ("type",),
    "halophily": ("halophily level",),
    "multicellular morphology": ("forms multicellular complex",),
}

REF_KEY = "@ref"


def load_metpo() -> Tuple[Dict[str, str], Dict[str, set]]:
    """
    Build a raw-value -> METPO CURIE index and the CURIE subsumption closure.

    Resolution must go through **synonyms**, not labels. BacDive writes
    ``anaerobe`` and ``obligate anaerobe``; METPO's labels are ``anaerobic`` and
    ``obligately anaerobic``, with the BacDive spellings carried as synonyms. A
    label-only match therefore resolves nothing and reports every oxygen-tolerance
    disagreement as a contradiction — which is how the "4,278 contradictions"
    framing in #737 overstates the problem.

    :return: ``({alias: curie}, {curie: {ancestor curie, ...}})``; both empty when
        the extracts are absent.
    """
    if not (METPO_NODES.is_file() and METPO_EDGES.is_file()):
        return {}, {}

    alias_to_curie: Dict[str, str] = {}
    known: set = set()
    with METPO_NODES.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            curie = (row.get("id") or "").strip()
            if not curie:
                continue
            known.add(curie)
            aliases = [(row.get("name") or "").strip()]
            aliases += [s.strip() for s in (row.get("synonym") or "").split("|")]
            for alias in aliases:
                if alias:
                    # First writer wins: the primary label is offered first, so a
                    # synonym shared by two terms cannot displace an exact label.
                    alias_to_curie.setdefault(alias.lower(), curie)

    parents: Dict[str, set] = defaultdict(set)
    with METPO_EDGES.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if (row.get("predicate") or "") != "biolink:subclass_of":
                continue
            child, parent = (row.get("subject") or ""), (row.get("object") or "")
            if child in known and parent in known:
                parents[child].add(parent)

    # Transitive closure — "strictly anaerobic" is two hops from "anaerobic".
    closed: Dict[str, set] = {}
    for curie in parents:
        seen, stack = set(), list(parents[curie])
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(parents.get(node, ()))
        closed[curie] = seen
    return alias_to_curie, closed


def _normalise(value) -> str:
    """Render an observation as a comparable string."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip().lower()


def observations(block, field: str) -> List[Tuple[str, str]]:
    """
    Pull ``(ref, value)`` pairs for one field out of a phenotype block.

    Handles both shapes BacDive uses — a single dict, or a list of per-reference
    dicts. Getting this wrong in one shape is how #793 happened, so both are
    handled in one place rather than at each call site.

    :param block: The raw block, dict or list of dicts.
    :param field: The value key to read.
    :return: ``[(ref, normalised value), ...]``, skipping entries with no value.
    """
    items = block if isinstance(block, list) else [block]
    out: List[Tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or field not in item:
            continue
        value = item.get(field)
        if value is None or value == "":
            continue
        out.append((str(item.get(REF_KEY, "")), _normalise(value)))
    return out


def classify(
    values: Iterable[str],
    alias_to_curie: Dict[str, str],
    subsumption: Dict[str, set],
) -> str:
    """
    Say whether a set of disagreeing values is a real contradiction.

    Three outcomes, deliberately distinct — collapsing the last two into
    "contradiction" is what inflates the headline number:

    * ``specificity`` — the values lie on one subsumption chain, so both edges
      are simultaneously true and no policy is needed.
    * ``contradiction`` — all values resolve to METPO and none subsumes the
      others. This is the set that needs a resolution policy.
    * ``unresolved`` — at least one value has no METPO term, so the relationship
      cannot be judged. Not evidence of a conflict; evidence of a mapping gap.

    :param values: The distinct observed values.
    :param alias_to_curie: Raw value -> METPO CURIE.
    :param subsumption: CURIE -> ancestor CURIEs.
    :return: One of the three labels above.
    """
    vals = sorted(set(values))
    if not alias_to_curie:
        return "unresolved"

    curies = [alias_to_curie.get(v) for v in vals]
    if any(c is None for c in curies):
        return "unresolved"
    curies = sorted(set(curies))
    if len(curies) < 2:
        # Distinct spellings of the same term — not a disagreement at all.
        return "specificity"
    # Specificity iff some term subsumes every other, i.e. they lie on one chain.
    for candidate in curies:
        others = [c for c in curies if c != candidate]
        if all(candidate in subsumption.get(other, ()) for other in others):
            return "specificity"
    return "contradiction"


def main(argv: List[str]) -> int:
    """Scan the raw dump and write the conflict report."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv[1:])

    if not args.raw.is_file():
        print(f"ERROR: no BacDive dump at {args.raw}", file=sys.stderr)
        return 1

    alias_to_curie, subsumption = load_metpo()
    if not alias_to_curie:
        print(
            "WARNING: METPO extracts absent — every disagreement will be reported "
            "as 'unresolved'. Run `poetry run kg transform -s ontologies` for the "
            "specificity/contradiction split.",
            file=sys.stderr,
        )

    with args.raw.open(encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.values() if isinstance(data, dict) else data

    rows: List[dict] = []
    multi = Counter()
    kinds = Counter()
    strains_with_conflict: Dict[str, set] = defaultdict(set)

    for record in records:
        strain = str((record.get("General") or {}).get("BacDive-ID", "")) or "?"
        for section, key in PHENOTYPE_PATHS:
            block = (record.get(section) or {}).get(key)
            if block is None:
                continue
            for field in VALUE_FIELDS.get(key, (key,)):
                obs = observations(block, field)
                if len(obs) < 2:
                    continue
                multi[f"{key}/{field}"] += 1
                distinct = {v for _, v in obs}
                if len(distinct) < 2:
                    continue
                kind = classify(distinct, alias_to_curie, subsumption)
                kinds[kind] += 1
                strains_with_conflict[kind].add(strain)
                rows.append(
                    {
                        "bacdive_id": strain,
                        "section": section,
                        "key": key,
                        "field": field,
                        "kind": kind,
                        "n_observations": len(obs),
                        "values": " | ".join(sorted(distinct)),
                        "refs": " | ".join(f"{r}={v}" for r, v in obs),
                    }
                )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "bacdive_id", "section", "key", "field", "kind",
        "n_observations", "values", "refs",
    ]
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows):,} disagreeing observations to {args.out}")
    print("\nBy field (multi-valued -> disagreeing):")
    for name, n in multi.most_common():
        dis = sum(1 for r in rows if f"{r['key']}/{r['field']}" == name)
        print(f"  {name:<40} {n:>7,} -> {dis:>6,}")
    print("\nBy kind:")
    for kind, n in kinds.most_common():
        print(f"  {kind:<16} {n:>7,} observations across {len(strains_with_conflict[kind]):,} strains")
    real = len(strains_with_conflict.get("contradiction", ()))
    print(
        f"\nStrains needing a resolution policy: {real:,}. "
        "Specificity cases do not — METPO already relates the terms, so both "
        "edges are true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
