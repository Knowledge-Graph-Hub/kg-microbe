"""Exercise the PR gate CLI without running the scientific test suite."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import stat
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
if mode == 'fail-tests' and arguments[:5] == ['run', '--', 'tox', '-e', 'py']:
    raise SystemExit(9)
if mode == 'mutate' and arguments == ['check', '--lock']:
    pathlib.Path('candidate.txt').write_text('changed by gate\\n')
if mode == 'chmod' and arguments == ['check', '--lock']:
    pathlib.Path('candidate.txt').chmod(int(os.environ['KGM_GATE_TEST_CHMOD']))
if mode == 'move-head' and arguments == ['check', '--lock']:
    subprocess.run([os.environ['KGM_GATE_TEST_GIT'], '-c', 'commit.gpgsign=false',
                    'commit', '--allow-empty', '-m', 'Moved during gate'], check=True)
if mode in ('flag-assume-unchanged', 'flag-skip-worktree') and arguments == ['check', '--lock']:
    git = os.environ['KGM_GATE_TEST_GIT']
    subprocess.run([git, 'update-index', '--' + mode.removeprefix('flag-'), '--', 'candidate.txt'], check=True)
    pathlib.Path('candidate.txt').write_text('hidden change by gate\\n')
    index = pathlib.Path(subprocess.check_output([git, 'rev-parse', '--git-path', 'index'], text=True).strip())
    pathlib.Path(os.environ['KGM_GATE_TEST_INDEX_SNAPSHOT']).write_bytes(index.read_bytes())
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
        ["run", "--", "tox", "-e", "py", "--", "tests", "--durations=50"],
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


def commit_candidate_mode(candidate: Path, mode: int) -> None:
    """Commit a test file's mode, then disable ordinary Git mode reporting locally."""
    (candidate / "candidate.txt").chmod(mode)
    git(candidate, "-c", "core.fileMode=true", "add", "candidate.txt")
    git(candidate, "commit", "--allow-empty", "-qm", "Record candidate file mode")
    git(candidate, "config", "core.fileMode", "false")


