"""Offline replay, scope and finite-policy controls for MediaDive endpoint generations."""

import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes
from tests.mediadive_generation_fixtures import seal_fixture_raw

FIXTURE = Path(__file__).parent / "resources/mediadive_retry_20261105.json"


@pytest.fixture
def raw(tmp_path):
    """Copy immutable synthetic records without manufacturing extra native assertions."""
    fixture = json.loads(FIXTURE.read_text())
    root = tmp_path / "raw"
    (root / "mediadive").mkdir(parents=True)
    details = fixture["order_sensitive_details"]
    (root / "mediadive.json").write_text(json.dumps({"data": [{"id": 1}, {"id": 2}], "count": 3338}))
    documents = {
        "media_detailed.json": details,
        "media_strains.json": {"1": fixture["strains"]["data"]},
        "solutions.json": {"10": details["1"]["solutions"][0]},
        "compounds.json": {"4": details["1"]["solutions"][0]["recipe"][0]},
    }
    for name, value in documents.items():
        (root / "mediadive" / name).write_text(json.dumps(value, indent=2))
    return root


def event(status=200, *, kind="medium-strains", body=True):
    """Build an explicit transport envelope for strict classifier unit controls."""
    url = outcomes.BASE_URL + kind + "/1"
    return {
        "url": url,
        "request": {"url": url, "method": "GET"},
        "transport_error": None,
        "response": {"url": url, "status": status, "headers": {"Content-Type": "application/json"}} if body else None,
    }


@pytest.mark.parametrize(
    "name,status,state",
    [("strains", 200, "nonempty"), ("empty", 200, "explicit_empty"), ("unknown", 404, "unknown_unavailable")],
)
def test_source_success_empty_and_unknown_remain_distinct(name, status, state):
    """The same absence of native strain keys cannot erase the underlying source state."""
    payload = json.loads(FIXTURE.read_text())[name]
    result = outcomes.classify_observation(event(status), outcomes.canonical(payload))
    assert result["state"] == state
    if state == "unknown_unavailable":
        assert result["data"] is None
    if state == "explicit_empty":
        assert result["data"] == []


@pytest.mark.parametrize("name", ["invalid", "contradictory_empty", "null_id", "wrong_count", "duplicate_keys"])
def test_malformed_success_never_becomes_explicit_empty(name):
    """Contradictory envelopes, wrong IDs/counts and duplicate fields remain malformed."""
    payload = json.loads(FIXTURE.read_text())[name]
    body = payload.encode() if isinstance(payload, str) else outcomes.canonical(payload)
    assert outcomes.classify_observation(event(), body)["state"] == "malformed"


def test_transport_and_missing_evidence_are_separate():
    """A transport exception is recorded; an uncompleted request has no asserted result."""
    value = event(body=False)
    assert outcomes.classify_observation(value, None)["state"] == "missing_evidence"
    value["transport_error"] = {"type": "ConnectionError", "message": "synthetic"}
    assert outcomes.classify_observation(value, None)["state"] == "transport_error"


def test_redirect_and_wrong_medium_are_malformed():
    """Neither an endpoint redirect nor a different medium can satisfy the requested identity."""
    fixture = json.loads(FIXTURE.read_text())
    value = event()
    value["response"]["url"] += "-different"
    assert outcomes.classify_observation(value, outcomes.canonical(fixture["strains"]))["state"] == "malformed"
    payload = fixture["detail"]
    payload["data"]["medium"]["id"] = 2
    assert outcomes.classify_observation(event(kind="medium"), outcomes.canonical(payload))["state"] == "malformed"


def test_complete_generation_replays_without_changing_original_inputs(raw):
    """The actual reader verifies copied fixture bytes, exact counts and detached contracts."""
    before = {path: outcomes.identity(path) for path in raw.rglob("*.json")}
    view = seal_fixture_raw(raw)
    reloaded = outcomes.load_generation(raw / "mediadive")
    assert reloaded.qualification["admissible"]
    assert reloaded.qualification["association_coverage_complete"]
    assert reloaded.qualification["expected_endpoint_count"] == 4
    assert reloaded.qualification["state_counts"]["nonempty"] == 3
    assert reloaded.qualification["state_counts"]["explicit_empty"] == 1
    assert set(reloaded.qualification["state_counts"]) == outcomes.STATES
    assert {path: outcomes.identity(path) for path in before} == before
    for name in outcomes.NATIVE_FILES.values():
        if name != "catalogue.json":
            assert (view.generation_dir / name).read_bytes() == (raw / "mediadive" / name).read_bytes()
    contract = view.contract()
    contract["qualification"]["admissible"] = False
    assert view.contract()["qualification"]["admissible"]


