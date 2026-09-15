"""Replacement of imported GO axioms must not manufacture hierarchy cycles or erase evidence."""

import csv
import hashlib
import json
import pickle
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import networkx as nx
import pytest

from kg_microbe.utils.go_authority import GoAuthority, GoReferenceError, load_go_authority, normalize_go_bundle
from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

FIXTURES = Path(__file__).parent / "resources/go_imported_axioms"


def _read(path, *, quoting=csv.QUOTE_NONE):
    """Read bounded literal graph rows, or explicitly quoted diagnostic reports."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=quoting))


def _prepare(tmp_path, monkeypatch, *, asserted_view=True):
    """Use real selected authority loading on immutable tiny SemSQL-shaped evidence."""
    raw = tmp_path / "raw"
    raw.mkdir()
    database = raw / "go.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE statements(subject,predicate,object,value)")
        conn.executemany(
            "INSERT INTO statements VALUES(?,?,?,?)",
            [
                tuple(row[field] or None for field in ("subject", "predicate", "object", "value"))
                for row in _read(FIXTURES / "statements.tsv")
            ],
        )
        if asserted_view:
            conn.execute("CREATE TABLE edge(subject,predicate,object)")
            conn.executemany(
                "INSERT INTO edge VALUES(?,?,?)",
                [
                    tuple(row[field] for field in ("subject", "predicate", "object"))
                    for row in _read(FIXTURES / "asserted_edges.tsv")
                ],
            )
    monkeypatch.setattr("kg_microbe.utils.go_authority._prepare_go_database", lambda selected: selected / "go.db")
    nodes, edges, report = (tmp_path / name for name in ("pato_nodes.tsv", "pato_edges.tsv", "resolution.tsv"))
    shutil.copyfile(FIXTURES / "nodes.tsv", nodes)
    shutil.copyfile(FIXTURES / "edges.tsv", edges)
    return raw, nodes, edges, report


def _quarantine_records(report):
    """Find lossless unsupported/quarantined source assertions without requiring report ordering."""
    records = []
    for row in _read(report, quoting=csv.QUOTE_MINIMAL):
        disposition = row.get("disposition", "").lower()
        if row.get("original_record_json") and ("quarant" in disposition or "unsupported" in disposition):
            records.append(json.loads(row["original_record_json"]))
    return records


def _write(path, rows, *, fields=None, quoting=csv.QUOTE_NONE):
    """Write bounded fixture variants without changing their scalar quote characters."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields or list(rows[0]),
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def test_replacement_imports_do_not_create_cycles_and_are_losslessly_quarantined(tmp_path, monkeypatch):
    """Reproduce actual obsolete biosynthesis→metabolism replacement cycles and partonomy loops."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    authority = load_go_authority(raw)
    normalize_go_bundle([nodes], [edges], authority, report)
    rows = _read(edges)
    graph = nx.DiGraph((row["subject"], row["object"]) for row in rows if row["predicate"] == "biolink:subclass_of")
    assert nx.is_directed_acyclic_graph(graph), "Authoritative ID replacement must not transfer reverse ancestry"
    assert not any(row["subject"] == row["object"] for row in rows)
    unsupported = {
        row["source_record"]: row
        for row in _read(FIXTURES / "edges.tsv")
        if row["source_record"].startswith("unsupported-")
    }
    assert not unsupported.keys() & {row["source_record"] for row in rows}
    quarantined = {row["source_record"]: row for row in _quarantine_records(report)}
    assert all(quarantined.get(key) == value for key, value in unsupported.items()), "Every original field must survive"


def test_supported_imports_and_external_observations_keep_exact_context(tmp_path, monkeypatch):
    """The narrow structural gate is relation-sensitive and does not suppress observation remapping."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    authority = pickle.loads(pickle.dumps(load_go_authority(raw)))
    normalize_go_bundle([nodes], [edges], authority, report)
    rows = {row["source_record"]: row for row in _read(edges)}
    assert "unsupported-wrong-relation" not in rows
    originals = {row["source_record"]: row for row in _read(FIXTURES / "edges.tsv")}
    for key in ("supported-import", "supported-partonomy"):
        assert rows[key]["subject"] == "GO:0008152"
        assert rows[key]["original_subject"] == "GO:0016053"
        for field, value in originals[key].items():
            if field != "subject":
                assert rows[key][field] == value
    unchanged = "unchanged-unsupported-import"
    assert all(rows[unchanged][field] == value for field, value in originals[unchanged].items())
    for key in ("organism-observation", "assay-observation"):
        assert rows[key]["object"] == "GO:0008152"
        expected_original = originals[key]["original_object"] or "GO:0016053"
        assert rows[key]["original_object"] == expected_original
        for field, value in originals[key].items():
            if field not in {"object", "original_object"}:
                assert rows[key][field] == value
        assert json.loads(rows[key]["go_reference_context"])[-1]["original_id"] == "GO:0016053"


