"""Offline durability, actual transport strategy and explicit generation recovery controls."""

import fcntl
import json
from pathlib import Path

import pytest
import requests

from kg_microbe.transform_utils.mediadive import acquisition
from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes
from tests.mediadive_generation_fixtures import _response, seal_fixture_raw

FIXTURE = Path(__file__).parent / "resources/mediadive_retry_20261105.json"


@pytest.fixture
def case(tmp_path, monkeypatch):
    """Keep real Sessions/cache serialization and stub only the HTTP adapter with fixture bytes."""
    fixture = json.loads(FIXTURE.read_text())
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text('{"status":200,"count":1,"data":[{"id":1}]}')
    output = tmp_path / "mediadive"
    hits, sessions, configured = [], [], {}
    real_session = requests.Session

    def fresh_session():
        """Retain actual session objects so reuse cannot hide behind recycled object IDs."""
        session = real_session()
        sessions.append(session)
        return session

    def send(adapter, request, **kwargs):
        """Serve explicit offline outcomes through the unchanged Requests session boundary."""
        url = request.url
        hits.append(url)
        kind = "strains" if "/medium-strains/" in url else "detail"
        choices = configured.get(kind, [kind])
        choice = choices.pop(0) if len(choices) > 1 else choices[0]
        if choice == "transport":
            raise requests.ConnectionError("Synthetic offline transport exception")
        if choice == "429":
            response = _response(url, {"error": "synthetic rate limit"}, 429)
            response.headers["Retry-After"] = "0"
        elif choice == "503":
            response = _response(url, {"error": "synthetic unavailable"}, 503)
        elif choice == "redirect":
            response = _response(url, {"error": "synthetic redirect"}, 302)
            response.headers["Location"] = outcomes.BASE_URL + "medium-strains/unselected"
        else:
            response = _response(url, fixture[choice], 404 if choice == "unknown" else 200)
        response.request = request
        return response

    monkeypatch.setattr(requests, "Session", fresh_session)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(acquisition.time, "sleep", lambda delay: None)
    return {
        "catalogue": catalogue,
        "output": output,
        "hits": hits,
        "sessions": sessions,
        "configured": configured,
        "fixture": fixture,
    }


def collect(case, name, *, publish=False, fault=None):
    """Acquire exactly the fixture's two endpoints through the public production writer."""
    with acquisition.start_generation(case["output"], name, case["catalogue"], fault=fault) as handle:
        previous = handle.check()["expected_current_sha256"]
        urls = [outcomes.BASE_URL + kind + "/1" for kind in ("medium", "medium-strains")]
        acquisition.acquire_endpoints(handle, urls, max_workers=1)
        view = acquisition.checkpoint_generation(handle)
    if publish:
        view = acquisition.publish_generation(case["output"], name, view.manifest_identity["sha256"], previous)
    return view


def test_fresh_sessions_terminal_unknown_and_transport_only_retry(case):
    """A connection failure retries with a fresh connection; documented 404 stops immediately."""
    case["configured"]["strains"] = ["transport", "unknown"]
    view = collect(case, "unknown")
    assert len(case["hits"]) == len(case["sessions"]) == 3
    assert all(session.headers["Connection"] == "close" for session in case["sessions"])
    assert not view.qualification["admissible"]
    assert view.qualification["state_counts"]["unknown_unavailable"] == 1
    assert not view.qualification["association_coverage_complete"]
    assert not (case["output"] / "current.json").exists()
    assert len((view.generation_dir / "observations.jsonl").read_bytes().splitlines()) == 3
    assert set(outcomes.cache_records(view.generation_dir / outcomes.CACHE_FILE)) == {outcomes.BASE_URL + "medium/1"}
    with pytest.raises(outcomes.EndpointEvidenceError, match="unresolved endpoint"):
        acquisition.publish_generation(case["output"], "unknown", view.manifest_identity["sha256"], None)


@pytest.mark.parametrize(
    "initial,attempts,final_state", [("429", 2, "nonempty"), ("503", 1, "malformed"), ("redirect", 1, "malformed")]
)
def test_only_429_retries_and_redirects_never_follow(case, initial, attempts, final_state):
    """Unexpected HTTP is retained as malformed; no off-scope redirected request can occur."""
    case["configured"]["strains"] = [initial, "strains"]
    view = collect(case, "http-case")
    strain_hits = [url for url in case["hits"] if "/medium-strains/" in url]
    assert len(strain_hits) == attempts
    assert all(url.endswith("/1") for url in strain_hits)
    assert view.endpoint_states[outcomes.BASE_URL + "medium-strains/1"] == final_state


