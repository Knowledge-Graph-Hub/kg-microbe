"""Pinned native FOODON branches, including genuine unresolved counterexamples."""

import json
from pathlib import Path

import pytest

from kg_microbe.utils import foodon_classification as policy

FIXTURE = Path(__file__).parent / "resources" / "foodon_category_ancestry.json"


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("FOODON:03430105", "biolink:PhenotypicQuality"),
        ("FOODON:03430106", "biolink:PhenotypicQuality"),
        ("FOODON:03440022", "biolink:PhenotypicQuality"),
        ("FOODON:00002407", "biolink:PhenotypicQuality"),
        ("FOODON:03460190", "biolink:Activity"),
        ("FOODON:03450002", "biolink:Activity"),
        ("FOODON:00001304", "biolink:Activity"),
        ("FOODON:00003203", "biolink:Activity"),
        ("FOODON:00004038", "biolink:Activity"),
        ("FOODON:03510198", "biolink:InformationContentEntity"),
        ("FOODON:03307083", "biolink:Food"),
        ("FOODON:00001258", "biolink:Food"),
        ("FOODON:03304737", "biolink:Food"),
        ("FOODON:00001155", "biolink:OrganismTaxon"),
        ("FOODON:00003673", "biolink:Food"),
        ("FOODON:03411744", "biolink:OrganismTaxon"),
    ],
)
def test_native_asserted_category(identifier, expected):
    """Processing/quality labels alone cannot classify products, parts, or claims."""
    assert policy.authoritative_foodon_category(identifier, path=FIXTURE) == expected


def test_snapshot_policy_ignores_restrictions_and_keeps_unknown_food_fallback():
    """Only the asserted subclass closure may determine a category."""
    graphs = json.loads(FIXTURE.read_text())["graphs"]
    graphs[0]["nodes"].append({"id": "FOODON:unknown", "type": "CLASS"})
    graphs[0]["edges"].extend(
        [
            {"sub": "FOODON:unknown", "pred": "RO:0000086", "obj": "PATO:0000001"},
            {"sub": "FOODON:unknown", "pred": "RO:0002353", "obj": "BFO:0000015"},
            {"sub": "FOODON:unknown", "pred": "RO:0002162", "obj": "PO:0000003"},
        ]
    )
    categories = policy.foodon_categories(graphs)
    assert policy.authoritative_foodon_category("FOODON:unknown", categories=categories) == "biolink:Food"
    assert policy.authoritative_foodon_category("FOODON:00004038", categories=categories) == "biolink:Activity"


def test_conflicting_asserted_branches_abort_instead_of_picking_a_category():
    """An authority contradiction cannot silently select the first root."""
    graphs = [
        {
            "nodes": [
                {"id": identifier, "type": "CLASS"} for identifier in ("FOODON:conflict", "PATO:0000001", "BFO:0000015")
            ],
            "edges": [
                {"sub": "FOODON:conflict", "pred": "is_a", "obj": "PATO:0000001"},
                {"sub": "FOODON:conflict", "pred": "is_a", "obj": "BFO:0000015"},
            ],
        }
    ]
    with pytest.raises(ValueError, match="Conflicting FOODON"):
        policy.foodon_categories(graphs)


def test_subclass_cycles_terminate_and_full_iri_predicates_are_supported():
    """Cyclic assertions and equivalent predicate representations are deterministic."""
    graphs = [
        {
            "nodes": [{"id": identifier, "type": "CLASS"} for identifier in ("FOODON:a", "FOODON:b", "BFO:0000015")],
            "edges": [
                {"sub": "FOODON:a", "pred": "http://www.w3.org/2000/01/rdf-schema#subClassOf", "obj": "BFO:0000015"},
                {"sub": "FOODON:b", "pred": "is_a", "obj": "FOODON:a"},
                {"sub": "FOODON:a", "pred": "is_a", "obj": "FOODON:b"},
            ],
        }
    ]
    assert policy.foodon_categories(graphs)["FOODON:b"] == "biolink:Activity"


@pytest.mark.parametrize("kind,deprecated", [("CLASS", True), ("PROPERTY", False), ("INDIVIDUAL", False)])
def test_declared_invalid_unconnected_node_is_never_silently_food(kind, deprecated):
    """Removing invalid ancestry must not create a new material fallback decision."""
    graphs = [{"nodes": [{"id": "FOODON:invalid", "type": kind, "meta": {"deprecated": deprecated}}]}]
    categories = policy.foodon_categories(graphs, dispositions={})
    assert "FOODON:invalid" not in categories
    with pytest.raises(ValueError, match="No live FOODON CLASS"):
        policy.authoritative_foodon_category("FOODON:invalid", categories=categories)


def test_missing_declaration_and_invalid_curated_organism_are_not_authority():
    """Curation cannot revive a retired node, and an unknown ID cannot default to Food."""
    graphs = [{"nodes": [{"id": "FOODON:03411744", "type": "CLASS", "meta": {"deprecated": True}}]}]
    categories = policy.foodon_categories(graphs)
    for identifier in ("FOODON:03411744", "FOODON:undeclared"):
        with pytest.raises(ValueError, match="No live FOODON CLASS"):
            policy.authoritative_foodon_category(identifier, categories=categories)


@pytest.mark.parametrize("change", [{"type": "PROPERTY"}, {"meta": {"deprecated": True}}])
def test_contradictory_native_declarations_abort(change):
    """Duplicate declarations cannot silently override class kind or obsolete status."""
    nodes = [{"id": "FOODON:conflict", "type": "CLASS"}]
    nodes.append({**nodes[0], **change})
    with pytest.raises(ValueError, match="Conflicting FOODON declarations"):
        policy.foodon_categories([{"nodes": nodes}])


@pytest.mark.parametrize("corruption", ["missing", "PROPERTY", "INDIVIDUAL", "obsolete"])
def test_invalid_intermediate_cannot_bridge_native_activity_ancestry(corruption):
    """Live endpoints and roots do not excuse an invalid intermediate class."""
    from kg_microbe.utils.graph_canonicalization import compact_identifier

    graphs = json.loads(FIXTURE.read_text())["graphs"]
    node = next(node for node in graphs[0]["nodes"] if compact_identifier(node["id"]) == "FOODON:03460130")
    if corruption == "missing":
        graphs[0]["nodes"].remove(node)
    elif corruption == "obsolete":
        node["meta"] = {"deprecated": True}
    else:
        node["type"] = corruption
    with pytest.raises(ValueError, match="Invalid FOODON subclass evidence"):
        policy.foodon_categories(graphs)
