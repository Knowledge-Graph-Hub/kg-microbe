"""
Audit an explicitly selected local CMM export without admitting or rewriting graph claims.

Purpose: retain original TSV bytes and report bounded schema/provenance/model-review gaps.
Inputs: explicit --nodes and --edges UTF-8 literal TSV files; no remote or ambient data.
Outputs: a fresh --output directory with source copies, findings.jsonl, and manifest.json.
Date: 2026-10-13. This is an intake report, not a canonical producer or release gate.
"""

import argparse
import hashlib
import json
import os
import re
import runpy
import sqlite3
import stat
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Load only the stdlib-only constants file, not kg_microbe.__init__ (which loads
# downloader dependencies). A plain Python interpreter can run this local audit.
CONSTANTS_PATH = Path(__file__).resolve().parents[2] / "kg_microbe/transform_utils/constants.py"
C = runpy.run_path(str(CONSTANTS_PATH))
NODE_COLUMNS = tuple(
    C[name]
    for name in (
        "ID_COLUMN",
        "CATEGORY_COLUMN",
        "NAME_COLUMN",
        "DESCRIPTION_COLUMN",
        "XREF_COLUMN",
        "PROVIDED_BY_COLUMN",
        "SYNONYM_COLUMN",
        "DEPRECATED_COLUMN",
        "SAME_AS_COLUMN",
    )
)
EDGE_COLUMNS = tuple(
    C[name]
    for name in (
        "SUBJECT_COLUMN",
        "PREDICATE_COLUMN",
        "OBJECT_COLUMN",
        "RELATION_COLUMN",
        "PRIMARY_KNOWLEDGE_SOURCE_COLUMN",
        "KNOWLEDGE_LEVEL_COLUMN",
        "AGENT_TYPE_COLUMN",
    )
)
NODE_REQUIRED = frozenset(
    C[name]
    for name in (
        "ID_COLUMN",
        "CATEGORY_COLUMN",
        "NAME_COLUMN",
        "DESCRIPTION_COLUMN",
        "PROVIDED_BY_COLUMN",
    )
)
ID, CATEGORY, NAME, PROVIDED_BY = (
    C[name]
    for name in (
        "ID_COLUMN",
        "CATEGORY_COLUMN",
        "NAME_COLUMN",
        "PROVIDED_BY_COLUMN",
    )
)
SUBJECT, PREDICATE, OBJECT, RELATION, PRIMARY, KNOWLEDGE, AGENT = EDGE_COLUMNS
KNOWLEDGE_VALUES = frozenset(
    C[name]
    for name in (
        "KNOWLEDGE_ASSERTION",
        "LOGICAL_ENTAILMENT",
        "PREDICTION",
        "STATISTICAL_ASSOCIATION",
        "OBSERVATION",
        "KNOWLEDGE_LEVEL_NOT_PROVIDED",
    )
)
AGENT_VALUES = frozenset(
    C[name]
    for name in (
        "MANUAL_AGENT",
        "AUTOMATED_AGENT",
        "DATA_ANALYSIS_PIPELINE",
        "COMPUTATIONAL_MODEL",
        "TEXT_MINING_AGENT",
        "IMAGE_PROCESSING_AGENT",
        "MANUAL_VALIDATION_OF_AUTOMATED_AGENT",
        "AGENT_TYPE_NOT_PROVIDED",
    )
)
CURIE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*:[^\s|:][^\s|]*\Z")
LEGACY_NAMESPACES = frozenset(
    {
        "strain",
        "kgmicrobe.genome",
        "kgmicrobe.taxon",
        "kgmicrobe.protein",
        "kgmicrobe.medium",
        "kgmicrobe.chemical",
        "kgmicrobe.ingredient",
        "kgmicrobe.pathway",
        "KEGG",
    }
)
CATEGORY_REVIEW = frozenset(
    {
        "biolink:Enzyme",
        "biolink:Genome",
        "biolink:ChemicalSubstance",
        "biolink:OntologyClass",
        "biolink:NamedThing",
    }
)
PROFILE = "cmm-explicit-local-intake-v1"


def _stamp(path):
    """Require a regular, non-symlink file and retain a concurrent-change sentinel."""
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"Input is not a regular non-symlink file: {path}")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _fingerprint(path, destination=None):
    """Stream complete input bytes, optionally retaining an exclusive unchanged copy."""
    before = _stamp(path)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as reader:
        opened = os.fstat(reader.fileno())
        if (opened.st_dev, opened.st_ino) != before[:2]:
            raise ValueError(f"Input changed before reading: {path}")
        writer = destination.open("xb") if destination is not None else None
        try:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                if writer is not None:
                    writer.write(block)
            if writer is not None:
                writer.flush()
                os.fsync(writer.fileno())
        finally:
            if writer is not None:
                writer.close()
    if _stamp(path) != before:
        raise ValueError(f"Input changed while reading: {path}")
    return {"sha256": digest.hexdigest(), "bytes": size}, before


