#!/usr/bin/env python3
"""
Resolve the finite MediaDive transport cohort through immutable production generations.

Purpose/date: retain #1734/#1751/#1754 source evidence for the M5 rebuild, 2026-11-05.
Inputs: pinned earlier failed receipts, independent native cache, exact original ledgers.
Outputs: sealed generations under data/raw/mediadive and exclusive run evidence.
Plan by default; each live stage requires an explicit reviewed predecessor receipt.
"""

import argparse
import hashlib
import inspect
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E = ROOT / "data/rebuild-evidence/20261105"
R = E / "mediadive-resolution-1734"
RETRY = E / "mediadive-retry-1734/attempts/retry-1"
FULL = E / "mediadive/attempts/sequence-1/full"
RAW = ROOT / "data/raw/mediadive"
RETRY_RECEIPT = "5050778364c925cedec323b78c9ef80787a9f01405ed42cf92c828be389da0c9"
SETTINGS = {"max_workers": 5, "retry_count": 3, "retry_delay": 2.0}


def digest(path):
    """Identify an existing evidence file without changing its representation."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    """Stop on differing identities or unresolved evidence without deleting artifacts."""
    if not condition:
        raise ValueError(message)


def save(path, value):
    """Create one new immutable evidence document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def load(path):
    """Read strict evidence JSON using the same production parser."""
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import strict_json

    return strict_json(Path(path).read_bytes())


def runtime():
    """Bind the actual isolated production module origins and launcher environment."""
    from kg_microbe.transform_utils.mediadive import acquisition, endpoint_outcomes
    from kg_microbe.utils import mediadive_bulk_download
    from scripts.adhoc import kgm_mediadive_retry_20261105 as old_retry

    require(Path.cwd().resolve() == ROOT and sys.dont_write_bytecode, "Use owned worktree with bytecode disabled")
    launcher = ROOT / "scripts/adhoc/kgm_rebuild_20261105.py"
    require(Path(os.environ.get("KGM_REBUILD_LAUNCHER", "")).resolve() == launcher, "Production launcher required")
    modules = {}
    for module in (acquisition, endpoint_outcomes, mediadive_bulk_download, old_retry):
        path = Path(inspect.getfile(module)).resolve()
        require(path.is_relative_to(ROOT), "Production module resolved outside owned worktree")
        modules[module.__name__] = {"path": str(path), "sha256": digest(path)}
    return {
        "python": sys.executable,
        "modules": modules,
        "launcher_sha256": digest(launcher),
        "helper_sha256": digest(__file__),
        "settings": SETTINGS,
    }


