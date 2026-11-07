#!/usr/bin/env python3
"""
Run the 2026-11-05 staged MediaDive refresh through the production downloader.

Input: independently staged data/raw/mediadive.json and the saved rebuild launcher.
Output: production data/raw/mediadive files and immutable per-phase evidence under
 data/rebuild-evidence/20261105/mediadive. Default operation is a read-only plan.
The only production setting changed between canary and full is the selected list.
HTTP observation never replaces the downloader's sessions, cache, or retry policy.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SETTINGS = {"max_workers": 5, "retry_count": 3, "retry_delay": 2.0, "ignore_cache": True}
BASE_URL = "https://mediadive.dsmz.de/rest/"
CACHE_NAME = "mediadive_bulk_cache.sqlite"
JSON_NAMES = ("media_detailed.json", "media_strains.json", "solutions.json", "compounds.json")
CANONICAL_URLS = {
    "mediadive.json": BASE_URL + "media",
    "taxdump.tar.gz": "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
}


def digest(path):
    """Hash a file without materializing it."""
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    """Refuse an unsafe layout or incomplete evidence."""
    if not condition:
        raise ValueError(message)


def load_json(path):
    """Read one bounded catalogue, artifact, or receipt."""
    return json.loads(Path(path).read_text())


def write_json(path, payload):
    """Publish a new evidence file without replacing prior evidence."""
    with Path(path).open("x") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def validate_layout(worktree, source_raw):
    """Reject original CWD, linked raw files, and legacy cache migration hazards."""
    raw = worktree / "data/raw"
    require(Path.cwd().resolve() == worktree, "CWD must be the owned rebuild worktree")
    require((worktree / ".git").is_file(), "Expected an isolated linked Git worktree")
    require(source_raw.is_dir(), "Original raw directory does not exist")
    require(raw.is_dir(), "Staged raw directory does not exist")
    require(raw.resolve() != source_raw.resolve(), "Original and staged raw directories coincide")
    require(not raw.is_symlink(), "Staged raw directory must not be a symlink")
    require(raw.resolve().is_relative_to(worktree), "Staged raw escapes the owned worktree")
    require(not source_raw.resolve().is_relative_to(worktree), "Original raw must be outside owned worktree")
    require(not worktree.is_relative_to(source_raw.resolve()), "Worktree is inside original raw")
    # Filesystem iteration includes ignored and hidden files, including SQLite sidecars.
    for suffix in ("", "-wal", "-shm", "-journal"):
        legacy = worktree / (CACHE_NAME + suffix)
        require(not os.path.lexists(legacy), f"Legacy root cache migration hazard: {legacy}")

    def refuse_scan_error(error):
        raise error

    file_count = 0
    for directory, subdirs, files in os.walk(raw, onerror=refuse_scan_error):
        for name in subdirs + files:
            path = Path(directory) / name
            require(not path.is_symlink(), f"Staged raw contains a symlink: {path}")
        for name in files:
            path = Path(directory) / name
            stat = path.stat()
            require(stat.st_nlink == 1, f"Staged raw file has shared hardlinks: {path}")
            original = source_raw / path.relative_to(raw)
            if original.exists():
                require(not path.samefile(original), f"Staged raw shares original inode: {path}")
            file_count += 1
    evidence = worktree / "data/rebuild-evidence/20261105/mediadive"
    require(evidence.resolve().is_relative_to(worktree), "Evidence directory escapes worktree")
    for parent in (evidence, *evidence.parents):
        if parent == worktree:
            break
        require(not parent.is_symlink(), f"Evidence path contains symlink: {parent}")
    return {"raw_files_checked": file_count, "ignored_files_included": True}


def canonical_urls(worktree):
    """Check narrow refresh inputs against the canonical download configuration."""
    import yaml

    entries = yaml.safe_load((worktree / "download.yaml").read_text())
    selected = {}
    for name, expected in CANONICAL_URLS.items():
        matches = [item for item in entries if item.get("local_name") == name]
        require(len(matches) == 1, f"Expected exactly one canonical download entry for {name}")
        require(matches[0]["url"] == expected, f"Canonical URL changed for {name}; review required")
        selected[name] = matches[0]["url"]
    return selected


def select_media(catalogue, phase):
    """Select exactly one complete medium for canary, or the complete catalogue."""
    require(isinstance(catalogue, dict), "Catalogue must be a JSON object")
    media = catalogue.get("data")
    require(isinstance(media, list) and media, "Catalogue data must be a nonempty list")
    ids = []
    for medium in media:
        require(isinstance(medium, dict), "Catalogue contains a non-object medium")
        medium_id = str(medium.get("id", ""))
        require(re.fullmatch(r"[A-Za-z0-9._-]+", medium_id) and medium_id != "None", "Invalid medium ID")
        ids.append(medium_id)
    require(len(ids) == len(set(ids)), "Catalogue has duplicate medium IDs")
    if phase == "canary":
        return [media[ids.index("1")] if "1" in ids else media[0]]
    return media


def identity(worktree, source_raw, launcher, production):
    """Bind the real interpreter, code, launcher, settings, and runtime environment."""
    require((3, 10) <= sys.version_info[:2] <= (3, 12), "Python 3.10-3.12 is required")
    require(sys.dont_write_bytecode, "Launch with PYTHONDONTWRITEBYTECODE=1")
    module_path = Path(production.__file__).resolve()
    require(module_path.is_relative_to(worktree), f"Production imports from wrong checkout: {module_path}")
    require(launcher.is_file() and launcher.is_relative_to(worktree), "Launcher must belong to owned worktree")
    require(production.MEDIADIVE_REST_API_BASE_URL == BASE_URL, "Production API base URL changed")
    environment = {key: value for key, value in os.environ.items() if key not in {"_", "SHLVL", "PWD", "OLDPWD"}}
    return {
        "worktree": str(worktree),
        "source_raw": str(source_raw),
        "output": str(worktree / "data/raw/mediadive"),
        "python": sys.executable,
        "python_version": sys.version,
        "launcher": str(launcher),
        "launcher_sha256": digest(launcher),
        "helper_sha256": digest(__file__),
        "production_module": str(module_path),
        "production_sha256": digest(module_path),
        "catalogue_sha256": digest(worktree / "data/raw/mediadive.json"),
        "environment_sha256": hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("requests", "requests-cache")},
        "settings": SETTINGS,
        "urls": canonical_urls(worktree),
    }


def validate_payload(url, payload):
    """Recognize recipe JSON and successful empty/nonempty strain responses."""
    require(isinstance(payload, dict) and "data" in payload, "Response lacks explicit data field")
    data = payload["data"]
    if url.startswith(BASE_URL + "medium-strains/"):
        require(isinstance(data, list), "Strain response data must be a list (including valid empty [])")
        require(all(isinstance(item, dict) and "id" in item for item in data), "Invalid strain association")
        return "empty_strains" if not data else "strains"
    require(url.startswith(BASE_URL + "medium/"), f"Unexpected endpoint: {url}")
    medium_id = url.rsplit("/", 1)[-1]
    require(isinstance(data, dict) and isinstance(data.get("medium"), dict), "Missing detailed medium object")
    require(str(data["medium"].get("id")) == medium_id, "Detailed medium ID does not match request")
    # Native public records may omit solutions, and step-only or commercial
    # formulations may omit recipe. Preserve and count these supported shapes;
    # never manufacture ingredients or confuse them with a failed request.
    if "solutions" not in data:
        return "medium_without_solutions"
    solutions = data["solutions"]
    require(isinstance(solutions, list), "Detailed medium solutions must be a list")
    for solution in solutions:
        require(isinstance(solution, dict) and "id" in solution, "Invalid solution record")
        if "recipe" in solution:
            recipe = solution["recipe"]
            require(isinstance(recipe, list), "Solution recipe must be a list")
            require(all(isinstance(item, dict) for item in recipe), "Recipe contains an invalid ingredient")
    return "medium" if any(solution.get("recipe") for solution in solutions) else "medium_without_recipe"


def response_record(url, response):
    """Describe transport success separately from JSON shape and body content."""
    record = {
        "request_url": url,
        "response_url": response.url,
        "status": response.status_code,
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
        "body_bytes": len(response.content),
        "from_cache": bool(getattr(response, "from_cache", False)),
        "valid": False,
    }
    try:
        require(200 <= response.status_code < 300, "HTTP response is not successful")
        require(response.url == url, "Endpoint redirected; review required")
        record["payload_kind"] = validate_payload(url, response.json())
        record["valid"] = True
    except (ValueError, TypeError) as exc:
        record["validation_error"] = str(exc)
    return record


@contextmanager
def observe_transport(path):
    """Observe real transport attempts while retaining native retry/cache behavior."""
    import requests

    original_send = requests.sessions.Session.send
    lock = threading.Lock()
    with path.open("x") as stream:

        def record(event):
            with lock:
                event["observed_at"] = datetime.now(timezone.utc).isoformat()
                stream.write(json.dumps(event, sort_keys=True) + "\n")
                stream.flush()

        def observed_send(session, request, **kwargs):
            try:
                response = original_send(session, request, **kwargs)
            except requests.RequestException as exc:
                record({"request_url": request.url, "valid": False, "transport_error": type(exc).__name__})
                raise
            record(response_record(request.url, response))
            return response

        with patch.object(requests.sessions.Session, "send", observed_send):
            yield


def summarize_attempts(path, medium_ids):
    """Require one observed successful uncached response per expected endpoint."""
    expected = {
        BASE_URL + endpoint + medium_id for endpoint in ("medium/", "medium-strains/") for medium_id in medium_ids
    }
    attempts = {}
    for line in path.read_text().splitlines():
        event = json.loads(line)
        url = event["request_url"]
        require(url in expected, f"Unexpected observed endpoint: {url}")
        attempts.setdefault(url, []).append(event)
    require(set(attempts) == expected, f"Missing observed endpoints: {sorted(expected - attempts.keys())[:20]}")
    failures = [url for url, events in attempts.items() if not events[-1]["valid"]]
    require(not failures, f"Endpoints failed HTTP/JSON validation: {failures[:20]}")
    for url, events in attempts.items():
        require(sum(bool(event["valid"]) for event in events) == 1, f"Unexpected repeated success: {url}")
        require(not events[-1].get("from_cache"), f"Response came from old cache: {url}")
        require(len(events) <= SETTINGS["retry_count"], f"Retry budget exceeded: {url}")
    return attempts


def snapshot_artifacts(output, destination):
    """Preserve actual output bytes and a consistent SQLite backup after workers stop."""
    destination.mkdir()
    for name in (*JSON_NAMES, "mediadive_download.log"):
        source = output / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    cache = output / CACHE_NAME
    if cache.is_file():
        # SQLite may leave a stale shared-memory file even after successfully
        # converting a backup to DELETE mode. Keep that transient state inside
        # our private build directory; publish only the verified standalone DB.
        with tempfile.TemporaryDirectory(prefix=".sqlite-backup-", dir=destination) as temporary:
            staged = Path(temporary) / CACHE_NAME
            with closing(sqlite3.connect(cache.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(staged)) as target:
                    source.backup(target)
                    require(
                        target.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                        "Snapshot could not leave WAL mode",
                    )
                    require(
                        target.execute("PRAGMA quick_check").fetchone() == ("ok",), "Snapshot SQLite quick_check failed"
                    )
            wal = staged.with_name(staged.name + "-wal")
            require(not wal.exists() or wal.stat().st_size == 0, "Snapshot still has unconsumed WAL bytes")
            with staged.open("rb") as stream:
                require(stream.read(20)[18:20] == b"\x01\x01", "Snapshot is not a standalone rollback database")
            staged.replace(destination / CACHE_NAME)
    return {path.name: digest(path) for path in sorted(destination.iterdir()) if path.is_file()}


def validate_artifacts(snapshot, medium_ids, attempts, production):
    """Validate all JSON and persisted HTTP responses using fresh read-only SQLite."""
    from requests_cache.serializers import pickle_serializer

    artifacts = {name: load_json(snapshot / name) for name in JSON_NAMES}
    require(all(isinstance(value, dict) for value in artifacts.values()), "Bulk output JSON must contain objects")
    detailed = artifacts["media_detailed.json"]
    strains = artifacts["media_strains.json"]
    require(set(detailed) == set(medium_ids), "Detailed-media output coverage is incomplete")
    expected_strains = set()
    seen = set()
    cache = snapshot / CACHE_NAME
    # Immutable mode is safe only for our completed, standalone backup. Refuse
    # sidecars rather than silently ignoring an unconsumed SQLite generation.
    for suffix in ("-wal", "-shm", "-journal"):
        require(
            not os.path.lexists(cache.with_name(cache.name + suffix)),
            f"Snapshot cache has an unconsumed SQLite sidecar: {suffix}",
        )
    with closing(sqlite3.connect(cache.as_uri() + "?mode=ro&immutable=1", uri=True)) as reader:
        require(reader.execute("PRAGMA quick_check").fetchone() == ("ok",), "SQLite quick_check failed")
        for (blob,) in reader.execute("SELECT value FROM responses"):
            require(bool(blob), "Empty persisted response")
            response = pickle_serializer.loads(blob)
            url = response.url
            require(url in attempts and url not in seen, f"Unexpected or repeated cached URL: {url}")
            seen.add(url)
            persisted = response_record(url, response)
            require(persisted["valid"], f"Invalid persisted response: {url}")
            require(persisted["body_sha256"] == attempts[url][-1]["body_sha256"], f"Persisted body differs: {url}")
            medium_id = url.rsplit("/", 1)[-1]
            data = response.json()["data"]
            if "/medium-strains/" in url:
                if data:
                    expected_strains.add(medium_id)
                    require(strains.get(medium_id) == data, f"Strain output differs from response: {url}")
                else:
                    require(medium_id not in strains, "Production empty-strain omission changed")
            else:
                require(detailed[medium_id] == data, f"Detailed output differs from response: {url}")
    require(seen == set(attempts), "SQLite responses do not cover every successful endpoint")
    require(set(strains) == expected_strains, "Strain output contains unexplained keys")
    solutions = production.extract_solutions_from_media(detailed)
    compounds = production.extract_compounds_from_media(detailed)
    require(solutions and compounds, "No solutions or compounds extracted")
    require(artifacts["solutions.json"] == solutions, "Extracted solution output differs")
    require(artifacts["compounds.json"] == compounds, "Extracted compound output differs")
    return {
        "detailed_media": len(detailed),
        "media_with_strains": len(strains),
        "valid_empty_strain_responses": len(medium_ids) - len(strains),
        "solutions": len(solutions),
        "compounds": len(compounds),
        "persisted_responses": len(seen),
        "response_shape_counts": dict(Counter(events[-1]["payload_kind"] for events in attempts.values())),
        "attempt_status_counts": dict(
            Counter(str(event.get("status", "transport_error")) for events in attempts.values() for event in events)
        ),
        "recovered_attempts": sum(len(events) - 1 for events in attempts.values()),
    }


def admit_canary(evidence, run_identity, output):
    """Refuse full overwrite unless preserved canary evidence is complete and unchanged."""
    canary = evidence / "canary"
    receipt = load_json(canary / "receipt.json")
    require(receipt.get("status") == "passed", "Canary did not pass")
    require(receipt.get("identity") == run_identity, "Canary/full runtime identity changed")
    require(receipt.get("selected_count") == 1, "Canary was not exactly one medium")
    for name, checksum in receipt["artifacts"].items():
        require(digest(canary / "artifacts" / name) == checksum, f"Canary snapshot changed: {name}")
        if name in JSON_NAMES:
            require(digest(output / name) == checksum, f"Canary output changed before full refresh: {name}")
    require(digest(canary / "http-attempts.jsonl") == receipt["http_attempts_sha256"], "Canary HTTP evidence changed")
    return digest(canary / "receipt.json")


def evidence_directory(worktree, attempt=None):
    """Select an owned evidence generation without following links or reusing labels."""
    base = worktree / "data/rebuild-evidence/20261105/mediadive"
    if attempt is None:
        return base
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", attempt), "Invalid attempt label")
    selected = base / "attempts" / attempt
    for path in (selected, selected.parent):
        require(not path.is_symlink(), f"Attempt evidence must not be a symlink: {path}")
    require(selected.resolve().is_relative_to(base.resolve()), "Attempt evidence escapes owned directory")
    return selected


@contextmanager
def download_logging(production):
    """Close only handlers added by one native invocation before the next phase."""
    previous = tuple(production.logger.handlers)
    try:
        yield
    finally:
        for handler in tuple(production.logger.handlers):
            if handler not in previous:
                production.logger.removeHandler(handler)
                handler.close()


def run_sequence(args):
    """Use one live interpreter/environment, admitting the verified canary before full."""
    canary_args = argparse.Namespace(**{**vars(args), "phase": "canary"})
    canary = run(canary_args)
    if not args.execute:
        return {
            "status": "planned",
            "sequence": ["canary", "full"],
            "canary": canary,
            "full_condition": "Full runs only after canary HTTP, artifact, SQLite and identity admission",
        }
    require(canary["status"] == "passed", "Sequence canary did not pass")
    return run(argparse.Namespace(**{**vars(args), "phase": "full"}))


def run(args):
    """Plan or explicitly execute one bounded production refresh phase."""
    from kg_microbe.utils import mediadive_bulk_download as production

    worktree = Path(__file__).resolve().parents[2]
    source_raw = args.source_raw.resolve()
    launcher = args.launcher.resolve()
    layout = validate_layout(worktree, source_raw)
    run_identity = identity(worktree, source_raw, launcher, production)
    raw = worktree / "data/raw"
    output = raw / "mediadive"
    evidence = evidence_directory(worktree, getattr(args, "attempt", None))
    if args.phase == "canary" and getattr(args, "attempt", None) is not None:
        require(not evidence.exists(), f"Refusing to reuse attempt evidence: {evidence}")
    selected = select_media(load_json(raw / "mediadive.json"), args.phase)
    selected_ids = [str(medium["id"]) for medium in selected]
    receipt = {
        "phase": args.phase,
        "identity": run_identity,
        "layout": layout,
        "selected_count": len(selected),
        "selected_ids": selected_ids,
        "status": "planned",
        "evidence": str(evidence / args.phase),
    }
    if args.phase == "full":
        receipt["canary_receipt_sha256"] = admit_canary(evidence, run_identity, output)
    phase_dir = evidence / args.phase
    require(not phase_dir.exists(), f"Refusing to overwrite previous phase evidence: {phase_dir}")
    if not args.execute:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return receipt
    phase_dir.mkdir(parents=True)
    receipt["started_at"] = datetime.now(timezone.utc).isoformat()
    write_json(phase_dir / "selected-media.json", {"data": selected})
    # Same exact input path, output path, settings and entry point for both phases.
    batch_path = evidence / "selected-media.json"
    temporary = evidence / "selected-media.json.tmp"
    write_json(temporary, {"data": selected})
    temporary.replace(batch_path)
    attempts_path = phase_dir / "http-attempts.jsonl"
    try:
        with download_logging(production), observe_transport(attempts_path):
            production.download_mediadive_bulk(str(batch_path), str(output), **SETTINGS)
        receipt["artifacts"] = snapshot_artifacts(output, phase_dir / "artifacts")
        attempts = summarize_attempts(attempts_path, selected_ids)
        receipt["validation"] = validate_artifacts(phase_dir / "artifacts", selected_ids, attempts, production)
        require(
            run_identity == identity(worktree, source_raw, launcher, production), "Inputs/runtime changed during run"
        )
        receipt["status"] = "passed"
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        if attempts_path.is_file():
            receipt["http_attempts_sha256"] = digest(attempts_path)
        write_json(phase_dir / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return receipt


def main():
    """Parse an explicit phase; default to read-only planning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("canary", "full", "sequence"), default="canary")
    parser.add_argument("--source-raw", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--attempt", help="New safe evidence label; preserves earlier attempts")
    parser.add_argument(
        "--execute", action="store_true", help="Permit this phase's real production HTTP calls and writes"
    )
    args = parser.parse_args()
    try:
        if args.phase == "sequence":
            result = run_sequence(args)
            if not args.execute:
                print(json.dumps(result, indent=2, sort_keys=True))
        else:
            run(args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"MediaDive refresh refused: {exc}\n")


if __name__ == "__main__":
    main()
