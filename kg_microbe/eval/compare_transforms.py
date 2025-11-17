"""Compare two versions of transform output to detect changes."""

import argparse
import json
from pathlib import Path
from typing import Any

from kg_microbe.eval.evaluate_transform import evaluate_transform


def compare_dicts(baseline: dict, current: dict, path: str = "") -> list[dict[str, Any]]:
    """
    Recursively compare two dictionaries and return differences.

    Args:
    ----
        baseline: Baseline dictionary
        current: Current dictionary
        path: Current path in dictionary (for nested dicts)

    Returns:
    -------
        List of difference dictionaries

    """
    differences = []

    # Check for missing keys
    for key in baseline:
        if key not in current:
            differences.append(
                {
                    "path": f"{path}.{key}" if path else key,
                    "type": "missing_key",
                    "baseline_value": baseline[key],
                    "current_value": None,
                }
            )

    # Check for new keys
    for key in current:
        if key not in baseline:
            differences.append(
                {
                    "path": f"{path}.{key}" if path else key,
                    "type": "new_key",
                    "baseline_value": None,
                    "current_value": current[key],
                }
            )

    # Check for value changes
    for key in baseline:
        if key not in current:
            continue

        current_path = f"{path}.{key}" if path else key
        baseline_val = baseline[key]
        current_val = current[key]

        # Handle nested dictionaries
        if isinstance(baseline_val, dict) and isinstance(current_val, dict):
            nested_diffs = compare_dicts(baseline_val, current_val, current_path)
            differences.extend(nested_diffs)
        # Handle numeric values
        elif isinstance(baseline_val, (int, float)) and isinstance(current_val, (int, float)):
            if baseline_val != current_val:
                change_pct = None
                if baseline_val != 0:
                    change_pct = ((current_val - baseline_val) / baseline_val) * 100

                differences.append(
                    {
                        "path": current_path,
                        "type": "value_change",
                        "baseline_value": baseline_val,
                        "current_value": current_val,
                        "change": current_val - baseline_val,
                        "change_percent": change_pct,
                    }
                )
        # Handle other value types
        elif baseline_val != current_val:
            differences.append(
                {
                    "path": current_path,
                    "type": "value_change",
                    "baseline_value": baseline_val,
                    "current_value": current_val,
                }
            )

    return differences


