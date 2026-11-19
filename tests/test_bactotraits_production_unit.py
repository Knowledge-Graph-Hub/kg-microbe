"""Reject drift of shared configuration and retain raw side effects from a real child process."""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/adhoc/run_bactotraits_production_unit_20261116.py"


@pytest.fixture
def unit(tmp_path, monkeypatch):
    """Load the launcher against an isolated filesystem with one deliberately tiny child."""
    spec = importlib.util.spec_from_file_location("bactotraits_production_unit", HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    root = tmp_path.resolve()
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    stages = root / "units"
    monkeypatch.setattr(helper, "ROOT", root)
    monkeypatch.setattr(helper, "STAGES", stages)
    prefixmap = root / "kg_microbe/transform_utils/prefixmap.json"
    profile = root / "kg_microbe/profiles/ingredient_scope_v1.yaml"
    for path in (prefixmap, profile):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original configuration\n")
    (raw / "original.json").write_text('{"before": true}\n')
    plan = {
        "stage": str(stages / "one"),
        "source": "offline-test-child",
        "environment": {},
        "originals": [],
        "implementation_and_policy_inputs": {
            str(path.relative_to(root)): helper.identity(path) for path in (prefixmap, profile)
        },
        "task_raw_before": {"original.json": helper.identity(raw / "original.json")},
        "allowed_raw_writes": [],
    }
    previous_umask = os.umask(0o077)
    os.umask(previous_umask)
    try:
        yield helper, plan, root, raw, prefixmap, profile
    finally:
        os.umask(previous_umask)


@pytest.mark.parametrize("changed", ["prefixmap", "profile"])
def test_real_child_configuration_drift_cannot_receive_receipt(unit, changed):
    """A mutation outside Python code must prevent a completed provenance record (#1869)."""
    helper, plan, _, _, prefixmap, profile = unit
    target = prefixmap if changed == "prefixmap" else profile
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('changed configuration')",
        str(target),
    ]
    with pytest.raises(ValueError, match="Implementation or policy changed"):
        helper.run(plan)
    stage = Path(plan["stage"])
    assert (stage / "process.json").is_file()
    assert not (stage / "receipt.json").exists()


def test_real_child_raw_mutation_and_new_derivative_are_inventoried(unit):
    """A source's canonical raw side effects remain visible beyond its unit output tree (#1870)."""
    helper, plan, _, raw, _, _ = unit
    plan["allowed_raw_writes"] = ["original.json", "derived.json"]
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; raw=Path(sys.argv[1]); "
        "(raw/'original.json').write_text('changed raw'); (raw/'derived.json').write_text('new derivative')",
        str(raw),
    ]
    assert helper.run(plan) == 0
    receipt = json.loads((Path(plan["stage"]) / "receipt.json").read_text())
    assert receipt["task_raw_new_files"] == ["derived.json"]
    assert receipt["task_raw_changed_files"] == ["original.json"]
    for name in ("original.json", "derived.json"):
        assert receipt["task_raw_after"][name] == helper.identity(raw / name)
    assert receipt["task_raw_before"]["original.json"] != receipt["task_raw_after"]["original.json"]
    assert receipt["published_release_verified"] is False


def test_planned_shared_non_python_inputs_are_actually_guarded(unit, monkeypatch):
    """Removing the declaration-based configuration pins restores the original unsafe behavior (#1869)."""
    helper, _, root, raw, prefixmap, profile = unit
    fingerprint = root / "kg_microbe/utils/transform_fingerprint.py"
    fingerprint.parent.mkdir()
    names = [str(path.relative_to(root)) for path in (prefixmap, profile)]
    fingerprint.write_text(f"SHARED_DATA_INPUTS = {tuple(names)!r}\n")
    (root / "mappings").mkdir()
    (root / "kg_microbe/transform_utils/custom_curies.yaml").write_text("{}\n")
    for name in ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml"):
        (raw / name).write_text("version: fixture\n")
    for name in ("pyproject.toml", "poetry.lock"):
        (root / name).write_text("fixture\n")
    script = root / "launcher.py"
    script.write_bytes(HELPER.read_bytes())
    monkeypatch.setattr(helper, "__file__", str(script))
    monkeypatch.setattr(helper.subprocess, "check_output", lambda *args, **kwargs: "fixture-commit\n")
    retained = root / "retained/data/raw"
    retained.mkdir(parents=True)
    (retained / "ro.owl").write_text("immutable fixture\n")
    args = SimpleNamespace(unit="planned", input_root=root / "retained", raw_input=["ro.owl"], source="ro")
    plan = helper.prepare(args)
    assert all(plan["implementation_and_policy_inputs"][name] == helper.identity(root / name) for name in names)
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('configuration drift')",
        str(prefixmap),
    ]
    plan["cli_origin_required"] = False
    with pytest.raises(ValueError, match="Implementation or policy changed"):
        helper.run(plan)
    assert not (Path(plan["stage"]) / "receipt.json").exists()


