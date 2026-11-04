"""
Export immutable KGX TSV records as streaming, lossless N-Triples evidence.

Purpose: replace the eager, identifier-rewriting historical make-nt branch.
Inputs: explicit local node/edge TSVs and a reviewed JSON prefix map.
Output: a new N-Triples file with embedded fingerprint/count manifests.
PR: current extraction of make-nt (df7b405c); date: 2026-10-13.

This is a record serialization, not an unconditional triple projection. Each
edge is reified without asserting its triple, so negation and qualifiers are
not discarded. Original cells, including empty cells, remain literal evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, TextIO
from urllib.parse import quote, urlsplit

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RECORD = "urn:kg-microbe:tsv-record:"
FIELD = "urn:kg-microbe:tsv-field:"


def fingerprint(path: Path) -> str:
    """Hash a regular file with bounded reads; never load a full graph."""
    if not path.is_file():
        raise ValueError(f"Not a regular input file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iri(value: str) -> str:
    """Validate an absolute IRI without modifying its lexical identity."""
    if not value or any(c.isspace() or ord(c) < 33 or c in '<>"{}|^`\\' for c in value):
        raise ValueError(f"Invalid IRI; correct the producing transform: {value!r}")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value) or re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError(f"Invalid IRI escape: {value!r}")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https", "urn"} or (parts.scheme != "urn" and not parts.netloc):
        raise ValueError(f"Expected absolute http(s) or urn IRI: {value!r}")
    if parts.scheme == "urn":
        namespace, separator, local = parts.path.partition(":")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,30}[A-Za-z0-9]", namespace) or not separator or not local:
            raise ValueError(f"Invalid URN: {value!r}")
    return f"<{value}>"


def _unique_object(pairs):
    """Reject ambiguous duplicate prefix declarations, including equal repeats."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate prefix declaration: {key}")
        result[key] = value
    return result


def load_prefixes(path: Path) -> dict[str, str]:
    """Read an explicitly selected local prefix map; never retrieve contexts."""
    with path.open(encoding="utf-8") as stream:
        prefixes = json.load(stream, object_pairs_hook=_unique_object)
    if not isinstance(prefixes, dict):
        raise ValueError("Prefix map must be a JSON object")
    for key, value in prefixes.items():
        if not isinstance(key, str) or not key or ":" in key or any(c.isspace() for c in key):
            raise ValueError(f"Invalid prefix name: {key!r}")
        if key in {"http", "https", "urn"} or not isinstance(value, str):
            raise ValueError(f"Invalid or reserved prefix: {key!r}")
        iri(value + "prefix-validation-sentinel")
    return prefixes


def expand(value: str, prefixes: dict[str, str]) -> str:
    """Expand only declared CURIEs or already absolute IRIs; fail on unknown prefixes."""
    prefix, separator, local = value.partition(":")
    if separator and prefix in prefixes and local:
        return iri(prefixes[prefix] + local)
    if value.startswith(("http://", "https://", "urn:")):
        return iri(value)
    raise ValueError(f"Undeclared prefix or empty identifier: {value!r}")


def literal(value: str) -> str:
    """Escape RDF string syntax without changing the represented Unicode text."""
    escapes = {"\\": "\\\\", '"': '\\"', "\t": "\\t", "\n": "\\n", "\r": "\\r"}
    pieces = []
    for char in value:
        if char in escapes:
            pieces.append(escapes[char])
        elif ord(char) < 32 or ord(char) == 127:
            pieces.append(f"\\u{ord(char):04X}")
        else:
            pieces.append(char)
    return '"' + "".join(pieces) + '"'


def _lines(stream: BinaryIO, digest) -> Iterator[list[str]]:
    """Read literal LF TSV rows, not CSV-style quoted or NA-coerced fields."""
    for number, line in enumerate(stream, 1):
        digest.update(line)
        if not line.endswith(b"\n") or b"\r" in line or b"\x00" in line:
            raise ValueError(f"Line {number}: require LF-terminated TSV without CR/NUL")
        yield line[:-1].decode("utf-8").split("\t")


