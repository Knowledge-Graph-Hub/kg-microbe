"""Explicit, audited source normalization before source fingerprints and KGX merge (#1082)."""

import csv
import hashlib
import inspect
import json
import os
import shutil
import tempfile
from collections import Counter
from contextlib import ExitStack, contextmanager
from copy import copy
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import canonical_node_category, compact_identifier
from kg_microbe.utils.transform_fingerprint import (
    SHARED_DATA_INPUTS,
    code_fingerprint,
    resolve_data_input,
    shared_code_fingerprint,
)
from kg_microbe.utils.tsv_io import tsv_dict_writer

FINALIZATION_FILE = "source_finalization.json"
FINALIZATION_VERSION = 1
_TEXT_COLUMNS = {NAME_COLUMN, DESCRIPTION_COLUMN}
_AUDIT_COLUMNS = ["file", "line", "original_row_json", "normalized_row_json"]


class SourceFinalizationRequired(ValueError):
    """A graph contains noncanonical source data which merge must not repair."""


def graph_rows(path, *, quoting=csv.QUOTE_NONE):
    """Read the explicitly selected TSV dialect, preserving literal KGX quotes."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=quoting)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise SourceFinalizationRequired(f"{path}: missing or duplicate TSV header")
        for line, row in enumerate(reader, 2):
            if None in row or None in row.values():
                raise SourceFinalizationRequired(f"{path}:{line}: malformed TSV field count")
            yield row


def _writer(stream, header):
    """Write literal KGX fields; controls must already have an explicit representation."""
    return tsv_dict_writer(stream, fieldnames=header, quoting=csv.QUOTE_NONE, quotechar=None)


def _sha256(path):
    """Hash authority bytes with bounded memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identifier(identifier):
    """Reject known noncanonical representations without guessing unknown URI identities."""
    if compact_identifier(identifier) != identifier:
        raise SourceFinalizationRequired(f"Noncanonical identifier {identifier!r}; rerun source finalization")


def validate_node_representation(identifier, category):
    """Enforce representation invariants without loading raw ontology authorities at merge."""
    validate_identifier(identifier)
    categories = set(category.split("|")) if isinstance(category, str) else set(category or ())
    if identifier.startswith(("FOODON:", "PATO:")) and "biolink:OntologyClass" in categories:
        raise SourceFinalizationRequired(f"Unfinalized imported category for {identifier}: {category}")


def validate_graph_bundle(node_paths, edge_paths, *, require_closure=False):
    """Check already finalized records; never remap identities, categories or assertions."""
    nodes, counts = set(), Counter()
    for path in node_paths:
        for row in graph_rows(path):
            validate_node_representation(row[ID_COLUMN], row.get(CATEGORY_COLUMN, ""))
            if require_closure and row[ID_COLUMN].startswith(
                ("NCBITaxon:", "GO:", "CHEBI:", "MICRO:", "OBI:", "gold:")
            ):
                if not row.get(NAME_COLUMN) and row.get(CATEGORY_COLUMN, "") in ("", "biolink:NamedThing"):
                    raise SourceFinalizationRequired(f"{path}: unresolved authoritative endpoint {row[ID_COLUMN]}")
            nodes.add(row[ID_COLUMN])
            counts["nodes"] += 1
    for path in edge_paths:
        for row in graph_rows(path):
            for column in (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN):
                validate_identifier(row[column])
            relation = row.get(RELATION_COLUMN, "")
            if "|" in relation:
                raise SourceFinalizationRequired(f"{path}: non-scalar relation {relation!r}")
            validate_identifier(relation)
            if require_closure:
                for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
                    if row[column] not in nodes:
                        raise SourceFinalizationRequired(f"{path}: undeclared endpoint {row[column]}")
            counts["edges"] += 1
    return dict(counts)


