"""Offline coverage for the retained 2026-11-05 production refresh wrapper."""

import argparse
import copy
import io
import json
import os
from pathlib import Path

import pytest
import requests
from urllib3.response import HTTPResponse

from kg_microbe.utils import mediadive_bulk_download as production
from scripts.adhoc import kgm_mediadive_refresh_20261105 as refresh

FIXTURE = Path(__file__).parent / "resources/mediadive_refresh_20261105.json"


@pytest.fixture
def payloads():
    """Read immutable synthetic endpoint payloads."""
    return refresh.load_json(FIXTURE)


@pytest.fixture
def transport(monkeypatch, payloads):
    """Stub only the transport adapter, retaining production requests/cache/retries."""
    hits = []
    strain_status = [200]

    def send(adapter, request, **kwargs):
        url = request.url
        hits.append(url)
        is_strain = "/medium-strains/" in url
        payload = copy.deepcopy(payloads["empty_strains" if is_strain else "detail"])
        if not is_strain:
            payload["data"]["medium"]["id"] = request.url.rsplit("/", 1)[-1]
        body = json.dumps(payload).encode()
        response = requests.Response()
        response.status_code = strain_status[0] if is_strain else 200
        response.url = url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = body
        response.raw = HTTPResponse(
            body=io.BytesIO(body),
            status=response.status_code,
            headers=response.headers,
            preload_content=False,
            request_url=url,
        )
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(production.time, "sleep", lambda delay: None)
    previous_handlers = list(production.logger.handlers)
    yield hits, strain_status
    production.setup_cache(None)
    for handler in list(production.logger.handlers):
        if handler not in previous_handlers:
            production.logger.removeHandler(handler)
            handler.close()


def run_production(tmp_path, monkeypatch, payloads):
    """Run the actual entry point and retain its real SQLite/JSON artifacts."""
    monkeypatch.chdir(tmp_path)
    basic = tmp_path / "selected.json"
    refresh.write_json(basic, {"data": refresh.select_media(payloads["catalogue"], "canary")})
    attempts = tmp_path / "http-attempts.jsonl"
    output = tmp_path / "output"
    with refresh.observe_transport(attempts):
        production.download_mediadive_bulk(str(basic), str(output), **refresh.SETTINGS)
    snapshot = tmp_path / "artifacts"
    refresh.snapshot_artifacts(output, snapshot)
    return attempts, output, snapshot


def test_canary_prefers_one_and_full_preserves_catalogue(payloads):
    """The only selected-data change is one catalogue record versus all records."""
    assert refresh.select_media(payloads["catalogue"], "canary") == [payloads["catalogue"]["data"][1]]
    assert refresh.select_media(payloads["catalogue"], "full") == payloads["catalogue"]["data"]
    with pytest.raises(ValueError, match="duplicate"):
        refresh.select_media({"data": [{"id": 1}, {"id": 1}]}, "canary")


def test_real_production_cache_preserves_valid_empty_strains(tmp_path, monkeypatch, payloads, transport):
    """A successful empty list remains distinguishable from native empty failure output."""
    attempts_path, output, snapshot = run_production(tmp_path, monkeypatch, payloads)
    attempts = refresh.summarize_attempts(attempts_path, ["1"])
    before = {path.name: refresh.digest(path) for path in snapshot.iterdir()}
    cache = snapshot / refresh.CACHE_NAME
    with cache.open("rb") as stream:
        assert stream.read(20)[18:20] == b"\x01\x01"
    result = refresh.validate_artifacts(snapshot, ["1"], attempts, production)
    assert {path.name: refresh.digest(path) for path in snapshot.iterdir()} == before
    assert result["persisted_responses"] == 2
    assert result["valid_empty_strain_responses"] == 1
    assert result["compounds"] == result["solutions"] == 1
    assert len(transport[0]) == 2
    assert refresh.load_json(output / "media_strains.json") == {}
    assert production._live_sessions == []
    assert (snapshot / refresh.CACHE_NAME).stat().st_ino != (output / refresh.CACHE_NAME).stat().st_ino
    (output / "media_detailed.json").write_text("{}")
    assert refresh.load_json(snapshot / "media_detailed.json")["1"]


def test_native_silent_404_is_not_accepted_as_empty_strains(tmp_path, monkeypatch, payloads, transport):
    """Native exit zero plus empty strain JSON cannot hide three failed HTTP attempts."""
    transport[1][0] = 404
    attempts, output, snapshot = run_production(tmp_path, monkeypatch, payloads)
    assert refresh.load_json(output / "media_strains.json") == {}
    assert len(transport[0]) == 4
    with pytest.raises(ValueError, match="failed HTTP/JSON"):
        refresh.summarize_attempts(attempts, ["1"])
    assert (snapshot / refresh.CACHE_NAME).is_file()


