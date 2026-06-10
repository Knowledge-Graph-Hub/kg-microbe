#!/usr/bin/env python3
"""Validate that all edges have proper knowledge source values."""

import sys
from pathlib import Path


def validate_edges_file(edges_file: Path) -> dict:
    """Check knowledge source column in edges file.

    Args:
        edges_file: Path to the edges.tsv file

    Returns:
        Dictionary with validation results
    """
    issues = []
    valid_count = 0
    total_edges = 0

    try:
        with open(edges_file) as f:
            header = f.readline().strip().split('\t')

            # Find knowledge source column index
            if 'primary_knowledge_source' not in header:
                return {
                    "file": str(edges_file),
                    "error": "No primary_knowledge_source column found",
                    "header": header,
                }

            ks_index = header.index('primary_knowledge_source')

            for line_num, line in enumerate(f, start=2):
                total_edges += 1
                parts = line.strip().split('\t')

                if len(parts) <= ks_index:
                    issues.append(f"Line {line_num}: Missing knowledge source column (only {len(parts)} columns)")
                    continue

                ks_value = parts[ks_index]

                # Check if empty
                if not ks_value or ks_value == "":
                    issues.append(f"Line {line_num}: Empty knowledge source")
                # Check if uses infores: format
                elif not ks_value.startswith("infores:"):
                    issues.append(f"Line {line_num}: Non-infores format: {ks_value}")
                else:
                    valid_count += 1

        return {
            "file": str(edges_file),
            "total_edges": total_edges,
            "valid_count": valid_count,
            "invalid_count": len(issues),
            "issues": issues[:20],  # Show first 20 issues
            "total_issues": len(issues)
        }
    except FileNotFoundError:
        return {
            "file": str(edges_file),
            "error": "File not found",
        }
    except Exception as e:
        return {
            "file": str(edges_file),
            "error": f"Error reading file: {str(e)}",
        }


def main():
    """Run validation on all transformed edges files."""
    # Get the project root directory (parent of scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    transforms_dir = project_root / "data" / "transformed"

    if not transforms_dir.exists():
        print(f"Error: Transforms directory not found: {transforms_dir}")
        sys.exit(1)

    print("=" * 80)
    print("KNOWLEDGE SOURCE VALIDATION REPORT")
    print("=" * 80)
    print()

    all_valid = True
    total_transforms = 0
    total_edges_checked = 0
    total_valid_edges = 0
    total_invalid_edges = 0

    # Find all transform directories
    transform_dirs = sorted([d for d in transforms_dir.iterdir() if d.is_dir()])

    for transform_dir in transform_dirs:
        edges_file = transform_dir / "edges.tsv"
        if not edges_file.exists():
            continue

        total_transforms += 1
        result = validate_edges_file(edges_file)

        print(f"Transform: {transform_dir.name}")
        print("-" * 80)

        if "error" in result:
            print(f"  ERROR: {result['error']}")
            all_valid = False
        else:
            total_edges_checked += result['total_edges']
            total_valid_edges += result['valid_count']
            total_invalid_edges += result['invalid_count']

            print(f"  Total edges: {result['total_edges']}")
            print(f"  Valid: {result['valid_count']} ({'100.0' if result['total_edges'] == 0 else f'{result['valid_count']/result['total_edges']*100:.1f}'}%)")

            if result['total_issues'] > 0:
                print(f"  Issues: {result['total_issues']}")
                print()
                print("  Sample issues:")
                for issue in result['issues']:
                    print(f"    - {issue}")
                all_valid = False
            else:
                print(f"  ✓ All edges have valid infores: knowledge sources")

        print()

    # Print summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Transforms checked: {total_transforms}")
    print(f"Total edges: {total_edges_checked}")
    print(f"Valid edges: {total_valid_edges} ({total_valid_edges/total_edges_checked*100:.1f}%)" if total_edges_checked > 0 else "No edges found")
    print(f"Invalid edges: {total_invalid_edges}")
    print()

    if all_valid and total_transforms > 0:
        print("✓ SUCCESS: All transforms have valid knowledge sources!")
        return 0
    elif total_transforms == 0:
        print("⚠ WARNING: No transform directories found")
        return 1
    else:
        print("✗ FAILURE: Some transforms have invalid knowledge sources")
        return 1


if __name__ == "__main__":
    sys.exit(main())
