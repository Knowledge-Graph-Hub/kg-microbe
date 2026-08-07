"""
Per-resource confidence calibration for PREGO association scores.

``prego_score`` is not one scale. PREGO's authors assign the genome-derived
channels (Isolates, Genome annotation, MAG, SAG) a flat 4-of-5 and the
BioProject/PMID rows a flat 3-of-5 — "assigned arbitrarily a confidence
level of four out of five" (Zafeiropoulos et al. 2022, §2.3) — while only
the Environmental Samples channel carries a computed, varying score. PREGO
computes no cross-channel combined score; the shared (0, 5] range is a
display convention.

So a single global cutoff is a provenance filter wearing a confidence
filter's clothes: at ``>= 4.0`` it retains 55% of edges, ~85% of which are
flat rows carrying no ordering, while deleting ~87% of the one channel
whose score actually varies.

This module implements the alternative used by the same lab for TISSUES and
DISEASES, and by STRING for its database channel: monotone per-channel
recalibration onto one shared star axis, with degenerate channels pinned to
a documented constant tier rather than score-ranked.

- Continuous channel: ``star = 4 * F_r(score)``, where ``F_r`` is the
  empirical CDF *within resource r* (MGnify / MG-RAST metagenome / MG-RAST
  amplicon each have their own marginal, so a shared CDF would conflate
  them).
- Flat channels: ``star = <author-assigned constant>``.

One user-facing knob, ``tau`` in [0, 4]: keep an edge iff ``star >= tau``.

Determinism is a requirement, not a nicety — a calibration that shifts
between runs silently changes which edges ship. Cutoffs therefore come from
fixed-width binned histograms, which are exact to the bin width, O(1) in
memory, and independent of row order. Streaming quantile sketches (t-digest,
P-square) are deliberately not used: they are order- and
implementation-dependent, so two passes over the same file in different
chunk orders can disagree.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, Mapping, Optional, Tuple

from kg_microbe.transform_utils.prego.utils import (
    CHANNEL_ENVIRONMENTAL,
    CHANNEL_GENOMES,
    CHANNEL_LITERATURE,
)

# The paper caps the Environmental Samples score at 4, but the shipped data
# reaches 4.00735 — so 4.0 is not a safe upper bound for binning. Bin to a
# hair above the observed maximum and clamp anything beyond it.
SCORE_MAX = 4.01

# Bin width 1e-4. Retention error at any tau is bounded by the mass in a
# single bin, which on the measured 23.7M-row channel is well under 0.1%.
BIN_WIDTH = 1e-4
BIN_COUNT = int(round(SCORE_MAX / BIN_WIDTH))

# Top of the star axis. Distinct from SCORE_MAX: stars are the calibrated
# output scale, SCORE_MAX is the raw input bound.
STAR_MAX = 4.0

# Author-assigned constants for the degenerate channels, from
# Zafeiropoulos et al. 2022 §2.3 and Appendix C.1. These are tiers, not
# measurements — every row in the channel carries the same value, so there
# is no within-channel ordering to threshold on.
FLAT_CHANNEL_STARS: Dict[str, float] = {
    "Isolates": 4.0,
    "Isolates GOLD": 4.0,
    "Genome annotation": 4.0,
    "Metagenome-Assembled Genome": 4.0,
    "Single Amplified Genome": 4.0,
}

# BioProject rows combine curated metadata with text mining over the linked
# abstract, which the authors score one tier lower.
PMID_CHANNEL_STAR = 3.0


def is_continuous_channel(channel: str) -> bool:
    """
    Return True for the channel whose score is computed and varies.

    This used to match the shape of an evidence tally (``402 of 487 samples``)
    because ``prego_channel`` carried PREGO's column 6 verbatim, which was a
    grab-bag of tallies, resource classes, citations and habitat names. Since
    that column now holds the archive-derived channel, the check is a direct
    comparison — and the shape-matching, which silently defined "continuous"
    for every measurement in PREGO_SCORE_VALIDATION.md, is gone.

    :param channel: Value of the ``prego_channel`` column.
    :return: True if the row's score is computed and varies within-channel.
    """
    return channel == CHANNEL_ENVIRONMENTAL


def flat_channel_star(channel: str) -> Optional[float]:
    """
    Return a constant tier for a recognised flat channel, or None.

    Only the genome/isolate channel is flat. Its rows carry a score PREGO's
    authors assigned by fiat rather than computed, so the value is already on
    the star axis and :func:`star_for_row` uses the row's own score; this
    function exists to answer "is this channel recognised", not to substitute a
    value. FLAT_CHANNEL_STARS documents the expected constants.

    :param channel: Value of the ``prego_channel`` column.
    :return: The channel's documented constant, or None if unrecognised.
    """
    if channel == CHANNEL_GENOMES:
        return 4.0
    if channel == CHANNEL_LITERATURE:
        return PMID_CHANNEL_STAR
    return None


def _bin_index(score: float) -> int:
    """
    Return the histogram bin for ``score``, clamped into range.

    :param score: Raw PREGO score.
    :return: Bin index in [0, BIN_COUNT - 1].
    """
    if not math.isfinite(score) or score <= 0.0:
        return 0
    return min(int(score / BIN_WIDTH), BIN_COUNT - 1)


class ScoreHistogram:

    """
    Fixed-width histogram of raw scores for one resource.

    Accumulates in pass 1; inverted to a cutoff in pass 2. Order-independent
    by construction, so the cutoff is a pure function of the input bytes.
    """

    def __init__(self) -> None:
        """Start an empty histogram."""
        self._bins: Dict[int, int] = {}
        self.count = 0

    def add(self, score: float) -> None:
        """
        Record one observation.

        :param score: Raw PREGO score.
        """
        idx = _bin_index(score)
        self._bins[idx] = self._bins.get(idx, 0) + 1
        self.count += 1

    def cutoff(self, tau: float) -> float:
        """
        Return the smallest raw score whose star rating is at least ``tau``.

        Solves ``4 * F(s) >= tau`` for the smallest such ``s``, where ``F``
        is the fraction of observations at or below ``s``. Filtering with
        ``score >= cutoff`` then retains approximately ``1 - tau/4`` of the
        resource.

        Ties are never split: every row sharing a bin is kept or dropped
        together, so the ~13% of rows piled at the score cap move as a unit.

        :param tau: Requested star threshold in [0, STAR_MAX].
        :return: Raw-score cutoff. 0.0 keeps everything.
        :raises ValueError: If the histogram is empty.
        """
        if self.count == 0:
            raise ValueError("cannot derive a cutoff from an empty histogram")
        if tau <= 0.0:
            return 0.0
        target = (tau / STAR_MAX) * self.count
        cumulative = 0
        for idx in sorted(self._bins):
            cumulative += self._bins[idx]
            if cumulative >= target:
                return idx * BIN_WIDTH
        return SCORE_MAX

    def cutoff_bin(self, tau: float) -> int:
        """
        Return the lowest histogram bin retained at ``tau``.

        Both the calibration table and the row filter compare against this,
        rather than one using a bin edge and the other a raw score. Those are
        not interchangeable: ``int(score / 1e-4) * 1e-4`` can exceed ``score``
        for 11.5% of representable 4-dp values — including 1.71, the measured
        p50 of the real continuous channel. Mixing the two let the table report
        a tie block as kept while the filter dropped it, a 40-point divergence
        on a constructed probe.

        :param tau: Star threshold in [0, STAR_MAX].
        :return: Bin index; 0 retains everything.
        :raises ValueError: If the histogram is empty.
        """
        if self.count == 0:
            raise ValueError("cannot derive a cutoff from an empty histogram")
        if tau <= 0.0:
            return 0
        target = (tau / STAR_MAX) * self.count
        cumulative = 0
        for idx in sorted(self._bins):
            cumulative += self._bins[idx]
            if cumulative >= target:
                return idx
        return BIN_COUNT

    def as_row(self, resource: str, tau: float) -> Dict[str, object]:
        """
        Return a serializable calibration row for this resource.

        ``kept_fraction`` is what the cutoff actually achieves, which can
        differ from the requested ``1 - tau/4`` when a large tie block
        straddles the target — reporting the realized value keeps the
        calibration table honest about that.

        :param resource: Resource name this histogram was built from.
        :param tau: Star threshold the cutoff was derived for.
        :return: Mapping of column name to value.
        """
        cut_bin = self.cutoff_bin(tau)
        cut = cut_bin * BIN_WIDTH
        kept = sum(n for idx, n in self._bins.items() if idx >= cut_bin)
        return {
            "resource": resource,
            "n": self.count,
            "tau": tau,
            "cutoff_score": f"{cut:.4f}",
            "kept_fraction": f"{kept / self.count:.6f}",
        }


def star_for_row(
    channel: str,
    score: float,
    resource: str,
    cutoffs: Mapping[str, float],
) -> Optional[float]:
    """
    Return the calibrated star rating for one edge, or None if uncalibratable.

    Flat channels return their constant tier. Continuous rows are compared
    against their resource's cutoff; because the cutoff already encodes
    ``tau``, this returns ``STAR_MAX`` for rows at or above it and 0.0 below,
    which is all the keep/drop decision needs.

    :param channel: Raw ``prego_channel`` value.
    :param score: Raw ``prego_score`` value.
    :param resource: Resource the row came from (MGnify, MG-RAST, …).
    :param cutoffs: Per-resource cutoff bin indices from :func:`build_cutoffs`.
    :return: Star rating, or None when the channel is unrecognised.
    """
    if not math.isfinite(score):
        # A non-finite score is bottom-ranked by _bin_index during
        # calibration, so retaining it here would be inconsistent: it would
        # shape the histogram as a zero yet survive every positive cutoff
        # because ``inf >= cutoff``. Rate it at the bottom in both passes.
        return 0.0
    if not is_continuous_channel(channel):
        if flat_channel_star(channel) is None:
            # Unrecognised channel. Its score may or may not be on the star
            # axis, and thresholding on semantics we have not verified is
            # how data gets dropped for the wrong reason. Decline to rate it.
            return None
        # Recognised flat channel: the score is already a star — PREGO
        # assigns these directly (4 for the genome channels, 3 for
        # BioProject/PMID). Return the row's own value rather than the
        # channel constant, so a row disagreeing with its channel's
        # documented tier is preserved as the data-quality signal it is
        # instead of being silently promoted. FLAT_CHANNEL_STARS documents
        # the expected value for validation, not for substitution.
        return score
    cut_bin = cutoffs.get(resource)
    if cut_bin is None:
        return None
    return STAR_MAX if _bin_index(score) >= cut_bin else 0.0


def keep_row(
    channel: str,
    score: float,
    resource: str,
    cutoffs: Mapping[str, float],
    tau: float,
) -> bool:
    """
    Return whether an edge survives the ``tau`` threshold.

    An unrecognised channel is kept. Dropping rows we cannot calibrate would
    silently delete data for a reason unrelated to confidence — the same
    failure this module exists to prevent.

    :param channel: Raw ``prego_channel`` value.
    :param score: Raw ``prego_score`` value.
    :param resource: Resource the row came from.
    :param cutoffs: Per-resource cutoff bin indices.
    :param tau: Star threshold in [0, STAR_MAX].
    :return: True if the edge should be emitted.
    """
    star = star_for_row(channel, score, resource, cutoffs)
    if star is None:
        return True
    return star >= tau


def build_cutoffs(histograms: Mapping[str, ScoreHistogram], tau: float) -> Dict[str, float]:
    """
    Invert per-resource histograms into per-resource raw-score cutoffs.

    :param histograms: Resource name to its accumulated histogram.
    :param tau: Star threshold in [0, STAR_MAX].
    :return: Resource name to cutoff BIN INDEX (not a raw score) — the filter
        and the calibration table must compare on the same quantity.
    :raises ValueError: If ``tau`` is outside [0, STAR_MAX].
    """
    validate_tau(tau)
    return {resource: hist.cutoff_bin(tau) for resource, hist in histograms.items()}


def validate_tau(tau: float) -> None:
    """
    Reject a threshold outside the star axis.

    Above ``STAR_MAX`` every channel drops to zero retention, which is never
    what a caller means; refusing is better than silently emitting nothing.

    :param tau: Requested threshold.
    :raises ValueError: If ``tau`` is negative or exceeds STAR_MAX.
    """
    if not math.isfinite(tau) or tau < 0.0 or tau > STAR_MAX:
        raise ValueError(f"min-confidence must be in [0, {STAR_MAX}]; got {tau!r}")


def estimate_retention(
    channel_shares: Mapping[str, float],
    tau: float,
    continuous_share: float,
) -> float:
    """
    Predict the fraction of edges retained at ``tau``, before running a filter.

    Flat channels contribute all-or-nothing at their constant tier; the
    continuous channel contributes ``1 - tau/4`` by construction of the
    percentile remap. Useful for warning that a threshold has become
    provenance-dominant.

    :param channel_shares: Flat channel name to its share of all edges (0-1).
    :param tau: Star threshold.
    :param continuous_share: Share of all edges in the continuous channel.
    :return: Predicted retained fraction in [0, 1].
    """
    validate_tau(tau)
    retained = sum(share for channel, share in channel_shares.items() if (flat_channel_star(channel) or 0.0) >= tau)
    return retained + continuous_share * (1.0 - tau / STAR_MAX)


def iter_calibration_rows(
    histograms: Mapping[str, ScoreHistogram], tau: float
) -> Iterable[Tuple[str, Dict[str, object]]]:
    """
    Yield ``(resource, row)`` calibration-table entries in deterministic order.

    :param histograms: Resource name to its accumulated histogram.
    :param tau: Star threshold the table is being generated for.
    :return: Iterable of resource name and serializable row.
    """
    for resource in sorted(histograms):
        yield resource, histograms[resource].as_row(resource, tau)
