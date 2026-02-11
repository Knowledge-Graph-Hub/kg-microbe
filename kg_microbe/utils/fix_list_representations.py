#!/usr/bin/env python
"""
Fix Python list representations in KGX merged output.

KGX sometimes writes list-valued fields as Python list representations
(e.g., "['infores:chebi', 'infores:chebi']") instead of pipe-delimited strings
(e.g., "infores:chebi|infores:chebi"). This utility converts them to proper format.

Usage:
    python kg_microbe/utils/fix_list_representations.py \
        --input data/merged/merged-kg_edges.tsv \
        --output data/merged/merged-kg_edges_fixed.tsv
"""

import argparse
import ast
from typing import List, Set

# List-valued fields that may have Python list representations
LIST_VALUED_FIELDS = {
    # Provenance fields
    "primary_knowledge_source",
    "aggregator_knowledge_source",
    "knowledge_source",
    "provided_by",
    "supporting_data_source",
    # Node fields
    "synonym",
    "xref",
    "category",
    "in_taxon",
    "same_as",
    # Edge fields
    "publications",
    "has_evidence",
    "qualifiers",
}


def parse_list_representation(value: str) -> List[str]:
    """
    Parse Python list representation to actual list.

    Args:
        value: String that may be a Python list representation

    Returns:
        List of strings if parseable, else [value]

    Example:
        >>> parse_list_representation("['infores:chebi', 'infores:chebi']")
        ['infores:chebi', 'infores:chebi']
        >>> parse_list_representation("infores:chebi")
        ['infores:chebi']

    """
    if not value:
        return []

    # Check if it looks like a Python list representation
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (ValueError, SyntaxError):
            # Not a valid Python list, treat as regular string
            pass

    return [value]


def fix_list_field(value: str, delimiter: str = "|", deduplicate: bool = True) -> str:
    """
    Fix Python list representation to pipe-delimited string.

    Args:
        value: String that may be a Python list representation
        delimiter: Output delimiter (default: pipe)
        deduplicate: Remove duplicates while preserving order (default: True)

    Returns:
        Properly formatted pipe-delimited string

    Example:
        >>> fix_list_field("['infores:chebi', 'infores:chebi']")
        'infores:chebi'
        >>> fix_list_field("['infores:madin_etal', 'infores:bactotraits']")
        'infores:madin_etal|infores:bactotraits'
        >>> fix_list_field("infores:chebi")
        'infores:chebi'

    """
    if not value:
        return value

    # Parse the value to a list
    items = parse_list_representation(value)

    # Deduplicate while preserving order if requested
    if deduplicate:
        seen: Set[str] = set()
        unique_items: List[str] = []
        for item in items:
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                unique_items.append(item)
        items = unique_items

    # Join with delimiter
    return delimiter.join(items)


def fix_tsv(
    input_file: str,
    output_file: str,
    delimiter: str = "\t",
    list_delimiter: str = "|",
    deduplicate: bool = True,
) -> None:
    """
    Fix Python list representations in TSV file.

    Args:
        input_file: Path to input TSV file
        output_file: Path to output fixed TSV file
        delimiter: TSV field delimiter (default: tab)
        list_delimiter: List value delimiter (default: pipe)
        deduplicate: Remove duplicates while preserving order (default: True)

    """
    total_rows = 0
    fixed_fields = 0
    fixed_rows = 0
    list_format_rows = 0

    with open(input_file, 'rb') as infile_bin, open(output_file, "wb") as outfile_bin:
        # Read header line manually preserving exact bytes
        header_bytes = infile_bin.readline()
        header = header_bytes.decode('utf-8').rstrip('\r\n')
        outfile_bin.write((header + '\n').encode('utf-8'))

        # Parse header to find column indices for list-valued fields
        # Note: Some headers may have embedded \r characters
        headers = header.split(delimiter)
        headers = [h.replace('\r', '') for h in headers]
        list_field_indices = {}
        for i, h in enumerate(headers):
            if h in LIST_VALUED_FIELDS:
                list_field_indices[i] = h

        # Process data rows
        for line_bytes in infile_bin:
            total_rows += 1
            line = line_bytes.decode('utf-8').rstrip('\r\n')
            fields = line.split(delimiter)
            row_had_list_format = False
            row_was_fixed = False

            # Check and fix list-valued fields
            for col_idx, _field_name in list_field_indices.items():
                if col_idx < len(fields):
                    value = fields[col_idx]
                    if value and value.startswith("[") and value.endswith("]"):
                        row_had_list_format = True
                        fixed_value = fix_list_field(value, list_delimiter, deduplicate)
                        if fixed_value != value:
                            fields[col_idx] = fixed_value
                            fixed_fields += 1
                            row_was_fixed = True

            if row_had_list_format:
                list_format_rows += 1
            if row_was_fixed:
                fixed_rows += 1

            outfile_bin.write((delimiter.join(fields) + '\n').encode('utf-8'))

    print(f"✓ Processed {total_rows:,} rows")
    print(f"✓ Found {list_format_rows:,} rows with Python list format")
    print(f"✓ Fixed {fixed_fields:,} fields across {fixed_rows:,} rows")
    print(f"✓ Output written to: {output_file}")


def main():
    """Parse command-line arguments and run fixes."""
    parser = argparse.ArgumentParser(
        description="Fix Python list representations in KGX merged output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix edges file
  python kg_microbe/utils/fix_list_representations.py \\
      --input data/merged/merged-kg_edges.tsv \\
      --output data/merged/merged-kg_edges_fixed.tsv

  # Fix nodes file
  python kg_microbe/utils/fix_list_representations.py \\
      --input data/merged/merged-kg_nodes.tsv \\
      --output data/merged/merged-kg_nodes_fixed.tsv

  # Fix without deduplication (keep duplicate values)
  python kg_microbe/utils/fix_list_representations.py \\
      --input data/merged/merged-kg_edges.tsv \\
      --output data/merged/merged-kg_edges_fixed.tsv \\
      --no-deduplicate
        """,
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input TSV file with Python list representations",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output fixed TSV file",
    )
    parser.add_argument(
        "--no-deduplicate",
        action="store_true",
        help="Keep duplicate values (default: remove duplicates)",
    )

    args = parser.parse_args()

    # Run fixes
    fix_tsv(args.input, args.output, deduplicate=not args.no_deduplicate)


if __name__ == "__main__":
    main()
