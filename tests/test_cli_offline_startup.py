"""CLI command discovery must not import network-backed implementations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("arguments", [["--help"], ["download", "--help"], ["transform", "--help"]])
def test_cli_help_works_with_socket_access_blocked(tmp_path: Path, arguments: list[str]) -> None:
    """Help must be available before command-local dependencies are imported."""
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        """
import socket

def blocked(*args, **kwargs):
    raise AssertionError("network access attempted during CLI startup")

socket.create_connection = blocked
socket.socket.connect = blocked
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["KG_MICROBE_TESTS_NO_NETWORK"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(REPO_ROOT)])
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        [sys.executable, "-m", "kg_microbe.run", *arguments],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout


def test_importing_cli_does_not_import_kgx() -> None:
    """KGX must remain command-local because importing it initializes BMT."""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and inline test program
        [
            sys.executable,
            "-c",
            "import sys; import kg_microbe.run; assert 'kgx' not in sys.modules",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
