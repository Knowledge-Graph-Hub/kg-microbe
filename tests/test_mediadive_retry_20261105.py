"""Offline targeted retry controls using real production requests/cache/retry code."""

import argparse
import copy
import io
import json
import shutil
from pathlib import Path

import pytest
import requests
from urllib3.response import HTTPResponse

from kg_microbe.utils import mediadive_bulk_download as production
from scripts.adhoc import kgm_mediadive_refresh_20261105 as refresh
from scripts.adhoc import kgm_mediadive_retry_20261105 as retry

FIXTURE = Path(__file__).parent / "resources/mediadive_retry_20261105.json"


@pytest.fixture
def transport(monkeypatch):
    """Replace only the actual HTTP adapter with immutable synthetic responses."""
    fixture = refresh.load_json(FIXTURE)
    hits = []
    configured = {}
    counts = {}

    def send(adapter, request, **kwargs):
        """Keep the production session, retry loop and SQLite implementation real."""
        url = request.url
        hits.append(url)
        counts[url] = counts.get(url, 0) + 1
        medium_id = url.rsplit("/", 1)[-1]
        if "/medium-strains/" in url:
            choices = configured.get(medium_id, ["strains"])
            choice = choices[min(counts[url] - 1, len(choices) - 1)]
            if choice == "transport":
                raise requests.ConnectionError("Synthetic offline transport failure")
            payload = copy.deepcopy(fixture[choice])
            status = 404 if choice in {"unknown", "malformed_unknown"} else 200
        else:
            payload = copy.deepcopy(fixture["detail"])
            payload["data"]["medium"]["id"] = medium_id
            status = 200
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        response.raw = HTTPResponse(
            body=io.BytesIO(response.content),
            status=status,
            headers=response.headers,
            preload_content=False,
            request_url=url,
        )
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(production.time, "sleep", lambda delay: None)
    yield configured, counts, hits, fixture
    production.setup_cache(None)


@pytest.fixture
def scenario(tmp_path, monkeypatch, transport):
    """Build independent tiny artifacts with the same real failed-full provenance chain."""
    configured, counts, hits, fixture = transport
    root = tmp_path / "owned"
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    source_raw = tmp_path / "original/data/raw"
    source_raw.mkdir(parents=True)
    launcher = root / "launcher.py"
    launcher.write_text("# Synthetic launcher identity only.\n")
    catalogue = {"data": [{"id": 1}, {"id": 1366}, {"id": 32}]}
    refresh.write_json(raw / "mediadive.json", catalogue)
    prior = root / retry.PRIOR
    prior.mkdir(parents=True)
    refresh.write_json(prior / "selected-media.json", catalogue)
    configured.update({"1366": ["unknown", "unknown", "transport"], "32": ["unknown"]})
    output = raw / "mediadive"
    with refresh.download_logging(production), refresh.observe_transport(prior / "http-attempts.jsonl"):
        production.download_mediadive_bulk(str(raw / "mediadive.json"), str(output), **refresh.SETTINGS)
    artifacts = refresh.snapshot_artifacts(output, prior / "artifacts")
    identity = {
        "launcher_sha256": "launcher",
        "production_sha256": "production",
        "helper_sha256": "refresh",
        "dependencies": {},
        "python": "synthetic",
        "python_version": "synthetic",
        "catalogue_sha256": refresh.digest(raw / "mediadive.json"),
    }
    receipt = {
        "status": "failed",
        "identity": identity,
        "artifacts": artifacts,
        "http_attempts_sha256": refresh.digest(prior / "http-attempts.jsonl"),
    }
    refresh.write_json(prior / "receipt.json", receipt)
    receipt_sha = refresh.digest(prior / "receipt.json")
    unresolved = {refresh.BASE_URL + "medium-strains/" + key: {} for key in ("1366", "32")}
    refresh.write_json(prior / "failure-accounting.json", {"failed_endpoints": unresolved})
    preservation = root / retry.RETRY / "preservation"
    preservation.mkdir(parents=True)
    shutil.copytree(output, preservation / "raw-mediadive")
    for name in ("receipt.json", "http-attempts.jsonl", "failure-accounting.json", "selected-media.json"):
        shutil.copy2(prior / name, preservation / name)
    originals = (
        list(output.iterdir())
        + [path for path in prior.iterdir() if path.is_file()]
        + list((prior / "artifacts").iterdir())
    )
    protected = root / "ontology-review.txt"
    protected.write_text("Unchanged scientific review evidence.\n")
    manifest = {
        "status": "preserved_before_retry",
        "prior_full_receipt_sha256": receipt_sha,
        "original_files": [{"path": str(path.relative_to(root)), **retry.file_identity(path)} for path in originals],
        "protected_ontology_and_review_artifacts": [
            {"path": str(protected.relative_to(root)), **retry.file_identity(protected)}
        ],
    }
    refresh.write_json(preservation / "manifest.json", manifest)
    monkeypatch.setattr(retry, "ROOT", root)
    monkeypatch.setattr(retry, "BASELINE_COUNTS", (3, 4, 2))
    monkeypatch.setattr(retry, "PRIOR_RECEIPT_SHA256", receipt_sha)
    monkeypatch.setattr(retry, "PRESERVATION_MANIFEST_SHA256", refresh.digest(preservation / "manifest.json"))
    monkeypatch.setattr(refresh, "validate_layout", lambda *args: {})
    monkeypatch.setattr(retry, "runtime_identity", lambda *args: copy.deepcopy(identity))
    configured.clear()
    counts.clear()
    hits.clear()
    args = argparse.Namespace(source_raw=source_raw, launcher=launcher, attempt="retry-test", execute=True)
    return root, output, args