def _stage_representation(source, destination, is_node, quoting, foodon_path, audit, used_inputs):
    """Normalize producer syntax explicitly, retaining every changed source row in an audit."""
    with source.open(encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream, delimiter="\t", quoting=quoting))
    if is_node:
        header = list(dict.fromkeys([*header, NAME_COLUMN, CATEGORY_COLUMN, PROVIDED_BY_COLUMN, DESCRIPTION_COLUMN]))
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = _writer(stream, header)
        writer.writeheader()
        for line, original in enumerate(graph_rows(source, quoting=quoting), 2):
            row = {column: original.get(column, "") for column in header}
            columns = (ID_COLUMN,) if is_node else (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN)
            for column in columns:
                row[column] = compact_identifier(row[column])
            if is_node:
                identifier = row[ID_COLUMN]
                if identifier.startswith("FOODON:") or identifier in {"COB:0000022", "PO:0000003", "OBO:COB_0000022"}:
                    if not foodon_path.is_file():
                        raise FileNotFoundError(f"Required FOODON category authority is missing: {foodon_path}")
                    used_inputs.add(foodon_path)
                row[CATEGORY_COLUMN] = canonical_node_category(
                    identifier, row[CATEGORY_COLUMN], foodon_path=foodon_path
                )
            elif RELATION_COLUMN in row:
                relations = {compact_identifier(value) for value in row[RELATION_COLUMN].split("|") if value}
                if len(relations) > 1:
                    raise SourceFinalizationRequired(
                        f"{source}:{line}: ambiguous source relation {row[RELATION_COLUMN]!r}"
                    )
                row[RELATION_COLUMN] = next(iter(relations), "")
            for column, value in row.items():
                if any(control in value for control in "\t\r\n"):
                    if column not in _TEXT_COLUMNS:
                        raise SourceFinalizationRequired(f"{source}:{line}: {column} has unencoded control characters")
                    row[column] = " ".join(value.split())
            if any(row.get(column, "") != value for column, value in original.items()):
                audit.writerow(
                    {
                        "file": source.name,
                        "line": line,
                        "original_row_json": json.dumps(original, sort_keys=True),
                        "normalized_row_json": json.dumps(row, sort_keys=True),
                    }
                )
            writer.writerow(row)


def _dependency_declarations(transform, used_inputs):
    """Recognize explicit ontology declarations; a cross-source reference is not an anonymous stub."""
    ontology_dir = Path(transform.output_base_dir) / "ontologies"
    if ontology_dir.resolve() == Path(transform.output_dir).resolve():
        return set()
    found = set()
    quoting = csv.QUOTE_NONE if (ontology_dir / FINALIZATION_FILE).is_file() else csv.QUOTE_MINIMAL
    for path in sorted(ontology_dir.glob("*nodes.tsv")):
        used_inputs.add(path)
        for row in graph_rows(path, quoting=quoting):
            if row.get(NAME_COLUMN):
                found.add(row[ID_COLUMN])
    return found


def _repeat_finalization(transform, file_prefix):
    """Reuse exact already-finalized bytes without overwriting the original disposition evidence."""
    output_dir = Path(transform.output_dir)
    report_path = output_dir / f"{file_prefix}{FINALIZATION_FILE}"
    if not report_path.is_file():
        return None
    with report_path.open(encoding="utf-8") as stream:
        report = json.load(stream)
    if report.get("version") != FINALIZATION_VERSION:
        return None
    if report.get("raw_input_directory") != str(Path(transform.input_base_dir).resolve()):
        raise SourceFinalizationRequired(
            "Selected raw input directory changed; rerun the producer and finalize(fresh_run=True)"
        )
    for name, expected in report.get("members", {}).items():
        path = output_dir / name
        if not path.is_file() or {"bytes": path.stat().st_size, "sha256": _sha256(path)} != expected:
            return None
    if not report.get("members"):
        return None
    verify_finalized_source_files([output_dir / name for name in report["members"]])
    transform.finalization_inputs = tuple(item["path"] for item in report.get("inputs", []))
    return report


def _publish_finalization(transform, prepared):
    """Publish one validated staging area, with its exact-byte completion record last."""
    staging, report_path, used_inputs, report = prepared
    for path in sorted(staging.iterdir(), key=lambda path: (path == report_path, path.name)):
        os.replace(path, Path(transform.output_dir) / path.name)
    transform.finalization_inputs = tuple(str(path.resolve()) for path in sorted(used_inputs))
    return report


def finalize_source(transform, *, file_prefix="", fresh_run=False):
    """Finalize an explicit source bundle, preserving prior audit evidence on exact repeat calls."""
    if not fresh_run:
        previous = _repeat_finalization(transform, file_prefix)
        if previous is not None:
            return previous
    with _stage_source(transform, file_prefix=file_prefix, inherit_audit=not fresh_run) as prepared:
        return _publish_finalization(transform, prepared)


def finalize_selected_sources(transform, output_dirs, *, fresh_run=False):
    """Validate all explicitly selected dataset bundles before publishing any finalizer changes."""
    selected = [Path(path) for path in output_dirs]
    if not selected or len(selected) != len(set(selected)):
        raise SourceFinalizationRequired("Dataset finalization requires a nonempty, distinct output selection")
    reports, pending, used = {}, [], set()
    with ExitStack() as stack:
        for output_dir in selected:
            view = copy(transform)
            view.output_dir = output_dir
            previous = None if fresh_run else _repeat_finalization(view, "")
            if previous is not None:
                reports[str(output_dir)] = previous
                used.update(view.finalization_inputs)
            else:
                pending.append((view, stack.enter_context(_stage_source(view, inherit_audit=not fresh_run))))
        for view, prepared in pending:
            reports[str(view.output_dir)] = _publish_finalization(view, prepared)
            used.update(view.finalization_inputs)
    transform.finalization_inputs = tuple(sorted(used))
    return {"datasets": reports}


