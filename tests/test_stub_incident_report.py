"""Per-ID source attribution makes anonymous-node gaps actionable (#1073)."""

import csv

import pytest

from kg_microbe.merge_utils.invariants import (
    STUB_NODE_DETAILS_HEADER,
    STUB_NODE_DETAILS_REPORT,
    check_merged_invariants,
    stub_incident_rows,
)


def test_every_stub_is_reported_with_both_endpoint_directions(tmp_path):
    """Do not hide the fourth ID of a prefix or double-count a self-loop."""
    edges = tmp_path / "graph_edges.tsv"
    edges.write_text(
        "subject\tpredicate\tobject\tprimary_knowledge_source\tprimary_knowledge_source\n"
        "GO:1\tbiolink:related_to\tGO:2\tinfores:upa\twrong\n"
        "GO:1\tbiolink:related_to\tGO:1\tinfores:rhea\twrong\n"
        "GO:3\tbiolink:related_to\tGO:4\tinfores:upa\twrong\n"
        "IMG:1\tbiolink:related_to\tGO:4\tinfores:gold\twrong\n",
        encoding="utf-8",
    )
    nodes = tmp_path / "graph_nodes.tsv"
    nodes.write_text(
        "id\tcategory\tname\n"
        + "".join(f"{curie}\tbiolink:NamedThing\t\n" for curie in ["GO:1", "GO:2", "GO:3", "GO:4", "IMG:1"]),
        encoding="utf-8",
    )
    check_merged_invariants(edges, nodes_file=nodes)
    with (tmp_path / STUB_NODE_DETAILS_REPORT).open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        assert reader.fieldnames == STUB_NODE_DETAILS_HEADER
        rows = {row["id"]: row for row in reader}
    assert len(rows) == 5
    assert rows["GO:1"]["incident_edges"] == "2"
    assert rows["GO:1"]["knowledge_sources"] == "infores:rhea|infores:upa"
    assert rows["GO:4"]["incident_edges"] == "2"
    assert rows["GO:4"]["expected"] == "no"
    assert rows["IMG:1"]["expected"] == "yes"
    assert rows["IMG:1"]["note"]


def test_report_retains_unconnected_candidates_and_rejects_bad_schema(tmp_path):
    """Missing edge columns are an explicit failure, not a clean attribution result."""
    edges = tmp_path / "edges.tsv"
    edges.write_text("subject\tpredicate\tobject\tprimary_knowledge_source\n", encoding="utf-8")
    rows = stub_incident_rows(edges, {"GO": ["GO:1"]})
    assert rows == [["GO:1", "no", "", 0, "", ""]]
    edges.write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lacks"):
        stub_incident_rows(edges, {"GO": ["GO:1"]})


def test_empty_graph_still_gets_header_only_detail_report(tmp_path):
    """A clean run has an explicit artifact rather than an absent report."""
    edges = tmp_path / "graph_edges.tsv"
    nodes = tmp_path / "graph_nodes.tsv"
    edges.write_text("subject\tpredicate\tobject\n", encoding="utf-8")
    nodes.write_text("id\tcategory\tname\n", encoding="utf-8")
    check_merged_invariants(edges, nodes_file=nodes)
    assert (tmp_path / STUB_NODE_DETAILS_REPORT).read_text() == "\t".join(STUB_NODE_DETAILS_HEADER) + "\n"


def test_quoted_source_cells_keep_their_logical_value(tmp_path):
    """Decode TSV transport quoting without evaluating legacy provenance text."""
    edges = tmp_path / "edges.tsv"
    legacy = '["infores:bacdive", "bacdive:1"]'
    with edges.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["subject", "predicate", "object", "primary_knowledge_source"])
        writer.writerow(["GO:1", "biolink:related_to", "GO:2", legacy])
    assert stub_incident_rows(edges, {"GO": ["GO:1"]})[0][-1] == legacy
