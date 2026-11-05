"""Stage, seal, recover and atomically publish MediaDive endpoint generations."""

import fcntl
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes

DEFAULT_SETTINGS = {"max_workers": 5, "retry_count": 3, "retry_delay": 2.0}


def _sync_directory(path):
    """Make completed directory entry changes durable before advancing publication."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path, value):
    """Create and synchronize new bytes without replacing any existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _replace(path, value):
    """Atomically replace a mutable staging artifact using a unique sibling temporary."""
    temporary = path.with_name(path.name + ".pending")
    _write_new(temporary, value)
    temporary.replace(path)
    _sync_directory(path.parent)


def _json_bytes(value):
    """Use stable evidence JSON without changing ordered native dictionaries."""
    return outcomes.canonical(value) + b"\n"


def _copy(source, target):
    """Copy an input byte-for-byte while binding the original and new independently owned files."""
    source = Path(source).absolute()
    expected = outcomes.identity(source)
    _write_new(target, source.read_bytes())
    outcomes.require(outcomes.identity(source) == expected == outcomes.identity(target), "Input changed while copying")
    return {"path": str(source), **expected}


def _cache_copy(source, target):
    """Make a standalone SQLite backup without altering source WAL/SHM files."""
    source = Path(source).absolute()
    original = outcomes.identity(source)
    sidecars = {}
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            outcomes.require(
                suffix != "-journal" and (suffix != "-wal" or sidecar.stat().st_size == 0),
                "Source cache has unconsumed writes",
            )
            sidecars[sidecar] = outcomes.identity(sidecar)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)) as reader:
        with closing(sqlite3.connect(target)) as writer:
            reader.backup(writer)
            outcomes.require(
                writer.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                "Cache backup did not leave WAL mode",
            )
            outcomes.require(writer.execute("PRAGMA quick_check").fetchone() == ("ok",), "Cache backup is invalid")
    outcomes.require(outcomes.identity(source) == original, "Source cache changed during backup")
    for sidecar, expected in sidecars.items():
        outcomes.require(outcomes.identity(sidecar) == expected, "Source cache sidecar changed")
    return {"path": str(source), **original}


def _empty_cache(path):
    """Initialize the production native SQLite cache format without opening HTTP sessions."""
    from requests_cache.backends.sqlite import SQLiteCache

    backend = SQLiteCache(str(path), wal=False)
    backend.close()


def _pointer_identity(root):
    """Bind the active pointer's exact bytes or explicit absence."""
    path = root / "current.json"
    return outcomes.identity(path)["sha256"] if path.exists() else None


@dataclass
class AcquisitionGeneration:
    """Exclusive mutable staging handle; all published generations remain immutable."""

    output_root: Path
    stage_dir: Path
    plan_sha256: str
    lock_stream: object
    fault: object = None
    mutex: object = field(default_factory=threading.Lock)
    closed: bool = False
    sequence: int = 0
    previous_observation_id: object = None
    request_count: int = 0
    endpoint_scope: set = field(default_factory=set)
    baseline_records: dict = field(default_factory=dict)

    def __enter__(self):
        """Keep the generation writer lock for a bounded caller-managed operation."""
        return self

    def __exit__(self, *unused):
        """Release the OS lock on normal completion or interruption without deleting evidence."""
        self.close()

    def close(self):
        """Release ownership while retaining every staging byte for explicit recovery."""
        if not self.closed:
            fcntl.flock(self.lock_stream.fileno(), fcntl.LOCK_UN)
            self.lock_stream.close()
            self.closed = True

    def check(self):
        """Refuse stale handles, altered plans and a concurrently replaced active generation."""
        outcomes.require(not self.closed, "Generation writer handle is closed")
        outcomes.require(
            outcomes.identity(self.stage_dir / "plan.json")["sha256"] == self.plan_sha256, "Generation plan changed"
        )
        plan = outcomes.strict_json((self.stage_dir / "plan.json").read_bytes())
        outcomes.require(
            _pointer_identity(self.output_root) == plan["expected_current_sha256"],
            "Active generation changed during acquisition",
        )
        return plan

    def checkpoint(self, label):
        """Expose deterministic interruption boundaries without altering production behavior."""
        if self.fault is not None:
            self.fault(label)