@contextmanager
def _stage_source(transform, *, file_prefix="", inherit_audit=False):
    """
    Stage and validate a produced source bundle, then publish it before its success marker.

    Producer ``run`` output may already be visible. This hook provides an
    all-validation-before-publication boundary for its own changes, not a
    cross-file filesystem transaction or rollback of the producer's writes.
    No ontology adapter is opened inside producer workers.
    """
    output_dir, raw_dir = Path(transform.output_dir), Path(transform.input_base_dir)
    node_paths = sorted(output_dir.glob(f"{file_prefix or '*'}nodes.tsv"))
    edge_paths = sorted(output_dir.glob(f"{file_prefix or '*'}edges.tsv"))
    if not node_paths or not edge_paths:
        raise SourceFinalizationRequired(f"{output_dir}: source finalization requires node and edge TSV files")
    repo_root = Path(__file__).resolve().parents[2]
    used_inputs = {
        resolve_data_input(repo_root, declaration, raw_dir)
        for declaration in (*getattr(type(transform), "DATA_INPUTS", ()), *SHARED_DATA_INPUTS)
    }
    with tempfile.TemporaryDirectory(prefix=".finalize-", dir=output_dir) as temporary:
        staging = Path(temporary)
        staged_nodes = [staging / path.name for path in node_paths]
        staged_edges = [staging / path.name for path in edge_paths]
        audit_path = staging / f"{file_prefix}source_canonicalization.tsv"
        with audit_path.open("w", encoding="utf-8", newline="") as stream:
            audit = tsv_dict_writer(stream, fieldnames=_AUDIT_COLUMNS)
            audit.writeheader()
            for sources, destinations, is_node in ((node_paths, staged_nodes, True), (edge_paths, staged_edges, False)):
                for source, destination in zip(sources, destinations, strict=True):
                    _stage_representation(
                        source,
                        destination,
                        is_node,
                        getattr(transform, "TSV_QUOTING", csv.QUOTE_MINIMAL),
                        raw_dir / "foodon.json",
                        audit,
                        used_inputs,
                    )
        go_present = any(row[ID_COLUMN].startswith("GO:") for path in staged_nodes for row in graph_rows(path))
        if not go_present:
            go_present = any(
                row[column].startswith("GO:")
                for path in staged_edges
                for row in graph_rows(path)
                for column in (SUBJECT_COLUMN, OBJECT_COLUMN)
            )
        from kg_microbe.utils.go_authority import load_go_authority, normalize_go_bundle

        summaries = {}
        authority = None
        if go_present:
            authority = load_go_authority(raw_dir)
            used_inputs.add(Path(authority.authority_path))
            used_inputs.update(Path(path) for path in authority.source_paths)
        go_report = staging / f"{file_prefix}go_reference_resolution.tsv"
        prior_go_report = output_dir / go_report.name
        if inherit_audit and prior_go_report.is_file():
            shutil.copyfile(prior_go_report, go_report)
        from kg_microbe.merge_utils.external_node_closure import resolve_external_reference_bundle

        external_report = staging / f"{file_prefix}source_reference_resolution.tsv"
        known_declarations = _dependency_declarations(transform, used_inputs)
        summaries["external"] = resolve_external_reference_bundle(
            staged_nodes,
            staged_edges,
            raw_dir,
            external_report,
            discover_references=True,
            include_go=False,
            strict=True,
            quoting=csv.QUOTE_NONE,
            known_declarations=known_declarations,
            consumed_authorities=used_inputs,
        )
        for row in graph_rows(external_report, quoting=csv.QUOTE_MINIMAL):
            if row["authority"]:
                used_inputs.add(raw_dir / row["authority"])
        # GO's audit checkpoints describe the final bundle, not intermediate
        # bytes which external declaration/enrichment subsequently changes.
        summaries["go"] = normalize_go_bundle(staged_nodes, staged_edges, authority, go_report)
        summaries["rows"] = validate_graph_bundle(staged_nodes, staged_edges)
        report = {
            "version": FINALIZATION_VERSION,
            "source": transform.source_name,
            "raw_input_directory": str(raw_dir.resolve()),
            "tsv_quoting": "none",
            "summaries": summaries,
            "finalizer_code": shared_code_fingerprint(repo_root),
            "members": {
                path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
                for path in [*staged_nodes, *staged_edges]
            },
            "audit_members": {
                path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
                for path in (audit_path, external_report, go_report)
            },
            "inputs": [{"path": str(path.resolve()), "sha256": _sha256(path)} for path in sorted(used_inputs)],
        }
        try:
            producer_file = inspect.getsourcefile(type(transform))
        except TypeError:
            producer_file = None
        if producer_file and Path(producer_file).is_relative_to(repo_root / "kg_microbe" / "transform_utils"):
            code_dir = Path(producer_file).resolve().parent
            # Base Transform and fixture objects do not identify a producer
            # package; never recurse through stdlib or a whole checkout while
            # trying to infer their code provenance.
            if code_dir != repo_root / "kg_microbe" / "transform_utils":
                report["producer_code"] = {
                    "directory": str(code_dir),
                    "fingerprint": code_fingerprint(code_dir, repo_root),
                }
        report_path = staging / f"{file_prefix}{FINALIZATION_FILE}"
        with report_path.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
        yield staging, report_path, used_inputs, report