@pytest.mark.parametrize("committed_mode,working_mode", [(0o644, 0o755), (0o755, 0o644)])
def test_ignored_executable_mode_change_is_rejected_before_evidence(
    candidate: Path, committed_mode: int, working_mode: int
) -> None:
    """Reject ignored executable-bit changes without changing work, index or config."""
    commit_candidate_mode(candidate, committed_mode)
    target = candidate / "candidate.txt"
    target.chmod(working_mode)
    assert git(candidate, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=no") == ""
    head = git(candidate, "rev-parse", "HEAD")
    before_bytes = target.read_bytes()
    index = candidate / git(candidate, "rev-parse", "--git-path", "index")
    config = candidate / git(candidate, "rev-parse", "--git-path", "config")
    before_index, before_config = index.read_bytes(), config.read_bytes()

    result = invoke(candidate)

    assert result.returncode != 0
    assert "Candidate has tracked changes" in result.stderr
    assert "GATES_COMPLETE" not in result.stdout
    assert not (candidate.parent / "commands.jsonl").exists()
    assert not (candidate / "data").exists()
    assert git(candidate, "rev-parse", "HEAD") == head
    assert target.read_bytes() == before_bytes
    assert stat.S_IMODE(target.stat().st_mode) == working_mode
    assert index.read_bytes() == before_index
    assert config.read_bytes() == before_config
    assert git(candidate, "config", "core.fileMode") == "false"


@pytest.mark.parametrize("committed_mode,working_mode", [(0o644, 0o755), (0o755, 0o644)])
def test_executable_mode_change_during_gate_aborts_before_full_suite(
    candidate: Path, monkeypatch: pytest.MonkeyPatch, committed_mode: int, working_mode: int
) -> None:
    """Repeat mode checks after a gate even when local Git ignores mode changes."""
    commit_candidate_mode(candidate, committed_mode)
    target = candidate / "candidate.txt"
    head = git(candidate, "rev-parse", "HEAD")
    before_bytes = target.read_bytes()
    index = candidate / git(candidate, "rev-parse", "--git-path", "index")
    config = candidate / git(candidate, "rev-parse", "--git-path", "config")
    before_index, before_config = index.read_bytes(), config.read_bytes()
    monkeypatch.setenv("KGM_GATE_TEST_MODE", "chmod")
    monkeypatch.setenv("KGM_GATE_TEST_CHMOD", str(working_mode))

    result = invoke(candidate)

    assert result.returncode != 0
    assert recorded_commands(candidate) == [["check", "--lock"]]
    assert "GATES_COMPLETE" not in result.stdout
    entries = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["exit_code"] == 0
    assert "Candidate has tracked changes" in entries[0]["candidate_error"]
    assert git(candidate, "rev-parse", "HEAD") == head
    assert target.read_bytes() == before_bytes
    assert stat.S_IMODE(target.stat().st_mode) == working_mode
    assert index.read_bytes() == before_index
    assert config.read_bytes() == before_config
    assert git(candidate, "config", "core.fileMode") == "false"


def test_committed_executable_is_accepted_with_filemode_disabled(candidate: Path) -> None:
    """A committed executable remains a valid candidate under core.fileMode=false."""
    commit_candidate_mode(candidate, 0o755)
    target = candidate / "candidate.txt"
    head = git(candidate, "rev-parse", "HEAD")
    before_bytes = target.read_bytes()
    index = candidate / git(candidate, "rev-parse", "--git-path", "index")
    config = candidate / git(candidate, "rev-parse", "--git-path", "config")
    before_index, before_config = index.read_bytes(), config.read_bytes()

    result = invoke(candidate)

    assert result.returncode == 0, result.stderr
    commands = recorded_commands(candidate)
    assert len(commands) == 4
    assert commands[-1] == ["run", "--", "tox", "-e", "py", "--", "tests", "--durations=50"]
    assert f"GATES_COMPLETE {head}" in result.stdout
    assert git(candidate, "rev-parse", "HEAD") == head
    assert target.read_bytes() == before_bytes
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert index.read_bytes() == before_index
    assert config.read_bytes() == before_config
    assert git(candidate, "config", "core.fileMode") == "false"


@pytest.mark.parametrize("flags", [("assume-unchanged",), ("skip-worktree",), ("assume-unchanged", "skip-worktree")])
@pytest.mark.parametrize("dirty", [False, True])
@pytest.mark.parametrize("filename", ["candidate.txt", " leading\ncandidate\t name.txt "])
def test_hidden_index_entries_are_rejected_before_evidence(
    candidate: Path, flags: tuple[str, ...], dirty: bool, filename: str
) -> None:
    """Reject clean or dirty flagged paths without changing flags, bytes or HEAD."""
    target = candidate / filename
    if filename != "candidate.txt":
        target.write_text("committed unusual path\n", encoding="utf-8")
        git(candidate, "add", "--", filename)
        git(candidate, "commit", "-qm", "Add unusual tracked path")
    head = git(candidate, "rev-parse", "HEAD")
    for flag in flags:
        git(candidate, "update-index", f"--{flag}", "--", filename)
    if dirty:
        target.write_text("hidden uncommitted code\n", encoding="utf-8")
    # Demonstrate why status alone is not proof of a committed candidate.
    assert git(candidate, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=no") == ""
    before_bytes = target.read_bytes()
    before_flags = git(candidate, "ls-files", "-v", "-z")
    index = candidate / git(candidate, "rev-parse", "--git-path", "index")
    before_index = index.read_bytes()

    result = invoke(candidate)

    assert result.returncode != 0
    assert "assume-unchanged or skip-worktree index flags" in result.stderr
    assert repr(filename) in result.stderr
    assert "GATES_COMPLETE" not in result.stdout
    assert not (candidate.parent / "commands.jsonl").exists()
    assert not (candidate / "data").exists()
    assert git(candidate, "rev-parse", "HEAD") == head
    assert target.read_bytes() == before_bytes
    assert git(candidate, "ls-files", "-v", "-z") == before_flags
    assert index.read_bytes() == before_index


@pytest.mark.parametrize("flag,tag", [("assume-unchanged", "h"), ("skip-worktree", "S")])
def test_index_flag_introduced_by_gate_aborts_before_full_suite(
    candidate: Path, monkeypatch: pytest.MonkeyPatch, flag: str, tag: str
) -> None:
    """Inspect flags again after gates, preserving any hidden change on rejection."""
    head = git(candidate, "rev-parse", "HEAD")
    snapshot = candidate.parent / "index-after-gate"
    monkeypatch.setenv("KGM_GATE_TEST_MODE", f"flag-{flag}")
    monkeypatch.setenv("KGM_GATE_TEST_INDEX_SNAPSHOT", str(snapshot))

    result = invoke(candidate)

    assert result.returncode != 0
    assert recorded_commands(candidate) == [["check", "--lock"]]
    assert "GATES_COMPLETE" not in result.stdout
    entries = json.loads((candidate / "data/validation/pr-gates/kgm-test-run-gates.json").read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["exit_code"] == 0
    assert "assume-unchanged or skip-worktree index flags" in entries[0]["candidate_error"]
    assert git(candidate, "rev-parse", "HEAD") == head
    assert (candidate / "candidate.txt").read_text(encoding="utf-8") == "hidden change by gate\n"
    assert git(candidate, "ls-files", "-v", "-z") == f"{tag} candidate.txt\0"
    index = candidate / git(candidate, "rev-parse", "--git-path", "index")
    assert index.read_bytes() == snapshot.read_bytes()


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
    assert plan["commands"][-1] == ["poetry", "run", "--", "tox", "-e", "py", "--", "tests", "--durations=50"]
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


def test_real_poetry_forwards_full_suite_arguments_once(tmp_path: Path) -> None:
    """The actual Poetry parser preserves tox's separator and the child's status."""
    poetry = shutil.which("poetry")
    assert poetry is not None, "The gate runner requires Poetry on PATH"
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "gate-dispatch-test"\nversion = "0.0.0"\n'
        'description = "Offline argument forwarding probe"\nauthors = []\n'
        '[tool.poetry.dependencies]\npython = ">=3.10"\n',
        encoding="utf-8",
    )
    ledger = tmp_path / "child-arguments.jsonl"
    recorder = tmp_path / "record-child-arguments"
    recorder.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        f"with Path({str(ledger)!r}).open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(23)\n",
        encoding="utf-8",
    )
    recorder.chmod(0o700)
    # Derive the boundary from production; replacing tox must not repair its syntax.
    command = list(runpy.run_path(str(RUNNER))["COMMANDS"][-1])
    command[0] = poetry
    command[command.index("tox")] = str(recorder)
    command.insert(1, "--no-plugins")
    environment = {name: value for name, value in os.environ.items() if not name.startswith("POETRY_")}
    environment.update(
        POETRY_CONFIG_DIR=str(tmp_path / "poetry-config"),
        POETRY_CACHE_DIR=str(tmp_path / "poetry-cache"),
        POETRY_VIRTUALENVS_CREATE="false",
    )
    result = subprocess.run(  # noqa: S603 - actual fixed production command with a temporary recorder
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 23, (result.stdout, result.stderr)
    assert [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()] == [
        ["-e", "py", "--", "tests", "--durations=50"]
    ]
