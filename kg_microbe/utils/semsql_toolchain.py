"""
Record the toolchain that built each SemSQL database, and compare it when the database is reused (#1524).

``semsql make`` runs SemSQL, ``rdftab`` and ``relation-graph`` from ``PATH`` and
the pinned ROBOT through a shim. Before this module, a build recorded none of
them, so two databases from the same ontology release could not be told apart by
toolchain: a difference showed up only as a failed content check. GO's restriction
policy refuses a quarantined restriction once ``entailed_edge`` supports it, and
``entailed_edge`` comes from relation-graph, so its version changes outcomes for
the same GO release.

Each successful build writes ``<db>.toolchain.json`` beside the database. It
names the database file it describes (size, modification time, inode), so a DB
copied in, replaced or restored from ``.prev`` is not vouched for by a record
written for another file. Only versions and digests are compared: paths differ
between machines and Java is recorded for provenance only. A tool whose version
or digest cannot be read cannot vouch for anything.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from kg_microbe.utils.atomic_io import atomic_write

RECORD_SUFFIX = ".toolchain.json"
RECORD_VERSION = 1
#: The parts whose versions or digests decide whether two builds are comparable.
COMPARED = ("semsql", "rdftab", "relation_graph", "robot_jar_sha256")
_RELATION_GRAPH_JAR = re.compile(r"org\.geneontology\.relation-graph-(\d[\w.\-]*)\.jar")


def _sha256(path: Path) -> Optional[str]:
    """Hash a file's complete bytes; None when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _which(name: str, env: Mapping[str, str], *, resolve: bool = True) -> Optional[Path]:
    """
    Find a tool the way ``semsql make`` will, following links to the real file unless asked not to.

    An interpreter must not be resolved: a virtualenv's ``python3`` is a link to the
    base interpreter, which does not see the virtualenv's packages.
    """
    if env.get("PATH") == os.environ.get("PATH"):
        found = shutil.which(name)
    else:
        found = shutil.which(name, path=env.get("PATH"))
    if not found:
        return None
    if not resolve:
        return Path(found)
    try:
        return Path(found).resolve()
    except (OSError, RuntimeError):  # a symlink loop
        return None


_PIP_TRAMPOLINE = re.compile(r"exec' \"([^\"]+)\" \"\$0\"")


def _interpreter(script: Path, env: Mapping[str, str]) -> Optional[str]:
    """
    Return the Python a console script runs, from its shebang.

    Handles an absolute interpreter, ``#!/usr/bin/env python3`` (conda uses it for
    long prefixes) and pip's ``/bin/sh`` trampoline, which pip writes when the
    interpreter path is long or contains spaces.
    """
    head = script.read_bytes()[:4096].decode("utf-8", "replace").splitlines()
    if not head or not head[0].startswith("#!"):
        return None
    words = head[0][2:].split()
    if not words:
        return None
    if Path(words[0]).name == "env":
        program = next((word for word in words[1:] if not word.startswith("-")), None)
        found = _which(program, env, resolve=False) if program else None
        return str(found) if found else None
    if Path(words[0]).name in ("sh", "bash"):
        match = next((m for line in head[1:4] if (m := _PIP_TRAMPOLINE.search(line))), None)
        return match.group(1) if match else None
    return words[0]


