"""Keep imported term categories and IRI identity consistent (#1052, #1054)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies import ontologies_transform
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils.graph_canonicalization import canonical_node_category, compact_identifier
from kg_microbe.utils.mapping_file_utils import uri_to_curie

FIXTURE = Path(__file__).parent / "resources" / "ontology_canonicalization.json"


@pytest.mark.parametrize(
    "identifier,category,expected",
    [
        ("FOODON:03301710", "biolink:OntologyClass|biolink:Food", "biolink:Food"),
        ("PATO:0001421", "biolink:PhenotypicQuality|biolink:OntologyClass", "biolink:PhenotypicQuality"),
        ("http://purl.obolibrary.org/obo/PATO_0001421", "", "biolink:PhenotypicQuality"),
        ("FOODON:03315426", "biolink:Food|biolink:ChemicalMixture", "biolink:ChemicalMixture|biolink:Food"),
        (
            "FOODON:03315426",
            "biolink:OntologyClass|biolink:Food|biolink:ChemicalMixture|biolink:Food",
            "biolink:ChemicalMixture|biolink:Food",
        ),
        ("FOODON:03420174", "biolink:EnvironmentalFeature", "biolink:EnvironmentalFeature|biolink:Food"),
        ("PATO:0001421", "biolink:Attribute|biolink:OntologyClass", "biolink:Attribute|biolink:PhenotypicQuality"),
        ("CHEBI:15377", "biolink:ChemicalEntity|biolink:ChemicalRole", "biolink:ChemicalEntity|biolink:ChemicalRole"),
        ("EC:1.1.1.1", "biolink:MolecularActivity|biolink:Protein", "biolink:MolecularActivity|biolink:Protein"),
    ],
)
def test_categories_follow_node_namespace(identifier, category, expected):
    """Importer identity cannot add an OntologyClass category back to FOODON/PATO."""
    assert canonical_node_category(identifier, category) == expected


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("https://www.w3.org/TR/owl-time/#time:Duration", "time:Duration"),
        ("http://www.w3.org/2006/time#Duration", "time:Duration"),
        ("https://www.w3.org/TR/owl-time/#time:unitYear", "time:unitYear"),
        ("http://purl.obolibrary.org/obo/FOODON_03301710", "FOODON:03301710"),
        ("https://w3id.org/metpo/1000059", "METPO:1000059"),
        ("FOODON:03301710", "FOODON:03301710"),
        ("http://example.org/Duration", "http://example.org/Duration"),
        ("https://www.w3.org/TR/other/#time:Duration", "https://www.w3.org/TR/other/#time:Duration"),
    ],
)
def test_identifier_compaction_is_specific_and_idempotent(identifier, expected):
    """Registered namespaces and explicit aliases compact; arbitrary URLs do not."""
    assert compact_identifier(identifier) == expected
    assert compact_identifier(expected) == expected
    assert uri_to_curie(identifier) == expected


def _transform(tmp_path):
    """Build an offline transform with only the state needed by normalization."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.output_dir = tmp_path
    transform.node_header = ["id", "category", "name", "description", "xref", "provided_by"]
    transform.edge_header = [
        "subject",
        "predicate",
        "object",
        "relation",
        "primary_knowledge_source",
        "knowledge_level",
        "agent_type",
    ]
    return transform


@pytest.mark.parametrize("importer", ["envo", "uberon", "ro"])
def test_final_normalization_fixes_imported_categories(tmp_path, importer):
    """All ontology files share the namespace guard, not just FOODON/PATO files."""
    transform = _transform(tmp_path)
    nodes = tmp_path / f"{importer}_nodes.tsv"
    pd.DataFrame(
        [
            ["FOODON:03301710", "biolink:OntologyClass"],
            ["PATO:0001421", "biolink:OntologyClass"],
            ["EC:1.1.1.1", "biolink:MolecularActivity|biolink:Protein"],
        ],
        columns=["id", "category"],
    ).to_csv(nodes, sep="\t", index=False)
    transform._normalize_schema(nodes, tmp_path / "absent_edges.tsv")
    categories = pd.read_csv(nodes, sep="\t").set_index("id")["category"].to_dict()
    assert categories["FOODON:03301710"] == "biolink:Food"
    assert categories["PATO:0001421"] == "biolink:PhenotypicQuality"
    assert categories["EC:1.1.1.1"] == "biolink:MolecularActivity|biolink:Protein"


def test_parse_drops_declared_annotations_and_preserves_temporal_hierarchy(tmp_path, monkeypatch):
    """Annotation declarations survive JSON preprocessing as metadata, never as entity nodes."""
    transform = _transform(tmp_path)

    def fake_kgx_transform(**kwargs):
        """Emit the small immutable obograph as KGX would, without a live ontology adapter."""
        graph = json.loads(Path(kwargs["inputs"][0]).read_text())["graphs"][0]
        pd.DataFrame(
            [[node["id"], "biolink:OntologyClass"] for node in graph["nodes"]],
            columns=["id", "category"],
        ).to_csv(tmp_path / "envo_nodes.tsv", sep="\t", index=False)
        pd.DataFrame(
            [[edge["sub"], "biolink:subclass_of", edge["obj"], "rdfs:subClassOf"] for edge in graph["edges"]],
            columns=["subject", "predicate", "object", "relation"],
        ).to_csv(tmp_path / "envo_edges.tsv", sep="\t", index=False)

    monkeypatch.setattr(ontologies_transform, "_run_kgx_transform", fake_kgx_transform)
    transform.parse("envo", FIXTURE, "envo")
    nodes = pd.read_csv(tmp_path / "envo_nodes.tsv", sep="\t")
    edges = pd.read_csv(tmp_path / "envo_edges.tsv", sep="\t")
    assert set(nodes["id"]) == {
        "RO:0002215",
        "FOODON:03301710",
        "PATO:0001421",
        "time:Duration",
        "time:TemporalDuration",
    }
    assert len(edges) == 1
    assert edges.iloc[0]["subject"] == "time:Duration"
    assert edges.iloc[0]["object"] == "time:TemporalDuration"
    assert set(edges["subject"]) | set(edges["object"]) <= set(nodes["id"])


def test_edge_only_iri_references_compact_without_local_node(tmp_path):
    """An imported endpoint must be canonical even if a different source owns its node."""
    transform = _transform(tmp_path)
    nodes = tmp_path / "nodes.tsv"
    edges = tmp_path / "edges.tsv"
    pd.DataFrame([["NCIT:C94729", "biolink:OntologyClass"]], columns=["id", "category"]).to_csv(
        nodes, sep="\t", index=False
    )
    pd.DataFrame(
        [["NCIT:C94729", "https://www.w3.org/TR/owl-time/#time:Interval"]], columns=["subject", "object"]
    ).to_csv(edges, sep="\t", index=False)
    transform._convert_urls_to_curies(nodes, edges)
    assert pd.read_csv(edges, sep="\t").iloc[0]["object"] == "time:Interval"


def test_annotation_declarations_do_not_leak_between_ontologies(tmp_path):
    """One ontology's annotation classification must not silently govern another source."""
    transform = _transform(tmp_path)
    transform._drop_deprecated_terms(FIXTURE)
    assert "http://qudt.org/schema/qudt/ucumCode" in transform._annotation_property_ids
    next_json = tmp_path / "next.json"
    next_json.write_text('{"graphs": [{"nodes": [], "edges": []}]}')
    transform._drop_deprecated_terms(next_json)
    assert transform._annotation_property_ids == set()
