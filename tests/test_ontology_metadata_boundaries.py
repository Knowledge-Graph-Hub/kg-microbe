"""Only evidence-backed annotation entities are excluded from ontology graphs (#1074)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils.graph_canonicalization import compact_identifier

FIXTURE = Path(__file__).parent / "resources/ontology_metadata_boundaries.json"
PERSON_IRI = "https://orcid.org/0000-0001-5208-3432"
PERSON = "orcid:0000-0001-5208-3432"


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("http://purl.obolibrary.org/obo/go#gocheck_do_not_annotate", "GOP:gocheck_do_not_annotate"),
        ("http://purl.obolibrary.org/obo/GOREL_0002003", "GOREL:0002003"),
        ("http://purl.obolibrary.org/obo/uberon/core#anastomoses_with", "UBERON_CORE:anastomoses_with"),
        ("https://www.wikidata.org/wiki/Q2", "WIKIDATA:Q2"),
        ("https://www.wikidata.org/entity/Q2", "WIKIDATA:Q2"),
        ("ORCID:0000-0001-5208-3432", PERSON),
        (PERSON_IRI, PERSON),
        ("https://www.wikidata.org/wiki/Special:EntityData/Q2", "https://www.wikidata.org/wiki/Special:EntityData/Q2"),
    ],
)
def test_verified_namespaces_and_specific_aliases(identifier, expected):
    """Aliases are idempotent and do not rewrite arbitrary wiki pages."""
    assert compact_identifier(identifier) == expected
    assert compact_identifier(expected) == expected


def _transform(tmp_path):
    """Avoid base setup and configure only fields exercised by normalization."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.node_header = ["id", "category", "name"]
    transform.edge_header = ["subject", "predicate", "object", "relation", "primary_knowledge_source"]
    transform.output_dir = tmp_path
    return transform


def test_annotation_entities_drop_but_genuine_same_prefix_nodes_and_metadata_survive(tmp_path):
    """Raw declarations, not blanket namespaces, control entity exclusion."""
    transform = _transform(tmp_path)
    original = FIXTURE.read_bytes()
    transform._drop_deprecated_terms(FIXTURE)
    assert FIXTURE.read_bytes() == original
    nodes = tmp_path / "uberon_nodes.tsv"
    edges = tmp_path / "uberon_edges.tsv"
    graph = json.loads(original)["graphs"][0]
    pd.DataFrame(
        [[compact_identifier(n["id"]), "biolink:OntologyClass", n.get("lbl", "")] for n in graph["nodes"]],
        columns=transform.node_header,
    ).to_csv(nodes, sep="\t", index=False)
    pd.DataFrame(
        [["WIKIDATA:Q2", "biolink:related_to", "NCBITaxon:9606", "GOREL:0002003", "envo.json"]],
        columns=transform.edge_header,
    ).to_csv(edges, sep="\t", index=False)
    transform._normalize_schema(nodes, edges)
    kept = set(pd.read_csv(nodes, sep="\t")["id"])
    assert PERSON not in kept
    assert "GOP:gocheck_do_not_annotate" not in kept
    assert "UBERON_CORE:BRAIN_NAME_ABV" not in kept
    assert {"GOREL:0002003", "UBERON_CORE:anastomoses_with", "WIKIDATA:Q2", "WIKIDATA:Q105560983"} <= kept
    edge = pd.read_csv(edges, sep="\t").iloc[0]
    assert edge["relation"] == "GOREL:0002003"
    assert edge["primary_knowledge_source"] == "envo.json"
    report = pd.read_csv(tmp_path / "uberon_metadata_exclusions.tsv", sep="\t")
    assert set(report["id"]) == {PERSON, "GOP:gocheck_do_not_annotate", "UBERON_CORE:BRAIN_NAME_ABV"}
    assert set(report["reason"]) == {"declared_annotation_property", "annotation_only_contributor"}


@pytest.mark.parametrize("protect", ["class", "semantic_edge", "logical_axiom", "second_graph", "no_annotation"])
def test_contributor_with_a_semantic_role_is_never_discarded(tmp_path, protect):
    """Individual declaration and annotation usage alone are insufficient for removal."""
    data = json.loads(FIXTURE.read_text())
    graph = data["graphs"][0]
    if protect == "class":
        graph["nodes"][0]["type"] = "CLASS"
    elif protect == "semantic_edge":
        graph["edges"].append({"sub": PERSON_IRI, "pred": "http://purl.obolibrary.org/obo/RO_0001025", "obj": "X:1"})
    elif protect == "logical_axiom":
        graph["logicalDefinitionAxioms"] = [{"definedClassId": "X:1", "genusIds": [PERSON_IRI]}]
    elif protect == "second_graph":
        data["graphs"].append({"nodes": [{"id": PERSON_IRI, "type": "CLASS"}]})
    else:
        graph["meta"] = {}
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(data))
    transform = _transform(tmp_path)
    transform._drop_deprecated_terms(raw)
    assert PERSON not in transform._annotation_individual_ids


