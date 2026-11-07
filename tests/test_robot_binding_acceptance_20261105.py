"""Offline controls for exact current-policy acceptance and narrow source-omission disposition."""

import copy
import json

import pytest

from scripts.adhoc import kgm_robot_binding_acceptance_20261105 as acceptance


def disposition():
    """Construct the sole explicitly reviewed source-omission shape, without ontology inputs."""
    exception = {
        "node": acceptance.EXPECTED_NODE,
        "annotated_property": acceptance.EXPECTED_PROPERTY,
        "annotated_target": acceptance.EXPECTED_TARGET,
        "source_annotations_still_unserialized_in_candidate": copy.deepcopy(acceptance.EXPECTED_MISSING),
        "source_annotations_newly_lost": [],
        "all_added_values_source_backed": True,
    }
    value = {
        "issue": 1737,
        "status": "recorded_preexisting_omission",
        "review5_sha256": "review-hash",
        "review5_inputs_sha256": "inputs-hash",
        "source_owl_sha256": "owl-hash",
        "exception": exception,
        "all_added_annotation_values_source_backed": True,
        "complete_source_annotation_equality": False,
        "unchanged_omission_acknowledged": True,
        "release_ready": False,
    }
    return exception, value


def test_exact_disposition_keeps_complete_source_equality_false():
    """An acknowledged existing omission is accepted only with explicit limited meaning."""
    exception, value = disposition()
    acceptance.validate_disposition(value, exception, "review-hash", "owl-hash", "inputs-hash")
    assert value["complete_source_annotation_equality"] is False
    assert value["release_ready"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete_source_annotation_equality", True),
        ("review5_inputs_sha256", "other-inputs"),
        ("source_owl_sha256", "other-source"),
        ("unchanged_omission_acknowledged", False),
    ],
)
def test_disposition_cannot_change_scope_source_or_completeness(field, value):
    """A stale source receipt or broader approval cannot stand in for the exact issue disposition."""
    exception, record = disposition()
    record[field] = value
    with pytest.raises(ValueError, match="Missing or mismatched"):
        acceptance.validate_disposition(record, exception, "review-hash", "owl-hash", "inputs-hash")


def test_different_missing_annotation_cannot_reuse_known_exception():
    """Newly omitted assertions must not inherit the single existing DOI disposition."""
    exception, value = disposition()
    exception["source_annotations_still_unserialized_in_candidate"].append(["urn:other", "new-missing-fact"])
    with pytest.raises(ValueError, match="Unexpected source completeness exception"):
        acceptance.validate_disposition(value, exception, "review-hash", "owl-hash", "inputs-hash")


def test_publish_is_exclusive_for_existing_artifact_and_dangling_link(tmp_path):
    """Interrupted or earlier evidence cannot be silently replaced by a new success artifact."""
    output = tmp_path / "artifact.json"
    acceptance.publish(output, {"complete_source_annotation_equality": False})
    assert json.loads(output.read_text()) == {"complete_source_annotation_equality": False}
    before = output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        acceptance.publish(output, {"complete_source_annotation_equality": True})
    assert output.read_bytes() == before
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="already exists"):
        acceptance.publish(dangling, {"status": "passed"})
    assert dangling.is_symlink()


def policy_pair():
    """Use small policy-shaped records to isolate the allowed metadata/guard delta."""
    original = {
        "ontology_parent_dispositions.json": {
            "reviewed_model": {"version": "4.4.2"},
            "sources": {
                "foodon": {
                    "json_context": {"nodes": []},
                    "json_context_sha256": "old",
                    "quarantines": [{"subject": "x", "parent": "y"}],
                }
            },
        },
        "foodon_anatomical_category_dispositions.json": {
            "category": "biolink:GrossAnatomicalStructure",
            "native_evidence": {"parent_policy_canonical_sha256": "old"},
        },
        "finite_import_category_dispositions.json": {"unchanged": True},
    }
    current = copy.deepcopy(original)
    current["ontology_parent_dispositions.json"]["sources"]["foodon"].update(
        {"json_context": {"nodes": [{"id": "x"}]}, "json_context_sha256": "new", "conversion_review_20261105": {}}
    )
    current["foodon_anatomical_category_dispositions.json"]["native_evidence"]["parent_policy_canonical_sha256"] = "new"
    return original, current


def test_approved_metadata_binding_delta_preserves_other_fields():
    """The declared conversion binding and seal may change without changing scientific decisions."""
    original, current = policy_pair()
    acceptance.validate_policy_delta(original, current)


@pytest.mark.parametrize("change", ["parent", "model", "category", "unrelated_policy"])
def test_binding_update_cannot_change_scientific_or_historical_fields(change):
    """Updating metadata hashes cannot authorize new hierarchy, category, or attribution decisions."""
    original, current = policy_pair()
    if change == "parent":
        current["ontology_parent_dispositions.json"]["sources"]["foodon"]["quarantines"][0]["parent"] = "other"
    elif change == "model":
        current["ontology_parent_dispositions.json"]["reviewed_model"]["version"] = "4.4.6"
    elif change == "category":
        current["foodon_anatomical_category_dispositions.json"]["category"] = "biolink:OrganismTaxon"
    else:
        current["finite_import_category_dispositions.json"]["unchanged"] = False
    with pytest.raises(ValueError):
        acceptance.validate_policy_delta(original, current)


def test_current_foodon_comparison_projects_only_baseline_and_preserves_actual_gate_input(monkeypatch, tmp_path):
    """A retained obsolete edge must not falsely fail the comparison or vanish from the real policy input."""
    candidate = {
        "graphs": [
            {
                "nodes": [
                    {"id": "live", "type": "CLASS"},
                    {"id": "retired", "meta": {"deprecated": True}},
                    {"id": "root", "type": "CLASS"},
                ],
                "edges": [
                    {"sub": "live", "pred": "is_a", "obj": "root"},
                    {"sub": "retired", "pred": "is_a", "obj": "root"},
                    {"sub": "live", "pred": "is_a", "obj": "retired"},
                ],
            }
        ]
    }
    preserved = copy.deepcopy(candidate)
    captured = {}

    def gate(policies, baseline, pristine, source):
        """Capture the representation boundaries, not a substituted scientific verdict."""
        captured.update(policies=policies, baseline=baseline, pristine=pristine, source=source)
        return "gate-result"

    monkeypatch.setattr(acceptance.review, "review_foodon", gate)
    source = tmp_path / "source.owl"
    assert acceptance.current_foodon_evidence({"policy": "unchanged"}, candidate, source) == "gate-result"
    assert captured["pristine"] is candidate
    assert candidate == preserved
    assert captured["baseline"]["graphs"][0]["edges"] == candidate["graphs"][0]["edges"][:1]
    assert [node["id"] for node in captured["baseline"]["graphs"][0]["nodes"]] == ["live", "root"]