def validated_history():
    """Verify old failed receipts and preserve their latest observations, never reclassifying transport."""
    from kg_microbe.utils import mediadive_bulk_download as legacy
    from scripts.adhoc import kgm_mediadive_retry_20261105 as old_retry

    base = old_retry.baseline(ROOT, legacy)
    require(digest(RETRY / "receipt.json") == RETRY_RECEIPT, "Prior retry receipt changed")
    receipt = load(RETRY / "receipt.json")
    selected = {}
    evidence = {
        "evidence/full-receipt.json": FULL / "receipt.json",
        "evidence/retry-receipt.json": RETRY / "receipt.json",
        "evidence/full-ledger.jsonl": FULL / "http-attempts.jsonl",
    }
    for number, line in enumerate((FULL / "http-attempts.jsonl").read_bytes().splitlines(), 1):
        value = json.loads(line)
        if value["request_url"] in base["accepted"] and value.get("valid"):
            selected[value["request_url"]] = (value, "evidence/full-ledger.jsonl", number, line, FULL)
    for phase in ("canary", "batch"):
        directory = RETRY / phase
        require(
            old_retry.file_identity(directory / "receipt.json") == receipt[phase + "_receipt"], "Phase receipt changed"
        )
        phase_receipt = load(directory / "receipt.json")
        require(
            digest(directory / "http-attempts.jsonl") == phase_receipt["http_attempts_sha256"], "Phase ledger changed"
        )
        ledger_name = "evidence/" + phase + "-ledger.jsonl"
        evidence[ledger_name] = directory / "http-attempts.jsonl"
        evidence["evidence/" + phase + "-receipt.json"] = directory / "receipt.json"
        latest = {}
        for number, line in enumerate((directory / "http-attempts.jsonl").read_bytes().splitlines(), 1):
            value = json.loads(line)
            require(value["request_url"] in base["unresolved"], "Retry added an unselected endpoint")
            if value.get("body_path"):
                body = directory / value["body_path"]
                require(digest(body) == value["body_sha256"], "Retained response body changed")
                evidence["evidence/" + phase + "/" + value["body_path"]] = body
            latest[value["request_url"]] = (value, ledger_name, number, line, directory)
        require(set(latest) == set(phase_receipt["selected_urls"]), "Phase selected scope changed")
        require(not (set(latest) & set(selected)), "Prior acquisition scopes overlap")
        selected.update(latest)
    require(len(selected) == 6688, "Exact endpoint history scope changed")
    counts = Counter(
        "transport" if item[0].get("transport_error") else item[0].get("status") for item in selected.values()
    )
    require(counts == {200: 6056, 404: 583, "transport": 49}, "Reviewed latest source outcomes changed")
    documentation = E / "mediadive-retry-1734/official-review/api-doc-bundle.body"
    evidence["official-documentation.body"] = documentation
    return base, selected, evidence


