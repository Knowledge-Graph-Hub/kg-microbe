"""Track both optional effective-raw mappings from constructor through public admission (#1205)."""

import copy
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.merge_utils import merge_kg
from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.utils.optional_consumed_inputs import optional_input_paths, verify_recorded_optional_inputs
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_mediadive_bulk_inputs import write_bulk_inputs
from tests.test_merge_source_freshness import (
    FIXTURES,
    merge_config,
    prepare_source,
    record_source,
    write_empty_mediadive_audit,
)

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = Path(__file__).parent / "resources"
ROLES = dict(mod.MediaDiveTransform.OPTIONAL_RAW_CONSUMED_INPUTS)


def write_inputs(raw):
    """Copy immutable synthetic inputs into only the selected disposable directory."""
    raw.mkdir(parents=True, exist_ok=True)
    for role, filename in ROLES.items():
        fixture = "hydrate.tsv" if role.endswith("hydrate") else "strict.tsv"
        shutil.copyfile(RESOURCES / "mediadive_raw_inputs" / fixture, raw / filename)
    write_bulk_inputs(raw)


@pytest.fixture
def build(tmp_path, monkeypatch):
    """Keep actual constructor/raw/bulk readers; stub only unrelated ontology and higher-priority index loads."""
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_roles", lambda self: None)
    monkeypatch.setattr(mod.MediaDiveTransform, "_load_chebi_categories", lambda self: None)
    monkeypatch.setattr(
        mod,
        "ChemicalMappingLoader",
        lambda: SimpleNamespace(find_chebi_by_name=lambda name: None, get_canonical_name=lambda target: ""),
    )
    lookup_dir = tmp_path / "lookup"
    lookup_dir.mkdir()
    shutil.copyfile(RESOURCES / "provenance_serialization/bacdive.tsv", lookup_dir / "bacdive.tsv")
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", lookup_dir)
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)

    def construct(raw=None):
        """Select one raw directory and retain actual constructor-time mapping snapshots."""
        return mod.MediaDiveTransform(raw or tmp_path / "raw", tmp_path / "transformed")

    return construct


def read_lookup(value):
    """Meet both run-time required reads using real immutable consumption, without graph emission."""
    with value.consume_bulk_input("mediadive_media_list", value.input_base_dir / "mediadive.json") as reader:
        media_list = json.load(reader)
    with value.consume_input("bacdive_taxon_lookup", mod.BACDIVE_TMP_DIR / "bacdive.tsv") as reader:
        reader.read()
    assert media_list["data"] == []
    value._material_scope_audit = mod.MaterialScopeAudit(value, media_list)


def test_constructor_reads_both_roles_and_preserves_priority(tmp_path, build):
    """Even a shadowed strict claim remains a consumed input, not an untracked optimization."""
    write_inputs(tmp_path / "raw")
    value = build()
    assert value.standardize_compound_id("1", "Offline strict fixture") == "PubChem:100"
    assert value.standardize_compound_id("2", "Offline second fixture") == "PubChem:200"
    assert value.standardize_compound_id("3", "Offline shared fixture") == "PubChem:301"
    assert set(value.optional_consumed_inputs["inputs"]) == set(ROLES)
    read_lookup(value)
    value.verify_consumed_inputs()


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("change", ["replace", "delete", "appear", "same-size", "retarget", "dangling"])
def test_original_epoch_detects_each_optional_path(tmp_path, build, role, change):
    """Each selected raw input preserves bytes, existence and lexical identity."""
    raw = tmp_path / "raw"
    write_inputs(raw)
    path = raw / ROLES[role]
    first = path.read_bytes()
    if change in {"appear", "dangling"}:
        path.unlink()
    if change == "retarget":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    value = build()
    read_lookup(value)
    value.verify_consumed_inputs()
    if change == "delete":
        path.unlink()
    elif change == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(first)
        replacement.replace(path)
    elif change == "same-size":
        before = path.stat()
        path.write_bytes(first.replace(b"PubChem:", b"PubChem0"))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == "retarget":
        replacement = path.with_suffix(".other")
        replacement.write_bytes(first)
        path.unlink()
        path.symlink_to(replacement)
    elif change == "dangling":
        path.symlink_to(path.with_suffix(".missing"))
    else:
        path.write_bytes(first)
    with pytest.raises(SourceFinalizationRequired):
        value.verify_consumed_inputs()


