"""Preserve compound trophic and application scope without inventing identities."""

import json

import pytest

from kg_microbe.transform_utils.microbedecoder import faprotax_dispositions as fap
from kg_microbe.transform_utils.microbedecoder import observation_audit
from kg_microbe.transform_utils.microbedecoder.source_annotations import (
    is_reported_metabolism_annotation,
)
from tests.microbedecoder_inactive_join_fixtures import bind_inactive_join_policy, write_empty_join_gss
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


REVIEWED_TARGETS = {
    "aerobic_anoxygenic_phototrophy": "METPO:1000657",
    "aerobic_chemoheterotrophy": "METPO:1000636",
    "anoxygenic_photoautotrophy": "METPO:1000656",
    "anoxygenic_photoautotrophy_Fe_oxidizing": "METPO:1000656",
    "anoxygenic_photoautotrophy_H2_oxidizing": "METPO:1000656",
    "anoxygenic_photoautotrophy_S_oxidizing": "METPO:1000656",
    "oxygenic_photoautotrophy": "METPO:1000656",
    "methylotrophy": "METPO:1000651",
}


@pytest.mark.parametrize("literal", REVIEWED)
def test_compound_group_preserves_reviewed_prediction_or_audit_only_scope(monkeypatch, tmp_path, literal):
    """Reviewed broad types preserve full qualified literals; unsupported claims remain only in audit."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", "FAPROTAX_Type_of_metabolism": literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    write_empty_join_gss(transform.input_base_dir)
    bind_inactive_join_policy(transform, quarantine_source, monkeypatch)
    transform.run(data_file=quarantine_source)
    edges = _rows(transform.output_edge_file)
    audits = _rows(transform.output_dir / observation_audit.AUDIT_FILE)
    assert len(audits) == 1
    audit = audits[0]
    row = json.loads(audit["original_claim_json"])
    assert json.loads(audit["source_cell_json"]) == literal
    assert audit["source_record"] == row["source_record"]
    assert audit["source_column"] == row["source_column"]
    assert "/issues/1847" in audit["evidence_uri"] and "/issues/1850" in audit["evidence_uri"]
    assert audit["curation_rationale"]
    assert (row["predicate"], row["relation"]) == ("biolink:has_attribute", "SIO:000008")
    assert row["source_column"] == "FAPROTAX_Type_of_metabolism"
    assert row["value"] == literal
    assert row["source_record"].startswith("sha256:")
    assert (row["primary_knowledge_source"], row["knowledge_level"], row["agent_type"]) == (
        "infores:faprotax",
        "prediction",
        "computational_model",
    )
    nodes = {node["id"]: node for node in _rows(transform.output_node_file)}
    if literal in REVIEWED_TARGETS:
        assert edges == [row] and json.loads(audit["emitted_claim_json"]) == row
        assert audit["disposition"] == fap.PREDICTION_DISPOSITION
        node = nodes[row["object"]]
        assert node["category"] == "biolink:Attribute"
        assert node["has_attribute_type"] == REVIEWED_TARGETS[literal]
        assert node["attribute_type_evidence"] == audit["evidence_uri"]
        assert node["attribute_type_rationale"] == audit["curation_rationale"]
    else:
        assert literal in {"phototrophy", "oil_bioremediation"}
        assert not edges and row["object"] not in nodes
        assert json.loads(audit["emitted_claim_json"]) is None
        assert audit["disposition"] == fap.AUDIT_DISPOSITION
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
