"""Category decisions belong before merge and retain their consumed authority identity."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.graph_canonicalization import canonical_node_category
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files


class _NativeAuthority:
    """A finite asserted-category decision, not a namespace or predicate guess."""

    def category_for(self, identifier):
        """Only the fixture's native material is classified."""
        return "biolink:PhysicalEntity" if identifier == "ENVO:1" else None


def test_only_generic_category_is_replaced_and_unknown_is_preserved():
    """Native decisions cannot overwrite substantive types or invent missing ancestry."""
    authority = _NativeAuthority()
    assert canonical_node_category("ENVO:1", "biolink:OntologyClass", ontology_authority=authority) == (
        "biolink:PhysicalEntity"
    )
    assert (
        canonical_node_category("ENVO:1", "biolink:ChemicalEntity|biolink:OntologyClass", ontology_authority=authority)
        == "biolink:ChemicalEntity|biolink:PhysicalEntity"
    )
    assert canonical_node_category("ENVO:1", "biolink:ChemicalEntity", ontology_authority=authority) == (
        "biolink:ChemicalEntity"
    )
    assert canonical_node_category("ENVO:2", "biolink:OntologyClass", ontology_authority=authority) == (
        "biolink:OntologyClass"
    )


@pytest.mark.parametrize(
    "category", ["biolink:Activity", "biolink:PhenotypicQuality", "biolink:InformationContentEntity"]
)
def test_authoritative_foodon_nonmaterial_branch_removes_food(category):
    """A process/quality/information class must not keep the old material fallback."""
    assert (
        canonical_node_category(
            "FOODON:1", "biolink:Food|biolink:OntologyClass", foodon_categories={"FOODON:1": category}
        )
        == category
    )


def _source(tmp_path):
    """Construct a minimal offline producer with an explicit FOODON authority."""
    raw = tmp_path / "raw"
    raw.mkdir()
    transform = Transform("fixture", raw, tmp_path / "transformed")
    authority = {
        "graphs": [
            {
                "nodes": [{"id": identifier, "type": "CLASS"} for identifier in ("FOODON:1", "BFO:0000015")],
                "edges": [{"sub": "FOODON:1", "pred": "is_a", "obj": "BFO:0000015"}],
            }
        ]
    }
    (raw / "foodon.json").write_text(json.dumps(authority))
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "FOODON:1\tbiolink:Food|biolink:OntologyClass\tFixture process\tinfores:foodon\n"
        "fixture:1\tbiolink:NamedThing\tPreserved target\tinfores:fixture\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "FOODON:1\tbiolink:related_to\tfixture:1\tskos:related\tinfores:fixture\n"
    )
    return transform


