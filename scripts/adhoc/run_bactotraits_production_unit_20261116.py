#!/usr/bin/env python3
"""
2026-11-16: run one real production CLI dependency unit in an exclusive M5 stage.

Plan first. Copy only explicitly named retained raw files to the task checkout's
canonical raw directory, preserving existing equal bytes and refusing conflicts.
Run the ordinary CLI with freshness on, one process, private caches and no HTTP
route. Each unit retains independent outputs/logs; prior units are never replaced.
This launcher does not declare source finalization or release success from exit
status: its receipt inventories actual persisted files for separate inspection.

2026-11-19, #1870/#1874/#1875: v2 receipts bind the actual isolated CLI import,
publish verified retained inputs without clobbering competitors, and enforce
explicit --allow-raw-write paths for producer additions, modifications or deletions.
Failures preserve private evidence; historical receipts are not reinterpreted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import runpy
import shutil
import socket
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGES = ROOT / "data/validation-bactotraits-130"
PROFILE = "bactotraits-production-unit-v2"


def identity(path):
    """Stream a complete named file without loading database-scale bytes into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def require(condition, message):
    """Fail closed on changed inputs or nonexclusive placement."""
    if not condition:
        raise ValueError(message)


def safe_path(path):
    """Reject symlinked ancestors before staging or selecting a private output root."""
    path = path.absolute()
    require(".." not in path.parts, "Parent traversal is not a staging path")
    require(all(not ancestor.is_symlink() for ancestor in (path, *path.parents)), "Symlinked staging/input path")
    return path


