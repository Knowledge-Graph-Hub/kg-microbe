#!/usr/bin/env python
"""
Consolidate multi-category nodes in merged knowledge graph.

This script resolves nodes with pipe-delimited categories (e.g., "biolink:ChemicalEntity|biolink:SmallMolecule")
using explicit, verified consolidation rules that account for semantic meaning and Biolink Model hierarchy.

Usage:
    python kg_microbe/utils/consolidate_categories.py \
        --input data/merged/merged-kg_nodes.tsv \
        --output data/merged/merged-kg_nodes_consolidated.tsv \
        --report data/merged/category_consolidation_report.txt
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

import yaml


def consolidate_node_categories(
    input_file: str,
    output_file: str,
    report_file: str = None,
    rules_file: str = None,
) -> None:
    """
    Read merged nodes TSV and consolidate multi-category nodes.

    For nodes with pipe-delimited categories, uses explicit verified rules
    that account for semantic meaning (e.g., ChemicalRole for functional
    classifications vs SmallMolecule for structural entities).

    Args:
        input_file: Path to input nodes TSV file (with multi-category nodes)
        output_file: Path to output consolidated nodes TSV file (single categories)
        report_file: Optional path to consolidation report file
        rules_file: Optional path to rules YAML file (defaults to package location)

    Example:
        >>> consolidate_node_categories(
        ...     "data/merged/merged-kg_nodes.tsv",
        ...     "data/merged/merged-kg_nodes_consolidated.tsv",
        ...     "data/merged/category_consolidation_report.txt"
        ... )
        ✓ Consolidated 1,117 multi-category nodes
        ✓ Output written to: data/merged/merged-kg_nodes_consolidated.tsv
        ✓ Report written to: data/merged/category_consolidation_report.txt

    """
    # Load consolidation rules
    if rules_file is None:
        # Default to package location
        rules_file = Path(__file__).parent / "category_consolidation_rules.yaml"

    with open(rules_file) as f:
        config = yaml.safe_load(f)
        rules = config.get("rules", {})
        resolution_notes = config.get("resolution_notes", {})

    # Statistics
    total_nodes = 0
    multi_category_nodes = 0
    consolidations = Counter()  # pattern -> count
    unknown_patterns = Counter()  # pattern -> count (no rule found)
    special_cases = []  # Nodes with resolution notes

    with open(input_file) as infile, open(output_file, "w") as outfile:
        reader = csv.DictReader(infile, delimiter="\t")
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames, delimiter="\t")
        writer.writeheader()

        for row in reader:
            total_nodes += 1
            category = row["category"]

            # Check for multi-category (pipe-delimited)
            if "|" in category:
                multi_category_nodes += 1
                categories = category.split("|")

                # Sort categories to match rules (rules use sorted pattern)
                sorted_pattern = "|".join(sorted(categories))
                consolidations[sorted_pattern] += 1

                # Check if this is a special case with resolution notes
                node_id = row.get("id", "")
                if node_id in resolution_notes:
                    special_cases.append(
                        {
                            "id": node_id,
                            "name": row.get("name", ""),
                            "original_pattern": category,
                            "note": resolution_notes[node_id],
                        }
                    )

                # Apply rule if exists
                if sorted_pattern in rules:
                    row["category"] = rules[sorted_pattern]
                else:
                    # No rule found - log as unknown pattern and use first category
                    unknown_patterns[sorted_pattern] += 1
                    row["category"] = categories[0]  # Fallback to first category
                    print(
                        f"WARNING: Unknown pattern '{sorted_pattern}' for node {node_id} - using {categories[0]}"
                    )

            writer.writerow(row)

    # Generate report
    if report_file:
        with open(report_file, "w") as f:
            f.write("Category Consolidation Report\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Total nodes processed: {total_nodes:,}\n")
            f.write(f"Multi-category nodes found: {multi_category_nodes:,}\n")
            f.write(f"Multi-category percentage: {(multi_category_nodes/total_nodes)*100:.2f}%\n")
            f.write(f"Unknown patterns (no rule): {len(unknown_patterns)}\n\n")

            f.write("Consolidation Method: Explicit verified rules\n")
            f.write("Rules file: " + str(rules_file) + "\n\n")

            f.write("Consolidation Patterns (sorted by count):\n")
            f.write("-" * 80 + "\n")
            for pattern, count in consolidations.most_common():
                percentage = (count / multi_category_nodes) * 100
                f.write(f"\nPattern: {pattern}\n")
                f.write(f"  Count: {count:,} ({percentage:.1f}% of multi-category nodes)\n")

                # Show selected category from rules
                if pattern in rules:
                    f.write(f"  Selected: {rules[pattern]}\n")
                    f.write("  Method: Explicit rule (verified)\n")
                else:
                    categories = pattern.split("|")
                    f.write(f"  Selected: {categories[0]} (FALLBACK - no rule found)\n")
                    f.write("  Method: First category (default fallback)\n")

            # Report unknown patterns
            if unknown_patterns:
                f.write("\n\n")
                f.write("UNKNOWN PATTERNS (No Rule Defined):\n")
                f.write("=" * 80 + "\n")
                for pattern, count in unknown_patterns.most_common():
                    f.write(f"\n{pattern}: {count} nodes\n")
                    f.write("  Action: Used first category as fallback\n")
                    f.write(
                        "  Recommendation: Add explicit rule to category_consolidation_rules.yaml\n"
                    )

            # Report special cases
            if special_cases:
                f.write("\n\n")
                f.write("SPECIAL CASES (Resolution Notes):\n")
                f.write("=" * 80 + "\n")
                for case in special_cases:
                    f.write(f"\nNode: {case['id']} - {case['name']}\n")
                    f.write(f"  Original: {case['original_pattern']}\n")
                    f.write(f"  Selected: {case['note']['selected']}\n")
                    f.write(f"  Rationale: {case['note']['rationale']}\n")

    print(f"✓ Consolidated {multi_category_nodes:,} multi-category nodes")
    print(f"✓ Total nodes: {total_nodes:,}")
    print(f"✓ Multi-category percentage: {(multi_category_nodes/total_nodes)*100:.2f}%")
    print(f"✓ Output written to: {output_file}")
    if report_file:
        print(f"✓ Report written to: {report_file}")


def main():
    """Parse command-line arguments and run consolidation."""
    parser = argparse.ArgumentParser(
        description="Consolidate multi-category nodes in merged knowledge graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python kg_microbe/utils/consolidate_categories.py \\
      --input data/merged/merged-kg_nodes.tsv \\
      --output data/merged/merged-kg_nodes_consolidated.tsv

  # With report generation
  python kg_microbe/utils/consolidate_categories.py \\
      --input data/merged/merged-kg_nodes.tsv \\
      --output data/merged/merged-kg_nodes_consolidated.tsv \\
      --report data/merged/category_consolidation_report.txt
        """,
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input nodes TSV file with multi-category nodes",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output consolidated nodes TSV file with single categories",
    )
    parser.add_argument(
        "--report",
        help="Optional consolidation report file (detailed statistics)",
    )
    parser.add_argument(
        "--rules",
        help="Optional path to rules YAML file (defaults to package location)",
    )

    args = parser.parse_args()

    # Run consolidation
    consolidate_node_categories(args.input, args.output, args.report, args.rules)


if __name__ == "__main__":
    main()
