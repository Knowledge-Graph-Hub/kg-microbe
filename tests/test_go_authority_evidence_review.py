"""Independent multistage GO normalization preserves assertion and audit evidence (#1086)."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.merge_utils.kgx_source import assertion_key, parse_source
from kg_microbe.utils.go_authority import GoAuthority, normalize_go_bundle

FIXTURES = Path(__file__).parent / "resources" / "go_authority"


def _read(path, *, quoting=csv.QUOTE_NONE):
    """Read a bounded literal graph fixture or explicitly quoted diagnostic report."""
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=quoting))


@pytest.fixture
def authority():
    """Use immutable local GO evidence with explicit two-step replacement chains."""
    statements = [
        tuple(row[column] or None for column in ("subject", "predicate", "object", "value"))
        for row in _read(FIXTURES / "statements.tsv")
    ]
    return GoAuthority.from_statements(statements, authority_path="fixture/go.db", authority_sha256="a" * 64)


@pytest.fixture
def bundle(tmp_path):
    """Copy immutable source assertions and declarations to isolated output paths."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "resolution.tsv"))
    shutil.copyfile(FIXTURES / "evidence_nodes.tsv", nodes)
    shutil.copyfile(FIXTURES / "evidence_edges.tsv", edges)
    return nodes, edges, report


def _original_records(report):
    """Compare complete original source rows without prescribing report ordering."""
    return {
        (row["record_kind"], json.dumps(json.loads(row["original_record_json"]), sort_keys=True))
        for row in _read(report, quoting=csv.QUOTE_MINIMAL)
        if row["original_record_json"]
    }


def test_earliest_original_and_immediate_source_context_both_survive(bundle, authority):
    """An earlier original ID stays scalar while exact incoming target evidence remains auditable."""
    nodes, edges, report = bundle
    normalize_go_bundle([nodes], [edges], authority, report)
    rows = _read(edges)
    assert len(rows) == 2
    assert {row["object"] for row in rows} == {"GO:0004096"}
    assert {row["original_object"] for row in rows} == {"GO:9999001"}
    assert all(
        row["primary_knowledge_source"] == "infores:rhea"
        and row["knowledge_level"] == "knowledge_assertion"
        and row["agent_type"] == "manual_agent"
        and row["publications"] == "PMID:1"
        for row in rows
    )
    originals = [json.loads(row) for kind, row in _original_records(report) if kind == "edge"]
    assert {row["object"] for row in originals} == {"GO:9999002", "GO:9999003"}
    assert {row["original_object"] for row in originals} == {"GO:9999001"}


def test_distinct_incoming_assertions_survive_real_kgx_ingestion(bundle, authority, tmp_path, monkeypatch):
    """Preserving row count alone cannot allow normalized evidence identities to collapse."""
    nodes, edges, report = bundle
    normalize_go_bundle([nodes], [edges], authority, report)
    rows = _read(edges)
    assert len({assertion_key(row) for row in rows}) == 2
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {})
    source = {"input": {"format": "tsv", "filename": [str(nodes), str(edges)]}}
    graph = parse_source("go-evidence-review", source, str(tmp_path / "kgx")).graph
    assert graph.number_of_edges() == 2
    assert {data["original_object"] for _, _, data in graph.edges(data=True)} == {"GO:9999001"}


def test_idempotent_repeat_retains_original_node_and_assertion_audit(bundle, authority):
    """Repeated normalization preserves original metadata evidence as well as graph bytes."""
    nodes, edges, report = bundle
    normalize_go_bundle([nodes], [edges], authority, report)
    before_graph = nodes.read_bytes(), edges.read_bytes()
    originals = _original_records(report)
    assert sum(kind == "edge" for kind, _ in originals) == 2
    assert sum(kind == "node" for kind, _ in originals) == 2
    assert any("Original source-specific activity context." in row for _, row in originals)
    normalize_go_bundle([nodes], [edges], authority, report)
    assert (nodes.read_bytes(), edges.read_bytes()) == before_graph
    assert originals <= _original_records(report)
