"""Offline controls for non-UPA ROBOT source evidence and bounded diagnostic projections."""

import copy
from types import SimpleNamespace

import pytest

from scripts.adhoc import kgm_robot_binding_review_20261105 as review


def write_owl(tmp_path, body):
    """Write local RDF/XML without ontology imports or external entity resolution."""
    path = tmp_path / "source.owl"
    path.write_text(
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">'
        + body
        + "</rdf:RDF>"
    )
    return path


def test_named_restriction_source_witness_resolves_forward_reference(tmp_path):
    """Source annotation reification must not hide a real named restriction witness."""
    path = write_owl(
        tmp_path,
        '<owl:Class rdf:about="urn:class"><rdfs:subClassOf rdf:nodeID="r"/></owl:Class>'
        '<owl:Restriction rdf:nodeID="r"><owl:onProperty rdf:resource="urn:relation"/>'
        '<owl:someValuesFrom rdf:resource="urn:target"/></owl:Restriction>',
    )
    assert review.owl_index(path, {"urn:class"})["urn:class"]["restrictions"] == {("urn:relation", "urn:target")}


def test_named_restriction_duplicate_is_not_silently_overwritten(tmp_path):
    """Ambiguous native restrictions cannot be accepted through dictionary overwrite."""
    restriction = (
        '<owl:Restriction rdf:nodeID="r"><owl:onProperty rdf:resource="urn:relation"/>'
        '<owl:someValuesFrom rdf:resource="urn:target"/></owl:Restriction>'
    )
    path = write_owl(tmp_path, restriction + restriction)
    with pytest.raises(ValueError, match="Duplicate named OWL restriction"):
        review.owl_index(path, set())


def test_source_deprecation_can_be_an_rdf_description(tmp_path):
    """Retired annotation-only IDs retain their explicit source deprecation fact."""
    path = write_owl(
        tmp_path, '<rdf:Description rdf:about="urn:obsolete"><owl:deprecated>true</owl:deprecated></rdf:Description>'
    )
    assert review.owl_index(path, {"urn:obsolete"})["urn:obsolete"]["deprecated"] == {"true"}


@pytest.mark.parametrize("unreviewed_parent", [False, True])
def test_finite_complete_ancestry_rejects_additional_source_parent(tmp_path, unreviewed_parent):
    """Supporting ancestry is the complete source closure, not a convenient subset."""
    parent = '<rdfs:subClassOf rdf:resource="urn:extra"/>' if unreviewed_parent else ""
    path = write_owl(
        tmp_path,
        '<owl:Class rdf:about="urn:class"><rdfs:label>class</rdfs:label>'
        '<rdfs:subClassOf rdf:resource="urn:root"/>' + parent + "</owl:Class>"
        '<owl:Class rdf:about="urn:root"/>',
    )
    policy = {"records": {"x": {"authority_file": "x.json", "native_iri": "urn:class", "native_label": "class"}}}
    decisions = {"x": SimpleNamespace(supporting_axioms=(("urn:class", "is_a", "urn:root"),))}
    if unreviewed_parent:
        with pytest.raises(ValueError, match="named-parent evidence differs"):
            review.verify_finite_owl(path, policy, "x.json", decisions)
    else:
        assert review.verify_finite_owl(path, policy, "x.json", decisions)["complete_named_parent_axioms"] == 1


def annotation_case():
    """Model one exact source-backed addition with a separately unrepresented source annotation."""
    original = {
        "graphs": [
            {
                "nodes": [
                    {
                        "id": "urn:class",
                        "meta": {"basicPropertyValues": [{"pred": "urn:depiction", "val": "urn:image"}]},
                    }
                ]
            }
        ]
    }
    candidate = copy.deepcopy(original)
    metadata = {"basicPropertyValues": [{"pred": "urn:license", "val": "urn:license-value"}]}
    candidate["graphs"][0]["nodes"][0]["meta"]["basicPropertyValues"][0]["meta"] = metadata
    proof = {
        "only_added_annotation_metadata": False,
        "complete_added_annotation_evidence": [
            {
                "graph_position": 0,
                "node_position": 0,
                "node": "urn:class",
                "property_path": ["meta", "basicPropertyValues", 0],
                "annotated_property": "urn:depiction",
                "annotated_target": "urn:image",
                "candidate_annotation": metadata,
                "source_owl_annotations": [["urn:license", "urn:license-value"], ["urn:xref", "urn:doi"]],
                "existing_serialized_annotation_facts": [],
                "source_owl_annotation_details": [],
            }
        ],
    }
    return original, candidate, proof


def test_source_backed_addition_does_not_waive_complete_source_omission():
    """Source-supported new facts do not silently excuse historically omitted facts."""
    original, candidate, proof = annotation_case()
    preserved = copy.deepcopy(candidate)
    report = review.annotation_completeness_assessment(original, candidate, proof)
    assert report["all_added_values_source_backed"] is True
    assert report["removing_only_source_backed_additions_recovers_prepared_original"] is True
    assert report["complete_source_annotation_equality"] is False
    gap = report["explicit_source_completeness_exceptions"][0]
    assert gap["source_annotations_still_unserialized_in_candidate"] == [("urn:xref", "urn:doi")]
    assert gap["source_annotations_newly_lost"] == []
    assert report["exceptions_approved"] is False
    assert report["release_ready"] is False
    assert candidate == preserved


def test_unbacked_addition_is_not_removed_by_diagnostic_projection():
    """An invented annotation remains visible and prevents the equivalence proof."""
    original, candidate, proof = annotation_case()
    proof["complete_added_annotation_evidence"][0]["source_owl_annotations"] = [["urn:xref", "urn:doi"]]
    report = review.annotation_completeness_assessment(original, candidate, proof)
    assert report["all_added_values_source_backed"] is False
    assert report["removing_only_source_backed_additions_recovers_prepared_original"] is False


def test_changed_existing_value_is_not_treated_as_added_metadata():
    """An old assertion value cannot be changed under an annotation-only explanation."""
    original, candidate, proof = annotation_case()
    candidate["graphs"][0]["nodes"][0]["meta"]["basicPropertyValues"][0]["val"] = "urn:other-image"
    report = review.annotation_completeness_assessment(original, candidate, proof)
    assert report["all_added_values_source_backed"] is False
    assert report["removing_only_source_backed_additions_recovers_prepared_original"] is False


def test_save_preserves_prior_evidence(tmp_path):
    """A failed or completed earlier receipt must never be overwritten."""
    path = tmp_path / "evidence.json"
    review.save(path, {"first": True})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        review.save(path, {"first": False})
    assert path.read_bytes() == original


def test_changed_candidate_metadata_cannot_reuse_earlier_annotation_proof():
    """A valid source proof applies only to the exact annotation occurrence it measured."""
    original, candidate, proof = annotation_case()
    candidate = copy.deepcopy(candidate)
    candidate["graphs"][0]["nodes"][0]["meta"]["basicPropertyValues"][0]["meta"]["basicPropertyValues"][0]["val"] = (
        "invented"
    )
    report = review.annotation_completeness_assessment(original, candidate, proof)
    assert report["all_added_values_source_backed"] is False
    assert report["removing_only_source_backed_additions_recovers_prepared_original"] is False
