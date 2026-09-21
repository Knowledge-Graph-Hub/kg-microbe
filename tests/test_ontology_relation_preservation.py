"""Ontology conversion must retain source relations even when Biolink predicates coincide."""

import ast
import builtins
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform, _run_kgx_transform
from kg_microbe.transform_utils.transform import Transform

FIXTURES = Path(__file__).parent / "resources/ontology_relations"


@pytest.fixture(autouse=True)
def pinned_relation_model(monkeypatch):
    """Use immutable mapping evidence that maps both real source relations to part_of."""
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(FIXTURES / "biolink-model.yaml"))


def _rows(path):
    """Read only a small literal converter TSV fixture."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _convert(tmp_path, *, reverse=False, keep_keys=False, mutate=None, source_name="relations", fresh_process=False):
    """Convert one ordered immutable fixture variant via the real KGX boundary."""
    document = json.loads((FIXTURES / "relations.json").read_text())
    if not keep_keys:
        for edge in document["graphs"][0]["edges"]:
            edge.pop("key")
    if mutate:
        mutate(document)
    if reverse:
        document["graphs"][0]["edges"].reverse()
    source = tmp_path / f"{source_name}.json"
    source.write_text(json.dumps(document))
    if fresh_process:
        _convert_with_fresh_toolkit(source, tmp_path / "out")
    else:
        _run_kgx_transform(inputs=[source], input_format="obojson", output=tmp_path / "out", output_format="tsv")
    return _rows(tmp_path / "out_nodes.tsv"), _rows(tmp_path / "out_edges.tsv")


def _convert_with_fresh_toolkit(source, output):
    """Isolate KGX's import-bound Toolkit class while invoking the unchanged real converter offline."""
    # Other tests intentionally import KGX under different minimal schemas.
    # An environment override cannot replace their already imported Toolkit
    # bindings. A fresh interpreter models normal CLI startup without patching
    # the mapper, reader, sink, or the schema-specific predicate expectation.
    script = """
import socket
import sys
import requests

def reject_network(*args, **kwargs):
    raise AssertionError("Network prohibited in isolated ontology conversion")

socket.getaddrinfo = reject_network
socket.gethostbyname = reject_network
socket.gethostbyname_ex = reject_network
socket.create_connection = reject_network
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network
requests.sessions.Session.request = reject_network
from kg_microbe.transform_utils.ontologies.ontologies_transform import _run_kgx_transform
_run_kgx_transform(inputs=[sys.argv[1]], input_format="obojson", output=sys.argv[2], output_format="tsv")
"""
    subprocess.run(  # noqa: S603 - fixed local interpreter/script and isolated fixture paths
        [sys.executable, "-c", script, str(source), str(output)],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str((FIXTURES / "biolink-model.yaml").resolve()),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str((FIXTURES.parent / "predicate_mapping_minimal.yaml").resolve()),
        },
        check=True,
        timeout=60,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_same_spo_distinct_source_relations_survive_both_orders(tmp_path, reverse):
    """One source relation must never overwrite the other at a shared Biolink SPO key."""
    _, edges = _convert(tmp_path, reverse=reverse, fresh_process=True)
    assert len(edges) == 2
    assert {row["predicate"] for row in edges} == {"biolink:part_of"}
    assert {row["relation"] for row in edges} == {"BFO:0000050", "RO:0002007"}


