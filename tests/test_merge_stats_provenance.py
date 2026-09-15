"""The stats file says what produced it and counts every predicate (#1013, #993)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.stats_provenance import (
    annotate_graph_stats,
    count_raw_predicates,
    stats_filename_from_config,
)

EDGES = [
    ("NCBITaxon:1", "METPO:2000517", "medium:1"),
    ("NCBITaxon:1", "METPO:2000517", "medium:2"),
    ("NCBITaxon:2", "biolink:subclass_of", "NCBITaxon:1"),
    ("NCBITaxon:2", "", "medium:2"),
]


def _write_fixture(tmp_path: Path):
    edges = tmp_path / "merged-kg_edges.tsv"
    with edges.open("w", encoding="utf-8") as handle:
        handle.write("subject\tpredicate\tobject\n")
        for row in EDGES:
            handle.write("\t".join(row) + "\n")
    stats = tmp_path / "stats.yaml"
    stats.write_text(
        yaml.safe_dump(
            {
                "graph_name": "kg-microbe graph",
                "edge_stats": {"total_edges": 4, "count_by_predicates": {"biolink:subclass_of": {"count": 1}}},
                "node_stats": {"total_nodes": 4},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data" / "transformed" / "bacdive").mkdir(parents=True)
    (tmp_path / "data" / "transformed" / "bacdive" / "source_fingerprint.json").write_text(
        '{"version": 3, "code": "c0de", "data": "da7a", "schema": {"digest": "5c", "version": "4.4.2"}}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "transformed" / "gold").mkdir(parents=True)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "merged_graph": {
                    "source": {
                        "bacdive": {"input": {"filename": ["data/transformed/bacdive/nodes.tsv"]}},
                        "gold": {"input": {"filename": ["data/transformed/gold/edges.tsv"]}},
                    },
                    "operations": [
                        {
                            "name": "kgx.graph_operations.summarize_graph.generate_graph_stats",
                            "args": {"filename": "stats.yaml"},
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return stats, edges, config


def test_raw_predicate_counts_include_metpo_and_sum_to_the_edge_total(tmp_path):
    """KGX's count_by_predicates records METPO as None; the raw count names it and adds up."""
    stats, edges, config = _write_fixture(tmp_path)
    result = annotate_graph_stats(stats, edges, config, tmp_path, now=datetime(2026, 9, 10, tzinfo=timezone.utc))
    raw = result["edge_stats"]["count_by_raw_predicate"]
    assert raw == {"(blank)": 1, "METPO:2000517": 2, "biolink:subclass_of": 1}
    assert sum(raw.values()) == result["edge_stats"]["total_edges"]
    assert result["edge_stats"]["count_by_predicates"] == {"biolink:subclass_of": {"count": 1}}, "KGX's block is kept"


def test_provenance_names_when_config_commit_and_source_markers(tmp_path):
    """A committed copy can be told from a stale one without diffing counts."""
    stats, edges, config = _write_fixture(tmp_path)
    result = annotate_graph_stats(stats, edges, config, tmp_path, now=datetime(2026, 9, 10, 1, 24, tzinfo=timezone.utc))
    prov = result["provenance"]
    assert prov["generated_at"] == "2026-09-10T01:24:00+00:00"
    assert prov["merge_config"] == str(config)
    assert prov["edges_file"] == str(edges)
    assert prov["commit"] == "unknown", "tmp_path is not a git checkout; the field is still written"
    assert prov["sources"]["bacdive"].startswith("code=c0de data=da7a schema=5c")
    assert prov["sources"]["gold"] == "no marker in data/transformed/gold"
    on_disk = yaml.safe_load(stats.read_text(encoding="utf-8"))
    assert on_disk["provenance"] == prov


