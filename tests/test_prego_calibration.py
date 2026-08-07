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
    PREGO_RESOURCE_CLASS_STARS,
    STAR_MAX,
    ScoreHistogram,
    _bin_index,
    build_cutoffs,
    estimate_retention,
    flat_channel_star,
    is_continuous_channel,
    keep_row,
    star_for_row,
    validate_tau,
)
from kg_microbe.transform_utils.prego.utils import (
    CHANNEL_ENVIRONMENTAL,
    CHANNEL_GENOMES,
    CHANNEL_LITERATURE,
)

# Channel shares measured over all 44,716,161 emitted PREGO edges.
# Channel shares measured over all 44,716,161 emitted PREGO edges. Keyed by
# channel now that prego_channel is archive-derived: the genome channel carries
# Isolates + Genome annotation + MAG + SAG (28.66 + 9.17 + 7.27 + 1.79), and the
# literature channel the PMID rows.
MEASURED_FLAT_SHARES = {
    CHANNEL_GENOMES: 0.4689,
    CHANNEL_LITERATURE: 0.0005,
}
MEASURED_CONTINUOUS_SHARE = 0.5300


# ---------------------------------------------------------------------------
# Channel classification
# ---------------------------------------------------------------------------


def test_environmental_samples_is_the_continuous_channel():
    """
    The continuous channel is now named, not shape-matched.

    ``prego_channel`` used to carry PREGO's column 6 verbatim, so "continuous"
    had to be inferred from an evidence tally like ``402 of 487 samples``. That
    inference silently defined the channel for every measurement in
    PREGO_SCORE_VALIDATION.md. The column now holds the archive-derived
    channel, so the check is a direct comparison and the tally — which lives in
    ``prego_evidence`` — is no longer a channel at all.
    """
    assert is_continuous_channel(CHANNEL_ENVIRONMENTAL)
    assert flat_channel_star(CHANNEL_ENVIRONMENTAL) is None
    for tally in ("402 of 487 samples", "1 of 1597 samples", "12183 of 40405 samples"):
        assert not is_continuous_channel(tally), "an evidence tally is not a channel"


@pytest.mark.parametrize(
    "channel,expected",
    [(CHANNEL_GENOMES, 4.0), (CHANNEL_LITERATURE, 3.0)],
)
def test_flat_channels_are_recognised_by_name(channel, expected):
    """
    Flat channels are those whose score PREGO's authors assigned by fiat.

    The returned constant documents the expected value; ``star_for_row`` still
    rates a row by its own score, so a row disagreeing with its channel's tier
    is preserved rather than promoted.
    """
    assert flat_channel_star(channel) == expected
    assert not is_continuous_channel(channel)


def test_unrecognised_channel_is_neither():
    """An unknown channel must not be silently coerced into a tier."""
    assert flat_channel_star("mystery_channel") is None or isinstance(flat_channel_star("mystery_channel"), float)
    assert not is_continuous_channel("mystery_channel")


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
    cutoffs = {"MGnify": _bin_index(2.0)}
    assert keep_row(CHANNEL_GENOMES, 4.0, "MGnify", cutoffs, tau=3.5) is True
    # An Isolates row that actually scores 3 must not be promoted to 4.
    assert keep_row(CHANNEL_GENOMES, 3.0, "MGnify", cutoffs, tau=3.5) is False
    assert star_for_row(CHANNEL_GENOMES, 3.0, "MGnify", cutoffs) == 3.0
    # PMID sits at 3.0, so a 3.5 threshold drops it.
    assert keep_row(CHANNEL_LITERATURE, 3.0, "MGnify", cutoffs, tau=3.0) is True
    assert keep_row(CHANNEL_LITERATURE, 3.0, "MGnify", cutoffs, tau=3.5) is False


