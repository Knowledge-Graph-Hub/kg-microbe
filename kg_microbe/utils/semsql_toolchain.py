"""
Record the toolchain that built each SemSQL database, and compare it when the database is reused (#1524).

``semsql make`` runs SemSQL, ``rdftab`` and ``relation-graph`` from ``PATH`` and
the pinned ROBOT through a shim. Before this module, a build recorded none of
them, so two databases from the same ontology release could not be told apart by
toolchain: a difference showed up only as a failed content check. GO's restriction
policy refuses a quarantined restriction once ``entailed_edge`` supports it, and
``entailed_edge`` comes from relation-graph, so its version changes outcomes for
the same GO release.

Each successful build writes ``<db>.toolchain.json`` beside the database. Only
versions and digests are compared: paths differ between machines and Java is
recorded for provenance only.
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


def _which(name: str, env: Mapping[str, str]) -> Optional[Path]:
    """Resolve a tool the way ``semsql make`` will find it, following links to the real file."""
    if env.get("PATH") == os.environ.get("PATH"):
        found = shutil.which(name)
    else:
        found = shutil.which(name, path=env.get("PATH"))
    return Path(found).resolve() if found else None


def _semsql(env: Mapping[str, str]) -> Optional[Dict[str, Optional[str]]]:
    """Describe the ``semsql`` on PATH by the package version its own interpreter reports."""
    path = _which("semsql", env)
    if path is None:
        return None
    version = None
    try:
        first = path.read_bytes().split(b"\n", 1)[0].decode("utf-8", "replace")
        interpreter = first[2:].strip().split()[0] if first.startswith("#!") else None
        if interpreter:
            result = subprocess.run(  # noqa: S603 - the script's own interpreter, a fixed query
                [interpreter, "-c", "import importlib.metadata as m; print(m.version('semsql'))"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            version = (getattr(result, "stdout", None) or "").strip() or None
    except (OSError, subprocess.SubprocessError, IndexError):
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
    covers the reasoner (Whelk) it bundles.
    """
    path = _which("relation-graph", env)
    if path is None:
        return None
    lib = path.parent.parent / "lib"
    jars = sorted(lib.glob("*.jar")) if lib.is_dir() else []
    version = next((m.group(1) for jar in jars if (m := _RELATION_GRAPH_JAR.fullmatch(jar.name))), None)
    if jars:
        listing = "\n".join(f"{jar.name} {_sha256(jar)}" for jar in jars)
        digest = hashlib.sha256(listing.encode("utf-8")).hexdigest()
    else:
        digest = _sha256(path)
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

    :param raw_dir: The raw directory the build runs in, which holds the pinned ``robot.jar``.
    :param env: The environment the build gets, with the pinned ROBOT shim on ``PATH``.
    :return: The record to write beside a database this toolchain builds.
    """
    robot_jar = Path(raw_dir) / "robot.jar"
    return {
        "version": RECORD_VERSION,
        "semsql": _semsql(env),
        "rdftab": _rdftab(env),
        "relation_graph": _relation_graph(env),
        "robot_jar_sha256": _sha256(robot_jar) if robot_jar.is_file() else None,
        "java": _java(env),
    }


def missing_tools(toolchain: dict) -> List[str]:
    """Name the build tools this toolchain lacks, so no build or comparison can succeed."""
    names = {"semsql": "semsql", "rdftab": "rdftab", "relation_graph": "relation-graph"}
    missing = [label for key, label in names.items() if not toolchain.get(key)]
    if not toolchain.get("robot_jar_sha256"):
        missing.append("the pinned robot.jar")
    return missing


def _comparable(part):
    """Drop machine-specific paths from one recorded part."""
    if isinstance(part, dict):
        return {key: value for key, value in part.items() if key != "path"}
    return part


def differences(recorded: Optional[dict], current: dict) -> List[str]:
    """
    Say how a database's recorded toolchain differs from the current one; empty when they match.

    :param recorded: The record written beside the database, or None when it has none.
    :param current: :func:`current_toolchain` for this machine.
    """
    if not recorded:
        return ["it has no toolchain record (it predates #1524 or was built elsewhere)"]
    if recorded.get("version") != RECORD_VERSION:
        return [f"its toolchain record has version {recorded.get('version')!r}, not {RECORD_VERSION}"]
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
    """Write the toolchain record of a database that was just built, atomically."""
    with atomic_write(record_path(db_path)) as stream:
        stream.write(json.dumps(toolchain, indent=2, sort_keys=True) + "\n")


def discard_record(db_path) -> None:
    """Remove a record that no longer describes the database beside it."""
    try:
        record_path(db_path).unlink()
    except FileNotFoundError:
        pass