def test_real_repeated_runs_keep_constructor_epoch(tmp_path, build):
    """Unchanged actual empty-medium runs work; changed cached mappings require a new instance."""
    raw = tmp_path / "raw"
    write_inputs(raw)
    value = build()
    original = copy.deepcopy(value.optional_consumed_inputs)
    value.run(show_status=False)
    value.run(show_status=False)
    assert value.optional_consumed_inputs == original
    outputs = {p.name: p.read_bytes() for p in value.output_dir.iterdir()}
    path = raw / ROLES["micromediaparam_strict"]
    path.write_bytes(path.read_bytes().replace(b"PubChem:100", b"PubChem:101"))
    with pytest.raises(SourceFinalizationRequired):
        value.run(show_status=False)
    assert {p.name: p.read_bytes() for p in value.output_dir.iterdir()} == outputs
    assert value.standardize_compound_id("1", "Offline strict fixture") == "PubChem:100"
    path.write_bytes(path.read_bytes().replace(b"PubChem:101", b"PubChem:100"))
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        value.run(show_status=False)
    fresh = build()
    fresh.run(show_status=False)


def test_custom_raw_location_and_switch_are_not_rebased(tmp_path, build):
    """A custom lexical directory wins and cannot be switched underneath cached mappings."""
    raw, other = tmp_path / "chosen", tmp_path / "other"
    write_inputs(raw)
    write_inputs(other)
    value = build(raw)
    read_lookup(value)
    assert all(Path(state["locator"]).parent == raw for state in value.optional_consumed_inputs["inputs"].values())
    value.verify_consumed_inputs()
    value.input_base_dir = other
    with pytest.raises(SourceFinalizationRequired, match="locator"):
        value.verify_consumed_inputs()


@pytest.mark.parametrize("kind", ["change-first-while-second-parses", "interrupt"])
def test_actual_parser_window_and_baseexception_are_sticky(tmp_path, build, monkeypatch, kind):
    """A later parser cannot erase earlier input evidence, even if its failure is caught."""
    raw = tmp_path / "raw"
    write_inputs(raw)
    value = build()
    read_lookup(value)
    real = mod.pd.read_csv
    seen = []

    def parse(reader, *args, **kwargs):
        """Inject drift or interruption while the real immutable parser handle is open."""
        seen.append(reader)
        assert hasattr(reader, "read"), "Production must parse an immutable handle, not reopen raw input"
        if len(seen) == 2:
            if kind == "interrupt":
                raise KeyboardInterrupt("fixture")
            path = raw / ROLES["micromediaparam_hydrate"]
            path.write_bytes(path.read_bytes() + b"\n")
        return real(reader, *args, **kwargs)

    monkeypatch.setattr(mod.pd, "read_csv", parse)
    with pytest.raises((SourceFinalizationRequired, KeyboardInterrupt)):
        value._load_micromediaparam_mappings()
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        value.verify_consumed_inputs()


@pytest.fixture
def admitted(tmp_path, monkeypatch, local_source_schema, build, request):
    """Finalize real registered producer fixtures with constructor-consumed raw mappings."""
    raw = tmp_path / "raw"
    write_inputs(raw)
    mode = getattr(request, "param", "present")
    if mode == "absent":
        for filename in ROLES.values():
            (raw / filename).unlink()
    elif mode == "symlink":
        target = raw.with_name("actual-raw")
        raw.rename(target)
        raw.symlink_to(target, target_is_directory=True)
    for source in ("ontologies", "bacdive"):
        prepare_source(tmp_path, source)
    value = build()
    read_lookup(value)
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", value.output_dir / f"{kind}.tsv")
    write_empty_mediadive_audit(value)
    value.finalize(fresh_run=True)
    record_source(value)
    config = merge_config(tmp_path, [value])
    script = ROOT / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("media_raw_diagnostic", script)
    checker = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, checker)
    spec.loader.exec_module(checker)
    monkeypatch.setattr(checker, "TRANSFORMED_DIR", tmp_path / "transformed")
    return value, config, checker


@pytest.mark.parametrize("role", ROLES)
def test_actual_public_and_diagnostic_reject_raw_drift(admitted, build, role):
    """The original reproduction must now reject changed raw bytes without changing outputs or markers."""
    value, config, checker = admitted
    before = {p.name: p.read_bytes() for p in value.output_dir.iterdir()}
    gate = merge_kg._assert_sources_finalized(str(config))
    assert checker.check_source("mediadive", "HEAD").status == "FRESH"
    path = value.input_base_dir / ROLES[role]
    label, old, new = (
        ("Offline strict fixture", "PubChem:100", "PubChem:101")
        if role.endswith("strict")
        else ("Offline second fixture", "PubChem:200", "PubChem:201")
    )
    path.write_bytes(path.read_bytes().replace(old.encode(), new.encode()))
    assert value.standardize_compound_id("1", label) == old
    assert build(value.input_base_dir).standardize_compound_id("1", label) == new
    assert checker.check_source("mediadive", "HEAD").status == "STALE_VS_DATA"
    with pytest.raises(SourceFinalizationRequired):
        merge_kg._assert_sources_finalized(str(config))
    with pytest.raises(SourceFinalizationRequired):
        gate.verify()
    assert before == {p.name: p.read_bytes() for p in value.output_dir.iterdir()}


