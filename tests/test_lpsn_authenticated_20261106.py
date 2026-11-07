"""Offline controls for the allowlisted credential and authenticated canary boundary."""

import contextlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/kgm_lpsn_authenticated_20261106.py"


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """Load the helper with owned temporary paths and no real credential environment."""
    spec = importlib.util.spec_from_file_location("auth_continuation_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "owned"
    root.mkdir()
    continuation = root / "data/evidence"
    continuation.mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "CONTINUATION", continuation)
    for key in module.KEYS:
        monkeypatch.delenv(key, raising=False)
    return module


def test_allowlisted_parser_never_expands_or_executes(helper, tmp_path, monkeypatch):
    """Shell expressions remain literal; unrelated credentials are neither loaded nor returned."""
    source = tmp_path / ".env"
    marker = tmp_path / "must-not-exist"
    source.write_text(
        "# synthetic only\nUNRELATED_TOKEN=do-not-load\n"
        "export LPSN_USERNAME='name@example.test'\n"
        f"LPSN_PASSWORD='$(touch {marker})$HOME${{UNRELATED_TOKEN}}'\n"
    )
    monkeypatch.setenv("UNRELATED_TOKEN", "unchanged-parent-value")
    before = dict(os.environ)
    result = helper.load_authorized_keys(source)
    assert result == {
        "LPSN_USERNAME": "name@example.test",
        "LPSN_PASSWORD": f"$(touch {marker})$HOME${{UNRELATED_TOKEN}}",
    }
    assert dict(os.environ) == before
    assert not marker.exists()


@pytest.mark.parametrize(
    "text",
    [
        "LPSN_USERNAME=u\n",
        "LPSN_PASSWORD=p\n",
        "LPSN_USERNAME=u\nLPSN_PASSWORD=\n",
        "LPSN_USERNAME=u\nLPSN_PASSWORD=p\nLPSN_PASSWORD=q\n",
        'LPSN_USERNAME=u\nLPSN_PASSWORD="line\\nsecret"\n',
        'LPSN_USERNAME=u\nLPSN_PASSWORD="unterminated\n',
        'UNRELATED="multiline\nLPSN_USERNAME=u\nLPSN_PASSWORD=p\n"\n',
        "LPSN_USERNAME=u\nLPSN_PASSWORD=p\\\n",
    ],
)
def test_parser_refuses_ambiguous_or_incomplete_source(helper, tmp_path, text):
    """Incomplete, duplicate and multiline input cannot silently broaden the authorized parse."""
    source = tmp_path / ".env"
    source.write_text(text)
    with pytest.raises(ValueError):
        helper.load_authorized_keys(source)


def test_parser_refuses_symlink(helper, tmp_path):
    """The fixed original credential locator cannot be redirected through a symbolic link."""
    target = tmp_path / "actual"
    target.write_text("LPSN_USERNAME=u\nLPSN_PASSWORD=p\n")
    alias = tmp_path / ".env"
    alias.symlink_to(target)
    with pytest.raises(ValueError, match="ordinary file"):
        helper.load_authorized_keys(alias)


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "opaque"},
        {"nested": [{"refresh_token": "opaque"}]},
        {"value": "before synthetic-password after"},
    ],
)
def test_public_receipt_refuses_sensitive_material(helper, monkeypatch, payload):
    """Credential values or token fields cannot enter retained JSON evidence."""
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-password")
    path = helper.CONTINUATION / "receipt.json"
    with pytest.raises(ValueError, match="Sensitive"):
        helper.save(path, payload)
    assert not path.exists()


def test_bounded_transport_budget_no_redirect_retry_or_auth_body_retention(helper, monkeypatch):
    """Actual session interception admits only one POST and one GET and retains no auth body."""
    import requests

    calls, events, bodies = [], [], []

    def original(session, method, url, **kwargs):
        """Model HTTP success without retaining the authentication body."""
        calls.append((method, url, kwargs))
        return SimpleNamespace(
            status_code=200, content=b"opaque-auth-token" if url == helper.AUTH_URL else b'{"results": []}'
        )

    monkeypatch.setattr(requests.Session, "request", original)
    with helper.bounded_http(events, bodies):
        session = requests.Session()
        assert session.adapters["https://"].max_retries.total == 0
        session.request("POST", helper.AUTH_URL)
        session.request("GET", helper.FETCH_URL)
        for method, url in [
            ("GET", helper.FETCH_URL),
            ("POST", helper.AUTH_URL),
            ("GET", "https://unapproved.invalid/"),
        ]:
            with pytest.raises(RuntimeError, match="budget or route"):
                session.request(method, url)
    assert len(calls) == 2
    assert all(call[2]["allow_redirects"] is False and call[2]["timeout"] == (10, 25) for call in calls)
    assert bodies == [b'{"results": []}']
    assert "opaque-auth-token" not in json.dumps(events)
    assert requests.Session.request is original


