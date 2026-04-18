#!/usr/bin/env python3
"""Generate METPO mapping coverage report for metatraits transform."""

import csv
from collections import defaultdict
from pathlib import Path

edges_file = Path("data/transformed/metatraits/edges.tsv")
unmapped_file = Path("data/transformed/metatraits/unmapped_traits.tsv")

# Count mapped traits by predicate
predicate_counts = defaultdict(int)
metpo_object_counts = defaultdict(int)
chebi_object_counts = defaultdict(int)
go_object_counts = defaultdict(int)
ec_object_counts = defaultdict(int)

print("Loading edges.tsv...")
with open(edges_file) as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        predicate_counts[row["predicate"]] += 1
        obj = row["object"]
        if obj.startswith("METPO:"):
            metpo_object_counts[obj] += 1
        elif obj.startswith("CHEBI:"):
            chebi_object_counts[obj] += 1
        elif obj.startswith("GO:"):
            go_object_counts[obj] += 1
        elif obj.startswith("EC:"):
            ec_object_counts[obj] += 1

# Count unmapped traits
print("Loading unmapped_traits.tsv...")
unmapped_traits = defaultdict(int)
with open(unmapped_file) as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        trait = row.get("trait_name", "").strip()
        if trait:
            unmapped_traits[trait] += 1

# Generate report
print("\n" + "=" * 70)
print("METPO Mapping Coverage Report")
print("=" * 70)

print(f"\n📊 OVERALL STATISTICS")
print(f"  Total edges: {sum(predicate_counts.values()):,}")
print(f"  Unique unmapped traits: {len(unmapped_traits):,}")
print(f"  Total unmapped trait occurrences: {sum(unmapped_traits.values()):,}")

print(f"\n🎯 EDGES BY PREDICATE")
for pred, count in sorted(predicate_counts.items(), key=lambda x: -x[1]):
    pct = (count / sum(predicate_counts.values())) * 100
    print(f"  {pred}: {count:,} ({pct:.1f}%)")

print(f"\n🧬 ONTOLOGY COVERAGE")
print(f"  METPO objects: {len(metpo_object_counts):,} unique terms")
print(f"  ChEBI objects: {len(chebi_object_counts):,} unique terms")
print(f"  GO objects: {len(go_object_counts):,} unique terms")
print(f"  EC objects: {len(ec_object_counts):,} unique terms")

print(f"\n🔝 TOP 15 METPO OBJECTS")
for obj, count in sorted(metpo_object_counts.items(), key=lambda x: -x[1])[:15]:
    pct = (count / sum(predicate_counts.values())) * 100
    print(f"  {obj}: {count:,} edges ({pct:.2f}%)")

print(f"\n🔝 TOP 10 UNMAPPED TRAITS")
for trait, count in sorted(unmapped_traits.items(), key=lambda x: -x[1])[:10]:
    print(f"  {trait}: {count:,} occurrences")

print(f"\n📈 MAPPING SUCCESS RATE")
total_edges = sum(predicate_counts.values())
unmapped_occurrences = sum(unmapped_traits.values())
# Note: This is approximate since unmapped_traits.tsv may have different granularity
print(f"  Mapped edges: {total_edges:,}")
print(f"  Unmapped trait occurrences: {unmapped_occurrences:,}")

print("\n" + "=" * 70)
