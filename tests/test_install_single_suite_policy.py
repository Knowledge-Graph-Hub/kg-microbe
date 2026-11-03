"""Keep policy installation scoped and collision-safe in temporary Git repositories."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/adhoc/install_single_suite_policy.py"
HISTORICAL_POLICY_PATHS = (
    ".claude/skills/add-transform/SKILL.md",
    ".claude/skills/branch-triage-ship/SKILL.md",
    ".claude/skills/kgm-freshness-check/SKILL.md",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "docs/INGREDIENT_ACCEPTANCE.md",
    "docs/NEXT_TASKS.md",
    "docs/TESTING.md",
    "scripts/adhoc/install_single_suite_policy.py",
    "scripts/adhoc/legacy_pr_gates.py",
    "scripts/run_pr_gates.py",
    "tests/test_pr_gates.py",
    "tox.ini",
)
UNRELATED_PATHS = ("pyproject.toml", "tests/test_unrelated.py", "tests/test_foodon_native_categories.py")


def git(root: Path, *arguments: str) -> str:
    """Run local Git operations only in a test-owned repository."""
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.check_output(  # noqa: S603 - temporary repository and controlled arguments
        [executable, *arguments], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def write(root: Path, name: str, data: bytes) -> None:
    """Write a bounded fixture file under a temporary root."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def initialize(root: Path) -> None:
    """Create a temporary feature branch without signing or user hooks."""
    root.mkdir(exist_ok=True)
    git(root, "init", "-q")
    git(root, "checkout", "-qb", "feature/policy-fixture")
    git(root, "config", "user.name", "Policy installer test")
    git(root, "config", "user.email", "policy-installer@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", str(root.parent / "no-hooks"))
    git(root, "config", "core.fileMode", "true")


def commit(root: Path) -> str:
    """Commit only the tiny test repository's fixture state."""
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Fixture state")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the actual installer while keeping its source root replaceable in tests."""
    name = "kgm_policy_installer_under_test"
    spec = importlib.util.spec_from_file_location(name, INSTALLER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, str]:
    """Prepare independent baseline source and target repositories without worktrees."""
    source, target = tmp_path / "source", tmp_path / "target"
    initialize(source)
    write(source, "scripts/adhoc/install_single_suite_policy.py", INSTALLER.read_bytes())
    write(source, "scripts/adhoc/legacy_pr_gates.py", INSTALLER.with_name("legacy_pr_gates.py").read_bytes())
    write(source, ".gitignore", b"data/\n")
    for name in ("README.md", "tox.ini", *UNRELATED_PATHS):
        write(source, name, b"baseline\n")
    base = commit(source)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git"))
    initialize(target)
    commit(target)
    return source, target, base


