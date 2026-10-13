"""Rhea consumes explicit immutable direction/RDF snapshots, not ambient caches."""

import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.rhea_mappings.native_inputs import (
    REQUIRED_INPUTS,
    load_pinned_inputs,
    read_release_policy,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_consumed_inputs

FIXTURE = Path(__file__).parent / "resources" / "rhea" / "native-small.rdf"


class PinnedRheaFixture(Transform):
    """Exercise the real read/finalization contract with a small isolated native input."""

    REQUIRED_CONSUMED_INPUTS = REQUIRED_INPUTS


def _inputs(tmp_path):
    """Stage an exact small native family and its two-file hash policy."""
    transform = PinnedRheaFixture("rhea_mappings", tmp_path / "raw", tmp_path / "transformed")
    raw = transform.input_base_dir / "rhea"
    raw.mkdir(parents=True)
    directions = b"RHEA_ID_MASTER\tRHEA_ID_LR\tRHEA_ID_RL\tRHEA_ID_BI\n100\t101\t102\t103\n"
    payloads = {
        "rhea-directions.tsv": directions,
        "rhea.rdf.gz": gzip.compress(FIXTURE.read_bytes(), mtime=0),
    }
    for name, value in payloads.items():
        (raw / name).write_bytes(value)
    policy = {
        "schema_version": 2,
        "snapshot_id": "hermetic-family",
        "archive": {
            "url": "https://example.org/rhea/fixture.tar.bz2",
            "members": {
                "rhea-directions.tsv": "fixture/tsv/rhea-directions.tsv",
                "rhea.rdf.gz": "fixture/rdf/rhea.rdf.gz",
            },
        },
        "files": {
            name: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)} for name, value in payloads.items()
        },
    }
    policy_path = tmp_path / "rhea_release.json"
    policy_path.write_text(json.dumps(policy))
    return transform, policy_path, policy


def test_pinned_rdf_and_directions_are_really_consumed(tmp_path):
    """Full parser snapshots and their exact policy are registered by the producer contract."""
    transform, policy_path, expected = _inputs(tmp_path)
    policy, families, index, cohort = load_pinned_inputs(transform, policy_path=policy_path)
    assert policy == expected
    assert families[0].master == "RHEA:100"
    assert set(index.reactions) == {identifier for identifier, _ in families[0].members}
    assert cohort == {
        "families": 1,
        "members": 4,
        "family_status_counts": {"Approved": 1, "Preliminary": 0},
        "obsolete_ids": (),
    }
    snapshots = transform.consumed_input_snapshots
    assert set(snapshots) == set(REQUIRED_INPUTS)
    for role, name in (("rhea_directions", "rhea-directions.tsv"), ("rhea_rdf", "rhea.rdf.gz")):
        assert snapshots[role]["sha256"] == expected["files"][name]["sha256"]
    verify_consumed_inputs(transform)


@pytest.mark.parametrize("name", ["rhea-directions.tsv", "rhea.rdf.gz"])
def test_mismatched_pin_is_rejected_before_source_output(tmp_path, name):
    """Appending even semantically harmless bytes does not pass an exact reviewed pin."""
    transform, policy_path, _ = _inputs(tmp_path)
    source = transform.input_base_dir / "rhea" / name
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="does not match pinned snapshot"):
        load_pinned_inputs(transform, policy_path=policy_path)
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
    with pytest.raises(SourceFinalizationRequired):
        verify_consumed_inputs(transform)


def test_hashes_do_not_waive_inconsistent_native_directions(tmp_path):
    """A coherently hashed but swapped direction table still fails the RDF role checks."""
    transform, policy_path, policy = _inputs(tmp_path)
    source = transform.input_base_dir / "rhea" / "rhea-directions.tsv"
    value = source.read_bytes().replace(b"100\t101\t102\t103", b"100\t102\t101\t103")
    source.write_bytes(value)
    policy["files"][source.name] = {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match="RDF evidence disagrees"):
        load_pinned_inputs(transform, policy_path=policy_path)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize("role", ["rhea_release_manifest", "rhea_directions", "rhea_rdf"])
def test_post_read_input_drift_cannot_be_finalized(tmp_path, role):
    """A successful parse does not certify later policy or payload changes."""
    transform, policy_path, _ = _inputs(tmp_path)
    load_pinned_inputs(transform, policy_path=policy_path)
    source = Path(transform.consumed_input_snapshots[role]["path"])
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize("change", ["missing_file", "extra_file", "bad_hash", "bad_size", "empty_snapshot"])
def test_release_contract_rejects_incomplete_or_malformed_pins(tmp_path, change):
    """No alternate local paths or unpinned payloads can enter the finite input selection."""
    _, _, policy = _inputs(tmp_path)
    if change == "missing_file":
        del policy["files"]["rhea.rdf.gz"]
    elif change == "extra_file":
        policy["files"]["../ambient.rdf.gz"] = policy["files"]["rhea.rdf.gz"]
    elif change == "bad_hash":
        policy["files"]["rhea.rdf.gz"]["sha256"] = "not-a-digest"
    elif change == "bad_size":
        policy["files"]["rhea.rdf.gz"]["bytes"] = True
    else:
        policy["snapshot_id"] = " "
    with pytest.raises(ValueError):
        read_release_policy(io.StringIO(json.dumps(policy)))


