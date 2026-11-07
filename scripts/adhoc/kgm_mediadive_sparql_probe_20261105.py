#!/usr/bin/env python3
"""
Retain bounded official MediaDive SPARQL discovery; never grant source admission.

Purpose/date: investigate exact-ID alternatives for #1734 on 2026-11-05.
Inputs: reviewed query files and saved M5 production launcher environment.
Outputs: immutable request/body/receipt under this run's evidence directory.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/20261105/mediadive-resolution-1734"
ENDPOINT = "https://sparql.dsmz.de/api/mediadive"
QUERIES = {
    "identity": (
        "01-exact-medium-identity.rq",
        "f5a8ad98d29743b8774e6faec08fbe03d5bfd475dbddf7065d97cbf8338e92f5",
        ["?medium", "?predicate", "?value"],
    ),
    "control": (
        "02-positive-control-native-terms.rq",
        "cc8e6cde8c75e818191553d372d4d219a5853376a2a37b2b0c4c558b15c0492e",
        ["?medium", "?growth", "?strain", "?bacdiveID", "?kind", "?subject", "?predicate", "?value"],
    ),
    "control-r2": (
        "02-positive-control-native-terms-r2.rq",
        "9080457431bfd46d5f5f1a19f870c5f7d944abf93c1c1dd520942a1cffde8617",
        ["?medium", "?growth", "?strain", "?bacdiveID", "?kind", "?subject", "?predicate", "?value"],
    ),
    "unknown": (
        "03-unresolved-1366-native-terms.rq",
        "fcc47d152426a848ce8da565e10c7d431c2b9c85ec655ad8377a8c583cc52e4a",
        ["?medium", "?growth", "?strain", "?kind", "?subject", "?predicate", "?value"],
    ),
    "unknown-r2": (
        "03-unresolved-1366-native-terms-r2.rq",
        "d0ec0bdad18907d963bc2cf0a02f6de11a10c21e45f2df1533c9b54eef7cd2a8",
        ["?medium", "?growth", "?strain", "?kind", "?subject", "?predicate", "?value"],
    ),
}


def digest(data):
    """Identify exact request, response and helper bytes."""
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    """Write new evidence exclusively; never replace previous observations."""
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def strict_json(data):
    """Refuse duplicate keys and nonfinite values in the native result."""

    def pairs(items):
        """Keep every native key unique."""
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        """Reject non-JSON numeric constants."""
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def write_bounded(chunks, handle, maximum):
    """Retain at most the declared byte bound and refuse truncated interpretation."""
    count = 0
    for chunk in chunks:
        remaining = maximum - count
        handle.write(chunk[:remaining])
        if len(chunk) > remaining:
            raise ValueError("Response byte ceiling reached; retained bounded prefix")
        count += len(chunk)
    return count


def validate_stats(payload):
    """Recognize the documented index-name/count fields, never HTTP200 error objects."""
    if any(key.lower() in {"error", "exception"} for key in payload):
        raise ValueError("Backend stats error envelope")
    if "status" in payload and payload["status"] != "OK":
        raise ValueError("Unexpected backend stats status")
    name = payload.get("kbindex", payload.get("name-index"))
    count = payload.get("num-triples-normal", payload.get("nofActualTriples"))
    permutations = payload.get("num-permutations", payload.get("permutations"))
    if not isinstance(name, str) or type(count) is not int or count < 0:
        raise ValueError("Unrecognized backend stats identity/count")
    if type(permutations) not in {str, int} or str(permutations) not in {"1", "2", "6"}:
        raise ValueError("Unrecognized backend stats permutations")


def run(args):
    """Make one bounded read-only request; retain failures and do not infer associations."""
    if Path.cwd().resolve() != ROOT or not sys.dont_write_bytecode:
        raise ValueError("Use the owned worktree and bytecode-disabled production launcher")
    launcher = ROOT / "scripts/adhoc/kgm_rebuild_20261105.py"
    if Path(os.environ.get("KGM_REBUILD_LAUNCHER", "")).resolve() != launcher:
        raise ValueError("Saved production launcher environment is required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.label):
        raise ValueError("Invalid exclusive evidence label")
    output = EVIDENCE / "sparql-probes" / args.label
    if output.exists():
        raise ValueError("Evidence destination already exists")
    query = None
    columns = None
    if args.step != "stats":
        filename, expected, columns = QUERIES[args.step]
        query = (EVIDENCE / "official-review" / filename).read_bytes()
        if digest(query) != expected:
            raise ValueError("Reviewed query identity changed")
    request = {
        "step": args.step,
        "endpoint": ENDPOINT,
        "method": "GET" if query is None else "POST",
        "query_sha256": digest(query) if query is not None else None,
        "maximum_bytes": 2000000,
        "row_sentinel": 201,
        "attempts": 1,
        "redirects": False,
        "source_association_admission": False,
        "python": sys.executable,
        "helper_sha256": digest(Path(__file__).read_bytes()),
        "launcher_sha256": digest(launcher.read_bytes()),
        "environment_sha256": digest(json.dumps(dict(os.environ), sort_keys=True).encode()),
    }
    if not args.execute:
        print(json.dumps(request, indent=2))
        return 0
    output.mkdir(parents=True)
    save(output / "request.json", request)
    if query is not None:
        (output / "query.rq").write_bytes(query)
    receipt = {
        "status": "failed",
        "source_association_admission": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    import requests

    try:
        with requests.Session() as session:
            session.headers.update({"User-Agent": "kg-microbe bounded scientific source review", "Connection": "close"})
            if query is None:
                response = session.get(
                    ENDPOINT, params={"cmd": "stats"}, timeout=(10, 30), allow_redirects=False, stream=True
                )
            else:
                response = session.post(
                    ENDPOINT,
                    data={"query": query.decode(), "send": "201"},
                    headers={"Accept": "application/qlever-results+json"},
                    timeout=(10, 30),
                    allow_redirects=False,
                    stream=True,
                )
            receipt.update(
                {
                    "request_url": response.request.url,
                    "response_url": response.url,
                    "http_status": response.status_code,
                    "headers": dict(response.headers),
                }
            )
            with (output / "response.body").open("xb") as handle:
                write_bounded(response.iter_content(65536), handle, request["maximum_bytes"])
            response.raise_for_status()
            if response.is_redirect or response.url != response.request.url:
                raise ValueError("Redirected source")
            payload = strict_json((output / "response.body").read_bytes())
            if not isinstance(payload, dict):
                raise ValueError("Unexpected result envelope")
            if query is not None:
                if payload.get("status") != "OK" or payload.get("selected") != columns:
                    raise ValueError("Unexpected QLever status or selected columns")
                rows = payload.get("res")
                if not isinstance(rows, list) or any(
                    not isinstance(row, list) or len(row) != len(columns) for row in rows
                ):
                    raise ValueError("Unexpected native row shape")
                if type(payload.get("resultsize")) is not int or payload["resultsize"] != len(rows):
                    raise ValueError("Incomplete result size")
                if len(rows) >= 201 or payload.get("warnings"):
                    raise ValueError("Query ceiling or warning; no complete interpretation")
                receipt.update({"rows": len(rows), "selected": columns, "resultsize": payload["resultsize"]})
            else:
                validate_stats(payload)
                receipt.update(
                    {
                        "index_name_available": bool(payload.get("kbindex", payload.get("name-index", "")).strip()),
                        "dataset_freshness_established": False,
                    }
                )
            save(output / "parsed.json", payload)
            receipt["status"] = "mechanics_verified_requires_scientific_review"
    except (requests.RequestException, ValueError, OSError) as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        body = output / "response.body"
        if body.exists():
            receipt.update({"body_sha256": digest(body.read_bytes()), "body_bytes": body.stat().st_size})
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(output / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"].startswith("mechanics_verified") else 2


def main():
    """Plan by default; execute exactly one explicitly selected discovery request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=["stats", *QUERIES], required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--execute", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
