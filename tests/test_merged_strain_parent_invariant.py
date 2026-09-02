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


def test_a_failing_check_cannot_stop_the_tarball_being_rewritten(monkeypatch, tmp_path):
    """
    A data-quality report must not decide whether the artifact ships (#914).

    `_cleanup_merged_outputs` is wrapped by a blanket handler in `load_and_merge`,
    so an exception raised by the check would skip `_rewrite_tarball` and leave
    normalized TSVs beside a stale archive while the merge reported success.
    """
    import kg_microbe.merge_utils.merge_kg as merge_kg

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated check failure")

    monkeypatch.setattr(merge_kg, "check_merged_invariants", boom)

    rewritten = []
    monkeypatch.setattr(merge_kg, "_rewrite_tarball", lambda archive, files: rewritten.append(archive))
    monkeypatch.setattr(merge_kg, "_normalize_nodes_tsv", lambda _p: None)
    monkeypatch.setattr(merge_kg, "_normalize_edges_tsv", lambda _p: None)
    monkeypatch.setattr(merge_kg, "_warn_about_stale_siblings", lambda *_a: None)

    (tmp_path / "merged-kg_nodes.tsv").write_text("id\n", encoding="utf-8")
    (tmp_path / "merged-kg_edges.tsv").write_text("subject\n", encoding="utf-8")
    config = tmp_path / "merge.yaml"
    config.write_text(
        "merged_graph:\n"
        "  destination:\n"
        "    merged-kg-tsv:\n"
        "      format: tsv\n"
        "      compression: tar.gz\n"
        f"      filename: {tmp_path / 'merged-kg'}\n",
        encoding="utf-8",
    )

    merge_kg._cleanup_merged_outputs(str(config))
    assert rewritten, "a failing invariant check suppressed the tarball rewrite"


def test_a_duplicated_column_name_does_not_hide_violations(tmp_path):
    """
    A merged header can repeat a column, and last-wins would read the wrong one (#915).

    KGX takes the column union across sources, which is why `merge_kg` has
    `_first_index`. Resolving last-wins here would find no strain subjects and
    report a clean graph — silent, and in the reassuring direction.
    """
    header = HEADER + ["subject"]
    path = _edges(
        tmp_path,
        [
            _row("kgmicrobe.strain:ATCC-13722", "NCBITaxon:272240") + ["something-else"],
            _row("kgmicrobe.strain:ATCC-13722", "NCBITaxon:1915061") + ["something-else"],
        ],
        header=header,
    )
    found = find_multi_parent_strains(path)
    assert set(found) == {"kgmicrobe.strain:ATCC-13722"}, "a duplicated header hid a real violation"


def _nodes(tmp_path, rows):
    header = ["id", "category", "name", "description", "xref", "provided_by", "synonym", "deprecated", "same_as"]
    path = tmp_path / "merged-kg_nodes.tsv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _node(curie, category="biolink:OrganismTaxon", name="a name"):
    return [curie, category, name, "", "", "infores:x", "", "", ""]


def test_a_named_node_is_not_a_stub(tmp_path):
    """Only nodes KGX invented are of interest; real ones are the whole graph."""
    from kg_microbe.merge_utils.invariants import find_stub_nodes

    path = _nodes(tmp_path, [_node("NCBITaxon:562")])
    assert find_stub_nodes(path) == {}


def test_a_namedthing_with_no_name_is_a_stub(tmp_path):
    """
    That is what KGX writes for an endpoint no source declared.

    It is the shape #892 objected to: an entity with an id, no type worth the
    name, and no label.
    """
    from kg_microbe.merge_utils.invariants import find_stub_nodes

    path = _nodes(tmp_path, [_node("NCBITaxon:999", category="biolink:NamedThing", name="")])
    assert find_stub_nodes(path) == {"NCBITaxon": ["NCBITaxon:999"]}


def test_a_namedthing_that_carries_a_name_is_not_a_stub(tmp_path):
    """
    `biolink:NamedThing` is a legitimate category for a node someone declared.

    Flagging on category alone would report real nodes as inventions.
    """
    from kg_microbe.merge_utils.invariants import find_stub_nodes

    path = _nodes(tmp_path, [_node("X:1", category="biolink:NamedThing", name="declared")])
    assert find_stub_nodes(path) == {}


def test_cross_reference_prefixes_are_marked_expected(tmp_path):
    """
    A GOLD study id names a record in someone else's system.

    We assert edges to those on purpose and never ingest them as nodes, so a
    stub is correct. Reporting them as problems would bury the 19% that are not
    — 49,568 of the 60,990 stubs in `merged/20260815` are of this kind.
    """
    from kg_microbe.merge_utils.invariants import find_stub_nodes, stub_node_rows

    path = _nodes(
        tmp_path,
        [
            _node("GOLD:Go0022271", category="biolink:NamedThing", name=""),
            _node("kgmicrobe.strain:ATCC-1", category="biolink:NamedThing", name=""),
        ],
    )
    rows = {row[0]: row[2] for row in stub_node_rows(find_stub_nodes(path))}
    assert rows == {"GOLD": "yes", "kgmicrobe.strain": "no"}


def test_our_own_namespace_is_never_expected(tmp_path):
    """
    A `kgmicrobe.*` stub means we referenced something we did not declare.

    That can never be someone else's system, so it must not be allowlisted —
    all 4,233 in `merged/20260815` come from LPSN alone (#932).
    """
    from kg_microbe.merge_utils.invariants import EXPECTED_STUB_PREFIXES

    assert not [p for p in EXPECTED_STUB_PREFIXES if p.startswith("kgmicrobe")]


