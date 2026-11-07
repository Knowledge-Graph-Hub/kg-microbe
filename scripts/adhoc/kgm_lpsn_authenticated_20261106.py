"""Run the authorized two-key LPSN canary and remaining source without secret evidence."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_ENV = ROOT.parent / "kg-microbe/.env"
EVIDENCE = ROOT / "data/rebuild-evidence/20261105/mediadive-resolution-1734"
CONTINUATION = EVIDENCE / "lpsn-continuation-20261106"
LAUNCHER = ROOT / "scripts/adhoc/kgm_rebuild_20261105.py"
KEYS = ("LPSN_USERNAME", "LPSN_PASSWORD")
AUTH_URL = "https://sso.dsmz.de/auth/realms/dsmz/protocol/openid-connect/token"
FETCH_URL = "https://api.lpsn.dsmz.de/fetch/35300"
TARGET_ID = 35300
TARGET_NAME = "Dryocola"
PHASE3_SHA = "c0086f69a6adc5ab4524b2e19c8792bb7dc675d2e702cdcdf3d7e73b056ea1e2"
MICRO_SHA = "056ce313e2f1b27e1c755c3a4046791f7295dd35a13bb9fab3b328c9774b8924"
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=(.*)$")


def digest(path):
    """Hash public code or scientific evidence only, never a credential file."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def one_line(raw):
    """Reject multiline shell/dotenv constructs without interpreting their values."""
    text = raw.strip()
    if text.endswith("\\"):
        return False
    if not text or text[0] not in "\"'":
        return True
    escaped = False
    for char in text[1:]:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == text[0]:
            return True
    return False


def load_authorized_keys(path):
    """Parse only the two authorized single-line assignments, without interpolation or execution."""
    from dotenv.parser import parse_stream

    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Credential source must be an ordinary file")
    values = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
            if not match or not one_line(match.group(2)):
                raise ValueError("Only single-line credential-source assignments are supported")
            key = match.group(1)
            if key not in KEYS:
                continue
            if key in values:
                raise ValueError("Duplicate authorized credential key")
            bindings = list(parse_stream(io.StringIO(line)))
            if len(bindings) != 1 or bindings[0].error or bindings[0].key != key:
                raise ValueError("Invalid authorized credential assignment")
            value = bindings[0].value
            if not value or any(char in value for char in "\x00\r\n"):
                raise ValueError("Authorized credential must be nonempty and single-line")
            values[key] = value
    if set(values) != set(KEYS):
        raise ValueError("Both authorized credential keys are required")
    return values


def public_payload(value, sensitive=()):
    """Refuse credential/token material before serializing scientific or execution evidence."""
    forbidden = {"access_token", "refresh_token", "password", "authorization", *[key.lower() for key in KEYS]}
    secrets = tuple(sensitive) + tuple(os.environ.get(key, "") for key in KEYS)
    if isinstance(value, dict):
        for key, item in value.items():
            public_payload(str(key), secrets)
            if str(key).lower() in forbidden:
                raise ValueError("Sensitive response field refused")
            public_payload(item, secrets)
    elif isinstance(value, list):
        for item in value:
            public_payload(item, secrets)
    elif isinstance(value, str):
        if any(secret and secret in value for secret in secrets):
            raise ValueError("Sensitive response value refused")