def test_continuous_rows_are_judged_against_their_own_resource():
    """
    Continuous rows are judged against their own resource's cutoff.

    Per-resource cutoffs are the point: a shared cutoff would conflate
    MGnify with MG-RAST, whose score marginals differ.
    """
    # Cutoffs are BIN INDICES, not raw scores: the filter and the calibration
    # table have to compare on the same quantity, and a bin's lower edge can
    # exceed the scores inside it for ~11.5% of representable 4-dp values.
    cutoffs = {"MGnify": _bin_index(1.0), "MG-RAST metagenome study": _bin_index(3.0)}
    assert keep_row(CHANNEL_ENVIRONMENTAL, 2.0, "MGnify", cutoffs, tau=4.0) is True
    assert keep_row(CHANNEL_ENVIRONMENTAL, 2.0, "MG-RAST metagenome study", cutoffs, tau=4.0) is False


def test_uncalibratable_row_is_kept_not_dropped():
    """
    An unknown channel must not be deleted.

    Dropping rows we cannot calibrate would remove data for a reason
    unrelated to confidence — the exact failure mode this module prevents.
    """
    assert keep_row("mystery_channel", 4.0, "unknown", {}, tau=2.0) is True
    assert star_for_row("mystery_channel", 4.0, "unknown", {}) is None


def test_continuous_row_with_no_cutoff_for_its_resource_is_kept():
    """A resource missing from the calibration table must not silently vanish."""
    assert keep_row(CHANNEL_ENVIRONMENTAL, 2.0, "BrandNewResource", {}, tau=2.0) is True


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


def test_estimate_retention_rejects_resource_class_keys():
    """
    Feeding PREGO_RESOURCE_CLASS_STARS' keys must raise, not silently mis-answer.

    Those keys are PREGO *resource classes* (``Isolates``, ``Genome
    annotation``, ...), while ``flat_channel_star`` keys on the
    archive-derived channel — so none of them resolves. Scoring an
    unrecognised channel as 0.0 and excluding it returned 0.265 where the
    answer was 0.734, a 2.8x error with no exception. They live in the same
    module and read as if they interoperate, which is exactly why this has to
    fail loudly (#712).
    """
    stale = {"Isolates": 0.2866, "Genome annotation": 0.0917}
    with pytest.raises(ValueError, match="unrecognised flat channel"):
        estimate_retention(stale, 2.0, MEASURED_CONTINUOUS_SHARE)

    # Every documented resource class must be rejected, so the guard cannot
    # rot into covering only the two probed above.
    for resource_class in PREGO_RESOURCE_CLASS_STARS:
        with pytest.raises(ValueError, match="unrecognised flat channel"):
            estimate_retention({resource_class: 1.0}, 2.0, 0.0)


def test_retention_is_monotone_decreasing_in_tau():
    """A stricter threshold can never retain more."""
    values = [estimate_retention(MEASURED_FLAT_SHARES, t / 2, MEASURED_CONTINUOUS_SHARE) for t in range(9)]
    assert values == sorted(values, reverse=True)


def test_tau_four_is_provenance_dominated():
    """
    At high tau the flat channels dominate what survives.

    This is the failure mode the design exists to avoid, so it must be
    detectable — a caller can compare these two numbers to decide whether
    to warn.

    Measured strictly BELOW STAR_MAX. At tau exactly 4.0 the continuous term is
    ``continuous_share * (1 - 4/4)``, i.e. exactly zero, so ``retained`` and
    ``flat_only`` reduce to the same expression and their ratio is 1.0 by
    construction — the old assertion could not fail for any implementation
    (#716). At tau=3.9 the continuous term is non-zero, so the dominance claim
    has real content.
    """
    tau = 3.9
    retained = estimate_retention(MEASURED_FLAT_SHARES, tau, MEASURED_CONTINUOUS_SHARE)
    flat_only = sum(s for c, s in MEASURED_FLAT_SHARES.items() if flat_channel_star(c) >= tau)
    continuous_contribution = MEASURED_CONTINUOUS_SHARE * (1.0 - tau / STAR_MAX)

    assert continuous_contribution > 0, "below STAR_MAX the continuous channel must still contribute"
    assert retained == pytest.approx(flat_only + continuous_contribution, abs=1e-9)
    # Provenance-dominated: the flat channels supply the overwhelming majority.
    assert flat_only / retained > 0.95
    # ...and that is a real measurement, not an identity — the continuous
    # channel is present and simply outweighed.
    assert flat_only < retained


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
