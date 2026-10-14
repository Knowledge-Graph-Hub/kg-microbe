"""A stub declared only in an ontology node file the merge leaves out is named with that file (#1556)."""

import csv
import json
import logging

from kg_microbe.merge_utils.invariants import (
    STUB_NODE_DETAILS_REPORT,
    check_merged_invariants,
    stubs_declared_in,
    unmerged_declaration_files,
)


def _layout(tmp_path):
    """
    Lay out a merged source, the ontology node files its finalization counted, and a merged graph.

    The source counted ``chebi_nodes.tsv`` and ``mondo_nodes.tsv`` as declarations; the
    merge includes the first only, so a reference to ``NCBITaxon:9``, which only MONDO's
    file declares, arrives as a KGX invention.
    """
    ontologies = tmp_path / "transformed" / "ontologies"
    source = tmp_path / "transformed" / "bacdive"
    ontologies.mkdir(parents=True)
    source.mkdir()
    (ontologies / "chebi_nodes.tsv").write_text("id\tcategory\tname\nCHEBI:1\tbiolink:ChemicalEntity\tx\n")
    (ontologies / "mondo_nodes.tsv").write_text("id\tcategory\tname\nNCBITaxon:9\tbiolink:OrganismTaxon\tBuchnera\n")
    for name in ("nodes.tsv", "edges.tsv"):
        (source / name).write_text("id\n")
    finalized = ["chebi_nodes.tsv", "mondo_nodes.tsv"]
    (ontologies / "source_finalization.json").write_text(json.dumps({"members": dict.fromkeys(finalized, {})}))
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "GOLD_nodes.tsv").write_text("id\nNCBITaxon:9\n")
    record = {
        "inputs": [
            {"path": str(ontologies / "chebi_nodes.tsv"), "sha256": "0"},
            {"path": str(ontologies / "mondo_nodes.tsv"), "sha256": "0"},
            {"path": str(ontologies / "gone_nodes.tsv"), "sha256": "0"},
            {"path": str(tmp_path / "raw" / "bacdive_strains.json"), "sha256": "0"},
            {"path": str(raw / "GOLD_nodes.tsv"), "sha256": "0"},
        ]
    }
    (source / "source_finalization.json").write_text(json.dumps(record))
    merged = [source / "nodes.tsv", source / "edges.tsv", ontologies / "chebi_nodes.tsv"]
    nodes, edges = tmp_path / "merged-kg_nodes.tsv", tmp_path / "merged-kg_edges.tsv"
    nodes.write_text("id\tcategory\tname\nNCBITaxon:9\tbiolink:NamedThing\t\nGO:1\tbiolink:NamedThing\t\n")
    edges.write_text(
        "subject\tpredicate\tobject\tprimary_knowledge_source\n"
        "kgmicrobe.strain:1\tbiolink:subclass_of\tNCBITaxon:9\tinfores:bacdive\n"
        "kgmicrobe.strain:1\tbiolink:related_to\tGO:1\tinfores:bacdive\n"
    )
    return ontologies, merged, nodes, edges


def test_the_files_counted_but_not_merged_are_found(tmp_path):
    """Only recorded, existing, finalized node files the merge does not read; never a raw input."""
    ontologies, merged, _, _ = _layout(tmp_path)
    assert unmerged_declaration_files(merged) == [(ontologies / "mondo_nodes.tsv").resolve()]
    assert unmerged_declaration_files([*merged, ontologies / "mondo_nodes.tsv"]) == []


def test_the_stub_is_named_with_the_file_that_declares_it(tmp_path, caplog):
    """The detail report says why the reference became a stub; the warning counts it per file."""
    _, merged, nodes, edges = _layout(tmp_path)
    with caplog.at_level(logging.WARNING, logger="kg_microbe.merge_utils.invariants"):
        check_merged_invariants(
            edges, tmp_path, nodes_file=nodes, unmerged_declarations=unmerged_declaration_files(merged)
        )
    with (tmp_path / STUB_NODE_DETAILS_REPORT).open() as handle:
        rows = {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    assert rows["NCBITaxon:9"]["declared_outside_merge"] == "mondo_nodes.tsv"
    assert rows["GO:1"]["declared_outside_merge"] == ""
    assert "this merge does not include that file (mondo_nodes.tsv: 1)" in caplog.text


def test_without_the_files_the_column_is_empty(tmp_path, caplog):
    """A caller that passes none gets the column, empty, and no such warning."""
    _, _, nodes, edges = _layout(tmp_path)
    check_merged_invariants(edges, tmp_path, nodes_file=nodes)
    with (tmp_path / STUB_NODE_DETAILS_REPORT).open() as handle:
        assert {row["declared_outside_merge"] for row in csv.DictReader(handle, delimiter="\t")} == {""}
    assert "does not include that file" not in caplog.text


def test_an_over_limit_cell_does_not_end_the_lookup(tmp_path):
    """Ontology descriptions can exceed CSV's default field limit; the caller's limit is restored."""
    path = tmp_path / "hp_nodes.tsv"
    path.write_text("id\tdescription\nHP:1\t" + "x" * 200_000 + "\nHP:2\ty\n")
    before = csv.field_size_limit()
    assert stubs_declared_in({"HP": ["HP:2"]}, [path]) == {"HP:2": ["hp_nodes.tsv"]}
    assert csv.field_size_limit() == before


def test_the_merge_passes_the_files_its_sources_counted(monkeypatch, tmp_path):
    """The merge derives the list from its own configuration, not from a guessed directory."""
    import kg_microbe.merge_utils.merge_kg as merge_kg

    ontologies, merged, _, _ = _layout(tmp_path)
    received = {}

    def capture(*_args, **kwargs):
        """Record what the merge hands the invariants."""
        received.update(kwargs)

    monkeypatch.setattr(merge_kg, "check_merged_invariants", capture)

    def validated(_nodes, _edges, report, **_kwargs):
        """Stand in for validation, leaving the empty reference report it would write."""
        report.write_text("")
        return {}

    monkeypatch.setattr(merge_kg, "write_merge_validation_report", validated)
    monkeypatch.setattr(merge_kg, "_rewrite_tarball", lambda *_a, **_k: None)
    monkeypatch.setattr(merge_kg, "_warn_about_stale_siblings", lambda *_a: None)
    out = tmp_path / "merged"
    out.mkdir()
    (out / "merged-kg_nodes.tsv").write_text("id\tcategory\tname\tdescription\tprovided_by\n")
    (out / "merged-kg_edges.tsv").write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\n"
    )
    files = "".join(f"            - {path}\n" for path in merged)
    config = tmp_path / "merge.yaml"
    config.write_text(
        f"configuration:\n  output_directory: {out}\n"
        "merged_graph:\n"
        "  source:\n"
        "    bacdive:\n"
        "      input:\n"
        "        format: tsv\n"
        "        filename:\n" + files + "  destination:\n"
        "    merged-kg-tsv:\n"
        "      format: tsv\n"
        "      filename: merged-kg\n"
    )
    merge_kg._cleanup_merged_outputs(str(config))
    assert received["unmerged_declarations"] == [(ontologies / "mondo_nodes.tsv").resolve()]
