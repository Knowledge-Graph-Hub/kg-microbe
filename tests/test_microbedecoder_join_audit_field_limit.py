"""MicrobeDecoder reads its join audit back at a field limit bounded by the file, not CSV's default (#1599)."""

import csv

import pytest

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.microbedecoder_join_fixtures import prepare


def _longest_audit_cell(transform):
    """Return the length of the longest cell the producer wrote into its join audit."""
    with (transform.output_dir / joins.AUDIT_FILE).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    return max(len(cell) for row in rows for cell in row)


@pytest.fixture
def caller_limit():
    """Restore whatever limit the session had, whatever the test leaves behind."""
    previous = csv.field_size_limit()
    yield
    csv.field_size_limit(previous)


def test_an_audit_cell_longer_than_the_callers_limit_still_verifies(tmp_path, monkeypatch, caller_limit):
    """
    A reviewed witness can outgrow CSV's 131,072-character default; verification must still read it.

    The caller's limit is set just below the audit's longest cell, which stands in
    for a witness over the default, and must be the same afterwards.
    """
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    limit = _longest_audit_cell(transform) - 1
    csv.field_size_limit(limit)
    joins.verify_transform(transform)
    assert csv.field_size_limit() == limit


def test_the_callers_limit_is_restored_when_verification_fails(tmp_path, monkeypatch, caller_limit):
    """A refused audit still leaves the process-wide limit where the caller set it."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    audit = transform.output_dir / joins.AUDIT_FILE
    audit.write_text(audit.read_text(encoding="utf-8").replace("source_record", "renamed", 1), encoding="utf-8")
    csv.field_size_limit(1000)
    with pytest.raises(SourceFinalizationRequired, match="audit header changed"):
        joins.verify_transform(transform)
    assert csv.field_size_limit() == 1000
