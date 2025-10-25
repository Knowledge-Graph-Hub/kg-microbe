"""Evaluate transform output for sampled taxa."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import bioregistry

from kg_microbe.eval.sample_taxa import is_strain_node, load_sample
from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    ID_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    SUBJECT_COLUMN,
)


def get_transformed_data_path(source: str, data_dir: Path | None = None) -> Path:
    """
    Get the path to transformed data directory for a given source.

    Args:
    ----
        source: Name of the data source (e.g., 'bacdive')
        data_dir: Optional override for data directory path

    Returns:
    -------
        Path to transformed data directory

    """
    if data_dir:
        return data_dir
    eval_dir = Path(__file__).parent
    project_root = eval_dir.parent.parent
    return project_root / "data" / "transformed" / source


def get_strain_node_ids(source: str, taxa_curies: list[str]) -> set[str]:
    """
    Convert taxa CURIEs to search set including both old and new formats.

    Args:
    ----
        source: Name of the data source
        taxa_curies: List of taxa CURIEs (strains + NCBITaxon)

    Returns:
    -------
        Set of node IDs to search for (includes alternative formats for strain compatibility)

    Note:
    ----
        For strain CURIEs, adds both old (strain:bacdive_X) and new (KGMICROBE:X)
        formats to support transition between ID schemes.
        Registered prefixes (ATCC:, DSMZ:, etc.) and NCBITaxon CURIEs are added as-is.

    """
    if source == "bacdive":
        node_ids = set()
        for curie in taxa_curies:
            # Add the input CURIE as-is
            node_ids.add(curie)

            # For strains in old/new KGMICROBE formats, add alternative format for compatibility
            if curie.startswith("strain:bacdive_"):
                # If old format, also add new KGMICROBE format
                bacdive_id = curie.replace("strain:bacdive_", "")
                node_ids.add(f"KGMICROBE:{bacdive_id}")
            elif curie.startswith("KGMICROBE:"):
                # If new KGMICROBE format, also add old format
                bacdive_id = curie.replace("KGMICROBE:", "")
                node_ids.add(f"strain:bacdive_{bacdive_id}")
            elif curie.startswith("kgmicrobe:"):
                # Handle old lowercase format (for backward compatibility)
                bacdive_id = curie.replace("kgmicrobe:", "")
                node_ids.add(f"strain:bacdive_{bacdive_id}")
                node_ids.add(f"KGMICROBE:{bacdive_id}")
            # Registered prefixes (ATCC:, DSMZ:, etc.) and NCBITaxon are already added as-is

        return node_ids
    else:
        raise ValueError(f"Unsupported source: {source}")


def load_nodes(nodes_file: Path, node_ids: set[str]) -> dict[str, dict[str, Any]]:
    """
    Load specific nodes by ID.

    Args:
    ----
        nodes_file: Path to nodes.tsv file
        node_ids: Set of node IDs to load

    Returns:
    -------
        Dictionary mapping node ID to node attributes

    """
    nodes = {}

    with open(nodes_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            node_id = row[ID_COLUMN]
            if node_id in node_ids:
                nodes[node_id] = row

    return nodes


def load_edges(edges_file: Path, strain_ids: set[str]) -> list[dict[str, str]]:
    """
    Load edges for sampled strains.

    Args:
    ----
        edges_file: Path to edges.tsv file
        strain_ids: Set of strain node IDs to include

    Returns:
    -------
        List of edge dictionaries

    """
    edges = []

    with open(edges_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            subject = row[SUBJECT_COLUMN]
            obj = row[OBJECT_COLUMN]

            # Include edges where subject or object is a sampled strain
            if subject in strain_ids or obj in strain_ids:
                edges.append(row)

    return edges


def calculate_edge_statistics(
    edges: list[dict[str, str]], nodes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """
    Calculate statistics about edges.

    Args:
    ----
        edges: List of edge dictionaries
        nodes: Dictionary of nodes

    Returns:
    -------
        Dictionary of edge statistics

    """
    predicate_counts = Counter()
    category_pair_counts = defaultdict(Counter)
    edges_per_strain = defaultdict(int)

    for edge in edges:
        subject = edge[SUBJECT_COLUMN]
        predicate = edge[PREDICATE_COLUMN]
        obj = edge[OBJECT_COLUMN]

        predicate_counts[predicate] += 1

        # Get categories
        subject_category = nodes.get(subject, {}).get(CATEGORY_COLUMN, "Unknown")
        object_category = nodes.get(obj, {}).get(CATEGORY_COLUMN, "Unknown")

        category_pair = f"{subject_category} -> {object_category}"
        category_pair_counts[predicate][category_pair] += 1

        # Count edges per strain (subject)
        if is_strain_node(subject):
            edges_per_strain[subject] += 1

    return {
        "total_edges": len(edges),
        "predicate_counts": dict(predicate_counts),
        "category_pairs_by_predicate": {
            pred: dict(pairs) for pred, pairs in category_pair_counts.items()
        },
        "edges_per_strain": dict(edges_per_strain),
        "avg_edges_per_strain": (
            sum(edges_per_strain.values()) / len(edges_per_strain) if edges_per_strain else 0
        ),
    }


def calculate_node_statistics(
    nodes: dict[str, dict[str, Any]], sampled_node_ids: set[str]
) -> dict[str, Any]:
    """
    Calculate statistics about nodes.

    Args:
    ----
        nodes: Dictionary of nodes
        sampled_node_ids: Set of sampled node IDs (strains + NCBITaxon)

    Returns:
    -------
        Dictionary of node statistics

    """
    category_counts = Counter()
    sampled_strains_old = []  # strain:bacdive_X (sampled)
    sampled_strains_new = []  # kgmicrobe:X (sampled)
    sampled_ncbitaxon = []  # NCBITaxon (sampled)
    connected_ncbitaxon = []  # NCBITaxon (connected but not sampled)
    other_nodes = []

    for node_id, node in nodes.items():
        category = node.get(CATEGORY_COLUMN, "Unknown")
        category_counts[category] += 1

        # Categorize nodes by type and format
        # NCBITaxon nodes (sampled or connected)
        if node_id.startswith("NCBITaxon:"):
            if node_id in sampled_node_ids:
                sampled_ncbitaxon.append(node_id)
            else:
                connected_ncbitaxon.append(node_id)
        # Strain nodes (all formats)
        elif is_strain_node(node_id):
            if node_id in sampled_node_ids:
                # Categorize by format
                if node_id.startswith("strain:bacdive_"):
                    sampled_strains_old.append(node_id)
                else:
                    # New format: KGMICROBE: or registered prefixes (ATCC:, DSMZ:, etc.)
                    sampled_strains_new.append(node_id)
        # Everything else (chemicals, phenotypes, etc.)
        else:
            other_nodes.append(node_id)

    all_sampled_strains = sampled_strains_old + sampled_strains_new
    all_sampled_taxa = all_sampled_strains + sampled_ncbitaxon
    all_taxa_nodes = all_sampled_taxa + connected_ncbitaxon

    return {
        "total_nodes": len(nodes),
        "sampled_strains_count": len(all_sampled_strains),
        "sampled_strains_old_format": sampled_strains_old,
        "sampled_strains_new_format": sampled_strains_new,
        "sampled_ncbitaxon_count": len(sampled_ncbitaxon),
        "sampled_ncbitaxon_nodes": sampled_ncbitaxon,
        "connected_ncbitaxon_count": len(connected_ncbitaxon),
        "connected_ncbitaxon_nodes": connected_ncbitaxon,
        "total_sampled_taxa_count": len(all_sampled_taxa),
        "total_taxa_nodes_count": len(all_taxa_nodes),
        "other_nodes_count": len(other_nodes),
        "category_counts": dict(category_counts),
    }


def evaluate_transform(source: str, data_dir: Path | None = None) -> dict[str, Any]:
    """
    Evaluate transform output for sampled taxa.

    Args:
    ----
        source: Name of the data source
        data_dir: Optional override for data directory path

    Returns:
    -------
        Dictionary of evaluation results

    """
    # Load sample
    taxa_curies = load_sample(source)
    if not taxa_curies:
        raise ValueError(f"No sample found for source: {source}. Run sample_taxa.py first.")

    strain_ids = get_strain_node_ids(source, taxa_curies)

    # Load transformed data
    transformed_path = get_transformed_data_path(source, data_dir)
    nodes_file = transformed_path / "nodes.tsv"
    edges_file = transformed_path / "edges.tsv"

    if not nodes_file.exists():
        raise FileNotFoundError(f"Nodes file not found: {nodes_file}")
    if not edges_file.exists():
        raise FileNotFoundError(f"Edges file not found: {edges_file}")

    # Load edges first to identify all connected nodes
    print(f"Loading edges from {edges_file}")
    edges = load_edges(edges_file, strain_ids)
    print(f"Loaded {len(edges)} edges")

    # Collect all node IDs from edges
    node_ids_to_load = set()
    for edge in edges:
        node_ids_to_load.add(edge[SUBJECT_COLUMN])
        node_ids_to_load.add(edge[OBJECT_COLUMN])

    print(f"Loading {len(node_ids_to_load)} nodes from {nodes_file}")
    nodes = load_nodes(nodes_file, node_ids_to_load)
    print(f"Loaded {len(nodes)} nodes")

    # Calculate statistics
    edge_stats = calculate_edge_statistics(edges, nodes)
    node_stats = calculate_node_statistics(nodes, strain_ids)

    return {
        "source": source,
        "sample_size": len(taxa_curies),
        "sampled_taxa_curies": taxa_curies,
        "node_statistics": node_stats,
        "edge_statistics": edge_stats,
    }


def main() -> None:
    """Run the evaluate_transform script."""
    parser = argparse.ArgumentParser(description="Evaluate transform output for sampled taxa")
    parser.add_argument(
        "--source", type=str, default="bacdive", help="Data source name (default: bacdive)"
    )
    parser.add_argument("--data-dir", type=Path, help="Override path to transformed data directory")
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to save evaluation report (default: eval/samples/{source}_evaluation.json)",
    )

    args = parser.parse_args()

    # Evaluate transform
    results = evaluate_transform(args.source, args.data_dir)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        eval_dir = Path(__file__).parent
        samples_dir = eval_dir / "samples"
        output_path = samples_dir / f"{args.source}_evaluation.json"

    # Save results
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nEvaluation complete. Results saved to {output_path}")

    # Print summary
    print("\n=== Summary ===")
    print(f"Sample size: {results['sample_size']} taxa")
    print(f"Total nodes: {results['node_statistics']['total_nodes']}")
    print(f"Total edges: {results['edge_statistics']['total_edges']}")
    print(f"Avg edges per strain: {results['edge_statistics']['avg_edges_per_strain']:.1f}")
    print("\nTop 5 predicates:")
    for pred, count in sorted(
        results["edge_statistics"]["predicate_counts"].items(), key=lambda x: x[1], reverse=True
    )[:5]:
        print(f"  {pred}: {count}")


if __name__ == "__main__":
    main()
