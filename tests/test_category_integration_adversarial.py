"""Adversarial source-category integration through real native fixture records."""

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows
from tests.test_go_checkpoint_finalization import _checkpoint, _prepare
from tests.test_source_category_authority import _source

FIXTURES = Path(__file__).parent / "resources"


@pytest.mark.parametrize("route", ["native_foodon", "imported_foodon"])
def test_ontology_foodon_route_uses_selected_raw_not_global_cache(tmp_path, monkeypatch, route):
    """An alternate raw directory cannot inherit stale substantive category evidence."""
    from kg_microbe.utils import foodon_classification

    transform = _source(tmp_path)
    shutil.copyfile(FIXTURES / "foodon_category_ancestry.json", transform.input_base_dir / "foodon.json")
    foreign = tmp_path / "foreign_foodon.json"
    foreign.write_text(
        json.dumps({"graphs": [{"edges": [{"sub": "FOODON:03430105", "pred": "is_a", "obj": "BFO:0000015"}]}]})
    )
    monkeypatch.setattr(foodon_classification, "FOODON_GRAPH", foreign)
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "FOODON:03430105\tbiolink:Food\tNative formed shape quality\tinfores:foodon\n"
        "fixture:1\tbiolink:NamedThing\tUnrelated target\tinfores:test\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:has_attribute\tFOODON:03430105\tRO:0000086\tinfores:foodon\n"
    )
    ontology = OntologiesTransform.__new__(OntologiesTransform)
    ontology.input_base_dir = transform.input_base_dir
    ontology.node_header = ["id", "category", "name", "provided_by"]
    if route == "native_foodon":
        ontology._fix_node_categories(transform.output_node_file, "foodon")
    else:
        ontology._normalize_schema(transform.output_node_file, tmp_path / "absent_edges.tsv")
    transform.finalize()
    row = next(graph_rows(transform.output_node_file))
    assert row["category"] == "biolink:PhenotypicQuality"


def test_postclosure_native_category_decision_keeps_go_final_byte_checkpoint(tmp_path, monkeypatch):
    """A closure-added declaration may change category but cannot stale the GO audit."""
    from kg_microbe.merge_utils import external_node_closure

    transform = _prepare(tmp_path, monkeypatch, "GO:0004096")
    shutil.copyfile(FIXTURES / "foodon_category_ancestry.json", transform.input_base_dir / "foodon.json")
    resolve = external_node_closure.resolve_external_reference_bundle

    def closure_with_import(node_paths, *args, **kwargs):
        """Add a real imported class at the same stage as local external declarations."""
        result = resolve(node_paths, *args, **kwargs)
        with node_paths[0].open(newline="") as stream:
            fields = next(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
        with node_paths[0].open("a", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n"
            )
            writer.writerow(
                {
                    "id": "FOODON:03430105",
                    "category": "biolink:Food",
                    "name": "Native formed shape quality",
                    "provided_by": "infores:foodon",
                }
            )
        return result

    monkeypatch.setattr(external_node_closure, "resolve_external_reference_bundle", closure_with_import)
    transform.finalize()
    node = next(row for row in graph_rows(transform.output_node_file) if row["id"] == "FOODON:03430105")
    assert node["category"] == "biolink:PhenotypicQuality"
    checkpoint = _checkpoint(transform.output_dir / "go_reference_resolution.tsv")
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (transform.output_node_file, transform.output_edge_file)
    }
    assert {row["file"]: row["sha256"] for row in checkpoint["bundle"]} == actual


@pytest.mark.parametrize("other_root", ["PATO:0000001", "IAO:0000030"])
def test_native_process_cannot_also_be_quality_or_information(tmp_path, other_root):
    """Mutually incompatible upper ontology ancestry must not become multi-typing."""
    from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority

    graph = {
        "nodes": [{"id": identifier, "type": "CLASS"} for identifier in ["ENVO:probe", "ENVO:02500000", other_root]],
        "edges": [{"sub": "ENVO:probe", "pred": "is_a", "obj": root} for root in ["ENVO:02500000", other_root]],
    }
    (tmp_path / "envo.json").write_text(json.dumps({"graphs": [graph]}))
    with pytest.raises(ValueError, match="Contradictory"):
        OntologyCategoryAuthority(tmp_path).category_for("ENVO:probe")


def test_actual_uberon_gene_assertions_keep_native_subject_relation_and_provenance(tmp_path):
    """Both native cell-expression assertions survive exact finite gene enrichment."""
    from kg_microbe.utils.graph_canonicalization import compact_identifier

    transform = _source(tmp_path)
    graph = json.loads((FIXTURES / "uberon_imported_genes.json").read_text())["graphs"][0]
    node_rows = [
        {
            "id": compact_identifier(node["id"]),
            "category": "biolink:Cell" if compact_identifier(node["id"]) == "CL:4023063" else "biolink:OntologyClass",
            "name": node.get("lbl", ""),
            "provided_by": "uberon.json",
        }
        for node in graph["nodes"]
    ]
    edge_rows = [
        {
            "subject": compact_identifier(edge["sub"]),
            "predicate": "biolink:expresses",
            "object": compact_identifier(edge["obj"]),
            "relation": compact_identifier(edge["pred"]),
            "primary_knowledge_source": "infores:uberon",
        }
        for edge in graph["edges"]
    ]
    for path, rows in ((transform.output_node_file, node_rows), (transform.output_edge_file, edge_rows)):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    transform.finalize()
    final_nodes = {row["id"]: row for row in graph_rows(transform.output_node_file)}
    assert {key: final_nodes[key]["name"] for key in ("NCBIGene:26468", "NCBIGene:55553")} == {
        "NCBIGene:26468": "LHX6",
        "NCBIGene:55553": "SOX6",
    }
    assert all(final_nodes[key]["provided_by"] == "uberon.json" for key in final_nodes)
    final_edges = list(graph_rows(transform.output_edge_file))
    assert [{key: row[key] for key in edge_rows[0]} for row in final_edges] == edge_rows
    assert len(final_edges) == 2


def test_gene_authority_mutation_during_parse_aborts_without_graph_publication(tmp_path, monkeypatch):
    """A changed curated snapshot cannot certify decisions from an earlier version."""
    from kg_microbe.utils import imported_gene_authority

    transform = _source(tmp_path)
    mapping = tmp_path / "imported_gene_authority.json"
    shutil.copyfile(imported_gene_authority.GENE_AUTHORITY_FILE, mapping)
    monkeypatch.setattr(imported_gene_authority, "GENE_AUTHORITY_FILE", mapping)
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "NCBIGene:26468\tbiolink:OntologyClass\t\tuberon.json\n"
        "fixture:1\tbiolink:NamedThing\tCell\tuberon.json\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:expresses\tNCBIGene:26468\tRO:0002292\tinfores:uberon\n"
    )
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    original = imported_gene_authority.load_imported_gene_records

    def mutated(stream, **kwargs):
        """Change the original while validation consumes the immutable snapshot."""
        records = original(stream, **kwargs)
        mapping.write_text("{}\n")
        return records

    monkeypatch.setattr(imported_gene_authority, "load_imported_gene_records", mutated)
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        transform.finalize()
    assert (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()) == before
    assert not (transform.output_dir / "source_finalization.json").exists()
