#!/usr/bin/env python3
"""
Migrate manually curated chemical mappings to unified chemical mappings file.

This script consolidates hard-coded chemical mappings from metatraits and bacdive
into the unified_chemical_mappings.tsv.gz file with provenance tracking.

Usage:
    python scripts/migrate_chemical_mappings.py [--dry-run]
"""

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set


class ChemicalMapping:
    """Represents a unified chemical mapping entry."""

    def __init__(self, chebi_id: str, canonical_name: str = "", formula: str = "",
                 synonyms: Set[str] = None, xrefs: Set[str] = None, sources: Set[str] = None):
        self.chebi_id = chebi_id
        self.canonical_name = canonical_name
        self.formula = formula
        self.synonyms = synonyms or set()
        self.xrefs = xrefs or set()
        self.sources = sources or set()

    def add_synonym(self, synonym: str):
        """Add a synonym (avoid duplicates and empty strings)."""
        if synonym and synonym.strip():
            self.synonyms.add(synonym.strip())

    def add_source(self, source: str):
        """Add a source (avoid duplicates)."""
        if source and source.strip():
            self.sources.add(source.strip())

    def merge(self, other: 'ChemicalMapping'):
        """Merge another mapping into this one."""
        # Prefer non-empty canonical name
        if not self.canonical_name and other.canonical_name:
            self.canonical_name = other.canonical_name

        # Prefer non-empty formula
        if not self.formula and other.formula:
            self.formula = other.formula

        # Merge synonyms, xrefs, sources
        self.synonyms.update(other.synonyms)
        self.xrefs.update(other.xrefs)
        self.sources.update(other.sources)

    def to_tsv_line(self) -> str:
        """Convert to TSV line for output."""
        synonyms_str = "|".join(sorted(self.synonyms)) if self.synonyms else ""
        xrefs_str = "|".join(sorted(self.xrefs)) if self.xrefs else ""
        sources_str = "|".join(sorted(self.sources)) if self.sources else ""

        return f"{self.chebi_id}\t{self.canonical_name}\t{self.formula}\t{synonyms_str}\t{xrefs_str}\t{sources_str}"


def load_existing_unified_file(path: Path) -> Dict[str, ChemicalMapping]:
    """Load existing unified chemical mappings file."""
    mappings = {}
    skipped = 0
    line_num = 0

    print(f"Loading existing unified file: {path}")

    with gzip.open(path, 'rt') as f:
        header = f.readline().strip().split('\t')
        line_num = 1

        for line in f:
            line_num += 1
            parts = line.strip().split('\t')
            if len(parts) < 6:
                parts.extend([''] * (6 - len(parts)))

            chebi_id, canonical_name, formula, synonyms_str, xrefs_str, sources_str = parts[:6]

            # Validate that first column is a CHEBI ID
            if not chebi_id.startswith('CHEBI:'):
                print(f"  WARNING: Skipping malformed row {line_num} (no CHEBI ID): {chebi_id[:50]}...")
                skipped += 1
                continue

            synonyms = set(synonyms_str.split('|')) if synonyms_str else set()
            xrefs = set(xrefs_str.split('|')) if xrefs_str else set()
            sources = set(sources_str.split('|')) if sources_str else set()

            # Remove empty strings from sets
            synonyms.discard('')
            xrefs.discard('')
            sources.discard('')

            mappings[chebi_id] = ChemicalMapping(
                chebi_id, canonical_name, formula, synonyms, xrefs, sources
            )

    print(f"  Loaded {len(mappings):,} existing mappings")
    if skipped > 0:
        print(f"  Skipped {skipped} malformed rows")
    return mappings


def migrate_chemical_name_synonyms(mappings: Dict[str, ChemicalMapping], path: Path) -> int:
    """Migrate chemical_name_synonyms.tsv to unified format."""
    print(f"\nMigrating: {path}")
    count = 0

    with open(path, 'r') as f:
        header = f.readline()  # Skip header

        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                continue

            metatraits_name, chebi_search_name, chebi_id, chebi_label = parts[:4]
            notes = parts[4] if len(parts) > 4 else ""

            if not chebi_id or not chebi_id.startswith('CHEBI:'):
                continue

            # Create or update mapping
            if chebi_id in mappings:
                mapping = mappings[chebi_id]
            else:
                mapping = ChemicalMapping(chebi_id, canonical_name=chebi_label)
                mappings[chebi_id] = mapping

            # Add metatraits name as synonym
            mapping.add_synonym(metatraits_name)

            # Add source with provenance
            mapping.add_source("metatraits_chemical_synonyms[manual_2026-04-07]")

            count += 1

    print(f"  Added {count} chemical synonym mappings")
    return count


