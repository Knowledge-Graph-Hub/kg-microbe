"""Report reviewed material context without granting chemical identity or changing graphs."""

import pytest

from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS
from kg_microbe.transform_utils.microbedecoder.material_dispositions import MaterialDispositionCuration
from tests.test_microbedecoder_curation_inventory import AUTHORITY, inventory, write_tsv


def _source(tmp_path, rules):
    """Project the immutable catalogue's graph witnesses into a small diagnostic fixture."""
    source = tmp_path / "source"
    source.mkdir()
    edges = [
        {
            "subject": rule.subject,
            "object": rule.object_curie,
            "source_record": rule.source_record,
            "source_column": rule.source_column,
            "value": rule.source_literal,
            "source_citation": rule.source_citation,
            "predicate": rule.predicate,
            "relation": rule.relation,
            "primary_knowledge_source": rule.primary_knowledge_source,
            "knowledge_level": rule.knowledge_level,
            "agent_type": rule.agent_type,
            "value_encoding": rule.value_encoding,
        }
        for rule in rules
    ]
    write_tsv(source / "edges.tsv", list(edges[0]), edges)
    write_tsv(
        source / "nodes.tsv",
        ["id", "category"],
        [{"id": curie, "category": "biolink:ChemicalEntity"} for curie in sorted({r.object_curie for r in rules})],
    )
    return source, edges


def test_complete_material_inventory_keeps_unresolved_identity_and_all_original_bytes(tmp_path):
    """All 240 uses are reviewed as context, never reported as approved ontology identities."""
    source, _ = _source(tmp_path, MaterialDispositionCuration().rules)
    before = {name: (source / name).read_bytes() for name in ("nodes.tsv", "edges.tsv")}
    result = inventory.review(
        source, tmp_path / "review", DEFAULT_PROCESS_MAPPINGS, AUTHORITY, require_reviewed_material_cohort=True
    )
    assert result["material_review"]["matched_source_uses"] == 240
    assert result["material_review"]["cohort_complete"] is True
    assert result["material_review"]["chemical_identity_approved"] is False
    assert result["material_review"]["raw_record_validation"] is None
    assert sum(result["material_review"]["edge_rows_by_disposition"].values()) == 240
    assert result["edge_rows_by_disposition"] == {"retained_local_material": 240}
    assert {name: (source / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("mutation", ["drop", "literal", "record", "citation", "target", "duplicate"])
def test_explicit_cohort_acceptance_rejects_lost_or_changed_uses(tmp_path, mutation):
    """A strict rebuild check cannot pass by losing a record or changing the catalogue lookup key."""
    source, edges = _source(tmp_path, MaterialDispositionCuration().rules)
    fields = list(edges[0])
    if mutation == "drop":
        edges.pop()
    elif mutation == "duplicate":
        edges.append(dict(edges[0]))
    else:
        field = {"literal": "value", "record": "source_record", "citation": "source_citation", "target": "object"}[
            mutation
        ]
        edges[0][field] = "changed"
    write_tsv(source / "edges.tsv", fields, edges)
    with pytest.raises(ValueError):
        inventory.review(
            source, tmp_path / "review", DEFAULT_PROCESS_MAPPINGS, AUTHORITY, require_reviewed_material_cohort=True
        )
    assert not (tmp_path / "review").exists()


def test_partial_diagnostic_does_not_claim_complete_cohort(tmp_path):
    """Non-production fixture or subset reviews can run without pretending all uses survived."""
    source, _ = _source(tmp_path, MaterialDispositionCuration().rules[:1])
    result = inventory.review(source, tmp_path / "review", DEFAULT_PROCESS_MAPPINGS, AUTHORITY)
    assert result["material_review"]["matched_source_uses"] == 1
    assert result["material_review"]["missing_reviewed_uses"] == 239
    assert result["material_review"]["cohort_complete"] is False
