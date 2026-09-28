"""Project only METPO's explicit native biological-process class branch (#1216)."""

import csv
import shutil
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

FIXTURES = Path(__file__).parent / "resources/metpo_process_categories"
ROOT = "METPO:1000630"
PROCESSES = {ROOT, "METPO:1000060", "METPO:1002005", "METPO:1000844", "METPO:1005039"}


def _bundle(tmp_path):
    """Copy the immutable native excerpt; never touch generated production outputs."""
    nodes, edges = tmp_path / "metpo_nodes.tsv", tmp_path / "metpo_edges.tsv"
    shutil.copyfile(FIXTURES / "nodes.tsv", nodes)
    shutil.copyfile(FIXTURES / "edges.tsv", edges)
    return nodes, edges


def _read(path):
    """Read small immutable/temporary test tables without type inference."""
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _write(path, rows):
    """Write an intentionally changed private authority fixture."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _project(nodes):
    """Exercise the production category hook without unrelated ontology downloads."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform._fix_node_categories(nodes, "metpo")
    return _read(nodes)


def test_asserted_process_branch_is_typed_and_other_fields_stay_unchanged(tmp_path):
    """The three consumer targets and their native ancestors become processes, not phenotypes."""
    nodes, edges = _bundle(tmp_path)
    before = {row["id"]: row for row in _read(nodes)}
    edge_bytes = edges.read_bytes()
    after = _project(nodes)
    assert {row["id"] for row in after if row["category"] == "biolink:BiologicalProcess"} == PROCESSES
    for row in after:
        expected = dict(before[row["id"]])
        if row["id"] in PROCESSES:
            expected["category"] = "biolink:BiologicalProcess"
        assert row == expected
    assert edges.read_bytes() == edge_bytes
    once = nodes.read_bytes()
    _project(nodes)
    assert nodes.read_bytes() == once


def test_imported_categories_retain_existing_deprecation_cleanup(tmp_path):
    """Specializing METPO must not bypass the previous generic category scrub."""
    nodes, _ = _bundle(tmp_path)
    rows = _read(nodes)
    rows.append({"id": "CHEBI:15377", "name": "water", "category": "biolink:ChemicalSubstance", "deprecated": ""})
    _write(nodes, rows)
    result = _project(nodes)
    imported = next(row for row in result if row["id"] == "CHEBI:15377")
    assert imported["category"] == "biolink:ChemicalEntity"
    assert {row["id"] for row in result if row["category"] == "biolink:BiologicalProcess"} == PROCESSES


@pytest.mark.parametrize("predicate", ["is_a", "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf"])
def test_native_subclass_spelling_and_uncompacted_metpo_ids_are_supported(tmp_path, predicate):
    """Categorization precedes the normal generic IRI-compaction stage."""
    nodes, edges = _bundle(tmp_path)
    node_rows, edge_rows = _read(nodes), _read(edges)
    for row in node_rows:
        row["id"] = row["id"].replace("METPO:", "https://w3id.org/metpo/")
    for row in edge_rows:
        row["predicate"] = predicate
        for field in ("subject", "object"):
            row[field] = row[field].replace("METPO:", "https://w3id.org/metpo/")
    _write(nodes, node_rows)
    _write(edges, edge_rows)
    result = _project(nodes)
    assert {
        row["id"].replace("https://w3id.org/metpo/", "METPO:")
        for row in result
        if row["category"] == "biolink:BiologicalProcess"
    } == PROCESSES


@pytest.mark.parametrize("predicate", ["rdf:type", "owl:equivalentClass", "skos:exactMatch", "biolink:part_of"])
def test_metadata_equivalence_and_part_of_edges_do_not_supply_process_ancestry(tmp_path, predicate):
    """An unrelated phenotype does not become a process through a non-subclass edge."""
    nodes, edges = _bundle(tmp_path)
    rows = _read(edges)
    rows.append({"subject": "METPO:1000059", "predicate": predicate, "object": ROOT, "relation": predicate})
    _write(edges, rows)
    result = _project(nodes)
    assert {row["id"] for row in result if row["category"] == "biolink:BiologicalProcess"} == PROCESSES


def test_imported_property_deprecated_and_unnamed_branches_do_not_propagate(tmp_path):
    """Only active named native class declarations can supply a process path."""
    nodes, edges = _bundle(tmp_path)
    rows, links = _read(nodes), _read(edges)
    for identifier, name, deprecated in (
        ("GO:0008150", "biological_process", ""),
        ("METPO:1999991", "obsolete process", "true"),
        ("METPO:1999992", "child of obsolete process", ""),
        ("METPO:1999993", "", ""),
        ("METPO:1999994", "child of unnamed process", ""),
    ):
        rows.append({"id": identifier, "name": name, "category": "biolink:OntologyClass", "deprecated": deprecated})
    for child, parent in (
        ("GO:0008150", ROOT),
        ("METPO:2000011", ROOT),
        ("METPO:1999991", ROOT),
        ("METPO:1999992", "METPO:1999991"),
        ("METPO:1999993", ROOT),
        ("METPO:1999994", "METPO:1999993"),
    ):
        links.append(
            {"subject": child, "predicate": "biolink:subclass_of", "object": parent, "relation": "rdfs:subClassOf"}
        )
    _write(nodes, rows)
    _write(edges, links)
    result = _project(nodes)
    assert {row["id"] for row in result if row["category"] == "biolink:BiologicalProcess"} == PROCESSES