def write_new(path, value):
    """Retain a new private JSON record without replacing previous evidence."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def tree_inventory(directory):
    """Record every nested entry, including unsafe links, without following directory links."""
    result = {}

    def visit(parent):
        for path in sorted(parent.iterdir()):
            name = path.relative_to(directory).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                result[name] = {"kind": "symlink", "target": os.readlink(path)}
            elif stat.S_ISDIR(mode):
                result[name] = {"kind": "directory"}
                visit(path)
            elif stat.S_ISREG(mode):
                result[name] = identity(path)
            else:
                result[name] = {"kind": "special", "mode": stat.S_IFMT(mode)}

    visit(directory)
    return result


def allowed_raw_paths(names):
    """Accept exact relative file paths, never patterns, traversal or existing symlinks."""
    for name in names:
        require(
            bool(name)
            and not any(character in name for character in "*?[]\\")
            and all(part not in {"", ".", ".."} for part in name.split("/")),
            "Allowed raw write must be an exact relative file path without globs or traversal",
        )
        path = safe_path(ROOT / "data/raw" / name)
        require(not path.exists() or path.is_file(), "Allowed raw write must identify a regular file")
    return sorted(set(names))


def raw_side_effects(before, after, allowed):
    """Account for all recursive changes; only declared files and their directories may change."""
    added = sorted(after.keys() - before.keys())
    deleted = sorted(before.keys() - after.keys())
    changed = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
    parents = {parent.as_posix() for name in allowed for parent in Path(name).parents if parent != Path(".")}
    unexpected = []
    for name in (*added, *changed, *deleted):
        kinds = {entries[name].get("kind", "file") for entries in (before, after) if name in entries}
        permitted = (kinds == {"file"} and name in allowed) or (kinds == {"directory"} and name in parents)
        if not permitted:
            unexpected.append(name)
    return {"added": added, "changed": changed, "deleted": deleted, "unexpected": sorted(unexpected)}


def run_bound_cli(origin_path, arguments):
    """Verify the bound package and CLI origins before running the ordinary module entry point."""
    require(sys.flags.isolated == 1, "Bound CLI bootstrap requires Python isolated mode")
    sys.path.insert(0, str(ROOT))
    package_path = safe_path(ROOT / "kg_microbe/__init__.py")
    cli_path = safe_path(ROOT / "kg_microbe/run.py")
    package_spec = importlib.util.find_spec("kg_microbe")
    require(
        package_spec is not None
        and package_spec.origin == str(package_path)
        and list(package_spec.submodule_search_locations or []) == [str(package_path.parent)],
        "kg_microbe package origin is outside the bound checkout",
    )
    package = importlib.import_module("kg_microbe")
    require(
        package.__file__ == str(package_path) and list(package.__path__) == [str(package_path.parent)],
        "Imported kg_microbe package origin is outside the bound checkout",
    )
    cli_spec = importlib.util.find_spec("kg_microbe.run")
    require(cli_spec is not None and cli_spec.origin == str(cli_path), "CLI origin is outside the bound checkout")
    write_new(
        safe_path(origin_path),
        {
            "profile": PROFILE,
            "root": str(ROOT),
            "package_origin": str(package_path),
            "package_identity": identity(package_path),
            "cli_origin": str(cli_path),
            "cli_identity": identity(cli_path),
            "isolated": sys.flags.isolated,
            "arguments": arguments,
        },
    )
    sys.argv = [str(cli_path), *arguments]
    runpy.run_module("kg_microbe.run", run_name="__main__", alter_sys=True)


def stage_input(record, stage):
    """Verify a private exclusive copy, then publish with atomic no-clobber hard-link creation."""
    source, target = safe_path(Path(record["source"])), safe_path(Path(record["target"]))
    expected = {key: record[key] for key in ("bytes", "sha256")}
    require(source.is_file() and identity(source) == expected, "Original changed before staging")
    if not target.exists():
        private = stage / "input-staging"
        private.mkdir(mode=0o700, exist_ok=True)
        temporary = private / target.name
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        require(identity(source) == identity(temporary) == expected, "Private input readback differs")
        safe_path(target)
        # Same-filesystem publication is required. EXDEV fails safely; never fall back to overwrite/copy.
        os.link(temporary, target)
        temporary.unlink()
    require(target.is_file() and identity(source) == identity(safe_path(target)) == expected, "Staged input differs")


def prepare(args):
    """Inspect named retained bytes and the exact CLI/environment before any mutation."""
    require(re.fullmatch(r"[a-z0-9-]+", args.unit) is not None, "Invalid unit name")
    stage = safe_path(STAGES / args.unit)
    require(not stage.exists(), "Unit already exists; preserve it and select another name")
    originals = []
    for name in args.raw_input:
        require(Path(name).name == name and name not in {".", ".."}, "Raw input must be one basename")
        source, target = safe_path(args.input_root / "data/raw" / name), safe_path(ROOT / "data/raw" / name)
        require(source.is_file() and not source.is_symlink(), f"Retained regular input unavailable: {source}")
        expected = identity(source)
        if target.exists():
            require(target.is_file() and identity(target) == expected, f"Existing task input differs: {target}")
        originals.append({"source": str(source), "target": str(target), **expected})
    interpreter = str(Path(sys.executable).absolute())
    command = [
        interpreter,
        "-I",
        "-B",
        str(Path(__file__).absolute()),
        "--_run-bound-cli",
        str(stage / "cli-origin.json"),
        "--",
        "transform",
        "-i",
        str(ROOT / "data/raw"),
        "-o",
        str(stage / "transformed"),
        "-s",
        args.source,
        "--no-show-status",
    ]
    cache = stage / "cache/pystow"
    environment = {
        "PYSTOW_HOME": str(cache),
        "PYSTOW_CONFIG_HOME": str(stage / "cache/pystow-config"),
        "PYSTOW_USE_APPDIRS": "false",
        "OAKLIB_HOME": str(cache / "oaklib"),
        "BIOREGISTRY_HOME": str(cache / "bioregistry"),
        "TMPDIR": str(stage / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "KG_SEMSQL_BUILD": "on",
        "KG_GO_VERSION_CHECK": "strict",
        "KG_NCBITAXON_VERSION_CHECK": "strict",
        "KG_CHEBI_VERSION_CHECK": "strict",
        "KG_MICROBE_METPO_TEMPLATE_DIR": str(ROOT / "data/raw"),
        "KG_MICROBE_METPO_JSON": str(ROOT / "data/raw/metpo.json"),
        "KG_MICROBE_BIOLINK_MODEL": str(ROOT / "data/raw/biolink-model.yaml"),
        "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(ROOT / "data/raw/predicate_mapping.yaml"),
        "METATRAITS_MULTIPROCESSING": "false",
        "METATRAITS_WORKERS": "1",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
        "ROBOT_JAVA_ARGS": "-Xmx12g -XX:+UseG1GC -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 "
        "-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9 -Dhttp.nonProxyHosts= "
        "-DsocksProxyHost=127.0.0.1 -DsocksProxyPort=9",
    }
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        environment[name.lower()] = environment[name]
    environment["_JAVA_OPTIONS"] = (
        "-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 -Dhttps.proxyHost=127.0.0.1 "
        "-Dhttps.proxyPort=9 -Dhttp.nonProxyHosts= -DsocksProxyHost=127.0.0.1 -DsocksProxyPort=9"
    )
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    pins = {
        str(path.relative_to(ROOT)): identity(path)
        for directory, pattern in ((ROOT / "kg_microbe", "*.py"), (ROOT / "mappings", "*"))
        for path in directory.rglob(pattern)
        if path.is_file() and "tmp" not in path.relative_to(ROOT).parts
    }
    declarations = [
        node.value
        for node in ast.parse((ROOT / "kg_microbe/utils/transform_fingerprint.py").read_bytes()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SHARED_DATA_INPUTS" for target in node.targets)
    ]
    require(len(declarations) == 1, "Ambiguous shared finalization input declaration")
    for name in (*ast.literal_eval(declarations[0]), "kg_microbe/transform_utils/custom_curies.yaml"):
        pins[name] = identity(safe_path(ROOT / name))
    pins[str(Path(__file__).relative_to(ROOT))] = identity(Path(__file__))
    for name in ("pyproject.toml", "poetry.lock"):
        pins[name] = identity(ROOT / name)
    for name in ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml"):
        path = ROOT / "data/raw" / name
        pins[str(path.relative_to(ROOT))] = identity(path)
    git = shutil.which("git")
    require(git is not None, "Git is unavailable")
    revision = subprocess.check_output([git, "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()  # noqa: S603
    raw_before = tree_inventory(safe_path(ROOT / "data/raw"))
    require(
        all(entry.get("kind", "file") in {"file", "directory"} for entry in raw_before.values()),
        "Raw tree contains a symlink or nonregular entry",
    )
    return {
        "profile": PROFILE,
        "stage": str(stage),
        "source": args.source,
        "command": command,
        "cli_origin_required": True,
        "environment": environment,
        "processes": 1,
        "originals": originals,
        "implementation_and_policy_inputs": pins,
        "task_raw_before": raw_before,
        "allowed_raw_writes": allowed_raw_paths(getattr(args, "allow_raw_write", [])),
        "git_revision": revision,
        "python": sys.version,
        "interpreter": {"executable": interpreter, "resolved": str(Path(interpreter).resolve())},
        "packages": {
            name: importlib.metadata.version(name) for name in ("kgx", "oaklib", "pandas", "PyYAML", "semsql")
        },
        "free_disk_bytes": shutil.disk_usage(ROOT).free,
    }


def run(plan):
    """Stage bounded inputs, execute one CLI child and inventory its actual side effects."""
    os.umask(0o077)
    stage = Path(plan["stage"])
    STAGES.mkdir(exist_ok=True, mode=0o700)
    stage.mkdir(mode=0o700)
    (stage / "tmp").mkdir(mode=0o700)
    write_new(stage / "plan.json", plan)
    started = datetime.now(timezone.utc).isoformat()
    before_child = plan["task_raw_before"]
    phase = "preflight"
    try:
        allowed = allowed_raw_paths(plan.get("allowed_raw_writes", []))
        require(tree_inventory(safe_path(ROOT / "data/raw")) == before_child, "Raw tree changed after planning")
        require(
            all(entry.get("kind", "file") in {"file", "directory"} for entry in before_child.values()),
            "Raw tree contains a symlink or nonregular entry",
        )
        phase = "input-staging"
        for record in plan["originals"]:
            stage_input(record, stage)
        staged = tree_inventory(ROOT / "data/raw")
        staged_paths = [
            Path(record["target"]).relative_to(ROOT / "data/raw").as_posix() for record in plan["originals"]
        ]
        staging_effects = raw_side_effects(before_child, staged, staged_paths)
        require(not staging_effects["unexpected"], "Raw tree changed unexpectedly during input staging")
        before_child = staged
        phase = "child"
        environment = {**os.environ, **plan["environment"]}
        with (stage / "stdout.log").open("x") as stdout, (stage / "stderr.log").open("x") as stderr:
            child = subprocess.Popen(plan["command"], cwd=ROOT, env=environment, stdout=stdout, stderr=stderr)  # noqa: S603
            write_new(
                stage / "process.json",
                {
                    "pid": child.pid,
                    "parent_pid": os.getpid(),
                    "host": socket.gethostname(),
                    "started_at": started,
                    "command": plan["command"],
                },
            )
            code = child.wait()
        phase = "postflight"
        if plan.get("cli_origin_required"):
            origin_path = stage / "cli-origin.json"
            require(origin_path.is_file(), "Bound CLI origin evidence is missing")
            origin = json.loads(safe_path(origin_path).read_text())
            require(
                origin["root"] == str(ROOT)
                and origin["isolated"] == 1
                and origin["package_origin"] == str(ROOT / "kg_microbe/__init__.py")
                and origin["cli_origin"] == str(ROOT / "kg_microbe/run.py")
                and origin["package_identity"] == plan["implementation_and_policy_inputs"]["kg_microbe/__init__.py"]
                and origin["cli_identity"] == plan["implementation_and_policy_inputs"]["kg_microbe/run.py"],
                "Bound CLI origin evidence differs from the planned checkout",
            )
        raw_after = tree_inventory(safe_path(ROOT / "data/raw"))
        effects = raw_side_effects(before_child, raw_after, allowed)
        require(not effects["unexpected"], "Undeclared or unsafe raw side effects: " + ", ".join(effects["unexpected"]))
        for record in plan["originals"]:
            require(
                identity(safe_path(Path(record["source"]))) == {key: record[key] for key in ("bytes", "sha256")},
                "Original retained input changed during execution",
            )
        for name, expected in plan["implementation_and_policy_inputs"].items():
            require(identity(safe_path(ROOT / name)) == expected, "Implementation or policy changed during execution")
    except BaseException as error:
        failure = {
            **plan,
            "profile": PROFILE,
            "status": "FAILED",
            "phase": phase,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "error": str(error),
            "task_raw_before_child": before_child,
            "published_release_verified": False,
        }
        try:
            failure["task_raw_after"] = tree_inventory(safe_path(ROOT / "data/raw"))
            failure["raw_side_effects"] = raw_side_effects(
                before_child, failure["task_raw_after"], plan.get("allowed_raw_writes", [])
            )
            failure["artifacts"] = tree_inventory(stage)
        except (OSError, ValueError) as inspection_error:
            failure["inspection_error"] = str(inspection_error)
        write_new(stage / "failure.json", failure)
        raise
    artifacts = tree_inventory(stage)
    total_effects = raw_side_effects(plan["task_raw_before"], raw_after, allowed)
    receipt = {
        **plan,
        "profile": PROFILE,
        "status": "COMPLETED" if code == 0 else "CHILD_FAILED",
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": code,
        "artifacts": artifacts,
        "task_raw_after": raw_after,
        "task_raw_before_child": before_child,
        "raw_side_effects": effects,
        "task_raw_new_files": total_effects["added"],
        "task_raw_changed_files": total_effects["changed"],
        "task_raw_deleted_files": total_effects["deleted"],
        "published_release_verified": False,
        "scope": "One actual CLI unit; inspect persisted graph/audits/finalization before accepting it.",
    }
    write_new(stage / "receipt.json", receipt)
    print(json.dumps({"stage": str(stage), "returncode": code, "receipt": str(stage / "receipt.json")}))
    return code


def main():
    """Separate the explicit read-only plan from a single real producer unit."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--source", choices=("ro", "ontologies", "bacdive", "bactotraits"), required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--raw-input", action="append", required=True)
    parser.add_argument(
        "--allow-raw-write",
        action="append",
        default=[],
        metavar="PATH",
        help="Allow this exact raw-relative file to be added, modified or deleted by the child; repeat as needed",
    )
    args = parser.parse_args()
    plan = prepare(args)
    if args.plan:
        print(json.dumps({"action": "plan", "writes": 0, **plan}, indent=2, sort_keys=True))
    else:
        raise SystemExit(run(plan))


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--_run-bound-cli" and sys.argv[3] == "--":
        run_bound_cli(Path(sys.argv[2]), sys.argv[4:])
    else:
        main()