def test_persisted_output_tampering_is_rejected(tmp_path, monkeypatch, payloads, transport):
    """All four emitted JSON files must agree with persisted endpoint responses."""
    attempts_path, _, snapshot = run_production(tmp_path, monkeypatch, payloads)
    attempts = refresh.summarize_attempts(attempts_path, ["1"])
    (snapshot / "compounds.json").write_text("{}")
    with pytest.raises(ValueError, match="compound output differs"):
        refresh.validate_artifacts(snapshot, ["1"], attempts, production)


def test_missing_persisted_response_is_rejected(tmp_path, monkeypatch, payloads, transport):
    """Fresh-reader verification fails if SQLite persistence omitted an endpoint."""
    import sqlite3

    attempts_path, _, snapshot = run_production(tmp_path, monkeypatch, payloads)
    attempts = refresh.summarize_attempts(attempts_path, ["1"])
    with sqlite3.connect(snapshot / refresh.CACHE_NAME) as connection:
        connection.execute("DELETE FROM responses WHERE key = (SELECT key FROM responses LIMIT 1)")
    with pytest.raises(ValueError, match="do not cover"):
        refresh.validate_artifacts(snapshot, ["1"], attempts, production)


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": None}])
def test_only_explicit_empty_list_is_valid(payload):
    """Missing data and fallback empty dictionaries are not successful empty responses."""
    with pytest.raises(ValueError):
        refresh.validate_payload(refresh.BASE_URL + "medium-strains/1", payload)


def test_layout_includes_ignored_files_and_blocks_hardlinks(tmp_path, monkeypatch):
    """Protect original inputs even when a shared file is hidden or ignored."""
    worktree = tmp_path / "owned"
    raw = worktree / "data/raw"
    source = tmp_path / "original/data/raw"
    raw.mkdir(parents=True)
    source.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: unused-test-placeholder\n")
    monkeypatch.chdir(worktree)
    (source / ".ignored.sqlite").write_bytes(b"untouched")
    os.link(source / ".ignored.sqlite", raw / ".ignored.sqlite")
    with pytest.raises(ValueError, match="shared hardlinks"):
        refresh.validate_layout(worktree, source)
    (raw / ".ignored.sqlite").unlink()
    (raw / ".ignored.sqlite").write_bytes(b"independent")
    assert refresh.validate_layout(worktree, source)["ignored_files_included"] is True
    (worktree / refresh.CACHE_NAME).write_bytes(b"never migrate this")
    with pytest.raises(ValueError, match="migration hazard"):
        refresh.validate_layout(worktree, source)


def test_layout_rejects_symlinked_raw(tmp_path, monkeypatch):
    """A staged path that redirects to the original must be refused before writes."""
    worktree = tmp_path / "owned"
    (worktree / "data").mkdir(parents=True)
    source = tmp_path / "original/data/raw"
    source.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: unused-test-placeholder\n")
    (worktree / "data/raw").symlink_to(source, target_is_directory=True)
    monkeypatch.chdir(worktree)
    with pytest.raises(ValueError, match="coincide"):
        refresh.validate_layout(worktree, source)


def test_native_step_only_and_public_shapes_remain_explicit(payloads):
    """Preserve native recipes without inventing ingredients or imposing new policy."""
    endpoint = refresh.BASE_URL + "medium/1"
    step_only = {"data": {"medium": {"id": 1}, "solutions": [{"id": 9, "steps": []}]}}
    public = {"data": {"medium": {"id": 1}}}
    assert refresh.validate_payload(endpoint, step_only) == "medium_without_recipe"
    assert refresh.validate_payload(endpoint, public) == "medium_without_solutions"
    assert refresh.validate_payload(endpoint, payloads["detail"]) == "medium"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_snapshot_sidecars_are_refused(tmp_path, monkeypatch, payloads, transport, suffix):
    """An immutable evidence reader must not ignore a separate SQLite generation."""
    attempts_path, _, snapshot = run_production(tmp_path, monkeypatch, payloads)
    attempts = refresh.summarize_attempts(attempts_path, ["1"])
    sidecar = snapshot / (refresh.CACHE_NAME + suffix)
    sidecar.write_bytes(b"unconsumed generation")
    with pytest.raises(ValueError, match="unconsumed SQLite sidecar"):
        refresh.validate_artifacts(snapshot, ["1"], attempts, production)
    assert sidecar.read_bytes() == b"unconsumed generation"


