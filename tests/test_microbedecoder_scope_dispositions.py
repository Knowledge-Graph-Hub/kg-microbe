"""Preserve compound trophic and application scope without inventing identities."""

import pytest

from kg_microbe.transform_utils.microbedecoder.source_annotations import (
    is_reported_metabolism_annotation,
)
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_curation_integration import _rows, _transform, _write_source

REVIEWED = (
    "aerobic_anoxygenic_phototrophy",
    "aerobic_chemoheterotrophy",
    "anoxygenic_photoautotrophy",
    "anoxygenic_photoautotrophy_Fe_oxidizing",
    "anoxygenic_photoautotrophy_H2_oxidizing",
    "anoxygenic_photoautotrophy_S_oxidizing",
    "oxygenic_photoautotrophy",
    "phototrophy",
    "methylotrophy",
    "oil_bioremediation",
)


@pytest.mark.parametrize("literal", REVIEWED)
def test_compound_group_keeps_full_literal_prediction_and_no_native_type(tmp_path, literal):
    """Changing representation is not permission to add an exact phenotype grounding."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", "FAPROTAX_Type_of_metabolism": literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    edges = _rows(transform.output_edge_file)
    assert len(edges) == 1
    row = edges[0]
    assert (row["predicate"], row["relation"]) == ("biolink:has_attribute", "SIO:000008")
    assert row["source_column"] == "FAPROTAX_Type_of_metabolism"
    assert row["value"] == literal
    assert row["source_record"].startswith("sha256:")
    assert (row["primary_knowledge_source"], row["knowledge_level"], row["agent_type"]) == (
        "infores:faprotax",
        "prediction",
        "computational_model",
    )
    node = next(node for node in _rows(transform.output_node_file) if node["id"] == row["object"])
    assert node["category"] == "biolink:Attribute"
    assert not node.get("has_attribute_type")
    assert _rows(transform.output_dir / "phenotype_normalizations.tsv") == []


@pytest.mark.parametrize("literal", REVIEWED)
def test_scope_classification_does_not_generalize_to_other_sources_or_spellings(literal):
    """Only the reviewed ten exact pairs acquire this representation disposition."""
    assert is_reported_metabolism_annotation("FAPROTAX_Type_of_metabolism", literal)
    for column in ("FAPROTAX2_Type_of_metabolism", "Bergey_Type_of_metabolism", "FAPROTAX_Substrates"):
        assert not is_reported_metabolism_annotation(column, literal)
    assert not is_reported_metabolism_annotation("FAPROTAX_Type_of_metabolism", literal + " ")
    assert not is_reported_metabolism_annotation("FAPROTAX_Type_of_metabolism", literal.upper())


@pytest.mark.parametrize("literal", ["dark_hydrogen_oxidation", "sulfate_respiration", "novel_phototrophy"])
def test_genuine_processes_and_unknown_future_groups_are_not_guessed(literal):
    """No substring, suffix, or broad trophic-word classifier is introduced."""
    assert not is_reported_metabolism_annotation("FAPROTAX_Type_of_metabolism", literal)