def write_table(
    path: Path, kind: str, expected_sha: str, prefixes: dict[str, str], output: TextIO, prefix_sha: str
) -> dict:
    """Stream a table into stable, distinct source-row resources; preserve all cells."""
    # Import project column constants locally, keeping --help dependency-free.
    from kg_microbe.transform_utils.constants import ID_COLUMN, OBJECT_COLUMN, PREDICATE_COLUMN, SUBJECT_COLUMN

    digest = hashlib.sha256()
    count = 0
    required = {ID_COLUMN} if kind == "node" else {SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN}
    with path.open("rb") as source:
        rows = _lines(source, digest)
        header = next(rows, [])
        if not header or any(not column for column in header) or len(header) != len(set(header)):
            raise ValueError(f"{path}: missing, blank, or duplicate columns")
        if not required <= set(header):
            raise ValueError(f"{path}: missing identity columns: {sorted(required - set(header))}")
        properties = [iri(FIELD + quote(column, safe="")) for column in header]
        for count, values in enumerate(rows, 1):
            if len(values) != len(header):
                raise ValueError(f"{path}:{count + 1}: inconsistent field count")
            row = dict(zip(header, values, strict=True))
            subject = iri(f"{RECORD}{kind}:{prefix_sha}:{expected_sha}:{count}")
            if kind == "edge":
                output.write(f"{subject} {iri(RDF + 'type')} {iri(RDF + 'Statement')} .\n")
                for column in (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN):
                    output.write(f"{subject} {iri(RDF + column)} {expand(row[column], prefixes)} .\n")
            else:
                output.write(f"{subject} {iri(RDF + 'type')} {iri(RECORD + 'NodeRow')} .\n")
                output.write(f"{subject} {iri(RDF + 'subject')} {expand(row[ID_COLUMN], prefixes)} .\n")
            for predicate, value in zip(properties, values, strict=True):
                output.write(f"{subject} {predicate} {literal(value)} .\n")
    if digest.hexdigest() != expected_sha:
        raise ValueError(f"Input changed during serialization: {path}")
    return {"rows": count, "sha256": expected_sha, "columns": header}


def export_records(nodes: Path, edges: Path, prefix_map: Path, output: Path) -> dict:
    """Publish a new complete N-Triples file atomically, never replacing existing data."""
    paths = [Path(path).resolve(strict=True) for path in (nodes, edges, prefix_map)]
    nodes, edges, prefix_map = paths
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if output.resolve() in paths:
        raise ValueError("Output must not overlap an input")
    before = [fingerprint(path) for path in paths]
    prefixes = load_prefixes(prefix_map)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"format": "kgm-tsv-records-nt-v1", "prefix_map_sha256": before[2], "asserts_edge_triples": False}
    descriptor, temporary_name = tempfile.mkstemp(prefix=".kgm-nt-", suffix=".nt", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            target.write("# " + json.dumps(metadata, sort_keys=True) + "\n")
            metadata["nodes"] = write_table(nodes, "node", before[0], prefixes, target, before[2])
            metadata["edges"] = write_table(edges, "edge", before[1], prefixes, target, before[2])
            if [fingerprint(path) for path in paths] != before:
                raise ValueError("Input or prefix map changed; no output published")
            target.write("# " + json.dumps(metadata, sort_keys=True) + "\n")
            target.flush()
            os.fsync(target.fileno())
        # A same-filesystem hard link is atomic and fails if any destination,
        # including a concurrently created file or symlink, already exists.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return metadata


def main(argv=None) -> None:
    """Run an explicit offline export; never discover or modify merged artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--edges", required=True, type=Path)
    parser.add_argument("--prefix-map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = export_records(args.nodes, args.edges, args.prefix_map, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
