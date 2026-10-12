"""No configurable biological repair or post-serialization edit may ship as a release."""

import json
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION
from tests.test_merge_canonical_serialization import _configuration, offline_kgx  # noqa: F401


@pytest.mark.parametrize("where", ["configuration", "graph", "source", "input", "destination"])
@pytest.mark.parametrize("option", ["operations", "prefix_map", "reverse_prefix_map", "filters"])
def test_transform_options_fail_before_admission(tmp_path, monkeypatch, where, option):
    """Diagnostic opt-out never grants permission to edit KG content at merge time."""
    config, _output = _configuration(tmp_path, "tar.gz")
    content = yaml.safe_load(config.read_text())
    graph = content["merged_graph"]
    target = {
        "configuration": content["configuration"],
        "graph": graph,
        "source": graph["source"]["fixture"],
        "input": graph["source"]["fixture"]["input"],
        "destination": graph["destination"]["tsv"],
    }[where]
    target[option] = [{"name": "unreviewed.mutate", "args": {}}] if option == "operations" else {"a": "b"}
    config.write_text(yaml.safe_dump(content))
    admission, kgx = Mock(), Mock()
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admission)
    monkeypatch.setattr(merge_kg, "merge", kgx)
    with pytest.raises(ValueError, match="upstream transforms|read-only statistics"):
        merge_kg.load_and_merge(str(config))
    admission.assert_not_called()
    kgx.assert_not_called()


@pytest.mark.parametrize(
    "key", ["provided_by", "primary_knowledge_source", "knowledge_source", "aggregator_knowledge_source"]
)
def test_source_provenance_override_is_not_a_merge_option(tmp_path, key):
    """Source-level provenance must come from finalized rows, not KGX configuration overrides."""
    config, _output = _configuration(tmp_path, None)
    content = yaml.safe_load(config.read_text())
    content["merged_graph"]["source"]["fixture"]["input"][key] = "infores:replacement"
    config.write_text(yaml.safe_dump(content))
    with pytest.raises(ValueError, match="unsupported overrides"):
        merge_kg.load_and_merge(str(config))


@pytest.mark.parametrize("compression", [None, "tar.gz"])
@pytest.mark.parametrize("stage", ["validation", "invariants", "statistics"])
@pytest.mark.parametrize("raises_after_edit", [False, True])
def test_post_serialization_edit_blocks_publication(tmp_path, monkeypatch, compression, stage, raises_after_edit):
    """Even optional diagnostics that edit valid graph bytes must not publish their mutation."""
    config, output = _configuration(tmp_path, compression)
    content = yaml.safe_load(config.read_text())
    content["merged_graph"]["operations"] = [
        {
            "name": STATS_OPERATION,
            "args": {"graph_name": "fixture", "filename": str(tmp_path / "stats.yaml")},
        }
    ]
    config.write_text(yaml.safe_dump(content))
    marker = output / ("merged-kg.tar.gz" if compression else "merged-kg_manifest.json")
    marker.write_bytes(b"previous accepted artifact")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    hook = {
        "validation": "write_merge_validation_report",
        "invariants": "check_merged_invariants",
        "statistics": "annotate_graph_stats",
    }[stage]
    real = getattr(merge_kg, hook)

    def edit(*args, **kwargs):
        """Simulate a future well-intended repair inside a report callback."""
        result = real(*args, **kwargs)
        nodes = args[0] if stage == "validation" else kwargs.get("nodes_file", kwargs.get("finalized_nodes_file"))
        payload = nodes.read_bytes()
        nodes.write_bytes(payload.replace(b"root", b"ROOT"))  # valid, same-length TSV edit
        if raises_after_edit:
            raise RuntimeError("diagnostic failed after editing graph")
        return result

    monkeypatch.setattr(merge_kg, hook, edit)
    expected = (
        "diagnostic failed" if stage == "validation" and raises_after_edit else "Post-serialization graph mutation"
    )
    with pytest.raises((ValueError, RuntimeError), match=expected):
        merge_kg.load_and_merge(str(config))
    assert marker.read_bytes() == b"previous accepted artifact"


@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_archive_graph_bytes_equal_first_serializer_write(tmp_path, monkeypatch, compression):
    """Validation, statistics and packaging preserve every first-write graph byte."""
    config, output = _configuration(tmp_path, compression)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    real_merge = merge_kg.merge
    first_write = {}

    def capture(*args, **kwargs):
        """Observe serialized output immediately after KGX, before downstream reports."""
        graph = real_merge(*args, **kwargs)
        with open(args[0]) as stream:
            staged = yaml.safe_load(stream)["configuration"]["output_directory"]
        for path in Path(staged).glob("*.tsv"):
            first_write[path.name] = path.read_bytes()
        return graph

    monkeypatch.setattr(merge_kg, "merge", capture)
    merge_kg.load_and_merge(str(config))
    if compression:
        with tarfile.open(output / "merged-kg.tar.gz") as archive:
            for name, payload in first_write.items():
                assert archive.extractfile(name).read() == payload
    else:
        manifest = json.loads((output / "merged-kg_manifest.json").read_text())
        for name, payload in first_write.items():
            assert name in manifest["members"]
            assert (output / name).read_bytes() == payload


@pytest.mark.parametrize("target", ["config", "nodes", "edges", "archive", "manifest", "report", "dependency"])
def test_statistics_cannot_overwrite_protected_paths(tmp_path, monkeypatch, target):
    """Stats cannot overwrite configuration, graph outputs or indirectly consumed authority."""
    config, output = _configuration(tmp_path, "tar.gz")
    dependency = tmp_path / "authority.json"
    dependency.write_text('{"authority": "unchanged"}')
    targets = {
        "config": config,
        "nodes": output / "merged-kg_nodes.tsv",
        "edges": output / "merged-kg_edges.tsv",
        "archive": output / "merged-kg.tar.gz",
        "manifest": output / "merged-kg_manifest.json",
        "report": output / "merged-kg_reference_resolution.tsv",
        "dependency": dependency,
    }
    content = yaml.safe_load(config.read_text())
    content["merged_graph"]["operations"] = [
        {"name": STATS_OPERATION, "args": {"graph_name": "fixture", "filename": str(targets[target])}}
    ]
    config.write_text(yaml.safe_dump(content))
    before = config.read_bytes(), dependency.read_bytes()
    if target == "dependency":
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        admission = SourceAdmission()
        admission.capture(dependency)
        monkeypatch.setattr(merge_kg, "_assert_sources_finalized", lambda *_args: admission)
    kgx = Mock()
    monkeypatch.setattr(merge_kg, "merge", kgx)
    with pytest.raises(ValueError, match="publication path.*conflicts"):
        merge_kg.load_and_merge(str(config))
    kgx.assert_not_called()
    assert before == (config.read_bytes(), dependency.read_bytes())
