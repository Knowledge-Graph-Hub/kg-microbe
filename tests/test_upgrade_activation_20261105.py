"""Offline activation controls: fixed selections, exact preservation and honest partial failures."""

import copy
import json
import os
from pathlib import Path

import pytest

from scripts.adhoc import kgm_activate_upgrades_20261105 as activation

FIXTURE = Path(__file__).parent / "resources/upgrade_activation_20261105.json"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """Construct only test-owned files from immutable text fixtures; no actual raw input is accessed."""
    root = tmp_path / "owned"
    raw, upgrades = root / "data/raw", root / "data/rebuild-evidence/20261105/upgrades"
    raw.mkdir(parents=True)
    upgrades.mkdir(parents=True)
    for key, value in {
        "ROOT": root,
        "MODULE_ROOT": root,
        "RAW": raw,
        "UPGRADES": upgrades,
        "ACTIVATION": upgrades / "activation",
    }.items():
        monkeypatch.setattr(activation, key, value)
    fixture = json.loads(FIXTURE.read_text())
    entries, guards = [], {}
    old_inodes = {}
    for name, payload in fixture["files"].items():
        source = (
            upgrades / "candidates" / activation.HTTP[name][1] / name
            if name in activation.HTTP
            else upgrades / "robot-conversions" / name
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(payload["candidate"])
        (raw / name).write_text(payload["old"])
        old_inodes[name] = (raw / name).stat().st_ino
        expected = activation.checked(source)
        guards[str(source)] = expected
        entries.append(
            {"name": name, "source": str(source), "candidate": expected, "before": activation.checked(raw / name)}
        )
    (raw / "rhea").mkdir()
    for name, value in fixture["old_rhea"].items():
        (raw / "rhea" / name).write_text(value)
    pair = upgrades / "candidates/rhea143"
    pair.mkdir()
    for name, value in fixture["new_rhea"].items():
        (pair / name).write_text(value)
        guards[str(pair / name)] = activation.checked(pair / name)
    for relative, value in fixture["unchanged"].items():
        path = raw / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    plan = {
        "ready": True,
        "worktree": str(root),
        "raw": str(raw),
        "evidence": str(activation.ACTIVATION),
        "replacements": entries,
        "guards": guards,
        "rhea_candidates": {name: str(pair / name) for name in fixture["new_rhea"]},
        "rhea_before": activation.tree_identity(raw / "rhea"),
        "rhea_policy": {"files": {name: activation.checked(pair / name) for name in fixture["new_rhea"]}},
    }

    def staged(generation, evidence):
        """Model only the already separately tested production Rhea stage/audit boundary."""
        assert not (raw / "rhea").exists()
        assert activation.tree_identity(evidence / "preserved/rhea") == plan["rhea_before"]
        (raw / "rhea").mkdir()
        for name, expected in plan["rhea_policy"]["files"].items():
            activation.copy_verified(generation / "rhea-inputs" / name, raw / "rhea" / name, expected)
        return {
            "legacy_rows": list(range(6)),
            "directional_witnesses": list(range(7)),
            "production_transform_run": False,
        }

    monkeypatch.setattr(activation, "activate_rhea", staged)
    return plan, fixture, old_inodes


def assert_originals(prepared):
    """Require selected old payloads, complete old Rhea and every excluded path to remain unchanged."""
    _, fixture, _ = prepared
    for name, row in fixture["files"].items():
        assert (activation.RAW / name).read_text() == row["old"]
    for name, value in fixture["old_rhea"].items():
        assert (activation.RAW / "rhea" / name).read_text() == value
    for relative, value in fixture["unchanged"].items():
        assert (activation.RAW / relative).read_text() == value


def test_default_plan_never_creates_activation_or_changes_raw(prepared, monkeypatch, capsys):
    """Readiness alone does not authorize mutation."""
    monkeypatch.setattr(activation, "build_plan", lambda: prepared[0])
    assert activation.main([]) == 0
    assert json.loads(capsys.readouterr().out)["ready"]
    assert not activation.ACTIVATION.exists()
    assert_originals(prepared)


def test_success_preserves_exact_old_inodes_and_whole_rhea_directory(prepared):
    """All16 original files move intact, unrelated raw remains untouched, and completion follows both stages."""
    plan, fixture, inodes = prepared
    result = activation.execute(plan)
    assert result["activation_complete"] and not result["production_admission"]
    preserved = activation.ACTIVATION / "preserved"
    for name, row in fixture["files"].items():
        assert (preserved / name).read_text() == row["old"]
        assert (preserved / name).stat().st_ino == inodes[name]
        assert (activation.RAW / name).read_text() == row["candidate"]
        assert (activation.RAW / name).stat().st_nlink == 1
    assert activation.tree_identity(preserved / "rhea") == plan["rhea_before"]
    for relative, value in fixture["unchanged"].items():
        assert (activation.RAW / relative).read_text() == value
    assert json.loads((activation.ACTIVATION / "after.json").read_text())["activation_complete"]


def test_evidence_collision_never_reuses_or_overwrites_prior_attempt(prepared):
    """A retained attempt requires review; it cannot be silently reused."""
    activation.ACTIVATION.mkdir()
    marker = activation.ACTIVATION / "foreign"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="collision"):
        activation.execute(prepared[0])
    assert marker.read_text() == "keep"
    assert_originals(prepared)


