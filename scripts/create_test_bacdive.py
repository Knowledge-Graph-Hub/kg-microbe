#!/usr/bin/env python3
"""Create a test BacDive dataset with 20 random taxa."""

import json
import random
import shutil
from pathlib import Path

import pandas as pd

# Set random seed for reproducibility
random.seed(42)

# Paths
BACDIVE_TMP = Path("kg_microbe/transform_utils/bacdive/tmp")
BACDIVE_RAW = Path("data/raw")
TEST_DIR = Path("tests/resources/bacdive")
TEST_RAW_DIR = Path("tests/resources/raw")
YAML_DIR = BACDIVE_TMP / "yaml"
TEST_YAML_DIR = TEST_DIR / "yaml"

# Number of random taxa to sample
N_TAXA = 20


def main():
    """Create test BacDive dataset."""
    print(f"Creating test BacDive dataset with {N_TAXA} random taxa...")

    # Create test directory structure
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    TEST_YAML_DIR.mkdir(parents=True, exist_ok=True)

    # Read main bacdive.tsv
    print("\nReading bacdive.tsv...")
    df_main = pd.read_csv(BACDIVE_TMP / "bacdive.tsv", sep="\t")
    print(f"Total taxa in bacdive.tsv: {len(df_main)}")

    # Randomly sample N_TAXA rows
    df_sample = df_main.sample(n=N_TAXA, random_state=42)

    # Extract BacDive IDs (format: "bacdive:12345" -> "12345")
    bacdive_ids = df_sample["bacdive_id"].str.replace("bacdive:", "").tolist()
    print(f"\nSampled taxa BacDive IDs: {bacdive_ids}")

    # Save sampled bacdive.tsv
    output_file = TEST_DIR / "bacdive.tsv"
    df_sample.to_csv(output_file, sep="\t", index=False)
    print(f"\n✅ Saved {len(df_sample)} taxa to {output_file}")

    # Process other TSV files
    for tsv_file in ["bacdive_name_tax_classification.tsv", "bacdive_physiology_metabolism.tsv"]:
        input_path = BACDIVE_TMP / tsv_file
        if not input_path.exists():
            print(f"⚠️  {tsv_file} not found, skipping")
            continue

        print(f"\nReading {tsv_file}...")
        df = pd.read_csv(input_path, sep="\t")

        # Filter to sampled BacDive IDs
        df_filtered = df[df["bacdive_id"].isin(df_sample["bacdive_id"])]

        # Save filtered TSV
        output_path = TEST_DIR / tsv_file
        df_filtered.to_csv(output_path, sep="\t", index=False)
        print(f"✅ Saved {len(df_filtered)} rows to {output_path}")

    # Copy corresponding YAML files
    print(f"\nCopying {len(bacdive_ids)} YAML files...")
    copied = 0
    missing = []

    for bacdive_id in bacdive_ids:
        yaml_file = YAML_DIR / f"{bacdive_id}.yaml"
        if yaml_file.exists():
            shutil.copy(yaml_file, TEST_YAML_DIR / f"{bacdive_id}.yaml")
            copied += 1
        else:
            missing.append(bacdive_id)

    print(f"✅ Copied {copied} YAML files to {TEST_YAML_DIR}")

    if missing:
        print(f"⚠️  Missing YAML files for IDs: {missing}")

    # Copy bacdive_mappings.tsv (reference data, not filtered)
    mappings_file = BACDIVE_TMP / "bacdive_mappings.tsv"
    if mappings_file.exists():
        shutil.copy(mappings_file, TEST_DIR / "bacdive_mappings.tsv")
        print(f"\n✅ Copied {mappings_file.name} to {TEST_DIR}")

    # Extract corresponding records from bacdive_strains.json
    json_input = BACDIVE_RAW / "bacdive_strains.json"
    if json_input.exists():
        print(f"\nExtracting {N_TAXA} records from bacdive_strains.json...")
        print("  (This may take a few minutes for the 748MB file)")

        with open(json_input, "r") as f:
            all_records = json.load(f)

        # Handle both dict and list formats
        if isinstance(all_records, dict):
            all_records = list(all_records.values())

        # Filter to sampled BacDive IDs (numeric format)
        bacdive_ids_int = [int(bid) for bid in bacdive_ids]
        test_records = [
            record
            for record in all_records
            if record.get("General", {}).get("BacDive-ID") in bacdive_ids_int
        ]

        # Save test JSON file
        TEST_RAW_DIR.mkdir(parents=True, exist_ok=True)
        test_json_output = TEST_RAW_DIR / "bacdive_strains.json"
        with open(test_json_output, "w") as f:
            json.dump(test_records, f, indent=2)

        print(f"✅ Saved {len(test_records)} records to {test_json_output}")
        print(
            f"   File size reduced from 748MB to {test_json_output.stat().st_size / 1024 / 1024:.1f}MB"
        )
    else:
        print(f"\n⚠️  {json_input} not found, skipping JSON extraction")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Test dataset locations:")
    print(f"  TSV/YAML: {TEST_DIR}")
    print(f"  JSON: {TEST_RAW_DIR / 'bacdive_strains.json'}")
    print(f"\nNumber of taxa: {N_TAXA}")
    print(f"Sampled BacDive IDs: {', '.join(bacdive_ids)}")
    print(f"YAML files: {copied}")
    print(f"JSON records: {len(test_records) if 'test_records' in locals() else 'N/A'}")
    print("\nTo run transform on test data:")
    print(f"  cp {TEST_RAW_DIR / 'bacdive_strains.json'} data/raw/bacdive_strains_test.json")
    print(f"  # Modify BacDive transform to read from bacdive_strains_test.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