def strict_object(pairs):
    """Refuse duplicate keys before any value can be shadowed during JSON decoding."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key refused")
        result[key] = value
    return result


def safe_failure(error):
    """Keep arbitrary exception names and response content out of failure provenance."""
    for kind in (TimeoutError, OSError, RuntimeError, ValueError, TypeError):
        if isinstance(error, kind):
            return kind.__name__
    return "Exception"


def public_record(payload):
    """Replay the exact public canary taxon identity from the native response envelope."""
    entries = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("One exact native response record required")
    record = entries[0]
    if (
        str(record.get("id")) != str(TARGET_ID)
        or record.get("full_name") != TARGET_NAME
        or record.get("category") != "genus"
    ):
        raise ValueError("Native response identity mismatch")
    return record


def checked_public_body(body, tokens):
    """Reject shadowed, keyed, encoded or raw secrets before a response write or digest."""
    secrets = tuple(tokens) + tuple(os.environ.get(key, "") for key in KEYS)
    if any(secret and secret.encode("utf-8") in body for secret in secrets):
        raise ValueError("Sensitive raw response value refused")
    payload = json.loads(body, object_pairs_hook=strict_object)
    public_payload(payload, secrets)
    public_record(payload)
    return payload


def save(path, value):
    """Create new nonsecret evidence exclusively, leaving all earlier attempts intact."""
    public_payload(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def bindings():
    """Bind the real interpreter, launcher and native LPSN code to this checkout."""
    if Path.cwd().resolve() != ROOT or Path(sys.prefix).resolve() != ROOT / ".venv":
        raise RuntimeError("Use the owned interpreter and worktree")
    sys.path.insert(0, str(ROOT))
    import kg_microbe.transform_utils.lpsn_api.lpsn_api as native

    native_path = Path(native.__file__).resolve()
    if native_path != ROOT / "kg_microbe/transform_utils/lpsn_api/lpsn_api.py":
        raise RuntimeError("Native LPSN module belongs to another checkout")
    return {
        "root": str(ROOT),
        "python": sys.executable,
        "helper_sha256": digest(Path(__file__).resolve()),
        "launcher_sha256": digest(LAUNCHER),
        "native_lpsn_sha256": digest(native_path),
    }


def prerequisite_path(path):
    """Keep explicit prerequisite evidence inside the owned tree without links or traversal."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Prerequisite receipt traversal refused")
    path = path.absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Prerequisite receipt links refused")
    path = path.resolve()
    if not path.is_relative_to(ROOT / "data/rebuild-evidence") or not path.is_file():
        raise ValueError("Require owned prerequisite evidence")
    return path


