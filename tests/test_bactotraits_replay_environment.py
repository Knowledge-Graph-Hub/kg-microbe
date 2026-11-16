"""
2026-11-16, #1866: verify real replay dependency imports respect private staging.

2026-11-16, #1868: verify staged URI conversion and reject prefix registry drift.

Inputs: checked-out launcher/producer and installed dependencies, no raw data.
Outputs: private pytest scratch caches; no producer run or network requests.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/adhoc/replay_bactotraits_identity_130_20261115.py"


def _load_replay():
    """Load the checked-out launcher without invoking a plan or producer."""
    spec = importlib.util.spec_from_file_location("bactotraits_replay", HELPER)
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    return replay


def _guarded_import(stage, outside):
    """Exercise the real import chain in a fresh interpreter under the replay guard."""
    os.umask(0o077)
    stage.mkdir(mode=0o700)
    original_home = os.environ.get("HOME")
    # Conflicting inherited cache overrides must not escape the private stage.
    for variable in ("PYSTOW_HOME", "PYSTOW_CONFIG_HOME", "OAKLIB_HOME", "BIOREGISTRY_HOME"):
        os.environ[variable] = str(outside / variable)
    os.environ["PYSTOW_USE_APPDIRS"] = "true"
    replay = _load_replay()
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


@pytest.fixture
def registry_plan(tmp_path):
    """Pin a synthetic registry in original and private staged locations."""
    replay = _load_replay()
    original = tmp_path.resolve() / "prefixmap.json"
    stage = tmp_path.resolve() / "stage"
    staged = stage / "mappings/prefixmap.json"
    raw = b'{"Replay130": "https://example.org/identity130/"}\n'
    original.write_bytes(raw)
    staged.parent.mkdir(parents=True)
    staged.write_bytes(raw)
    plan = {
        "stage": stage,
        "sources": [replay.source_pin(original, raw)],
        "shared": {"staged_inputs": {"mappings/prefixmap.json": replay.digest(raw)}},
    }
    return replay, plan, original, staged


def test_uri_conversion_uses_staged_registry_and_discards_old_cache(registry_plan, tmp_path, monkeypatch):
    """A warmed registry cannot override the bytes selected for actual URI conversion."""
    from kg_microbe.utils import graph_canonicalization, mapping_file_utils

    replay, plan, original, staged = registry_plan
    previous = tmp_path / "previous.json"
    previous.write_text('{"Stale": "https://example.org/identity130/"}')
    monkeypatch.setattr(graph_canonicalization, "PREFIXMAP_JSON_FILEPATH", previous)
    graph_canonicalization._uri_prefixes.cache_clear()
    try:
        assert mapping_file_utils.uri_to_curie("https://example.org/identity130/7") == "Stale:7"
        replay.verify_runtime_inputs(plan)
        replay.bind_staged_prefix_registry(plan["stage"])
        assert graph_canonicalization.PREFIXMAP_JSON_FILEPATH == staged
        assert mapping_file_utils.uri_to_curie("https://example.org/identity130/7") == "Replay130:7"
        replay.verify_runtime_inputs(plan)
        assert original.read_bytes() == staged.read_bytes()
    finally:
        graph_canonicalization._uri_prefixes.cache_clear()


@pytest.mark.parametrize("changed", ["original", "staged"])
def test_registry_drift_rejected_before_receipt(registry_plan, changed):
    """Neither an edited original nor an edited staged registry can receive a valid receipt."""
    replay, plan, original, staged = registry_plan
    replay.verify_runtime_inputs(plan)
    (original if changed == "original" else staged).write_text('{"Changed": "https://example.org/"}')
    with pytest.raises(ValueError, match=f"{changed.capitalize()} runtime input changed"):
        replay.verify_runtime_inputs(plan)


def test_baseline_candidate_registry_hashes_must_agree(registry_plan):
    """A candidate with a different prefix registry cannot reuse a baseline receipt."""
    replay, plan, _, _ = registry_plan
    baseline = plan["stage"] / "baseline-receipt.json"
    receipt = {
        "profile": replay.PROFILE,
        "mode": "baseline",
        "git_revision": replay.BASE_REVISION,
        "shared_inputs": plan["shared"],
    }
    baseline.write_text(json.dumps(receipt))
    candidate_inputs = {"staged_inputs": {"mappings/prefixmap.json": replay.digest(b"changed registry")}}
    with pytest.raises(ValueError, match="Baseline and candidate do not share exact inputs/runtime"):
        replay.baseline_data(SimpleNamespace(baseline_receipt=baseline), candidate_inputs)


if __name__ == "__main__":
    _guarded_import(Path(sys.argv[1]), Path(sys.argv[2]))
