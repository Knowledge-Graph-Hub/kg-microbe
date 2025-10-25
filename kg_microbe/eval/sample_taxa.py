"""Generate or load random taxa samples for evaluation."""

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import bioregistry


def is_strain_node(node_id: str) -> bool:
    """
    Check if a node ID represents a strain.

    Args:
    ----
        node_id: Node CURIE to check

    Returns:
    -------
        True if the node is a strain, False otherwise

    Note:
    ----
        Strain nodes can be in multiple formats:
        - Old format: strain:bacdive_X
        - New format (unregistered): KGMICROBE:X
        - New format (registered): ATCC:X, DSMZ:X, JCM:X, etc.

    """
    # Old format
    if node_id.startswith("strain:bacdive_"):
        return True

    # New KGMICROBE format
    if node_id.startswith("KGMICROBE:"):
        return True

    # Check if it's a registered culture collection prefix
    # Extract prefix before the colon
    if ":" in node_id:
        prefix = node_id.split(":", 1)[0]
        # Don't treat NCBITaxon, CHEBI, etc. as strains
        if prefix in ["NCBITaxon", "CHEBI", "ENVO", "GO", "HP", "MONDO", "EC", "RHEA"]:
            return False
        # Check if it's a registered prefix in bioregistry
        normalized = bioregistry.normalize_prefix(prefix.lower())
        if normalized:
            # It's a registered prefix - likely a culture collection
            return True

    return False


def get_sample_file_path(source: str) -> Path:
    """
    Get the path to the sample file for a given source.

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')

    Returns:
    -------
        Path to the sample file

    """
    eval_dir = Path(__file__).parent
    samples_dir = eval_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    return samples_dir / f"{source}_sample_taxa.json"


def get_raw_data_path(source: str) -> Path:
    """
    Get the path to the raw data file for a given source.

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')

    Returns:
    -------
        Path to the raw data file

    """
    eval_dir = Path(__file__).parent
    project_root = eval_dir.parent.parent
    data_path = project_root / "data" / "raw" / f"{source}_strains.json"
    return data_path


def get_transformed_edges_path(source: str) -> Path:
    """
    Get the path to the transformed edges file for a given source.

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')

    Returns:
    -------
        Path to the transformed edges.tsv file

    """
    eval_dir = Path(__file__).parent
    project_root = eval_dir.parent.parent
    edges_path = project_root / "data" / "transformed" / source / "edges.tsv"
    return edges_path


