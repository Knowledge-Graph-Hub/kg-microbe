"""Optional source reads retain exact bytes, locator and absence without weakening required reads."""

import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

import pytest

from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import source_finalization as finalization
from kg_microbe.utils import transform_fingerprint as fingerprint
from kg_microbe.utils.optional_consumed_inputs import verify_optional_inputs, verify_recorded_optional_inputs

FIXTURE = Path(__file__).parent / "resources/metatraits_ec_inputs"
QUERY = "enzyme activity: fixture (EC1.1.1.1)"


class OptionalTransform(Transform):
    """Use the generic read contract with the actual unchanged EC parser and resolver."""

    OPTIONAL_CONSUMED_INPUTS = (("ec_to_go", "data/raw/ec2go.txt"),)
    _load_ec_to_go = MetaTraitsTransform._load_ec_to_go
    _resolve_enzyme_activity = MetaTraitsTransform._resolve_enzyme_activity


@pytest.fixture
def optional(tmp_path, monkeypatch):
    """Create only a disposable selected repository; no real raw authority is read."""
    monkeypatch.setattr(fingerprint, "_repo_root", lambda: tmp_path)
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    path = raw / "ec2go.txt"
    path.write_bytes((FIXTURE / "first.txt").read_bytes())
    value = OptionalTransform("fixture", tmp_path / "alternate", tmp_path / "transformed")
    value.enzyme_name_to_go = {}
    value.metpo_pattern_to_predicate = {}
    return value, path


def load(value):
    """Load and resolve using the actual production implementations."""
    value.ec_to_go = value._load_ec_to_go()
    return value._resolve_enzyme_activity(QUERY)["curie"]


def test_actual_loader_and_optional_absence(optional):
    """Presence yields GO and explicit absence retains the existing EC fallback."""
    value, path = optional
    assert load(value) == "GO:0004022"
    finalization.verify_consumed_inputs(value)
    path.unlink()
    value.begin_consumed_inputs()
    assert load(value) == "EC:1.1.1.1"
    assert value.optional_consumed_inputs["inputs"]["ec_to_go"]["sha256"] is None
    finalization.verify_consumed_inputs(value)


def test_never_read_and_undeclared_role_fail(optional):
    """Optional absence is evidence, not permission to omit the reader entirely."""
    value, _ = optional
    with pytest.raises(finalization.SourceFinalizationRequired):
        finalization.verify_consumed_inputs(value)
    with pytest.raises(finalization.SourceFinalizationRequired):
        with value.consume_optional_input("other"):
            pass


def test_immutable_parser_bytes_and_sticky_drift(optional):
    """A mutation after capture cannot alter the parser snapshot or certify the run."""
    value, path = optional
    with pytest.raises(finalization.SourceFinalizationRequired):
        with value.consume_optional_input("ec_to_go") as reader:
            path.write_bytes((FIXTURE / "second.txt").read_bytes())
            assert reader.read() == (FIXTURE / "first.txt").read_text()
    with pytest.raises(finalization.SourceFinalizationRequired, match="read failed"):
        finalization.verify_consumed_inputs(value)


def test_actual_decode_error_cannot_be_swallowed(optional):
    """The real EC reader propagates decode failure and retains failed consumption."""
    value, path = optional
    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        load(value)
    with pytest.raises(finalization.SourceFinalizationRequired, match="read failed"):
        finalization.verify_consumed_inputs(value)


@pytest.mark.parametrize("kind", ["delete", "same-size", "same-byte-retarget", "parent-retarget", "appear"])
def test_live_guard_lifecycle(optional, kind):
    """Byte and locator/absence changes fail even when digest or restored mtime alone would match."""
    value, path = optional
    first = (FIXTURE / "first.txt").read_bytes()
    if kind == "appear":
        path.unlink()
    if kind == "same-byte-retarget":
        original = path.with_name("original.txt")
        path.rename(original)
        path.symlink_to(original)
    load(value)
    if kind == "delete":
        path.unlink()
    elif kind == "same-size":
        stamp = path.stat()
        second = (FIXTURE / "second.txt").read_bytes()
        assert len(first) == len(second)
        path.write_bytes(second)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif kind == "same-byte-retarget":
        replacement = path.with_name("replacement.txt")
        replacement.write_bytes(first)
        path.unlink()
        path.symlink_to(replacement)
    elif kind == "parent-retarget":
        old_parent = path.parent.with_name("old-raw")
        path.parent.rename(old_parent)
        path.parent.symlink_to(old_parent, target_is_directory=True)
    else:
        path.write_bytes(first)
    with pytest.raises(finalization.SourceFinalizationRequired):
        finalization.verify_consumed_inputs(value)