def test_compressed_merge_provenance_names_a_surviving_artifact(tmp_path):
    """The archive locator still resolves after cleanup removes the loose TSVs (#1055)."""
    import tarfile

    from kg_microbe.merge_utils.merge_kg import _cleanup_merged_outputs

    stats, edges, config = _write_fixture(tmp_path)
    nodes = tmp_path / "merged-kg_nodes.tsv"
    nodes.write_text(
        "id\tcategory\tname\n"
        "NCBITaxon:1\tbiolink:OrganismTaxon\tone\n"
        "NCBITaxon:2\tbiolink:OrganismTaxon\ttwo\n"
        "medium:1\tbiolink:ChemicalMixture\tmedium one\n"
        "medium:2\tbiolink:ChemicalMixture\tmedium two\n",
        encoding="utf-8",
    )
    archive_path = tmp_path / "merged-kg.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in (nodes, edges):
            archive.add(path, arcname=path.name)
    nodes.unlink()
    edges.unlink()
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    settings["configuration"] = {"output_directory": str(tmp_path)}
    settings["merged_graph"]["destination"] = {
        "tsv": {"format": "tsv", "filename": "merged-kg", "compression": "tar.gz"}
    }
    settings["merged_graph"]["operations"][0]["args"]["filename"] = str(stats)
    config.write_text(yaml.safe_dump(settings), encoding="utf-8")

    _cleanup_merged_outputs(str(config))

    provenance = yaml.safe_load(stats.read_text(encoding="utf-8"))["provenance"]
    assert "edges_file" not in provenance, "must not cite the deleted working file"
    assert Path(provenance["edges_archive"]).is_file()
    with tarfile.open(provenance["edges_archive"]) as archive:
        assert archive.getmember(provenance["edges_archive_member"]).isfile()
    assert not edges.exists()
    assert not nodes.exists()


def test_annotating_twice_replaces_rather_than_appends(tmp_path):
    """Re-running the merge must not stack provenance blocks or double the raw counts."""
    stats, edges, config = _write_fixture(tmp_path)
    annotate_graph_stats(stats, edges, config, tmp_path)
    second = annotate_graph_stats(stats, edges, config, tmp_path)
    assert list(second) == ["edge_stats", "graph_name", "node_stats", "provenance"]
    assert second["edge_stats"]["count_by_raw_predicate"]["METPO:2000517"] == 2


def test_a_mismatched_edges_file_is_refused(tmp_path):
    """Counting a different file than the stats describe would be worse than no count."""
    stats, edges, config = _write_fixture(tmp_path)
    with edges.open("a", encoding="utf-8") as handle:
        handle.write("NCBITaxon:9\tbiolink:related_to\tNCBITaxon:1\n")
    try:
        annotate_graph_stats(stats, edges, config, tmp_path)
    except ValueError as exc:
        assert "5 != KGX total_edges 4" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_finalized_recount_replaces_all_stale_totals_and_facets(tmp_path):
    """Removed edges/nodes and changed categories/providers never leave KGX facets at top level."""
    stats, edges, config = _write_fixture(tmp_path)
    original = yaml.safe_load(stats.read_text())
    original["edge_stats"]["count_by_spo"] = {"old-category-old-predicate-old-category": 4}
    original["node_stats"]["count_by_category"] = {"obsolete-category": {"count": 4}}
    original["custom_old_graph_facet"] = {"old": 4}
    stats.write_text(yaml.safe_dump(original))
    nodes = tmp_path / "final_nodes.tsv"
    nodes.write_text(
        "id\tcategory\tname\tprovided_by\n"
        "NCBITaxon:12\tbiolink:OrganismTaxon\tAccepted taxon\tinfores:ncbitaxon\n"
        "CHEBI:3\tbiolink:ChemicalEntity|biolink:OntologyClass|biolink:ChemicalEntity\tCompound\tinfores:chebi|infores:source\n"
    )
    edges.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\n"
        "NCBITaxon:12\tMETPO:2000517\tCHEBI:3\tMETPO:2000517\tinfores:source\tknowledge_assertion\tmanual_agent\n"
        "NCBITaxon:12\tbiolink:related_to\tCHEBI:3\tRO:0001\tinfores:other\tprediction\tautomated_agent\n"
    )
    result = annotate_graph_stats(stats, edges, config, tmp_path, finalized_nodes_file=nodes)
    assert result["pre_normalization_stats"] == original
    assert "custom_old_graph_facet" not in result
    assert "count_by_predicates" not in result["edge_stats"]
    assert "count_by_spo" not in result["edge_stats"]
    assert "count_by_category" not in result["node_stats"]
    assert result["node_stats"]["total_nodes"] == 2
    assert result["edge_stats"]["total_edges"] == 2
    assert result["edge_stats"]["count_by_raw_predicate"] == {"METPO:2000517": 1, "biolink:related_to": 1}
    assert result["edge_stats"]["count_by_raw_primary_knowledge_source"] == {"infores:other": 1, "infores:source": 1}
    assert result["edge_stats"]["count_by_raw_agent_type"] == {"automated_agent": 1, "manual_agent": 1}
    assert result["node_stats"]["count_by_raw_category_incidence"] == {
        "biolink:OrganismTaxon": 1,
        "biolink:ChemicalEntity": 1,
        "biolink:OntologyClass": 1,
    }
    assert result["node_stats"]["count_by_raw_id_prefix"] == {"CHEBI": 1, "NCBITaxon": 1}
    assert result["node_stats"]["count_by_provided_by_incidence"] == {
        "infores:ncbitaxon": 1,
        "infores:chebi": 1,
        "infores:source": 1,
    }
    assert "may exceed total_nodes" in result["provenance"]["note"]
    assert yaml.safe_load(stats.read_text()) == result