@pytest.mark.parametrize("broken_view", [False, True])
def test_missing_asserted_authority_cannot_silently_bless_imported_rewrites(tmp_path, monkeypatch, broken_view):
    """Required structural support failures leave both original graph members untouched."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch, asserted_view=False)
    if broken_view:
        with sqlite3.connect(raw / "go.db") as connection:
            connection.execute("CREATE VIEW edge AS SELECT subject,predicate,object FROM missing_asserted_edges")
    original = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(OntologyDbUnavailableError, match="edge|assert|structure|axiom"):
        load_go_authority(raw)
    assert (nodes.read_bytes(), edges.read_bytes()) == original


@pytest.mark.parametrize("source_record", ["unsupported-cycle", "organism-observation", "assay-observation"])
def test_metadata_only_authority_requires_axioms_only_for_gated_rows(tmp_path, monkeypatch, source_record):
    """Explicit in-memory metadata suffices for observations, never for imported structural rewrites."""
    _, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    statements = [
        tuple(row[field] or None for field in ("subject", "predicate", "object", "value"))
        for row in _read(FIXTURES / "statements.tsv")
    ]
    authority = GoAuthority.from_statements(statements)
    row = next(row for row in _read(FIXTURES / "edges.tsv") if row["source_record"] == source_record)
    _write(edges, [row])
    before = nodes.read_bytes(), edges.read_bytes()
    if source_record == "unsupported-cycle":
        with pytest.raises(GoReferenceError, match="assert|Assert|structure|axiom"):
            normalize_go_bundle([nodes], [edges], authority, report)
        assert (nodes.read_bytes(), edges.read_bytes()) == before
    else:
        normalize_go_bundle([nodes], [edges], authority, report)
        actual = _read(edges)[0]
        assert actual["object"] == "GO:0008152"
        assert actual["value"] == row["value"]
        assert actual["publications"] == row["publications"]


def test_repeated_supported_normalization_preserves_quarantine_audit(tmp_path, monkeypatch):
    """A no-op repeat must retain the full excluded-source evidence, not replace it with empty audit."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    authority = load_go_authority(raw)
    normalize_go_bundle([nodes], [edges], authority, report)
    originals = _quarantine_records(report)
    assert len(originals) == 5
    before = nodes.read_bytes(), edges.read_bytes(), report.read_bytes()
    normalize_go_bundle([nodes], [edges], authority, report)
    assert (nodes.read_bytes(), edges.read_bytes(), report.read_bytes()) == before
    assert _quarantine_records(report) == originals


