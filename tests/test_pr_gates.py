"""Exercise the PR gate CLI without running the scientific test suite."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_pr_gates.py"

# Purpose: a test-controlled Poetry executable for the single-suite policy (2026-10-28).
# Input: CLI arguments and KGM_GATE_TEST_* variables. Output: command ledger and optional faults.
FAKE_POETRY = """import json, os, pathlib, subprocess, sys
arguments = sys.argv[1:]
ledger = pathlib.Path(os.environ['KGM_GATE_TEST_LEDGER'])
with ledger.open('a') as handle:
    handle.write(json.dumps(arguments) + '\\n')
mode = os.environ.get('KGM_GATE_TEST_MODE', '')
if mode == 'fail-lock' and arguments == ['check', '--lock']:
    raise SystemExit(7)
if mode == 'fail-qc' and arguments[:2] == ['run', 'tox']:
    raise SystemExit(8)
if mode == 'fail-tests' and arguments[:4] == ['run', 'tox', '-e', 'py']:
    raise SystemExit(9)
if mode == 'mutate' and arguments == ['check', '--lock']:
    pathlib.Path('candidate.txt').write_text('changed by gate\\n')
if mode == 'move-head' and arguments == ['check', '--lock']:
    subprocess.run([os.environ['KGM_GATE_TEST_GIT'], '-c', 'commit.gpgsign=false',
                    'commit', '--allow-empty', '-m', 'Moved during gate'], check=True)
names = ['TOXENV', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'TOX_NO_TEST', 'TOXNO_TEST',
         'TOX_PACKAGE_ONLY', 'TOXPACKAGE_ONLY', 'TOX_SKIP_ENV', 'TOX_OVERRIDE', 'TOX_USER_CONFIG_FILE']