@pytest.mark.parametrize("change", ["outside_name", "wrong_source", "extra_file", "rhea_source"])
def test_execute_revalidates_the_exact_finite_write_selection(prepared, change):
    """Even a direct Python caller cannot supply another raw filename or source root."""
    plan = copy.deepcopy(prepared[0])
    if change == "outside_name":
        plan["replacements"][0]["name"] = "../outside"
    elif change == "wrong_source":
        plan["replacements"][0]["source"] = str(activation.ROOT.parent / "foreign")
    elif change == "extra_file":
        plan["replacements"].append(copy.deepcopy(plan["replacements"][0]))
    else:
        plan["rhea_candidates"]["rhea.rdf.gz"] = str(activation.RAW / "rhea/rhea.rdf.gz")
    with pytest.raises(ValueError):
        activation.execute(plan)
    assert not activation.ACTIVATION.exists()
    assert_originals(prepared)


@pytest.mark.parametrize("when", ["copy", "guard", "raw"])
def test_failures_before_first_move_leave_all_raw_unchanged(prepared, monkeypatch, when):
    """Preparing or rechecking a generation cannot partially activate it."""
    plan = prepared[0]
    if when == "copy":

        def fail(*args):
            raise OSError("injected copy failure")

        monkeypatch.setattr(activation, "copy_verified", fail)
    elif when == "guard":
        guard = activation.UPGRADES / "guard.txt"
        guard.write_text("before")
        plan["guards"][str(guard)] = activation.checked(guard)
        guard.write_text("changed")
    else:
        name = plan["replacements"][0]["name"]
        (activation.RAW / name).write_text("external raw change")
    with pytest.raises((ValueError, OSError)):
        activation.execute(plan)
    assert not (activation.ACTIVATION / "after.json").exists()
    assert not json.loads((activation.ACTIVATION / "failure.json").read_text())["activation_complete"]
    assert list((activation.ACTIVATION / "preserved").iterdir()) == []
    if when != "raw":
        assert_originals(prepared)
    else:
        assert (activation.RAW / name).read_text() == "external raw change"


def test_partial_publication_failure_retains_originals_and_never_claims_completion(prepared, monkeypatch):
    """A failure after preservation leaves every old payload recoverable and an explicit partial journal."""
    real_link, calls = os.link, []

    def fail_second(source, destination, **kwargs):
        calls.append(destination)
        if len(calls) == 2:
            raise OSError("injected publication failure")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(activation.os, "link", fail_second)
    with pytest.raises(OSError, match="publication"):
        activation.execute(prepared[0])
    for name, row in prepared[1]["files"].items():
        preserved = activation.ACTIVATION / "preserved" / name
        current = preserved if preserved.exists() else activation.RAW / name
        assert current.read_text() == row["old"]
    failure = json.loads((activation.ACTIVATION / "failure.json").read_text())
    assert not failure["activation_complete"] and failure["events"]
    assert not (activation.ACTIVATION / "after.json").exists()


