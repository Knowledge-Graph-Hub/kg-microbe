"""
Install the committed single-suite policy into existing feature-branch checkouts.

Purpose: install the requested KG-Microbe validation policy on M5, 2026-10-28.
Inputs: a committed source checkout, its baseline ref, and explicit target roots.
Outputs: policy-only target commits, preserved originals, and JSON installation receipts.
The default prints a plan. Only --apply changes files; failures never discard local work.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SOURCE = Path(__file__).resolve().parents[2]
LEGACY_NAMES = ("kgm-run-pr-gates.py", "kgm-run-pr-gates-v2.py", "kgm-run-pr-gates-v3.py")


def git(root: Path, *arguments: str) -> bytes:
    """Run a bounded Git operation without a shell or network access."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git is required on PATH")
    return subprocess.check_output(  # noqa: S603 - explicit Git argument arrays, no shell
        [executable, *arguments], cwd=root, stderr=subprocess.PIPE
    )


def git_text(root: Path, *arguments: str) -> str:
    """Read a textual Git result."""
    return git(root, *arguments).decode().strip()


def digest(data: bytes) -> str:
    """Hash full file contents for installation evidence."""
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, name: str) -> Path:
    """Reject paths that could write outside a target or traverse a symlink."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(part in {"..", ".git"} for part in relative.parts):
        raise RuntimeError(f"Unsafe managed path: {name!r}")
    path = root
    for index, part in enumerate(relative.parts):
        path = path / part
        if path.is_symlink():
            raise RuntimeError(f"Refusing symlink traversal: {path}")
        if index < len(relative.parts) - 1 and path.exists() and not path.is_dir():
            raise RuntimeError(f"Parent path is not a directory: {path}")
    return path


def clean_checkout(root: Path, *, feature: bool) -> tuple[str, str]:
    """Require a checkout root with no tracked edits and optionally a feature branch."""
    if Path(git_text(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise RuntimeError(f"Not a checkout root: {root}")
    if git_text(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise RuntimeError(f"Tracked edits must be reviewed and committed before installation: {root}")
    try:
        branch = git_text(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except subprocess.CalledProcessError:
        if feature:
            raise RuntimeError(f"Target must already be on a feature branch: {root}") from None
        branch = "(detached)"
    if feature and branch in {"main", "master", "trunk"}:
        raise RuntimeError(f"Target must already be on a feature branch: {root} ({branch})")
    return git_text(root, "rev-parse", "HEAD"), branch


def blob(root: Path, revision: str, name: str) -> tuple[bytes, int] | None:
    """Read a regular tracked file at a commit, distinguishing absence from content."""
    entry = git(root, "ls-tree", "-z", revision, "--", name)
    if not entry:
        return None
    mode = entry.split(b" ", 1)[0]
    if mode not in {b"100644", b"100755"}:
        raise RuntimeError(f"Managed paths must be regular files: {revision}:{name}")
    return git(root, "show", f"{revision}:{name}"), 0o755 if mode == b"100755" else 0o644


@dataclass(frozen=True)
class ManagedFile:
    """Hold the committed replacement and the baseline used to detect collisions."""

    name: str
    data: bytes
    mode: int
    baseline: bytes | None


def managed_files(base: str, head: str) -> list[ManagedFile]:
    """Derive only added and modified policy files from the committed source diff."""
    names = git(SOURCE, "diff", "--name-only", "--diff-filter=AM", "-z", base, head).split(b"\0")
    files = []
    for raw_name in filter(None, names):
        name = os.fsdecode(raw_name)
        safe_path(SOURCE, name)
        current = blob(SOURCE, head, name)
        if current is None:
            raise RuntimeError(f"Missing source file: {name}")
        baseline = blob(SOURCE, base, name)
        files.append(ManagedFile(name, current[0], current[1], None if baseline is None else baseline[0]))
    if not files:
        raise RuntimeError("The selected baseline has no added or modified policy files")
    return files


def target_files(root: Path, files: list[ManagedFile]) -> list[dict]:
    """Validate every managed path before any write, including untracked collisions."""
    result = []
    for item in files:
        path = safe_path(root, item.name)
        if path.exists() and not path.is_file():
            raise RuntimeError(f"Managed path is not a regular file: {path}")
        current = path.read_bytes() if path.exists() else None
        if current != item.data and current != item.baseline:
            raise RuntimeError(f"Target differs from both baseline and installed policy: {path}")
        if current is None and item.baseline is not None:
            raise RuntimeError(f"A baseline file is missing from the target: {path}")
        result.append(
            {
                "path": item.name,
                "before_sha256": None if current is None else digest(current),
                "after_sha256": digest(item.data),
                "content_changes": current != item.data,
            }
        )
    return result


def write_file(path: Path, data: bytes, mode: int) -> None:
    """Write a checked destination while retaining the requested executable bit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def write_receipt(path: Path, receipt: dict) -> None:
    """Replace an installation receipt atomically after each completed stage."""
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def install_target(root: Path, head: str, base: str, files: list[ManagedFile], planned: dict, stamp: str) -> Path:
    """Back up, copy, and commit only the managed files on the existing feature branch."""
    prior, branch = clean_checkout(root, feature=True)
    if (prior, branch) != (planned["prior_head"], planned["branch"]):
        raise RuntimeError(f"Target moved after planning: {root}")
    observed = target_files(root, files)
    if observed != planned["files"]:
        raise RuntimeError(f"Target files changed after planning: {root}")
    evidence = safe_path(root, f"data/validation/pr-gates/install-{stamp}")
    evidence.mkdir(parents=True, exist_ok=False)
    receipt_path = evidence / "receipt.json"
    receipt = {**planned, "source_head": head, "source_baseline": base, "post_head": None, "status": "installing"}
    write_receipt(receipt_path, receipt)
    try:
        for item, record in zip(files, receipt["files"], strict=True):
            path = safe_path(root, item.name)
            if path.exists():
                backup = safe_path(evidence, "backups/" + item.name)
                original = path.read_bytes()
                if digest(original) != record["before_sha256"]:
                    raise RuntimeError(f"File changed before copying: {path}")
                write_file(backup, original, stat.S_IMODE(path.stat().st_mode))
                record["backup"] = str(backup)
            write_file(path, item.data, item.mode)
            write_receipt(receipt_path, receipt)
        if (git_text(root, "rev-parse", "HEAD"), git_text(root, "symbolic-ref", "--short", "HEAD")) != (prior, branch):
            raise RuntimeError(f"HEAD or branch moved during installation: {root}")
        names = [item.name for item in files]
        changed = set(filter(None, git(root, "diff", "--name-only", "HEAD", "-z").split(b"\0")))
        if changed - {os.fsencode(name) for name in names}:
            raise RuntimeError(f"Unrelated tracked files changed during installation: {root}")
        git(root, "add", "--", *names)
        if git(root, "diff", "--cached", "--name-only", "-z"):
            git(root, "commit", "--only", "-m", f"Install single-suite validation policy from {head}", "--", *names)
        post, current_branch = clean_checkout(root, feature=True)
        if current_branch != branch or any(record["content_changes"] for record in target_files(root, files)):
            raise RuntimeError(f"Installed policy changed during the commit: {root}")
        receipt.update({"post_head": post, "status": "installed"})
        write_receipt(receipt_path, receipt)
        return receipt_path
    except (Exception, KeyboardInterrupt) as error:
        receipt.update({"status": "failed", "error": str(error), "post_head": git_text(root, "rev-parse", "HEAD")})
        write_receipt(receipt_path, receipt)
        print(f"Installation stopped; originals and receipt remain at {evidence}", file=sys.stderr)
        raise