def test_explicit_nested_derivative_and_deletion_are_accounted(unit):
    """Exact file declarations permit real nested output and intentional deletion, with both visible."""
    helper, plan, _, raw, _, _ = unit
    plan["allowed_raw_writes"] = ["nested/derivative.json", "original.json"]
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; raw=Path(sys.argv[1]); "
        "(raw/'nested').mkdir(); (raw/'nested/derivative.json').write_text('derived'); (raw/'original.json').unlink()",
        str(raw),
    ]
    assert helper.run(plan) == 0
    receipt = json.loads((Path(plan["stage"]) / "receipt.json").read_text())
    assert receipt["profile"] == "bactotraits-production-unit-v2"
    assert receipt["raw_side_effects"] == {
        "added": ["nested", "nested/derivative.json"],
        "changed": [],
        "deleted": ["original.json"],
        "unexpected": [],
    }
    assert receipt["task_raw_after"]["nested/derivative.json"] == helper.identity(raw / "nested/derivative.json")


def test_allowed_raw_file_cannot_be_replaced_with_symlink(unit):
    """A file declaration never grants a child permission to route writes outside the raw tree."""
    helper, plan, root, raw, _, _ = unit
    outside = root / "outside.json"
    outside.write_text("unrelated bytes")
    plan["allowed_raw_writes"] = ["original.json"]
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; path=Path(sys.argv[1]); path.unlink(); path.symlink_to(sys.argv[2])",
        str(raw / "original.json"),
        str(outside),
    ]
    with pytest.raises(ValueError, match="Undeclared or unsafe raw side effects"):
        helper.run(plan)
    assert outside.read_text() == "unrelated bytes"
    failure = json.loads((Path(plan["stage"]) / "failure.json").read_text())
    assert failure["raw_side_effects"]["unexpected"] == ["original.json"]
    assert failure["task_raw_after"]["original.json"]["kind"] == "symlink"


def test_existing_nested_raw_deletion_is_not_lost(unit):
    """The before/after inventory includes an already present nested file, not just new directories."""
    helper, plan, _, raw, _, _ = unit
    nested = raw / "existing/data.json"
    nested.parent.mkdir()
    nested.write_text("existing nested input")
    plan["task_raw_before"].update({"existing": {"kind": "directory"}, "existing/data.json": helper.identity(nested)})
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).unlink()",
        str(nested),
    ]
    with pytest.raises(ValueError, match="Undeclared or unsafe raw side effects"):
        helper.run(plan)
    failure = json.loads((Path(plan["stage"]) / "failure.json").read_text())
    assert failure["raw_side_effects"]["deleted"] == ["existing/data.json"]


@pytest.mark.parametrize("mutation", ["add", "change", "delete", "nested"])
def test_undeclared_raw_side_effect_is_refused_with_failure_evidence(unit, mutation):
    """Real child additions, overwrites, deletion and nested writes all require a prior declaration."""
    helper, plan, _, raw, _, _ = unit
    operations = {
        "add": "(raw/'unexpected.json').write_text('unexpected')",
        "change": "(raw/'original.json').write_text('unexpected')",
        "delete": "(raw/'original.json').unlink()",
        "nested": "(raw/'nested').mkdir(); (raw/'nested/unexpected.json').write_text('unexpected')",
    }
    plan["command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; raw=Path(sys.argv[1]); " + operations[mutation],
        str(raw),
    ]
    with pytest.raises(ValueError, match="Undeclared or unsafe raw side effects"):
        helper.run(plan)
    stage = Path(plan["stage"])
    assert not (stage / "receipt.json").exists()
    failure = json.loads((stage / "failure.json").read_text())
    assert failure["status"] == "FAILED"
    assert failure["raw_side_effects"]["unexpected"]
    assert failure["task_raw_after"] != failure["task_raw_before"]
    assert (stage / "process.json").is_file()


def _retained_input(helper, plan, root, raw):
    source = root / "retained.owl"
    source.write_bytes(b"complete retained ontology\n" * 100)
    target = raw / "ontology.owl"
    plan["originals"] = [{"source": str(source), "target": str(target), **helper.identity(source)}]
    plan["command"] = [sys.executable, "-c", "pass"]
    return source, target


