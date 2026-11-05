"""Retain reviewed native axiom annotations through KGX's streamed boundary."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import NOTES_COLUMN, OBO_ANNOTATIONS_COLUMN, OBO_AXIOM_EVIDENCE_COLUMN
from tests.test_ontology_relation_preservation import _convert, _convert_with_fresh_toolkit, _rows

FIXTURES = Path(__file__).parent / "resources"
NOTE_PREDICATE = "http://www.geneontology.org/formats/oboInOwl#notes"


@pytest.fixture(autouse=True)
def local_model(monkeypatch):
    """Use only the immutable schema and mapping in fresh conversion processes."""
    monkeypatch.setenv("KG_MICROBE_BIOLINK_MODEL", str(FIXTURES / "ontology_relations/biolink-model.yaml"))
    monkeypatch.setenv("KG_MICROBE_BIOLINK_PREDICATE_MAP", str(FIXTURES / "predicate_mapping_minimal.yaml"))


def test_native_uberon_note_retains_exact_assertion_and_text(tmp_path):
    """Exercise the actual native UBERON assertion that exposed KGX 2.8's change."""
    native = json.loads((FIXTURES / "native_ro_retention/uberon.json").read_text())
    graph = native["graphs"][0]
    selected = [
        e
        for e in graph["edges"]
        if any(a.get("pred") == NOTE_PREDICATE for a in e.get("meta", {}).get("basicPropertyValues", []))
    ]
    assert len(selected) == 1
    graph["edges"] = selected
    endpoints = {selected[0]["sub"], selected[0]["obj"]}
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] in endpoints]
    source = tmp_path / "uberon.json"
    source.write_text(json.dumps(native))
    _convert_with_fresh_toolkit(source, tmp_path / "out")
    (row,) = _rows(tmp_path / "out_edges.tsv")
    assert (row["subject"], row["relation"], row["object"]) == ("UBERON:0000070", "RO:0002082", "GO:0035209")
    assert row[NOTES_COLUMN] == "may be better to model pupal development as including the pre-pupal stage"


@pytest.mark.parametrize("column", [NOTES_COLUMN, OBO_ANNOTATIONS_COLUMN, OBO_AXIOM_EVIDENCE_COLUMN])
def test_annotation_literal_transport_survives_source_finalization_and_merge(tmp_path, column):
    """Preserve literal text, JSON ordering and quote escapes through every transport boundary."""
    import io

    from kg_microbe.merge_utils.kgx_source import (
        ProvenancePreservingTransformer,
        RelationAwareTsvSink,
        RelationAwareTsvSource,
    )
    from kg_microbe.merge_utils.local_context import local_prefix_context
    from kg_microbe.utils.graph_schema import validate_canonical_tsv
    from kg_microbe.utils.source_finalization import _stage_representation

    literal = 'pupal | pre-pupal "quoted" wording remains source annotation'
    predicates = {
        NOTES_COLUMN: NOTE_PREDICATE,
        OBO_ANNOTATIONS_COLUMN: "https://example.org/unreviewed",
        OBO_AXIOM_EVIDENCE_COLUMN: "http://www.geneontology.org/formats/oboInOwl#evidence",
    }
    values = [literal] if column == NOTES_COLUMN else [literal, "second"]
    annotations = [{"pred": predicates[column], "val": value} for value in values]
    expected_values = (
        [f"https://example.org/unreviewed={value}" for value in values] if column == OBO_ANNOTATIONS_COLUMN else values
    )
    expected = literal if column == NOTES_COLUMN else json.dumps(expected_values, separators=(",", ":"))

    def annotate(document):
        """Attach exact literal payloads to one assertion for end-to-end transport checks."""
        graph = document["graphs"][0]
        graph["edges"] = [graph["edges"][0]]
        graph["edges"][0].update(
            meta={"basicPropertyValues": annotations},
            primary_knowledge_source="infores:test",
            knowledge_source="infores:test",
            knowledge_level="knowledge_assertion",
            agent_type="manual_agent",
        )

    _, rows = _convert(tmp_path, mutate=annotate, fresh_process=True)
    assert rows[0][column] == expected
    import ast

    assert ast.literal_eval(rows[0]["meta"]) == {"basicPropertyValues": annotations}
    finalized = tmp_path / "finalized_edges.tsv"
    audit_stream = io.StringIO()
    audit = csv.DictWriter(
        audit_stream, fieldnames=["file", "line", "original_row_json", "normalized_row_json"], delimiter="\t"
    )
    _stage_representation(
        tmp_path / "out_edges.tsv",
        finalized,
        False,
        csv.QUOTE_NONE,
        Path("mappings/foodon_model_dispositions.tsv"),
        audit,
        set(),
        set(),
    )
    assert validate_canonical_tsv(finalized, is_node=False) == 1
    (finalized_row,) = _rows(finalized)
    assert finalized_row[column] == expected
    with local_prefix_context():
        owner = ProvenancePreservingTransformer()
        reader = RelationAwareTsvSource(owner)
        record = reader.read_edge(finalized_row)[-1]
        assert record[column] == expected
        sink = RelationAwareTsvSink(
            owner,
            format="tsv",
            filename=str(tmp_path / "merged"),
            node_properties={"id"},
            edge_properties=set(finalized_row),
        )
        try:
            sink.write_edge(record)
        finally:
            sink.finalize()
    (merged_row,) = _rows(tmp_path / "merged_edges.tsv")
    assert merged_row[column] == expected


def test_note_column_is_absent_without_native_annotation(tmp_path):
    """An empty projected note column must not appear in unrelated conversions."""
    _, rows = _convert(tmp_path, fresh_process=True)
    assert NOTES_COLUMN not in rows[0]


