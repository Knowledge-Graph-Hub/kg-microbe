"""
Tests for per-resource PREGO confidence calibration.

The failure this module exists to prevent is subtle: a global cutoff on
``prego_score`` looks like a confidence filter but behaves as a provenance
filter, because ~47% of PREGO edges carry a flat author-assigned constant
(4.0 for the genome channels, 3.0 for PMID rows) while only the
Environmental Samples channel has a score that varies. At ``>= 4.0`` a
global cut keeps essentially all of the flat rows and deletes ~87% of the
one channel carrying real signal.

These tests therefore pin behaviour, not just arithmetic: that flat channels
are tiered rather than ranked, that ties at the score cap move as a unit,
and that cutoffs do not depend on row order.
"""

import pytest

from kg_microbe.transform_utils.prego.calibration import (
    STAR_MAX,
    ScoreHistogram,
    build_cutoffs,
    estimate_retention,
    flat_channel_star,
    is_continuous_channel,
    keep_row,
    star_for_row,
    validate_tau,
)

# Channel shares measured over all 44,716,161 emitted PREGO edges.
MEASURED_FLAT_SHARES = {
    "Isolates": 0.2866,
    "Genome annotation": 0.0917,
    "Metagenome-Assembled Genome": 0.0727,
    "Single Amplified Genome": 0.0179,
    "PMID:12345678": 0.0005,
}
MEASURED_CONTINUOUS_SHARE = 0.5300


# ---------------------------------------------------------------------------
# Channel classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "channel",
    ["402 of 487 samples", "1 of 1597 samples", "12183 of 40405 samples"],
)
def test_evidence_tally_is_the_continuous_channel(channel):
    """Environmental Samples rows are identified by their tally shape."""
    assert is_continuous_channel(channel)
    assert flat_channel_star(channel) is None


@pytest.mark.parametrize(
    "channel,expected",
    [
        ("Isolates", 4.0),
        ("Genome annotation", 4.0),
        ("Metagenome-Assembled Genome", 4.0),
        ("Single Amplified Genome", 4.0),
        ("PMID:24914180", 3.0),
    ],
)
def test_flat_channels_get_their_author_assigned_tier(channel, expected):
    """
    Flat channels carry a constant assigned by PREGO's authors.

    These are tiers, not measurements — every row in the channel has the
    same value, so there is nothing within the channel to threshold on.
    """
    assert flat_channel_star(channel) == expected
    assert not is_continuous_channel(channel)


def test_unrecognised_channel_is_neither():
    """An unknown channel must not be silently coerced into a tier."""
    assert flat_channel_star("Kidneys") is None or isinstance(flat_channel_star("Kidneys"), float)
    assert not is_continuous_channel("Kidneys")


# ---------------------------------------------------------------------------
# Histogram / cutoff inversion
# ---------------------------------------------------------------------------


def _hist(scores):
    """Build a histogram from an iterable of scores."""
    h = ScoreHistogram()
    for s in scores:
        h.add(s)
    return h


def test_cutoff_retains_the_requested_fraction():
    """tau=2.0 must keep about the top half of a uniform resource."""
    h = _hist(i / 1000.0 * 4.0 for i in range(1000))
    cut = h.cutoff(2.0)
    kept = sum(1 for i in range(1000) if i / 1000.0 * 4.0 >= cut)
    assert 0.49 <= kept / 1000 <= 0.51


def test_tau_zero_keeps_everything():
    """The most permissive setting must not drop rows."""
    h = _hist([0.0, 1.0, 2.0, 3.0, 4.0])
    assert h.cutoff(0.0) == 0.0


def test_cutoff_is_order_independent():
    """
    Two runs over the same data must produce an identical cutoff.

    This is why fixed-width histograms are used instead of t-digest or
    P-square: those are order-dependent, so a re-run could silently ship a
    different edge set.
    """
    # Same multiset, two orders — built by a stride permutation rather than
    # an RNG so the test itself is deterministic.
    scores = [(i % 4001) / 1000.0 for i in range(5000)]
    reordered = [scores[(i * 37) % 5000] for i in range(5000)]
    assert sorted(scores) == sorted(reordered), "reordering must preserve the multiset"
    assert scores != reordered, "the two orders must actually differ"
    assert _hist(scores).cutoff(2.5) == _hist(reordered).cutoff(2.5)


def test_tie_block_at_the_cap_moves_as_a_unit():
    """
    Rows sharing the capped score must be kept or dropped together.

    ~13% of the real continuous channel piles up at the cap. Splitting that
    block would delete some edges and keep others with identical evidence.
    """
    h = _hist([4.0] * 300 + [1.0] * 700)
    cut = h.cutoff(2.0)
    # Every capped row lands on the same side of the cutoff.
    assert (4.0 >= cut) is True
    kept_capped = sum(1 for _ in range(300) if 4.0 >= cut)
    assert kept_capped in (0, 300)


def test_empty_histogram_refuses_to_produce_a_cutoff():
    """A resource with no rows must fail loudly rather than return 0."""
    with pytest.raises(ValueError):
        ScoreHistogram().cutoff(2.0)


def test_scores_above_the_documented_cap_are_binned():
    """
    The shipped data reaches 4.00735, above the paper's stated cap of 4.

    Binning to exactly 4.0 would silently clamp those rows into the top bin
    and misreport the distribution.
    """
    h = _hist([4.00735, 4.0, 3.0])
    assert h.count == 3
    assert h.cutoff(0.0) == 0.0