def _semsql(env: Mapping[str, str]) -> Optional[Dict[str, Optional[str]]]:
    """Describe the ``semsql`` on PATH by the package version its own interpreter reports."""
    path = _which("semsql", env)
    if path is None:
        return None
    version = None
    try:
        interpreter = _interpreter(path, env)
        if interpreter:
            result = subprocess.run(  # noqa: S603 - the script's own interpreter, a fixed query
                [interpreter, "-c", "import importlib.metadata as m; print(m.version('semsql'))"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            version = (getattr(result, "stdout", None) or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        version = None
    return {"path": str(path), "version": version}


def _rdftab(env: Mapping[str, str]) -> Optional[Dict[str, str]]:
    """Describe the ``rdftab`` binary on PATH by its digest; it reports no version."""
    path = _which("rdftab", env)
    return None if path is None else {"path": str(path), "sha256": _sha256(path)}


def _relation_graph(env: Mapping[str, str]) -> Optional[Dict[str, Optional[str]]]:
    """
    Describe the ``relation-graph`` on PATH by its version and a digest of the jars it runs.

    The release is a launcher in ``bin/`` beside the jars in ``lib/``; the version is
    in ``org.geneontology.relation-graph-<version>.jar``, and the jar digest also
    covers the reasoner (Whelk) it bundles. Any other layout (a wrapper script, a
    shared ``lib/`` without that jar) leaves the version and digest unknown, so the
    install cannot vouch for a database.
    """
    path = _which("relation-graph", env)
    if path is None:
        return None
    lib = path.parent.parent / "lib"
    jars = sorted(lib.glob("*.jar")) if lib.is_dir() else []
    version = next((m.group(1) for jar in jars if (m := _RELATION_GRAPH_JAR.fullmatch(jar.name))), None)
    digest = None
    if version is not None:
        hashes = [_sha256(jar) for jar in jars]
        if None not in hashes:
            listing = "\n".join(f"{jar.name} {sha}" for jar, sha in zip(jars, hashes, strict=True))
            digest = hashlib.sha256(listing.encode("utf-8")).hexdigest()
    return {"path": str(path), "version": version, "sha256": digest}


def _java(env: Mapping[str, str]) -> Optional[str]:
    """Return the first line of ``java -version``, for provenance."""
    java = _which("java", env)
    if java is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - a fixed query
            [java, "-version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (getattr(result, "stderr", None) or getattr(result, "stdout", None) or "").strip().splitlines()
    return lines[0] if lines else None


def current_toolchain(raw_dir: Path, env: Mapping[str, str]) -> dict:
    """
    Describe the toolchain a ``semsql make`` started with ``env`` in ``raw_dir`` would run.

    :param raw_dir: The raw directory the build runs in, which holds the pinned ROBOT.
    :param env: The environment the build gets.
    :return: The record to write beside a database this toolchain builds. The pinned
        ``robot.jar`` counts only beside its ``robot`` wrapper, which is what puts it on
        ``PATH`` for SemSQL (``robot_utils.pinned_robot_on_path``).
    """
    robot_jar = Path(raw_dir) / "robot.jar"
    pinned = robot_jar.is_file() and (Path(raw_dir) / "robot").is_file()
    return {
        "version": RECORD_VERSION,
        "semsql": _semsql(env),
        "rdftab": _rdftab(env),
        "relation_graph": _relation_graph(env),
        "robot_jar_sha256": _sha256(robot_jar) if pinned else None,
        "java": _java(env),
    }


def missing_tools(toolchain: dict) -> List[str]:
    """Name the build tools this toolchain lacks or cannot identify; none of them can vouch for a DB."""
    missing = []
    for key, label, field in (
        ("semsql", "semsql", "version"),
        ("rdftab", "rdftab", "sha256"),
        ("relation_graph", "relation-graph", "version"),
    ):
        part = toolchain.get(key)
        if not part:
            missing.append(label)
        elif not part.get(field) or (key == "relation_graph" and not part.get("sha256")):
            missing.append(f"{label} (found, but its {field} cannot be read)")
    if not toolchain.get("robot_jar_sha256"):
        missing.append("the pinned robot and robot.jar")
    return missing


def _comparable(part):
    """Drop machine-specific paths from one recorded part."""
    if isinstance(part, dict):
        return {key: value for key, value in part.items() if key != "path"}
    return part


def database_identity(db_path) -> Optional[Dict[str, int]]:
    """Identify the database file a record describes: size, modification time and inode."""
    try:
        status = os.stat(db_path)
    except OSError:
        return None
    return {"size": status.st_size, "mtime_ns": status.st_mtime_ns, "inode": status.st_ino}


def differences(recorded: Optional[dict], current: dict, db_path=None) -> List[str]:
    """
    Say why a database's record cannot vouch for it under the current toolchain; empty when it can.

    :param recorded: The record written beside the database, or None when it has none.
    :param current: :func:`current_toolchain` for this machine.
    :param db_path: The database the record sits beside; when given, the record must
        name this very file.
    """
    if not recorded:
        return ["it has no toolchain record (it predates #1524 or was built elsewhere)"]
    if recorded.get("version") != RECORD_VERSION:
        return [f"its toolchain record has version {recorded.get('version')!r}, not {RECORD_VERSION}"]
    if db_path is not None and recorded.get("database") != database_identity(db_path):
        return ["its toolchain record describes another file (the DB was replaced, copied in or restored)"]
    unknown = missing_tools(current)
    if unknown:
        return [f"this machine cannot identify {', '.join(unknown)}"]
    return [
        f"{key}: recorded {_comparable(recorded.get(key))}, now {_comparable(current.get(key))}"
        for key in COMPARED
        if _comparable(recorded.get(key)) != _comparable(current.get(key))
    ]


def record_path(db_path) -> Path:
    """Return where the toolchain record of ``db_path`` lives."""
    return Path(str(db_path) + RECORD_SUFFIX)


def read_record(db_path) -> Optional[dict]:
    """Read a database's toolchain record; None when it is missing or unreadable."""
    try:
        record = json.loads(record_path(db_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def write_record(db_path, toolchain: dict) -> None:
    """Write the toolchain record of a database that was just built, naming that file, atomically."""
    record = {**toolchain, "database": database_identity(db_path)}
    with atomic_write(record_path(db_path)) as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")


def discard_record(db_path) -> None:
    """Remove a record that no longer describes the database beside it."""
    try:
        record_path(db_path).unlink()
    except FileNotFoundError:
        pass
