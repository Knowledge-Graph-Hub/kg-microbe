#!/usr/bin/env python3
"""Analyze overlap between GTDB and NCBITaxon metatraits data.

This script determines how much new coverage GTDB metatraits would provide
compared to existing NCBITaxon metatraits data in the knowledge graph.
"""

import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set


def load_ncbi_taxa_with_traits(edges_file: Path) -> Set[str]:
    """Load NCBITaxon IDs that already have trait data.

    Args:
        edges_file: Path to metatraits edges.tsv file

    Returns:
        Set of NCBITaxon IDs (e.g., 'NCBITaxon:562')
    """
    taxa_with_traits = set()

    if not edges_file.exists():
        print(f"Warning: {edges_file} not found. Run 'poetry run kg transform -s metatraits' first.")
        return taxa_with_traits

    with open(edges_file, 'r') as f:
        next(f)  # Skip header
        for line in f:
            parts = line.strip().split('\t')
            if parts:
                subject_id = parts[0]
                if subject_id.startswith('NCBITaxon:'):
                    taxa_with_traits.add(subject_id)

    print(f"Loaded {len(taxa_with_traits)} unique NCBITaxon taxa with existing trait data")
    return taxa_with_traits


def load_gtdb_taxa_with_traits(data_dir: Path) -> Dict[str, dict]:
    """Load GTDB taxa that have trait data.

    Args:
        data_dir: Path to data/raw/ directory

    Returns:
        Dict mapping GTDB tax_name to trait summary stats
    """
    gtdb_taxa = {}

    for level in ['species', 'genus', 'family']:
        filepath = data_dir / f"gtdb_{level}_summary.jsonl.gz"

        if not filepath.exists():
            print(f"Warning: {filepath} not found")
            continue

        print(f"Loading {filepath.name}...")
        with gzip.open(filepath, 'rt') as f:
            for line in f:
                record = json.loads(line)
                tax_name = record.get('tax_name')
                summaries = record.get('summaries', [])

                if tax_name and summaries:
                    total_obs = sum(s.get('num_observations', 0) for s in summaries)
                    unique_traits = len(summaries)
                    gtdb_taxa[tax_name] = {
                        'level': level,
                        'num_observations': total_obs,
                        'num_traits': unique_traits
                    }

    print(f"Loaded {len(gtdb_taxa)} unique GTDB taxa with trait data")
    return gtdb_taxa


def load_gtdb_to_ncbi_mapping(gtdb_dir: Path) -> Dict[str, Set[str]]:
    """Load GTDB to NCBITaxon mapping from GTDB metadata files.

    Args:
        gtdb_dir: Path to directory containing GTDB metadata files

    Returns:
        Dict mapping GTDB species name to set of NCBITaxon IDs
    """
    mapping = defaultdict(set)

    # Process both bacterial and archaeal metadata
    for metadata_file in ['bac120_metadata.tsv.gz', 'ar53_metadata.tsv.gz']:
        filepath = gtdb_dir / metadata_file

        if not filepath.exists():
            print(f"Warning: {filepath} not found")
            continue

        print(f"Loading {filepath.name}...")
        with gzip.open(filepath, 'rt') as f:
            header = next(f).strip().split('\t')

            # Find column indices
            try:
                taxonomy_idx = header.index('gtdb_taxonomy')
                taxid_idx = header.index('ncbi_taxid')
            except ValueError as e:
                print(f"Error: Could not find required columns in {metadata_file}: {e}")
                continue

            for line in f:
                parts = line.strip().split('\t')
                if len(parts) > max(taxonomy_idx, taxid_idx):
                    gtdb_taxonomy = parts[taxonomy_idx]
                    ncbi_taxid = parts[taxid_idx]

                    # Extract species name from taxonomy string
                    # Format: d__Bacteria;p__...;s__Species_name
                    if gtdb_taxonomy and ncbi_taxid and ncbi_taxid not in ('none', 'NA', ''):
                        tax_parts = gtdb_taxonomy.split(';')
                        if len(tax_parts) >= 7:
                            species = tax_parts[6].replace('s__', '')  # Remove 's__' prefix
                            if species:
                                # Add NCBITaxon: prefix
                                ncbi_id = f'NCBITaxon:{ncbi_taxid}'
                                mapping[species].add(ncbi_id)

    print(f"Loaded {len(mapping)} unique GTDB species → NCBITaxon mappings")
    return mapping