def test_dangling_symlink_is_not_absence(optional):
    """An unreadable selected link must not become the permitted missing-input state."""
    value, path = optional
    path.unlink()
    path.symlink_to(path.with_name("nonexistent"))
    with pytest.raises(finalization.SourceFinalizationRequired):
        load(value)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "version",
        "bool-version",
        "extra-role",
        "missing-role",
        "extra-field",
        "wrong-locator",
        "wrong-resolved",
        "null",
        "short-sha",
        "upper-sha",
        "numeric-sha",
        "missing-snapshot",
        "wrong-snapshot",
    ],
)
def test_exact_record_contract(optional, change):
    """Require exact schema, declaration membership and matching immutable snapshot evidence."""
    value, path = optional
    load(value)
    contract, snapshots = copy.deepcopy(value.optional_consumed_inputs), value.consumed_input_snapshots
    state = contract["inputs"]["ec_to_go"]
    if change == "missing":
        contract = None
    elif change in ("version", "bool-version"):
        contract["version"] = True if change == "bool-version" else 2
    elif change == "extra-role":
        contract["inputs"]["extra"] = dict(state)
    elif change == "missing-role":
        contract["inputs"].clear()
    elif change == "extra-field":
        state["extra"] = "unreviewed"
    elif change in ("wrong-locator", "wrong-resolved"):
        alternative = path.with_name("same-bytes.txt")
        alternative.write_bytes(path.read_bytes())
        state["locator" if change == "wrong-locator" else "resolved"] = str(alternative)
    elif change == "missing-snapshot":
        snapshots.clear()
    elif change == "wrong-snapshot":
        snapshots["ec_to_go"]["sha256"] = "0" * 64
    else:
        state["sha256"] = {"null": None, "short-sha": "0", "upper-sha": "A" * 64, "numeric-sha": 3}[change]
    with pytest.raises(finalization.SourceFinalizationRequired):
        verify_optional_inputs(type(value), contract, snapshots)


@pytest.mark.parametrize("payload", ["duplicate", "nonfinite"])
def test_ambiguous_json_record_rejected(optional, payload):
    """Even duplicate keys hidden by ordinary json.loads cannot erase read evidence."""
    value, path = optional
    load(value)
    report = {
        "optional_consumed_inputs": value.optional_consumed_inputs,
        "consumed_inputs": value.consumed_input_snapshots,
    }
    serialized = json.dumps(report)
    serialized = (
        serialized[:-1] + ', "extra": 1, "extra": 2}' if payload == "duplicate" else serialized[:-1] + ', "extra": NaN}'
    )
    record = path.parent / "receipt.json"
    record.write_text(serialized)
    with pytest.raises(finalization.SourceFinalizationRequired):
        verify_recorded_optional_inputs(type(value), json.loads(serialized), report_path=record)


def test_capture_to_reader_retarget_rejected(optional, monkeypatch):
    """The hash captured before copying must equal the bytes actually handed to the parser."""
    value, path = optional
    real = value.consume_input

    def swapped(name, selected):
        """Inject equal-byte alternate resolution between admission and immutable copy."""
        replacement = path.with_name("other.txt")
        replacement.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(replacement)
        return real(name, selected)

    monkeypatch.setattr(value, "consume_input", swapped)
    with pytest.raises(finalization.SourceFinalizationRequired):
        load(value)
    with pytest.raises(finalization.SourceFinalizationRequired, match="read failed"):
        finalization.verify_consumed_inputs(value)


def test_exact_old_loader_negative_control(optional):
    """The actual prior method loads identical mappings but cannot satisfy the new read contract."""
    value, path = optional
    namespace = {"RAW_DATA_DIR": path.parent, "Dict": Dict}
    exec(compile((FIXTURE / "legacy_loader.txt").read_text(), "legacy_loader.txt", "exec"), namespace)  # noqa: S102
    assert namespace["_load_ec_to_go"](value)["1.1.1.1"]["go_id"] == "GO:0004022"
    with pytest.raises(finalization.SourceFinalizationRequired, match="optional"):
        finalization.verify_consumed_inputs(value)


def test_optional_only_declaration_refuses_actual_migration_script(tmp_path, monkeypatch, capsys):
    """Even a producer with no dynamic/inherited dependencies must not restamp optional-input history."""
    import kg_microbe.transform as dispatcher

    source = Path(__file__).parents[1] / "scripts/migrate_fingerprints.py"
    spec = importlib.util.spec_from_file_location("optional_migration", source)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dispatcher, "DATA_SOURCES", {"optional": SimpleNamespace(transform_class=OptionalTransform)})
    directory = tmp_path / "data/transformed/optional"
    directory.mkdir(parents=True)
    marker = directory / fingerprint.FINGERPRINT_FILE
    original = b'{"version": 2}\n'
    marker.write_bytes(original)
    assert migration.main() == 0
    assert "require a producer rerun" in capsys.readouterr().out
    assert marker.read_bytes() == original


def test_open_error_stays_failed_even_if_caller_catches(optional, monkeypatch):
    """Actual selected-file open errors cannot be downgraded to a successful empty lookup."""
    value, path = optional
    original = Path.open

    def failed_open(selected, *args, **kwargs):
        """Fail only the synthetic selected EC input, leaving all unrelated I/O real."""
        if selected == path:
            raise PermissionError("synthetic unreadable EC input")
        return original(selected, *args, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "open", failed_open)
        with pytest.raises(finalization.SourceFinalizationRequired):
            load(value)
    with pytest.raises(finalization.SourceFinalizationRequired, match="read failed"):
        finalization.verify_consumed_inputs(value)
