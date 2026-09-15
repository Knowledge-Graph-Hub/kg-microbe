"""Bind production merge publication to the exact source evidence admitted before KGX."""

import os
import shutil
from multiprocessing.pool import ThreadPool
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_merge_source_freshness import merge_config, prepare_source, record_source

pytestmark = pytest.mark.usefixtures("local_source_schema")


@pytest.mark.parametrize("compression", [None, "tar.gz"])
@pytest.mark.parametrize("change", ["graph", "valid_replacement", "marker", "audit", "missing", "config", "restored"])
def test_public_merge_refuses_changed_admitted_evidence(tmp_path, monkeypatch, change, compression):
    """Even a separately valid concurrent producer run cannot replace the original admitted bundle."""
    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["destination"]["tsv"]["compression"] = compression
    config.write_text(yaml.safe_dump(payload))
    published = tmp_path / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"previous complete archive")

    def emit_staged_pair(config_file, **kwargs):
        """Model a competing producer between the real public gate and staged publication."""
        del kwargs
        if change in {"graph", "valid_replacement"}:
            path = source.output_edge_file
            path.write_text(path.read_text().replace("\tfixture:2\t", "\tfixture:1\t"))
            if change == "valid_replacement":
                source.finalize(fresh_run=True)
                record_source(source)
                merge_kg._assert_sources_finalized(str(config))
        elif change in {"marker", "audit"}:
            path = source.output_dir / (
                "source_fingerprint.json" if change == "marker" else "source_canonicalization.tsv"
            )
            with path.open("a") as stream:
                stream.write("\n")
        elif change == "missing":
            (source.output_dir / "source_finalization.json").unlink()
        elif change == "config":
            with config.open("a") as stream:
                stream.write("# a concurrently edited configuration\n")
        else:
            replacement = source.output_edge_file.with_suffix(".replacement")
            shutil.copyfile(source.output_edge_file, replacement)
            replacement.replace(source.output_edge_file)
        staging = Path(merge_kg.parse_load_config(config_file)["configuration"]["output_directory"])
        shutil.copyfile(source.output_node_file, staging / "fixture_nodes.tsv")
        shutil.copyfile(source.output_edge_file, staging / "fixture_edges.tsv")

    monkeypatch.setattr(merge_kg, "merge", emit_staged_pair)
    with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
        merge_kg.load_and_merge(str(config))
    assert published.read_bytes() == b"previous complete archive"
    assert sorted(path.name for path in published.parent.iterdir()) == ["fixture.tar.gz"]


def test_unchanged_admitted_source_publishes_normally(tmp_path, monkeypatch):
    """The guard permits a stable finalized bundle without requiring graph copies."""
    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])

    def emit_staged_pair(config_file, **kwargs):
        """Write a tiny valid KGX result while leaving all admitted evidence untouched."""
        del kwargs
        staging = Path(merge_kg.parse_load_config(config_file)["configuration"]["output_directory"])
        shutil.copyfile(source.output_node_file, staging / "fixture_nodes.tsv")
        shutil.copyfile(source.output_edge_file, staging / "fixture_edges.tsv")

    monkeypatch.setattr(merge_kg, "merge", emit_staged_pair)
    merge_kg.load_and_merge(str(config))
    assert (tmp_path / "published/fixture_manifest.json").is_file()


def test_mutation_during_verification_is_not_snapshotted_as_current(tmp_path, monkeypatch):
    """Capture belongs to the validator's original read, not a later snapshot of changed evidence."""
    from kg_microbe.merge_utils.source_freshness import _SourceFreshness

    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    original = _SourceFreshness._check_marker

    def change_after_metadata_check(self, *args, **kwargs):
        """Modify a previously hashed member while admission is still in progress."""
        original(self, *args, **kwargs)
        with source.output_node_file.open("a") as stream:
            stream.write("fixture:3\tbiolink:NamedThing\tNew\tinfores:test\t\n")

    def unexpected_merge(*args, **kwargs):
        """Admission itself must fail before KGX gets the changed source."""
        raise AssertionError("KGX must not run")

    monkeypatch.setattr(_SourceFreshness, "_check_marker", change_after_metadata_check)
    monkeypatch.setattr(merge_kg, "merge", unexpected_merge)
    with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
        merge_kg.load_and_merge(str(config))
    assert not (tmp_path / "published").exists()