def test_layout_refuses_unreadable_ignored_subdirectory(tmp_path, monkeypatch):
    """A silently skipped directory cannot count as verified independent staging."""
    worktree = tmp_path / "owned"
    (worktree / "data/raw").mkdir(parents=True)
    source = tmp_path / "original/data/raw"
    source.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: unused-test-placeholder\n")
    monkeypatch.chdir(worktree)

    def inaccessible_walk(path, *, onerror=None):
        """Model os.walk reporting a permission failure for an ignored directory."""
        if onerror:
            onerror(PermissionError("unreadable ignored raw directory"))
        return iter(())

    monkeypatch.setattr(refresh.os, "walk", inaccessible_walk)
    with pytest.raises(PermissionError, match="unreadable ignored raw directory"):
        refresh.validate_layout(worktree, source)


@pytest.fixture
def sequence_args(tmp_path, monkeypatch, payloads):
    """Own a complete independent layout while controlling only runtime identity."""
    worktree = tmp_path / "owned"
    raw = worktree / "data/raw"
    raw.mkdir(parents=True)
    source = tmp_path / "original/data/raw"
    source.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: unused-test-placeholder\n")
    script = worktree / "scripts/adhoc/helper.py"
    script.parent.mkdir(parents=True)
    script.write_text("# test-owned script locator\n")
    refresh.write_json(raw / "mediadive.json", payloads["catalogue"])
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(refresh, "__file__", str(script))
    monkeypatch.setenv("TEST_MEDIADIVE_BOUND_ENV", "same")
    monkeypatch.setattr(refresh, "identity", lambda *args: {"environment": os.environ["TEST_MEDIADIVE_BOUND_ENV"]})
    return argparse.Namespace(phase="sequence", source_raw=source, launcher=script, attempt="fresh", execute=True)


def test_sequence_admits_real_canary_before_same_process_full(sequence_args, transport, monkeypatch):
    """Both batches retain native calls/settings and verify independent canary artifacts."""
    calls = []
    previous_handlers = tuple(production.logger.handlers)
    original = production.download_mediadive_bulk

    def observed(*args, **kwargs):
        calls.append((args, kwargs, os.getpid()))
        return original(*args, **kwargs)

    monkeypatch.setattr(production, "download_mediadive_bulk", observed)
    result = refresh.run_sequence(sequence_args)
    assert result["status"] == "passed" and result["selected_count"] == 2
    assert len(transport[0]) == 6
    assert calls[0] == calls[1]
    assert calls[0][1] == refresh.SETTINGS
    evidence = refresh.evidence_directory(Path.cwd(), "fresh")
    canary = refresh.load_json(evidence / "canary/receipt.json")
    assert canary["status"] == "passed" and canary["selected_count"] == 1
    assert len(refresh.load_json(evidence / "canary/artifacts/media_detailed.json")) == 1
    assert len(refresh.load_json(evidence / "full/artifacts/media_detailed.json")) == 2
    assert tuple(production.logger.handlers) == previous_handlers


def test_sequence_environment_mismatch_stops_before_full_http(sequence_args, transport, monkeypatch):
    """One process does not waive the existing exact canary/full environment gate."""
    original = refresh.run

    def changed_after_verified_canary(args):
        result = original(args)
        if args.phase == "canary":
            monkeypatch.setenv("TEST_MEDIADIVE_BOUND_ENV", "changed")
        return result

    monkeypatch.setattr(refresh, "run", changed_after_verified_canary)
    with pytest.raises(ValueError, match="runtime identity changed"):
        refresh.run_sequence(sequence_args)
    assert len(transport[0]) == 2
    evidence = refresh.evidence_directory(Path.cwd(), "fresh")
    assert refresh.load_json(evidence / "canary/receipt.json")["status"] == "passed"
    assert not (evidence / "full").exists()


def test_attempt_collision_and_unsafe_label_refuse_before_http(sequence_args, transport):
    """A new attempt cannot overwrite existing evidence or escape through its label."""
    evidence = refresh.evidence_directory(Path.cwd(), "fresh")
    evidence.mkdir(parents=True)
    with pytest.raises(ValueError, match="reuse attempt evidence"):
        refresh.run_sequence(sequence_args)
    assert transport[0] == []
    with pytest.raises(ValueError, match="Invalid attempt"):
        refresh.evidence_directory(Path.cwd(), "../old")
