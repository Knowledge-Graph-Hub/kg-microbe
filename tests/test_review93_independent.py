"""Independent declaration-validity and assembly-conservation review probes."""

import json
from pathlib import Path

import pytest

from kg_microbe.utils import foodon_classification
from kg_microbe.utils.graph_canonicalization import compact_identifier

RESOURCES = Path(__file__).parent / "resources"


@pytest.mark.parametrize("corruption", ["missing", "PROPERTY", "INDIVIDUAL", "obsolete"])
def test_foodon_invalid_endpoint_cannot_inherit_activity(corruption):
    """A raw subclass edge cannot authorize classification of an invalid endpoint."""
    graphs = json.loads((RESOURCES / "foodon_category_ancestry.json").read_text())["graphs"]
    identifier = "FOODON:00004038"
    graph = graphs[0]
    node = next(node for node in graph["nodes"] if compact_identifier(node["id"]) == identifier)
    if corruption == "missing":
        graph["nodes"].remove(node)
    elif corruption == "obsolete":
        node["meta"] = {"deprecated": True}
    else:
        node["type"] = corruption
    try:
        categories = foodon_classification.foodon_categories(graphs, dispositions={})
    except ValueError:
        return
    assert categories.get(identifier) != "biolink:Activity"


@pytest.mark.parametrize("corruption", ["missing", "PROPERTY", "obsolete"])
def test_foodon_invalid_root_cannot_authorize_descendants(corruption):
    """A root ID alone cannot authorize a category without a live class declaration."""
    graphs = json.loads((RESOURCES / "foodon_category_ancestry.json").read_text())["graphs"]
    graph = graphs[0]
    node = next(node for node in graph["nodes"] if compact_identifier(node["id"]) == "BFO:0000015")
    if corruption == "missing":
        graph["nodes"].remove(node)
    elif corruption == "obsolete":
        node["meta"] = {"deprecated": True}
    else:
        node["type"] = corruption
    try:
        categories = foodon_classification.foodon_categories(graphs, dispositions={})
    except ValueError:
        return
    assert categories.get("FOODON:00004038") != "biolink:Activity"


def test_foodon_contradictory_declared_roots_abort():
    """A live class cannot be both a process and an information entity."""
    graphs = [
        {
            "nodes": [
                {"id": identifier, "type": "CLASS"}
                for identifier in ("FOODON:review_conflict", "BFO:0000015", "IAO:0000030")
            ],
            "edges": [
                {"sub": "FOODON:review_conflict", "pred": "is_a", "obj": root}
                for root in ("BFO:0000015", "IAO:0000030")
            ],
        }
    ]
    with pytest.raises(ValueError, match="Conflicting"):
        foodon_classification.foodon_categories(graphs, dispositions={})


@pytest.mark.parametrize("accession,paired", [("RS_GCF_000005845.2", "GCA_000005845.2"), ("GB_GCA_950287535.1", None)])
def test_gtdb_assignment_changes_only_membership_semantics(tmp_path, accession, paired):
    """The semantic correction preserves accession version, paired ID and node category."""
    from kg_microbe.transform_utils.gtdb.gtdb import GTDBTransform

    transform = GTDBTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "out")
    taxon = "s__Escherichia_coli"
    taxon_id = transform._get_or_create_taxon_id(taxon)
    original_nodes = {row["id"]: dict(row) for row in transform.nodes}
    transform._create_genome_node(accession, taxon, genbank_accession=paired)
    identifier = "ncbi.assembly:" + accession.removeprefix("RS_").removeprefix("GB_")
    nodes = {row["id"]: row for row in transform.nodes}
    node = nodes[identifier]
    assert node["category"] == "biolink:Genome"
    assert node["same_as"] == ("ncbi.assembly:" + paired if paired else "")
    assert node["id"] == identifier
    assert {key: nodes[key] for key in original_nodes} == original_nodes
    assert len(transform.edges) == 1
    edge = transform.edges[0]
    assert (edge["subject"], edge["object"], edge["predicate"], edge["relation"]) == (
        identifier,
        taxon_id,
        "biolink:in_taxon",
        "RO:0002162",
    )
