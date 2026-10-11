"""The real Rhea producer retains directions and chemical identity on canonical outputs."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.rhea_mappings import rhea_mappings as module
from kg_microbe.transform_utils.rhea_mappings.native_graph import native_curie
from kg_microbe.transform_utils.rhea_mappings.native_rdf import NativeRheaError
from kg_microbe.utils.graph_schema import validate_canonical_tsv
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import verify_consumed_inputs
from tests.rhea_fixtures import stage_rhea_label_databases
from tests.rhea_legacy_fixtures import empty_legacy_policy
from tests.test_rhea_native_inputs import FIXTURE, _inputs
from tests.test_rhea_native_inputs import _replace_native as _replace_native_input


def _fixture_legacy_policy(producer, policy):
    """Declare this tiny fixture's actual lack of a historical cohort without waiving production history."""
    path = producer.input_base_dir / "rhea/fixture_legacy_policy.json"
    path.write_text(json.dumps(empty_legacy_policy(policy)), encoding="utf-8")
    return path


def _replace_native(producer, path, policy, xml):
    """Repin a deliberate native fixture variation and its correspondingly scoped no-history policy."""
    _replace_native_input(producer, path, policy, xml)
    _fixture_legacy_policy(producer, policy)


def _producer(tmp_path, monkeypatch):
    """Use the actual producer with native reads and prepared raw-root label authorities."""
    fixture, policy_path, policy = _inputs(tmp_path)
    monkeypatch.setattr(module, "POLICY_PATH", policy_path)
    stage_rhea_label_databases(fixture.input_base_dir)
    producer = module.RheaMappingsTransform(fixture.input_base_dir, tmp_path / "transformed")
    monkeypatch.setattr(module, "LEGACY_POLICY_PATH", _fixture_legacy_policy(producer, policy))
    return producer, policy_path, policy


def _rows(path):
    """Read only these tiny fixture TSVs in literal canonical dialect."""
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_real_producer_emits_complete_family_direction_paths(tmp_path, monkeypatch):
    """Variants carry distinct states; master links make their annotations traversable."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    nodes = {row["id"]: row for row in _rows(producer.output_node_file)}
    edges = _rows(producer.output_edge_file)
    triples = {(row["subject"], row["predicate"], row["object"]) for row in edges}
    for identifier, direction in (("100", "UN"), ("101", "LR"), ("102", "RL"), ("103", "BI")):
        row = nodes["RHEA:" + identifier]
        assert row["rhea_direction"] == direction
        assert row["rhea_master_id"] == "RHEA:100"
        assert row["rhea_status"] == "Approved"
    assert {
        ("RHEA:100", "rheav:directionalReaction", "RHEA:101"),
        ("RHEA:100", "rheav:directionalReaction", "RHEA:102"),
        ("RHEA:100", "rheav:bidirectionalReaction", "RHEA:103"),
    } <= triples
    for identifier in ("RHEA:100", "RHEA:103"):
        assert (identifier, "biolink:has_participant", "CHEBI:15377") in triples
        assert not any(s == identifier and p in ("biolink:has_input", "biolink:has_output") for s, p, _ in triples)
    assert ("RHEA:101", "biolink:has_input", "rheav:Polymer_2") in triples
    assert ("RHEA:102", "biolink:has_output", "rheav:Polymer_2") in triples
    assert ("RHEA:101", "biolink:has_output", "rheav:Generic_3") in triples
    assert ("RHEA:102", "biolink:has_input", "rheav:Generic_3") in triples
    assert not any(s == o or p in ("biolink:same_as", "biolink:subclass_of") for s, p, o in triples)
    assert validate_canonical_tsv(producer.output_node_file, is_node=True) == len(nodes)
    assert validate_canonical_tsv(producer.output_edge_file, is_node=False) == len(edges)
    verify_consumed_inputs(producer)
    verify_producer_audits(producer)


def test_parts_and_underlying_polymers_are_not_whole_reactants(tmp_path, monkeypatch):
    """Reactive-part ChEBI and polymer base references survive as distinct native paths."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    nodes = {row["id"]: row for row in _rows(producer.output_node_file)}
    assert nodes["rheav:Polymer_2"]["name"] == "fixture polymer (n+1)"
    assert nodes["rheav:Polymer_2"]["rhea_polymerization_index"] == "n+1"
    assert nodes["rheav:Generic_3"]["name"] == "fixture whole compound"
    assert nodes["rheav:ReactivePart_3b"]["name"] == "fixture proton moiety"
    edges = _rows(producer.output_edge_file)
    triples = {(r["subject"], r["predicate"], r["object"]) for r in edges}
    assert ("rheav:Polymer_2", "rheav:underlyingChebi", "CHEBI:27732") in triples
    assert ("rheav:Generic_3", "rheav:reactivePart", "rheav:ReactivePart_3b") in triples
    assert ("rheav:ReactivePart_3b", "rheav:chebi", "CHEBI:15378") in triples
    assert not any(s.startswith("RHEA:") and o in ("CHEBI:27732", "CHEBI:15378") for s, _, o in triples)
    generic = [r for r in edges if r["subject"] == "RHEA:101" and r["object"] == "rheav:Generic_3"]
    assert len(generic) == 1  # two reactive parts do not create two whole-reactant observations
    assert generic[0]["rhea_participant"] == "rheav:Participant_3"
    assert generic[0]["rhea_side"] == "rheav:100_R"