def test_foodon_snapshot_and_audit_are_bound_before_merge(tmp_path):
    """The category correction is finalized upstream and a changed authority is rejected."""
    transform = _source(tmp_path)
    report = transform.finalize()
    node = next(graph_rows(transform.output_node_file))
    assert node["category"] == "biolink:Activity"
    assert report["consumed_inputs"]["category_authority_foodon"]["path"] == str(
        (transform.input_base_dir / "foodon.json").resolve()
    )
    audit = list(graph_rows(transform.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    changes = [r for r in audit if json.loads(r["normalized_row_json"]).get("id") == "FOODON:1"]
    assert len(changes) == 1
    assert json.loads(changes[0]["original_row_json"])["category"] == "biolink:Food|biolink:OntologyClass"
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    (transform.input_base_dir / "foodon.json").write_text('{"graphs": []}')
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_changed_authority_during_classification_publishes_no_finalization(tmp_path, monkeypatch):
    """The consumed bytes, not a later hash of modified authority, define each decision."""
    from kg_microbe.utils import foodon_classification

    transform = _source(tmp_path)
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original = foodon_classification.foodon_categories

    def mutate_after_read(graphs, **kwargs):
        """Change a real selected input during parsing of its immutable snapshot."""
        (transform.input_base_dir / "foodon.json").write_text('{"graphs": []}')
        return original(graphs, **kwargs)

    monkeypatch.setattr(foodon_classification, "foodon_categories", mutate_after_read)
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        transform.finalize()
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_generic_importer_is_classified_from_selected_native_snapshot(tmp_path):
    """An importer uses ENVO ancestry, while unrelated authorities are not required."""
    transform = _source(tmp_path)
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\nENVO:1\tbiolink:OntologyClass\tFixture material\tinfores:test\n"
        "fixture:1\tbiolink:NamedThing\tTarget\tinfores:test\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "ENVO:1\tbiolink:related_to\tfixture:1\tskos:related\tinfores:test\n"
    )
    path = transform.input_base_dir / "envo.json"
    path.write_text(
        json.dumps(
            {
                "graphs": [
                    {
                        "nodes": [{"id": "ENVO:1", "type": "CLASS"}, {"id": "BFO:0000040", "type": "CLASS"}],
                        "edges": [{"sub": "ENVO:1", "pred": "is_a", "obj": "BFO:0000040"}],
                    }
                ]
            }
        )
    )
    report = transform.finalize()
    assert next(graph_rows(transform.output_node_file))["category"] == "biolink:PhysicalEntity"
    assert set(report["consumed_inputs"]) == {"category_authority_envo"}
    assert "foodon.json" not in {Path(record["path"]).name for record in report["inputs"]}


def test_missing_selected_native_authority_aborts_before_publication(tmp_path):
    """Missing authority is not equivalent to evidence for an unresolved category."""
    transform = _source(tmp_path)
    text = transform.output_node_file.read_text().replace("FOODON:1", "ENVO:1").replace("biolink:Food|", "")
    transform.output_node_file.write_text(text)
    before = transform.output_node_file.read_bytes()
    with pytest.raises(FileNotFoundError, match="envo.json"):
        transform.finalize()
    assert transform.output_node_file.read_bytes() == before
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_finite_gene_enrichment_leaves_unknown_gene_and_assertions_unchanged(tmp_path):
    """Only the two validated native records supply gene category and blank labels."""
    transform = _source(tmp_path)
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "NCBIGene:26468\tbiolink:OntologyClass\t\tinfores:uberon\n"
        "NCBIGene:55553\tbiolink:OntologyClass\t\tinfores:uberon\n"
        "NCBIGene:999999999\tbiolink:OntologyClass\tUnknown\tinfores:uberon\n"
        "fixture:1\tbiolink:NamedThing\tTarget\tinfores:test\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:expresses\tNCBIGene:26468\tRO:0002292\tinfores:uberon\n"
    )
    edge_before = next(graph_rows(transform.output_edge_file))
    report = transform.finalize()
    nodes = {row["id"]: row for row in graph_rows(transform.output_node_file)}
    for identifier, symbol in (("NCBIGene:26468", "LHX6"), ("NCBIGene:55553", "SOX6")):
        assert nodes[identifier]["category"] == "biolink:Gene"
        assert nodes[identifier]["name"] == symbol
    assert nodes["NCBIGene:999999999"]["category"] == "biolink:OntologyClass"
    assert nodes["NCBIGene:999999999"]["name"] == "Unknown"
    edge_after = next(graph_rows(transform.output_edge_file))
    assert {key: edge_after[key] for key in edge_before} == edge_before
    assert set(report["consumed_inputs"]) == {
        "category_authority_imported_gene_authority",
        "category_authority_imported_gene_native_esummary",
    }


@pytest.mark.parametrize("payload", [{"graphs": []}, {"graphs": [{"nodes": [], "edges": []}]}])
def test_empty_foodon_authority_aborts_instead_of_asserting_food(tmp_path, payload):
    """An empty selected ontology is an infrastructure failure, not Food evidence."""
    transform = _source(tmp_path)
    (transform.input_base_dir / "foodon.json").write_text(json.dumps(payload))
    before = transform.output_node_file.read_bytes()
    with pytest.raises(ValueError, match="Missing FOODON ontology declarations"):
        transform.finalize()
    assert transform.output_node_file.read_bytes() == before
    assert not (transform.output_dir / "source_finalization.json").exists()