def test_a_disconnected_class_and_cycle_stay_untyped(tmp_path):
    """Classify from directed ancestry, never a label or graph connected component."""
    nodes, edges = _bundle(tmp_path)
    rows = _read(edges)
    rows = [row for row in rows if row["subject"] != "METPO:1002005"]
    rows.append(
        {
            "subject": "METPO:1000059",
            "predicate": "biolink:subclass_of",
            "object": "METPO:1000631",
            "relation": "rdfs:subClassOf",
        }
    )
    _write(edges, rows)
    result = _project(nodes)
    assert {row["id"] for row in result if row["category"] == "biolink:BiologicalProcess"} == PROCESSES - {
        "METPO:1002005"
    }


@pytest.mark.parametrize("child,parent", [(ROOT, "METPO:1000060"), (ROOT, ROOT), ("METPO:1000060", "METPO:1002005")])
def test_process_branch_cycles_abort_without_rewriting(tmp_path, child, parent):
    """Never certify cyclic selected ancestry or recurse indefinitely."""
    nodes, edges = _bundle(tmp_path)
    rows = _read(edges)
    rows.append({"subject": child, "predicate": "biolink:subclass_of", "object": parent, "relation": "rdfs:subClassOf"})
    _write(edges, rows)
    before = nodes.read_bytes()
    with pytest.raises(ValueError, match="Cycle"):
        _project(nodes)
    assert nodes.read_bytes() == before


def test_diamond_ancestry_is_not_a_cycle(tmp_path):
    """A multiply inherited process remains supported by both named paths."""
    nodes, edges = _bundle(tmp_path)
    rows = _read(edges)
    rows.append(
        {"subject": "METPO:1002005", "predicate": "biolink:subclass_of", "object": ROOT, "relation": "rdfs:subClassOf"}
    )
    _write(edges, rows)
    assert {row["id"] for row in _project(nodes) if row["category"] == "biolink:BiologicalProcess"} == PROCESSES


@pytest.mark.parametrize(
    "fault",
    [
        "missing_root",
        "changed_root",
        "deprecated_root",
        "duplicate_root",
        "invalid_status",
        "missing_edges",
        "header_only",
        "missing_column",
        "duplicate_column",
        "ragged",
        "empty_cell",
        "missing_endpoint",
        "conflicting_relation",
    ],
)
def test_missing_or_malformed_support_aborts_without_rewriting(tmp_path, fault):
    """Reject unavailable or inconsistent source evidence instead of guessing a class."""
    nodes, edges = _bundle(tmp_path)
    rows, links = _read(nodes), _read(edges)
    if fault == "missing_root":
        rows = [row for row in rows if row["id"] != ROOT]
    elif fault == "changed_root":
        rows[0]["name"] = "another concept"
    elif fault == "deprecated_root":
        rows[0]["deprecated"] = "true"
    elif fault == "duplicate_root":
        rows.append(dict(rows[0]))
    elif fault == "invalid_status":
        rows[0]["deprecated"] = "unknown"
    _write(nodes, rows)
    if fault == "missing_edges":
        edges.unlink()
    elif fault == "header_only":
        edges.write_text(edges.read_text().splitlines()[0] + "\n")
    elif fault == "missing_column":
        edges.write_text("subject\tobject\n")
    elif fault == "duplicate_column":
        edges.write_text("subject\tpredicate\tobject\tobject\n")
    elif fault == "ragged":
        edges.write_text(edges.read_text() + "METPO:1005039\tbiolink:subclass_of\n")
    elif fault == "empty_cell":
        links[0]["object"] = ""
        _write(edges, links)
    elif fault == "missing_endpoint":
        links[0]["subject"] = "METPO:1999999"
        _write(edges, links)
    elif fault == "conflicting_relation":
        links[0]["relation"] = "rdf:type"
        _write(edges, links)
    before = nodes.read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        _project(nodes)
    assert nodes.read_bytes() == before


def test_no_process_branch_can_leak_between_sequential_ontology_files(tmp_path):
    """No successful classification is cached across a later changed source pair."""
    nodes, edges = _bundle(tmp_path)
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform._fix_node_categories(nodes, "metpo")
    _bundle(tmp_path)
    links = [row for row in _read(edges) if row["subject"] != "METPO:1002005"]
    _write(edges, links)
    transform._fix_node_categories(nodes, "metpo")
    assert next(row for row in _read(nodes) if row["id"] == "METPO:1002005")["category"] == "biolink:OntologyClass"


def test_missing_node_columns_are_rejected(tmp_path):
    """The root must be an actual named declaration, not a missing table field."""
    _, edges = _bundle(tmp_path)
    with pytest.raises(ValueError, match="declaration columns"):
        OntologiesTransform._metpo_process_classes(pd.DataFrame({"id": [ROOT]}), edges)