def test_obograph_metadata_and_source_provenance_are_not_column_projected_away(tmp_path):
    """Keep all reader-emitted node properties and explicit edge metadata in the intermediate TSV."""

    def explicit_provenance(document):
        """Attach independent provenance to the first of two otherwise related assertions."""
        document["graphs"][0]["edges"][0].update(
            primary_knowledge_source="infores:fixture-primary",
            original_knowledge_source="infores:fixture-original",
            aggregator_knowledge_source=["infores:fixture-aggregator"],
            supporting_data_source=["infores:fixture-support"],
            provided_by=["infores:fixture-provider"],
            knowledge_level="knowledge_assertion",
            agent_type="manual_agent",
            publications=["PMID:123"],
            description="Source assertion description",
            xref=["TEST:456"],
        )

    nodes, edges = _convert(tmp_path, keep_keys=True, mutate=explicit_provenance)
    node = next(row for row in nodes if row["id"] == "PATO:0000001")
    assert node["name"] == "first quality"
    assert node["description"] == "A fixture definition"
    assert node["iri"] == "http://purl.obolibrary.org/obo/PATO_0000001"
    assert node["deprecated"] == "True"
    # These are the native reader's normalized values, not unparsed raw JSON.
    assert node["subsets"] == "reviewed"
    assert node["xref"] == "TEST:123"
    assert node["same_as"] == "PATO:0000003"
    assert node["synonym"] == node["exact_synonym"] == "fixture synonym"
    assert node["provided_by"] == "relations.json"
    edge = next(row for row in edges if row["relation"] == "BFO:0000050")
    assert edge["key"] == "fixture-bfo"
    assert ast.literal_eval(edge["meta"]) == {"evidence": "first relation"}
    for column, value in {
        "primary_knowledge_source": "infores:fixture-primary",
        "original_knowledge_source": "infores:fixture-original",
        "aggregator_knowledge_source": "infores:fixture-aggregator",
        "supporting_data_source": "infores:fixture-support",
        "provided_by": "infores:fixture-provider",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
        "publications": "PMID:123",
        "description": "Source assertion description",
        "xref": "TEST:456",
    }.items():
        assert edge[column] == value


def test_absent_optional_metadata_keeps_existing_ontology_defaults(tmp_path):
    """Blank projected columns must not suppress the existing default metadata and source rename."""
    _, intermediate = _convert(tmp_path, source_name="pato")
    assert not {"knowledge_level", "agent_type", "primary_knowledge_source"} & intermediate[0].keys()
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    nodes, edges = tmp_path / "out_nodes.tsv", tmp_path / "pato_edges.tsv"
    (tmp_path / "out_edges.tsv").rename(edges)
    transform._add_kgx_metadata_to_edges(edges)
    transform._normalize_schema(nodes, edges)
    for row in _rows(edges):
        assert row["knowledge_level"] == "knowledge_assertion"
        assert row["agent_type"] == "manual_agent"
        assert row["primary_knowledge_source"] == "infores:pato"
    assert len(_rows(edges)) == 2


def test_real_converter_ec_postprocessing_keeps_column_meanings(tmp_path):
    """EC must carry the actual intermediate header until canonical schema projection."""

    def ec_hierarchy(document):
        """Use EC's real URI form and is_a relation through the native converter."""
        graph = document["graphs"][0]
        child, parent = "https://bioregistry.io/eccode:1.1", "https://bioregistry.io/eccode:1"
        graph["nodes"][0]["id"], graph["nodes"][1]["id"] = child, parent
        graph["edges"] = [{"sub": child, "pred": "is_a", "obj": parent}]

    _convert(tmp_path, source_name="ec", mutate=ec_hierarchy)
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    nodes, edges = transform.output_dir / "ec_nodes.tsv", transform.output_dir / "ec_edges.tsv"
    (tmp_path / "out_nodes.tsv").rename(nodes)
    (tmp_path / "out_edges.tsv").rename(edges)
    transform.post_process("ec")
    assert {(row["subject"], row["predicate"], row["object"], row["relation"]) for row in _rows(edges)} == {
        ("EC:1.1", "biolink:subclass_of", "EC:1", "rdfs:subClassOf"),
    }
    assert all(row["primary_knowledge_source"] == "infores:ec" for row in _rows(edges))
    assert all(row["knowledge_level"] == "knowledge_assertion" for row in _rows(edges))
    assert all(row["agent_type"] == "manual_agent" for row in _rows(edges))


@pytest.mark.parametrize("blank_id", [False, True])
@pytest.mark.parametrize("modern_source", [None, "infores:modern", ""])
@pytest.mark.parametrize("blank_metadata", [False, True])
def test_real_converter_upa_projects_header_before_legacy_helpers(
    tmp_path, monkeypatch, blank_id, modern_source, blank_metadata
):
    """UPA preserves its complete chain and pathway edge with extra columns and explicit provenance."""
    _assert_upa_projection(tmp_path, monkeypatch, blank_id, modern_source, blank_metadata)