@pytest.mark.parametrize("status", [302, 401, 403, 503])
def test_bounded_transport_refuses_non_success(helper, monkeypatch, status):
    """A redirect or upstream failure is a failed canary, never a fresh association response."""
    import requests

    monkeypatch.setattr(
        requests.Session, "request", lambda *a, **k: SimpleNamespace(status_code=status, content=b"secret-response")
    )
    events, bodies = [], []
    with helper.bounded_http(events, bodies):
        with pytest.raises(RuntimeError, match="not successful"):
            requests.Session().request("POST", helper.AUTH_URL)
    assert events == [{"method": "POST", "url": helper.AUTH_URL, "outcome": "http_response", "status_code": status}]
    assert bodies == []


@pytest.mark.parametrize("damage", [None, "no_tokens", "wrong_id", "wrong_name", "extra_record", "exception"])
def test_canary_keeps_only_exact_public_success(helper, monkeypatch, damage):
    """Only a token-initialized exact record may produce public scientific evidence."""
    monkeypatch.setenv("LPSN_USERNAME", "synthetic-user")
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-password")
    monkeypatch.setattr(helper, "bindings", lambda: {"public_binding": "fixed"})
    record = {"id": 35300, "full_name": "Dryocola", "category": "genus"}
    if damage == "wrong_id":
        record["id"] = 35301
    if damage == "wrong_name":
        record["full_name"] = "Different taxon"
    records = [record, record] if damage == "extra_record" else [record]

    class Client:
        """Synthetic in-memory client; no credentials or endpoints are real."""

        def __init__(self, user, password, **kwargs):
            """Initialize synthetic in-memory authentication state for the canary control."""
            assert user == "synthetic-user" and password == "synthetic-password"  # noqa: S105 - offline synthetic control
            assert kwargs == {"max_retries": 1, "retry_delay": 0, "request_timeout": 25}
            if damage != "no_tokens":
                self.access_token = "synthetic-access"  # noqa: S105 - offline synthetic control
                self.refresh_token = "synthetic-refresh"  # noqa: S105 - offline synthetic control

        def search(self, *, id):
            """Select the single synthetic record without contacting a service."""
            assert id == "35300"
            return 1

        def retrieve(self):
            """Yield public fixture records or a synthetic secret-bearing exception."""
            if damage == "exception":
                raise RuntimeError("synthetic-password synthetic-access")
            return iter(records)

    @contextlib.contextmanager
    def http(events, bodies):
        """Supply only synthetic bounded canary events and a public scientific response."""
        events.extend(
            [
                {"method": "POST", "url": helper.AUTH_URL, "status_code": 200},
                {"method": "GET", "url": helper.FETCH_URL, "status_code": 200},
            ]
        )
        bodies.append(json.dumps({"results": records}).encode())
        yield

    monkeypatch.setitem(sys.modules, "lpsn", SimpleNamespace(LpsnClient=Client))
    monkeypatch.setattr(helper, "bounded_http", http)
    path = helper.CONTINUATION / "canary.json"
    assert helper.canary(path, "synthetic-canary") == (0 if damage is None else 1)
    saved = path.read_text()
    assert "synthetic-password" not in saved and "synthetic-access" not in saved
    proof = json.loads(saved)
    assert proof["status"] == ("pass" if damage is None else "fail")
    assert path.with_name("canary-public-response.json").exists() is (damage is None)


def test_cache_preservation_independent_and_mutation_refused(helper):
    """Original staged successes and their independently copied bytes survive the later phase."""
    for kind in ("api_cache", "web_cache"):
        directory = helper.ROOT / "data/raw/lpsn" / kind
        directory.mkdir(parents=True)
        (directory / "35300.json").write_text('{"id":35300}')
    preserved = helper.preserve_cache("test")
    proof = helper.verify_preserved_cache("test")
    assert proof["preserved_files"] == 2
    original = helper.ROOT / "data/raw/lpsn/api_cache/35300.json"
    assert original.stat().st_ino != (preserved / "api_cache/35300.json").stat().st_ino
    original.write_text('{"id":35301}')
    with pytest.raises(ValueError, match="changed"):
        helper.verify_preserved_cache("test")
    assert (preserved / "api_cache/35300.json").read_text() == '{"id":35300}'


