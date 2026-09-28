"""GO checkpoints bind published canonical bytes after every authority/header stage."""

import csv
import hashlib
import json
import shutil
import sqlite3
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import go_authority
from kg_microbe.utils.graph_schema import canonical_header
from kg_microbe.utils.source_finalization import (
    graph_rows,
    verify_finalized_source_files,
)

FIXTURES = Path(__file__).parent / "resources"


def _read(path, quoting=csv.QUOTE_NONE):
    """Read only tiny hermetic graph or audit fixtures using their explicit dialect."""
    return list(graph_rows(path, quoting=quoting))


def _header(path):
    """Read the literal graph header without loading graph rows."""
    with path.open(newline="") as stream:
        return next(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _digest(path):
    """Hash a bounded test fixture, never a production graph."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkpoint(report):
    """Require one explicitly versioned final-byte checkpoint in the GO audit."""
    checkpoints = [
        json.loads(row["bundle_fingerprint"])
        for row in _read(report, csv.QUOTE_MINIMAL)
        if row["record_kind"] == "bundle_checkpoint"
    ]
    assert len(checkpoints) == 1
    return checkpoints[0]


def _write(path, fields, rows, quoting=csv.QUOTE_NONE):
    """Serialize intentional tiny migration or mutation fixtures in their specified dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _audit_rows(report):
    """Retain complete audit events while comparing checkpoints separately."""
    return [row for row in _read(report, csv.QUOTE_MINIMAL) if row["record_kind"] != "bundle_checkpoint"]


def _set_checkpoint(report, version, nodes, edges, *, bind_bytes=True):
    """Reproduce an old exact or mismatched checkpoint without touching its disposition rows."""
    rows = _read(report, csv.QUOTE_MINIMAL)
    for row in rows:
        if row["record_kind"] == "bundle_checkpoint":
            checkpoint = json.loads(row["bundle_fingerprint"])
            checkpoint["version"] = version
            if bind_bytes:
                checkpoint["bundle"] = [
                    {"kind": kind, "file": path.name, "sha256": _digest(path)}
                    for kind, path in (("nodes", nodes), ("edges", edges))
                ]
            row["bundle_fingerprint"] = json.dumps(checkpoint, sort_keys=True)
    _write(report, list(rows[0]), rows, csv.QUOTE_MINIMAL)


def _prepare(tmp_path, monkeypatch, target):
    """Build actual tiny local GO/NCBI authorities and a source needing header extension."""
    raw = tmp_path / "raw"
    raw.mkdir()
    with sqlite3.connect(raw / "go.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value)")
        connection.execute("CREATE TABLE edge(subject,predicate,object)")
        with (FIXTURES / "go_authority" / "statements.tsv").open(newline="") as source:
            reader = csv.DictReader(source, delimiter="\t")
            connection.executemany(
                "INSERT INTO statements VALUES(?,?,?,?)",
                (tuple(row[key] or None for key in ("subject", "predicate", "object", "value")) for row in reader),
            )
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        for name in ("nodes.dmp", "names.dmp", "merged.dmp"):
            archive.add(FIXTURES / "source_finalization_review" / name, arcname=name)
    # Only bypass the production-sized GO cache builder; the real loader,
    # SQLite evidence, hashes, external closure and source finalizer all run.
    monkeypatch.setattr(go_authority, "_prepare_go_database", lambda root: root / "go.db")
    producer = Transform("fixture", raw, tmp_path / "transformed")
    producer.TSV_QUOTING = csv.QUOTE_NONE
    shutil.copyfile(FIXTURES / "go_checkpoint" / "nodes.tsv", producer.output_node_file)
    producer.output_edge_file.write_text(
        (FIXTURES / "go_checkpoint" / "edges.tsv").read_text().replace("GO:0004096", target)
    )
    return producer


@pytest.mark.parametrize("target", ["GO:0004096", "GO:9999002"])
def test_composed_finalizer_checkpoint_binds_published_headers_and_exact_rows(tmp_path, monkeypatch, target):
    """External header addition plus GO metadata/remapping cannot leave an intermediate checkpoint."""
    producer = _prepare(tmp_path, monkeypatch, target)
    original_rows = _read(producer.output_edge_file)
    assert "original_object" in _header(producer.output_edge_file)
    assert "original_subject" not in _header(producer.output_edge_file)
    observed = {}
    normalize = go_authority.normalize_go_bundle

    def capture_go_output(nodes, edges, authority, report, **kwargs):
        """Witness actual external-closure output and GO replacement bytes before final ordering."""
        entering = _header(edges[0])
        assert entering[-1] == "original_subject"
        assert entering != canonical_header(entering, False)
        result = normalize(nodes, edges, authority, report, **kwargs)
        observed.update({path.name: path.read_bytes() for path in [*nodes, *edges]})
        return result

    monkeypatch.setattr(go_authority, "normalize_go_bundle", capture_go_output)
    manifest = producer.finalize(fresh_run=True)
    monkeypatch.setattr(go_authority, "normalize_go_bundle", normalize)
    nodes, edges = producer.output_node_file, producer.output_edge_file
    report = producer.output_dir / "go_reference_resolution.tsv"
    checkpoint = _checkpoint(report)
    assert checkpoint["version"] == 2
    actual = {path.name: _digest(path) for path in (nodes, edges)}
    assert {row["file"]: row["sha256"] for row in checkpoint["bundle"]} == actual
    assert {name: member["sha256"] for name, member in manifest["members"].items()} == actual
    assert {path.name: path.read_bytes() for path in (nodes, edges)} == observed
    for path, is_node in ((nodes, True), (edges, False)):
        assert _header(path) == canonical_header(_header(path), is_node)
    rows = _read(edges)
    assert len(rows) == len(original_rows) == 3
    assert rows[0] == rows[1]
    for original, row in zip(original_rows, rows, strict=True):
        for field, value in original.items():
            expected = "GO:0004096" if field == "object" and value == "GO:9999002" else value
            assert row[field] == expected
        assert row["original_subject"] == ""
    if target == "GO:9999002":
        assert any(row["record_kind"] == "edge" for row in _read(report, csv.QUOTE_MINIMAL))
        assert json.loads(rows[0]["go_reference_context"])[0]["original_id"] == target
    authority = go_authority.load_go_authority(producer.input_base_dir)
    before = {path: path.read_bytes() for path in (nodes, edges, report)}
    assert normalize([nodes], [edges], authority, report) == {"already_normalized": 1}
    assert {path: path.read_bytes() for path in before} == before
    verify_finalized_source_files([nodes, edges])
    assert producer.finalize() == manifest
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("noncanonical", [False, True])
def test_verified_checkpoint_migration_retains_obsolete_audit_and_later_history(
    tmp_path, monkeypatch, version, noncanonical
):
    """Byte-verified old audit survives representation migration and a subsequent authority replacement."""
    producer = _prepare(tmp_path, monkeypatch, "GO:9999002")
    producer.finalize(fresh_run=True)
    nodes, edges = producer.output_node_file, producer.output_edge_file
    report = producer.output_dir / "go_reference_resolution.tsv"
    authority = go_authority.load_go_authority(producer.input_base_dir)
    if noncanonical:
        for path in (nodes, edges):
            _write(path, list(reversed(_header(path))), _read(path))
    _set_checkpoint(report, version, nodes, edges)
    old_events, original_rows = _audit_rows(report), _read(edges)
    assert any(row["record_kind"] == "edge" for row in old_events)
    before = {path: path.read_bytes() for path in (nodes, edges, report)}
    result = go_authority.normalize_go_bundle([nodes], [edges], authority, report)
    if version == 2 and not noncanonical:
        assert result == {"already_normalized": 1}
        assert {path: path.read_bytes() for path in before} == before
    else:
        assert "already_normalized" not in result
    assert _read(edges) == original_rows
    assert all(row in _audit_rows(report) for row in old_events)
    for path, is_node in ((nodes, True), (edges, False)):
        assert _header(path) == canonical_header(_header(path), is_node)
    assert _checkpoint(report)["version"] == 2
    assert {row["file"]: row["sha256"] for row in _checkpoint(report)["bundle"]} == {
        path.name: _digest(path) for path in (nodes, edges)
    }

    terms = dict(authority.records)
    terms["GO:0004096"] = replace(terms["GO:0004096"], deprecated=True, replaced_by=("GO:0008152",))
    later = replace(authority, records=terms, authority_sha256="b" * 64)
    assert "already_normalized" not in go_authority.normalize_go_bundle([nodes], [edges], later, report)
    final_rows = _read(edges)
    assert final_rows[0]["object"] == final_rows[1]["object"] == "GO:0008152"
    assert all(len(json.loads(row["go_reference_context"])) == 2 for row in final_rows[:2])
    assert final_rows[0]["original_object"] == "GO:9999001"
    assert all(row in _audit_rows(report) for row in old_events)
    before = {path: path.read_bytes() for path in (nodes, edges, report)}
    assert go_authority.normalize_go_bundle([nodes], [edges], later, report) == {"already_normalized": 1}
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("mutation", ["cell", "multiplicity", "legacy_intermediate_header"])
def test_changed_bundle_never_inherits_or_blesses_unmatched_audit(tmp_path, monkeypatch, mutation):
    """Representation handling cannot make changed observations or an intermediate hash reusable."""
    producer = _prepare(tmp_path, monkeypatch, "GO:9999002")
    producer.finalize(fresh_run=True)
    nodes, edges = producer.output_node_file, producer.output_edge_file
    report = producer.output_dir / "go_reference_resolution.tsv"
    authority = go_authority.load_go_authority(producer.input_base_dir)
    assert any(row["record_kind"] == "edge" for row in _audit_rows(report))
    fields, rows = _header(edges), _read(edges)
    if mutation == "cell":
        rows[0]["value"] = '"different"\\nbackslash'
    elif mutation == "multiplicity":
        rows.append(dict(rows[0]))
    else:
        fields = list(reversed(fields))
        _set_checkpoint(report, 1, nodes, edges, bind_bytes=False)
    _write(edges, fields, rows)
    assert "already_normalized" not in go_authority.normalize_go_bundle([nodes], [edges], authority, report)
    assert _read(edges) == rows
    # The prior obsolete-endpoint audit cannot be attributed to unbound bytes.
    assert not any(row["record_kind"] == "edge" for row in _audit_rows(report))
    assert {row["file"]: row["sha256"] for row in _checkpoint(report)["bundle"]} == {
        path.name: _digest(path) for path in (nodes, edges)
    }


@pytest.mark.parametrize("identity", ["authority_path", "authority_sha256"])
def test_authority_identity_change_forbids_reuse_but_retains_verified_audit(tmp_path, monkeypatch, identity):
    """Exact graph identity permits audit retention, not skipping a changed authority."""
    producer = _prepare(tmp_path, monkeypatch, "GO:9999002")
    producer.finalize(fresh_run=True)
    nodes, edges = producer.output_node_file, producer.output_edge_file
    report = producer.output_dir / "go_reference_resolution.tsv"
    authority = go_authority.load_go_authority(producer.input_base_dir)
    authority = replace(authority, **{identity: "different/go.db" if identity == "authority_path" else "b" * 64})
    old_events, rows = _audit_rows(report), _read(edges)
    assert "already_normalized" not in go_authority.normalize_go_bundle([nodes], [edges], authority, report)
    assert _read(edges) == rows
    assert all(row in _audit_rows(report) for row in old_events)
    key = "path" if identity == "authority_path" else "sha256"
    assert _checkpoint(report)["authority"][key] == getattr(authority, identity)
