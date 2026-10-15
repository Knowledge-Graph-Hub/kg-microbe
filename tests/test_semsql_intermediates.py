"""A build never reuses intermediates an earlier, unfinished SemSQL build left (#1642)."""

from pathlib import Path

from kg_microbe.utils import ontology_utils as ou
from tests.db_helpers import write_single_ontology_db

OWL_HEAD = '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/go/releases/{d}/go.owl"/>\n'


def _build(tmp_path, monkeypatch, seen):
    """Run the guarded build with a fake `semsql make` that records what it found."""
    owl = tmp_path / "go.owl"
    owl.write_text(OWL_HEAD.format(d="2026-06-15"), encoding="utf-8")
    db = write_single_ontology_db(tmp_path / "go.db", "go")
    monkeypatch.setattr(ou.shutil, "which", lambda _: "/usr/bin/semsql")

    def make(cmd, **kwargs):
        """Note which intermediates were present, then publish a complete GO database."""
        cwd = Path(kwargs["cwd"])
        seen.update(path.name for path in cwd.iterdir() if path.name.startswith("go-"))
        write_single_ontology_db(cwd / "go.db", "go")

    monkeypatch.setattr(ou.subprocess, "run", make)
    return ou._run_semsql_build(
        owl, str(db), 3000, "GO", "n", reuse_on_failure=False, require_content=True, ontology="go"
    )


def test_a_relation_graph_tsv_left_by_a_failed_build_is_not_reused(tmp_path, monkeypatch, capsys):
    """The precious TSV and the ROBOT-made min.owl are removed before make runs."""
    for name in ("go-relation-graph.tsv", "go-min.owl"):
        (tmp_path / name).write_text("from an earlier toolchain\n", encoding="utf-8")
    seen = set()
    _build(tmp_path, monkeypatch, seen)
    assert seen == set()
    assert "left by an earlier build that did not finish" in capsys.readouterr().out


def test_only_the_targets_own_intermediates_are_removed(tmp_path, monkeypatch):
    """Another ontology's TSV and the gzipped TSV a finished build keeps stay where they are."""
    keep = ("chebi-relation-graph.tsv", "go-relation-graph.tsv.gz")
    for name in keep:
        (tmp_path / name).write_text("kept\n", encoding="utf-8")
    seen = set()
    _build(tmp_path, monkeypatch, seen)
    assert seen == {"go-relation-graph.tsv.gz"}
    assert all((tmp_path / name).exists() for name in keep)