@pytest.mark.parametrize(
    "damage", ["duplicate", "secret_key", "encoded_value", "token_value", "encoded_token", "token_key"]
)
def test_raw_public_response_secret_scan_before_any_write(helper, monkeypatch, damage):
    """Shadowed values, JSON keys and client tokens cannot evade the pre-persistence scan."""
    monkeypatch.setenv("LPSN_PASSWORD", "synthetic-password")
    record = {"id": 35300, "full_name": "Dryocola", "category": "genus"}
    payload = {"results": [record]}
    if damage == "duplicate":
        body = b'{"note":"\\u0073ynthetic-password","note":"public","results":' + json.dumps([record]).encode() + b"}"
    elif damage == "secret_key":
        payload["synthetic-password"] = "public"
        body = json.dumps(payload).encode()
    elif damage == "encoded_value":
        payload["note"] = "synthetic-password"
        body = json.dumps(payload).replace("synthetic-password", "\\u0073ynthetic-password").encode()
    elif damage == "encoded_token":
        payload["note"] = "synthetic-access"
        body = json.dumps(payload).replace("synthetic-access", "\\u0073ynthetic-access").encode()
    else:
        payload["note" if damage == "token_value" else "synthetic-access"] = (
            "synthetic-access" if damage == "token_value" else "public"
        )
        body = json.dumps(payload).encode()
    with pytest.raises(ValueError):
        helper.checked_public_body(body, ("synthetic-access", "synthetic-refresh"))
    assert list(helper.CONTINUATION.iterdir()) == []


def test_fixed_failure_category_cannot_persist_dynamic_token(helper):
    """Even an exception type name is not trusted nonsecret provenance."""
    error = type("synthetic-access-token", (Exception,), {})()
    assert helper.safe_failure(error) == "Exception"


def test_manifest_cohort_cannot_shrink_while_original_cache_changes(helper):
    """Changing a cache and deleting its manifest entry must fail despite surviving copies."""
    for kind in ("api_cache", "web_cache"):
        directory = helper.ROOT / "data/raw/lpsn" / kind
        directory.mkdir(parents=True)
        (directory / "35300.json").write_text('{"id":35300}')
    directory = helper.preserve_cache("cohort")
    before = helper.verify_preserved_cache("cohort")
    (helper.ROOT / "data/raw/lpsn/api_cache/35300.json").write_text('{"id":35301}')
    manifest = directory / "manifest.json"
    body = json.loads(manifest.read_text())
    del body["members"]["api_cache/35300.json"]
    manifest.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="manifest changed"):
        helper.verify_preserved_cache("cohort", before["sha256"])


def test_cache_new_success_allowed_without_modifying_original_cohort(helper):
    """New scientific responses may be added while original successes remain byte-identical."""
    for kind in ("api_cache", "web_cache"):
        directory = helper.ROOT / "data/raw/lpsn" / kind
        directory.mkdir(parents=True)
        (directory / "35300.json").write_text('{"id":35300}')
    helper.preserve_cache("addition")
    before = helper.verify_preserved_cache("addition")
    (helper.ROOT / "data/raw/lpsn/api_cache/35301.json").write_text('{"id":35301}')
    assert helper.verify_preserved_cache("addition", before["sha256"]) == before


