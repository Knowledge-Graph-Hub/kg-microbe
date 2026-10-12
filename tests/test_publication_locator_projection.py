"""Publish portable evidence locators without changing reviewed scientific payloads."""

import ast
import copy
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "tests/resources/publication_locator_projection.json"
HASH_ANCHOR_FILES = (
    "kg_microbe/transform_utils/mediadive/recipe_identity.py",
    "mappings/mediadive_recipe_identity_policy.json",
    "tests/resources/mediadive_recipe_identity/fixture-origins.json",
    "tests/resources/native_ro_retention/origin.json",
    "tests/test_native_ro_ordering_retention.py",
    "tests/resources/participation_disposition/manifest.json",
)
PROJECTED_POLICY_SHA = "9f590b55a9183b5dfec6cc9082c6193db79b2fd7b6bd8e938a5c4a35126e059f"
HISTORICAL_SCOPE = (
    "Reviewed historical excerpts; two go_reference_context authority locators are publication projections, "
    "not byte-identical original field strings. Original and published hashes are in "
    "../publication_locator_projection.json. Upstream byte identities and native coordinates remain in properties.json."
)
LOCATOR_ROOTS = {
    "source-repository": (
        "Historical original source repository root; an evidence locator, not the active runtime root."
    ),
    "candidate-worktree": (
        "Historical separately reviewed candidate worktree root; an evidence locator, not the active runtime root."
    ),
    "review-evidence": (
        "Historical local review-evidence root; content hashes identify evidence, not public availability."
    ),
}
# Original artifact, complete scientific remainder, and exact finite edit contract.
ANCHORS = {
    "mappings/kgxval_reference_dispositions_v1.json": (
        "b17ffbe83bcfcd1f4d63da24c7619a7f166feba60dc2b8bd44dba673733be3c4",
        "a937b92890a2e50467887ca25591a2066a843dc9114224f0a119289629ccf1d8",
        "5ce5813b4509ced6c922d7a46ec9b0f9587d791a9cca43c20fd4321019348a3c",
    ),
    "mappings/mediadive_recipe_identity_evidence.json": (
        "0a01869d5d46cacbf67ecdcc33f3a44d580f914ac6dd58f584276aac5d602da9",
        "cd740cb9b06e871da782978d85416bfa66a962fc7482fe307646cb726fb9924c",
        "f841d561861508a301b148d04ffb6b8ad93b211ef4633d6f1e957d3b8fb40bb7",
    ),
    "tests/resources/gold_selected_taxon_aliases/native_evidence.json": (
        "069fd57c7ef9367cfdbff8f4ec6f287026d521058eb7950f15288388a0115a6f",
        "8cd06cb38da8a9976f20c39998e3e3490414b0c6c70e233dcb808f8134cc85e0",
        "43ae73ffd8dbb2ec15875e87d8f661f574e9bd2343d357aab1d91751ea318909",
    ),
    "tests/resources/gold_selected_taxon_aliases/producer_contexts.json": (
        "2b8e81d06669e2ee2586abf25590f9cd99cfe5378afc759eb7acd933d2ef53ed",
        "7f10c5f0d143a9f7828549df9804d51bc8db29c691c95803502546b85298cce9",
        "5be42687f3dd1e65633650c5f0c7058989383e7208fc87709980f60886aa8566",
    ),
    "tests/resources/gold_taxonomy/microbedecoder_native_context.json": (
        "84a0e948fb5c48f927428c1f5e850f26cbdb98215220c59c10614d05ea9ede3c",
        "5199827eb09b8d1588d63e12ad3ed9eaa8729eb2d7a5e23307af55babf2756e3",
        "1415703c1fd232d0deb669f9acc733bcbb5b652a1c14e71a5daa7bea964f2ea3",
    ),
    "tests/resources/gold_taxonomy/native_contexts.json": (
        "f3af2d4857fc4d55a3e79236916517908187e9f250d72545bb18231b129950be",
        "9299b3524057f0b1dbda582a559cc3d037d8f2a5ff39fb84c680b903e5a09bcb",
        "2c6b588c4f121ff29d7f32d88e255c3986b71ac125c924ded7edc93c78db94a7",
    ),
    "tests/resources/native_ro_retention/temporal62_native.json": (
        "c19f4d0348e16b73511a81feed3f647bc0bfbda20cb6a5a5253375ef1d2daf27",
        "f016c9432894f0c6a19601820513948a7552e62afb924dad54dbfd98b3d82e8e",
        "10ac2e9a4bd1b45dd4a47774899464d470210354d6c276fdc9af127a202633e1",
    ),
    "tests/resources/participation_disposition/historical_claims.json": (
        "dfffd127b651b44a12537c20d2f33c3b8749206bfc8364e2084fc4933e03ea2b",
        "32d0e5d9e1af947d751d68584a52a317f39960ec841e392bf7a97fed0e91a99a",
        "51f2292420405f7e827807595843c722326c4d1d6751b60891b83bac3e753de0",
    ),
}


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


