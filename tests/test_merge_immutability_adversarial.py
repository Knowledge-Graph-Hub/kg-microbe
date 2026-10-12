"""Independent adversarial probes for coordinator's no-postmerge-edit contract."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION
from tests.test_merge_canonical_serialization import _configuration, offline_kgx  # noqa: F401


def test_later_optional_callback_cannot_change_earlier_loose_destination(tmp_path, monkeypatch):
    """An earlier manifest is not a guard against edits by a later report callback."""
    config, output = _configuration(tmp_path, None)
    data = yaml.safe_load(config.read_text())
    data["merged_graph"]["destination"]["tsv2"] = {"format": "tsv", "filename": "second"}
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    original = merge_kg.check_merged_invariants

    def edit_earlier(edges_file, output_dir, *, nodes_file):
        """Inject a mutation of an earlier destination during the later report."""
        result = original(edges_file, output_dir, nodes_file=nodes_file)
        if nodes_file.name == "second_nodes.tsv":
            earlier = nodes_file.with_name("merged-kg_nodes.tsv")
            earlier.write_bytes(earlier.read_bytes().replace(b"root", b"ROOT"))
        return result

    monkeypatch.setattr(merge_kg, "check_merged_invariants", edit_earlier)
    try:
        merge_kg.load_and_merge(str(config))
    except ValueError as error:
        assert "mutation" in str(error)
        return
    manifest = json.loads((output / "merged-kg_manifest.json").read_text())
    observed = hashlib.sha256((output / "merged-kg_nodes.tsv").read_bytes()).hexdigest()
    assert observed == manifest["members"]["merged-kg_nodes.tsv"]["sha256"], (
        "Published mutated earlier destination with a stale manifest"
    )
    pytest.fail("A later callback edited an already packaged loose destination without rejection")


def test_stats_publication_cannot_overwrite_source_input(tmp_path, monkeypatch):
    """The permitted stats operation must not write through its final locator to an input."""
    config, output = _configuration(tmp_path, "tar.gz")
    data = yaml.safe_load(config.read_text())
    source_nodes = Path(data["merged_graph"]["source"]["fixture"]["input"]["filename"][0])
    before = source_nodes.read_bytes()
    data["merged_graph"]["operations"] = [
        {"name": STATS_OPERATION, "args": {"graph_name": "fixture", "filename": str(source_nodes)}}
    ]
    config.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    try:
        merge_kg.load_and_merge(str(config))
    except ValueError:
        assert source_nodes.read_bytes() == before
        return
    assert source_nodes.read_bytes() == before, (
        "Permitted stats output overwrote the admitted source TSV after final admission verification"
    )
    pytest.fail("Unsafe stats/source publication collision was not rejected")


def test_empty_remap_placeholders_remain_supported(tmp_path, monkeypatch):
    """Positive control: canonical empty mapping placeholders do not create a transform."""
    config, output = _configuration(tmp_path, "tar.gz")
    data = yaml.safe_load(config.read_text())
    data["configuration"].update({"curie_map": None, "predicate_mappings": {}, "node_properties": []})
    config.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    merge_kg.load_and_merge(str(config))
    assert (output / "merged-kg.tar.gz").is_file()


def test_optional_callback_deleting_required_pair_must_fail(tmp_path, monkeypatch):
    """Removing a required graph member cannot become optional report failure."""
    config, output = _configuration(tmp_path, "tar.gz")
    marker = output / "merged-kg.tar.gz"
    marker.write_bytes(b"previous accepted archive")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)

    def remove_pair(edges_file, output_dir, *, nodes_file):
        """Remove a required input before raising an otherwise optional report error."""
        nodes_file.unlink()
        raise RuntimeError("optional callback failed after deleting a required graph file")

    monkeypatch.setattr(merge_kg, "check_merged_invariants", remove_pair)
    with pytest.raises((ValueError, FileNotFoundError)):
        merge_kg.load_and_merge(str(config))
    assert marker.read_bytes() == b"previous accepted archive"


def test_checkpoint_source_key_cannot_escape_private_staging(tmp_path, monkeypatch):
    """Checkpoint writes cannot bypass the destination publication contract."""
    config, output = _configuration(tmp_path, "tar.gz")
    data = yaml.safe_load(config.read_text())
    data["configuration"]["checkpoint"] = True
    source = data["merged_graph"]["source"].pop("fixture")
    data["merged_graph"]["source"]["../../checkpoint-leak"] = source
    config.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    escaped = tmp_path / "checkpoint-leak_nodes.tsv"
    try:
        merge_kg.load_and_merge(str(config))
    except ValueError:
        assert not escaped.exists()
        return
    assert not escaped.exists(), "Accepted checkpoint/source key wrote outside the unique private staging directory"
    pytest.fail("Unsafe checkpoint/source key was not rejected")
