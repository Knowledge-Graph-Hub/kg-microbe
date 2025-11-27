#!/usr/bin/env python3
"""Check BacDive strains for enzymes without EC IDs."""

import json
from collections import defaultdict
from pathlib import Path


def check_enzymes_without_ec(bacdive_file: str) -> None:
    """
    Check BacDive data for enzymes without EC IDs.

    Args:
    ----
        bacdive_file: Path to bacdive_strains.json file

    """
    # Load the BacDive data
    print(f"Loading data from {bacdive_file}...")
    with open(bacdive_file) as f:
        data = json.load(f)

    print(f"Total strains in file: {len(data)}")

    # Track enzymes without EC IDs
    enzymes_without_ec = []
    strains_with_missing_ec = set()
    enzyme_name_counts = defaultdict(int)

    # Iterate through all strains
    for strain_data in data:
        # Extract strain ID (handles MongoDB ObjectId format)
        strain_id_raw = strain_data.get("_id", "Unknown")
        if isinstance(strain_id_raw, dict) and "$oid" in strain_id_raw:
            strain_id = strain_id_raw["$oid"]
        else:
            strain_id = str(strain_id_raw)

        # Navigate to Physiology and metabolism section
        if "Physiology and metabolism" not in strain_data:
            continue

        phys_meta = strain_data["Physiology and metabolism"]

        # Check for enzymes section
        if "enzymes" not in phys_meta:
            continue

        enzymes = phys_meta["enzymes"]
        if not isinstance(enzymes, list):
            enzymes = [enzymes]

        # Check each enzyme entry
        for enzyme in enzymes:
            if not isinstance(enzyme, dict):
                continue

            enzyme_name = enzyme.get("value", "Unknown")
            ec_number = enzyme.get("ec", "")
            activity = enzyme.get("activity", "")

            # Check if EC number is missing or empty
            if not ec_number or ec_number.strip() == "":
                # Get strain name from Name and taxonomic classification
                strain_name = "Unknown"
                if "Name and taxonomic classification" in strain_data:
                    tax_class = strain_data["Name and taxonomic classification"]
                    if isinstance(tax_class, list) and len(tax_class) > 0:
                        strain_name = tax_class[0].get("strain designation", "Unknown")

                enzymes_without_ec.append(
                    {
                        "strain_id": strain_id,
                        "strain_name": strain_name,
                        "enzyme_name": enzyme_name,
                        "activity": activity,
                        "full_entry": enzyme,
                    }
                )
                strains_with_missing_ec.add(strain_id)
                enzyme_name_counts[enzyme_name] += 1

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total enzymes without EC IDs: {len(enzymes_without_ec)}")
    print(f"Number of strains affected: {len(strains_with_missing_ec)}")

    # Print top enzyme names without EC IDs
    print("\n" + "=" * 80)
    print("TOP 20 ENZYME NAMES WITHOUT EC IDs (by frequency)")
    print("=" * 80)
    sorted_enzyme_names = sorted(enzyme_name_counts.items(), key=lambda x: x[1], reverse=True)
    for enzyme_name, count in sorted_enzyme_names[:20]:
        print(f"{count:4d} | {enzyme_name}")

    # Print detailed examples (first 10)
    print("\n" + "=" * 80)
    print("EXAMPLES OF ENZYMES WITHOUT EC IDs (first 10)")
    print("=" * 80)
    for i, entry in enumerate(enzymes_without_ec[:10], 1):
        print(f"\n{i}. Strain ID: {entry['strain_id']}")
        print(f"   Strain Name: {entry['strain_name']}")
        print(f"   Enzyme Name: {entry['enzyme_name']}")
        print(f"   Activity: {entry['activity']}")
        print(f"   Full Entry: {entry['full_entry']}")

    # Write full report to file
    report_file = "mappings/bacdive_enzymes_without_ec_report.txt"
    print(f"\n\nWriting full report to {report_file}...")

    with open(report_file, "w") as f:
        f.write("BacDive Enzymes Without EC IDs - Full Report\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total enzymes without EC IDs: {len(enzymes_without_ec)}\n")
        f.write(f"Number of strains affected: {len(strains_with_missing_ec)}\n\n")

        f.write("=" * 80 + "\n")
        f.write("ENZYME NAMES WITHOUT EC IDs (sorted by frequency)\n")
        f.write("=" * 80 + "\n")
        for enzyme_name, count in sorted_enzyme_names:
            f.write(f"{count:4d} | {enzyme_name}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("DETAILED LIST OF ALL ENZYMES WITHOUT EC IDs\n")
        f.write("=" * 80 + "\n\n")

        for i, entry in enumerate(enzymes_without_ec, 1):
            f.write(f"{i}. Strain ID: {entry['strain_id']}\n")
            f.write(f"   Strain Name: {entry['strain_name']}\n")
            f.write(f"   Enzyme Name: {entry['enzyme_name']}\n")
            f.write(f"   Activity: {entry['activity']}\n")
            f.write(f"   Full Entry: {entry['full_entry']}\n\n")

    print(f"Full report written to {report_file}")


if __name__ == "__main__":
    bacdive_file = Path("data/raw/bacdive_strains.json")

    if not bacdive_file.exists():
        print(f"Error: File not found: {bacdive_file}")
        print("Please ensure the BacDive data has been downloaded.")
        exit(1)

    check_enzymes_without_ec(str(bacdive_file))
