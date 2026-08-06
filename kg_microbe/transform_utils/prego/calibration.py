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
    Return True when ``channel`` is the computed-score (Environmental Samples) channel.

    Identified by shape rather than by name: these rows carry an evidence
    tally such as ``402 of 487 samples`` in the channel column. The column
    is a grab-bag upstream (see the prego_channel issue), so matching the
    tally shape is more robust than enumerating channel names.

    :param channel: Raw value of the ``prego_channel`` column.
    :return: True if the row's score is computed and varies within-channel.
    """
    if not channel:
        return False
    parts = channel.split()
    return len(parts) == 4 and parts[1] == "of" and parts[3] == "samples" and parts[0].isdigit()


def flat_channel_star(channel: str) -> Optional[float]:
    """
    Return the constant star tier for a degenerate channel, or None.

    :param channel: Raw value of the ``prego_channel`` column.
    :return: The author-assigned constant, or None if the channel is not a
        recognised flat channel.
    """
    if not channel:
        return None
    if channel.startswith("PMID:"):
        return PMID_CHANNEL_STAR
    for prefix, star in FLAT_CHANNEL_STARS.items():
        if channel.startswith(prefix):
            return star
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
        cut = self.cutoff(tau)
        kept = sum(n for idx, n in self._bins.items() if idx * BIN_WIDTH >= cut)
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
    :param cutoffs: Per-resource raw-score cutoffs from :func:`build_cutoffs`.
    :return: Star rating, or None when the channel is unrecognised.
    """
    flat = flat_channel_star(channel)
    if flat is not None:
        return flat
    if not is_continuous_channel(channel):
        return None
    cut = cutoffs.get(resource)
    if cut is None:
        return None
    return STAR_MAX if score >= cut else 0.0


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
    :param cutoffs: Per-resource raw-score cutoffs.
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
    :return: Resource name to raw-score cutoff.
    :raises ValueError: If ``tau`` is outside [0, STAR_MAX].
    """
    validate_tau(tau)
    return {resource: hist.cutoff(tau) for resource, hist in histograms.items()}


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
