"""Reject drift of shared configuration and retain raw side effects from a real child process."""

import importlib.util
import json
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
    }
    return helper, plan, root, raw, prefixmap, profile


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
    with pytest.raises(ValueError, match="Implementation or policy changed"):
        helper.run(plan)
    assert not (Path(plan["stage"]) / "receipt.json").exists()
