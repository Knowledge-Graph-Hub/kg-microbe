"""Tests for summaries of loose and archived merged graphs."""

import importlib.util
import tarfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "graph_summary.py"
SPEC = importlib.util.spec_from_file_location("graph_summary", SCRIPT)
assert SPEC and SPEC.loader
graph_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph_summary)

NODES = "id\tcategory\nNCBITaxon:1\tbiolink:OrganismTaxon\nCHEBI:1\tbiolink:ChemicalEntity\n"
EDGES = (
    "subject\tpredicate\tobject\n"
    "NCBITaxon:1\tbiolink:related_to\tmedium:1\n"
    "NCBITaxon:1\tbiolink:related_to\ttemperature:high\n"
)


def write_graph(directory: Path) -> None:
    """Write a tiny merged TSV pair."""
    directory.mkdir(exist_ok=True)
    (directory / "merged-kg_nodes.tsv").write_text(NODES)
    (directory / "merged-kg_edges.tsv").write_text(EDGES)


def test_summary_reads_loose_files(tmp_path: Path) -> None:
    """Loose merged TSVs remain supported."""
    write_graph(tmp_path)
    summary = graph_summary.summarize(tmp_path)
    assert "NODES\t2" in summary
    assert "taxon -> medium\t1" in summary


def test_summary_reads_default_merge_archive(tmp_path: Path) -> None:
    """The default tar.gz output can be summarized without extraction."""
    source = tmp_path / "source"
    output = tmp_path / "output"
    write_graph(source)
    output.mkdir()
    with tarfile.open(output / "merged-kg.tar.gz", "w:gz") as archive:
        archive.add(source / "merged-kg_nodes.tsv", arcname="merged-kg_nodes.tsv")
        archive.add(source / "merged-kg_edges.tsv", arcname="merged-kg_edges.tsv")
    assert graph_summary.summarize(output) == graph_summary.summarize(source)