def test_stub_rows_lead_with_the_largest_prefix(tmp_path):
    """A report nobody can skim is a report nobody reads."""
    from kg_microbe.merge_utils.invariants import find_stub_nodes, stub_node_rows

    path = _nodes(
        tmp_path,
        [_node("A:1", category="biolink:NamedThing", name="")]
        + [_node(f"B:{i}", category="biolink:NamedThing", name="") for i in range(3)],
    )
    rows = stub_node_rows(find_stub_nodes(path))
    assert [row[0] for row in rows] == ["B", "A"]


def test_a_nodes_file_without_the_expected_columns_is_skipped_not_crashed(tmp_path):
    """A merge that took hours must not die on an unexpected header."""
    from kg_microbe.merge_utils.invariants import find_stub_nodes

    path = tmp_path / "merged-kg_nodes.tsv"
    path.write_text("something\telse\nx\ty\n", encoding="utf-8")
    assert find_stub_nodes(path) == {}


def test_an_absent_nodes_file_does_not_break_the_edge_checks(tmp_path):
    """
    The strain-parent check needs no nodes file, and callers may point at any edge dump.

    Failing here would make the stub check able to break the check beside it —
    the coupling #914 was filed about.
    """
    path = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-1", "NCBITaxon:5")])
    assert check_merged_invariants(path) == 0
    assert (tmp_path / STRAIN_PARENT_REPORT).is_file()


def test_a_graph_with_no_stubs_still_writes_the_stub_report(tmp_path):
    """
    An absent report cannot be told from a check that never ran (#934).

    Same reasoning as the strain-parent report, which this one sat beside while
    behaving differently — a reader who learns one is always present will
    reasonably assume the same of the other.
    """
    from kg_microbe.merge_utils.invariants import STUB_NODE_REPORT, STUB_NODE_REPORT_HEADER

    _nodes(tmp_path, [_node("NCBITaxon:562")])
    edges = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-1", "NCBITaxon:562")])
    check_merged_invariants(edges)
    report = tmp_path / STUB_NODE_REPORT
    assert report.is_file()
    assert report.read_text(encoding="utf-8").splitlines() == ["\t".join(STUB_NODE_REPORT_HEADER)]


def test_an_absent_nodes_file_writes_no_stub_report(tmp_path):
    """
    Not being able to check is not a clean result.

    Writing an empty report there would claim zero stubs on a graph whose nodes
    were never read.
    """
    from kg_microbe.merge_utils.invariants import STUB_NODE_REPORT

    edges = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-1", "NCBITaxon:5")])
    check_merged_invariants(edges)
    assert not (tmp_path / STUB_NODE_REPORT).exists()


def test_an_expected_prefix_carries_its_justification(tmp_path):
    """
    "Expected" is the claim that most needs justifying, so it must not be bare (#935).

    It separates the 49,568 rows that are fine from the 11,422 that are not, and
    a reader auditing the graph should not have to read the source to learn why.
    """
    from kg_microbe.merge_utils.invariants import (
        EXPECTED_STUB_PREFIXES,
        find_stub_nodes,
        stub_node_rows,
    )

    path = _nodes(
        tmp_path,
        [
            _node("GOLD:Go1", category="biolink:NamedThing", name=""),
            _node("kgmicrobe.strain:ATCC-1", category="biolink:NamedThing", name=""),
        ],
    )
    rows = {row[0]: (row[2], row[3]) for row in stub_node_rows(find_stub_nodes(path))}
    assert rows["GOLD"] == ("yes", EXPECTED_STUB_PREFIXES["GOLD"])
    assert rows["kgmicrobe.strain"][0] == "no"
    assert rows["kgmicrobe.strain"][1] == ""


def test_every_expected_prefix_states_a_reason():
    """A prefix allowlisted without a justification is silently exempted."""
    from kg_microbe.merge_utils.invariants import EXPECTED_STUB_PREFIXES

    unexplained = [p for p, why in EXPECTED_STUB_PREFIXES.items() if not (why or "").strip()]
    assert not unexplained, f"expected without a reason: {unexplained}"


def test_the_nodes_path_can_be_passed_rather_than_guessed(tmp_path):
    """
    A derivation that fails looks exactly like a graph with no stubs (#936).

    `str.replace` leaves the name untouched when the pattern is absent, so a
    destination not using the `_edges`/`_nodes` convention would report clean on
    a graph whose nodes were never opened — reassuring, and wrong.
    """
    from kg_microbe.merge_utils.invariants import STUB_NODE_REPORT

    nodes = tmp_path / "oddly-named-nodes.tsv"
    header = ["id", "category", "name", "description", "xref", "provided_by", "synonym", "deprecated", "same_as"]
    with nodes.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerow(_node("X:1", category="biolink:NamedThing", name=""))
    edges = _edges(tmp_path, [_row("kgmicrobe.strain:DSM-1", "NCBITaxon:5")])

    # Without the path it guesses, finds nothing, and writes no report.
    check_merged_invariants(edges)
    assert not (tmp_path / STUB_NODE_REPORT).exists()

    # Given the path it actually reads the file.
    check_merged_invariants(edges, nodes_file=nodes)
    body = (tmp_path / STUB_NODE_REPORT).read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("X\t1\t") for line in body), body


def test_the_merge_hands_over_the_path_it_already_built():
    """The caller computes both paths from one base; discarding one invites the guess."""
    import inspect

    import kg_microbe.merge_utils.merge_kg as merge_kg

    source = inspect.getsource(merge_kg._cleanup_merged_outputs)
    assert "check_merged_invariants(edges_file, output_dir, nodes_file=nodes_file)" in source
