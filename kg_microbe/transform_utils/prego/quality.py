"""
Fold-enrichment measurement for PREGO association scores.

The percentile calibration in :mod:`calibration` equalizes **rank**: at
``min-confidence 2.0`` it keeps the top half of each resource. It makes no
claim about quality, because nothing anchors it to an external truth.

TISSUES closes that gap by calibrating against a gold standard — "we select
the genes and tissues that are in common between the dataset and the gold
standard, sort the gene–tissue pairs by raw expression value and calculate
fold enrichment in sliding windows of 100 pairs" (Palasca et al. 2018). This
module is the equivalent measurement for taxon→GO associations.

    fold enrichment = P(pair in gold | pair in window) / P(pair in gold)

where the denominator is the density of the gold standard over the shared
entity space. Fold 1.0 means the window matches that baseline — **not**
that the score carries no information, since the baseline weights every
subject x object cell equally and so controls for neither taxon annotation
depth nor GO-term ubiquity. A degree-preserving null would be a stronger
test and is not implemented here.

**What this measured, and why the answer depends on the gold standard.**
Two were tried, and they disagree — which is the most important result
here.

Against **UniProt proteome annotations** (14.4M taxon→GO pairs derived
from ``kg-microbe-function``; 4,209 GO terms, 41% of PREGO's taxon→GO
edges comparable), fold enrichment *rises* with score across the
continuous channel: 0.94x → 0.96x → 1.04x → 1.19x. The flat channels sit
at 2.19x.

Against **metatraits + madin_etal** (trait-derived; 78 GO terms, ~1%
comparable), it *falls*: 1.61x → 1.59x → 1.56x, with the flat channels at
1.00x.

The leading *hypothesis* for the reversal is provenance alignment, which is
not established: UniProt annotations come from genome annotation and PREGO's
flat channels are genome-derived (JGI IMG, Struo-GTDB), so their agreement
may reflect a shared source rather than either being right. metatraits is
trait/literature-derived. Testing this needs a source-overlap exclusion and
a degree-matched comparison; until then treat the UniProt figure for the
genome channels as provenance agreement rather than quality, and treat any
single-gold-standard verdict as provisional.

Effect sizes, stated per benchmark rather than pooled: against UniProt the
continuous channel spans 0.94x-1.19x; against the trait-derived standard it
spans 1.56x-1.61x. Neither range is accompanied by an uncertainty estimate.
The observations are not independent — edges reuse the same taxa, GO terms
and resources — so clustered intervals are needed before any ordering of
these point estimates is called directional.

**Status of the predicate hypothesis: NOT ESTABLISHED.** An earlier version of
this docstring stated that the score discriminates on ``location_of`` edges and
not on ``capable_of`` ones, citing 1.57x (18/19 ENVO terms) and 1.94x (7/9 BTO
terms). Those figures came from a within-term split that used an index median
and therefore split tied scores; tie-safe boundaries give 1.49x (18/20) and
1.69x (6/8). BTO is also not an independent replication — it projects the same
BacDive isolation source as ENVO.

Under matched taxa *and* matched label policy the contrast largely dissolves:
interaction +0.281, two-way clustered 95% CI [-0.237, +0.624], 82.5% one-sided.
Both predicates show weak positive discrimination (1.40 and 1.12) and the
difference between them is not distinguishable from zero.

See ``docs/PREGO_SCORE_VALIDATION.md`` for the full record, including the
corrections list. Do not cite the withdrawn figures.

Separately, the score tracks evidence volume: a GO term's edge count
correlates with its mean score at Spearman +0.26, driven by rare terms
scoring low (mean 0.67 in the lowest-ubiquity decile vs ~2.0 everywhere
above). Raising a threshold therefore strips rare, specific annotations
first — a coverage bias worth knowing about independent of quality.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


class GoldStandard:
    """
    A set of curated ``(subject, object)`` pairs plus the entity space it covers.

    The entity sets matter as much as the pairs: fold enrichment is only
    meaningful over subjects and objects the gold standard actually knows
    about. Scoring a pair whose object the gold standard has never seen
    would count as a miss for a reason that has nothing to do with quality.
    """

    def __init__(self, pairs: Iterable[Tuple[str, str]]) -> None:
        """
        Build a gold standard from curated pairs.

        :param pairs: Iterable of ``(subject, object)`` CURIE pairs.
        """
        self.pairs: Set[Tuple[str, str]] = set(pairs)
        self.subjects: Set[str] = {s for s, _ in self.pairs}
        self.objects: Set[str] = {o for _, o in self.pairs}

    def covers(self, subject: str, object_: str) -> bool:
        """
        Return whether both endpoints are inside the gold standard's entity space.

        :param subject: Subject CURIE.
        :param object_: Object CURIE.
        :return: True if the pair is comparable.
        """
        return subject in self.subjects and object_ in self.objects

    def contains(self, subject: str, object_: str) -> bool:
        """
        Return whether the gold standard asserts this pair.

        :param subject: Subject CURIE.
        :param object_: Object CURIE.
        :return: True if the pair is a curated hit.
        """
        return (subject, object_) in self.pairs

    def baseline(self, subjects: Set[str], objects: Set[str]) -> float:
        """
        Return the density of the gold standard over a shared entity space.

        This is the rate a random pair drawn from ``subjects x objects``
        would hit, and the denominator of every fold-enrichment figure.

        :param subjects: Subjects shared with the dataset under test.
        :param objects: Objects shared with the dataset under test.
        :return: Expected hit rate in [0, 1]; 0.0 if the space is empty.
        :raises ValueError: If either shared set is empty.
        """
        universe = len(subjects) * len(objects)
        if universe == 0:
            raise ValueError("no shared entities; fold enrichment is undefined")
        hits = sum(1 for s, o in self.pairs if s in subjects and o in objects)
        return hits / universe


def fold_enrichment(hit_rate: float, baseline: float) -> float:
    """
    Return enrichment of an observed hit rate over the random expectation.

    :param hit_rate: Observed fraction of pairs that are curated hits.
    :param baseline: Expected fraction for a random pair.
    :return: Fold enrichment relative to ``baseline``; 1.0 matches it.
    :raises ValueError: If ``baseline`` is not positive.
    """
    if baseline <= 0:
        raise ValueError("baseline must be positive to compute fold enrichment")
    return hit_rate / baseline


def enrichment_by_window(
    scored: Sequence[Tuple[float, bool]],
    baseline: float,
    windows: int = 5,
) -> List[Dict[str, float]]:
    """
    Return fold enrichment per equal-count score window, ascending by score.

    Equal-count windows rather than equal-width: PREGO's scores pile up at
    the cap, so equal-width bins would put most of the mass in one bin and
    measure nothing.

    A window whose score range is a single value is flagged via ``degenerate``.
    Such a window is an arbitrary slice of tied rows — its hit rate reflects
    whatever order the ties arrived in, not the score — so it must not be
    read as signal.

    :param scored: ``(score, is_hit)`` pairs; sorted internally.
    :param baseline: Random-expectation hit rate.
    :param windows: Number of equal-count windows.
    :return: One dict per window with score bounds, n, hit rate, and fold.
    :raises ValueError: If ``windows`` is not positive.
    """
    if windows <= 0:
        raise ValueError("windows must be positive")
    if not scored:
        return []
    # Aggregate by exact score first. Slicing a sorted list by index splits a
    # tie block across the boundary, and then *which* tied rows land either
    # side is decided by the sort's tiebreak rather than by the score. That
    # is not hypothetical: an earlier ad-hoc analysis sorted (score, is_hit)
    # tuples, which pushed every non-hit to the low side of the 4.0 block and
    # every hit to the high side, manufacturing a 0.44x window next to a
    # 1.95x one out of pure ordering. Windows must break only where the score
    # actually changes.
    by_score: Dict[float, List[int]] = {}
    for score, hit in scored:
        slot = by_score.setdefault(score, [0, 0])
        slot[0] += 1
        slot[1] += 1 if hit else 0

    total = sum(v[0] for v in by_score.values())
    target = total / windows
    out: List[Dict[str, float]] = []
    n = h = 0
    lo = hi = None
    for score in sorted(by_score):
        count, hits = by_score[score]
        if lo is None:
            lo = score
        hi = score
        n += count
        h += hits
        if n >= target and len(out) < windows - 1:
            rate = h / n
            out.append(
                {
                    "window": len(out) + 1,
                    "score_min": lo,
                    "score_max": hi,
                    "n": n,
                    "hit_rate": rate,
                    "fold": fold_enrichment(rate, baseline),
                    "degenerate": lo == hi,
                }
            )
            n = h = 0
            lo = None
    if n:
        rate = h / n
        out.append(
            {
                "window": len(out) + 1,
                "score_min": lo,
                "score_max": hi,
                "n": n,
                "hit_rate": rate,
                "fold": fold_enrichment(rate, baseline),
                "degenerate": lo == hi,
            }
        )
    return out


def is_monotone_increasing(results: Sequence[Dict[str, float]]) -> bool:
    """
    Return whether fold enrichment rises with score across non-degenerate windows.

    This is the property a usable confidence score must have: a higher score
    should mean a higher chance of agreeing with curated knowledge. Whether
    PREGO's has it depends on the gold standard — rising against UniProt,
    falling against metatraits — so this predicate exists to make the
    question checkable per gold standard rather than a matter of opinion.

    Degenerate (all-ties) windows are excluded; their ordering is arbitrary.

    :param results: Output of :func:`enrichment_by_window`.
    :return: True if fold is non-decreasing across usable windows.
    """
    folds = [r["fold"] for r in results if not r["degenerate"]]
    if len(folds) < 2:
        # Fewer than two usable windows means there is no comparison to make.
        # Returning True here would report a fully tied channel — which has no
        # score ordering at all — as monotonically increasing, because
        # ``all()`` over an empty sequence is vacuously true.
        return False
    return all(a <= b for a, b in zip(folds, folds[1:], strict=False))


# ---------------------------------------------------------------------------
# Labelled evidence — precision measurement.
#
# Fold enrichment needs a null model, and the uniform subject x object null
# used above controls for neither taxon annotation depth nor term ubiquity.
# Where labelled *negatives* exist that problem disappears: precision is
# measured directly against the empirical base rate, with nothing assumed
# about how pairs are drawn.
#
# KG-Microbe has such labels. BacDive records assay outcomes with polarity —
# METPO:2000302 "shows activity of" and METPO:2000303 "does not show activity
# of" — so chaining strain -> assay -> GO and lifting strain to NCBITaxon
# yields positives and negatives from wet-lab phenotype tests, provenance-
# disjoint from both genome annotation and trait curation.
# ---------------------------------------------------------------------------


class LabelledEvidence:
    """
    Positive/negative labels for ``(subject, object)`` pairs.

    Unlike :class:`GoldStandard`, which only knows which pairs are asserted,
    this knows which are asserted *false*. That is what makes precision
    measurable without a null model.
    """

    def __init__(self, positives: Iterable[Tuple[str, str]], negatives: Iterable[Tuple[str, str]]) -> None:
        """
        Build labelled evidence from disjoint positive and negative pairs.

        :param positives: Pairs the evidence asserts hold.
        :param negatives: Pairs the evidence asserts do not hold.
        :raises ValueError: If a pair appears in both, which would make its
            label ambiguous rather than merely unknown.
        """
        self.positives: Set[Tuple[str, str]] = set(positives)
        self.negatives: Set[Tuple[str, str]] = set(negatives)
        overlap = self.positives & self.negatives
        if overlap:
            raise ValueError(
                f"{len(overlap)} pair(s) labelled both positive and negative; "
                "resolve or exclude conflicting evidence before constructing"
            )

    def label(self, subject: str, object_: str) -> Optional[bool]:
        """
        Return True, False, or None when the pair is unlabelled.

        :param subject: Subject CURIE.
        :param object_: Object CURIE.
        :return: The label, or None if this evidence says nothing about the pair.
        """
        key = (subject, object_)
        if key in self.positives:
            return True
        if key in self.negatives:
            return False
        return None

    def base_rate(self) -> float:
        """
        Return the fraction of labelled pairs that are positive.

        This is the precision a selector achieves by picking labelled pairs at
        random, and the only reference point precision needs — it is measured,
        not modelled.

        :return: Base rate in [0, 1].
        :raises ValueError: If there are no labelled pairs.
        """
        total = len(self.positives) + len(self.negatives)
        if total == 0:
            raise ValueError("no labelled pairs; base rate is undefined")
        return len(self.positives) / total


def precision_by_window(
    scored: Sequence[Tuple[float, bool]],
    windows: int = 5,
) -> List[Dict[str, float]]:
    """
    Return precision per equal-count score window, ascending by score.

    Precision is the fraction of labelled edges in the window whose label is
    positive. Compare against :meth:`LabelledEvidence.base_rate`; a score that
    discriminates produces windows rising above it.

    Windows break only where the score changes, for the same reason as
    :func:`enrichment_by_window` — an index-based slice would let the sort's
    tiebreak decide which tied rows land in which window.

    :param scored: ``(score, is_positive)`` pairs for labelled edges only.
    :param windows: Number of equal-count windows.
    :return: One dict per window with score bounds, n, precision, degenerate.
    :raises ValueError: If ``windows`` is not positive.
    """
    results = enrichment_by_window(scored, baseline=1.0, windows=windows)
    for row in results:
        # enrichment_by_window with baseline 1.0 makes `fold` the raw rate.
        row["precision"] = row.pop("fold")
        row.pop("hit_rate", None)
    return results


def lift(precision: float, base_rate: float) -> float:
    """
    Return precision relative to the measured base rate.

    Distinct from :func:`fold_enrichment` in that the denominator is observed
    rather than derived from a uniform-cell null, so it carries none of that
    null's assumptions about how pairs are drawn.

    :param precision: Observed precision.
    :param base_rate: Fraction of labelled pairs that are positive.
    :return: Lift; 1.0 means no better than picking labelled pairs at random.
    :raises ValueError: If ``base_rate`` is not positive.
    """
    if base_rate <= 0:
        raise ValueError("base rate must be positive to compute lift")
    return precision / base_rate