def test_rhea_gate_failure_keeps_complete142_directory_and_no_success_receipt(prepared, monkeypatch):
    """Post-staging scientific failure cannot approve a partially activated input cohort."""

    def fail(*args):
        raise ValueError("Rhea native audit failed")

    monkeypatch.setattr(activation, "activate_rhea", fail)
    with pytest.raises(ValueError, match="native audit"):
        activation.execute(prepared[0])
    assert activation.tree_identity(activation.ACTIVATION / "preserved/rhea") == prepared[0]["rhea_before"]
    assert not (activation.ACTIVATION / "after.json").exists()
    assert not json.loads((activation.ACTIVATION / "failure.json").read_text())["activation_complete"]


@pytest.mark.parametrize("link", ["symbolic", "hard"])
def test_linked_candidates_are_refused_without_touching_the_original(prepared, link):
    """Copies may never read through a link into an unowned or shared file."""
    source = Path(prepared[0]["replacements"][0]["source"])
    original = activation.ROOT / "original"
    original.write_text("original must survive")
    source.unlink()
    source.symlink_to(original) if link == "symbolic" else os.link(original, source)
    with pytest.raises(ValueError, match="Symlink|hard-linked"):
        activation.checked(source)
    assert original.read_text() == "original must survive"


def test_directory_scan_error_cannot_certify_complete_rhea_preservation(prepared, monkeypatch):
    """Ignored/hidden directory contents count, and an unreadable traversal is a hard failure."""

    def denied(*args, **kwargs):
        kwargs["onerror"](PermissionError("unreadable Rhea directory"))

    monkeypatch.setattr(activation.os, "walk", denied)
    with pytest.raises(PermissionError):
        activation.tree_identity(activation.RAW / "rhea")


def test_explicit_sources_match_the_actual_reviewed_conversion_receipts():
    """CHEBI, EC and NCBITaxon bind compressed inputs, independently of existing uncompressed neighbors."""
    expected = json.loads(FIXTURE.read_text())["conversion_inputs"]
    assert activation.INPUTS == expected
    for name in ("chebi", "ec", "ncbitaxon"):
        source = activation.RAW / expected[name]
        receipt = {"source": str(source)}
        activation.record_path(receipt, activation.RAW / activation.INPUTS[name])
        with pytest.raises(ValueError, match="Receipt path mismatch"):
            activation.record_path(receipt, activation.RAW / (name + ".owl"))


@pytest.mark.parametrize("changed_policy", ["ncit_eight_categories.json", "mesh_finite_category_dispositions.json"])
def test_biolink_readiness_requires_actual_finite_policy_guards(monkeypatch, changed_policy):
    """An unrelated policy mutation cannot pass merely because model version and SHA remain reviewed."""
    from kg_microbe.utils import mesh_finite_categories, ncit_eight_categories

    root = Path(activation.__file__).resolve().parents[2]
    model_path = Path(__file__).parent / "resources/biolink_4_4_6/biolink-model.yaml"
    policies = {
        module.POLICY_FILE.name: json.loads(module.POLICY_FILE.read_text())
        for module in (ncit_eight_categories, mesh_finite_categories)
    }
    changed = policies[changed_policy]
    assert changed["model_version"] == "4.4.6"
    assert changed["model_sha256"] == activation.identity(model_path)["sha256"]
    changed["unreviewed_policy_change"] = True
    monkeypatch.setattr(activation, "ROOT", root)
    monkeypatch.setattr(activation, "validate_layout", lambda: None)

    def selected_http(name, guards, acquisition):
        """Supply the immutable reviewed model while isolating the finite-policy readiness gate."""
        guards[str(model_path)] = activation.identity(model_path)
        return model_path

    def selected_read(path, guards):
        """Expose actual curated policy objects; reaching any later gate means the mutation escaped."""
        if path == activation.UPGRADES / "candidates/receipt.json":
            return {"status": "acquired_not_activated"}
        if path.name in policies:
            return policies[path.name]
        raise AssertionError("Unreviewed finite policy escaped the readiness gate")

    monkeypatch.setattr(activation, "check_http", selected_http)
    monkeypatch.setattr(activation, "read", selected_read)
    with pytest.raises(ValueError, match="Unreviewed finite"):
        activation.build_plan()
