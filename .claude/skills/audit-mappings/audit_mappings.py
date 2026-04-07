#!/usr/bin/env python3
"""Audit KG-Microbe transform code for hardcoded ontology mappings."""

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


class MappingAuditor:
    """Audits transform code for hardcoded ontology mappings."""

    # Regex patterns for detecting CURIEs
    CURIE_PATTERN = re.compile(r'["\']([A-Z]+:[a-z_]+\d*|[A-Z]+:\d+)["\']')
    DICT_ASSIGNMENT = re.compile(r'(\w+)\s*=\s*\{')

    # Ontology prefixes to look for
    ONTOLOGY_PREFIXES = {
        'METPO', 'CHEBI', 'GO', 'EC', 'RO', 'ENVO', 'NCBITaxon',
        'MONDO', 'HP', 'UniProtKB', 'KEGG', 'COG', 'KGM'
    }

    # Paths to exclude from scanning
    EXCLUDE_PATHS = {'__pycache__', '.pytest_cache', 'tests', '.git', '.tox'}

    # Configuration constants that are acceptable (not data mappings)
    ACCEPTABLE_CONSTANTS = {
        'API_BASE_URLS', 'ENDPOINT', 'BASE_URL', 'FILE_PATH',
        'COLUMN', 'HEADER', 'BIOLINK_', 'CATEGORY'
    }

    def __init__(self, root_dir: Path):
        """Initialize auditor with root directory."""
        self.root_dir = root_dir
        self.transform_utils = root_dir / "kg_microbe" / "transform_utils"

    def scan_all_transforms(self, specific_transform: str = None) -> Dict[str, Any]:
        """Scan all or specific transform for hardcoded mappings."""
        results = {
            'report_date': datetime.now().strftime('%Y-%m-%d'),
            'transforms': [],
            'summary': {
                'total_transforms': 0,
                'transforms_with_hardcoded': 0,
                'total_mapping_files': 0,
                'total_mapping_entries': 0
            }
        }

        if not self.transform_utils.exists():
            print(f"Error: Transform utils directory not found: {self.transform_utils}")
            return results

        # Find all transform directories
        transform_dirs = []
        if specific_transform:
            target_dir = self.transform_utils / specific_transform
            if target_dir.is_dir():
                transform_dirs = [target_dir]
            else:
                print(f"Error: Transform not found: {specific_transform}")
                return results
        else:
            transform_dirs = [d for d in self.transform_utils.iterdir()
                            if d.is_dir() and d.name not in self.EXCLUDE_PATHS]

        for transform_dir in sorted(transform_dirs):
            transform_name = transform_dir.name
            transform_data = self._audit_transform(transform_dir, transform_name)

            if transform_data:
                results['transforms'].append(transform_data)
                results['summary']['total_transforms'] += 1

                if transform_data['hardcoded_mappings']:
                    results['summary']['transforms_with_hardcoded'] += 1

                results['summary']['total_mapping_files'] += len(transform_data['mapping_files'])
                results['summary']['total_mapping_entries'] += sum(
                    f['entry_count'] for f in transform_data['mapping_files']
                )

        return results

    def _audit_transform(self, transform_dir: Path, transform_name: str) -> Dict[str, Any]:
        """Audit a single transform directory."""
        transform_data = {
            'name': transform_name,
            'hardcoded_mappings': [],
            'mapping_files': []
        }

        # Scan Python files for hardcoded mappings
        py_files = list(transform_dir.glob("*.py"))
        for py_file in py_files:
            if py_file.name.startswith('test_'):
                continue
            mappings = self._scan_python_file(py_file)
            transform_data['hardcoded_mappings'].extend(mappings)

        # Scan for mapping files
        mapping_files = self._find_mapping_files(transform_dir)
        transform_data['mapping_files'] = mapping_files

        # Calculate data-driven percentage
        total_mappings = sum(m['entry_count'] for m in transform_data['hardcoded_mappings'])
        total_file_mappings = sum(f['entry_count'] for f in transform_data['mapping_files'])

        if total_mappings + total_file_mappings > 0:
            transform_data['data_driven_percentage'] = round(
                100 * total_file_mappings / (total_mappings + total_file_mappings), 2
            )
        else:
            transform_data['data_driven_percentage'] = 100.0

        return transform_data

    def _scan_python_file(self, py_file: Path) -> List[Dict[str, Any]]:
        """Scan Python file for hardcoded CURIE mappings."""
        hardcoded = []

        try:
            content = py_file.read_text()

            # Parse AST to find dictionary assignments
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    # Check if this is a dictionary assignment
                    if (isinstance(node.value, ast.Dict) and
                        len(node.targets) == 1 and
                        isinstance(node.targets[0], ast.Name)):

                        var_name = node.targets[0].id

                        # Skip acceptable configuration constants
                        if any(pattern in var_name.upper() for pattern in self.ACCEPTABLE_CONSTANTS):
                            continue

                        # Count CURIE values in the dict
                        curie_count = self._count_curies_in_dict(node.value, content)

                        if curie_count > 5:  # Threshold for "significant" hardcoded mapping
                            hardcoded.append({
                                'file': py_file.name,
                                'variable': var_name,
                                'line_start': node.lineno,
                                'line_end': node.end_lineno or node.lineno,
                                'entry_count': curie_count,
                                'type': 'dict_assignment'
                            })

        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"Warning: Could not parse {py_file}: {e}")

        return hardcoded

    def _count_curies_in_dict(self, dict_node: ast.Dict, content: str) -> int:
        """Count CURIE values in a dictionary AST node."""
        count = 0

        for value in dict_node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                # Check if it's a CURIE
                if any(prefix in value.value for prefix in self.ONTOLOGY_PREFIXES):
                    count += 1

        return count

    def _find_mapping_files(self, transform_dir: Path) -> List[Dict[str, Any]]:
        """Find and count entries in mapping files."""
        mapping_files = []

        # Check for mappings subdirectory
        mappings_dir = transform_dir / "mappings"
        if mappings_dir.exists():
            # TSV files
            for tsv_file in mappings_dir.glob("*.tsv"):
                entry_count = self._count_tsv_entries(tsv_file)
                mapping_files.append({
                    'file': f"mappings/{tsv_file.name}",
                    'type': 'tsv',
                    'entry_count': entry_count
                })

            # TXT files (like ec2go.txt)
            for txt_file in mappings_dir.glob("*.txt"):
                entry_count = self._count_tsv_entries(txt_file)
                mapping_files.append({
                    'file': f"mappings/{txt_file.name}",
                    'type': 'txt',
                    'entry_count': entry_count
                })

        # JSON mapping files in main directory
        for json_file in transform_dir.glob("*mapping*.json"):
            entry_count = self._count_json_entries(json_file)
            mapping_files.append({
                'file': json_file.name,
                'type': 'json',
                'entry_count': entry_count
            })

        # YAML files
        for yaml_file in transform_dir.glob("*.yaml"):
            if 'mapping' in yaml_file.name or 'curie' in yaml_file.name:
                entry_count = self._count_yaml_entries(yaml_file)
                mapping_files.append({
                    'file': yaml_file.name,
                    'type': 'yaml',
                    'entry_count': entry_count
                })

        return mapping_files

    def _count_tsv_entries(self, tsv_file: Path) -> int:
        """Count entries in TSV file (lines minus header)."""
        try:
            lines = tsv_file.read_text().strip().split('\n')
            # Subtract 1 for header, filter empty lines
            return max(0, len([l for l in lines if l.strip()]) - 1)
        except Exception as e:
            print(f"Warning: Could not read {tsv_file}: {e}")
            return 0

    def _count_json_entries(self, json_file: Path) -> int:
        """Count entries in JSON file."""
        try:
            data = json.loads(json_file.read_text())
            if isinstance(data, dict):
                return len(data)
            elif isinstance(data, list):
                return len(data)
            return 0
        except Exception as e:
            print(f"Warning: Could not read {json_file}: {e}")
            return 0

    def _count_yaml_entries(self, yaml_file: Path) -> int:
        """Count entries in YAML file."""
        try:
            data = yaml.safe_load(yaml_file.read_text())
            if isinstance(data, dict):
                # Count all top-level keys
                total = 0
                for key, value in data.items():
                    if isinstance(value, dict):
                        total += len(value)
                    elif isinstance(value, list):
                        total += len(value)
                    else:
                        total += 1
                return total
            return 0
        except Exception as e:
            print(f"Warning: Could not read {yaml_file}: {e}")
            return 0


