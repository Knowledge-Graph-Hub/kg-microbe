"""
Tests for fold-enrichment measurement of PREGO scores.

This module exists because the percentile calibration equalizes rank, not
quality, and the difference is not rhetorical: measured against curated
taxon→GO annotations, PREGO's score turns out to be *anti*-correlated with
agreement. These tests pin the measurement machinery that established that,
so the finding stays checkable and can be re-run against a better gold
standard.
"""

import pytest

from kg_microbe.transform_utils.prego.quality import (
    GoldStandard,
    enrichment_by_window,
    fold_enrichment,
    is_monotone_increasing,
)


@pytest.fixture()
def gold():
    """Return a small curated set over 3 subjects x 2 objects."""
    return GoldStandard(
        [
            ("NCBITaxon:1", "GO:1"),
            ("NCBITaxon:2", "GO:1"),
            ("NCBITaxon:3", "GO:2"),
        ]
    )


def test_entity_space_is_tracked_not_just_pairs(gold):
    """
    Comparability is about entities, not only pairs.

    Scoring a pair whose object the gold standard has never seen would count
    as a miss for a reason unrelated to quality, so the entity space has to
    be explicit.
    """
    assert gold.subjects == {"NCBITaxon:1", "NCBITaxon:2", "NCBITaxon:3"}
    assert gold.objects == {"GO:1", "GO:2"}
    assert gold.covers("NCBITaxon:1", "GO:2") is True
    assert gold.covers("NCBITaxon:1", "GO:99") is False, "unseen object is not comparable"
    assert gold.contains("NCBITaxon:1", "GO:2") is False, "covered but not asserted"


def test_baseline_is_gold_density_over_the_shared_space(gold):
    """3 curated pairs in a 3x2 space means a random pair hits half the time."""
    assert gold.baseline({"NCBITaxon:1", "NCBITaxon:2", "NCBITaxon:3"}, {"GO:1", "GO:2"}) == 0.5


def test_baseline_refuses_an_empty_shared_space(gold):
    """No shared entities means fold enrichment is undefined, not zero."""
    with pytest.raises(ValueError):
        gold.baseline(set(), {"GO:1"})


def test_fold_of_one_means_no_information():
    """A hit rate equal to the baseline carries no signal."""
    assert fold_enrichment(0.25, 0.25) == 1.0
    assert fold_enrichment(0.50, 0.25) == 2.0


def test_fold_refuses_a_zero_baseline():
    """Dividing by a zero baseline would report infinite enrichment from nothing."""
    with pytest.raises(ValueError):
        fold_enrichment(0.5, 0.0)


def test_windows_are_equal_count_not_equal_width():
    """
    Equal-count windows are required because scores pile up at the cap.

    Equal-width bins would put most of the mass in a single bin and measure
    nothing.
    """
    scored = [(0.1, True)] * 10 + [(4.0, False)] * 90
    results = enrichment_by_window(scored, baseline=0.1, windows=5)
    assert [r["n"] for r in results] == [20, 20, 20, 20, 20]


def test_tied_window_is_flagged_degenerate():
    """
    An all-ties window's hit rate reflects arrival order, not score.

    On the real data the flat channels produced windows reading 0.00x and
    5.00x purely from how ties happened to sort. Those must never be read as
    signal, so they are flagged.
    """
    scored = [(4.0, i < 10) for i in range(100)]
    results = enrichment_by_window(scored, baseline=0.1, windows=5)
    assert all(r["degenerate"] for r in results)


def test_varying_window_is_not_degenerate():
    """A window spanning a real score range is usable."""
    scored = [(i / 100.0, i % 2 == 0) for i in range(100)]
    results = enrichment_by_window(scored, baseline=0.5, windows=5)
    assert not any(r["degenerate"] for r in results)


def test_monotonicity_predicate_detects_a_good_score():
    """A score that works has fold enrichment rising with score."""
    scored = [(i / 100.0, i >= 50) for i in range(100)]
    results = enrichment_by_window(scored, baseline=0.5, windows=2)
    assert is_monotone_increasing(results)


def test_monotonicity_predicate_detects_the_prego_failure():
    """
    An anti-correlated score must be reported as failing.

    This is PREGO's measured shape: fold enrichment falls from 1.61x in the
    lowest continuous-channel quintile to 1.17x in the highest. A threshold
    on such a score selects edges that agree with curated knowledge less
    often, so the predicate has to catch it.
    """
    scored = [(i / 100.0, i < 50) for i in range(100)]
    results = enrichment_by_window(scored, baseline=0.5, windows=2)
    assert not is_monotone_increasing(results)


def test_monotonicity_ignores_degenerate_windows():
    """
    Tied windows must not decide the verdict either way.

    Otherwise the flat channels' arbitrary tie ordering would flip the
    answer at random.
    """
    scored = [(0.1, False)] * 25 + [(0.5, True)] * 25 + [(4.0, False)] * 50
    results = enrichment_by_window(scored, baseline=0.5, windows=4)
    assert any(r["degenerate"] for r in results), "fixture must produce a tied window"
    # Verdict rests only on the windows where the score actually varies.
    assert is_monotone_increasing(results)


def test_empty_input_yields_no_windows():
    """Nothing to measure is not an error."""
    assert enrichment_by_window([], baseline=0.1) == []


def test_windows_must_be_positive():
    """A non-positive window count is a caller bug, not a silent no-op."""
    with pytest.raises(ValueError):
        enrichment_by_window([(1.0, True)], baseline=0.1, windows=0)
