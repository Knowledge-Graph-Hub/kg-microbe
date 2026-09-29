"""Test source-defined processes through actual emission, not just table loading."""

import csv

import pytest

from kg_microbe.transform_utils.microbedecoder.process_scopes import ProcessScopeCuration
from tests.test_microbedecoder_curation_integration import _rows, _transform, _write_source
from tests.test_microbedecoder_curation_inventory import inventory


def test_all_scopes_emit_separate_ids_complete_definitions_and_original_assertions(tmp_path):
    """Source-local definitions neither leak across sources nor invent native class identities."""
    scopes = ProcessScopeCuration().rules
    transform = _transform(tmp_path)
    source = _write_source(
        tmp_path,
        [
            {
                "LPSN_ID": str(1000 + index),
                "FAPROTAX_Type_of_metabolism": scope.source_literal,
                "Bergey_Type_of_metabolism": scope.source_literal,
                "Bergey_Article_link": "https://doi.org/10.1234/example",
            }
            for index, scope in enumerate(scopes)
        ],
    )
    transform.run(data_file=source)
    nodes = {row["id"]: row for row in _rows(transform.output_node_file)}
    edges = _rows(transform.output_edge_file)
    assert len(edges) == 90
    for scope in scopes:
        node = nodes[scope.curie]
        assert node["description"] == scope.description
        assert node["name"] == scope.source_literal
        assert node["category"] == "biolink:BiologicalProcess"
        assert node["provided_by"] == "infores:microbedecoder"
        assert not node["has_attribute_type"]
        prediction = next(row for row in edges if row["object"] == scope.curie)
        assert prediction["source_column"] == scope.source_column
        assert prediction["value"] == scope.source_literal
        assert prediction["source_record"].startswith("sha256:")
        assert (prediction["predicate"], prediction["relation"]) == ("biolink:capable_of", "RO:0002215")
        assert (prediction["primary_knowledge_source"], prediction["knowledge_level"], prediction["agent_type"]) == (
            "infores:faprotax",
            "prediction",
            "computational_model",
        )
        historical = nodes[prediction["original_object"]]
        assert historical["name"] == scope.source_literal
        assert historical["description"] != scope.description
        independent = next(
            row
            for row in edges
            if row["source_column"] == "Bergey_Type_of_metabolism" and row["value"] == scope.source_literal
        )
        assert independent["object"] == prediction["original_object"]
        assert not independent["original_object"]


@pytest.mark.parametrize("literal", ["fermentation", "chemoheterotrophy"])
def test_conflicting_native_and_source_scope_policies_abort_before_outputs(tmp_path, literal):
    """Do not silently choose table precedence when curated meanings conflict."""
    transform = _transform(tmp_path)
    transform.run(
        data_file=_write_source(tmp_path, [{"LPSN_ID": "101", "FAPROTAX_Type_of_metabolism": "nitrification"}])
    )
    before = {path: path.read_bytes() for path in (transform.output_node_file, transform.output_edge_file)}
    rows = _rows(transform.process_scopes)
    rows[0]["source_literal"] = literal
    with transform.process_scopes.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="Conflicting process scope"):
        transform.run(data_file=tmp_path / "source.csv")
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    "mutation",
    [None, "description", "provided_by", "name", "category", "original_object", "source_column", "value", "orphan"],
)
def test_inventory_requires_complete_scoped_declaration_and_source_use(tmp_path, mutation):
    """A declared process meaning cannot validate mutated ownership or unrelated assertions."""
    transform = _transform(tmp_path)
    transform.run(
        data_file=_write_source(tmp_path, [{"LPSN_ID": "101", "FAPROTAX_Type_of_metabolism": "nitrification"}])
    )
    if mutation is not None:
        node_fields = {"description", "provided_by", "name", "category"}
        path = transform.output_node_file if mutation in node_fields else transform.output_edge_file
        rows = _rows(path)
        fields = list(rows[0])
        if mutation in node_fields:
            row = next(row for row in rows if row["id"].startswith("kgmicrobe.pathway:"))
            row[mutation] = ""
        elif mutation == "orphan":
            rows = []
        else:
            rows[0][mutation] = "changed"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    args = (
        transform.output_dir,
        tmp_path / "inventory",
        transform.process_mappings,
        tmp_path / "ontologies/metpo_nodes.tsv",
    )
    if mutation is not None:
        with pytest.raises(ValueError):
            inventory.review(*args, process_scopes=transform.process_scopes)
        assert not (tmp_path / "inventory").exists()
    else:
        report = inventory.review(*args, process_scopes=transform.process_scopes)
        assert report["source_defined_process_nodes"] == 1
        assert report["edge_rows_by_disposition"] == {"reviewed_source_defined_process": 1}