def test_cache_inventory_failure_is_not_a_partial_backup(helper, monkeypatch):
    """Unreadable cache descendants abort preservation instead of silently reducing membership."""
    from scripts.adhoc import kgm_rebuild_20261105 as launcher

    for kind in ("api_cache", "web_cache"):
        (helper.ROOT / "data/raw/lpsn" / kind).mkdir(parents=True)

    def denied(root):
        """Simulate an unreadable descendant without producing a partial inventory."""
        raise PermissionError("synthetic unreadable subtree")

    monkeypatch.setattr(launcher, "inventory", denied)
    with pytest.raises(PermissionError):
        helper.preserve_cache("unreadable")
    assert not (helper.CONTINUATION / "cache-before-unreadable/manifest.json").exists()


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "missing_plan_digest",
        "wrong_plan_digest",
        "missing_result_digest",
        "wrong_result_digest",
        "failed_result",
        "wrong_mode",
        "wrong_body",
        "missing_origins",
    ],
)
def test_canary_admission_requires_actual_private_command_and_result(helper, monkeypatch, damage):
    """Replay authenticated plan/result digests and public record identity without plaintext args."""
    import time

    from scripts.adhoc import kgm_rebuild_20261105 as launcher

    label = "synthetic-canary"
    path = helper.CONTINUATION / "canary.json"
    bound = {"launcher_sha256": "a" * 64}
    monkeypatch.setattr(helper, "bindings", lambda: bound)
    public = helper.CONTINUATION / "public.json"
    public.write_text(json.dumps({"results": [{"id": 35300, "full_name": "Dryocola", "category": "genus"}]}))
    source = helper.ROOT / "kg_microbe/__init__.py"
    source.parent.mkdir()
    source.write_text('"""Synthetic owned module."""\n')
    command = ["scripts/adhoc/kgm_lpsn_authenticated_20261106.py", "canary", "--label", label, "--receipt", str(path)]
    if damage == "wrong_mode":
        command[1] = "phase"
    command_sha = launcher.command_sha256(command)
    folder = helper.ROOT / "data/rebuild-evidence/20261105/stages" / label
    folder.mkdir(parents=True)
    plan = {"command_withheld": True, "command_sha256": command_sha, "launcher_sha256": bound["launcher_sha256"]}
    result = {
        "command_withheld": True,
        "command_sha256": command_sha,
        "exit_code": 0,
        "python": str(helper.ROOT / ".venv/bin/python"),
        "origins_after": {"kg_microbe": {"file": str(source), "sha256": helper.digest(source)}},
    }
    for target, field in [(plan, "plan"), (result, "result")]:
        if damage == "missing_" + field + "_digest":
            target.pop("command_sha256")
        if damage == "wrong_" + field + "_digest":
            target["command_sha256"] = "b" * 64
    if damage == "failed_result":
        result["exit_code"] = 1
    if damage == "missing_origins":
        result["origins_after"] = {}
    if damage == "wrong_body":
        public.write_text(json.dumps({"results": [{"id": 35301, "full_name": "Dryocola", "category": "genus"}]}))
    (folder / "plan.json").write_text(json.dumps(plan))
    (folder / "result.json").write_text(json.dumps(result))
    proof = {
        "command": "canary",
        "stage_label": label,
        "status": "pass",
        "bindings": bound,
        "finished": time.time(),
        "record_id": 35300,
        "public_response": {"path": str(public), "sha256": helper.digest(public)},
        "requests": [
            {"method": "POST", "url": helper.AUTH_URL, "status_code": 200},
            {"method": "GET", "url": helper.FETCH_URL, "status_code": 200},
        ],
    }
    path.write_text(json.dumps(proof))
    if damage is None:
        checked = helper.validate_canary(path)
        assert checked["stage_result_sha256"] == helper.digest(folder / "result.json")
        assert checked["stage_plan_sha256"] == helper.digest(folder / "plan.json")
    else:
        with pytest.raises(ValueError):
            helper.validate_canary(path)


def test_first_credential_bearing_interpreter_startup_is_silent(helper, monkeypatch, tmp_path, capfd):
    """A startup print before launcher protections cannot disclose environment credentials."""
    source = tmp_path / "source.env"
    source.write_text("LPSN_USERNAME=synthetic-user\nLPSN_PASSWORD=synthetic-password\nUNRELATED_TOKEN=ignored\n")
    monkeypatch.setattr(helper, "ORIGINAL_ENV", source)
    monkeypatch.setattr(helper, "bindings", lambda: {})
    python = helper.ROOT / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    launcher = helper.ROOT / "startup.py"
    launcher.write_text(
        "import os, sys\nprint(os.environ['LPSN_PASSWORD'])\nprint(os.environ['LPSN_USERNAME'], file=sys.stderr)\n"
    )
    monkeypatch.setattr(helper, "LAUNCHER", launcher)
    receipt = helper.CONTINUATION / "receipt.json"
    monkeypatch.setattr(sys, "argv", ["helper", "launch-canary", "--label", "test", "--receipt", str(receipt)])
    assert helper.main() == 0
    captured = capfd.readouterr()
    assert captured.out == captured.err == ""
    assert "LPSN_PASSWORD" not in os.environ and "LPSN_USERNAME" not in os.environ
    assert not receipt.exists()