def test_annotation_individual_state_resets_between_sources(tmp_path):
    """A contributor in one ontology cannot suppress another ontology's real entity."""
    transform = _transform(tmp_path)
    transform._drop_deprecated_terms(FIXTURE)
    assert transform._annotation_individual_ids == {PERSON}
    empty = tmp_path / "empty.json"
    empty.write_text('{"graphs": []}')
    transform._drop_deprecated_terms(empty)
    assert transform._annotation_individual_ids == set()


def test_oio_and_oboinowl_metamodel_nodes_excluded_and_wd_entity_compacted(tmp_path):
    """OIO:* and oboInOwl:* metamodel nodes are dropped and WD_Entity: compacts to WIKIDATA: (#1074)."""
    assert compact_identifier("WD_Entity:Q2") == "WIKIDATA:Q2"
    assert compact_identifier("WD_Entity:not_a_qid") == "WD_Entity:not_a_qid"

    transform = _transform(tmp_path)
    nodes = tmp_path / "envo_nodes.tsv"
    edges = tmp_path / "envo_edges.tsv"
    pd.DataFrame(
        [
            {"id": "OIO:hasExactSynonym", "category": "biolink:OntologyClass", "name": "has_exact_synonym"},
            {"id": "oboInOwl:hasDbXref", "category": "biolink:OntologyClass", "name": "database_cross_reference"},
            {"id": "WD_Entity:Q2", "category": "biolink:NamedThing", "name": "Earth"},
            {"id": "ENVO:00000428", "category": "biolink:EnvironmentalFeature", "name": "biome"},
        ]
    ).to_csv(nodes, sep="\t", index=False)
    pd.DataFrame(columns=transform.edge_header).to_csv(edges, sep="\t", index=False)
    transform._convert_urls_to_curies(nodes, edges)
    transform._normalize_schema(nodes, edges)

    kept = set(pd.read_csv(nodes, sep="\t")["id"])
    assert "OIO:hasExactSynonym" not in kept
    assert "oboInOwl:hasDbXref" not in kept
    assert {"WIKIDATA:Q2", "ENVO:00000428"} == kept
    report = pd.read_csv(tmp_path / "envo_metadata_exclusions.tsv", sep="\t")
    assert set(report["id"]) == {"OIO:hasExactSynonym", "oboInOwl:hasDbXref"}
    assert set(report["reason"]) == {"metamodel_vocabulary"}


def test_establish_transitive_relationship_multiple_retains_multi_valued_and_marks_entailed(tmp_path):
    """Multi-hop transitive deduction keeps all subjects (#1360) and marks logical_entailment (#1362)."""
    from kg_microbe.utils.pandas_utils import establish_transitive_relationship_multiple

    edges = tmp_path / "upa_edges.tsv"
    pd.DataFrame(
        [
            {
                "subject": "RHEA:10001",
                "predicate": "biolink:part_of",
                "object": "UPA:UCR00001",
                "relation": "BFO:0000050",
                "primary_knowledge_source": "infores:upa",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
            },
            {
                "subject": "RHEA:10002",
                "predicate": "biolink:part_of",
                "object": "UPA:UCR00001",
                "relation": "BFO:0000050",
                "primary_knowledge_source": "infores:upa",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
            },
            {
                "subject": "UPA:UCR00001",
                "predicate": "biolink:part_of",
                "object": "UPA:UER00001",
                "relation": "BFO:0000050",
                "primary_knowledge_source": "infores:upa",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
            },
            {
                "subject": "UPA:UER00001",
                "predicate": "biolink:part_of",
                "object": "UPA:UPA00001",
                "relation": "BFO:0000050",
                "primary_knowledge_source": "infores:upa",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
            },
        ]
    ).to_csv(edges, sep="\t", index=False)

    df = establish_transitive_relationship_multiple(
        edges,
        "RHEA:",
        ["UPA:UCR", "UPA:UER"],
        ["biolink:part_of", "biolink:part_of"],
        [["UPA:UER"], ["UPA:UPA"]],
    )
    shortcut_rows = df[(df["subject"].str.startswith("RHEA:")) & (df["object"] == "UPA:UPA00001")]
    assert set(shortcut_rows["subject"]) == {"RHEA:10001", "RHEA:10002"}
    assert set(shortcut_rows["knowledge_level"]) == {"logical_entailment"}
    assert set(shortcut_rows["agent_type"]) == {"automated_agent"}