def analyze_overlap(
    gtdb_taxa: Dict[str, dict],
    gtdb_to_ncbi: Dict[str, Set[str]],
    ncbi_taxa_with_traits: Set[str]
) -> Dict:
    """Analyze overlap between GTDB and NCBITaxon metatraits.

    Args:
        gtdb_taxa: GTDB taxa with trait data
        gtdb_to_ncbi: GTDB to NCBITaxon mapping
        ncbi_taxa_with_traits: NCBITaxon IDs with existing traits

    Returns:
        Dict with analysis results
    """
    redundant_taxa = set()
    new_coverage_taxa = set()
    gtdb_only_taxa = set()

    redundant_obs = 0
    new_coverage_obs = 0
    gtdb_only_obs = 0

    for gtdb_taxon, stats in gtdb_taxa.items():
        ncbi_ids = gtdb_to_ncbi.get(gtdb_taxon, set())
        num_obs = stats['num_observations']

        if not ncbi_ids:
            # GTDB-only (no NCBITaxon mapping)
            gtdb_only_taxa.add(gtdb_taxon)
            gtdb_only_obs += num_obs
        else:
            # Check if any mapped NCBITaxon ID has traits
            has_traits = any(ncbi_id in ncbi_taxa_with_traits for ncbi_id in ncbi_ids)

            if has_traits:
                # Redundant (NCBITaxon already has traits)
                redundant_taxa.add(gtdb_taxon)
                redundant_obs += num_obs
            else:
                # New coverage (NCBITaxon exists but no traits yet)
                new_coverage_taxa.add(gtdb_taxon)
                new_coverage_obs += num_obs

    total_taxa = len(gtdb_taxa)
    total_obs = sum(s['num_observations'] for s in gtdb_taxa.values())

    return {
        'total_taxa': total_taxa,
        'total_observations': total_obs,
        'redundant_taxa': len(redundant_taxa),
        'redundant_obs': redundant_obs,
        'new_coverage_taxa': len(new_coverage_taxa),
        'new_coverage_obs': new_coverage_obs,
        'gtdb_only_taxa': len(gtdb_only_taxa),
        'gtdb_only_obs': gtdb_only_obs,
        'redundant_taxa_set': redundant_taxa,
        'new_coverage_taxa_set': new_coverage_taxa,
        'gtdb_only_taxa_set': gtdb_only_taxa,
    }