@pytest.mark.parametrize("fails", [False, True])
def test_native_request_ledger_retains_no_sensitive_request_or_error_text(helper, monkeypatch, fails):
    """Only route/status/counters survive; credentials, tokens, URL queries and errors do not."""
    import requests

    def request(*args, **kwargs):
        """Simulate an upstream response or sensitive error entirely offline."""
        if fails:
            raise OSError("synthetic-password synthetic-token")
        return SimpleNamespace(
            status_code=200, content=b"synthetic-token", headers={"Authorization": "synthetic-token"}
        )

    monkeypatch.setattr(requests.Session, "request", request)
    path = helper.CONTINUATION / "requests.jsonl"
    with helper.public_request_ledger(path):
        if fails:
            with pytest.raises(OSError):
                requests.Session().request(
                    "GET", helper.FETCH_URL + "?token=synthetic-token", headers={"Authorization": "synthetic-token"}
                )
        else:
            requests.Session().request("POST", helper.AUTH_URL, data={"password": "synthetic-password"})
    text = path.read_text()
    assert "synthetic-password" not in text and "synthetic-token" not in text and "Authorization" not in text
    item = json.loads(text)
    assert item["route"] == ("lpsn_record" if fails else "authentication")
    assert item["outcome"] == ("transport_error" if fails else "http_response")
    if fails:
        assert item["record_ids"] == [35300] and item["failure_type"] == "OSError"
    else:
        assert item["status_code"] == 200
    assert requests.Session.request is request


def test_manifest_changed_during_verification_is_refused(helper, monkeypatch):
    """The parsed cohort and reported digest must come from one immutable captured byte string."""
    for kind in ("api_cache", "web_cache"):
        directory = helper.ROOT / "data/raw/lpsn" / kind
        directory.mkdir(parents=True)
        (directory / "35300.json").write_text('{"id":35300}')
    preserved = helper.preserve_cache("mid-check")
    manifest = preserved / "manifest.json"
    before = helper.digest(manifest)
    original_digest = helper.digest
    changed = False

    def digest(path):
        """Mutate the manifest during member verification to exercise identity binding."""
        nonlocal changed
        value = original_digest(path)
        if path.name == "35300.json" and not changed:
            changed = True
            body = json.loads(manifest.read_bytes())
            del body["members"]["api_cache/35300.json"]
            manifest.write_text(json.dumps(body))
        return value

    monkeypatch.setattr(helper, "digest", digest)
    with pytest.raises(ValueError, match="changed during verification"):
        helper.verify_preserved_cache("mid-check", before)
    assert changed


@pytest.fixture
def prerequisite_records(helper, monkeypatch):
    """Model owned native admission receipts against an independently selected finite plan."""
    from scripts.adhoc import kgm_rebuild_admission_20261105 as planner

    evidence = helper.ROOT / "data/rebuild-evidence/synthetic-prerequisites"
    evidence.mkdir(parents=True)
    monkeypatch.setattr(helper, "EVIDENCE", evidence)
    config = helper.ROOT / "merge.yaml"
    config.write_text("synthetic canonical configuration\n")
    planner_file = helper.ROOT / "scripts/adhoc/kgm_rebuild_admission_20261105.py"
    planner_file.parent.mkdir(parents=True)
    planner_file.write_text('"""Synthetic planner origin for this isolated boundary fixture."""\n')
    monkeypatch.setattr(planner, "__file__", str(planner_file))
    plan = {
        "phases": [["ontologies"], ["bacdive", "mediadive"], ["gold"], ["lpsn_api", "microbedecoder"]],
        "sources": {
            name: [str(helper.ROOT / "data/transformed" / name / "nodes.tsv")]
            for name in ("ontologies", "bacdive", "mediadive", "gold", "lpsn_api", "microbedecoder")
        },
        "merge_config": str(config),
        "raw_directory": str(helper.ROOT / "data/raw"),
        "transformed_directory": str(helper.ROOT / "data/transformed"),
        "merged_directory": str(helper.ROOT / "data/merged"),
    }
    calls = []

    def build_plan(*args):
        """Return the current fixture plan independently of the receipt's self-description."""
        calls.append(args)
        return json.loads(json.dumps(plan))

    monkeypatch.setattr(planner, "build_plan", build_plan)
    selected = {}
    for kind, command, names, filename in (
        ("phase3", "verify-sources", ["ontologies", "bacdive", "mediadive", "gold"], "phase3-admission-r1.json"),
        ("microbedecoder", "verify-microbedecoder", ["microbedecoder"], "microbedecoder-admission-r1.json"),
    ):
        path = evidence / filename
        path.write_text(
            json.dumps(
                {
                    "root": str(helper.ROOT),
                    "status": "pass",
                    "command": command,
                    "plan": plan,
                    "verification": {"sources": {name: {} for name in names}},
                }
            )
        )
        selected[kind + "_receipt"] = path
        selected[kind + "_sha256"] = helper.digest(path)
    return selected, plan, calls


