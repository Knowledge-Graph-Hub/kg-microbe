"""Sanitize CURIEs and URIs in KGX TSV files."""

import csv
import re
import urllib.parse
from io import StringIO

import click


def robust_fix_uri(val):
    """Fix URIs by properly encoding path components while preserving structure."""
    # Only encode if URI-like (starts with http)
    if val.startswith("http"):
        # Split scheme and netloc from the path
        m = re.match(r'(https?://[^/]+)(/.*)$', val)
        if m:
            base, path = m.groups()
            # Encode everything in the path, including colons, arrows, degrees
            # Keep slashes to preserve URI structure, but encode everything else
            encoded_path = urllib.parse.quote(path, safe="/")
            return base + encoded_path
        else:
            # No path found - might be just domain, return as is
            return val
    return val

def sanitize_id_or_uri(val):
    """Sanitize values that could become URIs, including node IDs."""
    if not val:
        return val

    # If it's already a full URI, use the existing function
    if val.startswith("http"):
        return robust_fix_uri(val)

    # For CURIEs (prefix:suffix format), preserve the first colon
    if ":" in val and not val.startswith("http"):
        parts = val.split(":", 1)  # Split only on first colon
        if len(parts) == 2:
            prefix, suffix = parts
            # Only sanitize the suffix part, keep prefix and first colon intact
            if any(char in suffix for char in ">°<[]{}|\\^`\""):
                sanitized_suffix = urllib.parse.quote(suffix, safe="")
                return f"{prefix}:{sanitized_suffix}"
            return val

    # For non-CURIE values that might become URIs, encode problematic characters
    # but don't encode colons that might be legitimate CURIE separators
    if any(char in val for char in ">°<[]{}|\\^`\""):
        return urllib.parse.quote(val, safe=":")  # Keep colons safe

    return val

def sanitize_row(row):
    """Sanitize a single row of TSV data."""
    # Fields that could become URIs in KGX processing
    uri_fields = {'id', 'subject', 'object', 'predicate', 'relation', 'category'}

    result = {}
    for k, v in row.items():
        # Remove carriage returns from all values
        if v:
            v = v.replace('\r', '')

        if k in uri_fields:
            result[k] = sanitize_id_or_uri(v)
        elif v and v.startswith('http'):
            result[k] = robust_fix_uri(v)
        else:
            result[k] = v
    return result

def sanitize_tsv(input_file, output_file):
    """Sanitize a TSV file by fixing line endings and URI encoding."""
    # First, read the entire file and fix line endings
    with open(input_file, 'rb') as infile:
        content = infile.read()

    # Convert Windows line endings to Unix line endings
    content = content.replace(b'\r\n', b'\n').replace(b'\r', b'\n')

    # Write back and then process normally
    content_str = content.decode('utf-8')
    content_io = StringIO(content_str)

    with open(output_file, 'w', newline='\n') as outfile:
        reader = csv.DictReader(content_io, delimiter='\t')
        writer = csv.DictWriter(
            outfile, fieldnames=reader.fieldnames, delimiter='\t', lineterminator='\n'
        )
        writer.writeheader()
        for row in reader:
            row = sanitize_row(row)
            writer.writerow(row)

@click.command()
@click.option('--nodes', required=True, type=click.Path(exists=True), help="Input nodes TSV file")
@click.option('--edges', required=True, type=click.Path(exists=True), help="Input edges TSV file")
@click.option(
    '--nodes-fixed',
    required=True,
    type=click.Path(),
    help="Output sanitized nodes TSV file (should end with _nodes.tsv)"
)
@click.option(
    '--edges-fixed',
    required=True,
    type=click.Path(),
    help="Output sanitized edges TSV file (should end with _edges.tsv)"
)
def main(nodes, edges, nodes_fixed, edges_fixed):
    """Sanitize (URL-encode) ALL URI content in KGX TSV files for nodes and edges, including interior path segments."""
    click.echo(f"Sanitizing all URIs in {nodes} → {nodes_fixed}")
    sanitize_tsv(nodes, nodes_fixed)
    click.echo(f"Sanitizing all URIs in {edges} → {edges_fixed}")
    sanitize_tsv(edges, edges_fixed)
    click.echo("Done.")

if __name__ == "__main__":
    main()
