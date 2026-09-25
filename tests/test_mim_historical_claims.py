"""Verify conservative quarantine resolves contradictions without guessed identities."""

import pytest

from scripts import audit_mim_historical_claims as audit
from scripts import mim_conservative_refresh as refresh
from tests.test_mim_conservative_refresh import FIELDS, _metadata, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs


@pytest.mark.parametrize("reverse_identity", [False, True])
def test_candidate_quarantines_complete_historical_conflicts(inputs, reverse_identity):
    """MIM's lossy old exact and parent claims reset together; independent rows survive."""
    baseline = inputs["baseline"]
    rows = list(refresh._rows(baseline))
    subject, target = ("CHEBI:6", "CHEBI:1") if reverse_identity else ("CHEBI:1", "CHEBI:6")
    rows.append(_row(subject, target, "Historical label", "chebi_xrefs|mediaingredientmech_reviewed"))
    _table(baseline, FIELDS, rows, _metadata())
    result = refresh.build_conservative_candidate(**inputs)
    report = audit.audit_historical_claims(
        baseline=baseline, candidate=result.candidate_path, quarantine=result.quarantine_path
    )
    assert report["baseline_conflicting_pairs"] == 1
    assert report["historical_rows_preserved_in_quarantine"] == 2
    assert report["candidate_conflicting_pairs"] == 0
    assert report["promotion_authorized"] is False
    assert report["pairs"][0]["identity_rows"][0]["mapping_date"] == "2026-01-01"
    assert any(row["comment"] == "recipe_equivalent_hydrate" for row in _read(result.candidate_path))
    assert any(
        row["subject_id"] == "CHEBI:4" and row["predicate_id"] == "skos:broadMatch"
        for row in _read(result.candidate_path)
    )


@pytest.mark.parametrize("mutation", ["lost_row", "changed_source", "lost_reason", "retained_conflict"])
def test_audit_refuses_incomplete_or_still_conflicting_candidate(tmp_path, mutation):
    """Counts alone cannot conceal source changes, missing originals, or retained ambiguity."""
    rows = [
        _row("CHEBI:1", "CHEBI:2", "two", "mediaingredientmech_reviewed"),
        _row("CHEBI:1", "CHEBI:2", "two", "mediaingredientmech_reviewed", predicate="skos:broadMatch"),
    ]
    baseline, candidate, quarantine = (tmp_path / name for name in ("baseline.tsv", "candidate.tsv", "quarantine.tsv"))
    _table(baseline, FIELDS, rows, _metadata())
    _table(candidate, FIELDS, rows if mutation == "retained_conflict" else [], _metadata())
    quarantined = [dict(row, quarantine_reason="historical_mim_provenance") for row in rows]
    if mutation == "lost_row":
        quarantined.pop()
    elif mutation == "changed_source":
        quarantined[0]["source"] = "new_unverified_source"
    elif mutation == "lost_reason":
        quarantined[0]["quarantine_reason"] = ""
    _table(quarantine, (*FIELDS, "quarantine_reason"), quarantined, _metadata())
    with pytest.raises(ValueError):
        audit.audit_historical_claims(baseline=baseline, candidate=candidate, quarantine=quarantine)
