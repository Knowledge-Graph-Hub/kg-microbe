"""
Make ``merged_graph_stats.yaml`` say what produced it, and count every predicate.

KGX's ``generate_graph_stats`` writes only what it computes, and it resolves
predicates through the Biolink toolkit: anything it cannot resolve is recorded
as ``None``. METPO predicates are deliberately not Biolink, so two thirds of
the graph's edges were invisible in the stats file the README points readers
at (#993). The file also carried no merge date, commit, config or input
digests, so a stale copy could not be told from a current one except by
diffing counts against a graph one already trusted (#1013).

After the merge writes the stats, :func:`annotate_graph_stats` adds two
blocks the merge step already knows how to fill:

``provenance``
    when, from which commit (short HEAD, ``-dirty`` if tracked files other than
    the stats file differ), which merge
    config, which edges file, and each source's ``source_fingerprint.json``
    digest or ``no marker``.
``edge_stats.count_by_raw_predicate``
    the predicate column counted directly from the merged edges TSV, no
    resolution, so ``METPO:*`` predicates appear next to ``biolink:*`` and
    the counts sum to the edge total.

Idempotent: both blocks are replaced, never appended, so re-annotating a
file yields the same shape.
"""

import csv
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml

from kg_microbe.utils.transform_fingerprint import FINGERPRINT_FILE, read_fingerprint

STATS_OPERATION = "kgx.graph_operations.summarize_graph.generate_graph_stats"
PROVENANCE_KEY = "provenance"
RAW_PREDICATE_KEY = "count_by_raw_predicate"


def stats_filename_from_config(config: Dict) -> Optional[str]:
    """Return the stats filename the merge config asks KGX to write, if any."""
    for operation in config.get("merged_graph", {}).get("operations", []) or []:
        if operation.get("name") == STATS_OPERATION:
            return (operation.get("args") or {}).get("filename")
    return None


def count_raw_predicates(edges_file: Path) -> Counter:
    """Count the ``predicate`` column of a KGX edges TSV as written, no resolution."""
    counts: Counter = Counter()
    with edges_file.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader, None)
        if header is None:
            return counts
        try:
            column = header.index("predicate")
        except ValueError as exc:
            raise ValueError(f"{edges_file} has no 'predicate' column: {header}") from exc
        for row in reader:
            if len(row) > column:
                counts[row[column] or "(blank)"] += 1
    return counts


def git_commit(repo_root: Path, ignore: Iterable[Path] = ()) -> str:
    """
    Return the short HEAD commit, with ``-dirty`` when tracked files differ.

    ``git describe --dirty`` cannot be used as-is: at annotation time KGX has
    just rewritten the stats file, so the tree is always dirty by exactly
    that file. Paths in ``ignore`` (the stats file) are excluded from the
    dirtiness check; untracked files never count. ``unknown`` when git or
    the checkout is unavailable.
    """
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        head = _git(git, repo_root, "rev-parse", "--short", "HEAD")
        status = _git(git, repo_root, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not head:
        return "unknown"
    ignored = {_relative(Path(path), repo_root) for path in ignore}
    changed = [line[3:] for line in status.splitlines() if line.strip()]
    dirty = any(path not in ignored for path in changed)
    return f"{head}-dirty" if dirty else head


def _git(git: str, repo_root: Path, *args: str) -> str:
    """Run one git command in the checkout and return stripped stdout."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [git, *args], cwd=repo_root, capture_output=True, text=True, check=False, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _relative(path: Path, repo_root: Path) -> str:
    """Render a path the way ``git status --porcelain`` does: repo-relative, POSIX."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def source_markers(config: Dict, repo_root: Path) -> Dict[str, str]:
    """
    Map each merge source to its transform's fingerprint digest.

    The source's input files name the transform directory
    (``data/transformed/<source>/...``); its ``source_fingerprint.json`` is
    the marker the freshness check reads. ``no marker`` is recorded rather
    than omitted, so an unfingerprinted input is visible in the artifact.
    """
    markers: Dict[str, str] = {}
    for name, source in (config.get("merged_graph", {}).get("source", {}) or {}).items():
        filenames = (source.get("input") or {}).get("filename") or []
        dirs = {Path(f).parent for f in filenames}
        digests = []
        for directory in sorted(dirs):
            marker = read_fingerprint(repo_root / directory)
            digests.append(_digest_of(marker) if marker else f"no marker in {directory}")
        markers[name] = "; ".join(digests) if digests else "no input files"
    return markers


def _digest_of(marker: Dict) -> str:
    """Compress a fingerprint marker to the fields that identify a build."""
    parts = []
    for key in ("code", "shared", "data", "upstream", "schema"):
        value = marker.get(key)
        if isinstance(value, dict):
            value = value.get("digest") or value.get("hash") or value
        if value:
            parts.append(f"{key}={str(value)[:20]}")
    return " ".join(parts) if parts else "marker without digests"


def annotate_graph_stats(
    stats_file: Path,
    edges_file: Path,
    yaml_file: Path,
    repo_root: Path,
    now: Optional[datetime] = None,
) -> Dict:
    """
    Add ``provenance`` and ``edge_stats.count_by_raw_predicate`` to a stats file.

    :param stats_file: The YAML KGX wrote.
    :param edges_file: The merged edges TSV (loose, not the archive).
    :param yaml_file: The merge config that produced both.
    :param repo_root: Checkout root, for ``git describe`` and the markers.
    :param now: Timestamp to record; defaults to UTC now.
    :return: The annotated stats dict, as written.
    :raises ValueError: If the raw predicate total disagrees with KGX's
        ``total_edges`` -- the two counted different files.
    """
    with stats_file.open(encoding="utf-8") as handle:
        stats = yaml.safe_load(handle) or {}
    with Path(yaml_file).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    raw = count_raw_predicates(edges_file)
    raw_total = sum(raw.values())
    kgx_total = (stats.get("edge_stats") or {}).get("total_edges")
    if kgx_total is not None and kgx_total != raw_total:
        raise ValueError(
            f"raw predicate count {raw_total:,} != KGX total_edges {kgx_total:,}; "
            f"{edges_file} is not the file the stats describe"
        )

    edge_stats = stats.setdefault("edge_stats", {})
    edge_stats[RAW_PREDICATE_KEY] = {predicate: raw[predicate] for predicate in sorted(raw)}

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    stats[PROVENANCE_KEY] = {
        "generated_at": stamp.isoformat(),
        "commit": git_commit(repo_root, ignore=(stats_file,)),
        "merge_config": str(yaml_file),
        "edges_file": str(edges_file),
        "python": sys.version.split()[0],
        "kgx": _kgx_version(),
        "sources": source_markers(config, repo_root),
        "note": (
            f"{RAW_PREDICATE_KEY} is the predicate column counted as written; KGX's "
            "count_by_predicates resolves through Biolink and records METPO and other "
            "non-Biolink predicates as None (#993). provenance is written by kg merge (#1013)."
        ),
    }

    with stats_file.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(stats, handle, sort_keys=True, allow_unicode=True)
    return stats


def _kgx_version() -> str:
    """Return the installed KGX version, or ``unknown``."""
    try:
        import kgx  # noqa: PLC0415 - optional at import time

        return str(getattr(kgx, "__version__", "unknown"))
    except ImportError:
        return "unknown"


__all__ = [
    "FINGERPRINT_FILE",
    "annotate_graph_stats",
    "count_raw_predicates",
    "git_commit",
    "source_markers",
    "stats_filename_from_config",
]