def seed(generation_id):
    """Import actual historical observations with original timestamps and immutable source witnesses."""
    from requests_cache.serializers import pickle_serializer

    from kg_microbe.transform_utils.mediadive import acquisition
    from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes

    base, selected, evidence = validated_history()
    cache = FULL / "artifacts/mediadive_bulk_cache.sqlite"
    responses = {}
    with closing(sqlite3.connect(cache.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        for _key, blob in connection.execute("SELECT key,value FROM responses"):
            response = pickle_serializer.loads(blob)
            responses[response.url] = response
    seeds = {name: RAW / name for name in outcomes.NATIVE_FILES.values() if name != "catalogue.json"}
    with acquisition.start_generation(
        RAW,
        generation_id,
        ROOT / "data/raw/mediadive.json",
        seed_cache=cache,
        seed_payloads=seeds,
        evidence_files=evidence,
    ) as handle:
        save(R / (generation_id + "-plan.json"), {"generation_id": generation_id, "plan_sha256": handle.plan_sha256})
        for position, (url, item) in enumerate(sorted(selected.items()), 1):
            native, ledger, number, line, directory = item
            source = {
                "kind": "imported",
                "ledger": ledger,
                "line": number,
                "line_sha256": hashlib.sha256(line).hexdigest(),
            }
            response, transport = None, None
            if native.get("transport_error"):
                transport = {
                    "type": native["transport_error"],
                    "message": "Historical transport outcome; exact original line retained",
                }
            elif native["status"] == 200:
                response = responses[url]
                require(
                    hashlib.sha256(response.content).hexdigest() == native["body_sha256"], "Historical success changed"
                )
            else:
                event = {
                    "url": url,
                    "request": {"headers": {}},
                    "response": {
                        "url": native["response_url"],
                        "status": native["status"],
                        "headers": native["response_headers"],
                    },
                }
                response = acquisition._response_from_event(event, (directory / native["body_path"]).read_bytes())
            acquisition.record_event(
                handle,
                url=url,
                observed_at=native["observed_at"],
                response=response,
                transport_error=transport,
                source=source,
            )
            if position % 500 == 0:
                print(json.dumps({"imported_observations": position}), flush=True)
        view = acquisition.checkpoint_generation(handle)
    from scripts.adhoc import kgm_mediadive_retry_20261105 as old_retry

    old_retry.check_preservation(ROOT, base["manifest"])
    return view, []


def previous_view(receipt_path, identity):
    """Require the caller's pinned predecessor evidence before considering further transport."""
    from kg_microbe.transform_utils.mediadive.endpoint_outcomes import validate_generation

    require(digest(receipt_path) == identity, "Predecessor receipt identity changed")
    receipt = load(receipt_path)
    require(receipt["status"] == "verified", "Predecessor stage is not verified")
    view = validate_generation(
        Path(receipt["generation"]), receipt["manifest_sha256"], require_current=False, require_admissible=False
    )
    return receipt, view


def retry(args, current_runtime):
    """Run one actual transport canary, then only its still-unresolved sibling cohort."""
    from kg_microbe.transform_utils.mediadive import acquisition

    receipt, parent = previous_view(Path(args.previous_receipt), args.previous_sha256)
    require(receipt["runtime"] == current_runtime, "Producer/runtime changed since predecessor; review a new canary")
    selected = sorted(url for url, state in parent.endpoint_states.items() if state == "transport_error")
    if args.step == "canary":
        require(receipt["step"] == "seed" and len(selected) == 49, "Canary requires reviewed49-transport seed")
        selected = selected[:1]
    else:
        require(
            receipt["step"] == "canary" and receipt["selected_count"] == 1, "Batch lacks verified one-endpoint canary"
        )
        require(
            receipt["canary_resolved"] is True and len(selected) == 48, "Canary failed to resolve its transport outcome"
        )
    with acquisition.start_generation(
        RAW, args.generation_id, ROOT / "data/raw/mediadive.json", base_generation=parent
    ) as handle:
        save(
            R / (args.generation_id + "-plan.json"),
            {"generation_id": args.generation_id, "plan_sha256": handle.plan_sha256},
        )
        acquisition.acquire_endpoints(handle, selected, **SETTINGS)
        view = acquisition.checkpoint_generation(handle)
    return view, selected


def run(args):
    """Retain each attempt and refuse partial scientific admission even after successful mechanics."""
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.generation_id), "Unsafe generation ID")
    current_runtime = runtime()
    destination = R / (args.generation_id + "-receipt.json")
    require(not destination.exists(), "Receipt destination exists")
    if not args.execute:
        print(
            json.dumps({"step": args.step, "generation_id": args.generation_id, "runtime": current_runtime}, indent=2)
        )
        return 0
    save(
        R / (args.generation_id + "-started.json"),
        {
            "step": args.step,
            "runtime": current_runtime,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "previous_receipt": args.previous_receipt,
            "previous_sha256": args.previous_sha256,
        },
    )
    receipt = {"status": "failed", "step": args.step, "runtime": current_runtime}
    try:
        view, selected = seed(args.generation_id) if args.step == "seed" else retry(args, current_runtime)
        require(runtime() == current_runtime, "Production modules changed during the stage")
        from scripts.adhoc import kgm_mediadive_retry_20261105 as old_retry

        old_retry.check_preservation(ROOT, load(ROOT / old_retry.RETRY / "preservation/manifest.json"))
        receipt.update(
            {
                "status": "verified",
                "generation": str(view.generation_dir),
                "manifest_sha256": view.manifest_identity["sha256"],
                "qualification": view.qualification,
                "selected_urls": selected,
                "selected_count": len(selected),
                "canary_resolved": bool(selected)
                and all(
                    view.endpoint_states[url] in {"nonempty", "explicit_empty", "unknown_unavailable"}
                    for url in selected
                ),
                "active_pointer_published": False,
            }
        )
    except Exception as error:
        receipt["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(destination, receipt)
        print(json.dumps({"receipt": str(destination), "status": receipt["status"]}), flush=True)
    return 0


def main():
    """Plan one explicit immutable stage; never run the entire retry chain implicitly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=["seed", "canary", "batch"], required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--previous-receipt")
    parser.add_argument("--previous-sha256")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    require(args.step == "seed" or (args.previous_receipt and args.previous_sha256), "Pinned predecessor required")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