@pytest.mark.parametrize(
    "change",
    ["version_one", "no_archive", "http_url", "extra_key", "missing_member", "absolute", "traversal", "wrong_name"],
)
def test_release_contract_requires_its_archive_and_safe_member_paths(tmp_path, change):
    """Version 2 names the archived release; a member path can never point outside it or rename a payload."""
    _, _, policy = _inputs(tmp_path)
    archive = policy["archive"]
    if change == "version_one":
        policy["schema_version"] = 1
    elif change == "no_archive":
        del policy["archive"]
    elif change == "http_url":
        archive["url"] = archive["url"].replace("https://", "http://")
    elif change == "extra_key":
        archive["sha256"] = "0" * 64
    elif change == "missing_member":
        del archive["members"]["rhea.rdf.gz"]
    elif change == "absolute":
        archive["members"]["rhea.rdf.gz"] = "/fixture/rdf/rhea.rdf.gz"
    elif change == "traversal":
        archive["members"]["rhea.rdf.gz"] = "fixture/../rdf/rhea.rdf.gz"
    else:
        archive["members"]["rhea.rdf.gz"] = "fixture/rdf/rhea.rdf"
    with pytest.raises(ValueError, match="Unsupported Rhea release|must name its archive"):
        read_release_policy(io.StringIO(json.dumps(policy)))


def test_boolean_schema_version_is_not_a_version(tmp_path):
    """Python bool/int equality must not make an invalid manifest appear versioned."""
    _, _, policy = _inputs(tmp_path)
    policy["schema_version"] = True
    with pytest.raises(ValueError, match="Unsupported Rhea release"):
        read_release_policy(io.StringIO(json.dumps(policy)))


@pytest.mark.parametrize("duplicate", ['"schema_version":999,', '"schema_version":2,'])
def test_duplicate_contract_keys_are_rejected_even_when_last_value_is_valid(tmp_path, duplicate):
    """A parser must not silently discard an earlier conflicting pin-contract value."""
    _, _, policy = _inputs(tmp_path)
    document = "{" + duplicate + json.dumps(policy)[1:]
    with pytest.raises(ValueError, match="Duplicate Rhea release contract key"):
        read_release_policy(io.StringIO(document))


def _replace_native(transform, policy_path, policy, xml):
    """Pin a deliberate hermetic source variation without mutating the immutable fixture."""
    source = transform.input_base_dir / "rhea" / "rhea.rdf.gz"
    payload = gzip.compress(xml, mtime=0)
    source.write_bytes(payload)
    policy["files"][source.name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    policy_path.write_text(json.dumps(policy))


def test_preliminary_families_keep_their_source_status(tmp_path):
    """A released preliminary family is not silently discarded or promoted to approved."""
    transform, policy_path, policy = _inputs(tmp_path)
    xml = FIXTURE.read_bytes().replace(b"/Approved", b"/Preliminary")
    _replace_native(transform, policy_path, policy, xml)
    _, families, native, cohort = load_pinned_inputs(transform, policy_path=policy_path)
    assert cohort["family_status_counts"] == {"Approved": 0, "Preliminary": 1}
    for identifier, _ in families[0].members:
        assert native.reactions[identifier]["http://rdf.rhea-db.org/status"] == ("http://rdf.rhea-db.org/Preliminary",)


@pytest.mark.parametrize("status", ["Approved", "Preliminary", "Unknown", "Obsolete"])
def test_whole_native_cohort_is_reconciled_not_only_listed_families(tmp_path, status):
    """Extra active/unknown records fail; explicit obsolete records receive an exact audit disposition."""
    transform, policy_path, policy = _inputs(tmp_path)
    record = (
        '<rdf:Description rdf:about="http://rdf.rhea-db.org/9999">'
        f'<rh:status rdf:resource="http://rdf.rhea-db.org/{status}"/>'
        "</rdf:Description>"
    ).encode()
    xml = FIXTURE.read_bytes().replace(b"</rdf:RDF>", record + b"</rdf:RDF>")
    _replace_native(transform, policy_path, policy, xml)
    if status == "Obsolete":
        _, _, _, cohort = load_pinned_inputs(transform, policy_path=policy_path)
        assert cohort["obsolete_ids"] == ("RHEA:9999",)
        verify_consumed_inputs(transform)
    else:
        with pytest.raises(ValueError):
            load_pinned_inputs(transform, policy_path=policy_path)
        with pytest.raises(SourceFinalizationRequired, match="read failed"):
            verify_consumed_inputs(transform)