print(json.dumps({name: os.environ.get(name) for name in names}))
"""


def git(root: Path, *arguments: str) -> str:
    """Run Git against a temporary test-owned repository."""
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.check_output(  # noqa: S603 - test-controlled repository and arguments
        [executable, *arguments], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a committed candidate and a fake Poetry executable outside its tree."""
    root = tmp_path / "candidate"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Gate test")
    git(root, "config", "user.email", "gate-test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (root / "candidate.txt").write_text("committed candidate\n", encoding="utf-8")
    git(root, "add", "candidate.txt")
    git(root, "commit", "-qm", "Initial candidate")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    poetry = binaries / "poetry"
    poetry.write_text(f"#!{sys.executable}\n{FAKE_POETRY}", encoding="utf-8")
    poetry.chmod(0o700)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("KGM_GATE_TEST_LEDGER", str(tmp_path / "commands.jsonl"))
    monkeypatch.setenv("KGM_GATE_TEST_GIT", shutil.which("git") or "")
    return root


def invoke(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Call the real gate CLI from a temporary candidate checkout."""
    return subprocess.run(  # noqa: S603 - fixed Python script and test-controlled arguments
        [sys.executable, str(RUNNER), "test-run", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def recorded_commands(root: Path) -> list[list[str]]:
    """Read the fake Poetry command ledger."""
    ledger = root.parent / "commands.jsonl"
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]


def test_final_gate_runs_full_suite_once_after_cheap_checks(candidate: Path) -> None:
    """A successful handoff tests once after cheap QC and records the candidate."""
    (candidate / "unrelated-data.txt").write_text("keep me\n", encoding="utf-8")
    result = invoke(candidate)
    assert result.returncode == 0, result.stderr
    assert recorded_commands(candidate) == [
        ["check", "--lock"],
        ["run", "python", "scripts/generate_merge_configs.py", "--check"],
        ["run", "tox", "-e", "coverage-clean,format-check,lint,codespell,docstr-coverage"],
        ["run", "tox", "-e", "py", "--", "tests", "--durations=50"],
    ]
    report = candidate / "data/validation/pr-gates/kgm-test-run-gates.json"
    entries = json.loads(report.read_text(encoding="utf-8"))
    assert len(entries) == 4
    assert all(entry["commit"] == git(candidate, "rev-parse", "HEAD") for entry in entries)
    assert all(entry["exit_code"] == 0 and Path(entry["log"]).is_file() for entry in entries)
    assert "GATES_COMPLETE" in result.stdout


@pytest.mark.parametrize("mode,exit_code,command_count", [("fail-lock", 7, 1), ("fail-qc", 8, 3), ("fail-tests", 9, 4)])
def test_failure_stops_and_cannot_be_reported_complete(
    candidate: Path, monkeypatch: pytest.MonkeyPatch, mode: str, exit_code: int, command_count: int
) -> None:
    """Both cheap failures and the final test failure propagate to callers."""
    monkeypatch.setenv("KGM_GATE_TEST_MODE", mode)
    result = invoke(candidate)
    assert result.returncode == exit_code
    assert len(recorded_commands(candidate)) == command_count
    assert "GATES_COMPLETE" not in result.stdout
    entries = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text(encoding="utf-8"))
    assert entries[-1]["exit_code"] == exit_code


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_candidate_is_rejected_before_gates(candidate: Path, staged: bool) -> None:
    """Staged changes are as disqualifying as unstaged edits for final evidence."""
    (candidate / "candidate.txt").write_text("not committed\n", encoding="utf-8")
    if staged:
        git(candidate, "add", "candidate.txt")
    result = invoke(candidate)
    assert result.returncode != 0
    assert "review and commit" in result.stderr
    assert not (candidate.parent / "commands.jsonl").exists()
    assert not (candidate / "data").exists()


@pytest.mark.parametrize("mode", ["mutate", "move-head"])
def test_candidate_changes_abort_before_expensive_gate(
    candidate: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """A successful process cannot certify a candidate that changed under the runner."""
    monkeypatch.setenv("KGM_GATE_TEST_MODE", mode)
    result = invoke(candidate)
    assert result.returncode != 0
    assert recorded_commands(candidate) == [["check", "--lock"]]
    assert "GATES_COMPLETE" not in result.stdout
    entries = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text(encoding="utf-8"))
    assert entries[0]["exit_code"] == 0
    assert entries[0]["candidate_error"]


def test_dry_run_writes_nothing_and_runs_no_gates(candidate: Path) -> None:
    """Planning is safe even while the developer is editing the candidate."""
    (candidate / "candidate.txt").write_text("editing\n", encoding="utf-8")
    result = invoke(candidate, "--dry-run")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["commands"][-1] == ["poetry", "run", "tox", "-e", "py", "--", "tests", "--durations=50"]
    assert not (candidate.parent / "commands.jsonl").exists()
    assert not (candidate / "data").exists()


def test_reusing_label_preserves_previous_evidence(candidate: Path, tmp_path: Path) -> None:
    """An explicit output path supports old callers without overwriting their evidence."""
    output_dir = tmp_path / "evidence"
    assert invoke(candidate, "--output-dir", str(output_dir)).returncode == 0
    report = output_dir / "kgm-test-run-gates.json"
    original = report.read_bytes()
    result = invoke(candidate, "--output-dir", str(output_dir))
    assert result.returncode != 0
    assert "new label" in result.stderr
    assert report.read_bytes() == original
    assert len(recorded_commands(candidate)) == 4


def test_local_subset_selectors_cannot_shorten_final_validation(
    candidate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final checks clear selection overrides while preserving configured test plugins."""
    monkeypatch.setenv("TOXENV", "lint")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k only_one_test")
    monkeypatch.setenv("PYTEST_PLUGINS", "example.keep")
    for name in ("TOX_NO_TEST", "TOXNO_TEST", "TOX_PACKAGE_ONLY", "TOXPACKAGE_ONLY"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("TOX_SKIP_ENV", "lint|format-check")
    monkeypatch.setenv("TOX_OVERRIDE", "testenv.py.commands=python --version")
    monkeypatch.setenv("TOX_USER_CONFIG_FILE", str(candidate.parent / "user-tox.ini"))
    (candidate.parent / "user-tox.ini").write_text("[tox]\nno_test=true\n", encoding="utf-8")
    result = invoke(candidate)
    assert result.returncode == 0, result.stderr
    final_log = candidate / "data/validation/pr-gates/kgm-test-run-4.log"
    assert json.loads(final_log.read_text(encoding="utf-8")) == {
        "TOXENV": None,
        "PYTEST_ADDOPTS": None,
        "PYTEST_PLUGINS": "example.keep",
        "TOX_NO_TEST": None,
        "TOXNO_TEST": None,
        "TOX_PACKAGE_ONLY": None,
        "TOXPACKAGE_ONLY": None,
        "TOX_SKIP_ENV": None,
        "TOX_OVERRIDE": None,
        "TOX_USER_CONFIG_FILE": os.devnull,
    }
