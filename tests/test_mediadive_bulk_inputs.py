"""Actual required MediaDive JSON reads survive finalization and public admission (#681)."""

import copy
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_merge_source_freshness import FIXTURES, merge_config, prepare_source, record_source

RESOURCES = Path(__file__).parent / "resources"
JSON_INPUTS = {
    "mediadive_media_list": "mediadive.json",
    "mediadive_media_detailed": "mediadive/media_detailed.json",
    "mediadive_media_strains": "mediadive/media_strains.json",
    "mediadive_solutions": "mediadive/solutions.json",
    "mediadive_compounds": "mediadive/compounds.json",
}
BULK_INPUTS = {name: path for name, path in JSON_INPUTS.items() if name != "mediadive_media_list"}


def write_bulk_inputs(raw):
    """Copy immutable five-role payloads to only an explicitly selected fixture raw tree."""
    payloads = json.loads((RESOURCES / "mediadive_bulk_inputs.json").read_text())
    for role, relative in JSON_INPUTS.items():
        path = raw / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payloads[role], sort_keys=True) + "\n")


@pytest.fixture
def bulk_build(tmp_path, monkeypatch):
    """Use actual constructors/JSON readers; isolate ontology and unrelated lexical-index work."""
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_roles", lambda self: None)
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_categories", lambda self: None)
    monkeypatch.setattr(
        mod,
        "ChemicalMappingLoader",
        lambda: SimpleNamespace(find_chebi_by_name=lambda name: None, get_canonical_name=lambda target: ""),
    )
    lookup = tmp_path / "lookup"
    lookup.mkdir()
    shutil.copyfile(RESOURCES / "provenance_serialization/bacdive.tsv", lookup / "bacdive.tsv")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", lookup)
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", scratch)

    def construct(raw):
        """Never invent a completed read or set using_bulk_data manually."""
        return mod.MediaDiveTransform(input_dir=raw, output_dir=tmp_path / "transformed")

    return construct


def test_declares_all_five_actual_json_reads_and_existing_lookup():
    """Missing old completion evidence must fail under registered current producer requirements."""
    assert set(mod.MediaDiveTransform.REQUIRED_CONSUMED_INPUTS) == {*JSON_INPUTS, "bacdive_taxon_lookup"}


def test_default_raw_root_is_consistent():
    """The list, bulk files and optional mappings share one actual default raw selection."""
    assert Path(mod.MediaDiveTransform.DEFAULT_INPUT_DIR) == Path(mod.RAW_DATA_DIR)


@pytest.mark.parametrize("default", [False, True])
def test_real_constructor_and_run_preserve_actual_read_bytes(tmp_path, monkeypatch, bulk_build, default):
    """Constructor bulk reads and run-time list/lookup reads enter the same immutable epoch."""
    raw = tmp_path / "selected-raw"
    write_bulk_inputs(raw)
    if default:
        monkeypatch.setattr(mod.MediaDiveTransform, "DEFAULT_INPUT_DIR", raw)
        monkeypatch.setattr(mod, "RAW_DATA_DIR", raw)
    value = bulk_build(None if default else raw)
    assert value.using_bulk_data
    assert value.input_base_dir == raw
    assert value.bulk_data_dir == raw / "mediadive"
    assert set(value.consumed_input_snapshots) == set(BULK_INPUTS)
    original = copy.deepcopy(value.consumed_input_snapshots)
    value.run(show_status=False)
    for role, relative in JSON_INPUTS.items():
        assert value.consumed_input_snapshots[role] == {
            "path": str((raw / relative).resolve()),
            "sha256": hashlib.sha256((raw / relative).read_bytes()).hexdigest(),
        }
    assert {key: value.consumed_input_snapshots[key] for key in BULK_INPUTS} == original
    value.verify_consumed_inputs()
    saved = copy.deepcopy(value.consumed_input_snapshots)
    value.run(show_status=False)
    assert value.consumed_input_snapshots == saved


