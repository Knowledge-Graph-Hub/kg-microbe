#!/usr/bin/env python3
"""
Report source-edge distributions and unresolved/source-observation queues.

Finalized edge rows and producer-reported observations have different units.
Neither local IDs nor ontology prefixes establish mapping success, and reported
MicrobeDecoder Attributes are not failed chemical identities. No combined
mapping-success rate is calculated.

Usage:

    poetry run python scripts/generate_coverage_report.py
    poetry run python scripts/generate_coverage_report.py -s microbedecoder
    poetry run python scripts/generate_coverage_report.py -s metatraits_gtdb
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

SOURCE_LAYOUTS = {
    "metatraits": {
        "edges": "data/transformed/metatraits/edges.tsv",
        "unmapped": "data/transformed/metatraits/unmapped_traits.tsv",
        "label_column": "trait_name",
        "count_column": "num_observations",
        "required_columns": ("trait_name", "tax_name", "majority_label", "num_observations"),
    },
    "metatraits_gtdb": {
        "edges": "data/transformed/metatraits_gtdb/edges.tsv",
        "unmapped": "data/transformed/metatraits_gtdb/unmapped_traits.tsv",
        "label_column": "trait_name",
        "count_column": "num_observations",
        "required_columns": ("trait_name", "tax_name", "majority_label", "num_observations"),
    },
    "microbedecoder": {
        "edges": "data/transformed/microbedecoder/edges.tsv",
        "unmapped": "data/transformed/microbedecoder/unmapped_labels.tsv",
        "label_column": "label",
        "count_column": "occurrences",
        "required_columns": ("placeholder_curie", "category", "label", "source_columns", "occurrences"),
    },
}


def _rows(path: Path, required_columns, *, quoting=csv.QUOTE_MINIMAL):
    """Read complete TSV rows, rejecting malformed headers and widths."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=quoting, strict=True)
        fields = reader.fieldnames
        if (
            not fields
            or len(fields) != len(set(fields))
            or any(not field for field in fields)
            or not set(required_columns).issubset(fields)
        ):
            raise ValueError(f"{path}: invalid header; required columns: {', '.join(required_columns)}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{reader.line_num}: invalid TSV row width")
            yield reader.line_num, row


def _id_family(curie: str) -> str:
    """Describe local object families without inferring their identity status."""
    for family in ("source_attribute", "pathway", "compound", "ingredient", "trait"):
        if curie.startswith(f"kgmicrobe.{family}:"):
            return family
    return "other"


def load_edge_stats(edges_file: Path) -> dict:
    """Stream finalized edge rows; retain duplicate rows in all distributions."""
    predicates, families, prefixes = Counter(), Counter(), Counter()
    ontology_objects = {prefix: Counter() for prefix in ("METPO", "CHEBI", "GO", "EC")}
    for line, row in _rows(edges_file, ("predicate", "object"), quoting=csv.QUOTE_NONE):
        predicate, obj = row["predicate"], row["object"]
        if not predicate or not obj:
            raise ValueError(f"{edges_file}:{line}: empty predicate or object")
        predicates[predicate] += 1
        families[_id_family(obj)] += 1
        prefix = obj.partition(":")[0] if ":" in obj else "(no prefix)"
        prefixes[prefix] += 1
        if prefix in ontology_objects:
            ontology_objects[prefix][obj] += 1
    return {
        "edge_rows": sum(predicates.values()),
        "predicates": predicates,
        "object_families": families,
        "object_prefixes": prefixes,
        "ontology_objects": ontology_objects,
    }


def load_unmapped(unmapped_file: Path, layout: dict) -> list[dict] | None:
    """Retain every report row and its context; None means absent, not empty."""
    if not unmapped_file.exists():
        return None
    records = []
    for line, row in _rows(unmapped_file, layout["required_columns"]):
        value = row[layout["count_column"]]
        if re.fullmatch(r"[0-9]+", value) is None:
            raise ValueError(
                f"{unmapped_file}:{line}: {layout['count_column']} must be a nonnegative integer; got {value!r}"
            )
        if not row[layout["label_column"]]:
            raise ValueError(f"{unmapped_file}:{line}: empty {layout['label_column']}")
        facet = (
            _id_family(row["placeholder_curie"])
            if "placeholder_curie" in layout["required_columns"]
            else "unresolved_trait"
        )
        records.append({"line": line, "row": row, "count": int(value), "facet": facet})
    return records


def _report(source: str, layout: dict) -> None:
    """Print separate edge distributions and context-preserving queue priorities."""
    edges_file, unmapped_file = Path(layout["edges"]), Path(layout["unmapped"])
    stats = load_edge_stats(edges_file)
    records = load_unmapped(unmapped_file, layout)

    print(f"{source} Source-edge and reported-observation inventory")
    print(f"Edges: {edges_file}")
    print(f"Finalized source edge rows: {stats['edge_rows']:,}")
    print("\nEdges by predicate (all rows, not mapping successes):")
    for predicate, count in stats["predicates"].most_common():
        print(f"  {predicate}: {count:,}")
    print("\nObject ID families (not resolution status):")
    for family, count in sorted(stats["object_families"].items()):
        print(f"  {family}: {count:,}")
    print("\nObject prefixes (not identity validation):")
    for prefix, count in stats["object_prefixes"].most_common():
        print(f"  {prefix}: {count:,}")
    print("\nSelected ontology object counts:")
    for prefix, counts in stats["ontology_objects"].items():
        print(f"  {prefix}: {len(counts):,} distinct objects; {sum(counts.values()):,} edge rows")

    print(f"\nProducer report: {unmapped_file}")
    if records is None:
        print("Report status: MISSING; unresolved/source-observation totals are unknown.")
    else:
        print("Report status: PRESENT" if records else "Report status: PRESENT_EMPTY (header only)")
        print(f"Report rows: {len(records):,} (no label-only deduplication)")
        if source == "microbedecoder":
            print("Count unit: producer placeholder/source-attribute emission attempts, before edge deduplication.")
        else:
            print("Count unit: producer-reported num_observations; report rows are separate trait/taxon records.")
        print(f"Reported count total: {sum(record['count'] for record in records):,}")
        facets, counts = Counter(), Counter()
        for record in records:
            facets[record["facet"]] += 1
            counts[record["facet"]] += record["count"]
        print("Queue facets:")
        for facet in sorted(facets):
            print(f"  {facet}: {facets[facet]:,} report rows; {counts[facet]:,} reported counts")
        print("\nTop 10 report rows by reported count (full context; input order breaks ties):")
        for record in sorted(records, key=lambda item: -item["count"])[:10]:
            print(f"  {record['facet']} line {record['line']}: {json.dumps(record['row'], ensure_ascii=False)}")

    print("\nEdge rows and reported observations are separate measures; no mapping-success rate is inferred.")
    print("Source Attributes require field/coding-scheme review, not automatic phenotype or chemical grounding.")


def main() -> None:
    """Parse args and report without importing producers or resolving identities."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("-s", "--source", default="metatraits", choices=sorted(SOURCE_LAYOUTS))
    args = parser.parse_args()
    try:
        _report(args.source, SOURCE_LAYOUTS[args.source])
    except (OSError, ValueError, csv.Error) as error:
        raise SystemExit(f"[coverage] {error}") from error


if __name__ == "__main__":
    main()