@pytest.mark.parametrize("change", ["upstream", "dynamic_input", "symlink"])
def test_admission_binds_upstream_dynamic_input_and_original_locator(tmp_path, monkeypatch, change):
    """Supporting evidence and lexical aliases cannot be swapped while admitted graph bytes stay the same."""
    upstream = prepare_source(tmp_path, "ontologies")
    source = prepare_source(tmp_path, "bacdive")
    lookup = tmp_path / "lookup.tsv"
    shutil.copyfile(Path(__file__).parent / "resources/merge_source_freshness/lookup.tsv", lookup)
    source.finalization_inputs = (*source.finalization_inputs, str(lookup))
    record_source(source)
    config = merge_config(tmp_path, [source])
    alias = tmp_path / "selected_edges.tsv"
    alias.symlink_to(source.output_edge_file)
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["source"]["selected_0"]["input"]["filename"][-1] = str(alias)
    config.write_text(yaml.safe_dump(payload))
    original = merge_kg._assert_sources_finalized

    def mutate_after_admission(*args, **kwargs):
        """Deterministically change evidence between admission and staged configuration creation."""
        admitted = original(*args, **kwargs)
        if change == "upstream":
            path = upstream.output_dir / "source_canonicalization.tsv"
            with path.open("a") as stream:
                stream.write("\n")
        elif change == "dynamic_input":
            with lookup.open("a") as stream:
                stream.write("changed\n")
        else:
            replacement = tmp_path / "replacement_edges.tsv"
            shutil.copyfile(source.output_edge_file, replacement)
            alias.unlink()
            alias.symlink_to(replacement)
        return admitted

    def emit_staged_pair(config_file, **kwargs):
        """Keep the staged graph valid so only the unchanged-admission requirement fails."""
        del kwargs
        staging = Path(merge_kg.parse_load_config(config_file)["configuration"]["output_directory"])
        shutil.copyfile(source.output_node_file, staging / "fixture_nodes.tsv")
        shutil.copyfile(source.output_edge_file, staging / "fixture_edges.tsv")

    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", mutate_after_admission)
    monkeypatch.setattr(merge_kg, "merge", emit_staged_pair)
    with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
        merge_kg.load_and_merge(str(config))
    assert not any((tmp_path / "published").glob("*"))


