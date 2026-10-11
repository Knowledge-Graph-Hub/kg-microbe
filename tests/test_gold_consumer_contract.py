"""Finite GOLD consumers retain member scope and cannot disguise identity in relation (#1331/#1332)."""

import pytest

from kg_microbe.transform_utils.gold.taxon_dispositions import load_gold_declarations
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_gold_taxon_dispositions import _write
from tests.test_microbedecoder_gold_dispositions import native_dispatch as native_dispatch


@pytest.mark.parametrize(
    "relation",
    [
        "owl:sameAs",
        "skos:exactMatch",
        "rdfs:subClassOf",
        "biolink:close_match",
        "http://www.w3.org/2002/07/owl#sameAs",
        "https://www.w3.org/2002/07/owl#sameAs",
        "http://www.w3.org/2004/02/skos/core#exactMatch",
        "https://www.w3.org/2004/02/skos/core#exactMatch",
        "http://www.w3.org/2000/01/rdf-schema#subClassOf",
        "https://www.w3.org/2000/01/rdf-schema#subClassOf",
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("field", ["predicate", "relation"])
def test_imported_identity_strength_is_rejected_in_either_field(native_dispatch, relation, reverse, field):
    """Use actual admitted native declarations; only the invalid claim is a synthetic perturbation."""
    consumer, evidence = native_dispatch
    guard = consumer._gold_crosswalk_declarations
    target = evidence["selected"]
    declaration = guard.declaration_for(target).declaration
    nodes, edges = consumer.output_node_file, consumer.output_edge_file
    _write(nodes, declaration.keys(), [declaration])
    row = {
        "subject": target if reverse else "NCBITaxon:1",
        "predicate": "biolink:related_to",
        "object": "NCBITaxon:1" if reverse else target,
        "relation": "biolink:related_to",
    }
    _write(edges, row.keys(), [row])
    guard.bind_members([nodes], [edges])
    guard.verify(output_dir=consumer.output_dir)
    row[field] = relation
    _write(edges, row.keys(), [row])
    with pytest.raises(SourceFinalizationRequired, match="unsupported identity/hierarchy"):
        guard.verify(output_dir=consumer.output_dir)


def test_new_finalization_scope_uses_new_guard_without_rebinding_old(native_dispatch):
    """An actual selected native authority can serve separate scopes with equal requests."""
    consumer, evidence = native_dispatch
    original = consumer._gold_crosswalk_declarations
    assert load_gold_declarations(consumer, {evidence["selected"]}) is original
    original.bind_members([consumer.output_dir / "first_nodes.tsv"], [consumer.output_dir / "first_edges.tsv"])
    old_contract = original.contract()
    renewed = load_gold_declarations(consumer, {evidence["selected"]})
    assert renewed is not original
    renewed.bind_members([consumer.output_dir / "second_nodes.tsv"], [consumer.output_dir / "second_edges.tsv"])
    assert original.contract() == old_contract
    original.verify(metadata_only=True)
    renewed.verify(metadata_only=True)
    with pytest.raises(SourceFinalizationRequired, match="members rebound"):
        original.bind_members([consumer.output_dir / "second_nodes.tsv"], [consumer.output_dir / "second_edges.tsv"])
    original._members = renewed._members
    with pytest.raises(SourceFinalizationRequired):
        original.admission.verify(metadata_only=True)


def test_new_finalization_must_verify_old_guard_before_replacing_it(native_dispatch):
    """New scope does not permit clearing a previous proof or immutable member inventory."""
    consumer, evidence = native_dispatch
    original = consumer._gold_crosswalk_declarations
    original.bind_members([consumer.output_node_file], [consumer.output_edge_file])
    original._members = ((), ())
    with pytest.raises(SourceFinalizationRequired):
        load_gold_declarations(consumer, {evidence["selected"]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("same_as", "NCBITaxon:1"),
        ("name", "invented specific strain"),
        ("xref", "NCBITaxon:1"),
        ("description", "claimed confirmed identity"),
        ("synonym", "invented strain alias"),
        ("deprecated", "true"),
        ("provided_by", "infores:gold|infores:unadmitted"),
        ("category", "biolink:NamedThing|biolink:OrganismTaxon"),
        ("extra_semantic_field", "identity"),
    ],
)
def test_named_native_copies_require_complete_semantic_equality(native_dispatch, field, value):
    """Named records are no weaker than blank native referents; extra provider tokens require own proof."""
    consumer, evidence = native_dispatch
    guard = consumer._gold_crosswalk_declarations
    target = evidence["selected"]
    declaration = guard.declaration_for(target).declaration
    nodes, edges = consumer.output_node_file, consumer.output_edge_file
    _write(nodes, declaration.keys(), [declaration])
    row = {
        "subject": "NCBITaxon:1",
        "predicate": "biolink:related_to",
        "object": target,
        "relation": "biolink:related_to",
    }
    _write(edges, row.keys(), [row])
    guard.bind_members([nodes], [edges])
    guard.verify(output_dir=consumer.output_dir)
    declaration[field] = value
    _write(nodes, declaration.keys(), [declaration])
    with pytest.raises(SourceFinalizationRequired):
        guard.verify(output_dir=consumer.output_dir)
