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
entity space, i.e. what a random pair would achieve. Fold 1.0 means the
score carries no information; above 1.0 means the window is enriched for
curated agreement.

**What this measured on the real data, and why it matters.** Run against
metatraits + metatraits_gtdb + madin_etal as the gold standard, PREGO's
score is *anti*-correlated with agreement. Within the continuous channel,
fold enrichment falls monotonically from 1.61x in the lowest score quintile
to 1.17x in the highest, and the effect survives stratifying by GO term
(30 of 47 terms show it; pooled hit rate 0.180 low-half vs 0.151
high-half). The flat channels sit at exactly 1.00x — random.

So raising a threshold on ``prego_score`` selects edges that agree with
curated annotation *less* often. The threshold remains a valid **size**
lever; it is not a quality lever. See the module tests for the invariants
this implies.

Coverage is the main caveat and is deliberately reported alongside every
result: only ~1% of PREGO's taxon→GO edges are comparable, over 70 shared
GO terms. A calibration fitted on that slice should not be extrapolated to
the whole graph without a broader gold standard.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set, Tuple


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
    :return: Fold enrichment; 1.0 means no information.
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
    rows = sorted(scored, key=lambda r: r[0])
    if not rows:
        return []
    size = max(1, len(rows) // windows)
    out: List[Dict[str, float]] = []
    for i in range(windows):
        lo = i * size
        hi = len(rows) if i == windows - 1 else min(len(rows), (i + 1) * size)
        window = rows[lo:hi]
        if not window:
            continue
        rate = sum(1 for _, hit in window if hit) / len(window)
        out.append(
            {
                "window": i + 1,
                "score_min": window[0][0],
                "score_max": window[-1][0],
                "n": len(window),
                "hit_rate": rate,
                "fold": fold_enrichment(rate, baseline),
                "degenerate": window[0][0] == window[-1][0],
            }
        )
    return out


def is_monotone_increasing(results: Sequence[Dict[str, float]]) -> bool:
    """
    Return whether fold enrichment rises with score across non-degenerate windows.

    This is the property a usable confidence score must have: a higher score
    should mean a higher chance of agreeing with curated knowledge. PREGO's
    does not, which is why this predicate exists — to make the failure
    checkable rather than a matter of opinion.

    Degenerate (all-ties) windows are excluded; their ordering is arbitrary.

    :param results: Output of :func:`enrichment_by_window`.
    :return: True if fold is non-decreasing across usable windows.
    """
    folds = [r["fold"] for r in results if not r["degenerate"]]
    return all(a <= b for a, b in zip(folds, folds[1:], strict=False))