def _read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=_unique)


def _at(value, parts):
    for part in parts:
        value = value[part]
    return value


def _assignment(path, name):
    values = [
        ast.literal_eval(node.value)
        for node in ast.parse(path.read_bytes()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    assert len(values) == 1
    return values[0]


def assert_hash_anchors(root):
    """Only publication-container anchors change; scientific authority digests keep their identities."""
    manifest = _read(root / MANIFEST)
    published = {name: record["published_file_sha256"] for name, record in manifest["files"].items()}
    evidence = published["mappings/mediadive_recipe_identity_evidence.json"]
    policy_path = root / HASH_ANCHOR_FILES[1]
    assert _digest(policy_path.read_bytes()) == PROJECTED_POLICY_SHA
    assert _read(policy_path)["evidence_sha256"] == evidence
    assert _assignment(root / HASH_ANCHOR_FILES[0], "EVIDENCE_SHA256") == evidence
    assert _assignment(root / HASH_ANCHOR_FILES[0], "POLICY_SHA256") == PROJECTED_POLICY_SHA
    origins = _read(root / HASH_ANCHOR_FILES[2])
    assert origins["evidence_sha256"] == evidence
    assert origins["policy_sha256"] == PROJECTED_POLICY_SHA
    temporal = published["tests/resources/native_ro_retention/temporal62_native.json"]
    assert _read(root / HASH_ANCHOR_FILES[3])["ordering_extension"]["science_fixture_sha256"] == temporal
    assert _assignment(root / HASH_ANCHOR_FILES[4], "SCIENCE_SHA") == temporal
    participation = _read(root / HASH_ANCHOR_FILES[5])
    assert participation["scope"] == HISTORICAL_SCOPE
    assert participation["sha256"] == {
        "historical_claims.json": published["tests/resources/participation_disposition/historical_claims.json"],
        "properties.json": "6de901f92f4e790a9b7358ad6b510e68bfd1067d8c186b037e520822110a962c",
        "quantifier_examples.json": "04ef2d6fab75ebb9eb2b1e06d0e19c330159b34188a36669ab5e83d85833d6c8",
    }


def assert_publication_contract(root):
    """Verify the finite public projection; private preimages are a separate local review proof."""
    assert b"/Users/" not in (root / MANIFEST).read_bytes()
    manifest = _read(root / MANIFEST)
    assert set(manifest) == {
        "version",
        "scope",
        "roots",
        "metadata_locator_edits",
        "historical_string_projections",
        "original_snapshots",
        "files",
    }
    assert type(manifest["version"]) is int and manifest["version"] == 1
    assert manifest["scope"] == "finite_publication_locator_projection_only_not_scientific_or_runtime_path_resolution"
    assert manifest["roots"] == LOCATOR_ROOTS
    assert (
        manifest["original_snapshots"]
        == "Retained separately in local review evidence; private absolute locators are not distributed."
    )
    assert manifest["metadata_locator_edits"] == 55
    assert manifest["historical_string_projections"] == 2
    assert set(manifest["files"]) == set(ANCHORS)
    counts = Counter()
    historical_count = 0
    for name, (original_sha, remainder_sha, edit_sha) in ANCHORS.items():
        record = manifest["files"][name]
        assert set(record) == {
            "original_file_sha256",
            "published_file_sha256",
            "scientific_remainder_canonical_sha256",
            "edits",
            "historical_string_projections",
        }
        assert record["original_file_sha256"] == original_sha
        assert record["scientific_remainder_canonical_sha256"] == remainder_sha
        contract = {key: record[key] for key in ("edits", "historical_string_projections")}
        assert _digest(_encoded(contract).encode()) == edit_sha
        path = root / name
        payload = path.read_bytes()
        assert _digest(payload) == record["published_file_sha256"]
        assert b"/Users/" not in payload and b"/home/" not in payload
        value = _read(path)
        remainder = copy.deepcopy(value)
        for edit in record["edits"]:
            kind, locator = edit["kind"], edit["published_locator"]
            counts[kind] += 1
            relative = PurePosixPath(locator)
            assert not relative.is_absolute() and ".." not in relative.parts
            assert str(relative) == locator and relative.parts[0] in manifest["roots"]
            original, masked = _at(value, edit["container"]), _at(remainder, edit["container"])
            if kind == "key":
                assert locator in original
                replacement = "<locator:" + edit["original_locator_sha256"] + ">"
                assert replacement not in masked
                updated = {replacement if key == locator else key: item for key, item in masked.items()}
                masked.clear()
                masked.update(updated)
            elif kind == "value":
                assert original[edit["field"]] == locator
                masked[edit["field"]] = "<publication-locator>"
            else:
                assert kind == "historical_json_string"
                context = json.loads(original[edit["field"]], object_pairs_hook=_unique)
                assert len(context) == 1 and context[0]["authority"] == locator
                context[0]["authority"] = "<publication-locator>"
                masked[edit["field"]] = _encoded(context)
        assert _digest(_encoded(remainder).encode()) == remainder_sha
        for projection in record["historical_string_projections"]:
            historical_count += 1
            assert projection["scope"] == "publication_locator_projection_not_byte_identical_original"
            row = value[projection["index"]]
            assert row["original_native_triple"] == projection["original_native_triple"]
            assert row["historical_merged_line"] == projection["historical_merged_line"]
            assert row["supplier"] == projection["supplier"] == "pato"
            fields = row["historical_nonempty_fields"]
            assert _digest(fields[projection["field"]].encode()) == projection["published_context_utf8_sha256"]
            assert _digest(_encoded(fields).encode()) == projection["published_nonempty_fields_canonical_sha256"]
            assert projection["original_context_utf8_sha256"] != projection["published_context_utf8_sha256"]
    assert counts == {"key": 23, "value": 32, "historical_json_string": 2}
    assert historical_count == 2


def test_publication_locators_preserve_complete_reviewed_scientific_remainder():
    """All eight artifacts remain native-evidence fixtures, not reidentified scientific objects."""
    assert_publication_contract(ROOT)


def test_publication_hash_anchors_bind_only_projected_containers():
    """Consumers and fixture receipts bind the new artifact bytes without changing native pins."""
    assert_hash_anchors(ROOT)


@pytest.fixture
def candidate(tmp_path):
    """Copy only the finite public evidence set, not private snapshots or production inputs."""
    for name in (*ANCHORS, MANIFEST, *HASH_ANCHOR_FILES):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def _save_resealed(root, name, value, manifest):
    payload = (_encoded(value) + "\n").encode()
    (root / name).write_bytes(payload)
    manifest["files"][name]["published_file_sha256"] = _digest(payload)
    (root / MANIFEST).write_text(_encoded(manifest))


@pytest.mark.parametrize(
    "damage",
    ["native_id", "native_source_hash", "amount", "citation", "xml", "annotation", "go_chain", "go_authority_hash"],
)
def test_restamped_publication_cannot_change_science(candidate, damage):
    """Refreshing the public container hash never authorizes scientific evidence drift."""
    names = tuple(ANCHORS)
    name = (
        names[2]
        if damage in {"native_id", "native_source_hash"}
        else names[1]
        if damage in {"amount", "citation"}
        else names[6]
        if damage in {"xml", "annotation"}
        else names[7]
    )
    value, manifest = _read(candidate / name), _read(candidate / MANIFEST)
    if damage == "native_id":
        value["native_records"][0]["id"] = "gold:Go9999999"
    elif damage == "native_source_hash":
        value["inputs"]["gold_nodes"]["sha256"] = "0" * 64
    elif damage in {"amount", "citation"}:
        value["historical_edges"][0]["value" if damage == "amount" else "publications"] = "999"
    elif damage == "xml":
        stanza = next(iter(value["stanzas"].values()))
        stanza["literal_xml"] += "<!--changed-->"
        stanza["sha256"] = _digest(stanza["literal_xml"].encode())
    elif damage == "annotation":
        value["native_axiom_annotations"]["uberon:genid83901"][0]["notes"][0]["value"] = "changed"
    else:
        row = value[8]["historical_nonempty_fields"]
        context = json.loads(row["go_reference_context"])
        context[0]["replacement_chain" if damage == "go_chain" else "authority_sha256"] = (
            ["GO:9999999"] if damage == "go_chain" else "0" * 64
        )
        row["go_reference_context"] = _encoded(context)
    _save_resealed(candidate, name, value, manifest)
    with pytest.raises(AssertionError):
        assert_publication_contract(candidate)


@pytest.mark.parametrize(
    "damage",
    [
        "extra_edit",
        "missing_projection",
        "original_hash",
        "false_original_bytes",
        "root_swap",
        "relative_suffix",
        "traversal",
        "absolute",
        "third_historical_projection",
        "wrong_historical_row",
        "wrong_count",
        "missing_anchor",
        "nonallowlisted_path",
        "duplicate_key",
    ],
)
def test_restamped_publication_cannot_expand_locator_projection(candidate, damage):
    """The exact approved edit surface and original-hash anchors are not self-restampable."""
    historical_damage = {
        "missing_projection",
        "false_original_bytes",
        "third_historical_projection",
        "wrong_historical_row",
    }
    name = tuple(ANCHORS)[-1] if damage in historical_damage else tuple(ANCHORS)[2]
    value, manifest = _read(candidate / name), _read(candidate / MANIFEST)
    record = manifest["files"][name]
    if damage == "extra_edit":
        record["edits"].append(copy.deepcopy(record["edits"][0]))
    elif damage == "missing_projection":
        record["historical_string_projections"].pop()
    elif damage == "original_hash":
        record["original_file_sha256"] = "0" * 64
    elif damage == "false_original_bytes":
        record["historical_string_projections"][0]["scope"] = "byte_identical_original"
    elif damage == "third_historical_projection":
        record["historical_string_projections"].append(copy.deepcopy(record["historical_string_projections"][0]))
    elif damage == "wrong_historical_row":
        record["historical_string_projections"][0]["index"] = 7
    elif damage == "wrong_count":
        manifest["metadata_locator_edits"] = 56
    elif damage == "missing_anchor":
        record.pop("original_file_sha256")
    elif damage == "nonallowlisted_path":
        value["invented_provenance"] = {"path": "source-repository/data/raw/new-source"}
    elif damage == "duplicate_key":
        payload = (candidate / name).read_bytes()
        repeated = b'{"inputs":{},' + payload[1:]
        (candidate / name).write_bytes(repeated)
        record["published_file_sha256"] = _digest(repeated)
        (candidate / MANIFEST).write_text(_encoded(manifest))
        with pytest.raises(AssertionError):
            assert_publication_contract(candidate)
        return
    else:
        edit = record["edits"][0]
        locator = edit["published_locator"]
        replacement = {
            "root_swap": "candidate-worktree/" + locator.split("/", 1)[1],
            "relative_suffix": locator + ".changed",
            "traversal": "source-repository/../private",
            "absolute": "/absolute/nonportable/locator",
        }[damage]
        _at(value, edit["container"])[edit["field"]] = replacement
        edit["published_locator"] = replacement
    _save_resealed(candidate, name, value, manifest)
    with pytest.raises(AssertionError):
        assert_publication_contract(candidate)


@pytest.mark.parametrize(
    "file_index,field",
    [
        (0, "EVIDENCE_SHA256"),
        (0, "POLICY_SHA256"),
        (1, "evidence_sha256"),
        (2, "evidence_sha256"),
        (2, "policy_sha256"),
        (3, "science_fixture_sha256"),
        (4, "SCIENCE_SHA"),
        (5, "historical_claims.json"),
        (5, "scope"),
    ],
)
def test_stale_or_unsupported_publication_anchor_is_rejected(candidate, file_index, field):
    """Every dependent anchor must agree, including the truthful historical-field scope."""
    path = candidate / HASH_ANCHOR_FILES[file_index]
    if path.suffix == ".py":
        before = _assignment(path, field)
        path.write_bytes(path.read_bytes().replace(before.encode(), b"0" * 64))
    else:
        value = _read(path)
        parent = (
            value["ordering_extension"] if file_index == 3 else value["sha256"] if field.endswith(".json") else value
        )
        parent[field] = "byte_identical_original" if field == "scope" else "0" * 64
        path.write_text(_encoded(value))
    with pytest.raises(AssertionError):
        assert_hash_anchors(candidate)
