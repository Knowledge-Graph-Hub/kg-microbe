"""
Tests for merging a subset of the sources in a KGX config.

KGX holds every source's graph in the parent process simultaneously:
``kgx.cli.cli_utils.merge`` does ``stores = [r.get() for r in results]``
before calling ``merge_all_graphs``. Peak memory therefore scales with the
whole source set, not with its largest member. A full kg-microbe merge
reached 48 GB resident on a 64 GB machine, dominated by PREGO's 44.7M
edges (~76% of all input by size).

Selecting a subset lets the merge run in stages so the big source is never
resident alongside the other nineteen. These tests pin the plumbing —
that the selection actually reaches KGX and that a bad key fails fast —
rather than running a real merge, which needs the full data tree.
"""

from unittest import mock

import pytest
import yaml as yaml_lib

from kg_microbe.merge_utils.merge_kg import load_and_merge

_CONFIG = {
    "configuration": {"output_directory": "data/merged"},
    "merged_graph": {
        "name": "test graph",
        "source": {
            "alpha": {"input": {"format": "tsv", "filename": ["a_nodes.tsv", "a_edges.tsv"]}},
            "beta": {"input": {"format": "tsv", "filename": ["b_nodes.tsv", "b_edges.tsv"]}},
            "gamma": {"input": {"format": "tsv", "filename": ["c_nodes.tsv", "c_edges.tsv"]}},
        },
        "destination": {"merged-kg-tsv": {"format": "tsv", "filename": "merged-kg"}},
    },
}


@pytest.fixture()
def config_path(tmp_path):
    """Write a minimal three-source KGX merge config and return its path."""
    path = tmp_path / "merge.test.yaml"
    path.write_text(yaml_lib.safe_dump(_CONFIG))
    return str(path)


def _merged_sources(mock_merge):
    """Return the ``source`` argument KGX was actually called with."""
    return mock_merge.call_args.kwargs.get("source")


@mock.patch("kg_microbe.merge_utils.merge_kg._cleanup_merged_outputs")
@mock.patch("kg_microbe.merge_utils.merge_kg.merge")
def test_subset_is_passed_through_to_kgx(mock_merge, _cleanup, config_path):
    """The selected subset must reach KGX, not just be accepted by the CLI."""
    load_and_merge(config_path, sources=["alpha", "gamma"])
    assert _merged_sources(mock_merge) == ["alpha", "gamma"]


@mock.patch("kg_microbe.merge_utils.merge_kg._cleanup_merged_outputs")
@mock.patch("kg_microbe.merge_utils.merge_kg.merge")
def test_no_subset_merges_everything(mock_merge, _cleanup, config_path):
    """Omitting the subset must merge all sources, i.e. pass source=None."""
    load_and_merge(config_path)
    assert _merged_sources(mock_merge) is None


@mock.patch("kg_microbe.merge_utils.merge_kg._cleanup_merged_outputs")
@mock.patch("kg_microbe.merge_utils.merge_kg.merge")
def test_empty_subset_is_treated_as_all(mock_merge, _cleanup, config_path):
    """An empty tuple from click must not mean 'merge nothing'."""
    load_and_merge(config_path, sources=[])
    assert _merged_sources(mock_merge) is None


@mock.patch("kg_microbe.merge_utils.merge_kg._cleanup_merged_outputs")
@mock.patch("kg_microbe.merge_utils.merge_kg.merge")
def test_unknown_source_fails_before_kgx_runs(mock_merge, _cleanup, config_path):
    """
    A typo must abort before any parsing starts.

    KGX indexes the config dict directly, so an unknown key would otherwise
    surface as a bare ``KeyError`` only once the merge is underway — an
    expensive place to discover a misspelling.
    """
    with pytest.raises(KeyError) as excinfo:
        load_and_merge(config_path, sources=["alpha", "prego"])
    message = str(excinfo.value)
    assert "prego" in message
    # The error has to name the valid options, or the user is left guessing.
    assert "alpha" in message and "beta" in message
    mock_merge.assert_not_called()


@mock.patch("kg_microbe.merge_utils.merge_kg._cleanup_merged_outputs")
@mock.patch("kg_microbe.merge_utils.merge_kg.merge")
def test_processes_still_defaults_to_one(mock_merge, _cleanup, config_path):
    """
    Each concurrent process holds its own source graph.

    Raising the default would multiply peak memory on the exact workload
    this subset option exists to make survivable.
    """
    load_and_merge(config_path)
    assert mock_merge.call_args.kwargs.get("processes") == 1