def test_finalized_recount_is_idempotent_and_keeps_original_kgx_block(tmp_path):
    """Repeated recounts replace current counts without nesting or rewriting original observations."""
    stats, edges, config = _write_fixture(tmp_path)
    original = yaml.safe_load(stats.read_text())
    nodes = tmp_path / "nodes.tsv"
    nodes.write_text("id\tcategory\nNCBITaxon:1\tbiolink:OrganismTaxon\n")
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    first = annotate_graph_stats(stats, edges, config, tmp_path, now=now, finalized_nodes_file=nodes)
    second = annotate_graph_stats(stats, edges, config, tmp_path, now=now, finalized_nodes_file=nodes)
    assert second == first
    assert second["pre_normalization_stats"] == original
    assert "pre_normalization_stats" not in second["pre_normalization_stats"]


def test_loose_locator_can_be_published_while_reading_staged_edges(tmp_path):
    """Provenance must not name the private staging directory once files are published."""
    stats, edges, config = _write_fixture(tmp_path)
    published = tmp_path / "published" / "merged-kg_edges.tsv"
    result = annotate_graph_stats(stats, edges, config, tmp_path, published_edges_file=published)
    assert result["provenance"]["edges_file"] == str(published)
    assert result["edge_stats"]["total_edges"] == 4
    assert not published.exists(), "the annotation only reads the real staged file"


def test_failed_final_recount_does_not_clobber_original_stats(tmp_path):
    """A malformed final TSV raises without rewriting pre-cleanup statistics as current."""
    stats, edges, config = _write_fixture(tmp_path)
    original = stats.read_bytes()
    nodes = tmp_path / "nodes.tsv"
    nodes.write_text("id\tcategory\nNCBITaxon:1\n")
    with pytest.raises(ValueError, match="malformed TSV row"):
        annotate_graph_stats(stats, edges, config, tmp_path, finalized_nodes_file=nodes)
    assert stats.read_bytes() == original


def test_the_stats_filename_comes_from_the_config_operation(tmp_path):
    """The merge config, not a hardcoded name, says which file to annotate — variants differ."""
    _, _, config = _write_fixture(tmp_path)
    assert stats_filename_from_config(yaml.safe_load(config.read_text())) == "stats.yaml"
    assert stats_filename_from_config({"merged_graph": {"operations": []}}) is None
    assert count_raw_predicates(tmp_path / "merged-kg_edges.tsv")["METPO:2000517"] == 2