def format_text_report(results: Dict[str, Any], verbose: bool = False) -> str:
    """Format audit results as text report."""
    lines = []
    lines.append("=" * 60)
    lines.append("=== Hardcoded Mapping Audit Report ===")
    lines.append("=" * 60)
    lines.append(f"Date: {results['report_date']}\n")

    for transform in results['transforms']:
        lines.append(f"Transform: {transform['name']}")

        # Hardcoded mappings
        if transform['hardcoded_mappings']:
            lines.append(f"  Python hardcoded mappings: {len(transform['hardcoded_mappings'])}")
            for mapping in transform['hardcoded_mappings']:
                line_range = f"{mapping['line_start']}-{mapping['line_end']}" if mapping['line_end'] > mapping['line_start'] else str(mapping['line_start'])
                lines.append(f"    - {mapping['file']}:{line_range} ({mapping['variable']}, {mapping['entry_count']} entries)")
        else:
            lines.append("  Python hardcoded mappings: 0")

        # Mapping files
        if transform['mapping_files']:
            lines.append(f"\n  Mapping files: {len(transform['mapping_files'])}")
            for mfile in sorted(transform['mapping_files'], key=lambda x: x['file']):
                lines.append(f"    - {mfile['file']} ({mfile['entry_count']} entries)")
        else:
            lines.append("\n  Mapping files: 0")

        # Status
        pct = transform['data_driven_percentage']
        status = "✅" if pct >= 95 else "⚠️"
        lines.append(f"\n  Status: {status} {pct}% data-driven\n")

    # Summary
    lines.append("-" * 60)
    lines.append("Summary:")
    lines.append(f"  Total transforms scanned: {results['summary']['total_transforms']}")
    lines.append(f"  Transforms with hardcoded mappings: {results['summary']['transforms_with_hardcoded']}")
    lines.append(f"  Total mapping files: {results['summary']['total_mapping_files']}")
    lines.append(f"  Total mapping entries: {results['summary']['total_mapping_entries']:,}+")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_markdown_report(results: Dict[str, Any], verbose: bool = False) -> str:
    """Format audit results as markdown report."""
    lines = []
    lines.append("# Hardcoded Mapping Audit Report\n")
    lines.append(f"**Date:** {results['report_date']}\n")

    for transform in results['transforms']:
        lines.append(f"## Transform: `{transform['name']}`\n")

        # Hardcoded mappings
        if transform['hardcoded_mappings']:
            lines.append(f"**Python hardcoded mappings:** {len(transform['hardcoded_mappings'])}\n")
            for mapping in transform['hardcoded_mappings']:
                line_range = f"{mapping['line_start']}-{mapping['line_end']}" if mapping['line_end'] > mapping['line_start'] else str(mapping['line_start'])
                lines.append(f"- `{mapping['file']}:{line_range}` (`{mapping['variable']}`, {mapping['entry_count']} entries)")
            lines.append("")
        else:
            lines.append("**Python hardcoded mappings:** 0\n")

        # Mapping files
        if transform['mapping_files']:
            lines.append(f"**Mapping files:** {len(transform['mapping_files'])}\n")
            for mfile in sorted(transform['mapping_files'], key=lambda x: x['file']):
                lines.append(f"- `{mfile['file']}` ({mfile['entry_count']} entries)")
            lines.append("")
        else:
            lines.append("**Mapping files:** 0\n")

        # Status
        pct = transform['data_driven_percentage']
        status = "✅" if pct >= 95 else "⚠️"
        lines.append(f"**Status:** {status} {pct}% data-driven\n")
        lines.append("---\n")

    # Summary
    lines.append("## Summary\n")
    lines.append(f"- **Total transforms scanned:** {results['summary']['total_transforms']}")
    lines.append(f"- **Transforms with hardcoded mappings:** {results['summary']['transforms_with_hardcoded']}")
    lines.append(f"- **Total mapping files:** {results['summary']['total_mapping_files']}")
    lines.append(f"- **Total mapping entries:** {results['summary']['total_mapping_entries']:,}+")

    return "\n".join(lines)