def fingerprints(root):
    """Capture all fixture files to prove planning and refusal are read-only."""
    return {str(path.relative_to(root)): retry.file_identity(path) for path in root.rglob("*") if path.is_file()}


def test_plan_is_read_only(scenario, transport):
    """Planning verifies the original cache and all outputs without HTTP or writes."""
    root, _, args = scenario
    args.execute = False
    before = fingerprints(root)
    plan = retry.run(args)
    assert plan["status"] == "planned"
    assert plan["selected_count"] == 2
    assert plan["maximum_transport_attempts"] == 6
    assert fingerprints(root) == before
    assert not transport[2]


def test_documented_unknown_canary_allows_batch_without_admission(scenario, transport):
    """A fresh exact 404 verifies execution; only the other fresh 200 becomes data."""
    root, output, args = scenario
    transport[0].update({"1366": ["unknown"], "32": ["strains"]})
    old = {name: refresh.digest(output / name) for name in refresh.JSON_NAMES if name != "media_strains.json"}
    baseline = retry.read_cache(output / refresh.CACHE_NAME, empty_sidecars=True)
    result = retry.run(args)
    assert result["status"] == "blocked" and not result["association_admission"]
    assert result["canary_execution"] == "verified_unknown"
    assert result["combined_valid_endpoints"] == 5
    assert result["recovered_endpoints"] == 1
    assert result["remaining_unresolved_urls"] == [refresh.BASE_URL + "medium-strains/1366"]
    assert [url.rsplit("/", 1)[-1] for url in transport[2]] == ["1366"] * 3 + ["32"]
    assert set(refresh.load_json(output / "media_strains.json")) == {"1", "32"}
    assert {name: refresh.digest(output / name) for name in old} == old
    current = retry.read_cache(output / refresh.CACHE_NAME, empty_sidecars=True)
    assert all(current[url]["body_sha256"] == value["body_sha256"] for url, value in baseline.items())
    evidence = Path(result["evidence"])
    canary = refresh.load_json(evidence / "canary/receipt.json")
    assert canary["outcome_counts"] == {"unknown_404": 1}
    assert not canary["fresh_valid_endpoints"]
    assert len(list((evidence / "canary/bodies").iterdir())) == 3
    retry.check_preservation(root, refresh.load_json(root / retry.RETRY / "preservation/manifest.json"))


def test_recovered_canary_and_valid_empty_batch_admit_complete_coverage(scenario, transport):
    """An observed persisted empty list counts as covered while native JSON omits it."""
    _, output, args = scenario
    transport[0].update({"1366": ["strains"], "32": ["empty"]})
    result = retry.run(args)
    assert result["status"] == "passed" and result["association_admission"]
    assert result["combined_valid_endpoints"] == 6
    assert result["recovered_endpoints"] == 2
    assert not result["remaining_unresolved_urls"]
    assert set(refresh.load_json(output / "media_strains.json")) == {"1", "1366"}
    batch = refresh.load_json(Path(result["evidence"]) / "batch/receipt.json")
    assert batch["outcome_counts"] == {"valid_empty": 1}
    assert len(transport[2]) == 2