def legacy_plan(directory: Path, wrapper: bytes) -> list[dict]:
    """Recognize the three old gate entrypoints without accepting arbitrary scripts."""
    result = []
    for name in LEGACY_NAMES:
        path = safe_path(directory, name)
        if not path.exists():
            continue
        if not path.is_file():
            raise RuntimeError(f"Legacy entrypoint is not a regular file: {path}")
        data = path.read_bytes()
        if data != wrapper:
            recognized = False
            try:
                tree = ast.parse(data)
            except (SyntaxError, UnicodeDecodeError) as error:
                raise RuntimeError(f"Unrecognized legacy runner: {path}") from error
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "commands" for t in node.targets
                ):
                    try:
                        commands = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(commands, list):
                        recognized = ["poetry", "run", "pytest"] in commands and ["poetry", "run", "tox"] in commands
                    if recognized:
                        break
            if not recognized:
                raise RuntimeError(f"Unrecognized legacy runner; leaving it untouched: {path}")
        result.append({"path": str(path), "before_sha256": digest(data), "after_sha256": digest(wrapper)})
    return result


def install_legacy(entries: list[dict], wrapper: bytes, receipt_path: Path) -> None:
    """Back up known legacy entrypoints alongside the first target's receipt."""
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["legacy_entrypoints"] = []
    receipt["legacy_status"] = "installing"
    write_receipt(receipt_path, receipt)
    try:
        for item in entries:
            path = Path(item["path"])
            safe_path(path.parent, path.name)
            current = path.read_bytes()
            if digest(current) != item["before_sha256"]:
                raise RuntimeError(f"Legacy runner changed after planning: {path}")
            backup = safe_path(receipt_path.parent, "legacy/" + path.name)
            mode = stat.S_IMODE(path.stat().st_mode)
            write_file(backup, current, mode)
            write_file(path, wrapper, mode)
            receipt["legacy_entrypoints"].append({**item, "backup": str(backup)})
            write_receipt(receipt_path, receipt)
        receipt["legacy_status"] = "installed"
        write_receipt(receipt_path, receipt)
    except (Exception, KeyboardInterrupt) as error:
        receipt.update({"legacy_status": "failed", "legacy_error": str(error)})
        write_receipt(receipt_path, receipt)
        raise


