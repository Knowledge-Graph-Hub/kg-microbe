#!/usr/bin/env python3
"""
Retry only the 632 unresolved strain endpoints retained for issue #1734.

Default: read-only plan. Explicit execution uses the saved launcher, the existing
production request/cache/retry implementation, and one process for canary/batch.
A documented 404 verifies execution only; it never establishes empty associations.
Prior evidence is immutable. Partial fresh recovery cannot admit the full source.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.adhoc import kgm_mediadive_refresh_20261105 as refresh

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("data/rebuild-evidence/20261105")
PRIOR = EVIDENCE / "mediadive/attempts/sequence-1/full"
RETRY = EVIDENCE / "mediadive-retry-1734"
PRIOR_RECEIPT_SHA256 = "d792f4def31b55e3e2aca041e4c1d45ef0f86e2b20427e7be78e84d168ffa840"
PRESERVATION_MANIFEST_SHA256 = "d63d0a6be750bc6f1f436aeb82e22d04c2d457fb0a3dac670d1f5b44f9990368"
BASELINE_COUNTS = (3344, 6056, 632)
CANARY_ID = "1366"
SETTINGS = {"max_workers": 5, "retry_count": 3, "retry_delay": 2.0}
UNKNOWN_MESSAGE = "Medium does not exist or composition was not calculated"
require = refresh.require


def file_identity(path):
    """Identify a regular independently owned file."""
    require(path.is_file() and not path.is_symlink(), f"Missing or linked input: {path}")
    require(path.stat().st_nlink == 1, f"Shared input inode: {path}")
    return {"sha256": refresh.digest(path), "bytes": path.stat().st_size}


def match_record(path, record):
    """Refuse changed bytes, including recorded zero-length WAL files."""
    require(file_identity(path) == {k: record[k] for k in ("sha256", "bytes")}, f"Input changed: {path}")


def owned_path(root, relative):
    """Reject escaping paths and symlinks in a retained manifest."""
    relative = Path(relative)
    require(not relative.is_absolute() and ".." not in relative.parts, "Manifest path escapes worktree")
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        require(not part.is_symlink(), f"Linked evidence path: {part}")
    require(path.resolve().is_relative_to(root), "Manifest path escapes worktree")
    return path


def check_preservation(root, manifest, initial=False):
    """Bind all preserved original files and the protected ontology/review outputs."""
    preservation = root / RETRY / "preservation"
    require(manifest["status"] == "preserved_before_retry", "Wrong preservation status")
    for record in manifest["original_files"]:
        path = owned_path(root, record["path"])
        if path.parent == root / "data/raw/mediadive":
            match_record(preservation / "raw-mediadive" / path.name, record)
            if initial or path.name in {*refresh.JSON_NAMES, "mediadive_download.log"} - {"media_strains.json"}:
                match_record(path, record)
        else:
            match_record(path, record)
            if path.parent == root / PRIOR:
                match_record(preservation / path.name, record)
    for record in manifest["protected_ontology_and_review_artifacts"]:
        match_record(owned_path(root, record["path"]), record)


def strict_json(body):
    """Reject duplicate keys and nonstandard constants in all retained JSON levels."""

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError(f"Nonstandard JSON constant: {value}")

    return json.loads(body, object_pairs_hook=pairs, parse_constant=reject_constant)


def strain_payload(payload):
    """Validate the documented list envelope and actual native association ID type."""
    require(
        isinstance(payload, dict) and set(payload) == {"status", "count", "data"}, "Unexpected strain envelope fields"
    )
    require(type(payload["status"]) is int and payload["status"] == 200, "Strain envelope status is not 200")
    data = payload["data"]
    require(isinstance(data, list), "Strain response data must be a list")
    require(
        type(payload["count"]) is int and payload["count"] == len(data),
        "Strain envelope count differs from list length",
    )
    require(
        all(isinstance(item, dict) and type(item.get("id")) is int and item["id"] >= 0 for item in data),
        "Invalid native strain association ID",
    )
    return "empty_strains" if not data else "strains"


def response_record(url, response):
    """Bind transport metadata and strict payload shape, independently of old helper flags."""
    record = refresh.response_record(url, response)
    record.update(
        {
            "valid": False,
            "response_headers": dict(response.headers),
            "prepared_request_url": getattr(response.request, "url", None),
            "request_method": getattr(response.request, "method", None),
        }
    )
    try:
        require(response.status_code == 200, "HTTP status is not 200")
        require(response.url == url and record["prepared_request_url"] == url, "Request/response URL differs")
        require(record["request_method"] == "GET", "Request method is not GET")
        require(
            response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == "application/json",
            "Response content type is not JSON",
        )
        payload = strict_json(response.content)
        record["payload_kind"] = (
            strain_payload(payload) if "/medium-strains/" in url else refresh.validate_payload(url, payload)
        )
        record["valid"] = True
        record.pop("validation_error", None)
    except (ValueError, TypeError, UnicodeError) as exc:
        record["validation_error"] = str(exc)
    return record


def read_cache(path, empty_sidecars=False):
    """Read fresh immutable SQLite only after rejecting any unconsumed WAL bytes."""
    before = file_identity(path)
    sidecars = {}
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if os.path.lexists(sidecar):
            require(empty_sidecars and suffix != "-journal", f"Unexpected SQLite sidecar: {sidecar}")
            sidecars[sidecar] = file_identity(sidecar)
            require(suffix != "-wal" or sidecar.stat().st_size == 0, "Unconsumed live SQLite WAL")
    from requests_cache.cache_keys import create_key
    from requests_cache.serializers import pickle_serializer

    records = {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as reader:
        require(reader.execute("PRAGMA quick_check").fetchone() == ("ok",), "SQLite integrity failure")
        require(reader.execute("SELECT count(*) FROM redirects").fetchone() == (0,), "Unexpected cached redirect")
        for key, blob in reader.execute("SELECT key, value FROM responses"):
            require(bool(blob), "Empty cached response")
            response = pickle_serializer.loads(blob)
            require(
                key == create_key(response.request, serializer=pickle_serializer), "Persisted request cache key differs"
            )
            require(response.url not in records, "Repeated cached response URL")
            record = response_record(response.url, response)
            record["serialized_value_sha256"] = hashlib.sha256(blob).hexdigest()
            record["cache_key"] = key
            # Invalid successful HTTP JSON remains evidence, never an association.
            try:
                record["payload"] = strict_json(response.content)
            except (ValueError, UnicodeError):
                record["payload"] = None
            records[response.url] = record
    match_record(path, before)
    for sidecar, recorded in sidecars.items():
        match_record(sidecar, recorded)
    return records


def ledger(path, expected):
    """Read bounded observed attempts without converting failures into empty lists."""
    grouped = {}
    for line in path.read_text().splitlines():
        event = json.loads(line)
        url = event["request_url"]
        require(url in expected, f"Unexpected observed endpoint: {url}")
        grouped.setdefault(url, []).append(event)
    for url, events in grouped.items():
        require(len(events) <= SETTINGS["retry_count"], f"Retry budget exceeded: {url}")
        successes = [e for e in events if e.get("valid")]
        require(len(successes) <= 1 and (not successes or successes[0] == events[-1]), "Repeated success")
        require(not any(e.get("from_cache") for e in events), "Observed response came from cache")
    return grouped


def validate_outputs(directory, records, media_ids, production):
    """Independently compare all four native outputs to accepted persisted responses."""
    objects = {name: refresh.load_json(directory / name) for name in refresh.JSON_NAMES}
    require(all(isinstance(value, dict) for value in objects.values()), "Output must contain JSON objects")
    details, strains = {}, {}
    for url, record in records.items():
        require(record["valid"], f"Unvalidated response used as coverage: {url}")
        data = record["payload"]["data"]
        medium_id = url.rsplit("/", 1)[-1]
        if "/medium-strains/" in url:
            if data:
                strains[medium_id] = data
        else:
            details[medium_id] = data
    require(set(details) == set(media_ids), "Detailed medium coverage changed")
    require(list(objects["media_detailed.json"]) == list(media_ids), "Detailed medium catalogue order changed")
    # Native extraction keeps the first occurrence of each solution/compound.
    # SQLite row order cannot replace the original catalogue/detailed JSON order.
    details = {medium_id: details[medium_id] for medium_id in media_ids}
    require(objects["media_detailed.json"] == details, "Detailed JSON differs from cache")
    require(objects["media_strains.json"] == strains, "Strain JSON differs from accepted cache")
    require(objects["solutions.json"] == production.extract_solutions_from_media(details), "Solutions changed")
    require(objects["compounds.json"] == production.extract_compounds_from_media(details), "Compounds changed")


def validate_cache_coverage(records, accepted):
    """Require exactly the admitted response rows, including immutable serialized metadata."""
    require(set(records) == set(accepted), "Final cache URL union differs from accepted coverage")
    for url, expected in accepted.items():
        require(records[url]["valid"], f"Final cache contains invalid response: {url}")
        for key in ("body_sha256", "serialized_value_sha256", "cache_key"):
            require(records[url][key] == expected[key], f"Final cache response identity differs: {url}: {key}")


def baseline(root, production):
    """Recompute the exact 6056/632 baseline from original ledger and native cache."""
    prior = root / PRIOR
    require(refresh.digest(prior / "receipt.json") == PRIOR_RECEIPT_SHA256, "Prior receipt identity changed")
    receipt = refresh.load_json(prior / "receipt.json")
    require(receipt["status"] == "failed", "Expected the preserved failed full refresh")
    require(
        refresh.digest(root / RETRY / "preservation/manifest.json") == PRESERVATION_MANIFEST_SHA256,
        "Preservation manifest identity changed",
    )
    manifest = refresh.load_json(root / RETRY / "preservation/manifest.json")
    require(manifest["prior_full_receipt_sha256"] == PRIOR_RECEIPT_SHA256, "Preservation receipt differs")
    check_preservation(root, manifest, initial=True)
    require(refresh.digest(prior / "http-attempts.jsonl") == receipt["http_attempts_sha256"], "Prior ledger changed")
    for name, checksum in receipt["artifacts"].items():
        require(refresh.digest(prior / "artifacts" / name) == checksum, f"Prior artifact changed: {name}")
    catalogue = refresh.select_media(refresh.load_json(root / "data/raw/mediadive.json"), "full")
    require(refresh.load_json(prior / "selected-media.json")["data"] == catalogue, "Catalogue changed")
    require(
        refresh.digest(root / "data/raw/mediadive.json") == receipt["identity"]["catalogue_sha256"],
        "Catalogue bytes changed",
    )
    ids = [str(item["id"]) for item in catalogue]
    expected = {refresh.BASE_URL + endpoint + key for endpoint in ("medium/", "medium-strains/") for key in ids}
    grouped = ledger(prior / "http-attempts.jsonl", expected)
    require(set(grouped) == expected, "Prior endpoint coverage changed")
    accepted = {url: events[-1] for url, events in grouped.items() if events[-1].get("valid")}
    unresolved = set(expected) - accepted.keys()
    require(
        (len(ids), len(accepted), len(unresolved)) == BASELINE_COUNTS, "Baseline coverage is not the reviewed 6056/632"
    )
    require(
        all(url.startswith(refresh.BASE_URL + "medium-strains/") for url in unresolved), "Non-strain retry selected"
    )
    accounting = refresh.load_json(prior / "failure-accounting.json")
    require(set(accounting["failed_endpoints"]) == unresolved, "Failure accounting disagrees with ledger")
    records = read_cache(prior / "artifacts" / refresh.CACHE_NAME)
    current = read_cache(root / "data/raw/mediadive" / refresh.CACHE_NAME, empty_sidecars=True)
    require(
        set(records) == set(current) == set(accepted), "Preexisting target cache entry or baseline coverage changed"
    )
    for url, event in accepted.items():
        require(records[url]["valid"] and current[url]["valid"], "Invalid baseline response")
        require(
            records[url]["body_sha256"] == current[url]["body_sha256"] == event["body_sha256"],
            "Baseline response body changed",
        )
        require(
            records[url]["serialized_value_sha256"] == current[url]["serialized_value_sha256"],
            "Baseline serialized response changed",
        )
    validate_outputs(root / "data/raw/mediadive", current, ids, production)
    canary = refresh.BASE_URL + "medium-strains/" + CANARY_ID
    require(canary in unresolved, "Canary is not unresolved")
    require(grouped[canary][-1].get("transport_error") == "ConnectionError", "Canary history changed")
    accepted = {
        url: {
            **event,
            "serialized_value_sha256": current[url]["serialized_value_sha256"],
            "cache_key": current[url]["cache_key"],
        }
        for url, event in accepted.items()
    }
    return {
        "manifest": manifest,
        "receipt": receipt,
        "catalogue": catalogue,
        "ids": ids,
        "accepted": accepted,
        "records": current,
        "unresolved": unresolved,
        "history": grouped,
    }


def runtime_identity(root, source_raw, launcher, production):
    """Keep launcher/runtime/code identities equal throughout both retry phases."""
    identity = refresh.identity(root, source_raw, launcher, production)
    identity.update(
        {
            "retry_helper_sha256": refresh.digest(__file__),
            "settings": SETTINGS,
            "cache_policy": "preserve baseline; every selected endpoint must be absent",
            "preservation_manifest": file_identity(root / RETRY / "preservation/manifest.json"),
        }
    )
    return identity


def unknown_envelope(payload):
    """Recognize the exact documented error without assigning association meaning."""
    return (
        isinstance(payload, dict)
        and type(payload.get("status")) is int
        and type(payload.get("count")) is int
        and payload == {"status": 404, "count": 0, "error": "DataNotFound", "msg": UNKNOWN_MESSAGE}
    )


@contextmanager
def observe_retry(directory, selected):
    """Bound actual transport and durably retain every fresh raw response body."""
    import requests

    original_send = requests.adapters.HTTPAdapter.send
    lock = threading.Lock()
    counts = Counter()
    bodies = directory / "bodies"
    bodies.mkdir()
    with (directory / "http-attempts.jsonl").open("x") as stream:

        def save(event, body=None):
            with lock:
                if body is not None:
                    name = f"{event['attempt']:02d}-{hashlib.sha256(event['request_url'].encode()).hexdigest()}.body"
                    with (bodies / name).open("xb") as target:
                        target.write(body)
                        target.flush()
                        os.fsync(target.fileno())
                    event["body_path"] = "bodies/" + name
                event["observed_at"] = datetime.now(timezone.utc).isoformat()
                stream.write(json.dumps(event, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        def observed_send(session, request, **kwargs):
            with lock:
                require(request.url in selected, f"Unselected transport URL: {request.url}")
                counts[request.url] += 1
                number = counts[request.url]
                require(number <= SETTINGS["retry_count"], "Transport attempt budget exceeded")
                require(request.method == "GET", "Unexpected request method")
            try:
                response = original_send(session, request, **kwargs)
            except requests.RequestException as exc:
                save(
                    {
                        "request_url": request.url,
                        "attempt": number,
                        "valid": False,
                        "transport_error": type(exc).__name__,
                    }
                )
                raise
            event = response_record(request.url, response)
            event["attempt"] = number
            event["valid"] = event["valid"] and response.status_code == 200
            try:
                event["documented_unknown"] = response.status_code == 404 and unknown_envelope(
                    strict_json(response.content)
                )
            except (ValueError, UnicodeError):
                event["documented_unknown"] = False
            save(event, response.content)
            return response

        with patch.object(requests.adapters.HTTPAdapter, "send", observed_send):
            yield


def verify_bodies(directory, grouped):
    """Reopen saved bodies independently; never trust observation flags alone."""
    for url, events in grouped.items():
        for event in events:
            if "body_path" not in event:
                require("transport_error" in event, "Missing transport body or error")
                continue
            body = owned_path(directory, event["body_path"]).read_bytes()
            require(
                hashlib.sha256(body).hexdigest() == event["body_sha256"] and len(body) == event["body_bytes"],
                "Response body evidence changed",
            )
            require(event["response_url"] == url, "Redirected response")
            try:
                payload = strict_json(body)
            except (ValueError, UnicodeError):
                payload = None
            valid = False
            if event["status"] == 200:
                try:
                    strain_payload(payload)
                    require(
                        event["prepared_request_url"] == url and event["request_method"] == "GET",
                        "Request metadata differs",
                    )
                    content_type = {key.lower(): value for key, value in event["response_headers"].items()}.get(
                        "content-type", ""
                    )
                    require(content_type.split(";", 1)[0].strip().lower() == "application/json", "Content type differs")
                    valid = True
                except (ValueError, TypeError):
                    pass
            require(event["valid"] == valid, "Observed payload validity differs from raw body")
            if valid:
                require(event["payload_kind"] == strain_payload(payload), "Observed payload kind differs from raw body")
            require(
                event.get("documented_unknown", False) == (event["status"] == 404 and unknown_envelope(payload)),
                "Unknown response envelope changed",
            )


def classify(event):
    """Keep valid empty, unknown absence, invalid data and transport separate."""
    if event is None:
        return "not_attempted"
    if event.get("valid"):
        return "valid_empty" if event["payload_kind"] == "empty_strains" else "recovered"
    if event.get("transport_error"):
        return "transport_error"
    if event.get("documented_unknown"):
        return "unknown_404"
    return "unresolved_http_or_payload"


def phase(directory, selected, output, accepted, media_ids, production, guard):
    """Run one native subset, then verify persistence before publishing an overlay."""
    directory.mkdir()
    refresh.write_json(directory / "selected-media.json", {"data": selected})
    urls = {refresh.BASE_URL + "medium-strains/" + str(item["id"]) for item in selected}
    before = read_cache(output / refresh.CACHE_NAME, empty_sidecars=True)
    require(not (set(before) & urls), "Preexisting selected target cache entry")
    require(
        all(
            url in before
            and all(before[url][key] == event[key] for key in ("body_sha256", "serialized_value_sha256", "cache_key"))
            for url, event in accepted.items()
        ),
        "Previously accepted cache changed",
    )
    protected = {name: file_identity(output / name) for name in (*refresh.JSON_NAMES, "mediadive_download.log")}
    receipt = {"status": "running", "selected_urls": sorted(urls), "association_admission": False}
    refresh.write_json(directory / "started.json", receipt)
    error = None
    result = None
    handler = logging.FileHandler(directory / "production.log", mode="x")
    production.logger.addHandler(handler)
    try:
        production.setup_cache(output, migrate_legacy=False, clear=False)
        with observe_retry(directory, urls):
            result = production.download_medium_strains(selected, **SETTINGS)
    except BaseException as exc:
        error = exc
    finally:
        production._reset_sessions()
        production.logger.removeHandler(handler)
        handler.close()
    try:
        receipt["snapshot_artifacts"] = refresh.snapshot_artifacts(output, directory / "artifacts")
        grouped = (
            ledger(directory / "http-attempts.jsonl", urls) if (directory / "http-attempts.jsonl").exists() else {}
        )
        verify_bodies(directory, grouped)
        current = read_cache(directory / "artifacts" / refresh.CACHE_NAME)
        for url, record in before.items():
            require(
                url in current and current[url]["serialized_value_sha256"] == record["serialized_value_sha256"],
                "Previously persisted serialized response changed",
            )
        fresh = {url: events[-1] for url, events in grouped.items() if events[-1].get("valid")}
        require(
            set(current) == set(before) | set(fresh), "Cache URL union differs from baseline plus valid fresh responses"
        )
        for url in set(current) - set(before):
            event = grouped[url][-1]
            require(current[url]["status"] == event.get("status") == 200, "Unexpected non-200 cached response")
            for key in (
                "body_sha256",
                "body_bytes",
                "response_url",
                "prepared_request_url",
                "request_method",
                "response_headers",
            ):
                require(current[url][key] == event.get(key), f"Persisted response differs from actual HTTP: {key}")
        for url, event in fresh.items():
            require(
                url in current and current[url]["valid"] and current[url]["body_sha256"] == event["body_sha256"],
                "Fresh response was not persisted",
            )
        expected_result = {
            url.rsplit("/", 1)[-1]: current[url]["payload"]["data"] for url in fresh if current[url]["payload"]["data"]
        }
        if error is None:
            require(set(grouped) == urls, "Native subset omitted an endpoint")
            # The native function can return invalid truthy data; it must never be promoted.
            require(
                {key: value for key, value in result.items() if refresh.BASE_URL + "medium-strains/" + key in fresh}
                == expected_result,
                "Native output differs from fresh response",
            )
        for name, recorded in protected.items():
            match_record(output / name, recorded)
        guard()
        fresh = {
            url: {
                **event,
                "serialized_value_sha256": current[url]["serialized_value_sha256"],
                "cache_key": current[url]["cache_key"],
            }
            for url, event in fresh.items()
        }
        combined = {**accepted, **fresh}
        candidate = refresh.load_json(output / "media_strains.json")
        candidate.update(expected_result)
        candidate_path = directory / "media_strains.candidate.json"
        refresh.write_json(candidate_path, candidate)
        # Verify complete native artifacts using only accepted, body-bound cache rows.
        validation_dir = directory / "validation"
        validation_dir.mkdir()
        for name in refresh.JSON_NAMES:
            source = candidate_path if name == "media_strains.json" else output / name
            shutil.copy2(source, validation_dir / name)
        validate_outputs(validation_dir, {url: current[url] for url in combined}, media_ids, production)
        if error is None and fresh:
            temporary = output / ".media_strains.retry-1734.tmp"
            require(not os.path.lexists(temporary), "Existing strain publication temporary")
            with temporary.open("xb") as target:
                target.write(candidate_path.read_bytes())
                target.flush()
                os.fsync(target.fileno())
            match_record(output / "media_strains.json", protected["media_strains.json"])
            temporary.replace(output / "media_strains.json")
            require(
                refresh.digest(output / "media_strains.json") == refresh.digest(candidate_path),
                "Published strain output differs",
            )
        receipt["candidate"] = file_identity(candidate_path)
        outcomes = {url: classify(grouped[url][-1] if url in grouped else None) for url in urls}
        receipt.update(
            {
                "status": "failed" if error else "completed",
                "outcomes": outcomes,
                "outcome_counts": dict(Counter(outcomes.values())),
                "fresh_valid_endpoints": sorted(fresh),
                "combined_valid_endpoints": len(combined),
                "artifacts": {name: file_identity(output / name) for name in refresh.JSON_NAMES},
                "http_attempts_sha256": refresh.digest(directory / "http-attempts.jsonl") if grouped else None,
            }
        )
        if error:
            receipt["error"] = f"{type(error).__name__}: {error}"
        return receipt, combined if error is None else accepted
    except BaseException as exc:
        receipt.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        refresh.write_json(directory / "receipt.json", receipt)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise error


def run(args):
    """Plan or execute one collision-protected, same-process canary/batch retry."""
    from kg_microbe.utils import mediadive_bulk_download as production

    root = ROOT
    source_raw, launcher = args.source_raw.resolve(), args.launcher.resolve()
    refresh.validate_layout(root, source_raw)
    base = baseline(root, production)
    identity = runtime_identity(root, source_raw, launcher, production)
    for key in ("launcher_sha256", "production_sha256", "helper_sha256", "dependencies", "python", "python_version"):
        require(identity[key] == base["receipt"]["identity"][key], f"Reviewed baseline runtime changed: {key}")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.attempt), "Invalid attempt label")
    destination = owned_path(root, RETRY / "attempts" / args.attempt)
    require(not os.path.lexists(destination), "Retry attempt evidence already exists")
    receipt = {
        "status": "planned",
        "identity": identity,
        "canary_id": CANARY_ID,
        "baseline_valid_endpoints": len(base["accepted"]),
        "selected_count": len(base["unresolved"]),
        "maximum_transport_attempts": len(base["unresolved"]) * SETTINGS["retry_count"],
        "association_admission": False,
        "evidence": str(destination),
    }
    if not args.execute:
        return receipt
    destination.mkdir(parents=True)
    receipt["status"] = "running"
    refresh.write_json(destination / "started.json", receipt)
    refresh.write_json(
        destination / "prior-unresolved-histories.json",
        {url: base["history"][url] for url in sorted(base["unresolved"])},
    )
    output = root / "data/raw/mediadive"

    def guard():
        require(
            runtime_identity(root, source_raw, launcher, production) == identity, "Retry runtime/input identity changed"
        )
        check_preservation(root, base["manifest"])

    accepted = base["accepted"]
    try:
        refresh.snapshot_artifacts(output, destination / "before")
        guard()
        selected = [
            item
            for item in base["catalogue"]
            if refresh.BASE_URL + "medium-strains/" + str(item["id"]) in base["unresolved"]
        ]
        canary_items = [item for item in selected if str(item["id"]) == CANARY_ID]
        canary, accepted = phase(destination / "canary", canary_items, output, accepted, base["ids"], production, guard)
        outcome = next(iter(canary.get("outcomes", {}).values()), None)
        verified = canary["status"] == "completed" and outcome in {"recovered", "valid_empty", "unknown_404"}
        receipt["canary_execution"] = (
            "verified_unknown"
            if verified and outcome == "unknown_404"
            else ("verified_recovery" if verified else "unverified")
        )
        receipt["canary_receipt"] = file_identity(destination / "canary/receipt.json")
        if verified:
            guard()
            batch, accepted = phase(
                destination / "batch",
                [item for item in selected if str(item["id"]) != CANARY_ID],
                output,
                accepted,
                base["ids"],
                production,
                guard,
            )
            receipt["batch_receipt"] = file_identity(destination / "batch/receipt.json")
            receipt["batch_status"] = batch["status"]
        final_cache = read_cache(output / refresh.CACHE_NAME, empty_sidecars=True)
        validate_cache_coverage(final_cache, accepted)
        validate_outputs(output, final_cache, base["ids"], production)
        guard()
        remaining = sorted(base["unresolved"] - accepted.keys())
        refresh.write_json(
            destination / "combined-coverage.json", {"accepted": accepted, "remaining_unresolved_urls": remaining}
        )
        receipt["combined_coverage"] = file_identity(destination / "combined-coverage.json")
        snapshot = destination / "after"
        receipt["after_artifacts"] = refresh.snapshot_artifacts(output, snapshot)
        retained_cache = read_cache(snapshot / refresh.CACHE_NAME)
        validate_cache_coverage(retained_cache, accepted)
        validate_outputs(snapshot, retained_cache, base["ids"], production)
        for name, checksum in receipt["after_artifacts"].items():
            require(refresh.digest(snapshot / name) == checksum, f"Final retained artifact changed: {name}")
            if name in refresh.JSON_NAMES:
                require(refresh.digest(output / name) == checksum, f"Final raw output differs from snapshot: {name}")
        validate_cache_coverage(read_cache(output / refresh.CACHE_NAME, empty_sidecars=True), accepted)
        guard()
        # Source admission is assigned only after fresh readers verify both generations.
        receipt.update(
            {
                "status": "passed" if not remaining else "blocked",
                "association_admission": not remaining,
                "combined_valid_endpoints": len(accepted),
                "remaining_unresolved_urls": remaining,
                "recovered_endpoints": len(accepted) - len(base["accepted"]),
            }
        )
    except BaseException as exc:
        receipt.update({"status": "failed", "association_admission": False, "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        refresh.write_json(destination / "receipt.json", receipt)
    return receipt


def main():
    """Keep planning read-only; expected unresolved outcomes exit with a receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-raw", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["status"] == "blocked":
            parser.exit(2, "MediaDive retry retained; unresolved endpoints still block association admission.\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"MediaDive retry refused: {exc}\n")


if __name__ == "__main__":
    main()
