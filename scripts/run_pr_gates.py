"""
Run PR checks with one full test suite on a clean, committed candidate.

Purpose: implement the single-suite validation policy requested on 2026-10-28.
Inputs: a candidate checkout, a run label, and installed Poetry dependencies.
Outputs: per-command logs and a JSON evidence ledger under data/validation/pr-gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

COMMANDS = (
    ("poetry", "check", "--lock"),
    ("poetry", "run", "python", "scripts/generate_merge_configs.py", "--check"),
    ("poetry", "run", "tox", "-e", "coverage-clean,format-check,lint,codespell,docstr-coverage"),
    ("poetry", "run", "tox", "-e", "py", "--", "tests", "--durations=50"),
)


def git_output(root: Path, *arguments: str) -> str:
    """Read repository state without invoking a shell."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required on PATH")
    result = subprocess.run(  # noqa: S603 - git and arguments are controlled by this module
        [git, *arguments], cwd=root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def check_candidate(root: Path, commit: str) -> None:
    """Reject a moved HEAD or any staged or unstaged tracked changes."""
    if git_output(root, "rev-parse", "HEAD") != commit:
        raise RuntimeError("HEAD moved during validation; validate the final candidate again")
    if git_output(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise RuntimeError(
            "Candidate has tracked changes. Finish formatting, review and commit the changes, "
            "then validate the final candidate again."
        )


def run_gates(root: Path, commit: str, label: str, output_dir: Path) -> int:
    """Run cheap checks before tox, saving each result and stopping on any failure."""
    check_candidate(root, commit)
    report = output_dir / f"kgm-{label}-gates.json"
    logs = [output_dir / f"kgm-{label}-{index}.log" for index in range(1, len(COMMANDS) + 1)]
    if any(path.exists() for path in [report, *logs]):
        raise RuntimeError("Run label already has evidence; use a new label to preserve the earlier results")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Claim this label exclusively before starting work; concurrent callers must not share logs.
    with report.open("x", encoding="utf-8") as handle:
        handle.write("[]\n")
    # Final validation ignores local subset selectors; targeted tests belong in the editing loop.
    environment = os.environ.copy()
    for variable in list(environment):
        if variable.startswith("TOX") or variable == "PYTEST_ADDOPTS":
            environment.pop(variable)
    # Tox's per-user defaults can also set no_test/package_only/skip_env (#1679).
    environment["TOX_USER_CONFIG_FILE"] = os.devnull
    results = []
    for command, logfile in zip(COMMANDS, logs, strict=True):
        check_candidate(root, commit)
        started = time.monotonic()
        with logfile.open("w", encoding="utf-8") as log:
            try:
                code = subprocess.run(  # noqa: S603 - commands are fixed above; no shell is used
                    command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False
                ).returncode
            except OSError as error:
                log.write(f"Could not start command: {error}\n")
                code = 127
        item = {
            "command": list(command),
            "commit": commit,
            "exit_code": code,
            "seconds": round(time.monotonic() - started, 2),
            "log": str(logfile),
        }
        try:
            check_candidate(root, commit)
        except RuntimeError as error:
            item["candidate_error"] = str(error)
        results.append(item)
        pending_report = report.with_suffix(".json.tmp")
        pending_report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        pending_report.replace(report)
        print(json.dumps(item), flush=True)
        if code or "candidate_error" in item:
            print(f"GATES_FAILED {commit}; see {report}", file=sys.stderr)
            return code if code > 0 else 1
    print(f"GATES_COMPLETE {commit}", flush=True)
    return 0


def main() -> int:
    """Parse the run label and resolve a checkout-root invocation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="unique run label (letters, numbers, dots, underscores and hyphens)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/validation/pr-gates"))
    parser.add_argument("--dry-run", action="store_true", help="print the plan without running gates or writing files")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.label):
        parser.error("label must start with a letter or number and contain at most 100 safe filename characters")
    try:
        root = Path(git_output(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
        if root != Path.cwd().resolve():
            raise RuntimeError(f"Run this command from the checkout root: {root}")
        commit = git_output(root, "rev-parse", "HEAD")
        output_dir = args.output_dir.resolve()
        if args.dry_run:
            print(json.dumps({"commit": commit, "commands": COMMANDS, "output_dir": str(output_dir)}, indent=2))
            return 0
        return run_gates(root, commit, args.label, output_dir)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"GATES_FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