def main() -> int:
    """Plan all destinations before optionally installing and committing the policy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, action="append", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--legacy-dir", type=Path)
    args = parser.parse_args()
    try:
        head, _ = clean_checkout(SOURCE, feature=False)
        git(SOURCE, "ls-files", "--error-unmatch", str(Path(__file__).resolve().relative_to(SOURCE)))
        base = git_text(SOURCE, "rev-parse", "--verify", "--end-of-options", args.base_ref + "^{commit}")
        git(SOURCE, "merge-base", "--is-ancestor", base, head)
        files = managed_files(base, head)
        targets = list(dict.fromkeys(path.resolve() for path in args.target))
        plans = []
        for root in targets:
            prior, branch = clean_checkout(root, feature=True)
            safe_path(root, "data/validation/pr-gates/install-check")
            plans.append(
                {"target": str(root), "prior_head": prior, "branch": branch, "files": target_files(root, files)}
            )
        wrapper = blob(SOURCE, head, "scripts/adhoc/legacy_pr_gates.py")
        if wrapper is None:
            raise RuntimeError("The source commit must contain the legacy wrapper")
        legacy = legacy_plan(args.legacy_dir.resolve(), wrapper[0]) if args.legacy_dir else []
        print(json.dumps({"source_head": head, "source_baseline": base, "targets": plans, "legacy": legacy}, indent=2))
        if not args.apply:
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        receipts = [
            install_target(root, head, base, files, plan, stamp) for root, plan in zip(targets, plans, strict=True)
        ]
        install_legacy(legacy, wrapper[0], receipts[0])
        for path in receipts:
            print(f"INSTALLED {path}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"INSTALL_FAILED: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode(errors="replace"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