def _phase_arguments(helper, selected, mode="launch-phase"):
    """Select public receipt locators only; no synthetic credentials enter argv."""
    args = [
        "helper",
        mode,
        "--label",
        "synthetic-phase",
        "--receipt",
        str(helper.CONTINUATION / "phase.json"),
        "--canary-receipt",
        str(helper.CONTINUATION / "canary.json"),
    ]
    for key, value in selected.items():
        args.extend(["--" + key.replace("_", "-"), str(value)])
    return args


def test_explicit_owned_prerequisites_bind_current_plan_and_exact_receipts(helper, prerequisite_records):
    """New receipt bytes need independent exact hashes and the current complete plan/cohort."""
    selected, plan, calls = prerequisite_records
    checked = helper.prerequisites(**selected)
    assert checked == {**{key: str(value) for key, value in selected.items()}, "plan": plan}
    assert calls == [
        (
            helper.ROOT,
            helper.ROOT / "data/raw",
            helper.ROOT / "data/transformed",
            helper.ROOT / "merge.yaml",
            helper.ROOT / "data/merged",
        )
    ]


def test_historical_default_receipt_selection_is_preserved(helper, prerequisite_records, monkeypatch):
    """Omitting all four selectors retains the original named-file and digest contract."""
    selected, plan, _ = prerequisite_records
    monkeypatch.setattr(helper, "PHASE3_SHA", selected["phase3_sha256"])
    monkeypatch.setattr(helper, "MICRO_SHA", selected["microbedecoder_sha256"])
    assert helper.prerequisites() == {**{key: str(value) for key, value in selected.items()}, "plan": plan}


@pytest.mark.parametrize("kind", ["phase3", "microbedecoder"])
@pytest.mark.parametrize(
    "damage", ["old_root", "wrong_plan", "failed", "wrong_command", "missing_source", "extra_source", "source_list"]
)
def test_hash_bound_prerequisite_still_requires_owned_current_admission(helper, prerequisite_records, kind, damage):
    """Even a supplied matching digest cannot authorize old-root, scope or command changes."""
    selected, _, _ = prerequisite_records
    path = selected[kind + "_receipt"]
    body = json.loads(path.read_text())
    if damage == "old_root":
        body["root"] = str(helper.ROOT.parent / "old-W1")
    elif damage == "wrong_plan":
        body["plan"]["raw_directory"] = str(helper.ROOT.parent / "old-W1/data/raw")
    elif damage == "failed":
        body["status"] = "fail"
    elif damage == "wrong_command":
        body["command"] = "plan"
    elif damage == "missing_source":
        body["verification"]["sources"].pop(next(iter(body["verification"]["sources"])))
    elif damage == "extra_source":
        body["verification"]["sources"]["unexpected"] = {}
    else:
        body["verification"]["sources"] = list(body["verification"]["sources"])
    path.write_text(json.dumps(body))
    selected[kind + "_sha256"] = helper.digest(path)
    with pytest.raises(ValueError, match="canonical source admissions"):
        helper.prerequisites(**selected)


@pytest.mark.parametrize("kind", ["phase3", "microbedecoder"])
def test_changed_selected_receipt_is_refused(helper, prerequisite_records, kind):
    """A new digest cannot be inferred from changed admission bytes."""
    selected, _, _ = prerequisite_records
    with selected[kind + "_receipt"].open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="receipt identity changed"):
        helper.prerequisites(**selected)


@pytest.mark.parametrize("damage", ["foreign", "traversal", "linked_file", "linked_parent"])
def test_selected_prerequisite_locators_refuse_escape_and_links(helper, prerequisite_records, damage):
    """Receipt contents cannot turn an unsafe locator into owned native evidence."""
    selected, _, _ = prerequisite_records
    source = selected["phase3_receipt"]
    if damage == "foreign":
        target = helper.ROOT.parent / "old-W1" / source.name
        target.parent.mkdir()
        target.write_bytes(source.read_bytes())
    elif damage == "traversal":
        target = source.parent / "unused" / ".." / source.name
    elif damage == "linked_file":
        target = source.with_name("linked.json")
        target.symlink_to(source)
    else:
        alias = source.parent / "linked-directory"
        alias.symlink_to(source.parent, target_is_directory=True)
        target = alias / source.name
    selected["phase3_receipt"] = target
    with pytest.raises(ValueError, match="owned prerequisite|traversal|links"):
        helper.prerequisites(**selected)


