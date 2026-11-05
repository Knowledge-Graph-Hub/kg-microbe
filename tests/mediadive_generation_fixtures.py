"""Explicit synthetic MediaDive generation construction through real production APIs."""

import io
import json
from pathlib import Path
from unittest.mock import patch

import requests
from urllib3.response import HTTPResponse

from kg_microbe.transform_utils.mediadive import acquisition, endpoint_outcomes


def fixture_policy_path(raw, generation_id="fixture"):
    """Locate the explicitly synthetic finite policy used only by an unknown-state fixture."""
    return Path(raw) / ".fixture-source" / generation_id / "curated-policy.json"


def _response(url, payload, status):
    """Construct an offline response from an explicit immutable native fixture value."""
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.request = requests.Request("GET", url).prepare()
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    response.raw = HTTPResponse(
        body=io.BytesIO(response.content),
        status=status,
        headers=response.headers,
        preload_content=False,
        request_url=url,
    )
    return response


def seal_fixture_raw(raw, *, generation_id="fixture", missing_strains="explicit_empty", unknown_ids=()):
    """
    Seal honest synthetic evidence without changing any supplied native record or root JSON.

    The finite fixture catalogue gets an explicit synthetic success envelope/count;
    its original bytes are retained as source evidence. Missing strain keys become
    synthetic successful empty lists only under the named explicit_empty option.
    Supplied native details, strain records, solutions and compounds must agree
    exactly with production replay. Unknown fixtures expose curated_policy_path;
    callers must explicitly monkeypatch that locator before consumer replay.
    """
    raw = Path(raw)
    output = raw / "mediadive"
    source = raw / ".fixture-source" / generation_id
    source.mkdir(parents=True)
    original_catalogue = raw / "mediadive.json"
    catalogue_original = endpoint_outcomes.strict_json(original_catalogue.read_bytes())
    catalogue = {"status": 200, "count": len(catalogue_original["data"]), "data": catalogue_original["data"]}
    catalogue_path = source / "catalogue.json"
    catalogue_path.write_text(json.dumps(catalogue, indent=2) + "\n")
    ids, _ = endpoint_outcomes.catalogue_scope(catalogue)
    unknown_ids = {str(value) for value in unknown_ids}
    assert unknown_ids <= set(ids)
    details = endpoint_outcomes.strict_json((output / "media_detailed.json").read_bytes())
    strains = endpoint_outcomes.strict_json((output / "media_strains.json").read_bytes())
    assert set(details) == set(ids), "Synthetic detail records must cover the exact fixture catalogue"
    assert set(strains) <= set(ids), "Synthetic strains have extra fixture IDs"
    responses, lines = [], []
    for key in ids:
        for kind in ("medium", "medium-strains"):
            url = endpoint_outcomes.BASE_URL + kind + "/" + key
            if kind == "medium":
                payload, status = {"status": 200, "count": len(details[key]), "data": details[key]}, 200
            elif key in unknown_ids:
                assert key not in strains, "Unknown fixture cannot discard a supplied native strain claim"
                payload, status = (
                    {"status": 404, "count": 0, "error": "DataNotFound", "msg": endpoint_outcomes.UNKNOWN_MESSAGE},
                    404,
                )
            else:
                if key not in strains:
                    assert missing_strains == "explicit_empty", (
                        "Missing strain evidence requires an explicit fixture choice"
                    )
                value = strains.get(key, [])
                assert isinstance(value, list), "Synthetic strain assertions must use the actual native list shape"
                payload, status = {"status": 200, "count": len(value), "data": value}, 200
            response = _response(url, payload, status)
            event = {
                "request_url": url,
                "response_url": url,
                "status": status,
                "response_headers": dict(response.headers),
                "body_sha256": endpoint_outcomes.sha256(response.content),
                "observed_at": "2026-11-05T00:00:00+00:00",
            }
            responses.append(response)
            lines.append(endpoint_outcomes.canonical(event))
    ledger = source / "synthetic-responses.jsonl"
    ledger.write_bytes(b"".join(line + b"\n" for line in lines))
    evidence = {
        "evidence/synthetic-responses.jsonl": ledger,
        "evidence/original-fixture-catalogue.json": original_catalogue,
    }
    if unknown_ids:
        documentation = source / "retained-official-documentation.body"
        documentation.write_bytes(
            (Path(__file__).parent / "resources/mediadive_medium_strains_official_endpoint.js").read_bytes()
        )
        evidence["official-documentation.body"] = documentation
    seeds = {name: output / name for name in endpoint_outcomes.NATIVE_FILES.values() if name != "catalogue.json"}
    with acquisition.start_generation(
        output, generation_id, catalogue_path, seed_payloads=seeds, evidence_files=evidence
    ) as handle:
        events = []
        for number, (response, line) in enumerate(zip(responses, lines, strict=True), 1):
            events.append(
                acquisition.record_event(
                    handle,
                    url=response.url,
                    observed_at="2026-11-05T00:00:00+00:00",
                    response=response,
                    source={
                        "kind": "imported",
                        "ledger": "evidence/synthetic-responses.jsonl",
                        "line": number,
                        "line_sha256": endpoint_outcomes.sha256(line),
                    },
                )
            )
        pointer_before = handle.check()["expected_current_sha256"]
        if unknown_ids:
            policy = {
                "schema_version": 1,
                "policy_version": "synthetic-fixture-v1",
                "scientific_impact": "Synthetic unavailable endpoints do not establish absence of growth.",
                "downstream_handling": "Omit strain and growth assertions for the exact synthetic unknown cases.",
                "source_freshness_limitations": "Offline fixture observations are not live source freshness evidence.",
                "catalogue_sha256": endpoint_outcomes.identity(catalogue_path)["sha256"],
                "official_contract": {
                    "version": endpoint_outcomes.ERROR_CONTRACT,
                    "documentation_url": "https://mediadive.dsmz.de/doc/assets/main.bundle.js",
                    "documentation_sha256": endpoint_outcomes.identity(documentation)["sha256"],
                },
                "cases": {
                    event["url"]: {
                        "medium_id": event["url"].rsplit("/", 1)[-1],
                        "observation_id": event["observation_id"],
                        "body_sha256": event["body"]["sha256"],
                    }
                    for event in events
                    if event.get("response", {}).get("status") == 404
                },
            }
            policy_path = fixture_policy_path(raw, generation_id)
            policy_path.write_bytes(endpoint_outcomes.canonical(policy) + b"\n")
            with patch.object(endpoint_outcomes, "CURATED_UNKNOWN_POLICY", policy_path):
                view = acquisition.checkpoint_generation(handle, unknown_policy=policy_path)
                return acquisition.publish_generation(
                    output, generation_id, view.manifest_identity["sha256"], pointer_before
                )
        view = acquisition.checkpoint_generation(handle)
        return acquisition.publish_generation(output, generation_id, view.manifest_identity["sha256"], pointer_before)
