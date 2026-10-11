"""Native Rhea acquisition is explicit, pinned, coherent and non-destructive."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.rhea_mappings import stage_snapshot as module
from tests.test_rhea_native_inputs import _inputs


def _staging_inputs(tmp_path):
    """Use the same immutable tiny native family as the real input-reader controls."""
    producer, policy_path, policy = _inputs(tmp_path / "origin")
    return producer.input_base_dir / "rhea", tmp_path / "destination", policy_path, policy


def test_native_pair_is_published_together_after_pin_and_semantic_validation(tmp_path):
    """A complete directory and acquisition-only receipt appear without a transform or release claim."""
    source, raw, policy_path, policy = _staging_inputs(tmp_path)
    receipt = module.stage_snapshot(source, raw, policy_path=policy_path)
    assert receipt["disposition"] == "staged"
    assert receipt["source_directory"] == str(source.resolve())
    assert receipt["acquisition_method"] == "explicit_local_copy"
    assert receipt["families"] == 1 and receipt["active_reactions"] == 4
    assert receipt["production_transform_run"] is False and receipt["release_ready"] is False
    assert receipt["policy_sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest()
    for name in policy["files"]:
        assert (source / name).read_bytes() == (raw / "rhea" / name).read_bytes()
    assert json.loads((raw / "rhea/snapshot_receipt.json").read_text()) == receipt
    assert list(raw.glob(".rhea-stage-*")) == []


def test_matching_existing_pair_is_read_only_even_if_source_is_missing(tmp_path):
    """Idempotence verifies destination bytes and never rewrites accepted inputs or receipts."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    module.stage_snapshot(source, raw, policy_path=policy_path)
    identities = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in (raw / "rhea").iterdir()}
    result = module.stage_snapshot(tmp_path / "absent", raw, policy_path=policy_path)
    assert result["disposition"] == "already_matching"
    assert result["source_directory"] is None
    assert result["acquisition_method"] == "verified_existing"
    assert identities == {
        p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in (raw / "rhea").iterdir()
    }


@pytest.mark.parametrize("filename", ["rhea-directions.tsv", "rhea.rdf.gz"])
@pytest.mark.parametrize("kind", ["absent", "short", "wrong", "long"])
def test_bad_or_missing_payload_never_publishes_or_repins(tmp_path, filename, kind):
    """Neither half-pairs nor merely same-sized bytes can become an admitted native snapshot."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    path = source / filename
    original_policy = policy_path.read_bytes()
    data = path.read_bytes()
    if kind == "absent":
        path.unlink()
    else:
        path.write_bytes({"short": data[:-1], "wrong": b"?" + data[1:], "long": data + b"!"}[kind])
    with pytest.raises((ValueError, FileNotFoundError)):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert not (raw / "rhea").exists()
    assert list(raw.glob(".rhea-stage-*")) == []
    assert policy_path.read_bytes() == original_policy


def test_valid_hashes_do_not_admit_semantically_inconsistent_pair(tmp_path):
    """Direction-role inversion must fail even with a deliberately matching fixture pin."""
    source, raw, policy_path, policy = _staging_inputs(tmp_path)
    table = source / "rhea-directions.tsv"
    value = table.read_bytes().replace(b"100\t101\t102\t103", b"100\t102\t101\t103")
    table.write_bytes(value)
    policy["files"][table.name] = {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match="RDF evidence disagrees"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert not (raw / "rhea").exists()


def test_existing_partial_or_different_destination_is_preserved(tmp_path):
    """Staging is not permission to replace, complete or delete an existing raw generation."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    existing = raw / "rhea"
    existing.mkdir(parents=True)
    (existing / "rhea-directions.tsv").write_text("existing data")
    (existing / "unrelated.txt").write_text("keep")
    before = {p.name: p.read_bytes() for p in existing.iterdir()}
    with pytest.raises(ValueError, match="pin mismatch"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert before == {p.name: p.read_bytes() for p in existing.iterdir()}


def test_symlink_destination_is_not_replaced_or_followed(tmp_path):
    """An explicit input-root choice does not authorize writes through a preexisting destination link."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    raw.mkdir()
    (raw / "rhea").symlink_to(source, target_is_directory=True)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(ValueError, match="symlink"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert (raw / "rhea").is_symlink()
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


def test_existing_destination_with_linked_payloads_is_refused(tmp_path):
    """A real destination directory cannot certify payload links into another, mutable tree."""
    source, raw, policy_path, policy = _staging_inputs(tmp_path)
    (raw / "rhea").mkdir(parents=True)
    for name in policy["files"]:
        (raw / "rhea" / name).symlink_to(source / name)
    with pytest.raises(ValueError, match="symlink or non-regular"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert all((raw / "rhea" / name).is_symlink() for name in policy["files"])


def test_publication_failure_cleans_only_owned_empty_reservation(tmp_path, monkeypatch):
    """No canonical half-pair survives a rename failure; unrelated raw inputs remain untouched."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    raw.mkdir()
    keep = raw / "keep.txt"
    keep.write_text("keep")

    def fail(*args):
        """Simulate a filesystem refusing atomic directory publication."""
        raise OSError("fixture publication failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError, match="publication failure"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert not (raw / "rhea").exists()
    assert keep.read_text() == "keep"
    assert list(raw.glob(".rhea-stage-*")) == []


def test_foreign_file_in_reserved_destination_is_not_removed(tmp_path, monkeypatch):
    """Concurrent additions prevent publication and are never recursively cleaned away."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    original_replace = module.os.replace

    def foreign_write(stage, destination):
        """Model an unrelated writer reaching the reserved directory before rename."""
        (destination / "foreign.txt").write_text("preserve")
        return original_replace(stage, destination)

    monkeypatch.setattr(module.os, "replace", foreign_write)
    with pytest.raises(OSError):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert (raw / "rhea/foreign.txt").read_text() == "preserve"
    assert sorted(p.name for p in (raw / "rhea").iterdir()) == ["foreign.txt"]


def test_policy_drift_before_publication_is_refused(tmp_path, monkeypatch):
    """A stale in-memory pin cannot be published after the reviewed policy has changed."""
    source, raw, policy_path, _ = _staging_inputs(tmp_path)
    original = module._validate_pair

    def drift(directory, policy):
        """Change only the fixture policy after the actual semantic validation."""
        cohort = original(directory, policy)
        policy_path.write_bytes(policy_path.read_bytes() + b"\n")
        return cohort

    monkeypatch.setattr(module, "_validate_pair", drift)
    with pytest.raises(ValueError, match="policy changed"):
        module.stage_snapshot(source, raw, policy_path=policy_path)
    assert not (raw / "rhea").exists()


def test_rolling_downloads_are_quarantined_not_transform_inputs():
    """Generic URL-only downloads cannot overwrite the hash-admitted native pair."""
    with (Path(__file__).parents[1] / "download.yaml").open() as stream:
        selected = [row for row in yaml.safe_load(stream) if row.get("tag") == "rhea"]
    assert {row["local_name"] for row in selected} == {
        "rhea_download/rhea-directions.tsv",
        "rhea_download/rhea.rdf.gz",
    }