def print_report(results: Dict, ncbi_taxa_count: int):
    """Print overlap analysis report.

    Args:
        results: Analysis results dict
        ncbi_taxa_count: Number of NCBITaxon taxa with existing traits
    """
    print("\n" + "="*70)
    print("GTDB MetaTraits Overlap Analysis")
    print("="*70)

    print(f"\nExisting NCBITaxon metatraits coverage: {ncbi_taxa_count:,} taxa")
    print(f"Total GTDB taxa with traits: {results['total_taxa']:,}")
    print(f"Total GTDB trait observations: {results['total_observations']:,}")

    print("\n" + "-"*70)
    print("Breakdown by Coverage Category:")
    print("-"*70)

    total = results['total_taxa']

    print(f"\n1. Redundant (NCBITaxon already has traits):")
    print(f"   Taxa: {results['redundant_taxa']:,} ({results['redundant_taxa']/total*100:.1f}%)")
    print(f"   Observations: {results['redundant_obs']:,} ({results['redundant_obs']/results['total_observations']*100:.1f}%)")

    print(f"\n2. New coverage (NCBITaxon exists, no traits):")
    print(f"   Taxa: {results['new_coverage_taxa']:,} ({results['new_coverage_taxa']/total*100:.1f}%)")
    print(f"   Observations: {results['new_coverage_obs']:,} ({results['new_coverage_obs']/results['total_observations']*100:.1f}%)")

    print(f"\n3. GTDB-only (no NCBITaxon mapping):")
    print(f"   Taxa: {results['gtdb_only_taxa']:,} ({results['gtdb_only_taxa']/total*100:.1f}%)")
    print(f"   Observations: {results['gtdb_only_obs']:,} ({results['gtdb_only_obs']/results['total_observations']*100:.1f}%)")

    print("\n" + "-"*70)
    print("Sample Taxa:")
    print("-"*70)

    for category, taxa_set in [
        ("Redundant", results['redundant_taxa_set']),
        ("New Coverage", results['new_coverage_taxa_set']),
        ("GTDB-only", results['gtdb_only_taxa_set'])
    ]:
        print(f"\n{category} (showing first 10):")
        for i, taxon in enumerate(sorted(taxa_set)[:10]):
            print(f"  {i+1}. {taxon}")

    print("\n" + "="*70)
    print("Recommendation:")
    print("="*70)

    new_coverage_pct = results['new_coverage_taxa'] / total * 100
    gtdb_only_pct = results['gtdb_only_taxa'] / total * 100
    redundant_pct = results['redundant_taxa'] / total * 100

    if new_coverage_pct >= 20 or gtdb_only_pct >= 10:
        print("\n✅ INTEGRATE - Significant new coverage detected")
        print(f"   - New coverage: {new_coverage_pct:.1f}% (threshold: ≥20%)")
        print(f"   - GTDB-only: {gtdb_only_pct:.1f}% (threshold: ≥10%)")
        print("\nNext steps:")
        print("1. Create gtdb_metatraits transform in kg_microbe/transform_utils/gtdb_metatraits/")
        print("2. Register in DATA_SOURCES dict in kg_microbe/transform.py")
        print("3. Add to merge.yaml")
    else:
        print("\n❌ SKIP - High redundancy with NCBITaxon metatraits")
        print(f"   - Redundant: {redundant_pct:.1f}% (threshold: <80% for integration)")
        print(f"   - New coverage: {new_coverage_pct:.1f}% (threshold: ≥20%)")
        print(f"   - GTDB-only: {gtdb_only_pct:.1f}% (threshold: ≥10%)")
        print("\nNext steps:")
        print("1. Document findings in docs/GTDB_METATRAITS_ANALYSIS.md")
        print("2. Keep download URLs commented out in download.yaml")
        print("3. No transform implementation needed")

    print("\n" + "="*70)


def main():
    """Main analysis function."""
    # Define paths
    base_dir = Path(__file__).parent.parent
    data_raw = base_dir / "data" / "raw"
    gtdb_dir = data_raw / "gtdb"
    metatraits_edges = base_dir / "data" / "transformed" / "metatraits" / "edges.tsv"

    # Load data
    print("="*70)
    print("Loading data...")
    print("="*70)
    print()

    ncbi_taxa_with_traits = load_ncbi_taxa_with_traits(metatraits_edges)
    gtdb_taxa = load_gtdb_taxa_with_traits(data_raw)
    gtdb_to_ncbi = load_gtdb_to_ncbi_mapping(gtdb_dir)

    # Analyze overlap
    print("\n" + "="*70)
    print("Analyzing overlap...")
    print("="*70)

    results = analyze_overlap(gtdb_taxa, gtdb_to_ncbi, ncbi_taxa_with_traits)

    # Print report
    print_report(results, len(ncbi_taxa_with_traits))


if __name__ == "__main__":
    main()