def _assert_upa_projection(tmp_path, monkeypatch, blank_id, modern_source, blank_metadata, *, reordered=False):
    """Exercise actual conversion and UPA helpers under one explicit intermediate header variant."""
    from kg_microbe.transform_utils.ontologies import ontologies_transform as module

    document = json.loads((FIXTURES / "upa.json").read_text())
    expected_metadata = "" if blank_metadata else "not_provided"
    for edge in document["graphs"][0]["edges"]:
        edge.update(knowledge_source="infores:legacy", knowledge_level=expected_metadata, agent_type=expected_metadata)
        if modern_source is not None:
            edge["primary_knowledge_source"] = modern_source
    source = tmp_path / "upa.json"
    source.write_text(json.dumps(document))
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    monkeypatch.setattr(module, "ONTOLOGIES_XREFS_DIR", tmp_path / "xrefs")
    monkeypatch.setattr(module, "UNIPATHWAYS_XREFS_FILEPATH", tmp_path / "xrefs/unipathways_xrefs.tsv")
    _run_kgx_transform(
        inputs=[source], input_format="obojson", output=transform.output_dir / "upa", output_format="tsv"
    )
    if blank_id or reordered:
        # Native KGX currently generates UUIDs. Exercise the valid blank-id
        # intermediate as a separate negative control for strip-based helpers.
        edges_path = transform.output_dir / "upa_edges.tsv"
        intermediate = _rows(edges_path)
        with edges_path.open("w", newline="") as stream:
            columns = list(intermediate[0])
            writer = csv.DictWriter(stream, fieldnames=columns[::-1] if reordered else columns, delimiter="\t")
            writer.writeheader()
            writer.writerows({**row, "id": ""} if blank_id else row for row in intermediate)
    transform.post_process("upa")
    rows = _rows(transform.output_dir / "upa_edges.tsv")
    triples = {(row["subject"], row["predicate"], row["object"]) for row in rows}
    assert ("RHEA:12345", "biolink:part_of", "UPA:UPA00001") in triples
    assert ("GO:0003824", "biolink:part_of", "UPA:UPA00001") in triples
    assert ("UPA:UPA00001", "biolink:part_of", "UPA:UPA00002") in triples
    pathway = next(row for row in rows if row["subject"] == "UPA:UPA00001")
    expected_source = "infores:legacy" if modern_source is None else modern_source or "infores:upa"
    assert pathway["primary_knowledge_source"] == expected_source
    assert pathway["knowledge_level"] == pathway["agent_type"] == expected_metadata
    assert pathway["relation"] == "BFO:0000050"
    assert {row["id"] for row in _rows(transform.output_dir / "upa_nodes.tsv")} == {
        "RHEA:12345",
        "UPA:UPA00001",
        "UPA:UPA00002",
    }


def test_real_converter_upa_reordered_header_keeps_exact_fields(tmp_path, monkeypatch):
    """Header-name projection cannot depend on native KGX's current column order."""
    _assert_upa_projection(tmp_path, monkeypatch, False, "infores:modern", False, reordered=True)


def test_explicit_blank_metadata_remains_explicit_not_defaulted(tmp_path):
    """Adding streaming conversion does not change the established present-but-blank policy."""

    def blank_metadata(document):
        """Declare blank metadata in the raw assertion itself."""
        for edge in document["graphs"][0]["edges"]:
            edge.update(knowledge_level="", agent_type="", primary_knowledge_source="")

    _, intermediate = _convert(tmp_path, mutate=blank_metadata)
    assert {"knowledge_level", "agent_type", "primary_knowledge_source"} <= intermediate[0].keys()
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    nodes, edges = tmp_path / "out_nodes.tsv", tmp_path / "out_edges.tsv"
    transform._add_kgx_metadata_to_edges(edges)
    transform._normalize_schema(nodes, edges)
    assert all(not row["knowledge_level"] and not row["agent_type"] for row in _rows(edges))


