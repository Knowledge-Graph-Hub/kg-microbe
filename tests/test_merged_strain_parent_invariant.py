"""The merged graph is where a shared namespace can be policed (#896)."""

import csv
from pathlib import Path

from kg_microbe.merge_utils.invariants import (
    STRAIN_PARENT_REPORT,
    STRAIN_PARENT_REPORT_HEADER,
    check_merged_invariants,
    find_multi_parent_strains,
    strain_parent_rows,
)

HEADER = [
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


def _edges(tmp_path: Path, rows, header=HEADER) -> Path:
    path = tmp_path / "merged-kg_edges.tsv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _row(subject, obj, predicate="biolink:subclass_of", source="infores:bacdive"):
    return [subject, predicate, obj, "rdfs:subClassOf", source, "observation", "manual_agent"]


def test_one_parent_per_strain_is_not_a_violation(tmp_path):
    """The ordinary case must stay silent, or the report is noise."""
    path = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-20154", "NCBITaxon:272240")])
    assert find_multi_parent_strains(path) == {}


def test_two_parents_on_one_strain_is_caught(tmp_path):
    """`ATCC 13722` carried two genera in the 20260815 build; that is the shape."""
    path = _edges(
        tmp_path,
        [
            _row("kgmicrobe.strain:ATCC-13722", "NCBITaxon:272240"),
            _row("kgmicrobe.strain:ATCC-13722", "NCBITaxon:1915061"),
        ],
    )
    found = find_multi_parent_strains(path)
    assert set(found) == {"kgmicrobe.strain:ATCC-13722"}
    parents, _ = found["kgmicrobe.strain:ATCC-13722"]
    assert parents == {"NCBITaxon:272240", "NCBITaxon:1915061"}


def test_the_same_parent_asserted_twice_is_not_a_violation(tmp_path):
    """
    Two sources agreeing is the merge working, not a conflict.

    The rule is about *distinct* parents; counting rows would fire on every
    strain BacDive and a future source both describe correctly.
    """
    path = _edges(
        tmp_path,
        [
            _row("kgmicrobe.strain:DSM-1", "NCBITaxon:5", source="infores:bacdive"),
            _row("kgmicrobe.strain:DSM-1", "NCBITaxon:5", source="infores:lpsn"),
        ],
    )
    assert find_multi_parent_strains(path) == {}


def test_the_report_names_which_sources_to_go_and_fix(tmp_path):
    """
    A count alone does not say who reintroduced it.

    The check exists because a *future* source could add a competing parent, so
    the report has to point at the source rather than just the node.
    """
    path = _edges(
        tmp_path,
        [
            _row("kgmicrobe.strain:X-1", "NCBITaxon:1", source="infores:bacdive"),
            _row("kgmicrobe.strain:X-1", "NCBITaxon:2", source="infores:somewhere-new"),
        ],
    )
    rows = strain_parent_rows(find_multi_parent_strains(path))
    assert rows == [["kgmicrobe.strain:X-1", 2, "NCBITaxon:1|NCBITaxon:2", "infores:bacdive|infores:somewhere-new"]]
    assert len(rows[0]) == len(STRAIN_PARENT_REPORT_HEADER)


def test_only_subclass_of_to_ncbitaxon_counts(tmp_path):
    """
    `close_match` to a deposit and `subclass_of` to an LPSN record are not parents.

    Counting every edge out of a strain node would fire on the record-to-deposit
    links (#894) and on microbedecoder's strain -> lpsn edges, neither of which
    is a taxonomic parent.
    """
    path = _edges(
        tmp_path,
        [
            _row("kgmicrobe.strain:bacdive_1", "NCBITaxon:5"),
            _row("kgmicrobe.strain:bacdive_1", "kgmicrobe.strain:ATCC-1", predicate="biolink:close_match"),
            _row("kgmicrobe.strain:bacdive_1", "lpsn:12345"),
        ],
    )
    assert find_multi_parent_strains(path) == {}


def test_a_clean_run_still_writes_the_report(tmp_path):
    """
    An absent report is indistinguishable from a check that never ran.

    A clean merge is the thing worth being able to demonstrate, so the file is
    written empty rather than skipped.
    """
    path = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-1", "NCBITaxon:5")])
    assert check_merged_invariants(path) == 0
    report = tmp_path / STRAIN_PARENT_REPORT
    assert report.is_file()
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines == ["\t".join(STRAIN_PARENT_REPORT_HEADER)]


def test_an_edge_file_without_the_expected_columns_is_skipped_not_crashed(tmp_path):
    """A merge that took hours must not die on a header this check did not expect."""
    path = _edges(tmp_path, [["a", "b"]], header=["something", "else"])
    assert find_multi_parent_strains(path) == {}


def test_an_empty_edge_file_is_survivable(tmp_path):
    """No header at all should not raise."""
    path = tmp_path / "merged-kg_edges.tsv"
    path.write_text("", encoding="utf-8")
    assert find_multi_parent_strains(path) == {}