class Findings:
    """Write every row-linked finding while holding only aggregate counters in memory."""

    def __init__(self, stream):
        """Initialize a JSONL sink and finite finding counters."""
        self.stream = stream
        self.counts = Counter()

    def add(self, code, table, line, field, value):
        """Retain the original value; never substitute a proposed correction."""
        record = {"code": code, "table": table, "line": line, "field": field, "value": value}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.counts[code] += 1


def _records(path, table, findings):
    """Read literal TSV records, rejecting malformed structure without interpreting quotes."""
    with path.open(encoding="utf-8", newline="") as stream:
        for line, text in enumerate(stream, 1):
            if "\x00" in text:
                raise ValueError(f"{table}:{line}: NUL byte in TSV record")
            if "\r" in text or not text.endswith("\n"):
                findings.add("noncanonical_line_ending", table, line, "", repr(text[-2:]))
            values = text.removesuffix("\n").removesuffix("\r").split("\t")
            yield line, values


def _identifier(value, table, line, field, findings):
    """Flag malformed, IRI, and selected legacy identifiers without asserting replacements."""
    if value.startswith(("http://", "https://")):
        findings.add("full_iri_requires_review", table, line, field, value)
    elif not CURIE.fullmatch(value):
        findings.add("non_curie_identifier", table, line, field, value)
    elif value.split(":", 1)[0] in LEGACY_NAMESPACES:
        findings.add("legacy_namespace_requires_review", table, line, field, value)


def _check_node(row, line, findings, database):
    """Inspect node declarations, retaining repeated and contradictory declarations alike."""
    identifier = row[ID]
    previous = database.execute("SELECT first_line FROM nodes WHERE id = ?", (identifier,)).fetchone()
    if previous is not None:
        findings.add("duplicate_node_id", "nodes", line, ID, identifier)
    else:
        database.execute("INSERT INTO nodes VALUES (?, ?)", (identifier, line))
    _identifier(identifier, "nodes", line, ID, findings)
    for field in (CATEGORY, NAME, PROVIDED_BY):
        if field in row and not row[field].strip():
            findings.add("blank_node_value", "nodes", line, field, row[field])
    if row.get(PROVIDED_BY) == "Graph":
        findings.add("generic_node_provenance", "nodes", line, PROVIDED_BY, row[PROVIDED_BY])
    for category in row.get(CATEGORY, "").split("|") if row.get(CATEGORY) else ():
        if category in CATEGORY_REVIEW or not category.startswith("biolink:") or not CURIE.fullmatch(category):
            findings.add("category_requires_review", "nodes", line, CATEGORY, category)


def _check_edge(row, line, findings, database):
    """Inspect closure and finite provenance syntax without claiming scientific validation."""
    for field in (SUBJECT, OBJECT):
        value = row[field]
        _identifier(value, "edges", line, field, findings)
        if database.execute("SELECT 1 FROM nodes WHERE id = ?", (value,)).fetchone() is None:
            findings.add("endpoint_not_declared_in_supplied_nodes", "edges", line, field, value)
    if row[SUBJECT] == row[OBJECT]:
        findings.add("self_loop_requires_review", "edges", line, PREDICATE, row[PREDICATE])
    for field in (PREDICATE, RELATION):
        if row.get(field):
            _identifier(row[field], "edges", line, field, findings)
    if not row[PREDICATE].startswith("biolink:"):
        findings.add("native_predicate_requires_authority_review", "edges", line, PREDICATE, row[PREDICATE])
    for field in (RELATION, PRIMARY, KNOWLEDGE, AGENT):
        if field in row and not row[field].strip():
            findings.add("blank_edge_value", "edges", line, field, row[field])
    if row.get(PRIMARY) and not re.fullmatch(r"infores:[A-Za-z0-9][A-Za-z0-9._-]*", row[PRIMARY]):
        findings.add("non_scalar_infores_provenance", "edges", line, PRIMARY, row[PRIMARY])
    for field, vocabulary in ((KNOWLEDGE, KNOWLEDGE_VALUES), (AGENT, AGENT_VALUES)):
        if row.get(field) and row[field] not in vocabulary:
            findings.add("unrecognized_provenance_value", "edges", line, field, row[field])
    encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if database.execute("SELECT 1 FROM edges WHERE digest = ?", (digest,)).fetchone():
        findings.add("duplicate_edge_row_preserved", "edges", line, "", digest)
    else:
        database.execute("INSERT INTO edges VALUES (?)", (digest,))


