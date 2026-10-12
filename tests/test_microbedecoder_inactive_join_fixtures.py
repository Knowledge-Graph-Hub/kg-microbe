"""Unexecuted fixture-migration controls using real producer consumption and guards."""

import csv
import json

import pytest

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from tests.microbedecoder_inactive_join_fixtures import (
    bind_inactive_join_policy,
    write_empty_join_gss,
    write_inactive_join_policy,
)
from tests.microbedecoder_join_fixtures import prepare as prepare_active
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_transform import _NoChebi, _supply_gold_fold_report


def _producer(directory, monkeypatch, *, context="first fixture"):
    """Provide independent old/new policies and genuine isolated source authorities."""
    raw = write_empty_join_gss(directory / "raw").parent
    output = directory / "transformed"
    source = raw / "database.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["LPSN_ID", "BacDive_ID", "Species"])
        writer.writerow(["101", "42", context])
    _supply_gold_fold_report(output)
    transform = MicrobeDecoderTransform(raw, output, chemical_loader=_NoChebi())
    bind_fixture_quarantine_policy(transform, source)
    bind_inactive_join_policy(transform, source, monkeypatch)
    return transform, source


def _audit(transform):
    """Read a tiny real audit without synthesizing any lifecycle receipt."""
    with (transform.output_dir / joins.AUDIT_FILE).open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_inactive_fixture_performs_real_reads_and_keeps_old_policy(tmp_path, monkeypatch):
    """Zero decisions require actual policy/GSS/CSV reads and producer completion."""
    transform, source = _producer(tmp_path, monkeypatch)
    old_policy = transform.crosswalk_quarantine_policy
    old_bytes = old_policy.read_bytes()
    source_bytes = source.read_bytes()
    transform.run(source)
    assert transform.crosswalk_quarantine_policy == old_policy
    assert old_policy.read_bytes() == old_bytes and source.read_bytes() == source_bytes
    assert set(joins.REQUIRED_INPUTS) <= transform.consumed_input_snapshots.keys()
    assert transform.producer_native_inputs[joins.CONTRACT_KEY]["quarantined_links"] == 0
    assert _audit(transform) == []
    transform.verify_native_inputs()


def test_existing_explicit_gss_fixture_is_not_replaced(tmp_path):
    """An intentional accepted-name fixture remains literal authority input."""
    path = write_empty_join_gss(tmp_path / "raw")
    payload = b"record_no,record_lnk,status\n103,101,synonym\n101,,correct name\n"
    path.write_bytes(payload)
    assert write_empty_join_gss(path.parent) == path
    assert path.read_bytes() == payload


@pytest.mark.parametrize("header", ["LPSN_ID", "BacDive_ID", "other"])
def test_inactive_writer_does_not_repair_incomplete_source_headers(tmp_path, header):
    """Missing native columns are an explicit authoring error, not runtime fabrication."""
    source = tmp_path / "source.csv"
    source.write_text(header + "\n101\n")
    original = source.read_bytes()
    gss = write_empty_join_gss(tmp_path / "raw")
    with pytest.raises(ValueError, match="requires LPSN_ID and BacDive_ID"):
        write_inactive_join_policy(source, gss, tmp_path / "policy")
    assert source.read_bytes() == original
    assert not (tmp_path / "policy").exists()


def test_inactive_writer_cannot_rebase_an_existing_policy_path(tmp_path):
    """A new source epoch needs a new fixture policy locator."""
    source = tmp_path / "source.csv"
    source.write_text("LPSN_ID,BacDive_ID\n101,42\n")
    gss = write_empty_join_gss(tmp_path / "raw")
    policy = write_inactive_join_policy(source, gss, tmp_path / "policy")
    before = policy.read_bytes()
    source.write_text("LPSN_ID,BacDive_ID\n102,42\n")
    with pytest.raises(ValueError, match="different source bytes"):
        write_inactive_join_policy(source, gss, tmp_path / "policy")
    assert policy.read_bytes() == before


def test_nested_inactive_cohort_scope_restores_previous_live_guard(tmp_path, monkeypatch):
    """A second fixture scope must not permanently rebase an earlier producer's anchors."""
    first, first_source = _producer(tmp_path / "first", monkeypatch)
    first.run(first_source)
    first_policy = first.bacdive_join_policy.read_bytes()
    with monkeypatch.context() as nested:
        second, second_source = _producer(tmp_path / "second", nested, context="different fixture")
        assert second.bacdive_join_policy != first.bacdive_join_policy
        second.run(second_source)
        second.verify_native_inputs()
    assert first.bacdive_join_policy.read_bytes() == first_policy
    first.verify_native_inputs()


def test_inactive_binder_does_not_erase_separately_scoped_active_decision(tmp_path, monkeypatch):
    """The existing selected-cohort prepare helper and old binder stay independent."""
    active, source, _, policy, _ = prepare_active(tmp_path / "active", monkeypatch)
    active.run(source)
    assert len(_audit(active)) == 1
    selected_policy = policy.read_bytes()
    with monkeypatch.context() as nested:
        inactive, inactive_source = _producer(tmp_path / "inactive", nested)
        inactive.run(inactive_source)
        assert _audit(inactive) == []
        assert json.loads(inactive.bacdive_join_policy.read_text())["decisions"] == []
    assert policy.read_bytes() == selected_policy
    active.verify_native_inputs()
    assert len(_audit(active)) == 1
