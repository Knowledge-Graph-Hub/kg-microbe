#!/usr/bin/env python3
"""
2026-11-16: run one real production CLI dependency unit in an exclusive M5 stage.

Plan first. Copy only explicitly named retained raw files to the task checkout's
canonical raw directory, preserving existing equal bytes and refusing conflicts.
Run the ordinary CLI with freshness on, one process, private caches and no HTTP
route. Each unit retains independent outputs/logs; prior units are never replaced.
This launcher does not declare source finalization or release success from exit
status: its receipt inventories actual persisted files for separate inspection.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGES = ROOT / "data/validation-bactotraits-130"


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
            require(not target.is_symlink() and identity(target) == expected, f"Existing task input differs: {target}")
        originals.append({"source": str(source), "target": str(target), **expected})
    interpreter = str(Path(sys.executable).absolute())
    command = [
        interpreter,
        "-B",
        "-m",
        "kg_microbe.run",
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
    return {
        "stage": str(stage),
        "source": args.source,
        "command": command,
        "environment": environment,
        "processes": 1,
        "originals": originals,
        "implementation_and_policy_inputs": pins,
        "task_raw_before": {
            path.name: identity(safe_path(path)) for path in (ROOT / "data/raw").iterdir() if path.is_file()
        },
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
    for record in plan["originals"]:
        source, target = Path(record["source"]), Path(record["target"])
        expected = {key: record[key] for key in ("bytes", "sha256")}
        require(identity(source) == expected, "Original changed before staging")
        if not target.exists():
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
        require(identity(source) == identity(target) == expected, "Staged input readback differs")
    environment = {**os.environ, **plan["environment"]}
    started = datetime.now(timezone.utc).isoformat()
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
    for record in plan["originals"]:
        require(
            identity(Path(record["source"])) == {key: record[key] for key in ("bytes", "sha256")},
            "Original retained input changed during execution",
        )
    for name, expected in plan["implementation_and_policy_inputs"].items():
        require(identity(ROOT / name) == expected, "Implementation or policy changed during execution")
    artifacts = {str(path.relative_to(stage)): identity(path) for path in stage.rglob("*") if path.is_file()}
    raw_after = {path.name: identity(safe_path(path)) for path in (ROOT / "data/raw").iterdir() if path.is_file()}
    receipt = {
        **plan,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": code,
        "artifacts": artifacts,
        "task_raw_after": raw_after,
        "task_raw_new_files": sorted(raw_after.keys() - plan["task_raw_before"].keys()),
        "task_raw_changed_files": sorted(
            name
            for name in raw_after.keys() & plan["task_raw_before"].keys()
            if raw_after[name] != plan["task_raw_before"][name]
        ),
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
    args = parser.parse_args()
    plan = prepare(args)
    if args.plan:
        print(json.dumps({"action": "plan", "writes": 0, **plan}, indent=2, sort_keys=True))
    else:
        raise SystemExit(run(plan))


if __name__ == "__main__":
    main()
