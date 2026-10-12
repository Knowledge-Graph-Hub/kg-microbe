"""The same native ENVO release supports category evidence and PREGO retirement evidence."""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies import ontologies_transform as ontologies
from kg_microbe.transform_utils.prego.envo_identity import (
    POLICY_FILE as IDENTITY_POLICY,
)
from kg_microbe.transform_utils.prego.envo_identity import (
    REVIEWED_ENVO_IDS,
    load_identity_decisions,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import finite_envo_po_categories as finite
from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
from tests.native_ro_fixtures import prepare_empty_native_ro_contract
from tests.prego_identity_fixtures import IDENTITY_FIXTURES
from tests.test_finite_envo_po_categories import ORIGIN, POLICY, prepare, repin_native_fixture, source


def identity_decisions(native):
    """Read the unchanged real identity policy with its authentic selected native declarations."""
    with IDENTITY_POLICY.open() as policy, native.open() as envo, (IDENTITY_FIXTURES / "foodon.json").open() as foodon:
        return load_identity_decisions(policy, envo, foodon)


def test_one_native_excerpt_supports_all_ten_retirements_and_both_finite_categories(tmp_path, monkeypatch):
    """Fixture repinning is explicit; its full-source origin remains the reviewed pristine release."""
    raw, _, policy = prepare(tmp_path, monkeypatch)
    assert ORIGIN["native_files"]["envo.json"]["full_source_sha256"] == (
        "c3c288b9d95cf1e62b0146bcb2a365bdbd294b0072bbf2efab8819e5db8fff2b"
    )
    decisions = identity_decisions(raw / "envo.json")
    assert set(decisions) == REVIEWED_ENVO_IDS
    assert Counter(decision.disposition for decision in decisions.values()) == {
        "replace_explicit_unique": 5,
        "retain_unresolved": 5,
    }
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    for identifier in ("ENVO:01001254", "ENVO:01001255"):
        evidence = authority.evidence_for(identifier)
        assert evidence.category == "biolink:EnvironmentalProcess"
        assert json.loads(evidence.native_witness_json) == ORIGIN["selected_native_evidence"]["envo.json"]
        assert "OBI:0000011" not in policy["records"][identifier]["named_path"]


def test_obsolete_side_branch_is_complete_native_evidence_not_new_category_membership(tmp_path, monkeypatch):
    """Retain the explicit native obsolete declaration without inventing an OBI-to-COB graph route."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    graph = json.loads((raw / "envo.json").read_text())["graphs"][0]
    record = next(node for node in graph["nodes"] if node["id"].endswith("OBI_0000011"))
    assert record == ORIGIN["pristine_envo_review"]["obsolete_side_branch"]
    assert record["type"] == "CLASS" and record["meta"]["deprecated"] is True
    assert ORIGIN["pristine_envo_review"]["obsolete_side_branch_edge"] in graph["edges"]
    assert any(item["val"].endswith("COB_0000035") for item in record["meta"]["basicPropertyValues"])
    assert not any(edge["obj"].endswith("COB_0000035") for edge in graph["edges"])
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    for identifier in ("OBI:0000011", "COB:0000035", "ENVO:01001436"):
        assert authority.evidence_for(identifier) is None
    assert not authority.source_paths
    assert finite.FINITE_IDS == {"ENVO:01001254", "ENVO:01001255", "PO:0007033"}


@pytest.mark.parametrize("damage", ["remove", "replace", "duplicate"])
def test_complete_extra_parent_evidence_cannot_be_filtered_or_reinterpreted(tmp_path, monkeypatch, damage):
    """Even an explicitly repinned fixture cannot change the complete reviewed selected-parent witness."""
    raw, policy_path, policy = prepare(tmp_path, monkeypatch)
    path = raw / "envo.json"
    data = json.loads(path.read_text())
    edges = data["graphs"][0]["edges"]
    edge = next(edge for edge in edges if edge["obj"].endswith("OBI_0000011"))
    if damage == "remove":
        edges.remove(edge)
    elif damage == "replace":
        edge["obj"] = "http://purl.obolibrary.org/obo/COB_0000035"
    else:
        edges.append(copy.deepcopy(edge))
    path.write_text(json.dumps(data))
    repin_native_fixture(path, policy_path, policy, monkeypatch)
    with pytest.raises(ValueError, match="definition/parent/restriction evidence changed"):
        finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for("ENVO:01001254")


def test_filtered_input_cannot_replace_the_pristine_category_or_identity_authority(tmp_path, monkeypatch):
    """The old filtered-input failure is reproduced without putting production raw data into tests."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    native = raw / "envo.json"
    data = json.loads(native.read_text())
    graph = data["graphs"][0]
    retired = {node["id"] for node in graph["nodes"] if node.get("meta", {}).get("deprecated")}
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] not in retired]
    graph["edges"] = [edge for edge in graph["edges"] if edge["sub"] not in retired and edge["obj"] not in retired]
    native.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="native bytes changed"):
        finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for("ENVO:01001254")
    with pytest.raises(ValueError, match="native retired CLASS declaration"):
        identity_decisions(native)