def prerequisites(
    *,
    phase3_receipt=None,
    phase3_sha256=None,
    microbedecoder_receipt=None,
    microbedecoder_sha256=None,
    admission=None,
):
    """Bind preceding native admissions to the entire current canonical dependency plan."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from scripts.adhoc import kgm_rebuild_admission_20261105 as planner

    supplied = (phase3_receipt, phase3_sha256, microbedecoder_receipt, microbedecoder_sha256)
    if any(value is not None for value in supplied) and not all(value is not None for value in supplied):
        raise ValueError("Supply both prerequisite receipt paths and SHA256 values together")
    prior = prerequisite_path(phase3_receipt if phase3_receipt is not None else EVIDENCE / "phase3-admission-r1.json")
    micro = prerequisite_path(
        microbedecoder_receipt if microbedecoder_receipt is not None else EVIDENCE / "microbedecoder-admission-r1.json"
    )
    prior_sha = phase3_sha256 if phase3_sha256 is not None else PHASE3_SHA
    micro_sha = microbedecoder_sha256 if microbedecoder_sha256 is not None else MICRO_SHA
    if any(
        not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in (prior_sha, micro_sha)
    ):
        raise ValueError("Require exact prerequisite SHA256 values")
    guard = admission if admission is not None else SourceAdmission()
    planner_path = Path(planner.__file__).resolve()
    if planner_path != ROOT / "scripts/adhoc/kgm_rebuild_admission_20261105.py":
        raise RuntimeError("Prerequisite planner belongs to another checkout")
    guard.capture(planner_path)
    guard.capture(ROOT / "merge.yaml")
    bodies = [guard.capture(path, retain=True) for path in (prior, micro)]
    if [hashlib.sha256(body).hexdigest() for body in bodies] != [prior_sha, micro_sha]:
        raise ValueError("Preceding admission receipt identity changed")
    a, b = (json.loads(body, object_pairs_hook=strict_object) for body in bodies)
    plan = planner.build_plan(
        ROOT, ROOT / "data/raw", ROOT / "data/transformed", ROOT / "merge.yaml", ROOT / "data/merged"
    )
    expected = {source for phase in plan["phases"][:3] for source in phase}
    preceding = a.get("verification", {}).get("sources")
    independent = b.get("verification", {}).get("sources")
    if (
        a.get("status") != "pass"
        or b.get("status") != "pass"
        or a.get("root") != str(ROOT)
        or b.get("root") != str(ROOT)
        or a.get("command") != "verify-sources"
        or b.get("command") != "verify-microbedecoder"
        or json.dumps(a.get("plan"), sort_keys=True, allow_nan=False)
        != json.dumps(plan, sort_keys=True, allow_nan=False)
        or json.dumps(b.get("plan"), sort_keys=True, allow_nan=False)
        != json.dumps(plan, sort_keys=True, allow_nan=False)
        or not isinstance(preceding, dict)
        or set(preceding) != expected
        or not isinstance(independent, dict)
        or set(independent) != {"microbedecoder"}
        or len(plan["phases"]) != 4
        or plan["phases"][-1] != ["lpsn_api", "microbedecoder"]
    ):
        raise ValueError("Require preceding canonical source admissions")
    guard.verify()
    return {
        "phase3_receipt": str(prior),
        "phase3_sha256": prior_sha,
        "microbedecoder_receipt": str(micro),
        "microbedecoder_sha256": micro_sha,
        "plan": plan,
    }


@contextlib.contextmanager
def bounded_http(events, fresh_body):
    """Permit one official auth POST and one exact-ID GET, with no retries or redirects."""
    import requests
    from urllib3.util.retry import Retry

    original_request = requests.Session.request
    original_mount = requests.Session.mount
    seen = set()

    def request(session, method, url, **kwargs):
        """Record only public route/status, never request headers, bodies or exception text."""
        pair = (method.upper(), url)
        if pair not in {("POST", AUTH_URL), ("GET", FETCH_URL)} or pair in seen:
            raise RuntimeError("Canary request budget or route exceeded")
        if pair == ("GET", FETCH_URL) and ("POST", AUTH_URL) not in seen:
            raise RuntimeError("Canary fetch must follow authentication")
        seen.add(pair)
        kwargs.update(timeout=(10, 25), allow_redirects=False)
        item = {"method": pair[0], "url": pair[1], "outcome": "transport_error"}
        events.append(item)
        response = original_request(session, method, url, **kwargs)
        item.update(status_code=response.status_code, outcome="http_response")
        if response.status_code != 200:
            raise RuntimeError("Canary HTTP response was not successful")
        if pair == ("GET", FETCH_URL):
            fresh_body.append(response.content)
        return response

    def mount(session, prefix, adapter):
        """Disable library retries at the transport, not just at the public client counter."""
        adapter.max_retries = Retry(total=0, connect=0, read=0, redirect=0, status=0)
        return original_mount(session, prefix, adapter)

    def deadline(signum, frame):
        """Abort the bounded canary without propagating server diagnostic content."""
        raise TimeoutError("Authenticated canary deadline exceeded")

    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise RuntimeError("Another process deadline is already active")
    previous = signal.signal(signal.SIGALRM, deadline)
    requests.Session.request, requests.Session.mount = request, mount
    signal.setitimer(signal.ITIMER_REAL, 90)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        requests.Session.request, requests.Session.mount = original_request, original_mount


def canary(receipt, label):
    """Authenticate and retrieve one real public record without reading or replacing caches."""
    import lpsn

    proof = {"command": "canary", "stage_label": label, "status": "fail", "bindings": bindings(), "requests": []}
    started = time.time()
    bodies = []
    proof["step"] = "authenticate"
    try:
        with bounded_http(proof["requests"], bodies):
            client = lpsn.LpsnClient(
                os.environ[KEYS[0]], os.environ[KEYS[1]], max_retries=1, retry_delay=0, request_timeout=25
            )
            if not all(
                isinstance(getattr(client, key, None), str) and getattr(client, key)
                for key in ("access_token", "refresh_token")
            ):
                raise RuntimeError("Authentication did not initialize the client")
            proof["step"] = "retrieve_exact_record"
            if client.search(id=str(TARGET_ID)) != 1:
                raise RuntimeError("Canary exact-ID search did not select one record")
            records = list(client.retrieve())
        proof["step"] = "validate_public_response"
        if len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("Canary requires one native record")
        record = records[0]
        if (
            str(record.get("id")) != str(TARGET_ID)
            or record.get("full_name") != TARGET_NAME
            or record.get("category") != "genus"
        ):
            raise ValueError("Canary exact record identity mismatch")
        if len(bodies) != 1:
            raise ValueError("Canary response body missing")
        checked_public_body(bodies[0], (client.access_token, client.refresh_token))
        scientific = receipt.with_name(receipt.stem + "-public-response.json")
        with scientific.open("xb") as handle:
            handle.write(bodies[0])
        proof.update(
            status="pass",
            record_id=TARGET_ID,
            record_name=TARGET_NAME,
            record_rank="genus",
            public_response={"path": str(scientific), "sha256": digest(scientific)},
            cache_changed=False,
        )
    except Exception as error:
        proof["failure_type"] = safe_failure(error)
    proof.update(finished=time.time(), seconds=round(time.time() - started, 3), credential_values_saved=False)
    save(receipt, proof)
    return 0 if proof["status"] == "pass" else 1


def validate_canary(path):
    """Require the completed current-code canary before starting the remaining source."""
    if path.is_symlink() or not path.resolve().is_relative_to(CONTINUATION):
        raise ValueError("Require an owned canary receipt")
    proof = json.loads(path.read_text(), object_pairs_hook=strict_object)
    if proof.get("status") != "pass" or proof.get("command") != "canary" or proof.get("bindings") != bindings():
        raise ValueError("Current-code authenticated canary required")
    if not 0 <= time.time() - proof["finished"] <= 24 * 3600:
        raise ValueError("Authenticated canary is outside this continuation window")
    if proof.get("record_id") != TARGET_ID or [item.get("status_code") for item in proof["requests"]] != [200, 200]:
        raise ValueError("Successful auth and exact-ID fetch required")
    public = Path(proof["public_response"]["path"])
    if not public.resolve().is_relative_to(CONTINUATION) or digest(public) != proof["public_response"]["sha256"]:
        raise ValueError("Canary scientific evidence identity changed")
    payload = json.loads(public.read_bytes(), object_pairs_hook=strict_object)
    public_payload(payload)
    public_record(payload)
    label = proof.get("stage_label", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", label):
        raise ValueError("Canary stage label missing")
    result_path = ROOT / "data/rebuild-evidence/20261105/stages" / label / "result.json"
    plan_path = result_path.with_name("plan.json")
    plan = json.loads(plan_path.read_text(), object_pairs_hook=strict_object)
    expected_command = [
        "scripts/adhoc/kgm_lpsn_authenticated_20261106.py",
        "canary",
        "--label",
        label,
        "--receipt",
        str(path.absolute()),
    ]
    expected_digest = hashlib.sha256(
        json.dumps(expected_command, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        plan.get("command_sha256") != expected_digest
        or plan.get("launcher_sha256") != proof["bindings"]["launcher_sha256"]
    ):
        raise ValueError("Actual canary command or launcher differs")
    expected_requests = [("POST", AUTH_URL, 200), ("GET", FETCH_URL, 200)]
    if [(x.get("method"), x.get("url"), x.get("status_code")) for x in proof["requests"]] != expected_requests:
        raise ValueError("Actual canary request routes differ")
    actual = json.loads(result_path.read_text(), object_pairs_hook=strict_object)
    if actual.get("command_sha256") != expected_digest:
        raise ValueError("Completed canary command identity differs")
    if actual.get("exit_code") != 0 or actual.get("python") != str(ROOT / ".venv/bin/python"):
        raise ValueError("Actual canary execution did not succeed")
    for item in actual.get("origins_after", {}).values():
        source = Path(item["file"])
        if not source.resolve().is_relative_to(ROOT / "kg_microbe") or digest(source) != item["sha256"]:
            raise ValueError("Actual canary module identity changed")
    if not actual.get("origins_after"):
        raise ValueError("Actual canary origins missing")
    return {
        "path": str(path),
        "sha256": digest(path),
        "stage_result_sha256": digest(result_path),
        "stage_plan_sha256": digest(plan_path),
    }


def preserve_cache(label):
    """Copy every existing staged LPSN cache file independently before native acquisition."""
    from scripts.adhoc.kgm_rebuild_20261105 import inventory

    destination = CONTINUATION / ("cache-before-" + label)
    destination.mkdir(exist_ok=False)
    members = {}
    for kind in ("api_cache", "web_cache"):
        root = ROOT / "data/raw/lpsn" / kind
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Existing staged LPSN cache directory required")
        before = inventory(root)
        for name in sorted(before):
            source = root / name
            if source.is_symlink():
                raise ValueError("Cache links refused")
            if source.is_dir():
                continue
            if not stat.S_ISREG(source.stat().st_mode):
                raise ValueError("Cache special file refused")
            if source.suffix == ".json" and not isinstance(json.loads(source.read_text()), dict):
                raise ValueError("Existing cache record is not an object")
            relative = source.relative_to(ROOT / "data/raw/lpsn")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            expected = digest(source)
            if digest(target) != expected or (target.stat().st_dev, target.stat().st_ino) == (
                source.stat().st_dev,
                source.stat().st_ino,
            ):
                raise ValueError("Cache preservation failed")
            members[str(relative)] = {"bytes": source.stat().st_size, "sha256": expected}
        if inventory(root) != before:
            raise ValueError("Staged cache changed during preservation")
    save(destination / "manifest.json", {"members": members, "original_staged_directory": str(ROOT / "data/raw/lpsn")})
    return destination


def verify_preserved_cache(label, expected_manifest=None):
    """Require every preexisting staged cache member and its independent preserved copy unchanged."""
    destination = CONTINUATION / ("cache-before-" + label)
    manifest_path = destination / "manifest.json"
    captured = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(captured).hexdigest()
    if expected_manifest is not None and manifest_sha != expected_manifest:
        raise ValueError("Original cache preservation manifest changed")
    manifest = json.loads(captured, object_pairs_hook=strict_object)
    for name, expected in manifest["members"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe cache preservation member")
        for base in (ROOT / "data/raw/lpsn", destination):
            member = base / relative
            if (
                member.is_symlink()
                or member.stat().st_size != expected["bytes"]
                or digest(member) != expected["sha256"]
            ):
                raise ValueError("A preserved cache member changed")
    if digest(manifest_path) != manifest_sha:
        raise ValueError("Cache preservation manifest changed during verification")
    return {
        "manifest": str(manifest_path),
        "sha256": manifest_sha,
        "preserved_files": len(manifest["members"]),
    }


@contextlib.contextmanager
def public_request_ledger(path):
    """Record fixed route kinds, numeric record IDs and statuses during native requests."""
    import requests

    original = requests.Session.request
    with path.open("x", encoding="utf-8") as stream:

        def request(session, method, url, **kwargs):
            """Retain no headers, bodies, query strings, tokens or arbitrary error text."""
            parsed = urlsplit(url)
            item = {
                "method": method.upper() if method.upper() in {"GET", "POST"} else "other",
                "route": "other",
                "outcome": "transport_error",
            }
            if (
                parsed.scheme == "https"
                and parsed.netloc == "sso.dsmz.de"
                and parsed.path == "/auth/realms/dsmz/protocol/openid-connect/token"
            ):
                item["route"] = "authentication"
            elif (
                parsed.scheme == "https"
                and parsed.netloc == "api.lpsn.dsmz.de"
                and re.fullmatch(r"/fetch/[0-9;]+", parsed.path)
            ):
                item.update(
                    route="lpsn_record",
                    record_ids=[int(value) for value in parsed.path.removeprefix("/fetch/").split(";")],
                )
            elif parsed.scheme == "https" and parsed.netloc == "lpsn.dsmz.de":
                item["route"] = "lpsn_public_page"
            started = time.monotonic()
            try:
                response = original(session, method, url, **kwargs)
                code = response.status_code
                if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
                    item.update(status_code=code, outcome="http_response")
                return response
            except Exception as error:
                item["failure_type"] = safe_failure(error)
                raise
            finally:
                item["seconds"] = round(time.monotonic() - started, 3)
                stream.write(json.dumps(item, sort_keys=True) + "\n")
                stream.flush()

        requests.Session.request = request
        try:
            yield
        finally:
            requests.Session.request = original


def phase(receipt, canary_receipt, label, *, prerequisite_inputs=None):
    """Use the unchanged native dispatcher for only the remaining canonical source."""
    import kg_microbe.transform as dispatcher
    from kg_microbe.merge_utils.artifact_manifest import file_identity
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    admission = SourceAdmission()
    proof = {
        "command": "phase",
        "status": "fail",
        "bindings": bindings(),
        "prerequisites": prerequisites(**(prerequisite_inputs or {}), admission=admission),
        "canary": validate_canary(canary_receipt),
        "sources": ["lpsn_api"],
        "preserved_cache_before": verify_preserved_cache(label),
    }
    try:
        admission.verify()
        with public_request_ledger(receipt.with_name(receipt.stem + "-requests.jsonl")):
            dispatcher.transform(
                input_dir=ROOT / "data/raw",
                output_dir=ROOT / "data/transformed",
                sources=["lpsn_api"],
                show_status=False,
            )
        admission.verify()
        directory = ROOT / "data/transformed/lpsn_api"
        proof.update(
            status="producer_pass",
            preserved_cache_after=verify_preserved_cache(label, proof["preserved_cache_before"]["sha256"]),
            graphs={name: file_identity(directory / name) for name in ("nodes.tsv", "edges.tsv")},
            finalization_sha256=digest(directory / "source_finalization.json"),
            full_source_admission_pending=True,
        )
    except Exception as error:
        proof["failure_type"] = safe_failure(error)
    ledger = receipt.with_name(receipt.stem + "-requests.jsonl")
    if ledger.exists():
        proof["request_ledger"] = {"path": str(ledger), "sha256": digest(ledger)}
    save(receipt, proof)
    return 0 if proof["status"] == "producer_pass" else 1


def main():
    """Load allowlisted values only for a fixed launcher command, never into arguments or files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("launch-canary", "launch-phase", "canary", "phase"))
    parser.add_argument("--label", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--canary-receipt", type=Path)
    parser.add_argument("--phase3-receipt", type=Path)
    parser.add_argument("--phase3-sha256")
    parser.add_argument("--microbedecoder-receipt", type=Path)
    parser.add_argument("--microbedecoder-sha256")
    args = parser.parse_args()
    selected = {
        "phase3_receipt": args.phase3_receipt,
        "phase3_sha256": args.phase3_sha256,
        "microbedecoder_receipt": args.microbedecoder_receipt,
        "microbedecoder_sha256": args.microbedecoder_sha256,
    }
    explicit = any(value is not None for value in selected.values())
    if explicit and "phase" not in args.mode:
        raise ValueError("Prerequisite selection applies only to phase modes")
    receipt = args.receipt.absolute()
    if not receipt.resolve().is_relative_to(CONTINUATION) or receipt.exists():
        raise ValueError("Use a new continuation receipt")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.label):
        raise ValueError("Use a unique safe stage label")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    bindings()
    admission = None
    if "phase" in args.mode:
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        admission = SourceAdmission()
        admitted = prerequisites(**selected, admission=admission)
        if explicit:
            selected = {key: admitted[key] for key in selected}
        if args.canary_receipt is None:
            raise ValueError("Phase requires the actual authenticated canary receipt")
        validate_canary(args.canary_receipt)
    if args.mode.startswith("launch-"):
        if args.mode == "launch-phase":
            preserve_cache(args.label)
            admission.verify()
        values = load_authorized_keys(ORIGINAL_ENV)
        child_env = dict(os.environ)
        child_env.update(values)
        mode = args.mode.removeprefix("launch-")
        command = [
            str(ROOT / ".venv/bin/python"),
            "-B",
            str(LAUNCHER),
            "launch",
            args.label,
            "--",
            "scripts/adhoc/kgm_lpsn_authenticated_20261106.py",
            mode,
            "--label",
            args.label,
            "--receipt",
            str(receipt),
        ]
        if args.canary_receipt:
            command.extend(["--canary-receipt", str(args.canary_receipt)])
        if explicit:
            for key, value in selected.items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
        if admission is not None:
            admission.verify()
        # Suppress the first credential-bearing interpreter before startup and imports.
        return subprocess.run(  # noqa: S603 - fixed owned script, no shell
            command, cwd=ROOT, env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        ).returncode
    if Path(os.environ.get("KGM_REBUILD_LAUNCHER", "")).resolve() != LAUNCHER or not all(
        os.environ.get(key) for key in KEYS
    ):
        raise RuntimeError("Authenticated stages require the reviewed launcher and two environment keys")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    return (
        canary(receipt, args.label)
        if args.mode == "canary"
        else phase(receipt, args.canary_receipt, args.label, prerequisite_inputs=selected)
    )


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        # The outer parser must also fail without echoing a value or exception payload.
        print('{"status":"fail","reason":"authenticated continuation precondition failed"}')
        result = 1
    raise SystemExit(result)
