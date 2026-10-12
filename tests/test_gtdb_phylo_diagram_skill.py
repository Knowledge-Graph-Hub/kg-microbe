"""The GTDB phylo-diagram skill keeps genome assignments out of clade metadata sizes."""

import importlib.util
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".claude/skills/gtdb-phylo-diagram/gtdb_phylo_diagram.py"


def _skill(monkeypatch):
    """Load the standalone skill script as a module, without installing it."""
    spec = importlib.util.spec_from_file_location("gtdb_phylo_diagram_skill", SKILL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_genome_in_taxon_assignment_is_classification_not_metadata(tmp_path, monkeypatch):
    """GTDB assigns assemblies with in_taxon (RO:0002162); those edges must not size the clade."""
    skill = _skill(monkeypatch)
    edges = tmp_path / "edges.tsv"
    edges.write_text(
        "subject\tpredicate\tobject\n"
        "ncbi.assembly:GCF_000001.1\tbiolink:in_taxon\tGTDB:s__Example\n"
        "ncbi.assembly:GCF_000002.1\tbiolink:subclass_of\tGTDB:s__Example\n"
        "FOODON:00000001\tbiolink:in_taxon\tGTDB:s__Example\n"
        "GTDB:s__Example\tbiolink:has_phenotype\tMETPO:0000001\n"
    )
    stats = skill.Stats()
    *_, counts, _ = skill.stream_edges(edges, {}, stats)
    assert stats.classification_edges_skipped == 2
    assert counts["GTDB:s__Example"] == 2