def _open_handle(root, stage, expected_plan, fault=None):
    """Acquire an OS writer lock which is automatically released if a process dies."""
    lock = (stage / ".writer.lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise outcomes.EndpointEvidenceError("Generation already has an active writer") from None
    handle = AcquisitionGeneration(root, stage, expected_plan, lock, fault)
    try:
        handle.check()
        event_files = sorted((stage / "events").glob("*.json"))
        handle.sequence = len(event_files)
        if event_files:
            handle.previous_observation_id = outcomes.strict_json(event_files[-1].read_bytes())["observation_id"]
        handle.request_count = len((stage / "request-intents.jsonl").read_bytes().splitlines())
        _, handle.endpoint_scope = outcomes.catalogue_scope(
            outcomes.strict_json((stage / "catalogue.json").read_bytes())
        )
        handle.baseline_records = outcomes.cache_records(stage / "baseline-cache.sqlite")
    except BaseException:
        handle.close()
        raise
    return handle


def start_generation(
    output_root,
    generation_id,
    catalogue_path,
    *,
    seed_cache=None,
    seed_payloads=None,
    evidence_files=None,
    base_generation=None,
    fault=None,
):
    """Create an isolated mutable generation from explicit source inputs or a sealed parent."""
    root = Path(output_root).absolute()
    outcomes.require(not root.is_symlink(), "Output root cannot be a symlink")
    outcomes.require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", generation_id), "Unsafe generation ID")
    root.mkdir(parents=True, exist_ok=True)
    stage = outcomes.member(root, ".staging/" + generation_id)
    destination = outcomes.member(root, "generations/" + generation_id)
    outcomes.require(not stage.exists() and not destination.exists(), "Generation ID already exists")
    stage.mkdir(parents=True)
    sources = []
    parent = None
    if base_generation is not None:
        parent = outcomes.validate_generation(
            base_generation.generation_dir,
            base_generation.manifest_identity["sha256"],
            require_current=False,
            require_admissible=False,
        )
        outcomes.require(parent.generation_dir.parent == root / "generations", "Parent belongs to another output root")
        for path in parent.generation_dir.rglob("*"):
            if path.is_file() and path.name not in {"manifest.json", "seal.json", ".writer.lock", "plan.json"}:
                _copy(path, stage / path.relative_to(parent.generation_dir))
        _copy(parent.generation_dir / "plan.json", stage / "history" / (parent.generation_dir.name + "-plan.json"))
        _copy(
            parent.generation_dir / "manifest.json", stage / "history" / (parent.generation_dir.name + "-manifest.json")
        )
        outcomes.require(
            outcomes.identity(Path(catalogue_path)) == outcomes.identity(stage / "catalogue.json"),
            "Parent catalogue changed",
        )
    else:
        sources.append(_copy(catalogue_path, stage / "catalogue.json"))
        if seed_cache is None:
            _empty_cache(stage / outcomes.CACHE_FILE)
            _cache_copy(stage / outcomes.CACHE_FILE, stage / "baseline-cache.sqlite")
        else:
            sources.append(_cache_copy(seed_cache, stage / "baseline-cache.sqlite"))
            _cache_copy(stage / "baseline-cache.sqlite", stage / outcomes.CACHE_FILE)
        _write_new(stage / "observations.jsonl", b"")
        _write_new(stage / "request-intents.jsonl", b"")
        (stage / "events").mkdir()
        (stage / "bodies").mkdir()
        for name, path in (seed_payloads or {}).items():
            outcomes.require(
                name in set(outcomes.NATIVE_FILES.values()) - {"catalogue.json"}, "Unexpected native seed file"
            )
            sources.append(_copy(path, stage / "seed-native" / name))
    outcomes.catalogue_scope(outcomes.strict_json((stage / "catalogue.json").read_bytes()))
    for relative, path in (evidence_files or {}).items():
        target = outcomes.member(stage, relative)
        outcomes.require(
            relative.startswith("evidence/") or relative == "official-documentation.body",
            "Evidence must have an explicit source-evidence role",
        )
        sources.append(_copy(path, target))
    plan = {
        "schema_version": 1,
        "generation_id": generation_id,
        "expected_current_sha256": _pointer_identity(root),
        "parent": {"generation_id": parent.generation_dir.name, "manifest_sha256": parent.manifest_identity["sha256"]}
        if parent
        else None,
        "source_inputs": sources,
        "catalogue_sha256": outcomes.identity(stage / "catalogue.json")["sha256"],
    }
    _write_new(stage / "plan.json", _json_bytes(plan))
    return _open_handle(root, stage, outcomes.identity(stage / "plan.json")["sha256"], fault)


def _append(path, value):
    """Append one complete canonical record and synchronize it before a following action."""
    with path.open("ab") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def begin_request(handle, url):
    """Persist a request intent before transport so interrupted attempts remain explicit."""
    with handle.mutex:
        handle.check()
        outcomes.require(url in handle.endpoint_scope, "Unselected endpoint request")
        path = handle.stage_dir / "request-intents.jsonl"
        intent = {
            "sequence": handle.request_count + 1,
            "url": url,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        intent["request_id"] = outcomes.sha256(outcomes.canonical(intent))
        _append(path, intent)
        handle.request_count += 1
        return intent["request_id"]


def _response_from_event(event, body):
    """Reconstruct native cache serialization only from a durable actual response observation."""
    import io

    import requests
    from urllib3.response import HTTPResponse

    response = requests.Response()
    response.status_code = event["response"]["status"]
    response.url = event["response"]["url"]
    response.headers.update(event["response"]["headers"])
    response.request = requests.Request("GET", event["url"], headers=event["request"].get("headers", {})).prepare()
    response._content = body
    response.raw = HTTPResponse(
        body=io.BytesIO(body),
        status=response.status_code,
        headers=response.headers,
        preload_content=False,
        request_url=response.url,
    )
    return response


def _persist_response(directory, event, body):
    """Persist validated successes explicitly, preserving every preexisting native cache blob."""
    from requests_cache.backends.sqlite import SQLiteCache

    if outcomes.classify_observation(event, body)["state"] not in {"nonempty", "explicit_empty"}:
        return
    backend = SQLiteCache(str(directory / outcomes.CACHE_FILE), wal=False)
    try:
        response = _response_from_event(event, body)
        key = backend.create_key(response.request)
        if key in backend.responses:
            existing = backend.responses[key]
            outcomes.require(
                existing.url == event["url"]
                and existing.content == body
                and dict(existing.headers) == event["response"]["headers"],
                "Existing cached response differs; refusing replacement",
            )
        else:
            backend.save_response(response)
    finally:
        backend.close()


def record_event(handle, *, url, observed_at, response=None, transport_error=None, source=None, request_id=None):
    """Durably record actual response bytes and immutable event evidence before updating cache."""
    with handle.mutex:
        handle.check()
        outcomes.require(url in handle.endpoint_scope, "Observed endpoint is outside the catalogue")
        source = source or {"kind": "live"}
        outcomes.require(source["kind"] == "imported" or request_id is not None, "Live response lacks request intent")
        event = {
            "schema_version": 1,
            "sequence": handle.sequence + 1,
            "previous_observation_id": handle.previous_observation_id,
            "url": url,
            "observed_at": observed_at,
            "source": source,
            "request_id": request_id,
            "request": {"url": url, "method": "GET", "headers": {}},
            "response": None,
            "body": None,
            "transport_error": transport_error,
        }
        body = None
        if response is not None:
            outcomes.require(transport_error is None, "Cannot record both transport error and response")
            event["request"] = {
                "url": response.request.url,
                "method": response.request.method,
                "headers": dict(response.request.headers),
            }
            body = response.content
            body_name = "bodies/" + outcomes.sha256(body) + ".body"
            body_path = handle.stage_dir / body_name
            if body_path.exists():
                outcomes.require(body_path.read_bytes() == body, "Existing content-addressed response body differs")
            else:
                _write_new(body_path, body)
            event["response"] = {"url": response.url, "status": response.status_code, "headers": dict(response.headers)}
            event["body"] = {"path": body_name, "sha256": outcomes.sha256(body), "bytes": len(body)}
        outcomes.require(response is not None or transport_error is not None, "Event has no actual transport outcome")
        event["observation_id"] = outcomes.observation_id(event)
        _write_new(
            handle.stage_dir / "events" / f"{event['sequence']:08d}-{event['observation_id']}.json", _json_bytes(event)
        )
        _append(handle.stage_dir / "observations.jsonl", event)
        handle.sequence += 1
        handle.previous_observation_id = event["observation_id"]
        handle.checkpoint("after_observation")
        witness = handle.baseline_records.get(url) if source["kind"] == "imported" else None
        if witness is not None:
            outcomes.require(
                response is not None
                and witness["body"] == body
                and witness["status"] == response.status_code
                and witness["headers"] == dict(response.headers)
                and witness["request_url"] == response.request.url
                and witness["request_method"] == response.request.method,
                "Imported baseline cache witness differs",
            )
        else:
            _persist_response(handle.stage_dir, event, body)
        handle.checkpoint("after_cache")
        return event


def acquire_endpoints(handle, urls, *, max_workers=5, retry_count=3, retry_delay=2.0):
    """Fetch an explicit subset with fresh sessions, no redirects and retries only for transport/429."""
    import requests

    from kg_microbe.utils.mediadive_bulk_download import USER_AGENT, _retry_after_delay

    handle.check()
    urls = list(urls)
    outcomes.require(
        len(urls) == len(set(urls)) and max_workers > 0 and 1 <= retry_count <= 3 and retry_delay >= 0,
        "Invalid bounded endpoint acquisition settings",
    )
    _, scope = outcomes.catalogue_scope(outcomes.strict_json((handle.stage_dir / "catalogue.json").read_bytes()))
    outcomes.require(set(urls) <= scope, "Requested endpoint scope is not in the catalogue")
    cached = outcomes.cache_records(handle.stage_dir / outcomes.CACHE_FILE)
    outcomes.require(not (set(urls) & set(cached)), "Selected endpoint already has a preserved successful response")

    def fetch(url):
        """Use a new actual Requests session for each attempt and retain every terminal outcome."""
        final = None
        for attempt in range(retry_count):
            request_id = begin_request(handle, url)
            retry_after = retry_delay
            with requests.Session() as session:
                session.headers.update({"User-Agent": USER_AGENT, "Connection": "close"})
                try:
                    response = session.get(url, timeout=30, allow_redirects=False)
                except requests.RequestException as error:
                    final = record_event(
                        handle,
                        url=url,
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        transport_error={"type": type(error).__name__, "message": str(error)},
                        request_id=request_id,
                    )
                    retryable = True
                else:
                    final = record_event(
                        handle,
                        url=url,
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        response=response,
                        request_id=request_id,
                    )
                    retryable = response.status_code == 429
                    if retryable:
                        retry_after = _retry_after_delay(response.headers.get("Retry-After"), retry_delay)
            if not retryable or retry_after is None or attempt + 1 == retry_count:
                break
            time.sleep(retry_after)
        return final

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, urls))