@pytest.mark.parametrize("boundary", ["after_observation", "after_cache", "before_json", "after_json", "before_seal"])
def test_interrupted_generation_recovery_preserves_old_active_and_all_responses(case, boundary):
    """Explicit #1754 recovery replays durable evidence without HTTP or replacing the old pointer."""
    old = collect(case, "old", publish=True)
    pointer = outcomes.identity(case["output"] / "current.json")
    originals = {path: outcomes.identity(path) for path in old.generation_dir.rglob("*") if path.is_file()}
    plan = None
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        with acquisition.start_generation(case["output"], "interrupted", case["catalogue"]) as handle:
            plan = handle.plan_sha256

            def interrupt(label):
                """Interrupt only after the final requested response or the selected publication boundary."""
                if label == boundary and (label not in {"after_observation", "after_cache"} or handle.sequence == 2):
                    raise RuntimeError("Synthetic interruption")

            handle.fault = interrupt
            acquisition.acquire_endpoints(
                handle, [outcomes.BASE_URL + "medium/1", outcomes.BASE_URL + "medium-strains/1"], max_workers=1
            )
            acquisition.checkpoint_generation(handle)
    hit_count = len(case["hits"])
    assert outcomes.identity(case["output"] / "current.json") == pointer
    recovered = acquisition.recover_generation(case["output"], "interrupted", plan)
    assert recovered.qualification["admissible"]
    assert len(case["hits"]) == hit_count
    assert outcomes.identity(case["output"] / "current.json") == pointer
    assert {path: outcomes.identity(path) for path in originals} == originals
    assert len((recovered.generation_dir / "observations.jsonl").read_bytes().splitlines()) == 2
    acquisition.publish_generation(
        case["output"], "interrupted", recovered.manifest_identity["sha256"], pointer["sha256"]
    )
    assert outcomes.load_generation(case["output"]).generation_dir == recovered.generation_dir


def test_later_completed_request_resolves_older_unmatched_intent(case):
    """A newer actual result resolves #1763 without erasing the earlier interrupted attempt."""
    with acquisition.start_generation(case["output"], "intent-recovery", case["catalogue"]) as handle:
        url = outcomes.BASE_URL + "medium-strains/1"
        acquisition.begin_request(handle, url)
        acquisition.acquire_endpoints(handle, [outcomes.BASE_URL + "medium/1", url], max_workers=1)
        view = acquisition.checkpoint_generation(handle)
    assert view.qualification["admissible"]
    assert view.endpoint_states[url] == "nonempty"
    assert len((view.generation_dir / "request-intents.jsonl").read_bytes().splitlines()) == 3
    assert len((view.generation_dir / "observations.jsonl").read_bytes().splitlines()) == 2


def test_latest_unmatched_intent_remains_missing(case):
    """An interrupted newer attempt cannot reuse an older response as its own evidence."""
    case["configured"]["strains"] = ["unknown"]
    with acquisition.start_generation(case["output"], "unmatched", case["catalogue"]) as handle:
        acquisition.acquire_endpoints(
            handle, [outcomes.BASE_URL + "medium/1", outcomes.BASE_URL + "medium-strains/1"], max_workers=1
        )
        acquisition.begin_request(handle, outcomes.BASE_URL + "medium-strains/1")
        view = acquisition.checkpoint_generation(handle)
    assert view.endpoint_states[outcomes.BASE_URL + "medium-strains/1"] == "missing_evidence"
    assert not view.qualification["admissible"] and not view.qualification["endpoint_accounting_complete"]


def test_pending_pointer_recovery_is_exact_and_preserves_old_active(case):
    """#1764 allows explicit reuse of verified pending bytes after a before-pointer crash."""
    old = collect(case, "old", publish=True)
    before = outcomes.identity(case["output"] / "current.json")
    new = collect(case, "new")

    def interrupt(label):
        """Simulate interruption after durable pending pointer bytes but before atomic replacement."""
        assert label == "before_pointer"
        raise RuntimeError("Synthetic pointer interruption")

    with pytest.raises(RuntimeError, match="pointer interruption"):
        acquisition.publish_generation(
            case["output"], "new", new.manifest_identity["sha256"], before["sha256"], fault=interrupt
        )
    assert outcomes.identity(case["output"] / "current.json") == before
    pending = case["output"] / ".current-new.pending"
    assert pending.is_file() and old.generation_dir.is_dir()
    acquisition.publish_generation(case["output"], "new", new.manifest_identity["sha256"], before["sha256"])
    assert outcomes.load_generation(case["output"]).generation_dir == new.generation_dir
    assert not pending.exists()


def test_mismatched_pending_pointer_is_retained_and_refused(case):
    """An unrelated pending pointer cannot be silently overwritten or assumed valid."""
    old = collect(case, "old", publish=True)
    before = outcomes.identity(case["output"] / "current.json")
    new = collect(case, "new")
    pending = case["output"] / ".current-new.pending"
    pending.write_bytes(b"unreviewed pending bytes")
    with pytest.raises(outcomes.EndpointEvidenceError, match="Pending pointer differs"):
        acquisition.publish_generation(case["output"], "new", new.manifest_identity["sha256"], before["sha256"])
    assert pending.read_bytes() == b"unreviewed pending bytes"
    assert outcomes.identity(case["output"] / "current.json") == before
    assert old.generation_dir.is_dir()


