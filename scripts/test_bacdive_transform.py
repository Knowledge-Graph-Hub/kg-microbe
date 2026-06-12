#!/usr/bin/env python3
"""Test BacDive transform with the test dataset."""

import shutil
from pathlib import Path

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform


def main():
    """Run BacDive transform on test data."""
    print("Testing BacDive transform with 20-taxa test dataset...")

    # Paths
    test_json = Path("tests/resources/raw/bacdive_strains.json")
    test_tmp_dir = Path("kg_microbe/transform_utils/bacdive/tmp_test")
    output_dir = Path("data/transformed_test/bacdive")

    # Validate test data exists
    if not test_json.exists():
        print(f"❌ Test data not found: {test_json}")
        print("Run scripts/create_test_bacdive.py first")
        return 1

    # Copy test JSON to data/raw for transform to find
    print(f"\nCopying test JSON to data/raw/bacdive_strains.json...")
    backup_json = Path("data/raw/bacdive_strains.json.backup")
    original_json = Path("data/raw/bacdive_strains.json")

    # Backup original if it exists
    if original_json.exists():
        print(f"  Backing up original to {backup_json}")
        shutil.copy(original_json, backup_json)

    # Copy test JSON
    shutil.copy(test_json, original_json)
    print(f"  ✅ Test JSON in place (20 records)")

    try:
        # Create test output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run transform
        print(f"\nRunning BacDive transform...")
        print(f"  Input directory: data/raw")
        print(f"  Output directory: {output_dir}")
        transform = BacDiveTransform(input_dir=Path("data/raw"), output_dir=output_dir)
        transform.run(show_status=True)

        # Check outputs (transform creates nested bacdive directory)
        actual_output_dir = output_dir / "bacdive"
        nodes_file = actual_output_dir / "nodes.tsv"
        edges_file = actual_output_dir / "edges.tsv"

        if nodes_file.exists() and edges_file.exists():
            # Count lines
            with open(nodes_file) as f:
                node_count = sum(1 for _ in f) - 1  # subtract header
            with open(edges_file) as f:
                edge_count = sum(1 for _ in f) - 1  # subtract header

            print(f"\n✅ Transform completed successfully!")
            print(f"   Nodes: {node_count}")
            print(f"   Edges: {edge_count}")

            # Check for empty relations
            print(f"\nChecking for empty relation values...")
            empty_count = 0
            with open(edges_file) as f:
                header = f.readline().strip().split("\t")
                relation_idx = header.index("relation")
                for line in f:
                    fields = line.strip().split("\t")
                    if relation_idx < len(fields):
                        relation = fields[relation_idx]
                        if not relation or relation == "":
                            empty_count += 1

            if empty_count == 0:
                print(f"   ✅ No empty relations found!")
            else:
                print(f"   ❌ Found {empty_count} empty relations")

            print(f"\nOutput files:")
            print(f"   {nodes_file}")
            print(f"   {edges_file}")

            return 0
        else:
            print(f"\n❌ Transform failed - output files not created")
            return 1

    finally:
        # Restore original JSON
        print(f"\nRestoring original bacdive_strains.json...")
        if backup_json.exists():
            shutil.move(backup_json, original_json)
            print(f"  ✅ Restored from backup")
        else:
            # Remove test JSON if no backup existed
            if original_json.exists():
                original_json.unlink()
            print(f"  ✅ Removed test JSON (no original existed)")


if __name__ == "__main__":
    exit(main())