def _count(database, table, kind, value):
    """Aggregate source-controlled labels on disk, not in unbounded in-memory counters."""
    database.execute(
        "INSERT INTO value_counts VALUES (?, ?, ?, 1) "
        "ON CONFLICT(table_name, kind, value) DO UPDATE SET row_count = row_count + 1",
        (table, kind, value),
    )


def _scan(path, table, findings, database):
    """Check one table with an on-disk identity index, never loading graph rows as a frame."""
    records = _records(path, table, findings)
    try:
        _, header = next(records)
    except StopIteration:
        raise ValueError(f"{table}: missing TSV header") from None
    if any(not column or column != column.strip() for column in header) or len(set(header)) != len(header):
        raise ValueError(f"{table}: blank, whitespace-padded, or duplicate header")
    identity = (ID,) if table == "nodes" else (SUBJECT, PREDICATE, OBJECT)
    if not set(identity).issubset(header):
        raise ValueError(f"{table}: missing identity columns: {sorted(set(identity) - set(header))}")
    canonical = NODE_COLUMNS if table == "nodes" else EDGE_COLUMNS
    required = NODE_REQUIRED if table == "nodes" else frozenset(EDGE_COLUMNS)
    missing = sorted(required - set(header))
    for field in missing:
        findings.add("missing_required_column", table, 1, field, None)
    expected = [column for column in canonical if column in set(header) | required]
    expected.extend(sorted(set(header) - set(canonical)))
    if header != expected:
        findings.add("noncanonical_header", table, 1, "", header)
    if table == "edges":
        for field in (ID, "key", "knowledge_source"):
            if field in header:
                findings.add("legacy_internal_edge_column", table, 1, field, field)
    counts = 0
    for line, values in records:
        if len(values) != len(header):
            raise ValueError(f"{table}:{line}: expected {len(header)} fields; found {len(values)}")
        row = dict(zip(header, values, strict=True))
        if any(not row[field].strip() for field in identity):
            raise ValueError(f"{table}:{line}: empty graph identity")
        if table == "nodes":
            _check_node(row, line, findings, database)
            _count(database, table, "node_prefix", row[ID].split(":", 1)[0])
        else:
            _check_edge(row, line, findings, database)
            _count(database, table, "predicate", row[PREDICATE])
        counts += 1
    if not counts:
        findings.add("empty_table_requires_review", table, 1, "", 0)
    database.commit()
    return {
        "rows": counts,
        "header": header,
        "missing_required_columns": missing,
        "missing_optional_columns": sorted(set(canonical) - required - set(header)),
        "distinct_node_prefixes": database.execute(
            "SELECT COUNT(*) FROM value_counts WHERE table_name = ? AND kind = 'node_prefix'", (table,)
        ).fetchone()[0],
        "distinct_predicates": database.execute(
            "SELECT COUNT(*) FROM value_counts WHERE table_name = ? AND kind = 'predicate'", (table,)
        ).fetchone()[0],
    }


def _publish(staging, destination):
    """Reserve a new directory exclusively, then publish the complete bundle in one rename."""
    destination.mkdir()  # No exist_ok: an existing empty directory also belongs to somebody else.
    reserved = destination.lstat()

    def owned():
        """Recognize only our empty directory reservation."""
        current = destination.lstat()
        return (current.st_dev, current.st_ino, current.st_mode) == (
            reserved.st_dev,
            reserved.st_ino,
            reserved.st_mode,
        )

    try:
        if not owned() or any(destination.iterdir()):
            raise ValueError("Output reservation changed; refusing to replace it")
        os.replace(staging, destination)
    except BaseException:
        if destination.exists() and owned():
            try:
                destination.rmdir()  # Only our still-empty reservation; never remove another writer's files.
            except OSError:
                pass
        raise


