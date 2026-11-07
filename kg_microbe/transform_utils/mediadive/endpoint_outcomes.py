"""Replay MediaDive endpoint evidence and admit immutable acquisition generations."""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE_URL = "https://mediadive.dsmz.de/rest/"
UNKNOWN_MESSAGE = "Medium does not exist or composition was not calculated"
ERROR_CONTRACT = "mediadive-medium-strains-404-v1"
CURATED_UNKNOWN_POLICY = Path(__file__).resolve().parents[3] / "mappings/mediadive_unknown_dispositions.json"
EMPTY_POLICY = {"schema_version": 1, "policy_version": "no-disposition-v1", "cases": {}}
STATES = frozenset(
    {"nonempty", "explicit_empty", "unknown_unavailable", "transport_error", "malformed", "missing_evidence"}
)
NATIVE_FILES = {
    "mediadive_media_list": "catalogue.json",
    "mediadive_media_detailed": "media_detailed.json",
    "mediadive_media_strains": "media_strains.json",
    "mediadive_solutions": "solutions.json",
    "mediadive_compounds": "compounds.json",
}
CACHE_FILE = "mediadive_bulk_cache.sqlite"


class EndpointEvidenceError(ValueError):
    """Acquisition evidence is incomplete, altered, or not scientifically admissible."""


def require(condition, message):
    """Refuse unsupported evidence without interpreting absence as a biological fact."""
    if not condition:
        raise EndpointEvidenceError(message)