@pytest.mark.parametrize("canary_kind", ["transport", "malformed_unknown"])
def test_unverified_canary_stops_before_batch(scenario, transport, canary_kind):
    """Transport failures, malformed errors and invalid success JSON cannot open the batch."""
    root, output, args = scenario
    transport[0]["1366"] = [canary_kind]
    before = refresh.digest(output / "media_strains.json")
    result = retry.run(args)
    assert result["status"] == "blocked" and not result["association_admission"]
    assert result["canary_execution"] == "unverified"
    assert result["recovered_endpoints"] == 0
    assert all(url.endswith("/1366") for url in transport[2])
    assert not (root / retry.RETRY / "attempts/retry-test/batch").exists()
    assert refresh.digest(output / "media_strains.json") == before


def test_transport_in_batch_retains_canary_recovery(scenario, transport):
    """Partial fresh data survives an unresolved batch without a successful receipt."""
    _, output, args = scenario
    transport[0].update({"1366": ["strains"], "32": ["transport"]})
    result = retry.run(args)
    assert result["status"] == "blocked" and result["recovered_endpoints"] == 1
    assert not result["association_admission"]
    assert "1366" in refresh.load_json(output / "media_strains.json")
    assert refresh.load_json(Path(result["evidence"]) / "batch/receipt.json")["outcome_counts"] == {
        "transport_error": 1
    }


def test_existing_attempt_collision_is_read_only(scenario, transport):
    """A duplicate label cannot consume a request or replace retained evidence."""
    root, _, args = scenario
    destination = root / retry.RETRY / "attempts/retry-test"
    destination.mkdir(parents=True)
    (destination / "receipt.json").write_text("Prior immutable evidence.\n")
    before = fingerprints(root)
    with pytest.raises(ValueError, match="already exists"):
        retry.run(args)
    assert fingerprints(root) == before
    assert not transport[2]


def test_manifest_tampering_is_refused(scenario, transport):
    """A relabelled preservation manifest is not a new approved baseline."""
    root, _, args = scenario
    (root / retry.RETRY / "preservation/manifest.json").write_text("{}\n")
    with pytest.raises(ValueError, match="manifest identity"):
        retry.run(args)
    assert not transport[2]


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_preexisting_selected_cache_is_refused(scenario, transport, journal_mode):
    """Reject a selected cached response in DELETE mode or with a live empty WAL."""
    import sqlite3
    from contextlib import closing

    root, output, _ = scenario
    # Verify the sealed baseline before deliberately adding an unapproved response.
    # Calling run() afterwards would stop at the changed preservation manifest,
    # before reaching the selected-response guard this control must exercise.
    baseline = retry.baseline(root, production)
    production.setup_cache(output)
    production.download_medium_strains([{"id": 1366}], **retry.SETTINGS)
    production._reset_sessions()
    transport[2].clear()
    cache = output / refresh.CACHE_NAME
    phase_dir = root / "preexisting-cache-phase"
    with closing(sqlite3.connect(cache)) as lifecycle:
        assert lifecycle.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        assert lifecycle.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
        if journal_mode == "wal":
            assert lifecycle.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            lifecycle.execute("BEGIN IMMEDIATE")
            lifecycle.commit()
            lifecycle.execute("SELECT count(*) FROM responses").fetchone()
            assert lifecycle.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        wal = cache.with_name(cache.name + "-wal")
        shm = cache.with_name(cache.name + "-shm")
        assert wal.exists() == (journal_mode == "wal")
        if journal_mode == "wal":
            assert shm.exists()
            assert wal.stat().st_size == 0
        # SQLite may retain SHM after switching to DELETE mode. Its presence
        # carries no pending writes without WAL; preserve its bytes if present.
        records = retry.read_cache(cache, empty_sidecars=True)
        selected_url = refresh.BASE_URL + "medium-strains/1366"
        assert records[selected_url]["valid"]
        before_refusal = fingerprints(output)
        with pytest.raises(ValueError, match="^Preexisting selected target cache entry$"):
            retry.phase(
                phase_dir, [{"id": 1366}], output, baseline["accepted"], baseline["ids"], production, lambda: None
            )
        assert fingerprints(output) == before_refusal
    assert not transport[2]
    assert not (phase_dir / "started.json").exists()