def test_finite_curated_unknown_policy_qualifies_without_complete_associations(raw, monkeypatch):
    """A reviewed unknown omits assertions and never increments explicit-empty coverage."""
    view = seal_fixture_raw(raw, unknown_ids={2})
    monkeypatch.setattr(outcomes, "CURATED_UNKNOWN_POLICY", view.curated_policy_path)
    current = outcomes.load_generation(raw / "mediadive")
    assert current.qualification["admissible"] and current.qualification["endpoint_accounting_complete"]
    assert not current.qualification["association_coverage_complete"]
    assert current.qualification["state_counts"]["unknown_unavailable"] == 1
    assert current.qualification["state_counts"]["explicit_empty"] == 0
    assert current.payloads["mediadive_media_strains"] == {"1": json.loads(FIXTURE.read_text())["strains"]["data"]}
    policy = outcomes.strict_json(view.curated_policy_path.read_bytes())
    policy["cases"] = {"*": next(iter(policy["cases"].values()))}
    view.curated_policy_path.write_bytes(outcomes.canonical(policy))
    with pytest.raises(outcomes.EndpointEvidenceError, match="current curated policy"):
        outcomes.load_generation(raw / "mediadive")


def test_self_restamped_native_output_cannot_replace_source_evidence(raw):
    """Consistent attacker-controlled manifests still cannot change the actual consumed assertions."""
    view = seal_fixture_raw(raw)
    directory = view.generation_dir
    changed = directory / "media_strains.json"
    changed.write_text("{}")
    manifest = outcomes.strict_json((directory / "manifest.json").read_bytes())
    manifest["files"][changed.name] = outcomes.identity(changed)
    (directory / "manifest.json").write_bytes(outcomes.canonical(manifest))
    checksum = outcomes.identity(directory / "manifest.json")["sha256"]
    (directory / "seal.json").write_bytes(outcomes.canonical({"schema_version": 1, "manifest_sha256": checksum}))
    (raw / "mediadive/current.json").write_bytes(
        outcomes.canonical({"schema_version": 1, "generation_id": "fixture", "manifest_sha256": checksum})
    )
    with pytest.raises(outcomes.EndpointEvidenceError, match="Native output differs"):
        outcomes.load_generation(raw / "mediadive")


def test_altered_body_missing_member_or_symlink_refuses_admission(raw):
    """Generation membership and raw response bytes are mandatory replay evidence."""
    view = seal_fixture_raw(raw)
    body = next((view.generation_dir / "bodies").iterdir())
    body.write_bytes(b"altered")
    with pytest.raises(outcomes.EndpointEvidenceError, match="member changed"):
        outcomes.load_generation(raw / "mediadive")


def test_zero_catalogue_is_explicit_and_counted(tmp_path):
    """An honest synthetic zero-row source has zero observations rather than invented empty endpoints."""
    raw = tmp_path / "raw"
    (raw / "mediadive").mkdir(parents=True)
    (raw / "mediadive.json").write_text('{"data":[]}')
    for name in outcomes.NATIVE_FILES.values():
        if name != "catalogue.json":
            (raw / "mediadive" / name).write_text("{}")
    view = seal_fixture_raw(raw)
    assert view.qualification["catalogue_count"] == view.qualification["expected_endpoint_count"] == 0
    assert view.endpoint_records == {}
    assert sum(view.qualification["state_counts"].values()) == 0


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_restamped_native_numeric_type_change_is_rejected(raw, replacement):
    """#1765 prevents Python numeric equality from substituting a different native JSON type."""
    view = seal_fixture_raw(raw)
    directory = view.generation_dir
    target = directory / "media_strains.json"
    value = outcomes.strict_json(target.read_bytes())
    value["1"][0]["growth"] = replacement
    target.write_bytes(outcomes.canonical(value))
    manifest = outcomes.strict_json((directory / "manifest.json").read_bytes())
    manifest["files"][target.name] = outcomes.identity(target)
    (directory / "manifest.json").write_bytes(outcomes.canonical(manifest))
    checksum = outcomes.identity(directory / "manifest.json")["sha256"]
    (directory / "seal.json").write_bytes(outcomes.canonical({"schema_version": 1, "manifest_sha256": checksum}))
    (raw / "mediadive/current.json").write_bytes(
        outcomes.canonical({"schema_version": 1, "generation_id": "fixture", "manifest_sha256": checksum})
    )
    with pytest.raises(outcomes.EndpointEvidenceError, match="Native output differs"):
        outcomes.load_generation(raw / "mediadive")