def get_leaf_taxa_and_ncbitaxon(source: str) -> tuple[set[str], set[str]]:
    """
    Get CURIEs for leaf taxa (strains) and their NCBITaxon parents.

    Leaf taxa are strains with:
    - Exactly 1 subclass_of edge (to parent taxon)
    - At least 1 non-subclass edge (trait data)

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')

    Returns:
    -------
        Tuple of (leaf_strain_curies, ncbitaxon_curies)

    """
    edges_path = get_transformed_edges_path(source)

    if not edges_path.exists():
        raise FileNotFoundError(
            f"Transformed edges file not found: {edges_path}. "
            "Run 'poetry run kg transform -s {source}' first."
        )

    # Count edges per strain (by CURIE)
    subclass_edges = defaultdict(int)
    other_edges = defaultdict(int)
    strain_to_ncbitaxon = {}  # Map strain -> NCBITaxon parent

    print(f"Loading edges from {edges_path} to identify leaf taxa...")
    with open(edges_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            subject = row["subject"]
            predicate = row["predicate"]
            obj = row["object"]

            # Only look at strain nodes (all formats: old, KGMICROBE:, or registered prefixes)
            if is_strain_node(subject):
                if predicate == "biolink:subclass_of":
                    subclass_edges[subject] += 1
                    # Track NCBITaxon parent
                    if obj.startswith("NCBITaxon:"):
                        strain_to_ncbitaxon[subject] = obj
                else:
                    other_edges[subject] += 1

    # Filter for leaf taxa
    leaf_strains = set()
    ncbitaxon_parents = set()

    for strain_curie in subclass_edges.keys():
        subclass_count = subclass_edges[strain_curie]
        other_count = other_edges.get(strain_curie, 0)

        # Leaf taxa: exactly 1 subclass edge + at least 1 non-subclass edge
        if subclass_count == 1 and other_count >= 1:
            leaf_strains.add(strain_curie)
            # Also collect its NCBITaxon parent
            if strain_curie in strain_to_ncbitaxon:
                ncbitaxon_parents.add(strain_to_ncbitaxon[strain_curie])

    print(f"Found {len(leaf_strains)} leaf strains out of {len(subclass_edges)} total strains")
    print(f"Found {len(ncbitaxon_parents)} unique NCBITaxon parents")
    print(f"Filtered out {len(subclass_edges) - len(leaf_strains)} strains without trait data")

    return leaf_strains, ncbitaxon_parents


def extract_bacdive_ids(records: list[dict[str, Any]], sample_size: int = 10) -> list[int]:
    """
    Extract BacDive IDs from random sample of records.

    Args:
    ----
        records: List of BacDive records
        sample_size: Number of random records to sample

    Returns:
    -------
        List of BacDive IDs

    """
    sampled_records = random.sample(records, min(sample_size, len(records)))
    bacdive_ids = []

    for record in sampled_records:
        if "General" in record and "BacDive-ID" in record["General"]:
            bacdive_ids.append(record["General"]["BacDive-ID"])

    return bacdive_ids


def generate_sample(
    source: str, sample_size: int = 100, strain_count: int = 50, ncbitaxon_count: int = 50
) -> list[str]:
    """
    Generate a random sample of mixed taxa from transformed data.

    Samples include:
    - Leaf strains (exactly 1 subclass edge + trait data)
    - NCBITaxon parent nodes

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')
        sample_size: Total number of taxa to sample (default: 100)
        strain_count: Number of strain nodes to sample (default: 50)
        ncbitaxon_count: Number of NCBITaxon nodes to sample (default: 50)

    Returns:
    -------
        List of mixed taxa CURIEs (strains + NCBITaxon)

    """
    if strain_count + ncbitaxon_count != sample_size:
        raise ValueError(
            f"strain_count ({strain_count}) + ncbitaxon_count ({ncbitaxon_count}) "
            f"must equal sample_size ({sample_size})"
        )

    if source == "bacdive":
        # Get leaf strains and NCBITaxon parents from transformed edges
        leaf_strains, ncbitaxon_parents = get_leaf_taxa_and_ncbitaxon(source)

        if len(leaf_strains) < strain_count:
            raise ValueError(
                f"Not enough leaf strains ({len(leaf_strains)}) to sample {strain_count}. "
                f"Reduce --strain-count or transform more data."
            )

        if len(ncbitaxon_parents) < ncbitaxon_count:
            raise ValueError(
                f"Not enough NCBITaxon parents ({len(ncbitaxon_parents)}) to sample {ncbitaxon_count}. "
                f"Reduce --ncbitaxon-count or transform more data."
            )

        # Random sample from each group
        sampled_strains = random.sample(sorted(leaf_strains), strain_count)
        sampled_ncbitaxon = random.sample(sorted(ncbitaxon_parents), ncbitaxon_count)

        # Combine
        taxa_curies = sampled_strains + sampled_ncbitaxon

        print(f"Generated sample of {len(taxa_curies)} taxa CURIEs:")
        print(f"  - {len(sampled_strains)} strains")
        print(f"  - {len(sampled_ncbitaxon)} NCBITaxon nodes")
        return taxa_curies
    else:
        raise ValueError(f"Unsupported source: {source}")


def save_sample(source: str, taxa_curies: list[str]) -> None:
    """
    Save taxa sample to file.

    Args:
    ----
        source: Name of the data source
        taxa_curies: List of taxa CURIEs to save

    """
    sample_file = get_sample_file_path(source)

    sample_data = {
        "source": source,
        "sample_size": len(taxa_curies),
        "taxa_curies": taxa_curies,
    }

    with open(sample_file, "w") as f:
        json.dump(sample_data, f, indent=2)

    print(f"Saved sample to {sample_file}")


def load_sample(source: str) -> list[str] | None:
    """
    Load existing taxa sample from file.

    Args:
    ----
        source: Name of the data source

    Returns:
    -------
        List of taxa CURIEs, or None if file doesn't exist

    """
    sample_file = get_sample_file_path(source)

    if not sample_file.exists():
        return None

    with open(sample_file) as f:
        sample_data = json.load(f)

    # Handle both old format (taxa_ids) and new format (taxa_curies)
    if "taxa_curies" in sample_data:
        taxa_curies = sample_data["taxa_curies"]
    elif "taxa_ids" in sample_data:
        # Migrate old format: numeric IDs to CURIEs
        print("Migrating old sample format (numeric IDs) to CURIEs...")
        taxa_ids = sample_data["taxa_ids"]
        # Assume old format is always strain:bacdive_X
        taxa_curies = [f"strain:bacdive_{taxa_id}" for taxa_id in taxa_ids]
    else:
        raise ValueError(f"Invalid sample file format: {sample_file}")

    print(f"Loaded existing sample of {len(taxa_curies)} taxa from {sample_file}")
    return taxa_curies


def main() -> None:
    """Run the sample_taxa script."""
    parser = argparse.ArgumentParser(
        description="Generate or load random taxa samples for transform evaluation"
    )
    parser.add_argument(
        "--source", type=str, default="bacdive", help="Data source name (default: bacdive)"
    )
    parser.add_argument(
        "--regenerate", action="store_true", help="Force regeneration of sample even if one exists"
    )
    parser.add_argument(
        "--sample-size", type=int, default=100, help="Total number of taxa to sample (default: 100)"
    )
    parser.add_argument(
        "--strain-count",
        type=int,
        default=50,
        help="Number of strain nodes to sample (default: 50)",
    )
    parser.add_argument(
        "--ncbitaxon-count",
        type=int,
        default=50,
        help="Number of NCBITaxon nodes to sample (default: 50)",
    )

    args = parser.parse_args()

    # Try to load existing sample
    if not args.regenerate:
        existing_sample = load_sample(args.source)
        if existing_sample:
            print(f"Using existing sample: {existing_sample}")
            return

    # Generate new sample
    print(f"Generating new sample for source: {args.source}")
    taxa_curies = generate_sample(
        args.source,
        sample_size=args.sample_size,
        strain_count=args.strain_count,
        ncbitaxon_count=args.ncbitaxon_count,
    )

    # Save sample
    save_sample(args.source, taxa_curies)
    print("\nSample taxa CURIEs (first 10):")
    for curie in taxa_curies[:10]:
        print(f"  {curie}")


if __name__ == "__main__":
    main()
