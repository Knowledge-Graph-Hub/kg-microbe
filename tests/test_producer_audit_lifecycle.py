"""Quarantine evidence is mandatory producer output, not a finalizer-restamped optional file."""

import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.merge_utils.source_freshness import _SourceFreshness
from kg_microbe.transform_utils.bactotraits.bactotraits import BactoTraitsTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.producer_audits import (
    required_producer_audits,
    verify_producer_audits,
    verify_recorded_producer_audits,
)
from kg_microbe.utils.source_finalization import (
    FINALIZATION_FILE,
    SourceFinalizationRequired,
    verify_finalized_source_files,
)

FIXTURES = Path(__file__).parent / "resources/source_finalization_review"
AUDIT = "crosswalk_quarantine.tsv"
CONTENT = b'source_record\tclaim_json\nrecord:1\t{"value":"literal\\tquote\\""}\n'


def _read_lookup(producer):
    """Consume the registered producer's unrelated mandatory immutable fixture normally."""
    path = producer.input_base_dir / "lookup.tsv"
    assert type(producer).REQUIRED_CONSUMED_INPUTS == ("bacdive_taxon_lookup",)
    with producer.consume_input("bacdive_taxon_lookup", path) as reader:
        assert reader.read()


@pytest.fixture
def producer(tmp_path, monkeypatch):
    """Exercise a registered producer's declarations without a live transform or API."""
    monkeypatch.setattr(BactoTraitsTransform, "REQUIRED_AUDIT_FILES", (AUDIT,))
    raw = tmp_path / "raw"
    raw.mkdir()
    obj = BactoTraitsTransform.__new__(BactoTraitsTransform)
    Transform.__init__(obj, "bactotraits", raw, tmp_path / "transformed")
    shutil.copyfile(FIXTURES.parent / "merge_source_freshness/lookup.tsv", raw / "lookup.tsv")
    _read_lookup(obj)
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"pato_{kind}.tsv", obj.output_dir / f"{kind}.tsv")
    (obj.output_dir / AUDIT).write_bytes(CONTENT)
    return obj


def test_exact_producer_bytes_survive_finalization_repeat_and_both_merge_checks(producer):
    """The same audit identity survives staging, fresh validation and current code admission."""
    producer.record_producer_audit(AUDIT)
    identity = producer.producer_audit_snapshots[AUDIT]
    report = producer.finalize(fresh_run=True)
    assert report["audit_members"][AUDIT] == identity
    assert report["producer_audit_members"] == {AUDIT: identity}
    assert (producer.output_dir / AUDIT).read_bytes() == CONTENT
    assert producer.finalize() == report
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    _SourceFreshness()._check_record(producer.output_dir / FINALIZATION_FILE, report)


@pytest.mark.parametrize("damage", ["unrecorded", "changed", "missing", "symlink"])
def test_prefinalization_tamper_cannot_be_restamped(producer, tmp_path, damage):
    """A fresh-run request is not permission to invent producer audit evidence."""
    path = producer.output_dir / AUDIT
    if damage != "unrecorded":
        producer.record_producer_audit(AUDIT)
    if damage == "changed":
        path.write_bytes(CONTENT + b"changed\n")
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        path.unlink()
        target = tmp_path / "foreign.tsv"
        target.write_bytes(CONTENT)
        path.symlink_to(target)
    graph_before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        producer.finalize(fresh_run=True)
    assert graph_before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())
    assert not (producer.output_dir / FINALIZATION_FILE).exists()


@pytest.mark.parametrize(
    "damage", ["missing", "changed", "receipt_omission", "both_omitted", "inconsistent", "renamed_source"]
)
def test_postfinalization_tamper_rejected_by_current_producer_declaration(producer, damage):
    """Removing both audit references does not bypass registered mandatory requirements."""
    producer.record_producer_audit(AUDIT)
    report = producer.finalize(fresh_run=True)
    path = producer.output_dir / AUDIT
    if damage == "missing":
        path.unlink()
    elif damage == "changed":
        path.write_bytes(CONTENT + b"changed\n")
    elif damage == "receipt_omission":
        del report["producer_audit_members"]
    elif damage in {"both_omitted", "renamed_source"}:
        del report["producer_audit_members"]
        del report["audit_members"][AUDIT]
        if damage == "renamed_source":
            report["source"] = "unregistered_fixture"
    else:
        report["audit_members"][AUDIT]["bytes"] += 1
    receipt = producer.output_dir / FINALIZATION_FILE
    receipt.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        verify_finalized_source_files([producer.output_node_file])
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        _SourceFreshness()._check_record(receipt, report)


