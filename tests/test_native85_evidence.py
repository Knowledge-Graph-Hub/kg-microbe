"""Test synthetic native85 locator/identity inputs, never full native acceptance."""

import hashlib
from types import SimpleNamespace

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.native85_evidence import COHORT_ENV, load_native85_cohort

SYNTHETIC_PAYLOAD = b'{"synthetic_locator_control": true}\n'
SYNTHETIC_SHA = hashlib.sha256(SYNTHETIC_PAYLOAD).hexdigest()


def test_explicit_cohort_uses_actual_local_bytes_and_admission(tmp_path, monkeypatch):
    """Read the selected absolute file independently of the working directory."""
    selected = tmp_path / "review-evidence" / "cohort.json"
    selected.parent.mkdir()
    selected.write_bytes(SYNTHETIC_PAYLOAD)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setenv(COHORT_ENV, str(selected))
    admission = SourceAdmission()

    assert load_native85_cohort(admission, SYNTHETIC_SHA) == SYNTHETIC_PAYLOAD
    assert admission.identities[selected] == {
        "bytes": len(SYNTHETIC_PAYLOAD),
        "sha256": SYNTHETIC_SHA,
    }
    assert admission.payloads[selected] == SYNTHETIC_PAYLOAD
    admission.verify()


@pytest.mark.parametrize("locator", [None, ""])
def test_missing_explicit_cohort_refuses_without_guessing(tmp_path, monkeypatch, locator):
    """Require a selector even when a plausible authoring-layout cohort exists."""
    guessed = tmp_path / "bacdive-taxonomy-fix-plans-20261001"
    guessed.mkdir()
    (guessed / "multi-claim-deposit-native-ancestry.json").write_bytes(SYNTHETIC_PAYLOAD)
    monkeypatch.chdir(tmp_path)
    if locator is None:
        monkeypatch.delenv(COHORT_ENV, raising=False)
    else:
        monkeypatch.setenv(COHORT_ENV, locator)
    admission = SourceAdmission()

    with pytest.raises(ValueError, match="explicit absolute cohort file path is required"):
        load_native85_cohort(admission, SYNTHETIC_SHA)
    assert admission.identities == {}


@pytest.mark.parametrize("locator", ["cohort.json", "~/cohort.json"])
def test_relative_cohort_is_not_resolved_or_expanded(tmp_path, monkeypatch, locator):
    """Refuse working-directory and home-expansion guesses."""
    (tmp_path / "cohort.json").write_bytes(SYNTHETIC_PAYLOAD)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(COHORT_ENV, locator)
    admission = SourceAdmission()

    with pytest.raises(ValueError, match="cohort file path must be absolute"):
        load_native85_cohort(admission, SYNTHETIC_SHA)
    assert admission.identities == {}


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_missing_or_non_file_cohort_has_specific_diagnostic(tmp_path, monkeypatch, kind):
    """Refuse absent or non-regular evidence before attempting an admitted read."""
    selected = tmp_path / "cohort.json"
    if kind == "directory":
        selected.mkdir()
    monkeypatch.setenv(COHORT_ENV, str(selected))
    admission = SourceAdmission()
    message = "missing or unreadable" if kind == "missing" else "must select a regular file"

    with pytest.raises(ValueError, match=message):
        load_native85_cohort(admission, SYNTHETIC_SHA)
    assert admission.identities == {}


def test_malformed_cohort_locator_has_specific_diagnostic(monkeypatch):
    """Report a malformed selector without handing it to the filesystem."""
    monkeypatch.setattr("tests.native85_evidence.os", SimpleNamespace(environ={COHORT_ENV: "/invalid\0cohort"}))
    admission = SourceAdmission()

    with pytest.raises(ValueError, match="invalid NUL byte"):
        load_native85_cohort(admission, SYNTHETIC_SHA)
    assert admission.identities == {}


def test_cohort_mismatch_checks_actual_bytes_not_a_receipt(tmp_path, monkeypatch):
    """Reject different synthetic bytes after their real admitted read."""
    selected = tmp_path / "cohort.json"
    changed = b'{"synthetic_locator_control": false}\n'
    selected.write_bytes(changed)
    monkeypatch.setenv(COHORT_ENV, str(selected))
    admission = SourceAdmission()

    with pytest.raises(ValueError, match="cohort SHA-256 mismatch"):
        load_native85_cohort(admission, SYNTHETIC_SHA)
    assert admission.identities[selected]["sha256"] == hashlib.sha256(changed).hexdigest()
    assert admission.payloads[selected] == changed


def test_selected_cohort_remains_bound_to_late_admission(tmp_path, monkeypatch):
    """Keep the real admission's late byte-drift refusal after the loader returns."""
    selected = tmp_path / "cohort.json"
    selected.write_bytes(SYNTHETIC_PAYLOAD)
    monkeypatch.setenv(COHORT_ENV, str(selected))
    admission = SourceAdmission()
    assert load_native85_cohort(admission, SYNTHETIC_SHA) == SYNTHETIC_PAYLOAD

    selected.write_bytes(SYNTHETIC_PAYLOAD + b"changed")
    with pytest.raises(SourceFinalizationRequired, match="Merge admitted file changed"):
        admission.verify()


def test_each_load_reads_the_current_explicit_selection(tmp_path, monkeypatch):
    """Avoid caching the environment selector across independent admission scopes."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    second_payload = b'{"synthetic_second_locator": true}\n'
    first.write_bytes(SYNTHETIC_PAYLOAD)
    second.write_bytes(second_payload)
    monkeypatch.setenv(COHORT_ENV, str(first))
    assert load_native85_cohort(SourceAdmission(), SYNTHETIC_SHA) == SYNTHETIC_PAYLOAD

    monkeypatch.setenv(COHORT_ENV, str(second))
    second_sha = hashlib.sha256(second_payload).hexdigest()
    assert load_native85_cohort(SourceAdmission(), second_sha) == second_payload