def _native_payloads(catalogue, latest):
    """Build native values in catalogue order with unchanged production first-wins extraction."""
    from kg_microbe.utils.mediadive_bulk_download import extract_compounds_from_media, extract_solutions_from_media

    ids, _ = outcomes.catalogue_scope(catalogue)
    details, strains = {}, {}
    for key in ids:
        for kind in ("medium", "medium-strains"):
            _, result = latest.get(outcomes.BASE_URL + kind + "/" + key, (None, {"state": "missing_evidence"}))
            if result["state"] in {"nonempty", "explicit_empty"}:
                if kind == "medium":
                    details[key] = result["data"]
                elif result["data"]:
                    strains[key] = result["data"]
    return {
        "media_detailed.json": details,
        "media_strains.json": strains,
        "solutions.json": extract_solutions_from_media(details),
        "compounds.json": extract_compounds_from_media(details),
    }


def _rebuild_staging(handle, unknown_policy=None):
    """Recreate cache/native outputs from durable evidence without any HTTP operation."""
    handle.check()
    catalogue = outcomes.strict_json((handle.stage_dir / "catalogue.json").read_bytes())
    _, states, latest = outcomes.replay(handle.stage_dir, catalogue)
    cached = outcomes.cache_records(handle.stage_dir / outcomes.CACHE_FILE)
    for event, result in latest.values():
        if event is not None and result["state"] in {"nonempty", "explicit_empty"}:
            existing = cached.get(event["url"])
            if existing is not None:
                outcomes.require(
                    existing["body_sha256"] == event["body"]["sha256"]
                    and existing["status"] == event["response"]["status"]
                    and existing["headers"] == event["response"]["headers"]
                    and existing["request_url"] == event["url"]
                    and existing["request_method"] == "GET",
                    "Durable response differs from existing cache during recovery",
                )
            else:
                _persist_response(
                    handle.stage_dir, event, outcomes.member(handle.stage_dir, event["body"]["path"]).read_bytes()
                )
    handle.checkpoint("before_json")
    for name, payload in _native_payloads(catalogue, latest).items():
        seed = handle.stage_dir / "seed-native" / name
        if seed.exists() and outcomes.canonical(outcomes.strict_json(seed.read_bytes())) == outcomes.canonical(payload):
            value = seed.read_bytes()
        else:
            if seed.exists() and name != "media_strains.json":
                outcomes.require(False, f"Protected native seed differs from replay: {name}")
            value = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        _replace(handle.stage_dir / name, value)
    policy_bytes = (
        Path(unknown_policy).read_bytes() if unknown_policy is not None else _json_bytes(outcomes.EMPTY_POLICY)
    )
    _replace(handle.stage_dir / "unknown-policy.json", policy_bytes)
    policy = outcomes.strict_json(policy_bytes)
    _replace(handle.stage_dir / "endpoint-outcomes.json", _json_bytes({"schema_version": 1, "endpoints": states}))
    handle.checkpoint("after_json")
    outcomes.validate_native(handle.stage_dir, catalogue, latest)
    curated = outcomes.strict_json(outcomes.CURATED_UNKNOWN_POLICY.read_bytes())
    return outcomes.qualify(handle.stage_dir, catalogue, states, policy, curated)


