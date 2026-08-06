"""
Tests for fold-enrichment measurement of PREGO scores.

This module exists because the percentile calibration equalizes rank, not
quality, and the difference is not rhetorical: measured against curated
taxon→GO annotations the direction of the score/agreement relationship is
**gold-standard dependent** — falling against the trait-derived benchmark,
rising against UniProt. These tests pin the measurement machinery, so the
question stays checkable and can be re-run against a better gold standard.
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


def test_windows_are_equal_count_where_the_score_varies():
    """
    Windows are equal-count, not equal-width.

    PREGO's scores pile up at the cap, so equal-width bins would put most of
    the mass in one bin and measure nothing.
    """
    scored = [(i / 100.0, i % 3 == 0) for i in range(100)]
    results = enrichment_by_window(scored, baseline=0.3, windows=5)
    assert [r["n"] for r in results] == [20, 20, 20, 20, 20]


def test_a_dominant_tie_block_yields_fewer_windows():
    """
    Tie-safety outranks hitting the requested window count.

    With 90% of rows sharing one score there is no way to cut five windows
    without splitting that block, and splitting it would fabricate signal
    from sort order. Returning fewer, honest windows is the right trade.
    """
    scored = [(0.1, True)] * 10 + [(4.0, False)] * 90
    results = enrichment_by_window(scored, baseline=0.1, windows=5)
    assert len(results) < 5
    assert sum(r["n"] for r in results) == 100, "no rows may be dropped"


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

    This is PREGO's shape against the trait-derived gold standard: fold
    enrichment falls from 1.61x in the lowest continuous-channel quintile to
    1.56x by the third. (Against UniProt it rises instead — the direction is
    gold-standard dependent.) A threshold on an anti-correlated score selects
    edges that agree with curated knowledge less often, so the predicate has
    to catch that case.
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
    # Two windows where the score varies, plus a dominant tie block.
    varied = [(i / 200.0, i >= 25) for i in range(50)]
    scored = varied + [(4.0, False)] * 50
    results = enrichment_by_window(scored, baseline=0.5, windows=4)
    assert any(r["degenerate"] for r in results), "fixture must produce a tied window"
    assert sum(1 for r in results if not r["degenerate"]) >= 2, "and >=2 usable windows"
    # Verdict rests only on the windows where the score actually varies.
    assert is_monotone_increasing(results)


def test_empty_input_yields_no_windows():
    """Nothing to measure is not an error."""
    assert enrichment_by_window([], baseline=0.1) == []


def test_windows_must_be_positive():
    """A non-positive window count is a caller bug, not a silent no-op."""
    with pytest.raises(ValueError):
        enrichment_by_window([(1.0, True)], baseline=0.1, windows=0)


def test_windows_never_split_a_tie_block():
    """
    A window boundary must fall only where the score changes.

    Slicing a sorted list by index splits a tie block, and which tied rows
    land either side is then decided by the sort's tiebreak rather than the
    score. An ad-hoc analysis that sorted ``(score, is_hit)`` tuples did
    exactly this on the real data: it pushed every non-hit to the low side
    of the 4.0 block and every hit to the high side, manufacturing a 0.44x
    window next to a 1.95x one out of pure ordering. Those numbers were
    reported before the bug was caught.
    """
    # 20 varied rows then a 80-row tie block that no boundary may cut.
    scored = [(i / 100.0, i % 2 == 0) for i in range(20)] + [(4.0, i < 40) for i in range(80)]
    results = enrichment_by_window(scored, baseline=0.5, windows=5)
    tied = [r for r in results if r["score_min"] == 4.0 or r["score_max"] == 4.0]
    assert len(tied) == 1, f"the 4.0 block must live in exactly one window, got {len(tied)}"
    assert tied[0]["n"] == 80, "the whole tie block belongs to that window"
    assert tied[0]["degenerate"] is True


def test_tie_split_cannot_be_faked_by_hit_ordering():
    """
    Ordering hits within a tie block must not change any window's fold.

    This is the direct regression for the artifact above.
    """
    block_sorted = [(4.0, False)] * 40 + [(4.0, True)] * 40
    block_reversed = [(4.0, True)] * 40 + [(4.0, False)] * 40
    a = enrichment_by_window(block_sorted, baseline=0.5, windows=4)
    b = enrichment_by_window(block_reversed, baseline=0.5, windows=4)
    assert [r["fold"] for r in a] == [r["fold"] for r in b]


def test_all_degenerate_is_insufficient_data_not_success():
    """
    A fully tied channel has no score ordering, so monotonicity is undefined.

    ``all()`` over an empty sequence is vacuously true, so filtering out every
    degenerate window and then calling ``all()`` reported a channel with zero
    usable comparisons as monotonically increasing.
    """
    results = enrichment_by_window([(4.0, i < 10) for i in range(100)], baseline=0.1, windows=5)
    assert all(r["degenerate"] for r in results)
    assert is_monotone_increasing(results) is False


def test_single_usable_window_is_also_insufficient():
    """One window is not a comparison either."""
    scored = [(0.1, True)] * 10 + [(4.0, False)] * 90
    results = enrichment_by_window(scored, baseline=0.1, windows=5)
    assert sum(1 for r in results if not r["degenerate"]) < 2
    assert is_monotone_increasing(results) is False