@pytest.mark.parametrize("absolute", [False, True])
def test_data_file_override_is_the_consumed_list(tmp_path, bulk_build, absolute):
    """An explicit relative/absolute list is not ignored or rebound to unconsumed mediadive.json."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    selected = (tmp_path if absolute else raw) / "chosen.json"
    (raw / "mediadive.json").rename(selected)
    value = bulk_build(raw)
    value.run(data_file=selected if absolute else selected.name, show_status=False)
    assert value.consumed_input_snapshots["mediadive_media_list"] == {
        "path": str(selected.resolve()),
        "sha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
    }
    value.verify_consumed_inputs()


@pytest.mark.parametrize("role", BULK_INPUTS)
@pytest.mark.parametrize("damage", ["absent", "malformed"])
def test_bulk_json_failure_cannot_become_cache_fallback(tmp_path, monkeypatch, bulk_build, role, damage):
    """Every required file fails closed even when the old stale-cache override is present."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    path = raw / JSON_INPUTS[role]
    if damage == "absent":
        path.unlink()
    else:
        path.write_text("{not valid JSON\n")
    monkeypatch.setenv("KG_MEDIADIVE_ALLOW_STALE_CACHE", "true")
    with pytest.raises((FileNotFoundError, ValueError)):
        bulk_build(raw)
    output = tmp_path / "transformed/mediadive"
    assert not (output / "nodes.tsv").exists()
    assert not (output / "edges.tsv").exists()


@pytest.mark.parametrize("role", BULK_INPUTS)
def test_changed_constructor_bytes_fail_before_graph_writes_and_stay_failed(tmp_path, bulk_build, role):
    """Restoring bytes cannot reset a failed instance whose dictionaries belong to an older epoch."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    value = bulk_build(raw)
    original = copy.deepcopy(value.consumed_input_snapshots)
    path = raw / JSON_INPUTS[role]
    old = path.read_bytes()
    path.write_bytes(old + b" ")
    with pytest.raises(SourceFinalizationRequired):
        value.run(show_status=False)
    assert not value.output_node_file.exists()
    assert not value.output_edge_file.exists()
    assert {key: value.consumed_input_snapshots[key] for key in BULK_INPUTS} == original
    path.write_bytes(old)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        value.run(show_status=False)
    fresh = bulk_build(raw)
    fresh.run(show_status=False)
    fresh.verify_consumed_inputs()


def test_later_bulk_parser_cannot_hide_first_input_drift(tmp_path, monkeypatch, bulk_build):
    """Changing a constructor input during another parse is caught before graph output opens."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    real = mod.json.load
    seen = []

    def parse(reader, *args, **kwargs):
        """Keep actual JSON parsing while changing the earlier file, not its immutable snapshot."""
        seen.append(reader)
        if len(seen) == 2:
            with (raw / JSON_INPUTS["mediadive_media_detailed"]).open("ab") as changed:
                changed.write(b" ")
        return real(reader, *args, **kwargs)

    monkeypatch.setattr(mod.json, "load", parse)
    with pytest.raises(SourceFinalizationRequired):
        value = bulk_build(raw)
        value.run(show_status=False)
    assert len(seen) >= 2
    assert not (tmp_path / "transformed/mediadive/nodes.tsv").exists()


def test_caught_bulk_parser_interruption_remains_sticky(tmp_path, monkeypatch, bulk_build):
    """A caught BaseException during an actual repeated bulk read cannot certify the old dictionaries."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    value = bulk_build(raw)

    def interrupted(reader):
        """Exercise the snapshot's BaseException branch, including an empty error string."""
        reader.read(1)
        raise KeyboardInterrupt()

    with monkeypatch.context() as scoped:
        scoped.setattr(mod.json, "load", interrupted)
        with pytest.raises(KeyboardInterrupt):
            value._load_bulk_data()
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        value.run(show_status=False)
    assert not value.output_node_file.exists()


