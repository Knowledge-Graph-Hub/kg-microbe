"""
Forward legacy gate invocations to the checkout's maintained single-suite runner.

Purpose: preserve existing M5 gate entrypoints for the single-suite policy, 2026-10-28.
Inputs: the original run label/options and current candidate checkout directory.
Outputs: canonical gate results, retaining /tmp/kgm-<label>-* evidence names.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LEGACY_OUTPUT = "/tmp"  # noqa: S108 - preserve the explicitly requested legacy evidence location


def main() -> int:
    """Run the repository-owned gate implementation without duplicating its policy."""
    runner = Path.cwd() / "scripts" / "run_pr_gates.py"
    if not runner.is_file():
        print("Install the single-suite policy in this candidate checkout before running gates.", file=sys.stderr)
        return 1
    return subprocess.run(  # noqa: S603 - use this Python and the checkout-owned gate CLI; no shell
        [sys.executable, str(runner), *sys.argv[1:], "--output-dir", LEGACY_OUTPUT], check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