def migrate_special_chemical_mappings(mappings: Dict[str, ChemicalMapping], path: Path) -> int:
    """Migrate special_chemical_mappings.tsv (only ChEBI entries)."""
    print(f"\nMigrating: {path}")
    count = 0
    skipped = 0

    with open(path, 'r') as f:
        header = f.readline()  # Skip header

        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3:
                continue

            trait_pattern, chemical_name, ontology_id = parts[:3]
            ontology_name = parts[3] if len(parts) > 3 else ""

            # Only migrate ChEBI entries
            if not ontology_id.startswith('CHEBI:'):
                skipped += 1
                continue

            # Create or update mapping
            if ontology_id in mappings:
                mapping = mappings[ontology_id]
            else:
                mapping = ChemicalMapping(ontology_id, canonical_name=ontology_name)
                mappings[ontology_id] = mapping

            # Add chemical name as synonym
            mapping.add_synonym(chemical_name)

            # Add source with provenance
            mapping.add_source("metatraits_special_chemicals[manual_2026-04-07]")

            count += 1

    print(f"  Added {count} special chemical mappings ({skipped} non-ChEBI entries skipped)")
    return count


def migrate_metabolite_mapping_json(mappings: Dict[str, ChemicalMapping], path: Path) -> int:
    """Migrate bacdive metabolite_mapping.json to unified format."""
    print(f"\nMigrating: {path}")
    count = 0

    with open(path, 'r') as f:
        metabolite_data = json.load(f)

    for chebi_id, compound_name in metabolite_data.items():
        if not chebi_id.startswith('CHEBI:'):
            continue

        # Create or update mapping
        if chebi_id in mappings:
            mapping = mappings[chebi_id]
        else:
            # Use compound name from JSON as canonical name if not already set
            mapping = ChemicalMapping(chebi_id, canonical_name=compound_name)
            mappings[chebi_id] = mapping

        # Add compound name as synonym
        mapping.add_synonym(compound_name)

        # Add source with provenance
        mapping.add_source("bacdive_antibiotics[manual_pre-2026]")

        count += 1

    print(f"  Added {count} bacdive antibiotic mappings")
    return count


def write_unified_file(mappings: Dict[str, ChemicalMapping], path: Path):
    """Write unified mappings to gzipped TSV file."""
    print(f"\nWriting unified file: {path}")

    # Sort by ChEBI ID
    sorted_ids = sorted(mappings.keys(), key=lambda x: int(x.split(':')[1]) if ':' in x else 0)

    with gzip.open(path, 'wt') as f:
        # Write header
        f.write("chebi_id\tcanonical_name\tformula\tsynonyms\txrefs\tsources\n")

        # Write mappings
        for chebi_id in sorted_ids:
            mapping = mappings[chebi_id]
            f.write(mapping.to_tsv_line() + "\n")

    print(f"  Wrote {len(mappings):,} total mappings")


def main():
    parser = argparse.ArgumentParser(description="Migrate chemical mappings to unified file")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be done without writing")
    args = parser.parse_args()

    # Paths
    repo_root = Path(__file__).parent.parent
    unified_file = repo_root / "mappings" / "unified_chemical_mappings.tsv.gz"
    output_file = repo_root / "mappings" / "unified_chemical_mappings_v2.tsv.gz"

    chem_synonyms = repo_root / "kg_microbe" / "transform_utils" / "metatraits" / "mappings" / "chemical_name_synonyms.tsv"
    special_chem = repo_root / "kg_microbe" / "transform_utils" / "metatraits" / "mappings" / "special_chemical_mappings.tsv"
    bacdive_json = repo_root / "kg_microbe" / "transform_utils" / "bacdive" / "metabolite_mapping.json"

    # Verify files exist
    for path in [unified_file, chem_synonyms, special_chem, bacdive_json]:
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            sys.exit(1)

    print("="*80)
    print("Chemical Mappings Migration")
    print("="*80)

    # Load existing unified file
    mappings = load_existing_unified_file(unified_file)
    original_count = len(mappings)

    # Migrate files
    chem_syn_count = migrate_chemical_name_synonyms(mappings, chem_synonyms)
    special_count = migrate_special_chemical_mappings(mappings, special_chem)
    bacdive_count = migrate_metabolite_mapping_json(mappings, bacdive_json)

    # Summary
    new_count = len(mappings)
    added = new_count - original_count

    print("\n" + "="*80)
    print("Migration Summary")
    print("="*80)
    print(f"Original unified mappings:  {original_count:,}")
    print(f"  + chemical_name_synonyms: {chem_syn_count}")
    print(f"  + special_chemicals:      {special_count}")
    print(f"  + bacdive_antibiotics:    {bacdive_count}")
    print(f"  = Total inputs:           {chem_syn_count + special_count + bacdive_count}")
    print(f"\nFinal unified mappings:     {new_count:,}")
    print(f"New unique ChEBI IDs added: {added:,}")
    print(f"Deduplicated (merged):      {(chem_syn_count + special_count + bacdive_count) - added}")

    # Write output
    if args.dry_run:
        print("\n[DRY RUN] No files written")
    else:
        write_unified_file(mappings, output_file)
        print("\n" + "="*80)
        print("Migration complete!")
        print("="*80)
        print(f"\nNext steps:")
        print(f"1. Backup original:")
        print(f"   cp {unified_file} {unified_file.parent}/unified_chemical_mappings_backup_2026-04-07.tsv.gz")
        print(f"2. Replace with migrated version:")
        print(f"   mv {output_file} {unified_file}")
        print(f"3. Test transforms:")
        print(f"   poetry run kg transform -s metatraits")
        print(f"   poetry run kg transform -s bacdive")


if __name__ == "__main__":
    main()