def test_unknown_raw_edge_field_fails_before_output_is_opened(tmp_path):
    """A new source property needs an explicit column policy instead of silent information loss."""

    def unknown_field(document):
        """Add an unsupported raw edge annotation."""
        document["graphs"][0]["edges"][0]["unreviewed_evidence"] = "preserve me"

    with pytest.raises(ValueError, match="Undeclared OBOJSON edge fields.*unreviewed_evidence"):
        _convert(tmp_path, mutate=unknown_field)
    assert not (tmp_path / "out_nodes.tsv").exists()
    assert not (tmp_path / "out_edges.tsv").exists()


def test_unknown_emitted_field_aborts_and_closes_both_sink_handles(tmp_path, monkeypatch):
    """Inspector failures close this converter's handles without globally replacing the KGX sink."""
    from kgx.sink.tsv_sink import TsvSink
    from kgx.source.obograph_source import ObographSource
    from kgx.transformer import Transformer

    captured = []
    original_init, original_read = TsvSink.__init__, ObographSource.read_edge
    original_factory = Transformer.get_sink

    def capture_init(self, *args, **kwargs):
        """Observe real native sink handles for cleanup assertions."""
        original_init(self, *args, **kwargs)
        captured.append(self)

    def added_field(self, *args, **kwargs):
        """Simulate a future KGX reader emitting an undeclared property."""
        result = original_read(self, *args, **kwargs)
        result[-1]["future_reader_field"] = "do not silently discard"
        return result

    monkeypatch.setattr(TsvSink, "__init__", capture_init)
    monkeypatch.setattr(ObographSource, "read_edge", added_field)
    with pytest.raises(ValueError, match="Undeclared KGX.*future_reader_field"):
        _convert(tmp_path)
    assert len(captured) == 1
    assert captured[0].NFH.closed and captured[0].EFH.closed
    assert Transformer.get_sink is original_factory


def test_second_sink_open_failure_closes_first_handle(tmp_path, monkeypatch):
    """Even a partially initialized native sink must not leak its already opened node file."""
    original_open, node_handles = builtins.open, []

    def fail_edge_open(path, *args, **kwargs):
        """Fail only the converter's second output open, after retaining its first handle."""
        if str(path) == str(tmp_path / "out_edges.tsv"):
            raise OSError("injected second sink open failure")
        handle = original_open(path, *args, **kwargs)
        if str(path) == str(tmp_path / "out_nodes.tsv"):
            node_handles.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", fail_edge_open)
    with pytest.raises(OSError, match="injected second sink open failure"):
        _convert(tmp_path)
    assert len(node_handles) == 1 and node_handles[0].closed


def test_exact_duplicate_input_rows_are_streamed_not_pooled(tmp_path):
    """The converter is lossless per input row; downstream exact deduplication owns multiplicity."""

    def duplicate(document):
        """Repeat one identical source assertion without a different relation or evidence."""
        edges = document["graphs"][0]["edges"]
        edges[:] = [edges[0], dict(edges[0])]

    _, edges = _convert(tmp_path, mutate=duplicate)
    assert len(edges) == 2
    assert [{key: value for key, value in row.items() if key != "id"} for row in edges] == [
        {key: value for key, value in edges[0].items() if key != "id"}
    ] * 2


def test_undeclared_endpoint_is_not_minted_and_missing_authority_aborts_finalizer(tmp_path):
    """Streaming cannot invent an anonymous endpoint; the actual finalizer requires its authority."""

    def undeclared(document):
        """Point one retained assertion at an undeclared externally owned entity."""
        document["graphs"][0]["edges"][0]["obj"] = "http://purl.obolibrary.org/obo/CHEBI_1234567"

    nodes, _ = _convert(tmp_path, mutate=undeclared)
    assert "CHEBI:1234567" not in {row["id"] for row in nodes}
    transform = Transform("fixture", tmp_path / "raw", tmp_path / "transformed")
    transform.TSV_QUOTING = csv.QUOTE_NONE
    transform.output_node_file.write_bytes((tmp_path / "out_nodes.tsv").read_bytes())
    # The synthetic converter filename is not a registered information resource.
    # Supply explicit fixture provenance so this test reaches the missing authority.
    transform.output_edge_file.write_text(
        (tmp_path / "out_edges.tsv").read_text().replace("relations.json", "infores:test")
    )
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    with pytest.raises(FileNotFoundError, match="Required CHEBI authority"):
        transform.finalize(fresh_run=True)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()