def audit(nodes, edges, output):
    """Publish an explicit-local intake bundle or fail without changing inputs/existing outputs."""
    sources = {"nodes": Path(nodes).absolute(), "edges": Path(edges).absolute()}
    destination = Path(output).absolute()
    for path in sources.values():
        _stamp(path)
    if os.path.samefile(sources["nodes"], sources["edges"]):
        raise ValueError("Node and edge inputs must be distinct files")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Output already exists: {destination}")
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if any(destination == path.resolve() or destination in path.resolve().parents for path in sources.values()):
        raise ValueError("Output overlaps an input")
    tool_paths = {"audit_script": Path(__file__).resolve(), "column_constants": CONSTANTS_PATH}
    tool_pins = {role: _fingerprint(path)[0] for role, path in tool_paths.items()}
    with tempfile.TemporaryDirectory(prefix=".cmm-intake-", dir=parent) as temporary:
        workspace = Path(temporary)
        bundle = workspace / "bundle"
        bundle.mkdir()
        pins = {}
        for role, source in sources.items():
            pin, sentinel = _fingerprint(source, bundle / f"original_{role}.tsv")
            pins[role] = {"path": str(source), **pin, "sentinel": sentinel}
        database = sqlite3.connect(workspace / "identities.sqlite")
        try:
            database.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, first_line INTEGER NOT NULL)")
            database.execute("CREATE TABLE edges (digest TEXT PRIMARY KEY)")
            database.execute(
                "CREATE TABLE value_counts (table_name TEXT, kind TEXT, value TEXT, row_count INTEGER NOT NULL, "
                "PRIMARY KEY(table_name, kind, value)) WITHOUT ROWID"
            )
            with (bundle / "findings.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
                findings = Findings(stream)
                tables = {
                    role: _scan(bundle / f"original_{role}.tsv", role, findings, database)
                    for role in ("nodes", "edges")
                }
            with (bundle / "counts.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
                for table, kind, value, count in database.execute(
                    "SELECT table_name, kind, value, row_count FROM value_counts ORDER BY table_name, kind, value"
                ):
                    stream.write(json.dumps({"table": table, "kind": kind, "value": value, "rows": count}) + "\n")
        finally:
            database.close()
        for role, source in sources.items():
            current, sentinel = _fingerprint(source)
            expected = {key: pins[role][key] for key in ("sha256", "bytes")}
            if current != expected or sentinel != pins[role].pop("sentinel"):
                raise ValueError(f"Input changed during audit: {source}")
            if _fingerprint(bundle / f"original_{role}.tsv")[0] != expected:
                raise ValueError(f"Retained input changed during audit: {role}")
        if any(_fingerprint(path)[0] != tool_pins[role] for role, path in tool_paths.items()):
            raise ValueError("Audit implementation changed during execution")
        result = {
            "profile": PROFILE,
            "status": "INTAKE_AUDIT_ONLY_NOT_ADMITTED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "inputs": pins,
            "tools": tool_pins,
            "output_directory": str(destination),
            "tables": tables,
            "finding_counts": dict(sorted(findings.counts.items())),
            "artifacts": {
                name: _fingerprint(bundle / name)[0]
                for name in (
                    "original_nodes.tsv",
                    "original_edges.tsv",
                    "findings.jsonl",
                    "counts.jsonl",
                )
            },
            "original_bytes_preserved": True,
            "source_inputs_unchanged": True,
            "source_activated": False,
            "canonical_admission": False,
            "release_ready": False,
            "limitations": [
                "No input authority, upstream release, license, or scientific identity is established by a checksum.",
                "No pinned Biolink/ontology, domain/range, native predicate, infores registration, or path validation.",
                "Namespace/category flags are finite review prompts, not exhaustive invalidity or identity rules.",
                "Closure is relative only to the supplied node table; external authoritative declarations may exist.",
                "No claims, duplicates, categories, identifiers, or missing provenance values were edited or inferred.",
                "No canonical transform, merge configuration, source finalization, or production output was changed.",
            ],
        }
        with (bundle / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        _publish(bundle, destination)
    return result


def main(argv=None):
    """Run the reporting-only command; structural failures exit nonzero without publishing."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory beneath an existing parent")
    args = parser.parse_args(argv)
    try:
        result = audit(args.nodes, args.edges, args.output)
    except (OSError, ValueError, UnicodeError, sqlite3.Error) as error:
        parser.exit(2, f"CMM intake failed: {error}\n")
    print(json.dumps({"status": result["status"], "output_directory": result["output_directory"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