def test_real_kgx_cannot_publish_changed_unfinalized_assertion(tmp_path, monkeypatch):
    """Use real parser, export, closure validation and archive writer after deterministic source drift."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx.cli import cli_utils

    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["destination"]["tsv"]["compression"] = "tar.gz"
    config.write_text(yaml.safe_dump(payload))
    published = tmp_path / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"previous complete archive")
    original = merge_kg.merge

    def mutate_before_real_kgx(*args, **kwargs):
        """Reproduce the original admitted-read race without mocking the KGX pipeline."""
        source.output_edge_file.write_text(
            source.output_edge_file.read_text().replace("\tfixture:2\t", "\tfixture:1\t")
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(cli_utils, "Pool", ThreadPool)
    monkeypatch.setattr(merge_kg, "merge", mutate_before_real_kgx)
    with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
        merge_kg.load_and_merge(str(config))
    assert published.read_bytes() == b"previous complete archive"


def test_new_cwd_file_cannot_shadow_admitted_config_relative_input(tmp_path, monkeypatch):
    """A higher-precedence newly created input is drift even when the admitted target survives unchanged."""
    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["source"]["selected_0"]["input"]["filename"] = [
        "transformed/rhea_mappings/nodes.tsv",
        "transformed/rhea_mappings/edges.tsv",
    ]
    config.write_text(yaml.safe_dump(payload))
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    original = merge_kg._assert_sources_finalized

    def shadow_after_admission(*args, **kwargs):
        """Create the exact higher-priority CWD candidates used by the real staging resolver."""
        admitted = original(*args, **kwargs)
        shadow = working / "transformed/rhea_mappings"
        shadow.mkdir(parents=True)
        shutil.copyfile(source.output_node_file, shadow / "nodes.tsv")
        (shadow / "edges.tsv").write_text(source.output_edge_file.read_text().replace("\tfixture:2\t", "\tfixture:1\t"))
        return admitted

    def emit_selected_pair(config_file, **kwargs):
        """Read actual staged input locators instead of retaining the known original fixture paths."""
        del kwargs
        staged = merge_kg.parse_load_config(config_file)
        selected = staged["merged_graph"]["source"]["selected_0"]["input"]["filename"]
        staging = Path(staged["configuration"]["output_directory"])
        shutil.copyfile(selected[0], staging / "fixture_nodes.tsv")
        shutil.copyfile(selected[1], staging / "fixture_edges.tsv")

    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", shadow_after_admission)
    monkeypatch.setattr(merge_kg, "merge", emit_selected_pair)
    with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
        merge_kg.load_and_merge(str(config))
    assert not any((tmp_path / "published").glob("*"))


@pytest.mark.parametrize("change_config", [True, False])
def test_diagnostic_mode_cannot_change_after_admission(tmp_path, monkeypatch, change_config):
    """An intentional source opt-out still binds the configuration that labels diagnostic artifacts."""
    source = prepare_source(tmp_path, "rhea_mappings")
    (source.output_dir / "source_finalization.json").unlink()
    (source.output_dir / "source_fingerprint.json").unlink()
    config = merge_config(tmp_path, [source], diagnostic=True)
    original = merge_kg._assert_sources_finalized

    def change_mode_after_admission(*args, **kwargs):
        """Try to relabel unchecked inputs as a production release after the diagnostic decision."""
        admitted = original(*args, **kwargs)
        if change_config:
            payload = yaml.safe_load(config.read_text())
            payload["configuration"]["allow_unfinalized_sources"] = False
            config.write_text(yaml.safe_dump(payload))
        return admitted

    def emit_staged_pair(config_file, **kwargs):
        """Keep the output graph valid so its mode identity is the deciding guard."""
        del kwargs
        staging = Path(merge_kg.parse_load_config(config_file)["configuration"]["output_directory"])
        shutil.copyfile(source.output_node_file, staging / "fixture_nodes.tsv")
        shutil.copyfile(source.output_edge_file, staging / "fixture_edges.tsv")

    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", change_mode_after_admission)
    monkeypatch.setattr(merge_kg, "merge", emit_staged_pair)
    if change_config:
        with pytest.raises(SourceFinalizationRequired, match="admitted|admission"):
            merge_kg.load_and_merge(str(config))
        assert not any((tmp_path / "published").glob("*"))
    else:
        merge_kg.load_and_merge(str(config))
        manifest = yaml.safe_load((tmp_path / "published/fixture_manifest.json").read_text())
        assert manifest["provenance"]["source_finalization"] == {"required": False, "diagnostic_opt_out": True}


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named FIFO control requires a POSIX filesystem")
def test_nonregular_input_is_rejected_before_potentially_blocking_open(tmp_path, monkeypatch):
    """Opening a FIFO would block before fstat; reject its initial mode without opening it."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    fifo = tmp_path / "input.tsv"
    os.mkfifo(fifo)
    original_open = Path.open

    def forbidden_fifo_open(path, *args, **kwargs):
        """Make a regression fail promptly instead of hanging the test runner."""
        if path == fifo:
            raise AssertionError("FIFO must not be opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden_fifo_open)
    with pytest.raises(SourceFinalizationRequired, match="not a regular file"):
        SourceAdmission().capture(fifo)