def canonical(value):
    """Encode a deterministic strict JSON identity, preserving list order and types."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256(value):
    """Hash bytes without assigning any semantic interpretation."""
    return hashlib.sha256(value).hexdigest()


def strict_json(value):
    """Reject duplicate keys and nonstandard JSON constants at every nesting level."""

    def pairs(items):
        """Build an object without silently discarding repeated fields."""
        result = {}
        for key, item in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = item
        return result

    def invalid_constant(value):
        """Refuse NaN and infinity as non-native scientific JSON values."""
        raise EndpointEvidenceError(f"Nonstandard JSON constant: {value}")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)


def identity(path):
    """Hash an independently owned regular file without following symbolic links."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"Missing or linked evidence file: {path}")
    initial = path.stat()
    require(initial.st_nlink == 1, f"Shared evidence inode: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    final = path.stat()
    require(
        (initial.st_ino, initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns)
        == (final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns),
        f"Evidence changed while reading: {path}",
    )
    return {"sha256": digest.hexdigest(), "bytes": initial.st_size}


def member(directory, relative):
    """Resolve a generation-local member while refusing path escapes and links."""
    directory, relative = Path(directory).absolute(), Path(relative)
    require(not relative.is_absolute() and ".." not in relative.parts, "Evidence member escapes generation")
    target = directory / relative
    for path in (target, *target.parents):
        if path == directory:
            break
        require(not path.is_symlink(), f"Linked generation member: {path}")
    require(target.resolve().is_relative_to(directory.resolve()), "Evidence member escapes generation")
    return target


def catalogue_scope(catalogue):
    """Return the exact ordered medium IDs and their two canonical endpoint URLs."""
    require(isinstance(catalogue, dict) and isinstance(catalogue.get("data"), list), "Invalid MediaDive catalogue")
    ids = []
    for item in catalogue["data"]:
        require(isinstance(item, dict) and type(item.get("id")) in (int, str), "Invalid catalogue medium ID")
        key = str(item["id"])
        require(re.fullmatch(r"[A-Za-z0-9._-]+", key), "Unsafe catalogue medium ID")
        ids.append(key)
    require(len(ids) == len(set(ids)), "Duplicate catalogue scope")
    require(
        type(catalogue.get("status")) is int and catalogue["status"] == 200, "Catalogue status is not explicit success"
    )
    require(
        type(catalogue.get("count")) is int and catalogue["count"] == len(ids),
        "Catalogue count differs from exact scope",
    )
    return ids, {BASE_URL + kind + "/" + key for kind in ("medium", "medium-strains") for key in ids}


def observation_id(event):
    """Identify an entire normalized observation independently of its file location."""
    return sha256(canonical({key: value for key, value in event.items() if key != "observation_id"}))


def classify_observation(event, body):
    """Distinguish six endpoint states using actual transport and strict source envelopes."""
    url = event["url"]
    response = event.get("response")
    if event.get("transport_error"):
        require(response is None and body is None, "Transport error also claims an HTTP response")
        return {"state": "transport_error", "reason": event["transport_error"]["type"], "data": None}
    if response is None or body is None:
        return {"state": "missing_evidence", "reason": "No complete response evidence", "data": None}
    try:
        require(type(response["status"]) is int, "HTTP status must be a native integer")
        require(event["request"]["url"] == url and event["request"]["method"] == "GET", "Wrong request identity")
        require(response["url"] == url, "Redirected response")
        headers = {key.lower(): value for key, value in response["headers"].items()}
        require(
            headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json",
            "Non-JSON content type",
        )
        payload = strict_json(body)
        if response["status"] == 404 and "/medium-strains/" in url:
            require(
                type(payload) is dict and type(payload.get("status")) is int and type(payload.get("count")) is int,
                "Malformed unavailable envelope",
            )
            require(
                payload == {"status": 404, "count": 0, "error": "DataNotFound", "msg": UNKNOWN_MESSAGE},
                "Undocumented unavailable envelope",
            )
            return {"state": "unknown_unavailable", "reason": ERROR_CONTRACT, "data": None}
        require(type(response["status"]) is int and response["status"] == 200, "Unexpected HTTP status")
        require(type(payload) is dict and set(payload) == {"status", "count", "data"}, "Unexpected response envelope")
        require(type(payload["status"]) is int and payload["status"] == 200, "Envelope status is not 200")
        require(type(payload["count"]) is int and payload["count"] >= 0, "Invalid envelope count")
        data = payload["data"]
        if "/medium-strains/" in url:
            require(isinstance(data, list) and payload["count"] == len(data), "Strain count/list mismatch")
            require(
                all(type(item) is dict and type(item.get("id")) is int and item["id"] >= 0 for item in data),
                "Invalid native strain ID",
            )
            return {"state": "nonempty" if data else "explicit_empty", "reason": "HTTP 200 source list", "data": data}
        require("/medium/" in url, "Unexpected endpoint")
        require(type(data) is dict and type(data.get("medium")) is dict, "Missing native medium record")
        require(str(data["medium"].get("id")) == url.rsplit("/", 1)[-1], "Wrong native medium ID")
        if "solutions" in data:
            require(type(data["solutions"]) is list, "Invalid native solution list")
            for solution in data["solutions"]:
                require(type(solution) is dict and "id" in solution, "Invalid native solution")
                if "recipe" in solution:
                    require(
                        type(solution["recipe"]) is list and all(type(row) is dict for row in solution["recipe"]),
                        "Invalid native recipe",
                    )
        return {"state": "nonempty", "reason": "HTTP 200 source medium", "data": data}
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        return {"state": "malformed", "reason": str(error), "data": None}


def cache_records(path):
    """Read a closed native SQLite cache with exact key, blob, body and response identities."""
    from requests_cache.cache_keys import create_key
    from requests_cache.serializers import pickle_serializer

    path = Path(path).absolute()
    for suffix in ("-wal", "-shm", "-journal"):
        require(not path.with_name(path.name + suffix).exists(), "Generation cache has an unconsumed sidecar")
    before = identity(path)
    records = {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        require(connection.execute("PRAGMA quick_check").fetchone() == ("ok",), "Cache integrity failure")
        require(connection.execute("SELECT count(*) FROM redirects").fetchone() == (0,), "Cached redirect is forbidden")
        for key, blob in connection.execute("SELECT key,value FROM responses"):
            response = pickle_serializer.loads(blob)
            require(key == create_key(response.request, serializer=pickle_serializer), "Cache key differs from request")
            require(response.url not in records, "Duplicate cached URL")
            records[response.url] = {
                "key": key,
                "blob_sha256": sha256(blob),
                "body_sha256": sha256(response.content),
                "body": response.content,
                "status": response.status_code,
                "headers": dict(response.headers),
                "request_url": response.request.url,
                "request_method": response.request.method,
            }
    require(identity(path) == before, "Cache changed while reading")
    return records


def _import_source(directory, event, source_cache, ledger_cache):
    """Verify imported observation fields against the exact retained original ledger line."""
    source = event["source"]
    if source["kind"] != "imported":
        require(source["kind"] == "live", "Unknown observation source")
        return
    if source["ledger"] not in ledger_cache:
        ledger_cache[source["ledger"]] = member(directory, source["ledger"]).read_bytes().splitlines()
    lines = ledger_cache[source["ledger"]]
    require(type(source["line"]) is int and 1 <= source["line"] <= len(lines), "Invalid imported ledger line")
    line = lines[source["line"] - 1]
    require(sha256(line) == source["line_sha256"], "Imported ledger line changed")
    original = strict_json(line)
    require(
        original["request_url"] == event["url"] and original["observed_at"] == event["observed_at"],
        "Imported observation identity differs",
    )
    if event.get("response"):
        require(original.get("status") == event["response"]["status"], "Imported HTTP status differs")
        require(original.get("response_url") == event["response"]["url"], "Imported response URL differs")
        require(original.get("body_sha256") == event["body"]["sha256"], "Imported body identity differs")
        if "response_headers" in original:
            require(original["response_headers"] == event["response"]["headers"], "Imported HTTP headers differ")
        else:
            cached = source_cache.get(event["url"])
            require(
                cached is not None and cached["body_sha256"] == event["body"]["sha256"],
                "Imported headers lack native cache witness",
            )
            require(cached["headers"] == event["response"]["headers"], "Imported cache headers differ")
    else:
        require(
            original.get("transport_error") == event["transport_error"]["type"], "Imported transport outcome differs"
        )


def replay(directory, catalogue):
    """Replay complete immutable event files, their chained ledger, request intents and bodies."""
    directory = Path(directory)
    ids, expected = catalogue_scope(catalogue)
    source_cache = cache_records(directory / "baseline-cache.sqlite")
    events = []
    ledger_cache = {}
    previous = None
    for number, line in enumerate((directory / "observations.jsonl").read_bytes().splitlines(), 1):
        event = strict_json(line)
        require(
            event["sequence"] == number and event["previous_observation_id"] == previous, "Observation chain differs"
        )
        require(event["observation_id"] == observation_id(event), "Observation digest differs")
        require(event["url"] in expected, "Observation has wrong or extra endpoint")
        observed = datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
        require(observed.tzinfo is not None, "Observation timestamp lacks timezone")
        event_path = directory / "events" / f"{number:08d}-{event['observation_id']}.json"
        require(strict_json(event_path.read_bytes()) == event, "Event file differs from appended ledger")
        body = None
        if event.get("body"):
            body_path = member(directory, event["body"]["path"])
            require(
                identity(body_path) == {key: event["body"][key] for key in ("sha256", "bytes")},
                "Raw response body changed",
            )
            body = body_path.read_bytes()
        _import_source(directory, event, source_cache, ledger_cache)
        result = classify_observation(event, body)
        events.append((event, result))
        previous = event["observation_id"]
    require(len(list((directory / "events").glob("*.json"))) == len(events), "Unindexed observation event file")
    latest = {}
    for event, result in events:
        if event["url"] in latest:
            previous_time = datetime.fromisoformat(latest[event["url"]][0]["observed_at"].replace("Z", "+00:00"))
            current_time = datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
            require(current_time >= previous_time, "Observation time regressed")
        latest[event["url"]] = (event, result)
    intents = [strict_json(line) for line in (directory / "request-intents.jsonl").read_bytes().splitlines()]
    seen_intents = set()
    live = [event for event, _ in events if event["source"]["kind"] == "live"]
    completed = {event.get("request_id"): event for event in live}
    require(len(completed) == len(live), "Repeated completion for one request intent")
    latest_intent = {}
    for number, intent in enumerate(intents, 1):
        require(intent["sequence"] == number, "Request intent sequence differs")
        latest_intent[intent["url"]] = intent
        request_id = intent["request_id"]
        require(
            request_id == sha256(canonical({key: value for key, value in intent.items() if key != "request_id"})),
            "Request intent changed",
        )
        require(request_id not in seen_intents and intent["url"] in expected, "Repeated or extra request intent")
        seen_intents.add(request_id)
        if request_id in completed:
            require(completed[request_id]["url"] == intent["url"], "Response completed a different endpoint")
    require(set(completed) <= seen_intents, "Live observation lacks a durable request intent")
    for url, intent in latest_intent.items():
        if intent["request_id"] not in completed:
            latest[url] = (
                None,
                {"state": "missing_evidence", "reason": "Uncompleted latest durable request intent", "data": None},
            )
    states = {}
    for url in sorted(expected):
        event, result = latest.get(
            url, (None, {"state": "missing_evidence", "reason": "Endpoint was never observed", "data": None})
        )
        states[url] = {
            "state": result["state"],
            "reason": result["reason"],
            "observation_id": event["observation_id"] if event else None,
            "body_sha256": event["body"]["sha256"] if event and event.get("body") else None,
            "observed_at": event["observed_at"] if event else None,
        }
    return ids, states, latest


def validate_native(directory, catalogue, latest):
    """Validate native output values, first-wins order and exact cache coverage without fallback."""
    from kg_microbe.utils.mediadive_bulk_download import extract_compounds_from_media, extract_solutions_from_media

    ids, _ = catalogue_scope(catalogue)
    details, strains, successes = {}, {}, {}
    for key in ids:
        for kind in ("medium", "medium-strains"):
            url = BASE_URL + kind + "/" + key
            event, result = latest.get(url, (None, {"state": "missing_evidence"}))
            if result["state"] in {"nonempty", "explicit_empty"}:
                successes[url] = event
                if kind == "medium":
                    details[key] = result["data"]
                elif result["data"]:
                    strains[key] = result["data"]
    expected = {
        "mediadive_media_list": catalogue,
        "mediadive_media_detailed": details,
        "mediadive_media_strains": strains,
        "mediadive_solutions": extract_solutions_from_media(details),
        "mediadive_compounds": extract_compounds_from_media(details),
    }
    for role, payload in expected.items():
        actual = strict_json((directory / NATIVE_FILES[role]).read_bytes())
        require(canonical(actual) == canonical(payload), f"Native output differs from source evidence: {role}")
        if role == "mediadive_media_detailed":
            require(list(actual) == list(details), "Native detailed catalogue order changed")
    cached = cache_records(directory / CACHE_FILE)
    require(set(cached) == set(successes), "Cache scope differs from successful endpoint evidence")
    for url, event in successes.items():
        row = cached[url]
        require(
            row["body_sha256"] == event["body"]["sha256"] and row["status"] == event["response"]["status"],
            "Cache response differs from source body/status",
        )
        require(
            row["headers"] == event["response"]["headers"]
            and row["request_url"] == url
            and row["request_method"] == "GET",
            "Cache response metadata differs",
        )
    for url, original in cache_records(directory / "baseline-cache.sqlite").items():
        require(
            url in cached
            and cached[url]["key"] == original["key"]
            and cached[url]["blob_sha256"] == original["blob_sha256"],
            "Original cached success was replaced",
        )
    return expected


def _javascript_value_end(text, start, terminators):
    """Bound one documentation value without evaluating JavaScript or scanning string contents."""
    stack = []
    quote = None
    escaped = False
    pairs = {"}": "{", "]": "[", ")": "("}
    for position in range(start, len(text)):
        character = text[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character in "{[(":
            stack.append(character)
        elif not stack and character in terminators:
            return position
        elif character in "}])":
            require(stack and stack.pop() == pairs[character], "Unbalanced official documentation value")
            if not stack and "object_end" in terminators:
                return position + 1
    require(quote is None and not stack, "Unterminated official documentation value")
    return len(text)


def _documentation_fields(record):
    """Read direct object properties while preserving nested objects and examples as opaque values."""
    require(record.startswith("{") and record.endswith("}"), "Official documentation record is not an object")
    fields = {}
    position = 1
    while position < len(record) - 1:
        while record[position].isspace():
            position += 1
        match = re.match(r'([A-Za-z_$][A-Za-z0-9_$]*|"(?:\\.|[^"\\])*")\s*:', record[position:])
        require(match is not None, "Unsupported official documentation property")
        key = match.group(1)
        key = strict_json(key) if key.startswith('"') else key
        require(key not in fields, "Repeated official documentation property")
        start = position + match.end()
        end = _javascript_value_end(record, start, {",", "}"})
        fields[key] = record[start:end].strip()
        position = end + 1
    return fields


def _documentation_records(text):
    """Read direct API table members from the retained generated bundle or an exact excerpt."""
    text = text.strip()
    if text.startswith("{"):
        require(_javascript_value_end(text, 0, {"object_end"}) == len(text), "Trailing documentation record content")
        return [text]
    if text.startswith("["):
        start = 0
    else:
        # This versioned contract recognizes the reviewed bundle's actual API
        # table declaration. It does not search arbitrary examples for a URL.
        wrapper = "function Ke(){var J;let Fe="
        require(text.count(wrapper) == 1, "Unsupported or ambiguous official documentation table")
        start = text.index(wrapper) + len(wrapper)
    require(text[start] == "[", "Official documentation table is not an array")
    end = _javascript_value_end(text, start, {"object_end"})
    if start == 0:
        require(end == len(text), "Trailing documentation table content")
    records = []
    position = start + 1
    while position < end - 1:
        while text[position].isspace():
            position += 1
        require(text[position] == "{", "Official documentation table member is not a record")
        finish = _javascript_value_end(text, position, {"object_end"})
        require(finish <= end - 1, "Documentation record escapes table")
        records.append(text[position:finish])
        position = finish
        while text[position].isspace():
            position += 1
        if position != end - 1:
            require(text[position] == ",", "Invalid documentation table separator")
            position += 1
    return records


def validate_official_error_contract(document):
    """Verify the specific documented endpoint error independently of its native wire message."""
    records = _documentation_records(document.decode("utf-8"))
    matches = [(record, _documentation_fields(record)) for record in records]
    matches = [(record, fields) for record, fields in matches if fields.get("url") == '"/medium-strains/:id"']
    require(len(matches) == 1, "Official documentation must contain exactly one medium-strains endpoint record")
    record, fields = matches[0]
    require(
        fields.get("type") == '"get"'
        and fields.get("url") == '"/medium-strains/:id"'
        and fields.get("name") == '"GetMediumStrains"',
        "Official medium-strains endpoint identity differs",
    )
    require(
        fields.get("sampleRequest") == '[{url:"https://mediadive.dsmz.de/rest/medium-strains/:id"}]',
        "Official medium-strains sample URL differs",
    )
    errors = _documentation_fields(fields.get("error", ""))
    statuses = _documentation_fields(errors.get("fields", ""))
    group = statuses.get("Error 404", "")
    require(group.startswith("[") and group.endswith("]"), "Official endpoint lacks its Error 404 group")
    error = _documentation_fields(group[1:-1])
    description = "<p>The medium could not be found or has no calculated composition</p>"
    require(
        error.get("group") == '"error404"'
        and error.get("field") == '"DataNotFound"'
        and error.get("description") == json.dumps(description),
        "Official endpoint DataNotFound meaning differs",
    )
    return {
        "endpoint": "/medium-strains/:id",
        "name": "GetMediumStrains",
        "error": "DataNotFound",
        "description": description,
        "record_sha256": sha256(record.encode("utf-8")),
    }


def qualify(directory, catalogue, states, policy, curated_policy):
    """Require a finite current reviewed policy for source-declared unknown associations."""
    ids, scope = catalogue_scope(catalogue)
    require(
        curated_policy.get("schema_version") == 1
        and type(curated_policy.get("cases")) is dict
        and bool(curated_policy.get("policy_version")),
        "Invalid current curated disposition policy",
    )
    unknown = {url: record for url, record in states.items() if record["state"] == "unknown_unavailable"}
    applied = bool(unknown) and policy != EMPTY_POLICY
    policy_ok = not unknown
    if applied:
        require(
            canonical(policy) == canonical(curated_policy),
            "Generation unknown policy differs from current curated policy",
        )
        require(
            policy.get("schema_version") == 1 and policy.get("policy_version") not in (None, "no-disposition-v1"),
            "Unknown disposition lacks reviewed version",
        )
        require(
            policy.get("catalogue_sha256") == identity(directory / "catalogue.json")["sha256"],
            "Unknown policy catalogue differs",
        )
        require(set(policy.get("cases", {})) == set(unknown), "Unknown policy is not the exact finite observed scope")
        for field in ("scientific_impact", "downstream_handling", "source_freshness_limitations"):
            require(type(policy.get(field)) is str and bool(policy[field].strip()), f"Unknown policy lacks {field}")
        official = policy["official_contract"]
        require(
            official["version"] == ERROR_CONTRACT
            and official["documentation_url"] == "https://mediadive.dsmz.de/doc/assets/main.bundle.js",
            "Unknown policy official contract differs",
        )
        document = directory / "official-documentation.body"
        require(identity(document)["sha256"] == official["documentation_sha256"], "Official documentation changed")
        validate_official_error_contract(document.read_bytes())
        for url, record in unknown.items():
            require(
                policy["cases"][url]
                == {
                    "medium_id": url.rsplit("/", 1)[-1],
                    "observation_id": record["observation_id"],
                    "body_sha256": record["body_sha256"],
                },
                "Unknown policy observation differs",
            )
        policy_ok = True
    else:
        require(policy == EMPTY_POLICY, "Unapplied policy must be the canonical empty disposition")
    recipe_complete = all(states[url]["state"] == "nonempty" for url in scope if "/medium/" in url)
    association_complete = all(
        states[url]["state"] in {"nonempty", "explicit_empty"} for url in scope if "/medium-strains/" in url
    )
    unresolved = sorted(
        url for url, record in states.items() if record["state"] in {"transport_error", "malformed", "missing_evidence"}
    )
    return {
        "schema_version": 1,
        "catalogue_count": len(ids),
        "expected_endpoint_count": len(scope),
        "association_endpoint_count": len(ids),
        "state_counts": {
            state: Counter(record["state"] for record in states.values())[state] for state in sorted(STATES)
        },
        "endpoint_accounting_complete": all(record["state"] != "missing_evidence" for record in states.values()),
        "association_coverage_complete": association_complete,
        "recipe_coverage_complete": recipe_complete,
        "unknown_endpoints": sorted(unknown),
        "unresolved_endpoints": unresolved,
        "policy_applied": applied,
        "admissible": recipe_complete and not unresolved and policy_ok,
        "omitted_assertions": "Unknown endpoints produce no inferred strain, growth, or absence assertions.",
    }


@dataclass(frozen=True)
class GenerationView:
    """Validated generation paths and detached consumer-facing evidence contracts."""

    generation_dir: Path
    native_paths: dict
    catalogue: dict
    payloads: dict
    endpoint_states: dict
    endpoint_records: dict
    qualification: dict
    pointer_identity: dict
    manifest_identity: dict
    admission: object
    curated_policy_path: Path
    _contract_json: bytes

    def contract(self):
        """Return a detached identity contract which callers cannot mutate in place."""
        return strict_json(self._contract_json)


def _read_role(path, role, admission, consume_input):
    """Parse the exact role bytes captured by the shared admission and native read boundary."""
    captured = admission.capture(path, retain=True)
    if consume_input is None:
        return strict_json(captured)
    with consume_input(role, path) as stream:
        read = stream.read()
    read = read.encode() if isinstance(read, str) else read
    require(read == captured, f"Consumed role differs from admitted bytes: {role}")
    return strict_json(read)


def validate_generation(
    generation_dir,
    expected_manifest_sha256,
    *,
    consume_input=None,
    admission=None,
    require_current=True,
    require_admissible=True,
):
    """Replay a sealed generation with actual current-policy and optional pointer admission."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    directory = Path(generation_dir).absolute()
    admission = admission or SourceAdmission()
    manifest_path = directory / "manifest.json"
    manifest = _read_role(manifest_path, "mediadive_generation_manifest", admission, consume_input)
    require(identity(manifest_path)["sha256"] == expected_manifest_sha256, "Generation manifest identity differs")
    require(
        manifest.get("schema_version") == 1 and manifest.get("generation_id") == directory.name,
        "Invalid generation manifest",
    )
    seal = strict_json(admission.capture(directory / "seal.json", retain=True))
    require(seal == {"schema_version": 1, "manifest_sha256": expected_manifest_sha256}, "Generation seal differs")
    for path in directory.rglob("*"):
        require(not path.is_symlink(), f"Linked generation member: {path}")
    members = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    require(
        members == set(manifest["files"]) | {"manifest.json", "seal.json", ".writer.lock"},
        "Generation file membership differs",
    )
    for relative, expected in manifest["files"].items():
        path = member(directory, relative)
        require(admission.capture(path) == expected, f"Generation member changed: {relative}")
    require(admission.capture(directory / ".writer.lock")["bytes"] == 0, "Unexpected writer lock payload")
    pointer_identity = {}
    if require_current:
        root = directory.parent.parent
        pointer_path = root / "current.json"
        pointer = _read_role(pointer_path, "mediadive_generation_pointer", admission, consume_input)
        require(
            pointer
            == {"schema_version": 1, "generation_id": directory.name, "manifest_sha256": expected_manifest_sha256},
            "Current generation pointer differs",
        )
        pointer_identity = {"path": str(pointer_path), **identity(pointer_path)}
    curated = _read_role(CURATED_UNKNOWN_POLICY, "mediadive_unknown_disposition_policy", admission, consume_input)
    policy = _read_role(directory / "unknown-policy.json", "mediadive_unknown_policy", admission, consume_input)
    outcomes = _read_role(directory / "endpoint-outcomes.json", "mediadive_endpoint_outcomes", admission, consume_input)
    catalogue = strict_json((directory / "catalogue.json").read_bytes())
    _, states, latest = replay(directory, catalogue)
    require(outcomes == {"schema_version": 1, "endpoints": states}, "Endpoint outcomes differ from source replay")
    payloads = validate_native(directory, catalogue, latest)
    qualification = qualify(directory, catalogue, states, policy, curated)
    if qualification["policy_applied"]:
        require(
            identity(directory / "unknown-policy.json") == identity(CURATED_UNKNOWN_POLICY),
            "Unknown policy bytes differ from curated policy",
        )
    require(manifest["qualification"] == qualification, "Generation qualification differs from replay")
    if require_admissible:
        require(qualification["admissible"], "MediaDive generation contains unresolved endpoint evidence")
    admission.verify()
    manifest_identity = {"path": str(manifest_path), **identity(manifest_path)}
    contract = {
        "schema_version": 1,
        "generation_id": directory.name,
        "pointer": pointer_identity,
        "manifest": manifest_identity,
        "outcomes": {
            "path": str(directory / "endpoint-outcomes.json"),
            **identity(directory / "endpoint-outcomes.json"),
        },
        "policy": {"path": str(directory / "unknown-policy.json"), **identity(directory / "unknown-policy.json")},
        "curated_policy": {"path": str(CURATED_UNKNOWN_POLICY), **identity(CURATED_UNKNOWN_POLICY)},
        "qualification": qualification,
    }
    return GenerationView(
        directory,
        {role: directory / name for role, name in NATIVE_FILES.items()},
        catalogue,
        payloads,
        {url: row["state"] for url, row in states.items()},
        states,
        qualification,
        pointer_identity,
        manifest_identity,
        admission,
        CURATED_UNKNOWN_POLICY,
        canonical(contract),
    )


def load_generation(output_root, *, consume_input=None, admission=None, require_admissible=True):
    """Resolve only the exact sealed generation selected by the atomic production pointer."""
    root = Path(output_root).absolute()
    pointer = strict_json((root / "current.json").read_bytes())
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", pointer.get("generation_id", "")), "Unsafe generation pointer"
    )
    return validate_generation(
        member(root, "generations/" + pointer["generation_id"]),
        pointer["manifest_sha256"],
        consume_input=consume_input,
        admission=admission,
        require_admissible=require_admissible,
    )
