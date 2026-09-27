"""Empty overlapping descriptions must not become literal pipes (#1200)."""

import copy
import csv
import io
import tarfile
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import kgx_source, merge_kg
from kg_microbe.transform_utils.constants import DESCRIPTION_COLUMN, ID_COLUMN

FIXTURES = Path(__file__).parent / "resources" / "node_description_merge"


@pytest.fixture(autouse=True)
def offline_kgx(monkeypatch):
    """Keep actual KGX source ingestion hermetic and in-process."""
    from kgx.cli import cli_utils

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    with kgx_source.local_prefix_context():
        yield


@pytest.mark.parametrize("legacy_export", [False, True])
def test_public_merge_omits_only_empty_description_contributions(tmp_path, monkeypatch, legacy_export):
    """Actual overlap and both canonical export paths preserve meaningful node fields."""
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    if legacy_export:
        monkeypatch.setattr(kgx_source, "_eligible_merge_configuration", lambda *args: False)
    sink_calls = []
    original_init = kgx_source.RelationAwareGraphSink.__init__

    def track_sink(self, owner):
        """Prove the selected direct or legacy path was actually exercised."""
        sink_calls.append(owner)
        original_init(self, owner)

    monkeypatch.setattr(kgx_source.RelationAwareGraphSink, "__init__", track_sink)
    sources = {
        source: {
            "input": {
                "format": "tsv",
                "filename": [str(FIXTURES / f"{source}_nodes.tsv"), str(FIXTURES / "edges.tsv")],
            }
        }
        for source in ("alpha", "beta")
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
                    "destination": {"tsv": {"format": "tsv", "filename": "merged", "compression": "tar.gz"}},
                },
            }
        )
    )
    graph = merge_kg.load_and_merge(str(config))
    assert len(sink_calls) == (3 if legacy_export else 2)
    # Serialization must not rewrite KGX's retained in-memory aggregation.
    assert graph.nodes()["fixture:blank"][DESCRIPTION_COLUMN] == ["", ""]
    with tarfile.open(tmp_path / "published" / "merged.tar.gz") as archive:
        text = archive.extractfile("merged_nodes.tsv").read().decode()
    rows = {row[ID_COLUMN]: row for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)}
    assert {identifier: row[DESCRIPTION_COLUMN] for identifier, row in rows.items()} == {
        "fixture:blank": "",
        "fixture:left_blank": "meaningful",
        "fixture:right_blank": "meaningful",
        "fixture:repeat": "meaningful|meaningful",
        "fixture:distinct": "alpha|beta",
        "fixture:whitespace": " ",
    }
    assert all(row["provided_by"] == "infores:alpha|infores:beta" for row in rows.values())
    assert all(row["xref"] == "fixture:common|fixture:alpha|fixture:common|fixture:beta" for row in rows.values())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["", ""], ""),
        ([None, "", None], ""),
        (["", "meaningful"], "meaningful"),
        (["meaningful", ""], "meaningful"),
        (["meaningful", "meaningful", ""], "meaningful|meaningful"),
        (["", "|"], "|"),
        (["", "literal|pipe", "literal|pipe"], "literal|pipe|literal|pipe"),
        (["", " ", "  "], " |  "),
        (["", False, 0], "0|False"),
        ((None, "", "meaningful"), "meaningful"),
        ({None, "", "meaningful"}, "meaningful"),
        ([], ""),
        (None, ""),
        ("", ""),
        (" ", " "),
        ("literal|pipe", "literal|pipe"),
        ("meaningful", "meaningful"),
        (False, "false"),
        (0, "0"),
    ],
)
def test_node_description_serialization(tmp_path, value, expected):
    """Only absent collection entries disappear, without trimming or deduplication."""
    sink = kgx_source.RelationAwareTsvSink(
        None, str(tmp_path / "graph"), "tsv", node_properties=[ID_COLUMN, DESCRIPTION_COLUMN]
    )
    record = {ID_COLUMN: "fixture:node", DESCRIPTION_COLUMN: value}
    original = copy.deepcopy(record)
    try:
        sink.write_node(record)
    finally:
        sink.finalize()
    assert record == original
    with (tmp_path / "graph_nodes.tsv").open() as stream:
        row = next(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert row[DESCRIPTION_COLUMN] == expected


def test_description_filter_does_not_change_other_node_or_edge_fields(tmp_path):
    """Retain existing serialization outside the node-description boundary."""
    sink = kgx_source.RelationAwareTsvSink(
        None,
        str(tmp_path / "graph"),
        "tsv",
        node_properties=[ID_COLUMN, "provided_by", "xref", "custom_node"],
        edge_properties=["subject", "predicate", "object", DESCRIPTION_COLUMN],
    )
    try:
        sink.write_node(
            {
                ID_COLUMN: "fixture:node",
                "provided_by": ["", "infores:alpha", "infores:alpha"],
                "xref": ["", "fixture:alpha", "fixture:alpha"],
                "custom_node": ["", ""],
            }
        )
        sink.write_edge(
            {
                "subject": "fixture:node",
                "predicate": "biolink:related_to",
                "object": "fixture:node",
                "relation": "RO:0002215",
                "primary_knowledge_source": "infores:fixture",
                "knowledge_level": "knowledge_assertion",
                "agent_type": "manual_agent",
                DESCRIPTION_COLUMN: ["", ""],
            }
        )
    finally:
        sink.finalize()
    with (tmp_path / "graph_nodes.tsv").open() as stream:
        node = next(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    with (tmp_path / "graph_edges.tsv").open() as stream:
        edge = next(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert node["provided_by"] == "|infores:alpha|infores:alpha"
    assert node["xref"] == "|fixture:alpha|fixture:alpha"
    assert node["custom_node"] == "|"
    # The existing edge assertion canonicalizer already omits blank scalar contributions.
    assert edge[DESCRIPTION_COLUMN] == ""
