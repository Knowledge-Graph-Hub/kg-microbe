#!/usr/bin/env python3
"""
Preserve PR #1871 worktree artifacts before separate Git cleanup (2026-11-19).

Inputs: clean exact Git HEAD/branch, ignored-inclusive status and lstat metadata.
Outputs: exclusive plan and same-volume archive with incremental JSON receipts.
No deletion, Git mutation, remote action or artifact-content reads. Symlinks are
opaque objects, never followed. Runtime bytes become historical evidence: their
absolute paths must be requalified before reuse. Preserve tracked source with
git archive separately. Before applying a plan, the caller must verify that no
active jobs or outside consumers depend on these paths and quiesce all writers.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

TEMPORARY_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")  # noqa: S108 - denylist


class Refusal(ValueError):
    """A preservation precondition failed; all existing evidence is retained."""


def require(condition, message):
    """Fail closed on an unmet preservation condition."""
    if not condition:
        raise Refusal(message)


def git(root, *args):
    """Run a local read-only Git query without optional index writes."""
    executable = shutil.which("git")
    require(executable is not None, "Git executable unavailable")
    return subprocess.check_output(  # noqa: S603 - fixed Git argv; no shell
        [executable, "-C", str(root), *args], env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    )


def real_path(path):
    """Reject symlinked existing ancestors rather than silently resolving them."""
    path = Path(os.path.abspath(path))
    for ancestor in (*reversed(path.parents), path):
        require(not ancestor.is_symlink(), f"Symlink in path: {ancestor}")
    require(path == path.resolve(), f"Noncanonical path: {path}")
    return path


def relative(name):
    """Validate one Git-relative path before joining it to a trusted root."""
    path = Path(name)
    require(
        bool(path.parts) and not path.is_absolute() and not {"..", ".git"}.intersection(path.parts),
        f"Unsafe relative path: {name}",
    )
    return path


def state(root):
    """Pin checkout identity and refuse an active Git operation."""
    root = real_path(root)
    top = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip())
    require(top == root, "Worktree must be its exact repository root")
    directories = [
        Path(os.fsdecode(git(root, "rev-parse", "--path-format=absolute", flag)).strip())
        for flag in ("--git-dir", "--git-common-dir")
    ]
    for directory in directories:
        for name in (
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "BISECT_START",
            "rebase-merge",
            "rebase-apply",
            "index.lock",
            "config.lock",
            "packed-refs.lock",
        ):
            require(not os.path.lexists(directory / name), f"Active Git operation: {name}")
    return {
        "worktree": str(root),
        "common_dir": str(directories[1]),
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "branch": git(root, "symbolic-ref", "--short", "HEAD").decode().strip(),
    }


def candidates(root):
    """Collapse overlapping normal-status directories, including ignored paths."""
    entries = git(root, "status", "--porcelain=v1", "-z", "--ignored", "--untracked-files=normal")
    names = set()
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        require(entry[:2] in (b"??", b"!!"), "Tracked worktree/index is not clean")
        names.add(relative(os.fsdecode(entry[3:]).rstrip("/")).as_posix())
    selected = []
    for name in sorted(names, key=lambda value: (len(Path(value).parts), value)):
        if not any(name.startswith(parent + "/") for parent in selected):
            selected.append(name)
    tracked = [os.fsdecode(value) for value in git(root, "ls-files", "-z").split(b"\0") if value]
    for name in selected:
        require(
            not any(value == name or value.startswith(name + "/") for value in tracked),
            f"Selected path contains tracked members: {name}",
        )
    return sorted(selected)


def inventory(path, device):
    """Inventory metadata recursively without reading contents or following links."""
    result = {}

    def visit(current, name):
        info = current.lstat()
        require(info.st_dev == device and not os.path.ismount(current), f"Mount/device boundary: {current}")
        require(
            stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode),
            f"Unsupported file type: {current}",
        )
        row = {key: getattr(info, "st_" + key) for key in ("dev", "ino", "mode", "size", "mtime_ns")}
        if stat.S_ISLNK(info.st_mode):
            row["target"] = os.readlink(current)
        result[name] = row
        if stat.S_ISDIR(info.st_mode):
            children = sorted(current.iterdir())
            names = {child.name for child in children}
            require(
                ".git" not in names and not {"HEAD", "objects", "refs"}.issubset(names), f"Nested repository: {current}"
            )
            for child in children:
                visit(child, f"{name}/{child.name}" if name != "." else child.name)

    visit(path, ".")
    return result


def outside_worktrees(root, destination):
    """Require durable evidence outside every registered checkout."""
    destination = real_path(destination)
    require(
        not any(destination.is_relative_to(Path(prefix)) for prefix in TEMPORARY_ROOTS),
        "Archive must be durable, not temporary",
    )
    for field in git(root, "worktree", "list", "--porcelain", "-z").split(b"\0"):
        if field.startswith(b"worktree "):
            checkout = Path(os.fsdecode(field[9:])).resolve()
            require(not destination.is_relative_to(checkout), f"Destination inside worktree: {checkout}")
    return destination


def sync_directory(path):
    """Persist a namespace change before acknowledging it in a receipt."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_new(path, value):
    """Write an exclusive durable JSON record without replacing an older record."""
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def make_plan(root, destination, head, branch):
    """Create a reviewable in-memory plan; CLI saves it exclusively."""
    identity = state(root)
    root = Path(identity["worktree"])
    require(identity["head"] == head and identity["branch"] == branch, "Unexpected HEAD/branch")
    destination = outside_worktrees(root, destination)
    require(not os.path.lexists(destination), "Archive destination already exists")
    device = root.stat().st_dev
    require(
        destination.parent.is_dir() and destination.parent.stat().st_dev == device,
        "Archive parent must exist on the same volume",
    )
    items = {name: inventory(root / name, device) for name in candidates(root)}
    require(state(root) == identity and candidates(root) == sorted(items), "Checkout changed during planning")
    return {
        "version": 1,
        "identity": identity,
        "destination": str(destination),
        "device": device,
        "items": items,
        "runtime": "historical bytes; requalify relocated runtimes",
    }