def test_pristine_evidence_survives_real_finalization_repeat_and_admission(tmp_path, monkeypatch):
    """Category normalization changes neither native retirement evidence nor any source edge."""
    producer, _ = source(tmp_path, monkeypatch, "infores:other-importer")
    native = producer.input_base_dir / "envo.json"
    before_native = native.read_bytes()
    before_edges = list(graph_rows(producer.output_edge_file))
    decisions = identity_decisions(native)
    report = producer.finalize()
    assert report["consumed_inputs"]["category_authority_envo"]["sha256"] == finite.digest(before_native)
    assert native.read_bytes() == before_native
    assert identity_decisions(native) == decisions
    assert list(graph_rows(producer.output_edge_file)) == before_edges
    nodes = list(graph_rows(producer.output_node_file))
    assert {row["id"]: row["category"] for row in nodes if row["id"] in finite.FINITE_IDS} == {
        identifier: policy["category"] for identifier, policy in POLICY["records"].items()
    }
    members = [producer.output_node_file, producer.output_edge_file]
    prior_output = [path.read_bytes() for path in members]
    verify_finalized_source_files(members)
    Transform("fixture", producer.input_base_dir, producer.output_base_dir).finalize()
    verify_finalized_source_files(members)
    assert [path.read_bytes() for path in members] == prior_output
    assert native.read_bytes() == before_native


def test_real_preprocessing_filters_only_private_copy_and_cannot_emit_obsolete_side_branch(tmp_path, monkeypatch):
    """Exercise the producer's preprocessing boundary; KGX serialization is inspected, not simulated as a full run."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    transform = ontologies.OntologiesTransform(raw, tmp_path / "transformed")
    prepare_empty_native_ro_contract(transform)
    native = raw / "envo.json"
    original = native.read_bytes()
    graph = json.loads(original)["graphs"][0]
    observed = []

    def inspect_kgx(**kwargs):
        """Capture the private conversion input without running another KGX transform."""
        path = Path(kwargs["inputs"][0])
        observed.append((path, json.loads(path.read_text())["graphs"][0]))

    monkeypatch.setattr(ontologies, "_run_kgx_transform", inspect_kgx)
    monkeypatch.setattr(transform, "post_process", lambda _name: None)
    transform.parse("envo", native, "envo")
    assert native.read_bytes() == original
    assert len(observed) == 1
    derived, projected = observed[0]
    assert derived.is_relative_to(transform.output_dir) and derived != native
    retired = {node["id"] for node in graph["nodes"] if node.get("meta", {}).get("deprecated")}
    assert len(retired) == 11
    assert projected["nodes"] == [node for node in graph["nodes"] if node["id"] not in retired]
    assert projected["edges"] == [
        edge for edge in graph["edges"] if edge["sub"] not in retired and edge["obj"] not in retired
    ]
    assert len(graph["edges"]) - len(projected["edges"]) == 1
    assert not any(edge["obj"].endswith(("OBI_0000011", "COB_0000035")) for edge in projected["edges"])
    assert set(identity_decisions(native)) == REVIEWED_ENVO_IDS
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    assert authority.evidence_for("ENVO:01001254").category == "biolink:EnvironmentalProcess"
    transform.verify_consumed_inputs()