def test_only_same_snapshot_xrefs_are_emitted_once(tmp_path, monkeypatch):
    """Unpinned legacy rhea2 tables and PyOBO cache contents cannot add or duplicate edges."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    (producer.input_base_dir / "rhea2ec.tsv").write_text("RHEA_ID\tID\n100\t9.9.9.9\n")
    producer.run(show_status=False)
    refs = [r for r in _rows(producer.output_edge_file) if r["predicate"] == "biolink:close_match"]
    assert {(r["subject"], r["object"]) for r in refs} == {("RHEA:100", "EC:1.2.3.4"), ("RHEA:100", "GO:0000001")}
    assert len(refs) == 2


def test_real_producer_requires_consumed_history_policy_and_published_audit(tmp_path, monkeypatch):
    """Even an explicitly empty fixture history is bound and audited, not bypassed."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    assert _rows(producer.output_dir / module.LEGACY_AUDIT_FILE) == []
    assert "rhea_legacy_xref_dispositions" in producer.consumed_input_snapshots
    assert module.LEGACY_AUDIT_FILE in producer.producer_audit_snapshots
    verify_consumed_inputs(producer)
    verify_producer_audits(producer)


def test_invalid_history_contract_cannot_publish_graph_or_disposition_reports(tmp_path, monkeypatch):
    """The audited historical selection is checked before replacing any existing producer artifact."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    policy = json.loads(module.LEGACY_POLICY_PATH.read_text())
    policy["expected_count"] = False
    module.LEGACY_POLICY_PATH.write_text(json.dumps(policy))
    outputs = [producer.output_node_file, producer.output_edge_file]
    outputs.extend(producer.output_dir / name for name in producer.REQUIRED_AUDIT_FILES)
    for output in outputs:
        output.write_text("previous artifact\n")
    with pytest.raises(ValueError, match="expected count"):
        producer.run(show_status=False)
    assert all(output.read_text() == "previous artifact\n" for output in outputs)


def test_statuses_and_obsolete_exclusions_are_audited(tmp_path, monkeypatch):
    """A preliminary family is not promoted; a retired record has an explicit disposition."""
    producer, path, policy = _producer(tmp_path, monkeypatch)
    extra = b'<rdf:Description rdf:about="http://rdf.rhea-db.org/9999"><rh:status rdf:resource="http://rdf.rhea-db.org/Obsolete"/></rdf:Description>'
    xml = FIXTURE.read_bytes().replace(b"/Approved", b"/Preliminary").replace(b"</rdf:RDF>", extra + b"</rdf:RDF>")
    _replace_native(producer, path, policy, xml)
    producer.run(show_status=False)
    audit = _rows(producer.output_dir / module.REACTION_AUDIT)
    assert len(audit) == 5
    assert {r["native_status"] for r in audit if r["disposition"] == "retained_active"} == {"Preliminary"}
    assert [r["reaction_id"] for r in audit if r["disposition"] == "excluded_obsolete"] == ["RHEA:9999"]
    assert "RHEA:9999" not in {r["id"] for r in _rows(producer.output_node_file)}


def test_native_preliminary_ec_identifiers_are_not_discarded(tmp_path, monkeypatch):
    """The pinned export contains EC:3.6.5.n1; preserve its exact provisional identity."""
    producer, path, policy = _producer(tmp_path, monkeypatch)
    xml = FIXTURE.read_bytes().replace(b"/enzyme/1.2.3.4", b"/enzyme/3.6.5.n1")
    _replace_native(producer, path, policy, xml)
    producer.run(show_status=False)
    assert any(row["object"] == "EC:3.6.5.n1" for row in _rows(producer.output_edge_file))


def test_native_nonreaction_helper_cannot_mint_alternate_numeric_reaction_ids():
    """The native vocabulary/compound namespace must not compete with RHEA reaction identity."""
    with pytest.raises(NativeRheaError):
        native_curie("http://rdf.rhea-db.org/100")


def test_native_variant_crossrefs_are_not_moved_or_rejected(tmp_path, monkeypatch):
    """Native RDF includes variant annotations; general documentation must not override their exact subjects."""
    producer, path, policy = _producer(tmp_path, monkeypatch)
    extra = b'<rdf:Description rdf:about="http://rdf.rhea-db.org/103"><rh:ec rdf:resource="http://purl.uniprot.org/enzyme/2.3.4.5"/></rdf:Description>'
    _replace_native(producer, path, policy, FIXTURE.read_bytes().replace(b"</rdf:RDF>", extra + b"</rdf:RDF>"))
    producer.run(show_status=False)
    refs = [row for row in _rows(producer.output_edge_file) if row["object"] == "EC:2.3.4.5"]
    assert len(refs) == 1 and refs[0]["subject"] == "RHEA:103"
    derived = [row for row in _rows(producer.output_edge_file) if row["rhea_participant"]]
    assert {row["agent_type"] for row in derived} == {"automated_agent"}
    assert {row["knowledge_level"] for row in derived} == {"logical_entailment"}


def test_opposite_direction_go_annotations_stay_on_their_native_variants(tmp_path, monkeypatch):
    """Like native 57721/57722, different directional functions must not be pooled onto a master."""
    producer, path, policy = _producer(tmp_path, monkeypatch)
    extra = (
        b'<rdf:Description rdf:about="http://rdf.rhea-db.org/101"><rdfs:seeAlso rdf:resource="http://purl.obolibrary.org/obo/GO_0046961"/></rdf:Description>'
        b'<rdf:Description rdf:about="http://rdf.rhea-db.org/102"><rdfs:seeAlso rdf:resource="http://purl.obolibrary.org/obo/GO_0046933"/></rdf:Description>'
    )
    _replace_native(producer, path, policy, FIXTURE.read_bytes().replace(b"</rdf:RDF>", extra + b"</rdf:RDF>"))
    producer.run(show_status=False)
    refs = {
        (row["subject"], row["object"])
        for row in _rows(producer.output_edge_file)
        if row["object"] in {"GO:0046961", "GO:0046933"}
    }
    assert refs == {("RHEA:101", "GO:0046961"), ("RHEA:102", "GO:0046933")}


def test_real_kgx_merge_transport_preserves_all_direction_and_participant_fields(tmp_path, monkeypatch):
    """Real KGX parsing, duplicate-source aggregation and serialization must not erase native context."""
    from kg_microbe.merge_utils.kgx_source import (
        ProvenancePreservingTransformer,
        RelationAwareTsvSink,
        merge_assertion_graphs,
        parse_source,
    )
    from kg_microbe.merge_utils.local_context import local_prefix_context

    schema = Path(__file__).parent / "resources/merge_offline_context/biolink-model.yaml"
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(schema))
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    spec = {"input": {"format": "tsv", "filename": [str(producer.output_node_file), str(producer.output_edge_file)]}}
    stores = [parse_source(name, spec, str(tmp_path)) for name in ("first", "duplicate")]
    graph = merge_assertion_graphs(store.graph for store in stores)
    with local_prefix_context():
        sink = RelationAwareTsvSink(
            ProvenancePreservingTransformer(),
            str(tmp_path / "roundtrip"),
            "tsv",
            node_properties=set(producer.node_header),
            edge_properties=set(producer.edge_header),
        )
    try:
        for _, node in graph.nodes(data=True):
            sink.write_node(node)
        for _, _, edge in graph.edges(data=True):
            sink.write_edge(edge)
    finally:
        sink.NFH.close()
        sink.EFH.close()
    for source, target in (
        (producer.output_node_file, Path(sink.nodes_file_name)),
        (producer.output_edge_file, Path(sink.edges_file_name)),
    ):
        # The separate pre-existing blank-xref list aggregation finding is
        # tracked in #1398. This gate checks all new scalar node annotations,
        # identity/name/provenance and every participant assertion field.
        fields = (
            (
                "id",
                "category",
                "name",
                "provided_by",
                "rhea_direction",
                "rhea_master_id",
                "rhea_status",
                "rhea_polymerization_index",
            )
            if source == producer.output_node_file
            else producer.edge_header
        )
        assert sorted(tuple(row[field] for field in fields) for row in _rows(source)) == sorted(
            tuple(row[field] for field in fields) for row in _rows(target)
        )


def test_bad_native_participant_leaves_existing_outputs_unchanged(tmp_path, monkeypatch):
    """Semantic failures cannot publish a partial replacement graph or fresh audit."""
    producer, path, policy = _producer(tmp_path, monkeypatch)
    xml = FIXTURE.read_bytes().replace(b'<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_1"/>', b"")
    _replace_native(producer, path, policy, xml)
    for output in (producer.output_node_file, producer.output_edge_file, producer.output_dir / module.REACTION_AUDIT):
        output.write_text("previous output\n")
    with pytest.raises(NativeRheaError, match="Missing participant compound"):
        producer.run(show_status=False)
    for output in (producer.output_node_file, producer.output_edge_file, producer.output_dir / module.REACTION_AUDIT):
        assert output.read_text() == "previous output\n"
    with pytest.raises(ValueError, match="audit snapshots"):
        verify_producer_audits(producer)
