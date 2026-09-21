"""Exclude reviewed ontology query-graph loops without deleting unrelated assertions."""

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies import ontologies_transform as module

FIXTURE = Path(__file__).parent / "resources/ontology_self_loops.json"
EDGE_HEADER = [
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


@pytest.fixture(autouse=True)
def isolated_foodon_authority(tmp_path, monkeypatch):
    """Never consult a developer's downloaded ontology during fixture normalization."""
    from kg_microbe.utils import foodon_classification

    monkeypatch.setattr(foodon_classification, "FOODON_GRAPH", tmp_path / "absent_foodon.json")


def _rows(path):
    """Read the small quoted transform/audit fixture, not a finalized graph."""
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _prepare(tmp_path, source):
    """Configure the normalization boundary without adapters or live data."""
    transform = module.OntologiesTransform.__new__(module.OntologiesTransform)
    transform.edge_header = EDGE_HEADER
    transform.node_header = ["id", "category", "name"]
    transform.output_dir = tmp_path
    records = json.loads(FIXTURE.read_text())
    edges = tmp_path / f"{source}_edges.tsv"
    pd.DataFrame(records).to_csv(edges, sep="\t", index=False)
    return transform, edges, records


@pytest.mark.parametrize("source", ["uberon", "foodon", "envo"])
def test_reviewed_loops_and_imported_copies_are_audited_with_original_evidence(tmp_path, source):
    """Match all four assertion fields, regardless of the importing ontology."""
    transform, edges, records = _prepare(tmp_path, source)
    transform._normalize_schema(tmp_path / "absent_nodes.tsv", edges)
    expected = [{key: row[key] for key in EDGE_HEADER} for row in records[2:]]
    assert _rows(edges) == expected
    report = tmp_path / f"{source}_self_loop_exclusions.tsv"
    excluded = _rows(report)
    assert [json.loads(row["original_record_json"]) for row in excluded] == records[:2]
    assert all(row["reason"] and row["source_file"] == edges.name for row in excluded)
    assert {row["primary_knowledge_source"] for row in excluded} == {"infores:uberon", "infores:foodon"}
    assert b"\r\n" not in report.read_bytes()


def test_clean_rebuild_replaces_stale_report_and_keeps_node_declarations(tmp_path):
    """Only the reviewed edge assertions disappear; no stale report survives a clean input."""
    transform, edges, _ = _prepare(tmp_path, "uberon")
    nodes = tmp_path / "uberon_nodes.tsv"
    pd.DataFrame(
        [["PR:000000001", "biolink:Protein", "protein"], ["FOODON:02021808", "biolink:Food", "cod material"]],
        columns=transform.node_header,
    ).to_csv(nodes, sep="\t", index=False)
    transform._normalize_schema(nodes, edges)
    first_edges = edges.read_bytes()
    report = tmp_path / "uberon_self_loop_exclusions.tsv"
    assert len(_rows(report)) == 2
    assert {row["id"] for row in _rows(nodes)} == {"PR:000000001", "FOODON:02021808"}
    transform._normalize_schema(nodes, edges)
    assert edges.read_bytes() == first_edges
    assert _rows(report) == []
    assert report.read_text().startswith("source_file\t")


def test_normal_postprocessing_compacts_url_endpoints_before_loop_exclusion(tmp_path):
    """The production postprocessing entry point cannot bypass the exclusion via IRI spelling."""
    transform, edges, records = _prepare(tmp_path, "uberon")
    records = records[:3]
    for row in records:
        for column in ("subject", "object"):
            row[column] = "http://purl.obolibrary.org/obo/" + row[column].replace(":", "_")
    pd.DataFrame(records).to_csv(edges, sep="\t", index=False)
    nodes = tmp_path / "uberon_nodes.tsv"
    pd.DataFrame(
        [["http://purl.obolibrary.org/obo/PR_000000001", "biolink:Protein", "protein"]],
        columns=transform.node_header,
    ).to_csv(nodes, sep="\t", index=False)
    transform.post_process("uberon")
    assert [(row["subject"], row["object"]) for row in _rows(edges)] == [("PR:000000001", "PR:000000002")]
    assert len(_rows(tmp_path / "uberon_self_loop_exclusions.tsv")) == 2


def test_exclusion_curation_participates_in_source_fingerprints():
    """Changing the curation must invalidate the ontology producer's freshness marker."""
    assert "mappings/ontology_self_loop_exclusions.tsv" in module.OntologiesTransform.DATA_INPUTS


@pytest.mark.parametrize(
    "fault",
    [
        "header",
        "nonself",
        "relation",
        "duplicate",
        "reason",
        "width",
        "blank_reason",
        "padded_subject",
        "padded_predicate",
        "padded_object",
        "padded_relation",
    ],
)
def test_invalid_exclusion_policy_aborts_without_filtering_edge_file(tmp_path, monkeypatch, fault):
    """Malformed curation cannot silently broaden, weaken or partially apply the filter."""
    transform, edges, _ = _prepare(tmp_path, "uberon")
    original = edges.read_bytes()
    header = "subject\tpredicate\tobject\trelation\treason\n"
    row = ["PR:000000001", "biolink:has_part", "PR:000000001", "BFO:0000051", "reviewed"]
    if fault == "header":
        header = "bad\theader\n"
    elif fault == "nonself":
        row[2] = "PR:000000002"
    elif fault == "relation":
        row[3] = "BFO:0000050"
    elif fault == "reason":
        row[4] = ""
    elif fault == "blank_reason":
        row[4] = "   "
    elif fault.startswith("padded_"):
        column = ["subject", "predicate", "object", "relation"].index(fault.removeprefix("padded_"))
        row[column] += " "
        if column in (0, 2):
            row[2 - column] += " "
    elif fault == "width":
        row.append("unexpected")
    content = "\t".join(row) + "\n"
    policy = tmp_path / "exclusions.tsv"
    policy.write_text(header + content * (2 if fault == "duplicate" else 1))
    monkeypatch.setattr(module, "SELF_LOOP_EXCLUSIONS_FILE", policy)
    with pytest.raises(ValueError, match="self-loop exclusion"):
        transform._normalize_schema(tmp_path / "absent_nodes.tsv", edges)
    assert edges.read_bytes() == original
    assert not (tmp_path / "uberon_self_loop_exclusions.tsv").exists()