def categorize_differences(differences: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Categorize differences by severity and type.

    Args:
    ----
        differences: List of difference dictionaries

    Returns:
    -------
        Dictionary categorizing differences

    """
    categorized = {
        "critical": [],  # Missing data, large decreases
        "warning": [],  # Moderate changes
        "info": [],  # Minor changes, additions
    }

    for diff in differences:
        diff_type = diff["type"]

        # Missing keys are critical
        if diff_type == "missing_key":
            categorized["critical"].append(diff)

        # New keys are informational
        elif diff_type == "new_key":
            categorized["info"].append(diff)

        # Value changes need more analysis
        elif diff_type == "value_change":
            # Critical: large decreases in counts
            if "change_percent" in diff and diff["change_percent"] is not None:
                if diff["change_percent"] < -10:  # >10% decrease
                    categorized["critical"].append(diff)
                elif diff["change_percent"] < -5:  # 5-10% decrease
                    categorized["warning"].append(diff)
                elif diff["change_percent"] > 10:  # >10% increase
                    categorized["warning"].append(diff)
                else:
                    categorized["info"].append(diff)
            else:
                categorized["info"].append(diff)

    return categorized


def print_comparison_summary(categorized: dict[str, list[dict[str, Any]]]) -> None:
    """
    Print a formatted summary of differences.

    Args:
    ----
        categorized: Categorized differences

    """
    print("\n=== Comparison Summary ===\n")

    for severity in ["critical", "warning", "info"]:
        diffs = categorized[severity]
        if not diffs:
            continue

        print(f"{severity.upper()}: {len(diffs)} differences")
        print("-" * 60)

        for diff in diffs:
            path = diff["path"]
            diff_type = diff["type"]

            if diff_type == "missing_key":
                print(f"  ❌ MISSING: {path}")
                print(f"     Baseline had: {diff['baseline_value']}")

            elif diff_type == "new_key":
                print(f"  ✨ NEW: {path}")
                print(f"     Current has: {diff['current_value']}")

            elif diff_type == "value_change":
                baseline = diff["baseline_value"]
                current = diff["current_value"]

                if "change_percent" in diff and diff["change_percent"] is not None:
                    change = diff["change"]
                    change_pct = diff["change_percent"]
                    symbol = "📈" if change > 0 else "📉"
                    print(f"  {symbol} CHANGED: {path}")
                    print(f"     {baseline} → {current} ({change:+d}, {change_pct:+.1f}%)")
                else:
                    print(f"  🔄 CHANGED: {path}")
                    print(f"     {baseline} → {current}")

        print()


def compare_transforms(
    source: str,
    baseline_dir: Path | None = None,
    current_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Compare baseline and current transform outputs.

    Args:
    ----
        source: Data source name
        baseline_dir: Path to baseline transformed data directory
        current_dir: Path to current transformed data directory

    Returns:
    -------
        Dictionary with comparison results

    """
    print("Evaluating baseline transform...")
    baseline_results = evaluate_transform(source, baseline_dir)

    print("\nEvaluating current transform...")
    current_results = evaluate_transform(source, current_dir)

    print("\nComparing results...")

    # Compare statistics only (not the full results with IDs)
    baseline_stats = {
        "node_statistics": baseline_results["node_statistics"],
        "edge_statistics": baseline_results["edge_statistics"],
    }

    current_stats = {
        "node_statistics": current_results["node_statistics"],
        "edge_statistics": current_results["edge_statistics"],
    }

    differences = compare_dicts(baseline_stats, current_stats)
    categorized = categorize_differences(differences)

    return {
        "source": source,
        "baseline_summary": {
            "total_nodes": baseline_results["node_statistics"]["total_nodes"],
            "total_edges": baseline_results["edge_statistics"]["total_edges"],
            "avg_edges_per_strain": baseline_results["edge_statistics"]["avg_edges_per_strain"],
        },
        "current_summary": {
            "total_nodes": current_results["node_statistics"]["total_nodes"],
            "total_edges": current_results["edge_statistics"]["total_edges"],
            "avg_edges_per_strain": current_results["edge_statistics"]["avg_edges_per_strain"],
        },
        "differences": differences,
        "categorized_differences": {
            "critical": categorized["critical"],
            "warning": categorized["warning"],
            "info": categorized["info"],
        },
        "summary": {
            "critical_count": len(categorized["critical"]),
            "warning_count": len(categorized["warning"]),
            "info_count": len(categorized["info"]),
            "total_differences": len(differences),
        },
    }


def main() -> None:
    """Run the compare_transforms script."""
    parser = argparse.ArgumentParser(description="Compare two versions of transform output")
    parser.add_argument(
        "--source", type=str, default="bacdive", help="Data source name (default: bacdive)"
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        required=True,
        help="Path to baseline transformed data directory",
    )
    parser.add_argument(
        "--current-dir",
        type=Path,
        help="Path to current transformed data directory (default: data/transformed/{source})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to save comparison report (default: eval/samples/{source}_comparison.json)",
    )

    args = parser.parse_args()

    # Run comparison
    results = compare_transforms(args.source, args.baseline_dir, args.current_dir)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        eval_dir = Path(__file__).parent
        samples_dir = eval_dir / "samples"
        output_path = samples_dir / f"{args.source}_comparison.json"

    # Save results
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Comparison complete. Results saved to {output_path}")

    # Print summary
    print_comparison_summary(results["categorized_differences"])

    # Exit with appropriate code
    if results["summary"]["critical_count"] > 0:
        print("⚠️  CRITICAL differences detected!")
        exit(1)
    elif results["summary"]["warning_count"] > 0:
        print("⚠️  Warnings detected")
        exit(0)
    else:
        print("✅ No significant differences detected")
        exit(0)


if __name__ == "__main__":
    main()