def test_legacy_checkpoint_rechecks_history_and_preserves_original_audit(tmp_path, monkeypatch):
    """An old exact-bundle checkpoint cannot bypass new axiom policy on already-remapped endpoints."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    authority = load_go_authority(raw)
    original = next(row for row in _read(FIXTURES / "edges.tsv") if row["source_record"] == "unsupported-cycle")
    current = dict(original)
    current.update(
        subject="GO:0008152",
        original_subject="GO:0016053",
        go_reference_context=json.dumps(
            [
                {
                    "column": "subject",
                    "original_id": "GO:0016053",
                    "canonical_id": "GO:0008152",
                    "replacement_chain": ["GO:0016053", "GO:0008152"],
                    "authority": authority.authority_path,
                    "authority_sha256": authority.authority_sha256,
                }
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    _write(edges, [current])
    _write(nodes, [row for row in _read(FIXTURES / "nodes.tsv") if row["id"] in {"GO:0008152", "GO:0044283"}])
    metadata_digest = hashlib.sha256()
    for identifier in sorted(authority.records):
        metadata_digest.update(json.dumps(vars(authority.records[identifier]), sort_keys=True).encode())
        metadata_digest.update(b"\n")
    # This is the exact checkpoint shape emitted before the structural policy:
    # current graph bytes and metadata are bound, but no asserted-axiom index is.
    checkpoint = {
        "version": 1,
        "authority": {
            "path": authority.authority_path,
            "sha256": authority.authority_sha256,
            "metadata_sha256": metadata_digest.hexdigest(),
        },
        "bundle": [
            {"kind": kind, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for kind, path in (("nodes", nodes), ("edges", edges))
        ],
    }
    previous = {
        "source_file": edges.name,
        "record_kind": "edge",
        "original_id": "GO:0016053",
        "canonical_id": "GO:0008152",
        "disposition": "replaced",
        "authority": authority.authority_path,
        "authority_sha256": authority.authority_sha256,
        "replacement_chain": '["GO:0016053", "GO:0008152"]',
        "consider": "[]",
        "original_record_json": json.dumps(original, sort_keys=True),
        "bundle_fingerprint": "",
    }
    _write(
        report,
        [previous, {"record_kind": "bundle_checkpoint", "bundle_fingerprint": json.dumps(checkpoint)}],
        fields=list(previous),
        quoting=csv.QUOTE_MINIMAL,
    )
    counts = normalize_go_bundle([nodes], [edges], authority, report)
    assert counts.get("already_normalized", 0) == 0
    assert _read(edges) == []
    audit = _read(report, quoting=csv.QUOTE_MINIMAL)
    assert any(all(row[field] == value for field, value in previous.items()) for row in audit)
    quarantined = [row for row in audit if row.get("candidate_record_json")]
    assert len(quarantined) == 1
    assert json.loads(quarantined[0]["candidate_record_json"]) == current
    assert json.loads(quarantined[0]["original_record_json"]) == current
    before = nodes.read_bytes(), edges.read_bytes(), report.read_bytes()
    normalize_go_bundle([nodes], [edges], authority, report)
    assert (nodes.read_bytes(), edges.read_bytes(), report.read_bytes()) == before


def test_asserted_index_fingerprint_rechecks_previously_supported_candidate(tmp_path, monkeypatch):
    """Pickled axiom evidence participates in checkpoint identity independently of term metadata."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    authority = load_go_authority(raw)
    candidate = ("GO:0008152", "rdfs:subClassOf", "GO:0044283")
    permissive = pickle.loads(
        pickle.dumps(replace(authority, structural_edges=authority.structural_edges | {candidate}))
    )
    assert permissive.structural_edges == authority.structural_edges | {candidate}
    assert isinstance(permissive.structural_edges, frozenset)
    normalize_go_bundle([nodes], [edges], permissive, report)
    assert any(row["source_record"] == "unsupported-cycle" for row in _read(edges))
    old_audit = _read(report, quoting=csv.QUOTE_MINIMAL)
    result = normalize_go_bundle([nodes], [edges], authority, report)
    assert not result.get("already_normalized")
    assert not any(row["source_record"] == "unsupported-cycle" for row in _read(edges))
    new_audit = _read(report, quoting=csv.QUOTE_MINIMAL)
    assert all(row in new_audit for row in old_audit if row["record_kind"] != "bundle_checkpoint")


@pytest.mark.parametrize("row_number", [0, 1])
def test_structural_predicate_relation_mismatch_fails_closed(tmp_path, monkeypatch, row_number):
    """Neither one correct structural field nor asserted support can bless an inconsistent pair."""
    raw, nodes, edges, report = _prepare(tmp_path, monkeypatch)
    row = _read(FIXTURES / "mismatched_edges.tsv")[row_number]
    with edges.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(row), delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow(row)
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises((GoReferenceError, ValueError), match="structure|predicate|relation"):
        normalize_go_bundle([nodes], [edges], load_go_authority(raw), report)
    assert (nodes.read_bytes(), edges.read_bytes()) == before
