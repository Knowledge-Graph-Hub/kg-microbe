#!/usr/bin/env python3
"""Freshness check for KG-Microbe transform / merge outputs vs origin/master.

For every transform directory under kg_microbe/transform_utils/<source>/,
compare:
  - the latest commit that touched the transform code on origin/master, vs
  - the mtime of the transform's data/transformed/<source>/{nodes,edges}.tsv output.

Also report:
  - whether the local working tree has changes to the transform code that
    diverge from origin/master (LOCAL_CHANGES).
  - merge-stage freshness: merge.yaml + merge_utils/ vs data/merged/*.

Per-source status codes:
  FRESH             — output mtime > latest code commit AND no local changes
  STALE_VS_CODE     — output mtime < latest code commit on origin/master
  LOCAL_CHANGES     — working tree diverges from origin/master for this dir
                     (in that case, "current relative to master" is not
                     meaningful; still report code-commit-vs-output for info)
  MISSING_OUTPUT    — no nodes.tsv/edges.tsv on disk
  NO_CODE           — code dir exists but no matching <source>.py (skip)

Merge status codes:
  FRESH           — merged output newer than every transform output and
                    newer than merge.yaml and newer than merge_utils/
  STALE_VS_INPUTS — merged output older than one or more transform outputs
  STALE_VS_CODE   — merged output older than merge_utils/ code on origin/master
  STALE_VS_YAML   — merged output older than merge.yaml
  MISSING_OUTPUT  — no merged-kg_edges.tsv on disk

Exit codes:
  0 — all FRESH
  1 — some STALE / MISSING (real problem)
  2 — invocation error (no origin/master, script error)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict, field
import re
from pathlib import Path
from typing import Iterable, Optional

REPO = Path(__file__).resolve().parents[3]
TRANSFORM_ROOT = REPO / "kg_microbe" / "transform_utils"


def _declared_data_inputs(source: str) -> tuple:
    """
    Repo-relative curation files a transform reads, from its ``DATA_INPUTS``.

    Read by importing the transform classes rather than by keeping a second
    list here: a hard-coded table in this skill would drift from the code it
    describes, and the whole point of #812 is that a stale declaration is
    indistinguishable from a fresh one. Import failure degrades to "no declared
    inputs" so the skill still runs in an environment without kg_microbe
    importable.

    :param source: Transform source name.
    :return: Tuple of repo-relative paths, empty when none are declared.
    """
    try:
        from kg_microbe.transform import DATA_SOURCES  # noqa: PLC0415 - optional, see docstring
    except Exception:
        return ()
    cls = DATA_SOURCES.get(source)
    return tuple(getattr(cls, "DATA_INPUTS", ()) or ()) if cls is not None else ()


def _latest_data_input_commit(source: str, ref: str) -> tuple[Optional[int], Optional[str]]:
    """
    Latest commit time across a source's declared data inputs.

    Uses commit time, not mtime: these files are tracked, and ``git checkout``
    rewrites mtimes without changing content (#797).

    :param source: Transform source name.
    :param ref: Git ref to measure against.
    :return: ``(timestamp, "path @ sha")``, or ``(None, None)``.
    """
    newest_ts: Optional[int] = None
    newest_desc: Optional[str] = None
    for rel in _declared_data_inputs(source):
        ts, sha = _latest_commit(REPO / rel, ref)
        if ts is not None and (newest_ts is None or ts > newest_ts):
            newest_ts, newest_desc = ts, f"{rel} @ {sha}"
    return newest_ts, newest_desc
TRANSFORMED_DIR = REPO / "data" / "transformed"
MERGE_UTILS_DIR = REPO / "kg_microbe" / "merge_utils"
DEFAULT_REF = "origin/master"

# Merge config file candidates. First existing one wins for the reporting
# "merge config touched" timestamp, but every existing candidate is compared
# against the merged output.
MERGE_YAML_CANDIDATES = ["merge.yaml", "merge.minimal.yaml"]

# Merged output candidates — checked in order; first hit wins.
MERGED_OUTPUT_CANDIDATES = [
    "data/merged/merged-kg_edges.tsv",
    "data/merged/merged-kg.tar.gz",
    "data/merged/merged-kg_edges.tsv.gz",
]


@dataclass
class SourceReport:
    """One row of the per-source freshness report."""

    source: str
    status: str
    code_commit_ts: Optional[int]  # unix seconds; None if never committed
    code_commit_sha: Optional[str]
    output_mtime: Optional[float]
    local_changes: bool
    note: str = ""

    def as_row(self) -> dict:
        """Return a JSON-safe dict version for stdout printing."""
        d = asdict(self)
        d["code_commit_iso"] = _iso(self.code_commit_ts)
        d["output_mtime_iso"] = _iso(self.output_mtime)
        return d


@dataclass
class MergeReport:
    """One-row summary for the merge stage."""

    status: str
    merged_output: Optional[str]
    merged_mtime: Optional[float]
    merge_utils_commit_ts: Optional[int]
    merge_utils_commit_sha: Optional[str]
    merge_yaml_mtime: Optional[float]
    merge_yaml_path: Optional[str]
    stale_against: list = field(default_factory=list)
    note: str = ""

    def as_row(self) -> dict:
        """Return a JSON-safe dict version."""
        d = asdict(self)
        d["merged_mtime_iso"] = _iso(self.merged_mtime)
        d["merge_utils_commit_iso"] = _iso(self.merge_utils_commit_ts)
        d["merge_yaml_mtime_iso"] = _iso(self.merge_yaml_mtime)
        return d


def _iso(ts: Optional[float]) -> Optional[str]:
    """Return an ISO-8601 UTC string for a unix timestamp, or None."""
    if ts is None:
        return None
    import datetime as _dt

    return _dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(args: list[str], cwd: Path = REPO) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return r.stdout.strip()


def _ensure_ref(ref: str) -> None:
    """Verify the ref exists locally; try `git fetch` if not."""
    if _git(["rev-parse", "--verify", ref]) == "":
        sys.stderr.write(f"[freshness] {ref} not found locally; running git fetch\n")
        subprocess.run(
            ["git", "fetch", "origin", "master"], cwd=REPO, check=False
        )
    if _git(["rev-parse", "--verify", ref]) == "":
        sys.stderr.write(
            f"[freshness] {ref} still not resolvable; aborting.\n"
        )
        sys.exit(2)


def _latest_commit(path: Path, ref: str) -> tuple[Optional[int], Optional[str]]:
    """Return (unix_ts, short_sha) of the latest commit on `ref` touching `path`."""
    rel = str(path.relative_to(REPO))
    out = _git(["log", "-1", "--format=%ct %h", ref, "--", rel])
    if not out:
        return None, None
    ts_str, _, sha = out.partition(" ")
    try:
        return int(ts_str), sha
    except ValueError:
        return None, None


def _has_local_diff(path: Path, ref: str) -> bool:
    """True iff the working tree + index differ from ref for path."""
    rel = str(path.relative_to(REPO))
    return bool(_git(["diff", ref, "--", rel]).strip())


#: Sources whose output directory is not simply ``data/transformed/<name>/``.
#: PREGO writes ``prego_habitat/`` under its default (``PREGO_SHAPES=habitat``,
#: since #766) and ``prego/`` under ``PREGO_SHAPES=all``. Watching only ``prego/``
#: left the flag permanently STALE_VS_CODE — no default run writes it — while the
#: directory ``merge.yaml`` actually consumes went unchecked entirely.
OUTPUT_DIR_ALIASES: dict[str, tuple[str, ...]] = {
    "prego": ("prego_habitat", "prego"),
}


def _dirs_referenced_by_merge_config() -> set[str]:
    """
    Transform output directories the active merge config actually reads.

    A release pre-flight has to answer "is what will be merged current?", not "is
    any output for this source current?". Those differ for a source with more than
    one output path: with a fresh ``prego/`` from ``PREGO_SHAPES=all`` and a stale
    ``prego_habitat/``, picking by mtime reports FRESH while the standard merge
    consumes the stale build.

    :return: Directory names under ``data/transformed/`` named by the config.
    """
    for candidate in MERGE_YAML_CANDIDATES:
        path = REPO / candidate
        if not path.is_file():
            continue
        referenced: set[str] = set()
        for line in path.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = re.search(r"data/transformed/([^/\s]+)/", line)
            if match:
                referenced.add(match.group(1))
        if referenced:
            return referenced
    return set()


def _output_dirs(source_name: str) -> list[Path]:
    """
    Candidate output directories for a source, most authoritative first.

    The directory the merge config names wins. Only when the config names none
    does this fall back to whichever alias is populated, newest first — that
    fallback is for a source not in the merge at all, where "any output" is the
    best available answer.

    :param source_name: Transform name.
    :return: Existing directories that could hold this source's output.
    """
    names = OUTPUT_DIR_ALIASES.get(source_name, (source_name,))
    existing = [n for n in names if (TRANSFORMED_DIR / n).is_dir()]
    if len(existing) > 1:
        merged_refs = _dirs_referenced_by_merge_config()
        preferred = [n for n in existing if n in merged_refs]
        if preferred:
            existing = preferred
    return [TRANSFORMED_DIR / n for n in existing]


def _output_mtime(source_name: str) -> Optional[float]:
    """
    Newest mtime across the expected nodes/edges outputs for a source.

    Measures the directory the merge config consumes when the source has more than
    one output path — see :func:`_output_dirs`. Taking the newest across all of
    them reported FRESH while the merge read a stale build.

    :param source_name: Transform name.
    :return: Newest output mtime, or None if nothing is on disk.
    """
    newest: Optional[float] = None
    for src_dir in _output_dirs(source_name):
        hits = list(src_dir.glob("*.tsv")) + list(src_dir.glob("*.tsv.gz"))
        if not hits:
            continue
        candidate = max(p.stat().st_mtime for p in hits)
        newest = candidate if newest is None else max(newest, candidate)
    return newest


def _list_transform_sources() -> list[str]:
    """Return every kg_microbe/transform_utils/<name>/ that looks like a transform."""
    out = []
    for entry in sorted(TRANSFORM_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        # Transforms name their entrypoint either <name>.py (most sources)
        # or <name>_transform.py (ontologies, ontologies_stubs).
        if (entry / f"{entry.name}.py").is_file() or (
            entry / f"{entry.name}_transform.py"
        ).is_file():
            out.append(entry.name)
    return out


def check_source(source: str, ref: str) -> SourceReport:
    """Evaluate freshness for one transform source."""
    code_dir = TRANSFORM_ROOT / source
    py_file = code_dir / f"{source}.py"
    alt_py = code_dir / f"{source}_transform.py"
    if not py_file.is_file() and not alt_py.is_file():
        return SourceReport(
            source=source,
            status="NO_CODE",
            code_commit_ts=None,
            code_commit_sha=None,
            output_mtime=None,
            local_changes=False,
            note=f"{py_file.name} / {alt_py.name} missing",
        )

    commit_ts, commit_sha = _latest_commit(code_dir, ref)
    local = _has_local_diff(code_dir, ref)
    out_mtime = _output_mtime(source)

    if out_mtime is None:
        status = "MISSING_OUTPUT"
        expected = " or ".join(f"data/transformed/{n}/" for n in OUTPUT_DIR_ALIASES.get(source, (source,)))
        note = f"{expected} has no .tsv/.tsv.gz"
    elif local:
        status = "LOCAL_CHANGES"
        note = (
            "local code diverges from " + ref
            + "; freshness vs master is not defined until the diff lands"
        )
    elif commit_ts is None:
        status = "FRESH"
        note = f"no commit on {ref} touches this dir; treating as fresh"
    elif out_mtime < commit_ts:
        delta_days = (commit_ts - out_mtime) / 86400.0
        status = "STALE_VS_CODE"
        note = (
            f"code advanced {delta_days:.1f} days after last output build; "
            f"rerun `poetry run kg transform -s {source}`"
        )
    else:
        status = "FRESH"
        note = ""

    # Data staleness is checked even when the code is current: a mapping
    # correction changes the output without touching a line of transform code,
    # and reporting FRESH there is what let a re-merge ship groundings two
    # merged PRs had already fixed (#812).
    if status in {"FRESH", "STALE_VS_CODE"}:
        data_ts, data_desc = _latest_data_input_commit(source, ref)
        if data_ts is not None and out_mtime is not None and out_mtime < data_ts:
            delta_days = (data_ts - out_mtime) / 86400.0
            status = "STALE_VS_DATA" if status == "FRESH" else "STALE_VS_CODE_AND_DATA"
            note = (
                f"data input advanced {delta_days:.1f} days after last output build "
                f"({data_desc}); rerun `poetry run kg transform -s {source}`"
                + (f" — {note}" if note else "")
            )

    return SourceReport(
        source=source,
        status=status,
        code_commit_ts=commit_ts,
        code_commit_sha=commit_sha,
        output_mtime=out_mtime,
        local_changes=local,
        note=note,
    )


def check_merge(source_reports: Iterable[SourceReport], ref: str) -> MergeReport:
    """Evaluate freshness of the merge stage output."""
    merged_path = None
    merged_mtime = None
    for cand in MERGED_OUTPUT_CANDIDATES:
        p = REPO / cand
        if p.exists():
            merged_path = cand
            merged_mtime = p.stat().st_mtime
            break

    merge_yaml_path = None
    merge_yaml_mtime = None
    for cand in MERGE_YAML_CANDIDATES:
        p = REPO / cand
        if p.is_file():
            merge_yaml_path = cand
            merge_yaml_mtime = p.stat().st_mtime
            break

    utils_ts, utils_sha = _latest_commit(MERGE_UTILS_DIR, ref)

    if merged_mtime is None:
        return MergeReport(
            status="MISSING_OUTPUT",
            merged_output=None,
            merged_mtime=None,
            merge_utils_commit_ts=utils_ts,
            merge_utils_commit_sha=utils_sha,
            merge_yaml_mtime=merge_yaml_mtime,
            merge_yaml_path=merge_yaml_path,
            note="no data/merged/merged-kg_edges.tsv[.gz] or .tar.gz on disk",
        )

    stale_against: list[str] = []
    if utils_ts is not None and merged_mtime < utils_ts:
        stale_against.append("merge_utils code")
    if merge_yaml_mtime is not None and merged_mtime < merge_yaml_mtime:
        stale_against.append(merge_yaml_path or "merge yaml")
    for r in source_reports:
        if r.output_mtime is not None and merged_mtime < r.output_mtime:
            # Name the directory that is actually newer, not the source name. For a
            # source with a variant output path these differ, and printing
            # "data/transformed/prego/" while the fresh build sits in
            # "prego_habitat/" sends the reader to the wrong file.
            fresher = [
                d for d in _output_dirs(r.source)
                if any(
                    f.stat().st_mtime > merged_mtime
                    for f in list(d.glob("*.tsv")) + list(d.glob("*.tsv.gz"))
                )
            ]
            for d in fresher or [TRANSFORMED_DIR / r.source]:
                stale_against.append(f"data/transformed/{d.name}/")

    if not stale_against:
        status = "FRESH"
        note = ""
    else:
        # Choose the primary status label by precedence.
        if any(s == "merge_utils code" for s in stale_against):
            status = "STALE_VS_CODE"
        elif any(
            s == (merge_yaml_path or "merge yaml") for s in stale_against
        ):
            status = "STALE_VS_YAML"
        else:
            status = "STALE_VS_INPUTS"
        note = "rerun `poetry run kg merge -y merge.yaml` (or the config in use)"

    return MergeReport(
        status=status,
        merged_output=merged_path,
        merged_mtime=merged_mtime,
        merge_utils_commit_ts=utils_ts,
        merge_utils_commit_sha=utils_sha,
        merge_yaml_mtime=merge_yaml_mtime,
        merge_yaml_path=merge_yaml_path,
        stale_against=stale_against,
        note=note,
    )


def _format_table(rows: list[SourceReport]) -> str:
    header = (
        f"{'SOURCE':<22} {'STATUS':<16} {'CODE COMMIT (UTC)':<21} "
        f"{'OUTPUT MTIME (UTC)':<21} LOCAL  NOTE"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.source:<22} {r.status:<16} "
            f"{_iso(r.code_commit_ts) or '-':<21} "
            f"{_iso(r.output_mtime) or '-':<21} "
            f"{'yes' if r.local_changes else 'no':<6} "
            f"{r.note}"
        )
    return "\n".join(lines)


def _format_merge(m: MergeReport) -> str:
    lines = [
        "",
        "MERGE",
        "-----",
        f"  status           : {m.status}",
        f"  merged output    : {m.merged_output or '(none)'}",
        f"  merged mtime     : {_iso(m.merged_mtime) or '-'}",
        f"  merge_utils code : {(_iso(m.merge_utils_commit_ts) or '-')} "
        f"({m.merge_utils_commit_sha or '-'})",
        f"  merge yaml       : {m.merge_yaml_path or '(none)'} "
        f"({_iso(m.merge_yaml_mtime) or '-'})",
    ]
    if m.stale_against:
        lines.append("  stale against    :")
        for s in m.stale_against:
            lines.append(f"    - {s}")
    if m.note:
        lines.append(f"  action           : {m.note}")
    return "\n".join(lines)


def main() -> int:
    """Entry point."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"git ref to compare against (default: {DEFAULT_REF})",
    )
    p.add_argument(
        "--source",
        action="append",
        help="only check this source (repeatable). Default: every transform dir",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the human table",
    )
    p.add_argument(
        "--skip-fetch",
        action="store_true",
        help="don't run `git fetch origin master` even if the ref is unresolved",
    )
    args = p.parse_args()

    if not args.skip_fetch:
        _ensure_ref(args.ref)
    else:
        # still fail loudly if the ref is genuinely missing
        if _git(["rev-parse", "--verify", args.ref]) == "":
            sys.stderr.write(
                f"[freshness] {args.ref} not resolvable and --skip-fetch set; aborting.\n"
            )
            return 2

    sources = args.source or _list_transform_sources()
    reports = [check_source(s, args.ref) for s in sources]
    merge = check_merge(reports, args.ref)

    if args.json:
        payload = {
            "ref": args.ref,
            "sources": [r.as_row() for r in reports],
            "merge": merge.as_row(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_table(reports))
        print(_format_merge(merge))
        # concise summary counts
        from collections import Counter

        c = Counter(r.status for r in reports)
        print("")
        print("SUMMARY")
        print("-------")
        # Any status seen must appear, even one added later: a summary that
        # silently omits a category reads as a clean run (#812).
        known = [
            "FRESH",
            "STALE_VS_CODE",
            "STALE_VS_DATA",
            "STALE_VS_CODE_AND_DATA",
            "LOCAL_CHANGES",
            "MISSING_OUTPUT",
            "NO_CODE",
        ]
        for status in known + sorted(set(c) - set(known)):
            print(f"  {status:<24} {c.get(status, 0)}")
        print(f"  merge            {merge.status}")

    # exit code
    non_fresh_sources = any(
        r.status not in ("FRESH", "NO_CODE") for r in reports
    )
    if non_fresh_sources or merge.status != "FRESH":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