def test_unreviewed_annotation_column_still_fails(tmp_path):
    """A known note never grants permission for arbitrary KGX annotation output."""

    def annotate(document):
        """Introduce an unreviewed native annotation to exercise the closed-field guard."""
        document["graphs"][0]["edges"][0]["meta"] = {
            "basicPropertyValues": [{"pred": "https://w3id.org/sssom/unreviewed_evidence", "val": "unreviewed"}]
        }

    with pytest.raises(ValueError, match="Undeclared KGX.*unreviewed_evidence"):
        _convert(tmp_path, mutate=annotate)


@pytest.mark.parametrize(
    "native_source, expected_level, expected_agent, expected_evidence",
    [
        ("PMID:123", "knowledge_assertion", "manual_agent", ("publications", "PMID:123")),
        ("https://orcid.org/0000-0001-0000-0001", "knowledge_assertion", "manual_agent", None),
        ("MONDO:Inferred", "logical_entailment", "automated_agent", None),
        ("BILS", "knowledge_assertion", "manual_agent", ("xref", "BILS")),
    ],
)
def test_native_sources_preserve_evidence_and_unannotated_defaults(
    tmp_path, native_source, expected_level, expected_agent, expected_evidence
):
    """Actual native parsing retains source evidence without blanking another assertion."""
    import ast

    from kg_microbe.transform_utils.constants import OBO_SOURCE_ANNOTATION_COLUMN
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    metadata = {
        "basicPropertyValues": [{"pred": "http://www.geneontology.org/formats/oboInOwl#source", "val": native_source}]
    }

    def annotate(document):
        """Annotate only one assertion, preserving the other assertion's absent fields."""
        document["graphs"][0]["edges"][0]["meta"] = metadata

    _, rows = _convert(tmp_path, mutate=annotate, fresh_process=True)
    annotated = next(row for row in rows if row["relation"] == "BFO:0000050")
    assert annotated[OBO_SOURCE_ANNOTATION_COLUMN] == native_source
    assert ast.literal_eval(annotated["meta"]) == metadata
    if expected_evidence:
        column, value = expected_evidence
        assert annotated[column] == value
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    transform._add_kgx_metadata_to_edges(tmp_path / "out_edges.tsv")
    rows = _rows(tmp_path / "out_edges.tsv")
    annotated = next(row for row in rows if row["relation"] == "BFO:0000050")
    unannotated = next(row for row in rows if row["relation"] == "RO:0002007")
    assert (annotated["knowledge_level"], annotated["agent_type"]) == (expected_level, expected_agent)
    assert (unannotated["knowledge_level"], unannotated["agent_type"]) == ("knowledge_assertion", "manual_agent")
    assert unannotated[OBO_SOURCE_ANNOTATION_COLUMN] == ""


def test_annotation_projection_never_replaces_explicit_raw_blanks(tmp_path):
    """Raw blank columns retain their established behavior even beside inferred annotations."""
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    def annotate(document):
        """Preserve explicit blank source values beside a reasoner annotation."""
        edge = document["graphs"][0]["edges"][0]
        edge.update(
            knowledge_level="",
            agent_type="",
            meta={
                "basicPropertyValues": [
                    {"pred": "http://www.geneontology.org/formats/oboInOwl#source", "val": "MONDO:Inferred"}
                ]
            },
        )

    _convert(tmp_path, mutate=annotate, fresh_process=True)
    transform = OntologiesTransform(input_dir=tmp_path / "raw", output_dir=tmp_path / "transformed")
    transform._add_kgx_metadata_to_edges(tmp_path / "out_edges.tsv")
    for row in _rows(tmp_path / "out_edges.tsv"):
        assert row["knowledge_level"] == row["agent_type"] == ""


@pytest.mark.parametrize("name", ["uberon", "foodon"])
def test_genuine_native_annotations_do_not_mint_biolink_evidence_entities(tmp_path, name):
    """Carry real heterogeneous evidence and opaque axiom labels without inventing typed entities."""
    import ast
    import hashlib

    source = FIXTURES / "ontology_axiom_annotations" / f"{name}.json"
    origin = json.loads((source.parent / "origin.json").read_text())[name]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == origin["fixture_sha256"]
    document = json.loads(source.read_text())
    _convert_with_fresh_toolkit(source, tmp_path / "out")
    rows = _rows(tmp_path / "out_edges.tsv")
    assert len(rows) == origin["selected_edges"]
    assert "has_evidence" not in rows[0]
    expected = []
    observed = []
    for edge in document["graphs"][0]["edges"]:
        values = [
            item["val"]
            for item in edge.get("meta", {}).get("basicPropertyValues", [])
            if item.get("pred") == "http://www.geneontology.org/formats/oboInOwl#evidence"
        ]
        if values:
            expected.append(values)
    for row in rows:
        metadata = ast.literal_eval(row["meta"])
        assert metadata in [edge["meta"] for edge in document["graphs"][0]["edges"]]
        if row.get(OBO_AXIOM_EVIDENCE_COLUMN):
            observed.append(json.loads(row[OBO_AXIOM_EVIDENCE_COLUMN]))
        if row.get(OBO_ANNOTATIONS_COLUMN):
            values = json.loads(row[OBO_ANNOTATIONS_COLUMN])
            assert isinstance(values, list) and all(isinstance(value, str) for value in values)
    assert sorted(observed) == sorted(expected)
    if name == "uberon":
        assert {value for values in observed for value in values} == {
            "definitional",
            "ISBN:0486692132",
            "cjm",
            "PMID:3709965",
            "NAS",
        }
    else:
        assert {value for row in rows for value in json.loads(row[OBO_ANNOTATIONS_COLUMN])} == {
            "rdfs:label=acid",
            "rdfs:label=acidity regulator",
        }
