"""Prove faithful ROBOT 1.9.11 FOODON annotations without weakening finite guards."""

import copy
import json
from pathlib import Path

import pytest

from kg_microbe.utils import foodon_anatomical_categories as anatomy
from kg_microbe.utils import ontology_parent_quarantine as parent
from scripts.adhoc.kgm_robot_annotation_review_20261105 import assess_added_annotation_metadata

FIXTURE = Path(__file__).parent / "resources/ontology_parent_dispositions"


def inputs():
    """Read only retained immutable fixture evidence and code-guarded scientific policy."""
    manifest = json.loads((FIXTURE / "robot-1.9.11-reconversion.json").read_text())
    document = json.loads((FIXTURE / "foodon.json").read_text())
    with parent.POLICY_FILE.open() as stream:
        policy = parent.load_policy(stream)
    return manifest, document, policy


def test_reconverted_foodon_additions_exactly_match_unchanged_source_owl():
    """All13 additions are source annotations and every other occurrence is identical."""
    manifest, candidate, policy = inputs()
    original = copy.deepcopy(candidate)
    replacements = manifest["historical_complete_nodes"]
    assert len(replacements) == 7
    for graph in original["graphs"]:
        for index, node in enumerate(graph["nodes"]):
            if node["id"] in replacements:
                graph["nodes"][index] = replacements[node["id"]]
    proof = assess_added_annotation_metadata(original, candidate, FIXTURE / "foodon.owl")
    assert proof["added_metadata_occurrences"] == 13
    assert proof["only_added_annotation_metadata"] is True
    assert proof["all_added_annotations_exactly_present_in_pinned_owl"] is True
    assert proof["unsupported_changes"] == []
    assert proof["source_annotation_mismatches"] == []
    assert parent.json_context(candidate, policy["sources"]["foodon"]) == policy["sources"]["foodon"]["json_context"]


def test_new_source_annotation_cannot_be_stripped_then_admitted():
    """The updated full-context seal must detect removal of a newly serialized fact."""
    manifest, candidate, policy = inputs()
    selected = manifest["source_annotation_evidence"][0]
    node = next(node for graph in candidate["graphs"] for node in graph["nodes"] if node["id"] == selected["node"])
    record = node
    for component in selected["property_path"]:
        record = record[component]
    record.pop("meta")
    with pytest.raises(ValueError, match="native declarations/axioms changed"):
        parent.json_context(candidate, policy["sources"]["foodon"])


def test_reconversion_keeps_historical_model_and_exact_anatomical_decisions():
    """A serialization review does not rewrite historical model attribution or category scope."""
    _, candidate, policy = inputs()
    assert policy["reviewed_model"] == {
        "version": "4.4.2",
        "sha256": "b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e",
    }
    assert policy["sources"]["foodon"]["full_primary_json"]["sha256"] == (
        "8dfba179356a84d8ddad4087dc1fa89a76f6511456c298b9dd7b09df9eb6d853"
    )
    categories = anatomy.categories_for(candidate["graphs"])
    assert set(categories) == anatomy.FINITE_IDS
    assert len(categories) == 24
    assert set(categories.values()) == {"biolink:GrossAnatomicalStructure"}