def test_partial_copy_never_publishes_canonical_input(unit, monkeypatch):
    """A failed copy retains its private prefix without poisoning the canonical raw target (#1875)."""
    helper, plan, root, raw, _, _ = unit
    source, target = _retained_input(helper, plan, root, raw)

    def interrupted(reader, writer, _length):
        writer.write(reader.read(7))
        raise OSError("injected copy failure")

    monkeypatch.setattr(helper.shutil, "copyfileobj", interrupted)
    with pytest.raises(OSError, match="injected copy failure"):
        helper.run(plan)
    assert not target.exists()
    assert helper.identity(source) == {key: plan["originals"][0][key] for key in ("bytes", "sha256")}
    stage = Path(plan["stage"])
    failure = json.loads((stage / "failure.json").read_text())
    partial = stage / "input-staging/ontology.owl"
    assert partial.read_bytes() == source.read_bytes()[:7]
    assert failure["artifacts"]["input-staging/ontology.owl"] == helper.identity(partial)
    assert not (stage / "receipt.json").exists()


@pytest.mark.parametrize("competitor", ["file", "symlink"])
def test_competing_input_is_never_overwritten(unit, monkeypatch, competitor):
    """Atomic no-clobber publication also refuses a target created after planning (#1875)."""
    helper, plan, root, raw, _, _ = unit
    source, target = _retained_input(helper, plan, root, raw)
    unrelated = root / "unrelated.owl"
    unrelated.write_bytes(b"competing bytes")
    copy = shutil.copyfileobj

    def racing_copy(reader, writer, length):
        copy(reader, writer, length)
        if competitor == "symlink":
            target.symlink_to(unrelated)
        else:
            target.write_bytes(unrelated.read_bytes())

    monkeypatch.setattr(helper.shutil, "copyfileobj", racing_copy)
    with pytest.raises((FileExistsError, ValueError)):
        helper.run(plan)
    assert unrelated.read_bytes() == b"competing bytes"
    assert target.read_bytes() == b"competing bytes"
    assert target.is_symlink() == (competitor == "symlink")
    stage = Path(plan["stage"])
    assert (stage / "failure.json").is_file()
    assert (stage / "input-staging/ontology.owl").read_bytes() == source.read_bytes()
    assert not (stage / "receipt.json").exists()


def test_actual_cli_ignores_foreign_python_startup_routes(unit, monkeypatch):
    """Two real package roots cannot redirect the planned ordinary CLI via ambient Python variables (#1874)."""
    helper, _, root, raw, prefixmap, profile = unit
    fingerprint = root / "kg_microbe/utils/transform_fingerprint.py"
    fingerprint.parent.mkdir()
    fingerprint.write_text(f"SHARED_DATA_INPUTS = {tuple(str(p.relative_to(root)) for p in (prefixmap, profile))!r}\n")
    (root / "mappings").mkdir()
    (root / "kg_microbe/transform_utils/custom_curies.yaml").write_text("{}\n")
    for name in ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml"):
        (raw / name).write_text("version: fixture\n")
    for name in ("pyproject.toml", "poetry.lock"):
        (root / name).write_text("fixture\n")
    script = root / "scripts/adhoc" / HELPER.name
    script.parent.mkdir(parents=True)
    script.write_bytes(HELPER.read_bytes())
    monkeypatch.setattr(helper, "__file__", str(script))
    monkeypatch.setattr(helper.subprocess, "check_output", lambda *args, **kwargs: "fixture-commit\n")
    retained = root / "retained/data/raw"
    retained.mkdir(parents=True)
    (retained / "ro.owl").write_text("immutable fixture\n")
    foreign = root / "foreign"
    for package_root, label in ((root, "intended"), (foreign, "foreign")):
        package = package_root / "kg_microbe"
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("")
        (package / "run.py").write_text(
            "import json, sys\nfrom pathlib import Path\n"
            "assert sys.argv[1] == 'transform'\n"
            "output = Path(sys.argv[sys.argv.index('-o') + 1])\n"
            "output.mkdir()\n"
            f"(output/'selected.json').write_text(json.dumps({{'package': {label!r}, "
            "'isolated': sys.flags.isolated, 'argv': sys.argv[1:]}))\n"
        )
    monkeypatch.setenv("PYTHONPATH", str(foreign))
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    args = SimpleNamespace(unit="routing", input_root=root / "retained", raw_input=["ro.owl"], source="ro")
    plan = helper.prepare(args)
    assert helper.run(plan) == 0
    stage = Path(plan["stage"])
    selected = json.loads((stage / "transformed/selected.json").read_text())
    assert selected["package"] == "intended"
    assert selected["isolated"] == 1
    origins = json.loads((stage / "cli-origin.json").read_text())
    assert origins["package_origin"] == str(root / "kg_microbe/__init__.py")
    assert origins["cli_origin"] == str(root / "kg_microbe/run.py")
    assert origins["root"] == str(root)
    assert (raw / "ro.owl").read_bytes() == (retained / "ro.owl").read_bytes()
    assert not (stage / "input-staging/ro.owl").exists()
    assert json.loads((stage / "receipt.json").read_text())["raw_side_effects"]["added"] == []
