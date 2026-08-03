#!/usr/bin/env python3
"""Generate mapping-coverage report for a transform.

Reads the transform's ``edges.tsv`` (for predicate + object-ontology
distributions) and its per-source unmapped queue (for the still-to-map
labels). Prints a scannable summary suitable for pasting into a release
report or a curation issue.

Historically metatraits-specific; now parametrised by ``--source`` so the
same shape works for any transform that emits an unmapped-labels TSV.

Supported sources today:

- ``metatraits`` → ``unmapped_traits.tsv`` (``trait_name`` column)
- ``metatraits_gtdb`` → same layout as ``metatraits``
- ``microbedecoder`` → ``unmapped_labels.tsv`` (``label`` +
  ``occurrences`` columns; occurrences are summed rather than
  counting rows)

Usage:

    poetry run python scripts/generate_coverage_report.py                # defaults to metatraits
    poetry run python scripts/generate_coverage_report.py -s microbedecoder
    poetry run python scripts/generate_coverage_report.py -s metatraits_gtdb
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Per-source layout: where the edge file lives, where the unmapped queue
# lives, which column carries the raw label, and how to compute the per-row
# occurrence count. Kept as a dict so adding a source is a one-line change.
# ---------------------------------------------------------------------------
SOURCE_LAYOUTS: Dict[str, Dict[str, object]] = {
    "metatraits": {
        "edges": "data/transformed/metatraits/edges.tsv",
        "unmapped": "data/transformed/metatraits/unmapped_traits.tsv",
        "label_column": "trait_name",
        "occurrences": lambda row: 1,  # one row = one occurrence
    },
    "metatraits_gtdb": {
        "edges": "data/transformed/metatraits_gtdb/edges.tsv",
        "unmapped": "data/transformed/metatraits_gtdb/unmapped_traits.tsv",
        "label_column": "trait_name",
        "occurrences": lambda row: 1,
    },
    "microbedecoder": {
        "edges": "data/transformed/microbedecoder/edges.tsv",
        "unmapped": "data/transformed/microbedecoder/unmapped_labels.tsv",
        "label_column": "label",
        # Microbedecoder pre-aggregates the count in the row itself.
        "occurrences": lambda row: int(row.get("occurrences", 1) or 1),
    },
}


def load_edge_stats(edges_file: Path) -> Tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
    """Return (predicate_counts, ontology_object_counts) for an edges.tsv."""
    predicate_counts: Dict[str, int] = defaultdict(int)
    ontology_counts: Dict[str, Dict[str, int]] = {
        "METPO": defaultdict(int),
        "CHEBI": defaultdict(int),
        "GO": defaultdict(int),
        "EC": defaultdict(int),
    }
    with open(edges_file) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            predicate_counts[row["predicate"]] += 1
            obj = row.get("object", "")
            for prefix in ontology_counts:
                if obj.startswith(f"{prefix}:"):
                    ontology_counts[prefix][obj] += 1
                    break
    return predicate_counts, ontology_counts


def load_unmapped(unmapped_file: Path, label_column: str, occurrences_fn) -> Dict[str, int]:
    """Return {label: occurrence_count} from a source-specific unmapped queue."""
    unmapped: Dict[str, int] = defaultdict(int)
    if not unmapped_file.exists():
        return unmapped
    with open(unmapped_file) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            label = (row.get(label_column) or "").strip()
            if not label:
                continue
            unmapped[label] += occurrences_fn(row)
    return unmapped


def _report(source: str, layout: Dict[str, object]) -> None:
    """Print the coverage report for one source."""
    edges_file = Path(str(layout["edges"]))
    unmapped_file = Path(str(layout["unmapped"]))
    if not edges_file.exists():
        raise SystemExit(f"[coverage] {edges_file} does not exist; run the transform first")

    print(f"Loading {edges_file}...")
    predicate_counts, ontology_counts = load_edge_stats(edges_file)

    print(f"Loading {unmapped_file}...")
    unmapped = load_unmapped(
        unmapped_file,
        str(layout["label_column"]),
        layout["occurrences"],  # type: ignore[arg-type]
    )

    total_edges = sum(predicate_counts.values())
    total_unmapped_occurrences = sum(unmapped.values())

    print("\n" + "=" * 70)
    print(f"{source} Mapping Coverage Report")
    print("=" * 70)

    print("\n📊 OVERALL STATISTICS")
    print(f"  Total edges: {total_edges:,}")
    print(f"  Unique unmapped labels: {len(unmapped):,}")
    print(f"  Total unmapped label occurrences: {total_unmapped_occurrences:,}")

    print("\n🎯 EDGES BY PREDICATE")
    for pred, count in sorted(predicate_counts.items(), key=lambda x: -x[1]):
        pct = (count / total_edges) * 100 if total_edges else 0
        print(f"  {pred}: {count:,} ({pct:.1f}%)")

    print("\n🧬 ONTOLOGY COVERAGE")
    for prefix, counts in ontology_counts.items():
        print(f"  {prefix} objects: {len(counts):,} unique terms")

    if ontology_counts["METPO"]:
        print("\n🔝 TOP 15 METPO OBJECTS")
        for obj, count in sorted(ontology_counts["METPO"].items(), key=lambda x: -x[1])[:15]:
            pct = (count / total_edges) * 100 if total_edges else 0
            print(f"  {obj}: {count:,} edges ({pct:.2f}%)")

    print("\n🔝 TOP 10 UNMAPPED LABELS")
    for label, count in sorted(unmapped.items(), key=lambda x: -x[1])[:10]:
        print(f"  {label}: {count:,} occurrences")

    print("\n📈 MAPPING SUCCESS RATE")
    print(f"  Mapped edges: {total_edges:,}")
    print(f"  Unmapped label occurrences: {total_unmapped_occurrences:,}")
    if total_edges + total_unmapped_occurrences:
        mapped_pct = 100 * total_edges / (total_edges + total_unmapped_occurrences)
        print(f"  Approximate mapping rate: {mapped_pct:.1f}%")

    print("\n" + "=" * 70)


def main() -> None:
    """Parse args and dispatch to :func:`_report`."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "-s",
        "--source",
        default="metatraits",
        choices=sorted(SOURCE_LAYOUTS),
        help="Transform whose coverage to report (default: metatraits).",
    )
    args = parser.parse_args()
    _report(args.source, SOURCE_LAYOUTS[args.source])


if __name__ == "__main__":
    main()