def test_the_real_canonical_config_names_a_stats_file():
    """merge.yaml's summarize operation is what the hook reads; keep them in step."""
    config = yaml.safe_load(Path("merge.yaml").read_text(encoding="utf-8"))
    assert stats_filename_from_config(config) == "merged_graph_stats.yaml"


def _init_repo(tmp_path: Path) -> Path:
    """Build a real git checkout with one commit, so git_commit has something to read."""
    import os
    import shutil
    import subprocess

    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run([git, "init", "-q"], cwd=repo, check=True, env=env)  # noqa: S603 - resolved path
    (repo / "stats.yaml").write_text("a: 1\n", encoding="utf-8")
    (repo / "other.txt").write_text("x\n", encoding="utf-8")
    subprocess.run([git, "add", "."], cwd=repo, check=True, env=env)  # noqa: S603 - resolved path
    subprocess.run([git, "commit", "-qm", "init"], cwd=repo, check=True, env=env)  # noqa: S603 - resolved path
    return repo


def test_the_ignored_stats_file_alone_does_not_make_the_tree_dirty(tmp_path):
    """
    #1038: `_git` stripped the leading space off `git status --porcelain`.

    Porcelain emits "XY PATH", so " M stats.yaml" became "M stats.yaml" and the
    `line[3:]` slice produced "tats.yaml" — which never matched the ignore set,
    so every merge stamped -dirty regardless of the tree. The old assertions
    passed against that constant answer; this constructs the exact state.
    """
    from kg_microbe.merge_utils.stats_provenance import git_commit

    repo = _init_repo(tmp_path)
    stats = repo / "stats.yaml"
    stats.write_text("a: 2\n", encoding="utf-8")

    clean = git_commit(repo, ignore=(stats,))
    self_dirty = git_commit(repo)
    assert not clean.endswith("-dirty"), f"only the ignored file changed, got {clean!r}"
    assert self_dirty.endswith("-dirty"), "without the ignore it must still report dirty"
    assert clean == self_dirty[: -len("-dirty")]


def test_a_second_modified_file_still_reports_dirty(tmp_path):
    """Ignoring the stats file must not blind the flag to everything else."""
    from kg_microbe.merge_utils.stats_provenance import git_commit

    repo = _init_repo(tmp_path)
    (repo / "stats.yaml").write_text("a: 2\n", encoding="utf-8")
    (repo / "other.txt").write_text("changed\n", encoding="utf-8")
    assert git_commit(repo, ignore=(repo / "stats.yaml",)).endswith("-dirty")


def test_porcelain_paths_parses_the_column_format(tmp_path):
    """Status columns, renames and quoted paths all have to yield the path itself."""
    from kg_microbe.merge_utils.stats_provenance import _porcelain_paths

    status = " M merged_graph_stats.yaml\n?? untracked.txt\nR  old.py -> new.py\nMM both.py\n"
    assert _porcelain_paths(status) == ["merged_graph_stats.yaml", "untracked.txt", "new.py", "both.py"]
    assert _porcelain_paths("") == []


def test_the_stats_file_itself_never_makes_the_commit_dirty():
    """KGX rewrites the stats file right before annotation; that must not read as a dirty tree."""
    from kg_microbe.merge_utils.stats_provenance import git_commit

    repo = Path(".").resolve()
    stats = repo / "merged_graph_stats.yaml"
    commit = git_commit(repo, ignore=(stats,))
    assert commit != "unknown"
    assert len(commit.split("-")[0]) >= 7
    # Ignoring the stats file can only make the verdict cleaner, never dirtier.
    assert not (commit.endswith("-dirty") and not git_commit(repo).endswith("-dirty"))


def test_a_directory_that_is_not_a_checkout_records_unknown(tmp_path):
    """No git, no repo: the field says so rather than raising."""
    from kg_microbe.merge_utils.stats_provenance import git_commit

    assert git_commit(tmp_path) == "unknown"
