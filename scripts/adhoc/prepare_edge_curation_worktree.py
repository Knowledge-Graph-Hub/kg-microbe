#!/usr/bin/env python3
"""
Prepare an isolated worktree under CLAW's short repository metadata lease.

Purpose: 2026-11-03 edge-curation implementation; no issue assigned yet.
Inputs: explicit source/destination, expected origin, branch and orchestration root.
Output: new feature worktree and its base SHA. Existing working files are untouched.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    """Validate repository identity and bound fetch/worktree metadata operations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--upstream", required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    claw = args.claw_root.resolve(strict=True)
    git = shutil.which("git")
    if git is None:
        parser.error("git is required")
    if args.destination.exists():
        parser.error("destination already exists; refusing to overwrite")
    origin = (
        subprocess.check_output(  # noqa: S603 - resolved git and literal read-only arguments
            [git, "-C", str(source), "remote", "get-url", "origin"], text=True
        )
        .strip()
        .removesuffix(".git")
    )
    if origin != args.expected_origin.removesuffix(".git"):
        parser.error("unexpected repository origin")
    if not args.branch.startswith(("feat/", "docs/", "test/")):
        parser.error("a new feature/docs/test branch is required")
    subprocess.run(  # noqa: S603 - git validates the requested feature ref
        [git, "check-ref-format", f"refs/heads/{args.branch}"], check=True
    )
    subprocess.run(  # noqa: S603 - validate the upstream ref before constructing a refspec
        [git, "check-ref-format", f"refs/heads/{args.upstream}"], check=True
    )
    os.environ["OPENCLAW_ORCHESTRATION_ROOT"] = str(claw)
    sys.path[:0] = [str(claw), str(claw / "src")]
    from plugins.lock_manager import LockManager

    manager = LockManager({"my_id": f"edge-curation-metadata-{os.getpid()}"})
    commands = (
        [git, "-C", str(source), "fetch", "origin", f"refs/heads/{args.upstream}:refs/remotes/origin/{args.upstream}"],
        [
            git,
            "-C",
            str(source),
            "worktree",
            "add",
            "-b",
            args.branch,
            str(args.destination),
            f"origin/{args.upstream}",
        ],
    )
    for command in commands:
        if not manager.acquire_lock(args.resource, "edge-curation-worktree", timeout=600):
            raise SystemExit(f"repository metadata lock unavailable: {args.resource}")
        try:
            subprocess.run(command, check=True, timeout=300)  # noqa: S603 - validated refs; no shell
        finally:
            if not manager.release_lock(args.resource):
                raise RuntimeError("could not release owned repository metadata lease")
    subprocess.run(  # noqa: S603 - resolved git with literal read-only arguments
        [git, "-C", str(args.destination), "log", "-1", "--format=%H"], check=True
    )


if __name__ == "__main__":
    main()