def test_float_http_status_cannot_declare_unknown():
    """#1765 applies native integer status checks before the unavailable branch too."""
    value = event(404.0)
    payload = json.loads(FIXTURE.read_text())["unknown"]
    assert outcomes.classify_observation(value, outcomes.canonical(payload))["state"] == "malformed"


def test_repeated_strain_entity_observations_survive_generation_and_fresh_replay(raw):
    """#1770 preserves exact duplicate and opposite-polarity rows without inventing strain IDs."""
    fixture = json.loads((FIXTURE.parent / "mediadive_repeated_strain_observations.json").read_text())
    rows = fixture["data"]
    strains_path = raw / "mediadive/media_strains.json"
    strains_path.write_text(json.dumps({"1": rows}, indent=2))
    original_bytes = strains_path.read_bytes()
    sealed = seal_fixture_raw(raw)
    replayed = outcomes.load_generation(raw / "mediadive")
    url = outcomes.BASE_URL + "medium-strains/1"
    assert replayed.endpoint_states[url] == "nonempty"
    assert replayed.qualification["association_coverage_complete"]
    assert [row["id"] for row in replayed.payloads["mediadive_media_strains"]["1"]] == [7, 7, 7]
    assert [row["growth"] for row in replayed.payloads["mediadive_media_strains"]["1"]] == [1, 1, 0]
    assert outcomes.canonical(replayed.payloads["mediadive_media_strains"]["1"]) == outcomes.canonical(rows)
    assert strains_path.read_bytes() == original_bytes
    assert (sealed.generation_dir / "media_strains.json").read_bytes() == original_bytes
    cached = outcomes.cache_records(sealed.generation_dir / outcomes.CACHE_FILE)[url]
    body = outcomes.strict_json(cached["body"])
    assert body["count"] == 3
    assert outcomes.canonical(body["data"]) == outcomes.canonical(rows)
    assert cached["body_sha256"] == replayed.endpoint_records[url]["body_sha256"]


def test_actual_official_endpoint_description_is_distinct_from_wire_message():
    """The exact retained endpoint record documents the same error using its own official wording."""
    path = FIXTURE.parent / "mediadive_medium_strains_official_endpoint.js"
    body = path.read_bytes()
    origin = json.loads(path.with_suffix(".origin.json").read_text())
    assert outcomes.sha256(body) == origin["sha256"]
    assert outcomes.UNKNOWN_MESSAGE.encode() not in body
    proof = outcomes.validate_official_error_contract(body)
    assert proof["record_sha256"] == origin["sha256"]
    assert proof["endpoint"] == "/medium-strains/:id"
    assert proof["error"] == "DataNotFound"
    assert proof["description"] == "<p>The medium could not be found or has no calculated composition</p>"


@pytest.mark.parametrize(
    "mutation",
    [
        "other_endpoint",
        "missing_error",
        "missing_phrase",
        "changed_meaning",
        "other_endpoint_has_correct_phrase",
        "example_has_correct_error",
        "other_endpoint_example_has_target_record",
    ],
)
def test_official_error_contract_is_bound_to_the_requested_endpoint(mutation):
    """Unrelated documentation text cannot supply or override the selected endpoint's error meaning."""
    original = (FIXTURE.parent / "mediadive_medium_strains_official_endpoint.js").read_bytes()
    if mutation == "other_endpoint":
        changed = original.replace(b"/medium-strains/:id", b"/different-endpoint/:id")
    elif mutation == "missing_error":
        changed = original.replace(b"error:{fields:", b"unrelated:{fields:")
    elif mutation == "missing_phrase":
        changed = original.replace(b" or has no calculated composition", b"")
    elif mutation == "example_has_correct_error":
        fields = outcomes._documentation_fields(original.decode().strip())
        error = b"error:" + fields["error"].encode()
        changed = original.replace(error, b"unrelated:{}")
        changed = changed.replace(b"content:`[", b"content:`" + error + b"[", 1)
    elif mutation == "other_endpoint_example_has_target_record":
        # Embed the complete matching record as example text in a different record.
        quoted = original.replace(b"`", b"\\`")
        changed = b'{type:"get",url:"/other",name:"Other",example:`' + quoted + b"`}"
    else:
        changed = original.replace(
            b"The medium could not be found or has no calculated composition", b"The medium has no associated strains"
        )
        if mutation == "other_endpoint_has_correct_phrase":
            changed = (
                b"[" + changed + b"," + original.replace(b"/medium-strains/:id", b"/different-endpoint/:id") + b"]"
            )
    with pytest.raises(outcomes.EndpointEvidenceError):
        outcomes.validate_official_error_contract(changed)
