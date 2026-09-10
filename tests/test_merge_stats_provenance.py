"""The stats file says what produced it and counts every predicate (#1013, #993)."""

from datetime import datetime, timezone
from pathlib import Path

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