def verify_finalized_source_files(paths):
    """Require exact prepared graph bytes and unchanged authority inputs before public merge."""
    records, authority_hashes, record_errors = {}, {}, {}
    repo_root = Path(__file__).resolve().parents[2]
    current_finalizer = shared_code_fingerprint(repo_root)
    for filename in paths:
        path = Path(filename)
        if not path.is_file():
            raise SourceFinalizationRequired(f"Missing configured graph input: {path}")
        directory = path.parent
        if directory not in records:
            records[directory] = []
            for report_path in sorted(directory.glob(f"*{FINALIZATION_FILE}")):
                try:
                    with report_path.open(encoding="utf-8") as stream:
                        report = json.load(stream)
                except (OSError, ValueError) as exc:
                    raise SourceFinalizationRequired(f"Unreadable source finalization record: {report_path}") from exc
                if report.get("version") != FINALIZATION_VERSION:
                    raise SourceFinalizationRequired(f"Unsupported source finalization record: {report_path}")
                records[directory].append((report_path, report))
        candidates = [(name, report) for name, report in records[directory] if path.name in report.get("members", {})]
        actual = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        candidates = [(name, report) for name, report in candidates if report["members"][path.name] == actual]
        if not candidates:
            raise SourceFinalizationRequired(f"{path}: absent/stale finalization record; rerun kg transform")
        # A valid later full-ontology record can supersede an older scoped
        # record even if the graph bytes are identical. Never select a stale
        # narrower record before checking each candidate's actual authorities.
        for record_path, report in sorted(candidates, key=lambda item: len(item[1]["members"])):
            if record_path not in record_errors:
                error = None
                if report.get("finalizer_code") != current_finalizer:
                    error = "source-finalization code changed; rerun kg transform"
                producer = report.get("producer_code")
                if producer and producer["fingerprint"] != code_fingerprint(Path(producer["directory"]), repo_root):
                    error = "producer code changed; rerun kg transform"
                for authority in report.get("inputs", []):
                    authority_path = Path(authority["path"])
                    if authority_path not in authority_hashes:
                        authority_hashes[authority_path] = _sha256(authority_path) if authority_path.is_file() else None
                    if authority_hashes[authority_path] != authority["sha256"]:
                        error = f"consumed authority changed or missing: {authority_path}"
                audits = report.get("audit_members", {})
                if not audits:
                    error = "missing mandatory audit-member identities; rerun kg transform"
                for name, expected in audits.items():
                    audit_path = record_path.parent / name
                    if (
                        not audit_path.is_file()
                        or {"bytes": audit_path.stat().st_size, "sha256": _sha256(audit_path)} != expected
                    ):
                        error = f"mandatory audit report changed or missing: {audit_path}"
                record_errors[record_path] = error
            if record_errors[record_path] is None:
                break
        else:
            raise SourceFinalizationRequired(f"{record_path}: {record_errors[record_path]}")


def write_merge_validation_report(node_path, edge_path, report_path):
    """Validate a merged pair without semantic edits; keep the legacy audit member name explicit."""
    counts = validate_graph_bundle([node_path], [edge_path], require_closure=True)
    with atomic_write(report_path, encoding="utf-8", newline="") as stream:
        writer = tsv_dict_writer(stream, fieldnames=["check", "status", "nodes", "edges"])
        writer.writeheader()
        writer.writerow(
            {"check": "canonical_representation_and_endpoint_closure_no_semantic_rewrites", "status": "pass", **counts}
        )
    return counts