def main():
    """Main entry point for audit script."""
    parser = argparse.ArgumentParser(
        description="Audit KG-Microbe transform code for hardcoded ontology mappings"
    )
    parser.add_argument(
        '--transform',
        type=str,
        help='Audit specific transform (default: all)'
    )
    parser.add_argument(
        '--format',
        choices=['text', 'json', 'md'],
        default='text',
        help='Output format (default: text)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Include code snippets and line numbers'
    )
    parser.add_argument(
        '--mapping-files-only',
        action='store_true',
        help='Only scan mapping files, skip Python code'
    )

    args = parser.parse_args()

    # Use current working directory as repository root
    root_dir = Path.cwd()

    # Create auditor and run scan
    auditor = MappingAuditor(root_dir)
    results = auditor.scan_all_transforms(specific_transform=args.transform)

    # Filter results if only mapping files requested
    if args.mapping_files_only:
        for transform in results['transforms']:
            transform['hardcoded_mappings'] = []
            transform['data_driven_percentage'] = 100.0

    # Format and output results
    if args.format == 'json':
        print(json.dumps(results, indent=2))
    elif args.format == 'md':
        print(format_markdown_report(results, verbose=args.verbose))
    else:
        print(format_text_report(results, verbose=args.verbose))


if __name__ == '__main__':
    main()