@pytest.mark.parametrize(
    "missing", ["phase3_receipt", "phase3_sha256", "microbedecoder_receipt", "microbedecoder_sha256"]
)
def test_prerequisite_quartet_cannot_mix_explicit_and_historical_selection(helper, prerequisite_records, missing):
    """Partial overrides cannot accidentally pair new evidence with old pinned receipts."""
    selected, _, _ = prerequisite_records
    selected.pop(missing)
    with pytest.raises(ValueError, match="together"):
        helper.prerequisites(**selected)


def test_duplicate_prerequisite_keys_are_refused_even_with_matching_hash(helper, prerequisite_records):
    """The receipt root cannot be shadowed by a second apparently owned value."""
    selected, _, _ = prerequisite_records
    path = selected["phase3_receipt"]
    body = path.read_text()
    path.write_text('{"root":"foreign",' + body[1:])
    selected["phase3_sha256"] = helper.digest(path)
    with pytest.raises(ValueError, match="Duplicate JSON"):
        helper.prerequisites(**selected)


@pytest.mark.parametrize("mode", ["canary", "launch-canary"])
def test_prerequisite_options_cannot_change_fixed_canary_command(helper, prerequisite_records, monkeypatch, mode):
    """The phase quartet is rejected before imports or credential loading in canary modes."""
    selected, _, _ = prerequisite_records
    monkeypatch.setattr(sys, "argv", _phase_arguments(helper, selected, mode))
    monkeypatch.setattr(helper, "bindings", lambda: pytest.fail("canary bindings should not run"))
    monkeypatch.setattr(helper, "load_authorized_keys", lambda path: pytest.fail("credentials should not load"))
    with pytest.raises(ValueError, match="only to phase"):
        helper.main()


@pytest.mark.parametrize("mutation", [None, "receipt_during_cache", "config_during_cache", "receipt_during_key_load"])
def test_phase_launch_preserves_selection_and_refuses_drift_before_spawn(
    helper, prerequisite_records, monkeypatch, mutation
):
    """The fixed child receives exact public selectors, and guarded bytes survive setup."""
    selected, _, _ = prerequisite_records
    monkeypatch.setattr(helper, "bindings", lambda: {})
    monkeypatch.setattr(helper, "validate_canary", lambda path: {"path": str(path), "sha256": "c" * 64})
    observed = []
    monkeypatch.setattr(sys, "argv", _phase_arguments(helper, selected))

    def preserve(label):
        """Simulate cache work and optional concurrent public-input drift without real caches."""
        observed.append("cache")
        if mutation in {"receipt_during_cache", "config_during_cache"}:
            path = selected["phase3_receipt"] if mutation == "receipt_during_cache" else helper.ROOT / "merge.yaml"
            with path.open("a") as stream:
                stream.write("\n")

    def keys(path):
        """Supply synthetic process-only values without opening any credential locator."""
        observed.append("keys")
        if mutation == "receipt_during_key_load":
            with selected["microbedecoder_receipt"].open("a") as stream:
                stream.write("\n")
        return {"LPSN_USERNAME": "synthetic-name", "LPSN_PASSWORD": "synthetic-password"}

    def run(command, **kwargs):
        """Intercept the launcher; never start a process or authenticate."""
        observed.append("spawn")
        assert command[:8] == [
            str(helper.ROOT / ".venv/bin/python"),
            "-B",
            str(helper.LAUNCHER),
            "launch",
            "synthetic-phase",
            "--",
            "scripts/adhoc/kgm_lpsn_authenticated_20261106.py",
            "phase",
        ]
        for key, value in selected.items():
            assert command[command.index("--" + key.replace("_", "-")) + 1] == str(value)
        assert "synthetic-name" not in command and "synthetic-password" not in command
        assert kwargs["env"]["LPSN_USERNAME"] == "synthetic-name"
        assert kwargs["env"]["LPSN_PASSWORD"] == "synthetic-password"  # noqa: S105 - synthetic offline fixture
        assert kwargs["stdout"] == kwargs["stderr"] == helper.subprocess.DEVNULL
        assert kwargs["cwd"] == helper.ROOT and kwargs["check"] is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper, "preserve_cache", preserve)
    monkeypatch.setattr(helper, "load_authorized_keys", keys)
    monkeypatch.setattr(helper.subprocess, "run", run)
    if mutation is None:
        assert helper.main() == 0
        assert observed == ["cache", "keys", "spawn"]
    else:
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        with pytest.raises(SourceFinalizationRequired, match="changed"):
            helper.main()
        assert observed == (["cache", "keys"] if mutation == "receipt_during_key_load" else ["cache"])
    assert all(key not in os.environ for key in helper.KEYS)
    assert not (helper.CONTINUATION / "phase.json").exists()