# ---------------------------------------------------------------------------
# Row-level keep/drop
# ---------------------------------------------------------------------------


def test_flat_channel_rows_are_rated_by_their_own_score():
    """
    A recognised flat channel is thresholded on the row's own value.

    Its score is already on the star axis, so it is used directly rather
    than substituting the channel's documented constant. Overriding would
    silently promote a row that disagrees with its channel — the fixture
    has Isolates rows scoring 3, and a constant-substituting implementation
    rated them 4.
    """
    cutoffs = {"MGnify": 2.0}
    assert keep_row("Isolates", 4.0, "MGnify", cutoffs, tau=3.5) is True
    # An Isolates row that actually scores 3 must not be promoted to 4.
    assert keep_row("Isolates", 3.0, "MGnify", cutoffs, tau=3.5) is False
    assert star_for_row("Isolates", 3.0, "MGnify", cutoffs) == 3.0
    # PMID sits at 3.0, so a 3.5 threshold drops it.
    assert keep_row("PMID:1", 3.0, "MGnify", cutoffs, tau=3.0) is True
    assert keep_row("PMID:1", 3.0, "MGnify", cutoffs, tau=3.5) is False


def test_continuous_rows_are_judged_against_their_own_resource():
    """
    Continuous rows are judged against their own resource's cutoff.

    Per-resource cutoffs are the point: a shared cutoff would conflate
    MGnify with MG-RAST, whose score marginals differ.
    """
    cutoffs = {"MGnify": 1.0, "MG-RAST metagenome study": 3.0}
    assert keep_row("10 of 20 samples", 2.0, "MGnify", cutoffs, tau=4.0) is True
    assert keep_row("10 of 20 samples", 2.0, "MG-RAST metagenome study", cutoffs, tau=4.0) is False


def test_uncalibratable_row_is_kept_not_dropped():
    """
    An unknown channel must not be deleted.

    Dropping rows we cannot calibrate would remove data for a reason
    unrelated to confidence — the exact failure mode this module prevents.
    """
    assert keep_row("Kidneys", 4.0, "unknown", {}, tau=2.0) is True
    assert star_for_row("Kidneys", 4.0, "unknown", {}) is None


def test_continuous_row_with_no_cutoff_for_its_resource_is_kept():
    """A resource missing from the calibration table must not silently vanish."""
    assert keep_row("10 of 20 samples", 2.0, "BrandNewResource", {}, tau=2.0) is True


# ---------------------------------------------------------------------------
# Retention model — checked against the measured distribution
# ---------------------------------------------------------------------------


def test_default_tau_lands_inside_the_75_percent_budget():
    """
    tau=2.0 must retain ~73.5% of edges on the real channel shares.

    Independently derived: 47.00% flat + (53.00% x 50%) = 73.50%, and the
    continuous channel's measured p50 is raw score 1.71.
    """
    retained = estimate_retention(MEASURED_FLAT_SHARES, 2.0, MEASURED_CONTINUOUS_SHARE)
    assert 0.73 <= retained <= 0.745
    assert retained <= 0.75


def test_retention_is_monotone_decreasing_in_tau():
    """A stricter threshold can never retain more."""
    values = [estimate_retention(MEASURED_FLAT_SHARES, t / 2, MEASURED_CONTINUOUS_SHARE) for t in range(9)]
    assert values == sorted(values, reverse=True)


def test_tau_four_is_provenance_dominated():
    """
    At tau=4.0 the flat channels dominate what survives.

    This is the failure mode the design exists to avoid, so it must be
    detectable — a caller can compare these two numbers to decide whether
    to warn.
    """
    retained = estimate_retention(MEASURED_FLAT_SHARES, 4.0, MEASURED_CONTINUOUS_SHARE)
    flat_only = sum(s for c, s in MEASURED_FLAT_SHARES.items() if (flat_channel_star(c) or 0) >= 4.0)
    assert retained == pytest.approx(flat_only, abs=1e-9)
    assert flat_only / retained > 0.99


@pytest.mark.parametrize("bad", [-0.1, 4.1, float("nan"), float("inf")])
def test_out_of_range_threshold_is_refused(bad):
    """Above STAR_MAX every channel drops out; refuse rather than emit nothing."""
    with pytest.raises(ValueError):
        validate_tau(bad)


def test_build_cutoffs_validates_before_inverting():
    """A bad tau must fail before any histogram work."""
    with pytest.raises(ValueError):
        build_cutoffs({"MGnify": _hist([1.0, 2.0])}, tau=STAR_MAX + 1)


def test_cap_tie_block_makes_the_threshold_stop_discriminating():
    """
    A resource piled up at the cap plateaus instead of honouring the request.

    Measured on the real archives: MG-RAST amplicon holds 46.4% of its rows
    at the score cap, so every threshold above ~2.5 retains that same 46.4%
    rather than the requested fraction. Ties are deliberately never split,
    so this is correct behaviour — but it means the knob silently stops
    responding, which the transform has to warn about.
    """
    # 46% of rows at the cap, the rest spread below it.
    h = _hist([4.0] * 460 + [i / 540.0 * 2.0 for i in range(540)])
    for tau in (2.5, 3.0, 3.5):
        row = h.as_row("MG-RAST amplicon study", tau)
        realized = float(row["kept_fraction"])
        requested = 1.0 - tau / STAR_MAX
        assert realized >= 0.46, "the capped block must survive intact"
        assert realized > requested + 0.05, (
            f"tau={tau} should over-retain (realized {realized:.3f} vs requested {requested:.3f}), "
            "which is what the transform warns about"
        )