@pytest.fixture
def bulk_admitted(tmp_path, bulk_build, local_source_schema, request):
    """Use real JSON consumption and public finalization over unrelated immutable tiny graph members."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    symlink_role = getattr(request, "param", None)
    if symlink_role is not None:
        path = raw / JSON_INPUTS[symlink_role]
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    for source in ("ontologies", "bacdive"):
        prepare_source(tmp_path, source)
    value = bulk_build(raw)
    value.run(show_status=False)
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", value.output_dir / f"{kind}.tsv")
    report = value.finalize(fresh_run=True)
    record_source(value)
    config = merge_config(tmp_path, [value])
    admission = merge_kg._assert_sources_finalized(str(config))
    admission.verify()
    return value, config, report, admission


def test_all_five_snapshots_reach_finalization_marker_and_admission(bulk_admitted):
    """Persisted authority identities come from actual reads, not from post hoc fixture hashes."""
    value, _, report, admission = bulk_admitted
    marker = json.loads((value.output_dir / "source_fingerprint.json").read_text())
    for role in JSON_INPUTS:
        snapshot = value.consumed_input_snapshots[role]
        assert report["consumed_inputs"][role] == snapshot
        assert snapshot in report["inputs"]
        assert snapshot["path"] in marker["finalization_inputs"]
        assert admission.identities[Path(snapshot["path"])]["sha256"] == snapshot["sha256"]
    assert value.finalize() == report


@pytest.mark.parametrize("role", JSON_INPUTS)
def test_missing_named_read_rejects_old_or_incomplete_receipt(bulk_admitted, role):
    """Otherwise valid files and generic hashes cannot replace one required producer-read role."""
    value, config, _, _ = bulk_admitted
    path = value.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    report["consumed_inputs"].pop(role, None)
    path.write_text(json.dumps(report))
    for operation in (
        lambda: verify_finalized_source_files([value.output_node_file, value.output_edge_file]),
        lambda: merge_kg._assert_sources_finalized(str(config)),
        value.finalize,
    ):
        with pytest.raises(SourceFinalizationRequired):
            operation()


@pytest.mark.parametrize("role", JSON_INPUTS)
@pytest.mark.parametrize("damage", ["changed", "deleted"])
def test_each_actual_json_remains_guarded_after_admission(bulk_admitted, role, damage):
    """Fresh finalization, public admission and retained admission all reject changed consumed bytes."""
    value, config, _, admission = bulk_admitted
    before = {path.name: path.read_bytes() for path in value.output_dir.iterdir()}
    path = value.input_base_dir / JSON_INPUTS[role]
    if damage == "deleted":
        path.unlink()
    else:
        stat = path.stat()
        path.write_bytes(path.read_bytes().replace(b"\n", b" "))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    for operation in (
        lambda: value.finalize(fresh_run=True),
        lambda: merge_kg._assert_sources_finalized(str(config)),
        admission.verify,
    ):
        with pytest.raises(SourceFinalizationRequired):
            operation()
    assert {path.name: path.read_bytes() for path in value.output_dir.iterdir()} == before


@pytest.mark.parametrize("same_bytes", [False, True])
@pytest.mark.parametrize("role", BULK_INPUTS)
def test_constructor_file_symlink_cannot_retarget_before_run(tmp_path, bulk_build, role, same_bytes):
    """Resolved bytes alone cannot silently replace a constructor's original lexical input."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    path = raw / JSON_INPUTS[role]
    original = path.with_suffix(".original")
    path.rename(original)
    path.symlink_to(original)
    value = bulk_build(raw)
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(original.read_bytes() + (b"" if same_bytes else b" "))
    path.unlink()
    path.symlink_to(replacement)
    with pytest.raises(SourceFinalizationRequired):
        value.run(show_status=False)
    assert not value.output_node_file.exists()