def test_phase_child_replays_selected_bytes_before_native_dispatch(helper, prerequisite_records, monkeypatch):
    """A changed receipt after parent launch cannot reach the native producer in the child."""
    import kg_microbe.transform as dispatcher

    selected, _, _ = prerequisite_records
    helper.prerequisites(**selected)
    monkeypatch.setattr(helper, "bindings", lambda: {})
    monkeypatch.setattr(helper, "validate_canary", lambda path: pytest.fail("changed prerequisite must fail first"))
    monkeypatch.setattr(dispatcher, "transform", lambda **kwargs: pytest.fail("native producer must not run"))
    with selected["phase3_receipt"].open("a") as stream:
        stream.write("\n")
    receipt = helper.CONTINUATION / "phase.json"
    with pytest.raises(ValueError, match="receipt identity changed"):
        helper.phase(receipt, helper.CONTINUATION / "canary.json", "synthetic-phase", prerequisite_inputs=selected)
    assert not receipt.exists()


def test_wrong_root_prerequisite_refuses_before_cache_credentials_or_launch(helper, prerequisite_records, monkeypatch):
    """A copied old-checkout success remains inadmissible even with its actual digest."""
    selected, _, _ = prerequisite_records
    path = selected["phase3_receipt"]
    body = json.loads(path.read_text())
    body["root"] = str(helper.ROOT.parent / "old-W1")
    path.write_text(json.dumps(body))
    selected["phase3_sha256"] = helper.digest(path)
    monkeypatch.setattr(sys, "argv", _phase_arguments(helper, selected))
    monkeypatch.setattr(helper, "bindings", lambda: {})
    monkeypatch.setattr(helper, "preserve_cache", lambda label: pytest.fail("cache preservation must not start"))
    monkeypatch.setattr(helper, "load_authorized_keys", lambda path: pytest.fail("credential source must not open"))
    monkeypatch.setattr(helper.subprocess, "run", lambda *args, **kwargs: pytest.fail("launcher must not start"))
    with pytest.raises(ValueError, match="canonical source admissions"):
        helper.main()


def test_selected_phase_records_exact_prerequisites_with_fixed_native_scope(helper, prerequisite_records, monkeypatch):
    """An intercepted native dispatch retains the selected receipt pair in its producer proof."""
    import kg_microbe.transform as dispatcher

    selected, plan, _ = prerequisite_records
    monkeypatch.setattr(helper, "bindings", lambda: {})
    monkeypatch.setattr(helper, "validate_canary", lambda path: {"path": str(path), "sha256": "c" * 64})
    preserved = {"manifest": "synthetic-preservation.json", "sha256": "d" * 64, "preserved_files": 2}
    monkeypatch.setattr(helper, "verify_preserved_cache", lambda *args: dict(preserved))
    called = []

    def dispatch(**kwargs):
        """Emit only a tiny synthetic result, never invoke a producer or network service."""
        called.append(kwargs)
        directory = helper.ROOT / "data/transformed/lpsn_api"
        directory.mkdir(parents=True)
        (directory / "nodes.tsv").write_text("id\tcategory\nLPSN:1\tbiolink:OrganismTaxon\n")
        (directory / "edges.tsv").write_text("subject\tpredicate\tobject\nLPSN:1\tbiolink:subclass_of\tNCBITaxon:1\n")
        (directory / "source_finalization.json").write_text('{"synthetic_fixture_only":true}\n')

    monkeypatch.setattr(dispatcher, "transform", dispatch)
    receipt = helper.CONTINUATION / "phase.json"
    assert (
        helper.phase(receipt, helper.CONTINUATION / "canary.json", "synthetic-phase", prerequisite_inputs=selected) == 0
    )
    assert called == [
        {
            "input_dir": helper.ROOT / "data/raw",
            "output_dir": helper.ROOT / "data/transformed",
            "sources": ["lpsn_api"],
            "show_status": False,
        }
    ]
    proof = json.loads(receipt.read_text())
    assert proof["prerequisites"] == {**{key: str(value) for key, value in selected.items()}, "plan": plan}
    assert proof["full_source_admission_pending"] is True
    assert proof["preserved_cache_before"] == proof["preserved_cache_after"] == preserved