def test_caught_record_failure_poisoned_until_explicit_new_run(producer):
    """Restoring old bytes cannot hide a caught producer-time inconsistency."""
    producer.record_producer_audit(AUDIT)
    (producer.output_dir / AUDIT).write_bytes(b"different\n")
    with pytest.raises(SourceFinalizationRequired, match="changed within"):
        producer.record_producer_audit(AUDIT)
    (producer.output_dir / AUDIT).write_bytes(CONTENT)
    with pytest.raises(SourceFinalizationRequired, match="recording failed"):
        producer.finalize(fresh_run=True)
    producer.begin_consumed_inputs()
    assert producer.producer_audit_snapshots == {}
    _read_lookup(producer)
    producer.record_producer_audit(AUDIT)
    producer.finalize(fresh_run=True)


def test_copied_snapshot_and_new_epoch_do_not_mutate_or_inherit_evidence(producer):
    """Public snapshot access is defensive and same-byte repeat recording is idempotent."""
    producer.record_producer_audit(AUDIT)
    before = producer.producer_audit_snapshots
    producer.record_producer_audit(AUDIT)
    copy = producer.producer_audit_snapshots
    copy[AUDIT]["bytes"] += 1
    assert producer.producer_audit_snapshots == before
    producer.begin_consumed_inputs()
    with pytest.raises(SourceFinalizationRequired, match="snapshots"):
        verify_producer_audits(producer)


def test_staging_copy_mutation_fails_without_publishing(producer, monkeypatch):
    """The staged audit must match original producer bytes, not a newly computed replacement."""
    from kg_microbe.utils import source_finalization

    producer.record_producer_audit(AUDIT)
    original = source_finalization.shutil.copyfile

    def corrupt(source, destination, *args, **kwargs):
        """Alter only the staged evidence copy to exercise its publication guard."""
        result = original(source, destination, *args, **kwargs)
        if Path(destination).name == AUDIT:
            Path(destination).write_bytes(b"corrupted staged evidence\n")
        return result

    monkeypatch.setattr(source_finalization.shutil, "copyfile", corrupt)
    with pytest.raises(SourceFinalizationRequired, match="audit changed"):
        producer.finalize(fresh_run=True)
    assert (producer.output_dir / AUDIT).read_bytes() == CONTENT
    assert not (producer.output_dir / FINALIZATION_FILE).exists()


@pytest.mark.parametrize(
    "names",
    [
        ("../outside.tsv",),
        ("nodes.tsv",),
        ("x_nodes.tsv",),
        ("source_canonicalization.tsv",),
        ("x/go.tsv",),
        ("x\\go.tsv",),
        ("report.json",),
        (AUDIT, AUDIT),
        [AUDIT],
        (None,),
    ],
)
def test_invalid_declarations_fail_before_access(producer, monkeypatch, names):
    """A sidecar contract cannot overwrite graph/finalizer members or escape its directory."""
    monkeypatch.setattr(type(producer), "REQUIRED_AUDIT_FILES", names)
    with pytest.raises(SourceFinalizationRequired, match="declaration"):
        required_producer_audits(type(producer))


def test_merge_admission_retains_audit_guard_after_initial_check(producer):
    """Changes during a merge fail its retained admission, not merely the initial hash check."""
    producer.record_producer_audit(AUDIT)
    report = producer.finalize(fresh_run=True)
    admission = SourceAdmission()
    verify_recorded_producer_audits(type(producer), report, producer.output_dir / FINALIZATION_FILE, admission)
    (producer.output_dir / AUDIT).write_bytes(CONTENT + b"later\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        admission.verify()


@pytest.mark.parametrize("audits", [None, [], "invalid"])
def test_malformed_audit_collection_is_a_contract_error(producer, audits):
    """Direct admission also rejects malformed containers with an actionable rerun error."""
    producer.record_producer_audit(AUDIT)
    report = {"producer_audit_members": producer.producer_audit_snapshots, "audit_members": audits}
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        verify_recorded_producer_audits(type(producer), report, producer.output_dir / FINALIZATION_FILE)
