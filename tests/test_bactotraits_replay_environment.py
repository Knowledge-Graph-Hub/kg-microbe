"""
2026-11-16, #1866: verify real replay dependency imports respect private staging.

Inputs: checked-out launcher/producer and installed dependencies, no raw data.
Outputs: private pytest scratch caches; no producer run or network requests.
"""

import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/adhoc/replay_bactotraits_identity_130_20261115.py"


def _guarded_import(stage, outside):
    """Exercise the real import chain in a fresh interpreter under the replay guard."""
    os.umask(0o077)
    stage.mkdir(mode=0o700)
    original_home = os.environ.get("HOME")
    # Conflicting inherited cache overrides must not escape the private stage.
    for variable in ("PYSTOW_HOME", "PYSTOW_CONFIG_HOME", "OAKLIB_HOME", "BIOREGISTRY_HOME"):
        os.environ[variable] = str(outside / variable)
    os.environ["PYSTOW_USE_APPDIRS"] = "true"
    spec = importlib.util.spec_from_file_location("bactotraits_replay", HELPER)
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    replay.configure_private_environment(stage)
    sys.path.insert(0, str(ROOT))
    replay.install_guards(stage)

    bactotraits = importlib.import_module("kg_microbe.transform_utils.bactotraits.bactotraits")

    import pystow
    from bioregistry.constants import BIOREGISTRY_MODULE
    from oaklib.constants import OAKLIB_MODULE

    assert Path(bactotraits.__file__).is_relative_to(ROOT)
    assert pystow.utils.get_home() == stage / "cache/pystow"
    readme = stage / "cache/pystow/README.md"
    assert readme.is_file() and readme.stat().st_size > 0
    assert readme.stat().st_mode & 0o777 == 0o600
    assert OAKLIB_MODULE.base.is_relative_to(stage)
    assert BIOREGISTRY_MODULE.base.is_relative_to(stage)
    assert os.environ.get("HOME") == original_home
    assert not outside.exists()

    try:
        (outside / "forbidden.txt").write_text("must not persist")
    except ValueError as error:
        assert "Write outside replay stage refused" in str(error)
    else:
        raise AssertionError("Replay write guard was weakened")
    try:
        socket.getaddrinfo("example.org", 443)
    except RuntimeError as error:
        assert "Network/subprocess use is forbidden" in str(error)
    else:
        raise AssertionError("Replay network guard was weakened")
    assert not outside.exists()
    print("real guarded dependency import passed")


def test_real_dependency_import_confined_to_private_stage(tmp_path):
    """Catch import-time cache writes without a live producer run or warmed modules."""
    stage = tmp_path.resolve() / "stage"
    outside = tmp_path.resolve() / "outside"
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/test file; no shell or network.
        [sys.executable, "-B", str(Path(__file__).resolve()), str(stage), str(outside)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "real guarded dependency import passed" in result.stdout
    assert (stage / "cache/pystow/README.md").stat().st_size > 0
    assert not outside.exists()


if __name__ == "__main__":
    _guarded_import(Path(sys.argv[1]), Path(sys.argv[2]))