def checkpoint_generation(handle, *, unknown_policy=None):
    """Seal one immutable checkpoint; unresolved forensic checkpoints cannot be published."""
    with handle.mutex:
        plan = handle.check()
        qualification = _rebuild_staging(handle, unknown_policy)
        for source in plan["source_inputs"]:
            outcomes.require(
                outcomes.identity(Path(source["path"])) == {key: source[key] for key in ("sha256", "bytes")},
                "Original acquisition input changed",
            )
        files = {}
        for path in handle.stage_dir.rglob("*"):
            outcomes.require(not path.is_symlink(), "Linked staging member")
            if path.is_file() and path.name not in {".writer.lock", "manifest.json", "seal.json"}:
                outcomes.require(
                    not path.name.endswith(".pending"), "Interrupted staging publication requires recovery"
                )
                files[str(path.relative_to(handle.stage_dir))] = outcomes.identity(path)
        manifest = {
            "schema_version": 1,
            "generation_id": plan["generation_id"],
            "parent": plan["parent"],
            "files": files,
            "qualification": qualification,
        }
        _write_new(handle.stage_dir / "manifest.json", _json_bytes(manifest))
        manifest_sha = outcomes.identity(handle.stage_dir / "manifest.json")["sha256"]
        _write_new(handle.stage_dir / "seal.json", _json_bytes({"schema_version": 1, "manifest_sha256": manifest_sha}))
        handle.checkpoint("before_seal")
        destination = handle.output_root / "generations" / plan["generation_id"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        outcomes.require(not destination.exists(), "Sealed generation already exists")
        handle.stage_dir.rename(destination)
        _sync_directory(destination.parent)
        handle.close()
    return outcomes.validate_generation(destination, manifest_sha, require_current=False, require_admissible=False)


def recover_generation(output_root, generation_id, expected_plan_sha256, *, unknown_policy=None):
    """Explicitly recover a known interrupted staging generation without sending requests."""
    root = Path(output_root).absolute()
    stage = outcomes.member(root, ".staging/" + generation_id)
    with _open_handle(root, stage, expected_plan_sha256) as handle:
        events = sorted((stage / "events").glob("*.json"))
        rebuilt = b"".join(_json_bytes(outcomes.strict_json(path.read_bytes())) for path in events)
        ledger = stage / "observations.jsonl"
        if ledger.read_bytes() != rebuilt:
            _copy(
                ledger, stage / "recovery-evidence" / ("observations-" + outcomes.identity(ledger)["sha256"] + ".jsonl")
            )
            _replace(ledger, rebuilt)
        for path in list(stage.rglob("*.pending")):
            target = (
                stage
                / "recovery-evidence"
                / (outcomes.sha256(str(path.relative_to(stage)).encode()) + "-" + outcomes.identity(path)["sha256"])
            )
            target.parent.mkdir(exist_ok=True)
            path.rename(target)
        # A prior crash may have finished the seal but not its directory publication.
        for name in ("manifest.json", "seal.json"):
            path = stage / name
            if path.exists():
                target = stage / "recovery-evidence" / (name + "." + outcomes.identity(path)["sha256"])
                target.parent.mkdir(exist_ok=True)
                path.rename(target)
        return checkpoint_generation(handle, unknown_policy=unknown_policy)


def publish_generation(output_root, generation_id, expected_manifest_sha256, expected_current_sha256, *, fault=None):
    """Serialize identity-bound pointer publication, including recovery of exact pending bytes."""
    root = Path(output_root).absolute()
    lock_path = root / ".publication.lock"
    outcomes.require(not lock_path.is_symlink(), "Linked publication lock")
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise outcomes.EndpointEvidenceError("Another generation publication is active") from None
        directory = outcomes.member(root, "generations/" + generation_id)
        view = outcomes.validate_generation(directory, expected_manifest_sha256, require_current=False)
        outcomes.require(
            _pointer_identity(root) == expected_current_sha256, "Current pointer changed before publication"
        )
        pointer = {"schema_version": 1, "generation_id": generation_id, "manifest_sha256": expected_manifest_sha256}
        value = _json_bytes(pointer)
        temporary = root / (".current-" + generation_id + ".pending")
        if temporary.exists():
            outcomes.require(
                outcomes.identity(temporary) == {"sha256": outcomes.sha256(value), "bytes": len(value)},
                "Pending pointer differs; retained for explicit review",
            )
        else:
            _write_new(temporary, value)
        if fault is not None:
            fault("before_pointer")
        view.admission.verify()
        outcomes.require(
            _pointer_identity(root) == expected_current_sha256, "Current pointer changed during publication"
        )
        temporary.replace(root / "current.json")
        _sync_directory(root)
        return outcomes.load_generation(root)


def rollback_generation(output_root, generation_id, expected_manifest_sha256, expected_current_sha256):
    """Explicitly restore a previously sealed admissible generation while retaining newer evidence."""
    return publish_generation(output_root, generation_id, expected_manifest_sha256, expected_current_sha256)


def download_mediadive_bulk(basic_file, output_dir, max_workers=5, retry_count=3, retry_delay=2.0, ignore_cache=False):
    """Acquire all endpoints into a fresh generation using the existing production entry signature."""
    root = Path(output_dir).absolute()
    if (root / "current.json").exists() and not ignore_cache:
        view = outcomes.load_generation(root)
        outcomes.require(
            outcomes.identity(Path(basic_file)) == outcomes.identity(view.native_paths["mediadive_media_list"]),
            "Selected catalogue differs from active generation",
        )
        return view
    generation_id = "download-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with start_generation(root, generation_id, basic_file) as handle:
        current = handle.check()["expected_current_sha256"]
        _, scope = outcomes.catalogue_scope(outcomes.strict_json((handle.stage_dir / "catalogue.json").read_bytes()))
        acquire_endpoints(
            handle, sorted(scope), max_workers=max_workers, retry_count=retry_count, retry_delay=retry_delay
        )
        view = checkpoint_generation(handle)
    if view.qualification["admissible"]:
        return publish_generation(root, generation_id, view.manifest_identity["sha256"], current)
    raise outcomes.EndpointEvidenceError(f"MediaDive acquisition retained unresolved generation {generation_id}")