def test_runtime_drift_prevents_batch(scenario, transport, monkeypatch):
    """The same-process canary cannot authorize a changed environment or helper."""
    _, _, args = scenario
    original = retry.runtime_identity
    calls = []

    def changed(*values):
        """Return a changed runtime identity after the canary begins."""
        calls.append(None)
        identity = original(*values)
        if len(calls) >= 3:
            identity["changed_environment"] = True
        return identity

    monkeypatch.setattr(retry, "runtime_identity", changed)
    with pytest.raises(ValueError, match="runtime/input identity changed"):
        retry.run(args)
    assert all(url.endswith("/1366") for url in transport[2])
    receipt = refresh.load_json(retry.ROOT / retry.RETRY / "attempts/retry-test/receipt.json")
    assert receipt["status"] == "failed" and not receipt["association_admission"]


def test_raw_body_tampering_is_refused(tmp_path):
    """Retained raw bodies must independently support their ledger classifications."""
    directory = tmp_path / "phase"
    directory.mkdir()
    (directory / "body").write_bytes(b"tampered")
    event = {"body_path": "body", "body_sha256": "wrong", "body_bytes": 8}
    with pytest.raises(ValueError, match="body evidence changed"):
        retry.verify_bodies(directory, {refresh.BASE_URL + "medium-strains/1366": [event]})


def test_observer_rejects_unselected_endpoint_before_transport(tmp_path, transport):
    """No accidental recipe reload or redirect destination may reach the adapter."""
    with retry.observe_retry(tmp_path, {refresh.BASE_URL + "medium-strains/1366"}):
        with pytest.raises(ValueError, match="Unselected transport"):
            requests.get(refresh.BASE_URL + "medium/1366", timeout=1)
    assert not transport[2]


def test_observer_enforces_three_attempt_ceiling(tmp_path, transport):
    """Request observation fails before a fourth physical request can be sent."""
    url = refresh.BASE_URL + "medium-strains/1366"
    with retry.observe_retry(tmp_path, {url}):
        for _ in range(3):
            requests.get(url, timeout=1)
        with pytest.raises(ValueError, match="attempt budget"):
            requests.get(url, timeout=1)
    assert len(transport[2]) == 3


def test_nonempty_wal_is_not_ignored(scenario):
    """Immutable mode cannot silently discard pending native cache writes."""
    _, output, _ = scenario
    cache = output / refresh.CACHE_NAME
    cache.with_name(cache.name + "-wal").write_bytes(b"not checkpointed")
    with pytest.raises(ValueError, match="Unconsumed live SQLite WAL"):
        retry.read_cache(cache, empty_sidecars=True)


@pytest.mark.parametrize("kind", ["invalid", "contradictory_empty", "null_id", "wrong_count", "duplicate_keys"])
def test_invalid_cached_200_fails_before_overlay(scenario, transport, kind):
    """Invalid HTTP 200 cache rows are quarantined as failure evidence, never coverage."""
    root, output, args = scenario
    transport[0]["1366"] = [kind]
    before = refresh.digest(output / "media_strains.json")
    with pytest.raises(ValueError, match="Cache URL union"):
        retry.run(args)
    destination = root / retry.RETRY / "attempts/retry-test"
    receipt = refresh.load_json(destination / "receipt.json")
    assert receipt["status"] == "failed" and not receipt["association_admission"]
    assert (destination / "canary/artifacts" / refresh.CACHE_NAME).is_file()
    assert len(list((destination / "canary/bodies").iterdir())) == 1
    assert not (destination / "batch").exists()
    assert refresh.digest(output / "media_strains.json") == before


