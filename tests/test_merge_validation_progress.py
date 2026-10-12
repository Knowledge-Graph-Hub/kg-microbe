"""Regressions for zero-count merge validation progress without changing graph semantics."""

import csv
import tarfile

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.progress import MergeProgress
from kg_microbe.utils.source_finalization import SourceFinalizationRequired


def fixture(tmp_path, kind):
    """Build valid literal TSVs for real cleanup without mocking validation or packaging."""
    output = tmp_path / "out"
    output.mkdir()
    nodes = output / "fixture_nodes.tsv"
    edges = output / "fixture_edges.tsv"
    node_rows = {
        "empty": [],
        "node_only": [["fixture:one", "biolink:NamedThing", "one", "", "infores:fixture"]],
        "nonempty": [
            ["fixture:one", "biolink:NamedThing", "one", "", "infores:fixture"],
            ["fixture:two", "biolink:NamedThing", "two", "", "infores:fixture"],
        ],
    }[kind]
    edge_rows = (
        []
        if kind != "nonempty"
        else [
            [
                "fixture:one",
                "biolink:related_to",
                "fixture:two",
                "",
                "infores:fixture",
                "knowledge_assertion",
                "manual_agent",
            ]
        ]
    )
    with nodes.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "category", "name", "description", "provided_by"])
        writer.writerows(node_rows)
    with edges.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["subject", "predicate", "object", "relation", "primary_knowledge_source", "knowledge_level", "agent_type"]
        )
        writer.writerows(edge_rows)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(output)},
                "merged_graph": {
                    "destination": {
                        "release": {
                            "format": "tsv",
                            "filename": "fixture",
                            "compression": "tar.gz",
                        }
                    }
                },
            }
        )
    )
    return config, nodes, edges


@pytest.mark.parametrize("kind,total", [("empty", 0), ("node_only", 1), ("nonempty", 3)])
def test_validation_progress_records_real_zero_and_nonzero_counts(tmp_path, monkeypatch, kind, total):
    """Zero-count validation still publishes identical graph bytes and reports exact progress."""
    config, nodes, edges = fixture(tmp_path, kind)
    before = {path.name: path.read_bytes() for path in (nodes, edges)}
    observed = []
    original = MergeProgress.report

    def report(self, state):
        """Observe the actual terminal count without replacing progress behavior."""
        if self.phase == "validation" and state == "complete":
            observed.append(self.count)
        return original(self, state)

    monkeypatch.setattr(MergeProgress, "report", report)
    merge_kg._cleanup_merged_outputs(str(config))
    assert observed == [total]
    with tarfile.open(nodes.parent / "fixture.tar.gz") as archive:
        for filename, payload in before.items():
            assert archive.extractfile(filename).read() == payload


@pytest.mark.parametrize("damage", ["undeclared_endpoint", "pipe_relation"])
def test_invalid_graph_still_refuses_publication_without_rewriting_tsvs(tmp_path, damage):
    """Invalid input must preserve TSVs and prior publication even when a count is absent."""
    config, nodes, edges = fixture(tmp_path, "nonempty")
    payload = edges.read_text()
    if damage == "undeclared_endpoint":
        payload = payload.replace("fixture:two", "fixture:missing")
    else:
        payload = payload.replace("fixture:two\t\t", "fixture:two\tRO:0000056|RO:0000057\t")
    edges.write_text(payload)
    before = {path: path.read_bytes() for path in (nodes, edges)}
    archive = nodes.parent / "fixture.tar.gz"
    archive.write_bytes(b"previous accepted archive")
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        merge_kg._cleanup_merged_outputs(str(config))
    assert archive.read_bytes() == b"previous accepted archive"
    assert {path: path.read_bytes() for path in (nodes, edges)} == before
    assert not (nodes.parent / "fixture_manifest.json").exists()
