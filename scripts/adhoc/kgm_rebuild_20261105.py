"""
Stage and launch the approved M5 rebuild with preserved execution evidence.

Purpose/date: isolated KG-Microbe current-master rebuild, 2026-11-05.
Inputs: this checkout, its isolated Python, and an explicitly selected old raw tree.
Outputs: independent staged raw files and immutable per-stage evidence under data/.
The plan command is read-only; stage-raw and launch are explicit execution commands.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import runpy
import stat
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/20261105"
PYTHON = ROOT / ".venv/bin/python"
LAUNCHER = Path(__file__).resolve()


def sha256(path: Path) -> str:
    """Hash an artifact without loading it entirely into memory."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def save(path: Path, value: object) -> None:
    """Create a JSON record exclusively, preserving any previous evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def traversal_error(error: OSError) -> None:
    """Reject incomplete inventories instead of skipping unreadable directories."""
    raise error


def inventory(root: Path) -> dict:
    """Inventory every raw file, including ignored files, rejecting links and special files."""
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Raw root must be an actual directory: {root}")
    result = {}
    for directory, directories, files in os.walk(root, followlinks=False, onerror=traversal_error):
        for name in directories + files:
            path = Path(directory) / name
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode):
                raise RuntimeError(f"Raw staging cannot contain symlinks: {path}")
            if stat.S_ISDIR(status.st_mode):
                continue
            if not stat.S_ISREG(status.st_mode):
                raise RuntimeError(f"Raw staging requires regular files: {path}")
            result[str(path.relative_to(root))] = {
                "size": status.st_size,
                "mtime_ns": status.st_mtime_ns,
                "inode": status.st_ino,
                "device": status.st_dev,
                "links": status.st_nlink,
            }
    return result


def environment() -> dict[str, str]:
    """Bind production to the owned checkout while preserving stronger inherited checks."""
    raw = ROOT / "data/raw"
    env = os.environ.copy()
    env.update(
        VIRTUAL_ENV=str(ROOT / ".venv"),
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        POETRY_VIRTUALENVS_CREATE="false",
        JAVA_HOME="/Library/Java/JavaVirtualMachines/temurin-27.jdk/Contents/Home",
        KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
        KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
        KG_MICROBE_METPO_JSON=str(raw / "metpo.json"),
        KG_MICROBE_METPO_TEMPLATE_DIR=str(raw),
        KG_SEMSQL_BUILD="on",
        KG_GO_VERSION_CHECK="strict",
        PREGO_SHAPES="habitat",
        PREGO_MIN_CONFIDENCE="0",
        PREGO_HABITAT_MIN_SCORE="1.0",
        GOLD_APPLY_TAXON_TRIM="true",
        METATRAITS_MULTIPROCESSING="true",
        METATRAITS_WORKERS="4",
        KGM_REBUILD_LAUNCHER=str(LAUNCHER),
    )
    env["PATH"] = os.pathsep.join(
        [
            str(PYTHON.parent),
            env["JAVA_HOME"] + "/bin",
            "/Users/marcin/.local/bin",
            "/opt/homebrew/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
    )
    return env


def origins() -> dict:
    """Prove every loaded KG module belongs to this checkout, including lazy imports."""
    loaded = {}
    for name, module in list(sys.modules.items()):
        if name != "kg_microbe" and not name.startswith("kg_microbe."):
            continue
        file = getattr(module, "__file__", None)
        if file is None:
            continue
        path = Path(file).resolve()
        if not path.is_relative_to(ROOT / "kg_microbe"):
            raise RuntimeError(f"Wrong module origin: {name}: {path}")
        loaded[name] = {"file": str(path), "sha256": sha256(path)}
    if "kg_microbe" not in loaded:
        raise RuntimeError("KG package has not been imported for origin verification")
    return loaded


def execute_stage(label: str, command: list[str]) -> int:
    """Run an explicit Python module/script and record actual imports before and after."""
    folder = EVIDENCE / "stages" / label
    started = time.time()
    result = {"started": started, "pid": os.getpid(), "command": command, "python": sys.executable}
    code = 1
    try:
        if Path.cwd().resolve() != ROOT or Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
            raise RuntimeError("The owned working directory and isolated interpreter are required")
        sys.path.insert(0, str(ROOT))
        importlib.import_module("kg_microbe")
        result["origins_before"] = origins()
        result["versions"] = {name: importlib.metadata.version(name) for name in ("kgx", "bmt", "semsql", "oaklib")}
        save(folder / "started.json", result)
        if command[:1] == ["-m"] and len(command) >= 2:
            sys.argv = command[1:]
            runpy.run_module(command[1], run_name="__main__", alter_sys=True)
        elif command:
            target = (ROOT / command[0]).resolve()
            if not target.is_relative_to(ROOT / "scripts") or not target.is_file():
                raise RuntimeError(f"Expected a checkout-owned script: {target}")
            sys.argv = [str(target), *command[1:]]
            runpy.run_path(str(target), run_name="__main__")
        else:
            raise RuntimeError("No stage command supplied")
        code = 0
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
        if code:
            result["error"] = repr(error)
    except (Exception, KeyboardInterrupt) as error:
        result["error"] = repr(error)
        traceback.print_exc()
        code = 1
    finally:
        try:
            result["origins_after"] = origins()
        except RuntimeError as error:
            result["origin_error"] = str(error)
            code = 1
        result.update(exit_code=code, finished=time.time(), elapsed_seconds=round(time.time() - started, 3))
        save(folder / "result.json", result)
    return code


def preserve_checkout_seeds(source: Path, destination: Path) -> None:
    """Preserve only pristine HEAD-tracked raw seeds also present unchanged in the source."""
    existing = inventory(destination)
    names = subprocess.check_output(  # noqa: S603 - fixed read-only git command
        ["/usr/bin/git", "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", "data/raw"], cwd=ROOT
    ).split(b"\0")
    tracked = [Path(name.decode()) for name in names if name]
    relative = {str(path.relative_to("data/raw")) for path in tracked}
    if not relative or set(existing) != relative:
        raise RuntimeError("Existing raw destination must contain exactly the tracked checkout seeds")
    hashes = {}
    for path in tracked:
        committed = subprocess.check_output(["/usr/bin/git", "show", f"HEAD:{path}"], cwd=ROOT)  # noqa: S603
        expected = hashlib.sha256(committed).hexdigest()
        original = source / path.relative_to("data/raw")
        if original.is_symlink() or not original.is_file():
            raise RuntimeError(f"Original raw lacks an independent tracked seed: {path}")
        if sha256(ROOT / path) != expected or sha256(original) != expected:
            raise RuntimeError(f"Tracked raw seed differs from HEAD or original raw: {path}")
        hashes[str(path)] = expected
    folder = EVIDENCE / "checkout-raw-seeds"
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "inventory.json", existing)
    save(folder / "hashes.json", hashes)
    destination.rename(folder / "raw")


def stage_raw(source: Path, *, preserve_seeds: bool = False) -> None:
    """Prove APFS clone independence, then stage and verify the complete raw inventory."""
    source = source.absolute()
    destination = ROOT / "data/raw"
    real_source = source.resolve()
    real_destination = destination.resolve()
    if (
        source.is_symlink()
        or real_source.is_relative_to(ROOT)
        or real_destination.is_relative_to(real_source)
        or real_source.is_relative_to(real_destination)
    ):
        raise RuntimeError("Select an independent original raw directory outside this worktree")
    if not real_destination.is_relative_to(ROOT):
        raise RuntimeError("Staged raw destination must remain inside the owned checkout")
    for parent in (destination, *destination.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise RuntimeError(f"Staged raw destination cannot traverse a symlink: {parent}")
    if destination.exists() and preserve_seeds:
        preserve_checkout_seeds(source, destination)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"Refusing to reuse a raw destination: {destination}")
    before = inventory(source)
    folder = EVIDENCE / "raw-staging"
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "source-before.json", before)
    original = source / "predicate_mapping.yaml"
    probe = folder / "clone-proof.yaml"
    subprocess.run(["/bin/cp", "-c", "-p", str(original), str(probe)], check=True)  # noqa: S603
    independent = (original.stat().st_dev, original.stat().st_ino) != (probe.stat().st_dev, probe.stat().st_ino)
    if not independent or sha256(original) != sha256(probe):
        raise RuntimeError("APFS clone did not prove independent inode and identical bytes")
    save(
        folder / "clone-proof.json",
        {"source": str(original), "clone": str(probe), "sha256": sha256(probe), "independent_inode": independent},
    )
    destination.mkdir(parents=True, exist_ok=False)
    subprocess.run(["/bin/cp", "-c", "-p", "-R", str(source) + "/.", str(destination)], check=True)  # noqa: S603
    after = inventory(source)
    copied = inventory(destination)
    save(folder / "source-after.json", after)
    save(folder / "staged-inventory.json", copied)
    if before != after or before.keys() != copied.keys():
        raise RuntimeError("Original raw inputs changed during staging or file membership differs")
    for name, original_state in before.items():
        current = copied[name]
        if current["size"] != original_state["size"] or current["mtime_ns"] != original_state["mtime_ns"]:
            raise RuntimeError(f"Staged bytes/mtime metadata differs: {name}")
        if current["links"] != 1 or (current["device"], current["inode"]) == (
            original_state["device"],
            original_state["inode"],
        ):
            raise RuntimeError(f"Staged file aliases original inode: {name}")
    save(
        folder / "receipt.json",
        {
            "source": str(source),
            "destination": str(destination),
            "files": len(copied),
            "bytes": sum(row["size"] for row in copied.values()),
            "clone_probe": str(folder / "clone-proof.json"),
            "original_inventory_unchanged": True,
            "independent_inodes": True,
        },
    )
    print(f"STAGED {len(copied)} independent raw files", flush=True)


def main() -> int:
    """Plan, stage independent inputs, or launch a persistent owned Python stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("plan")
    stage = sub.add_parser("stage-raw")
    stage.add_argument("source", type=Path)
    stage.add_argument("--preserve-checkout-seeds", action="store_true")
    for name in ("launch", "_run"):
        item = sub.add_parser(name)
        item.add_argument("label")
        item.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "plan":
        env = environment()
        keys = (
            "KG_MICROBE_BIOLINK_MODEL",
            "KG_MICROBE_BIOLINK_PREDICATE_MAP",
            "KG_MICROBE_METPO_JSON",
            "KG_MICROBE_METPO_TEMPLATE_DIR",
            "KG_SEMSQL_BUILD",
            "KG_GO_VERSION_CHECK",
            "PREGO_SHAPES",
            "PREGO_MIN_CONFIDENCE",
            "PREGO_HABITAT_MIN_SCORE",
            "GOLD_APPLY_TAXON_TRIM",
            "METATRAITS_MULTIPROCESSING",
            "METATRAITS_WORKERS",
        )
        selected = {key: env[key] for key in keys}
        print(
            json.dumps(
                {"root": str(ROOT), "python": str(PYTHON), "evidence": str(EVIDENCE), "bindings": selected}, indent=2
            )
        )
        return 0
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError(f"Run only from the owned worktree: {ROOT}")
    if args.action == "stage-raw":
        stage_raw(args.source, preserve_seeds=args.preserve_checkout_seeds)
        return 0
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.label):
        raise RuntimeError("Use a unique safe stage label")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.action == "_run":
        return execute_stage(args.label, command)
    folder = EVIDENCE / "stages" / args.label
    folder.mkdir(parents=True, exist_ok=False)
    env = environment()
    save(
        folder / "plan.json",
        {
            "root": str(ROOT),
            "python": str(PYTHON),
            "command": command,
            "launcher_sha256": sha256(LAUNCHER),
            "environment_sha256": hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest(),
        },
    )
    with (folder / "process.log").open("xb") as log:
        process = subprocess.Popen(  # noqa: S603 - explicit owned Python and launcher; no shell
            [str(PYTHON), "-B", str(LAUNCHER), "_run", args.label, "--", *command],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    save(
        folder / "process.json", {"pid": process.pid, "process_group": process.pid, "log": str(folder / "process.log")}
    )
    print(json.dumps({"label": args.label, "pid": process.pid, "evidence": str(folder)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