@pytest.mark.parametrize("same_bytes", [False, True])
def test_later_parser_detects_earlier_file_symlink_retarget(tmp_path, monkeypatch, bulk_build, same_bytes):
    """A later JSON callback cannot move an earlier locator while its old target stays unchanged."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    path = raw / JSON_INPUTS["mediadive_media_detailed"]
    original, replacement = path.with_suffix(".original"), path.with_suffix(".replacement")
    path.rename(original)
    replacement.write_bytes(original.read_bytes() + (b"" if same_bytes else b" "))
    path.symlink_to(original)
    real = mod.json.load
    calls = []

    def parse(reader, *args, **kwargs):
        """Retarget a lexical path only; the previously resolved file deliberately remains valid."""
        calls.append(reader)
        if len(calls) == 2:
            path.unlink()
            path.symlink_to(replacement)
        return real(reader, *args, **kwargs)

    monkeypatch.setattr(mod.json, "load", parse)
    with pytest.raises(SourceFinalizationRequired):
        value = bulk_build(raw)
        value.run(show_status=False)
    assert not (tmp_path / "transformed/mediadive/nodes.tsv").exists()


@pytest.mark.parametrize("same_bytes", [False, True])
@pytest.mark.parametrize("bulk_admitted", JSON_INPUTS, indirect=True)
def test_each_bulk_locator_is_retained_after_public_admission(bulk_admitted, same_bytes):
    """Each current read keeps its lexical binding through public checks and the retained guard."""
    value, config, _, admission = bulk_admitted
    before = {path.name: path.read_bytes() for path in value.output_dir.iterdir()}
    paths = [value.input_base_dir / relative for relative in JSON_INPUTS.values()]
    path = next(path for path in paths if path.is_symlink())
    # Preserve the original resolved input so a digest-only verifier could
    # still succeed there; the selected lexical path now means a different file.
    original = path.resolve()
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(original.read_bytes() + (b"" if same_bytes else b" "))
    path.unlink()
    path.symlink_to(replacement)
    for operation in (
        value.verify_consumed_inputs,
        lambda: merge_kg._assert_sources_finalized(str(config)),
        admission.verify,
    ):
        with pytest.raises(SourceFinalizationRequired):
            operation()
    assert {path.name: path.read_bytes() for path in value.output_dir.iterdir()} == before


def test_selected_raw_directory_symlink_cannot_retarget(tmp_path, bulk_build):
    """An equal-byte alternate raw tree is not the original constructor epoch."""
    original, raw, replacement = tmp_path / "original", tmp_path / "raw", tmp_path / "replacement"
    write_bulk_inputs(original)
    shutil.copytree(original, replacement)
    raw.symlink_to(original, target_is_directory=True)
    value = bulk_build(raw)
    raw.unlink()
    raw.symlink_to(replacement, target_is_directory=True)
    with pytest.raises(SourceFinalizationRequired):
        value.run(show_status=False)
    assert not value.output_node_file.exists()


@pytest.mark.parametrize("damage", ["missing", "missing-role", "wrong-locator", "wrong-resolved", "wrong-hash"])
def test_public_admission_requires_exact_persisted_bulk_contract(bulk_admitted, damage):
    """A valid generic consumed hash does not replace the serialized required lexical proof."""
    value, config, _, _ = bulk_admitted
    path = value.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    role = "mediadive_solutions"
    if damage == "missing":
        report.pop("producer_native_inputs")
    elif damage == "missing-role":
        report["producer_native_inputs"]["inputs"].pop(role)
    else:
        field = damage.removeprefix("wrong-")
        report["producer_native_inputs"]["inputs"][role][field if field != "hash" else "sha256"] = (
            "0" * 64 if field == "hash" else str(value.input_base_dir / "mediadive/compounds.json")
        )
    path.write_text(json.dumps(report))
    for operation in (
        lambda: verify_finalized_source_files([value.output_node_file, value.output_edge_file]),
        lambda: merge_kg._assert_sources_finalized(str(config)),
        value.finalize,
    ):
        with pytest.raises(SourceFinalizationRequired):
            operation()


@pytest.mark.parametrize("missing", ["medium", "solution"])
@pytest.mark.parametrize("cached", [False, True])
def test_requested_bulk_records_fail_before_any_graph_write(tmp_path, monkeypatch, bulk_build, missing, cached):
    """Neither absent details nor missing first-level solution records may be rescued by stale YAML."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    shutil.copyfile(RESOURCES / "provenance_serialization/mediadive.json", raw / "mediadive.json")
    if missing == "solution":
        (raw / JSON_INPUTS["mediadive_media_detailed"]).write_text(
            json.dumps({"1": {"medium": {"id": 1}, "solutions": [{"id": 77}]}})
        )
    cache = tmp_path / "old-yaml"
    cache.mkdir()
    stale = cache / "1.yaml"
    stale_bytes = b"medium: {id: 1, name: Obsolete}\nsolutions: [{id: 77}]\n"
    if cached:
        stale.write_bytes(stale_bytes)
    monkeypatch.setattr(mod, "MEDIADIVE_MEDIUM_YAML_DIR", cache)
    monkeypatch.setattr(mod, "MEDIADIVE_MEDIUM_STRAIN_YAML_DIR", cache)
    value = bulk_build(raw)

    def no_fallback(*args, **kwargs):
        """Reject any alternative parser or request for a missing required record."""
        pytest.fail("requested bulk record attempted YAML/HTTP fallback")

    monkeypatch.setattr(value, "_get_mediadive_json", no_fallback)
    monkeypatch.setattr(value, "download_yaml_and_get_json", no_fallback)
    monkeypatch.setattr(yaml, "safe_load", no_fallback)
    previous = {value.output_node_file: b"previous nodes\n", value.output_edge_file: b"previous edges\n"}
    for path, payload in previous.items():
        path.write_bytes(payload)
    with pytest.raises(FileNotFoundError, match="medium" if missing == "medium" else "solution"):
        value.run(show_status=False)
    assert {path: path.read_bytes() for path in previous} == previous
    assert not (mod.MEDIADIVE_TMP_DIR / "mediadive.tsv").exists()
    assert value.api_calls_made == 0
    assert stale.read_bytes() == stale_bytes if cached else not stale.exists()


