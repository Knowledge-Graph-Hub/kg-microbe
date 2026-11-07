"""Offline source proof controls for complete ROBOT annotation occurrence evidence."""

import copy
import json
from pathlib import Path

import pytest

from scripts.adhoc import kgm_robot_annotation_review_20261105 as proof

FIXTURE = Path(__file__).parent / "resources/robot_annotation_review_20261105"


def documents():
    """Read immutable synthetic control documents, never raw production files."""
    return tuple(json.loads((FIXTURE / name).read_text()) for name in ("original.json", "candidate.json"))


def test_four_annotation_locations_and_existing_source_facts_are_exact():
    """Retain repeated occurrences and source-verified old xrefs/type alongside new facts."""
    original, candidate = documents()
    before = copy.deepcopy((original, candidate))
    result = proof.assess_added_annotation_metadata(original, candidate, FIXTURE / "source.owl")
    assert (original, candidate) == before
    assert result["only_added_annotation_metadata"]
    assert result["all_added_annotations_exactly_present_in_pinned_owl"]
    assert result["added_metadata_occurrences"] == 5
    assert result["verified_additions_by_location"] == {
        "definition": 1,
        "synonyms": 1,
        "xrefs": 2,
        "basicPropertyValues": 1,
    }
    assert not result["source_annotation_mismatches"]
    assert not result["unsupported_changes"]


@pytest.mark.parametrize("damage", ["source", "property", "target", "metadata", "shape", "existing_xref"])
def test_source_property_target_and_complete_annotation_identity_are_required(damage):
    """Matching annotation text alone cannot hide a different subject, property, target or preserved fact."""
    original, candidate = documents()
    old_node, new_node = original["graphs"][0]["nodes"][0], candidate["graphs"][0]["nodes"][0]
    if damage == "source":
        old_node["id"] = new_node["id"] = "http://example.test/Different"
    elif damage == "property":
        for node in (old_node, new_node):
            node["meta"]["basicPropertyValues"][0]["pred"] = "http://example.test/different"
    elif damage == "target":
        for node in (old_node, new_node):
            node["meta"]["definition"]["val"] = "Different target"
    elif damage == "existing_xref":
        for node in (old_node, new_node):
            node["meta"]["definition"]["xrefs"] = ["PMID:wrong"]
    elif damage == "shape":
        new_node["meta"]["definition"]["meta"] = {"unsupported": []}
    else:
        new_node["meta"]["definition"]["meta"]["basicPropertyValues"][0]["val"] = "Invented source"
    result = proof.assess_added_annotation_metadata(original, candidate, FIXTURE / "source.owl")
    assert not result["only_added_annotation_metadata"]
    assert not result["all_added_annotations_exactly_present_in_pinned_owl"]
    assert result["unsupported_changes"]


@pytest.mark.parametrize("damage", ["node_order", "xref_occurrence", "edge", "unrelated_label"])
def test_verified_annotation_additions_do_not_waive_other_document_changes(damage):
    """The proof never sorts, collapses multiplicity or removes unrelated changed fields."""
    original, candidate = documents()
    graph = candidate["graphs"][0]
    if damage == "node_order":
        graph["nodes"].reverse()
    elif damage == "xref_occurrence":
        graph["nodes"][0]["meta"]["xrefs"].pop()
    elif damage == "edge":
        graph["edges"].append({"sub": "a", "pred": "b", "obj": "c"})
    else:
        graph["nodes"][0]["lbl"] = "New unrelated label"
    result = proof.assess_added_annotation_metadata(original, candidate, FIXTURE / "source.owl")
    assert not result["removing_only_verified_additions_recovers_exact_original_document"]
    assert result["unsupported_changes"]


def test_anonymous_source_axioms_are_retained_but_cannot_prove_named_annotations():
    """Unrelated anonymous OWL expressions are scoped explicitly, never coerced into named assertion keys."""
    original, candidate = documents()
    result = proof.assess_added_annotation_metadata(original, candidate, FIXTURE / "anonymous-source.owl")
    assert result["only_added_annotation_metadata"]
    assert result["all_added_annotations_exactly_present_in_pinned_owl"]
    assert result["owl_axioms_inspected"] == 5
    assert len(result["out_of_scope_source_axioms"]) == 1
    ignored = result["out_of_scope_source_axioms"][0]
    assert ignored["axiom_ordinal_one_based"] == 5
    assert "intersectionOf" in ignored["xml_serialization"]
    assert "Anonymous-only evidence" in ignored["xml_serialization"]
    record = candidate["graphs"][0]["nodes"][0]["meta"]["basicPropertyValues"][0]
    record["meta"]["basicPropertyValues"][0]["val"] = "Anonymous-only evidence"
    result = proof.assess_added_annotation_metadata(original, candidate, FIXTURE / "anonymous-source.owl")
    assert not result["all_added_annotations_exactly_present_in_pinned_owl"]
    assert not result["only_added_annotation_metadata"]