def rename_exclusive(source, destination):
    """Use the OS's atomic no-replace rename; never fall back to overwrite."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function, args = library.renamex_np, (os.fsencode(source), os.fsencode(destination), 4)
    elif sys.platform.startswith("linux"):
        function, args = library.renameat2, (-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise Refusal("Exclusive rename is supported only on macOS/Linux")
    if function(*args):
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), str(destination))


def reconcile(plan, root, destination):
    """Recheck exact identity and every source/archive item before success (#1877)."""
    require(state(root) == plan["identity"], "Checkout identity changed")
    outside_worktrees(root, destination)
    require(destination.parent.stat().st_dev == plan["device"], "Destination volume changed")
    pending, moved = [], []
    for name, expected in plan["items"].items():
        source, target = root / name, destination / "payload" / name
        real_path(source.parent)
        real_path(target.parent)
        present, retained = os.path.lexists(source), os.path.lexists(target)
        require(present != retained, f"Expected exactly one source/archive copy: {name}")
        require(inventory(source if present else target, plan["device"]) == expected, f"Metadata drift: {name}")
        (pending if present else moved).append(name)
    require(candidates(root) == sorted(pending), "Unplanned artifacts or tracked changes")
    require(state(root) == plan["identity"], "Checkout identity changed during reconciliation")
    return pending, moved


def apply(plan, mode, dry_run=False):
    """Preserve one canary or remaining items; interrupted renames are resumable."""
    require(plan["version"] == 1, "Unsupported plan")
    root = real_path(plan["identity"]["worktree"])
    destination = outside_worktrees(root, plan["destination"])
    for name in plan["items"]:
        relative(name)
    if destination.exists():
        real_path(destination / "plan.json")
        require((destination / "plan.json").is_file(), "Existing destination lacks its preservation plan")
        require(json.loads((destination / "plan.json").read_text()) == plan, "Archive belongs to another plan")
    pending, moved = reconcile(plan, root, destination)
    require(mode == "canary" or moved or not pending, "Run and verify one canary first")
    selected = pending[:1] if mode == "canary" else pending
    if dry_run:
        return {"status": "DRY_RUN", "selected": selected, "retained": moved}
    if not destination.exists():
        destination.mkdir(mode=0o700)
        save_new(destination / "plan.json", plan)
    for name in selected:
        source, target = root / name, destination / "payload" / name
        require(state(root) == plan["identity"], "Checkout identity changed")
        real_path(source.parent)
        real_path(target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        real_path(target.parent)
        require(inventory(source, plan["device"]) == plan["items"][name], f"Metadata drift: {name}")
        event = {"source": str(source), "destination": str(target), "item": name}
        token = uuid.uuid4().hex
        save_new(destination / f"{token}-intent.json", event)
        try:
            rename_exclusive(source, target)
            sync_directory(source.parent)
            sync_directory(target.parent)
            require(inventory(target, plan["device"]) == plan["items"][name], f"Post-move drift: {name}")
            save_new(destination / f"{token}-verified.json", {**event, "metadata_verified": True})
        except Exception as error:
            save_new(destination / f"{token}-failure.json", {**event, "error": str(error)})
            raise
    try:
        final_pending, final_moved = reconcile(plan, root, destination)
        require(
            sorted(final_pending) == sorted(set(pending) - set(selected))
            and sorted(final_moved) == sorted(moved + selected),
            "Source/archive locations changed unexpectedly",
        )
    except Exception as error:
        save_new(
            destination / f"{uuid.uuid4().hex}-final-failure.json", {"error": str(error), "moved_this_run": selected}
        )
        raise
    result = {
        "status": "PRESERVED" if not final_pending else "CANARY_PRESERVED",
        "moved_this_run": selected,
        "retained_before_run": moved,
        "retained_metadata_verified": True,
    }
    save_new(destination / f"{uuid.uuid4().hex}-run.json", result)
    return result


def main():
    """Plan or preserve locally; never remove a worktree or publish anything."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "canary", "remaining"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-branch")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "plan":
            require(
                all((args.worktree, args.destination, args.expected_head, args.expected_branch)),
                "plan requires worktree, destination, expected-head and expected-branch",
            )
            plan = make_plan(args.worktree, args.destination, args.expected_head, args.expected_branch)
            plan_path = outside_worktrees(args.worktree, args.plan)
            require(not plan_path.is_relative_to(Path(plan["destination"])), "Plan must precede archive creation")
            if not args.dry_run:
                save_new(plan_path, plan)
            result = {"status": "PLAN_ONLY", "items": len(plan["items"]), "destination": plan["destination"]}
        else:
            plan = json.loads(real_path(args.plan).read_text())
            result = apply(plan, args.mode, args.dry_run)
        print(json.dumps(result, indent=2))
        return 0
    except (Refusal, OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Preservation refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