@pytest.mark.parametrize("change", ["missing-contract", "missing-locator", "wrong-locator", "wrong-resolved"])
def test_recorded_raw_directory_contract_is_required(admitted, change):
    """A current digest cannot replace the registered effective raw locator contract."""
    value, _, _ = admitted
    path = value.output_dir / "source_finalization.json"
    record = json.loads(path.read_bytes())
    if change == "missing-contract":
        record.pop("optional_consumed_inputs")
    elif change == "missing-locator":
        record.pop("raw_input_locator")
    elif change == "wrong-locator":
        record["raw_input_locator"] = str(value.output_dir)
    else:
        record["raw_input_directory"] = str(value.output_dir)
    path.write_text(json.dumps(record))
    with pytest.raises(SourceFinalizationRequired):
        verify_recorded_optional_inputs(type(value), record, report_path=path)


def test_raw_declaration_requires_context_and_unique_modes(tmp_path):
    """Raw roles never silently select repository raw or override a repository role."""
    with pytest.raises(SourceFinalizationRequired):
        optional_input_paths(mod.MediaDiveTransform)
    producer = SimpleNamespace(
        OPTIONAL_CONSUMED_INPUTS=(("one", "data/raw/one"),), OPTIONAL_RAW_CONSUMED_INPUTS=(("one", "one"),)
    )
    with pytest.raises(SourceFinalizationRequired):
        optional_input_paths(producer, input_dir=tmp_path)


@pytest.mark.parametrize("admitted", ["absent", "symlink"], indirect=True)
def test_optional_absence_and_raw_symlink_survive_repeat_but_not_drift(admitted):
    """Absent and lexical raw selections are valid until the exact original state changes."""
    value, config, checker = admitted
    original = (value.output_dir / "source_finalization.json").read_bytes()
    gate = merge_kg._assert_sources_finalized(str(config))
    assert checker.check_source("mediadive", "HEAD").status == "FRESH"
    value.finalize()
    assert (value.output_dir / "source_finalization.json").read_bytes() == original
    raw = value.input_base_dir
    if raw.is_symlink():
        replacement = raw.with_name("replacement-raw")
        shutil.copytree(raw, replacement)
        raw.unlink()
        raw.symlink_to(replacement, target_is_directory=True)
    else:
        shutil.copyfile(RESOURCES / "mediadive_raw_inputs/strict.tsv", raw / ROLES["micromediaparam_strict"])
    assert checker.check_source("mediadive", "HEAD").status == "STALE_VS_DATA"
    for operation in (lambda: merge_kg._assert_sources_finalized(str(config)), gate.verify, value.finalize):
        with pytest.raises(SourceFinalizationRequired):
            operation()
    assert (value.output_dir / "source_finalization.json").read_bytes() == original


@pytest.mark.parametrize("relative", ["", "../escape.tsv", "/absolute.tsv"])
def test_invalid_raw_relative_declarations_rejected(tmp_path, relative):
    """Optional raw declarations cannot escape or omit their selected raw base."""
    producer = SimpleNamespace(OPTIONAL_RAW_CONSUMED_INPUTS=(("raw", relative),))
    with pytest.raises(SourceFinalizationRequired):
        optional_input_paths(producer, input_dir=tmp_path)


def test_raw_optional_marker_migration_requires_rerun(tmp_path, monkeypatch, capsys):
    """Existing graphs cannot gain raw read evidence by a fingerprint-only migration."""
    import kg_microbe.transform as dispatcher

    spec = importlib.util.spec_from_file_location("media_raw_migration", ROOT / "scripts/migrate_fingerprints.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        dispatcher, "DATA_SOURCES", {"mediadive": SimpleNamespace(transform_class=mod.MediaDiveTransform)}
    )
    output = tmp_path / "data/transformed/mediadive"
    output.mkdir(parents=True)
    marker = output / "source_fingerprint.json"
    original = b'{"version": 2}\n'
    marker.write_bytes(original)
    assert migration.main() == 0
    assert "require a producer rerun" in capsys.readouterr().out
    assert marker.read_bytes() == original


def test_shadowed_strict_claim_is_still_guarded(tmp_path, build):
    """Hydrate precedence is not permission to omit the lower-priority input's identity."""
    raw = tmp_path / "raw"
    write_inputs(raw)
    value = build()
    read_lookup(value)
    path = raw / ROLES["micromediaparam_strict"]
    path.write_bytes(path.read_bytes().replace(b"PubChem:300", b"PubChem:302"))
    assert value.standardize_compound_id("1", "Offline shared fixture") == "PubChem:301"
    assert build().standardize_compound_id("1", "Offline shared fixture") == "PubChem:301"
    with pytest.raises(SourceFinalizationRequired):
        value.verify_consumed_inputs()
