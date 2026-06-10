#!/usr/bin/env python3
"""Validate RO relation values against the RO ontology."""

import re
import sys
from pathlib import Path
from typing import Set


def extract_ro_terms_from_owl(owl_path: Path) -> Set[str]:
    """
    Extract all RO term IDs from the OWL file.

    Args:
        owl_path: Path to RO ontology OWL file

    Returns:
        Set of valid RO term IDs (e.g., "RO:0000052", "RO:HOM0000017")
    """
    ro_terms = set()

    with open(owl_path) as f:
        content = f.read()

    # Find all RO IDs (format: RO_0000000 or RO_HOM0000000)
    matches = re.findall(r"RO_(HOM)?(\d{7,})", content)
    for match in matches:
        if match[0]:  # HOM prefix
            ro_terms.add(f"RO:HOM{match[1]}")
        else:
            ro_terms.add(f"RO:{match[1]}")

    return ro_terms


def validate_edge_files(transformed_dir: Path, valid_ro_terms: Set[str]) -> dict:
    """
    Validate relation columns in all edge files.

    Args:
        transformed_dir: Path to data/transformed directory
        valid_ro_terms: Set of valid RO term IDs from ontology

    Returns:
        Dictionary mapping source names to lists of issues found
    """
    results = {}

    for edges_file in transformed_dir.glob("*/edges.tsv"):
        source = edges_file.parent.name
        issues = []

        with open(edges_file) as f:
            headers = f.readline().strip().split("\t")
            if "relation" not in headers:
                continue

            relation_idx = headers.index("relation")

            for line_num, line in enumerate(f, start=2):
                fields = line.strip().split("\t")
                if len(fields) <= relation_idx:
                    continue

                relation = fields[relation_idx]

                # Check for numeric-only (missing prefix)
                if re.match(r"^\d+$", relation):
                    issues.append(
                        {
                            "line": line_num,
                            "issue": "numeric_only",
                            "value": relation,
                            "subject": fields[0] if fields else "",
                            "object": fields[2] if len(fields) > 2 else "",
                        }
                    )

                # Check for invalid RO terms
                elif relation.startswith("RO:"):
                    if relation not in valid_ro_terms:
                        issues.append(
                            {
                                "line": line_num,
                                "issue": "invalid_ro_term",
                                "value": relation,
                                "subject": fields[0] if fields else "",
                                "object": fields[2] if len(fields) > 2 else "",
                            }
                        )

        if issues:
            results[source] = issues

    return results


def main():
    """Run validation."""
    # Paths
    ro_owl = Path("data/raw/ro.owl")
    transformed_dir = Path("data/transformed")

    if not ro_owl.exists():
        print("ERROR: RO ontology not found. Run 'poetry run kg download' first.")
        sys.exit(1)

    print("Extracting valid RO terms from ontology...")
    valid_ro_terms = extract_ro_terms_from_owl(ro_owl)
    print(f"Found {len(valid_ro_terms)} valid RO terms")

    if not transformed_dir.exists():
        print("ERROR: Transformed data directory not found.")
        print("Run 'poetry run kg transform' to generate edge files first.")
        sys.exit(1)

    print("\nValidating edge files...")
    issues = validate_edge_files(transformed_dir, valid_ro_terms)

    if not issues:
        print("✅ All relation values are valid!")
        return 0

    print(f"\n❌ Found issues in {len(issues)} transform(s):\n")

    for source, source_issues in issues.items():
        print(f"=== {source} ===")
        numeric_only = [i for i in source_issues if i["issue"] == "numeric_only"]
        invalid_ro = [i for i in source_issues if i["issue"] == "invalid_ro_term"]

        if numeric_only:
            print(f"  Numeric-only relations (missing prefix): {len(numeric_only)}")
            for issue in numeric_only[:3]:
                print(
                    f"    Line {issue['line']}: {issue['subject']} -> {issue['object']} | relation: {issue['value']}"
                )
            if len(numeric_only) > 3:
                print(f"    ... and {len(numeric_only) - 3} more")

        if invalid_ro:
            print(f"  Invalid RO terms: {len(invalid_ro)}")
            for issue in invalid_ro[:3]:
                print(f"    Line {issue['line']}: {issue['value']}")
            if len(invalid_ro) > 3:
                print(f"    ... and {len(invalid_ro) - 3} more")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
