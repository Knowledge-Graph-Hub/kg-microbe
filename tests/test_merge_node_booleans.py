"""Overlapping declarations cannot turn scalar Boolean flags into pipe strings."""

import csv
import io
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.kgx_source import RelationAwareTsvSink
from kg_microbe.transform_utils.constants import DEPRECATED_COLUMN, ID_COLUMN

FIXTURES = Path(__file__).parent / "resources" / "node_boolean_merge"


@pytest.fixture(autouse=True)
def offline_prefix_context(monkeypatch):
    """Never fetch a remote context, including when the serializer runs directly."""
    monkeypatch.setattr("kgx.prefix_manager.get_jsonld_context", lambda: {"@context": {}})


@pytest.fixture
def boolean_merge(tmp_path, monkeypatch):
    """Use real KGX ingestion, overlap and export with immutable local declarations."""
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)

    def run(beta="beta_nodes.tsv"):
        """Keep the diagnostic fixture admission separate from production receipts."""
        sources = {}
        for name, nodes in (("alpha", "alpha_nodes.tsv"), ("beta", beta)):
            sources[name] = {
                "input": {"format": "tsv", "filename": [str(FIXTURES / nodes), str(FIXTURES / "edges.tsv")]}
            }
        config = tmp_path / "merge.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "configuration": {
                        "output_directory": str(tmp_path / "published"),
                        "allow_unfinalized_sources": True,
                    },
                    "merged_graph": {
                        "source": sources,
                        "destination": {"tsv": {"format": "tsv", "filename": "merged-kg", "compression": "tar.gz"}},
                    },
                }
            )
        )
        merge_kg.load_and_merge(str(config))
        with tarfile.open(tmp_path / "published" / "merged-kg.tar.gz") as archive:
            text = archive.extractfile("merged-kg_nodes.tsv").read().decode()
        return {
            row[ID_COLUMN]: row for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
        }

    return run


def test_overlapping_boolean_declarations_remain_scalar(boolean_merge):
    """Blank is no assertion; repeated flags stay Boolean through an actual merge."""
    rows = boolean_merge()
    assert {identifier: row[DEPRECATED_COLUMN] for identifier, row in rows.items()} == {
        "fixture:current": "",
        "fixture:historical": "true",
        "fixture:repeated": "true",
        "fixture:explicit_false": "false",
    }
    assert set(rows["fixture:historical"]["provided_by"].split("|")) == {"infores:alpha", "infores:beta"}


def test_conflicting_boolean_declarations_preserve_previous_archive(boolean_merge, tmp_path):
    """A real true/false disagreement must abort publication, never pick a winner."""
    previous = tmp_path / "published" / "merged-kg.tar.gz"
    previous.parent.mkdir()
    previous.write_bytes(b"last good archive")
    with pytest.raises(ValueError, match="Conflicting Boolean node field"):
        boolean_merge("conflicting_nodes.tsv")
    assert previous.read_bytes() == b"last good archive"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["", "", None], ""),
        ([True, "true", "1", ""], "true"),
        ([False, "false", "0", ""], "false"),
        (True, "true"),
        (False, "false"),
        ("TRUE", "true"),
        (1, "true"),
        (0, "false"),
    ],
)
def test_boolean_node_serialization(tmp_path, value, expected):
    """Serialize one typed truth value, preserving an absent declaration as blank."""
    sink = RelationAwareTsvSink(None, str(tmp_path / "graph"), "tsv", node_properties=[ID_COLUMN, DEPRECATED_COLUMN])
    try:
        sink.write_node({ID_COLUMN: "fixture:node", DEPRECATED_COLUMN: value})
    finally:
        sink.finalize()
    with (tmp_path / "graph_nodes.tsv").open() as stream:
        row = next(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert row[DEPRECATED_COLUMN] == expected


@pytest.mark.parametrize("value", [[True, False], ["true", "false"], "|||", "true|false", "unknown", " true "])
def test_invalid_boolean_node_values_are_rejected(tmp_path, value):
    """Malformed scalar text and contradictory flags cannot enter a canonical TSV."""
    sink = RelationAwareTsvSink(None, str(tmp_path / "graph"), "tsv", node_properties=[ID_COLUMN, DEPRECATED_COLUMN])
    try:
        with pytest.raises(ValueError, match="Boolean node field"):
            sink.write_node({ID_COLUMN: "fixture:node", DEPRECATED_COLUMN: value})
    finally:
        sink.finalize()