def test_payload_kind_is_recomputed_from_raw_body(tmp_path, transport):
    """Changing a nonempty success to an empty classification cannot survive replay."""
    url = refresh.BASE_URL + "medium-strains/1366"
    with retry.observe_retry(tmp_path, {url}):
        requests.get(url, timeout=1)
    grouped = retry.ledger(tmp_path / "http-attempts.jsonl", {url})
    grouped[url][0]["payload_kind"] = "empty_strains"
    with pytest.raises(ValueError, match="payload kind differs"):
        retry.verify_bodies(tmp_path, grouped)


def test_original_cache_metadata_tampering_is_rejected(scenario, transport, monkeypatch):
    """Changing only headers in an old serialized response is a preservation failure."""
    import sqlite3

    from requests_cache.serializers import pickle_serializer

    root, output, args = scenario
    native = production.download_medium_strains

    def changed(*values, **kwargs):
        """Alter an original cached response header after the native request."""
        result = native(*values, **kwargs)
        production._reset_sessions()
        with sqlite3.connect(output / refresh.CACHE_NAME) as connection:
            key, blob = next(
                (key, blob)
                for key, blob in connection.execute("SELECT key, value FROM responses")
                if pickle_serializer.loads(blob).url.endswith("/medium/1")
            )
            response = pickle_serializer.loads(blob)
            response.headers["X-Unreviewed-Metadata"] = "changed without changing the body"
            connection.execute("UPDATE responses SET value=? WHERE key=?", (pickle_serializer.dumps(response), key))
        return result

    monkeypatch.setattr(production, "download_medium_strains", changed)
    before = refresh.digest(output / "media_strains.json")
    with pytest.raises(ValueError, match="serialized response changed|response differs from actual HTTP"):
        retry.run(args)
    assert refresh.digest(output / "media_strains.json") == before
    assert refresh.load_json(root / retry.RETRY / "attempts/retry-test/receipt.json")["status"] == "failed"


def test_redirect_table_is_rejected(scenario):
    """A hidden cached redirect cannot redirect selected requests into stale responses."""
    import sqlite3

    _, output, _ = scenario
    cache = output / refresh.CACHE_NAME
    with sqlite3.connect(cache) as connection:
        connection.execute("INSERT INTO redirects (key,value) VALUES (?,?)", ("unexpected", "target"))
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(ValueError, match="cached redirect"):
        retry.read_cache(cache, empty_sidecars=True)


def test_interruption_after_http_persistence_preserves_evidence(scenario, transport, monkeypatch):
    """An interrupted phase retains fresh cache evidence without publishing or admission."""
    root, output, args = scenario
    native = production.download_medium_strains

    def interrupted(*values, **kwargs):
        """Interrupt after the production request has persisted its response."""
        native(*values, **kwargs)
        raise KeyboardInterrupt("Synthetic interruption after HTTP persistence")

    monkeypatch.setattr(production, "download_medium_strains", interrupted)
    before = refresh.digest(output / "media_strains.json")
    with pytest.raises(KeyboardInterrupt):
        retry.run(args)
    destination = root / retry.RETRY / "attempts/retry-test"
    receipt = refresh.load_json(destination / "receipt.json")
    assert receipt["status"] == "failed" and not receipt["association_admission"]
    assert (destination / "canary/artifacts" / refresh.CACHE_NAME).is_file()
    assert refresh.load_json(destination / "canary/receipt.json")["status"] == "failed"
    assert refresh.digest(output / "media_strains.json") == before
    assert not (destination / "batch").exists()


def test_final_receipt_failure_cannot_claim_admission(scenario, transport, monkeypatch):
    """Failure before a final receipt retains phase proof and an explicitly non-admitted start."""
    root, output, args = scenario
    write = refresh.write_json
    final = root / retry.RETRY / "attempts/retry-test/receipt.json"

    def fail_final(path, payload):
        """Refuse only the final receipt publication while retaining prior evidence."""
        if path == final:
            raise OSError("Synthetic final receipt publication failure")
        return write(path, payload)

    monkeypatch.setattr(refresh, "write_json", fail_final)
    with pytest.raises(OSError, match="final receipt"):
        retry.run(args)
    assert not final.exists()
    start = refresh.load_json(final.parent / "started.json")
    assert start["status"] == "running" and not start["association_admission"]
    assert (final.parent / "after" / refresh.CACHE_NAME).is_file()
    # A second invocation cannot reinterpret the changed raw generation as the old baseline.
    args.attempt = "second-attempt"
    with pytest.raises(ValueError, match="Input changed"):
        retry.run(args)


