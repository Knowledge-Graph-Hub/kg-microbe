"""Offline controls for retained UPA/Rhea candidate review evidence."""

import copy
import json

import pytest

from kg_microbe.transform_utils.rhea_mappings import legacy_xrefs
from scripts.adhoc import kgm_robot_rhea_review_20261105 as review
from tests.test_rhea_legacy_xrefs import _prepare


def test_record_comparison_preserves_duplicate_occurrences():
    """Order-independent comparison still exposes a lost repeated native assertion."""
    record = {"sub": "a", "pred": "b", "obj": "c"}
    delta = review.multiset_delta([record, record], [record])
    assert delta == {"removed": [{"record": record, "count": 1}], "added": []}


def test_upa_projection_exposes_top_level_and_annotation_order():
    """Serialization order changes stay visible separately from keyed record identity."""
    first = {"id": "one", "meta": {"xrefs": [{"val": "GO:1"}, {"val": "GO:2"}]}}
    second = {"id": "two"}
    before = review.native_upa_projection({"graphs": [{"nodes": [first, second], "edges": []}]})
    after = review.native_upa_projection({"graphs": [{"nodes": [second, first], "edges": []}]})
    assert before["nodes"] == after["nodes"]
    assert before["node_order"] != after["node_order"]
    reversed_annotations = copy.deepcopy(first)
    reversed_annotations["meta"]["xrefs"].reverse()
    assert review.mapping_delta({"one": first}, {"one": reversed_annotations})
    with pytest.raises(ValueError, match="Duplicate UPA node"):
        review.native_upa_projection({"graphs": [{"nodes": [first, first], "edges": []}]})


def test_complete_six_and_seven_native_context_passes(tmp_path):
    """Existing immutable RDF witnesses satisfy every finite selected-context check."""
    _, _, _, native, policy = _prepare(tmp_path)
    result = review.precheck_legacy(policy, native)
    assert result["passed"]
    assert len(result["exclusions"]) == 6
    assert len(result["directional_annotations"]) == 7


def test_restored_exclusion_blocks_provisional_policy(tmp_path):
    """A changed native assertion cannot be hidden by a candidate digest binding."""
    transform, _, _, native, policy = _prepare(tmp_path)
    native = copy.deepcopy(native)
    row = policy["exclusions"][0]
    record = native.reactions[row["subject"]]
    predicate = row["native_predicate"]
    restored = legacy_xrefs._target(row["original_object"], predicate)
    record[predicate] = (*record.get(predicate, ()), restored)
    result = review.precheck_legacy(policy, native)
    assert not result["passed"]
    assert any("restored" in error for item in result["exclusions"] for error in item["errors"])
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    actual = review.file_identity(transform.consumed_input_snapshots["rhea_rdf"]["path"])
    with pytest.raises(ValueError, match="no candidate policy"):
        review.consumed_legacy_audit(transform, policy, actual, native, evidence)
    assert list(evidence.iterdir()) == []


def test_real_consumed_legacy_gate_preserves_history_and_go_evidence(tmp_path):
    """Use actual immutable RDF consumption and the production legacy audit reader."""
    transform, _, _, native, policy = _prepare(tmp_path)
    before = copy.deepcopy(policy)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    actual = review.file_identity(transform.consumed_input_snapshots["rhea_rdf"]["path"])
    result = review.consumed_legacy_audit(transform, policy, actual, native, evidence)
    assert result["passed"] and result["rows"] == 6
    assert policy == before
    candidate = json.loads((evidence / "PROVISIONAL-rhea-legacy-policy.json").read_text())
    assert candidate["historical_snapshot"] == policy["historical_snapshot"]
    assert candidate["legacy_sources"] == policy["legacy_sources"]
    assert candidate["exclusions"] == policy["exclusions"]
    assert candidate["selected_snapshot"]["rdf"]["sha256"] == actual["sha256"]
    assert legacy_xrefs.INPUT_ROLE in transform.consumed_input_snapshots
    rows = json.loads((evidence / "consumed143-legacy-audit.json").read_text())
    normalized = next(row for row in rows if row["subject"] == "RHEA:19441")
    assert normalized["original_object"] == "GO:0018581"
    assert normalized["legacy_normalized_object"] == "GO:0047074"
    assert json.loads(normalized["normalization_evidence"]) == next(
        row["normalization_evidence"] for row in policy["exclusions"] if row["subject"] == "RHEA:19441"
    )
    assert not result["historical_explanations_revalidated"]