def test_publisher_lock_refuses_competing_writer(case):
    """#1764 serializes pointer writers before their expected-current comparison."""
    view = collect(case, "candidate")
    with (case["output"] / ".publication.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(outcomes.EndpointEvidenceError, match="publication is active"):
            acquisition.publish_generation(case["output"], "candidate", view.manifest_identity["sha256"], None)
    assert not (case["output"] / "current.json").exists()


def test_generation_writer_lock_and_recovery_plan_identity(case):
    """An active writer or a different recovery plan cannot be taken over implicitly."""
    with acquisition.start_generation(case["output"], "active", case["catalogue"]) as handle:
        with pytest.raises(outcomes.EndpointEvidenceError, match="active writer"):
            acquisition.recover_generation(case["output"], "active", handle.plan_sha256)
    with pytest.raises(outcomes.EndpointEvidenceError, match="plan changed"):
        acquisition.recover_generation(case["output"], "active", "0" * 64)


def test_imported_cache_blobs_are_preserved_without_reopening_per_row(tmp_path, monkeypatch):
    """Verified baseline imports bind original ledger lines and never rewrite native cached successes."""
    fixture = json.loads(FIXTURE.read_text())
    raw = tmp_path / "raw"
    (raw / "mediadive").mkdir(parents=True)
    (raw / "mediadive.json").write_text('{"data":[{"id":1}]}')
    detail = fixture["detail"]["data"]
    payloads = {
        "media_detailed.json": {"1": detail},
        "media_strains.json": {"1": fixture["strains"]["data"]},
        "solutions.json": {"10": detail["solutions"][0]},
        "compounds.json": {"4": detail["solutions"][0]["recipe"][0]},
    }
    for name, value in payloads.items():
        (raw / "mediadive" / name).write_text(json.dumps(value))
    original = seal_fixture_raw(raw)
    baseline = outcomes.cache_records(original.generation_dir / outcomes.CACHE_FILE)
    source_ledger = original.generation_dir / "evidence/synthetic-responses.jsonl"
    lines = source_ledger.read_bytes().splitlines()
    output = tmp_path / "imported"
    with acquisition.start_generation(
        output,
        "imported",
        original.native_paths["mediadive_media_list"],
        seed_cache=original.generation_dir / outcomes.CACHE_FILE,
        seed_payloads={name: original.generation_dir / name for name in payloads},
        evidence_files={"evidence/original-ledger.jsonl": source_ledger},
    ) as handle:
        calls = []
        native_persist = acquisition._persist_response

        def counted(*values):
            """Count native cache persistence without replacing actual serialization behavior."""
            calls.append(values[1]["url"])
            return native_persist(*values)

        monkeypatch.setattr(acquisition, "_persist_response", counted)
        for number, line in enumerate(lines, 1):
            record = outcomes.strict_json(line)
            row = baseline[record["request_url"]]
            response = _response(record["request_url"], outcomes.strict_json(row["body"]), row["status"])
            response._content = row["body"]
            response.headers.clear()
            response.headers.update(row["headers"])
            acquisition.record_event(
                handle,
                url=response.url,
                observed_at=record["observed_at"],
                response=response,
                source={
                    "kind": "imported",
                    "ledger": "evidence/original-ledger.jsonl",
                    "line": number,
                    "line_sha256": outcomes.sha256(line),
                },
            )
        assert calls == []
        view = acquisition.checkpoint_generation(handle)
        assert calls == []
    cached = outcomes.cache_records(view.generation_dir / outcomes.CACHE_FILE)
    assert {url: row["blob_sha256"] for url, row in cached.items()} == {
        url: row["blob_sha256"] for url, row in baseline.items()
    }


@pytest.mark.parametrize(
    "timestamps,regresses",
    [
        (["2026-11-05T19:00:00+00:00", "2026-11-05T20:00:00+02:00"], True),
        (["2026-11-05T20:00:00+02:00", "2026-11-05T19:00:00+00:00"], False),
    ],
)
def test_observation_order_compares_aware_instants(case, timestamps, regresses):
    """#1766 retains timestamp spelling while rejecting chronological regressions across offsets."""
    with acquisition.start_generation(case["output"], "timestamps", case["catalogue"]) as handle:
        url = outcomes.BASE_URL + "medium-strains/1"
        for timestamp in timestamps:
            request_id = acquisition.begin_request(handle, url)
            acquisition.record_event(
                handle,
                url=url,
                observed_at=timestamp,
                response=_response(url, case["fixture"]["unknown"], 404),
                request_id=request_id,
            )
        catalogue = outcomes.strict_json(case["catalogue"].read_bytes())
        if regresses:
            with pytest.raises(outcomes.EndpointEvidenceError, match="Observation time regressed"):
                outcomes.replay(handle.stage_dir, catalogue)
        else:
            _, states, _ = outcomes.replay(handle.stage_dir, catalogue)
            assert states[url]["observed_at"] == timestamps[-1]
            assert states[url]["state"] == "unknown_unavailable"