def test_compound_extraction_preserves_catalogue_order_with_reversed_cache(tmp_path):
    """Repeated compound records retain the native first occurrence despite SQLite order."""
    details = refresh.load_json(FIXTURE)["order_sensitive_details"]
    production.save_json_file(details, tmp_path / "media_detailed.json", "synthetic ordered details")
    production.save_json_file({}, tmp_path / "media_strains.json", "synthetic strains")
    production.save_json_file(
        production.extract_solutions_from_media(details), tmp_path / "solutions.json", "solutions"
    )
    production.save_json_file(
        production.extract_compounds_from_media(details), tmp_path / "compounds.json", "compounds"
    )
    records = {
        refresh.BASE_URL + "medium/" + key: {"valid": True, "payload": {"data": details[key]}}
        for key in reversed(details)
    }
    before = fingerprints(tmp_path)
    assert production.extract_compounds_from_media(dict(reversed(list(details.items())))) != refresh.load_json(
        tmp_path / "compounds.json"
    )
    retry.validate_outputs(tmp_path, records, ["1", "2"], production)
    assert fingerprints(tmp_path) == before
    # Reversing the native detailed artifact itself is different from SQLite row order.
    (tmp_path / "media_detailed.json").write_text(json.dumps(dict(reversed(list(details.items())))))
    with pytest.raises(ValueError, match="catalogue order changed"):
        retry.validate_outputs(tmp_path, records, ["1", "2"], production)


@pytest.mark.parametrize("change", ["live_extra", "live_metadata", "retained_metadata", "retained_json"])
def test_final_cache_and_retained_snapshot_are_verified_before_admission(scenario, monkeypatch, change):
    """Actual post-phase/cache-backup mutations cannot bypass the final admission boundary."""
    import sqlite3

    from requests_cache.cache_keys import create_key
    from requests_cache.serializers import pickle_serializer

    root, output, args = scenario

    def mutate_cache(cache, extra=False):
        """Change persisted metadata or insert an unselected response row."""
        with sqlite3.connect(cache) as connection:
            key, blob = next(
                (key, blob)
                for key, blob in connection.execute("SELECT key, value FROM responses")
                if pickle_serializer.loads(blob).url.endswith("/medium-strains/1")
            )
            response = pickle_serializer.loads(blob)
            if extra:
                response.url = refresh.BASE_URL + "medium-strains/unselected"
                response.request.url = response.url
                key = create_key(response.request, serializer=pickle_serializer)
                connection.execute(
                    "INSERT INTO responses (key,value) VALUES (?,?)", (key, pickle_serializer.dumps(response))
                )
            else:
                response.headers["X-Unreviewed-Final-Metadata"] = "changed"
                connection.execute("UPDATE responses SET value=? WHERE key=?", (pickle_serializer.dumps(response), key))
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    native_phase = retry.phase
    native_snapshot = refresh.snapshot_artifacts

    def phase_with_final_mutation(*values, **kwargs):
        """Mutate the live cache after the batch has completed its phase checks."""
        result = native_phase(*values, **kwargs)
        if values[0].name == "batch" and change.startswith("live_"):
            mutate_cache(output / refresh.CACHE_NAME, extra=change == "live_extra")
        return result

    def snapshot_with_retained_mutation(source, destination):
        """Alter retained final evidence after the native snapshot is created."""
        result = native_snapshot(source, destination)
        if destination.name == "after":
            if change == "retained_metadata":
                mutate_cache(destination / refresh.CACHE_NAME)
            elif change == "retained_json":
                (destination / "compounds.json").write_text("{}\n")
        return result

    monkeypatch.setattr(retry, "phase", phase_with_final_mutation)
    monkeypatch.setattr(refresh, "snapshot_artifacts", snapshot_with_retained_mutation)
    with pytest.raises(ValueError, match="Final cache URL union|Final cache response identity|Compounds changed"):
        retry.run(args)
    receipt = refresh.load_json(root / retry.RETRY / "attempts/retry-test/receipt.json")
    assert receipt["status"] == "failed" and not receipt["association_admission"]