def invoke(source: Path, target: Path, base: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Execute the real copied installer against temporary repositories only."""
    return subprocess.run(  # noqa: S603 - fixed interpreter and temporary fixture paths
        [
            sys.executable,
            str(source / "scripts/adhoc/install_single_suite_policy.py"),
            "--base-ref",
            base,
            "--target",
            str(target),
            *arguments,
        ],
        cwd=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def snapshot(root: Path) -> tuple[str, str, dict]:
    """Capture target bytes, links, modes and refs, including ignored evidence files."""
    files = {}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            files[name] = ("symlink", os.readlink(path))
        elif path.is_file():
            files[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        else:
            files[name] = ("directory",)
    return git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain=v1"), files


def test_historical_payload_keeps_exact_fifteen_paths(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit manifest retains historical bytes, modes and baseline collisions."""
    source = tmp_path / "historical"
    initialize(source)
    for name in HISTORICAL_POLICY_PATHS:
        write(source, name, b"baseline\n")
    base = commit(source)
    for name in HISTORICAL_POLICY_PATHS:
        write(source, name, b"policy\n")
    (source / "scripts/run_pr_gates.py").chmod(0o755)
    head = commit(source)
    monkeypatch.setattr(installer, "SOURCE", source)
    selected = installer.managed_files(base, head)
    assert {item.name for item in selected} == set(HISTORICAL_POLICY_PATHS)
    assert all(item.data == b"policy\n" and item.baseline == b"baseline\n" for item in selected)
    assert {item.name: item.mode for item in selected}["scripts/run_pr_gates.py"] == 0o755
    assert "tests/test_install_single_suite_policy.py" not in {item.name for item in selected}


def test_mixed_range_plans_and_installs_only_policy_files(repositories: tuple[Path, Path, str]) -> None:
    """Unrelated committed fixes never become installable even on matching baseline targets."""
    source, target, base = repositories
    for name in ("README.md", "tox.ini", *UNRELATED_PATHS):
        write(source, name, b"changed\n")
    (source / "tox.ini").chmod(0o755)
    (source / UNRELATED_PATHS[0]).chmod(0o755)
    head = commit(source)
    before = snapshot(target)
    plan_result = invoke(source, target, base)
    assert plan_result.returncode == 0, plan_result.stderr
    plan = json.loads(plan_result.stdout)
    assert plan["policy_scope"] == "single-suite-policy-v1"
    assert set(plan["ignored_source_paths"]) == set(UNRELATED_PATHS)
    assert {item["path"] for item in plan["targets"][0]["files"]} == {"README.md", "tox.ini"}
    assert snapshot(target) == before
    applied = invoke(source, target, base, "--apply")
    assert applied.returncode == 0, applied.stderr
    receipt_path = Path(
        next(line.removeprefix("INSTALLED ") for line in applied.stdout.splitlines() if line.startswith("INSTALLED "))
    )
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "installed"
    assert receipt["source_head"] == head
    assert receipt["source_baseline"] == base
    assert receipt["policy_scope"] == plan["policy_scope"]
    assert receipt["ignored_source_paths"] == plan["ignored_source_paths"]
    assert set(git(target, "diff", "--name-only", before[0], "HEAD").splitlines()) == {"README.md", "tox.ini"}
    for record in receipt["files"]:
        assert Path(record["backup"]).read_bytes() == b"baseline\n"
        assert (target / record["path"]).read_bytes() == b"changed\n"
        assert record["before_sha256"] != record["after_sha256"]
    assert stat.S_IMODE((target / "tox.ini").stat().st_mode) == 0o755
    for name in UNRELATED_PATHS:
        assert (target / name).read_bytes() == b"baseline\n"
        assert stat.S_IMODE((target / name).stat().st_mode) == before[2][name][1]
    installed_head = git(target, "rev-parse", "HEAD")
    repeated = invoke(source, target, base, "--apply")
    assert repeated.returncode == 0, repeated.stderr
    assert git(target, "rev-parse", "HEAD") == installed_head


def test_unrelated_only_range_fails_without_target_mutation(repositories: tuple[Path, Path, str]) -> None:
    """A valid ancestor range cannot install arbitrary files in lieu of policy changes."""
    source, target, base = repositories
    write(source, "pyproject.toml", b"unrelated committed change\n")
    commit(source)
    before = snapshot(target)
    result = invoke(source, target, base, "--apply")
    assert result.returncode == 1
    assert "no changed policy manifest files" in result.stderr
    assert snapshot(target) == before


@pytest.mark.parametrize("kind", ["delete", "rename", "symlink", "directory"])
def test_managed_deletion_or_nonregular_source_fails_before_writes(
    repositories: tuple[Path, Path, str], kind: str
) -> None:
    """Deletion and rename source paths cannot disappear through an AM-only filter."""
    source, target, base = repositories
    managed = source / "README.md"
    if kind == "rename":
        managed.rename(source / "unmanaged-readme.md")
    else:
        managed.unlink()
        if kind == "symlink":
            managed.symlink_to("tox.ini")
        elif kind == "directory":
            write(source, "README.md/child", b"unexpected tree\n")
    write(source, "tox.ini", b"otherwise installable\n")
    commit(source)
    before = snapshot(target)
    result = invoke(source, target, base, "--apply")
    assert result.returncode == 1
    assert "README.md" in result.stderr
    assert snapshot(target) == before


def test_unrelated_deletion_is_reported_but_not_installed(repositories: tuple[Path, Path, str]) -> None:
    """Excluding an unrelated deletion preserves the corresponding target file."""
    source, target, base = repositories
    (source / "pyproject.toml").unlink()
    write(source, "README.md", b"policy\n")
    commit(source)
    result = invoke(source, target, base, "--apply")
    assert result.returncode == 0, result.stderr
    plan = json.JSONDecoder().raw_decode(result.stdout)[0]
    assert plan["ignored_source_paths"] == ["pyproject.toml"]
    assert (target / "pyproject.toml").read_bytes() == b"baseline\n"


@pytest.mark.parametrize("kind", ["dirty", "committed", "untracked"])
def test_manifest_does_not_relax_target_collision_guards(repositories: tuple[Path, Path, str], kind: str) -> None:
    """Local work, committed divergence and new-file collisions all stop before backups."""
    source, target, base = repositories
    name = "tests/test_pr_gates.py" if kind == "untracked" else "README.md"
    write(source, name, b"policy\n")
    commit(source)
    write(target, name, b"keep target work\n")
    if kind == "committed":
        commit(target)
    before = snapshot(target)
    result = invoke(source, target, base, "--apply")
    assert result.returncode == 1
    assert ("Tracked edits" if kind == "dirty" else "differs from both baseline") in result.stderr
    assert snapshot(target) == before


@pytest.mark.parametrize("kind", ["file", "parent"])
def test_target_symlink_paths_remain_rejected(repositories: tuple[Path, Path, str], tmp_path: Path, kind: str) -> None:
    """Manifest membership never authorizes following a destination link."""
    source, target, base = repositories
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind == "file":
        name = "README.md"
        write(outside, "README.md", b"baseline\n")
        (target / name).unlink()
        (target / name).symlink_to(outside / name)
    else:
        name = "docs/TESTING.md"
        (target / "docs").symlink_to(outside, target_is_directory=True)
    commit(target)
    write(source, name, b"policy\n")
    commit(source)
    before = snapshot(target)
    outside_before = {path.name: path.read_bytes() for path in outside.iterdir()}
    result = invoke(source, target, base, "--apply")
    assert result.returncode == 1
    assert "Refusing symlink traversal" in result.stderr
    assert snapshot(target) == before
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == outside_before


def test_legacy_recognition_keeps_historical_commands_and_rejects_unknown(
    tmp_path: Path, installer: ModuleType
) -> None:
    """Scope repair preserves old-runner recognition without executing those scripts."""
    wrapper = b"print('wrapper')\n"
    path = tmp_path / "kgm-run-pr-gates.py"
    path.write_text("commands = [['poetry', 'run', 'pytest'], ['poetry', 'run', 'tox']]\n")
    before = path.read_bytes()
    plan = installer.legacy_plan(tmp_path, wrapper)
    assert len(plan) == 1 and plan[0]["path"] == str(path)
    assert path.read_bytes() == before
    path.write_text("commands = [['unrecognized']]\n")
    with pytest.raises(RuntimeError, match="Unrecognized legacy runner"):
        installer.legacy_plan(tmp_path, wrapper)
    assert path.read_text() == "commands = [['unrecognized']]\n"
