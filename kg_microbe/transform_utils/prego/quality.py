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

The reversal is a provenance-alignment artifact, not a contradiction.
UniProt annotations come from genome annotation, and PREGO's flat channels
are genome-derived (JGI IMG, Struo-GTDB) — so they agree with each other
for reasons unrelated to whether either is right. metatraits is
trait/literature-derived and aligns better with PREGO's environmental
channel. **Each gold standard flatters the PREGO channel that shares its
provenance.** Any single-gold-standard verdict on this score should be
treated as provisional.

What both agree on: the effect is weak. Fold enrichment spans roughly
1.0–1.2x across the continuous channel's whole score range, so the score
is at best a soft quality signal, and thresholding on it is not a strong
quality lever in either direction.

Separately, the score tracks evidence volume: a GO term's edge count
correlates with its mean score at Spearman +0.26, driven by rare terms
scoring low (mean 0.67 in the lowest-ubiquity decile vs ~2.0 everywhere
above). Raising a threshold therefore strips rare, specific annotations
first — a coverage bias worth knowing about independent of quality.
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
    return all(a <= b for a, b in zip(folds, folds[1:], strict=False))
