"""
Summarize cProfile evidence for the fingerprint AST cache, issue #1862.

Purpose: compare measured test profiles without adding overlapping timings (2026-11-15).
Inputs: completed cProfile .prof files and optional pytest text logs.
Outputs: JSON on stdout, or a newly created --output file; inputs remain unchanged.
Only input basenames and selected function basenames are reported, not machine paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pstats
import re
from pathlib import Path

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PYTEST_SUMMARY = re.compile(
    r"^(?:=+\s*)?\d+ (?:passed|failed|skipped|xfailed|xpassed|errors?|deselected)\b.*\bin \d+(?:\.\d+)?s\b"
)


def input_identity(path: Path) -> dict[str, str]:
    """Identify an input by basename and exact bytes without publishing its parent path."""
    return {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def summarize_profile(path: Path) -> dict:
    """Return individual pstats measurements, retaining cumulative overlap explicitly."""
    stats = pstats.Stats(str(path))
    functions = []
    for (filename, line, function), (primitive_calls, total_calls, self_seconds, cumulative_seconds, _) in sorted(
        stats.stats.items()
    ):
        basename = Path(filename).name
        fingerprint = basename == "transform_fingerprint.py" and ("behaviour" in function or "cached" in function)
        ast_function = basename == "ast.py" and function in {"parse", "dump"}
        if fingerprint or ast_function:
            functions.append(
                {
                    "file": basename,
                    "line": line,
                    "function": function,
                    "primitive_calls": primitive_calls,
                    "total_calls": total_calls,
                    "self_seconds": self_seconds,
                    "cumulative_seconds": cumulative_seconds,
                }
            )
    return {
        **input_identity(path),
        "total_profile_seconds": stats.total_tt,
        "primitive_calls": stats.prim_calls,
        "total_calls": stats.total_calls,
        "functions": functions,
    }


def summarize_log(path: Path) -> dict:
    """Retain literal pytest summary lines without inferring scope from test counts."""
    lines = [
        ANSI_ESCAPE.sub("", line).strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    ]
    return {**input_identity(path), "summary_lines": [line for line in lines if PYTEST_SUMMARY.search(line)]}


def main() -> int:
    """Read profiles and emit an evidence summary without overwriting earlier output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", type=Path, nargs="+", help="completed cProfile files, reported separately")
    parser.add_argument("--pytest-log", type=Path, action="append", default=[], help="optional log; repeat as needed")
    parser.add_argument("--output", type=Path, help="create this JSON file instead of printing to stdout")
    args = parser.parse_args()
    try:
        report = {
            "issue": 1862,
            "timing_note": "Profile time is not wall-clock time. Cumulative function times overlap; do not sum them.",
            "selection_note": "Only AST parse/dump and transform_fingerprint behaviour/cache functions are listed. "
            "An absent function entry does not establish cache hit counts or coverage.",
            "profiles": [summarize_profile(path) for path in args.profiles],
            "pytest_logs": [summarize_log(path) for path in args.pytest_log],
        }
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, EOFError, TypeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