def test_present_metadata_only_medium_is_not_a_missing_record(tmp_path, monkeypatch, bulk_build):
    """A real present public medium without a solutions key remains an accepted typed declaration."""
    raw = tmp_path / "raw"
    write_bulk_inputs(raw)
    shutil.copyfile(RESOURCES / "provenance_serialization/mediadive.json", raw / "mediadive.json")
    detail = {"1": {"medium": {"id": 1, "name": "Fixture medium"}}}
    (raw / JSON_INPUTS["mediadive_media_detailed"]).write_text(json.dumps(detail))
    cache = tmp_path / "unused-yaml"
    monkeypatch.setattr(mod, "MEDIADIVE_MEDIUM_YAML_DIR", cache)
    monkeypatch.setattr(mod, "MEDIADIVE_MEDIUM_STRAIN_YAML_DIR", cache)
    value = bulk_build(raw)

    def no_fallback(*args, **kwargs):
        """Present metadata is complete evidence for this case, not a request to fill a recipe."""
        pytest.fail("metadata-only bulk medium attempted YAML/HTTP fallback")

    monkeypatch.setattr(value, "_get_mediadive_json", no_fallback)
    monkeypatch.setattr(yaml, "safe_load", no_fallback)
    value.run(show_status=False)
    with value.output_node_file.open(newline="") as stream:
        medium = [row for row in csv.DictReader(stream, delimiter="\t") if row["id"] == "mediadive.medium:1"]
    assert len(medium) == 1
    assert medium[0]["name"] == "Fixture medium"
    assert medium[0]["category"] == mod.MEDIUM_DEFINED_CATEGORY
    assert value.media_detailed == detail
    assert value.api_calls_made == 0
    assert not cache.exists()
    value.verify_consumed_inputs()
