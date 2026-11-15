"""
Test whether PREGO's score measures ubiquity rather than confidence.

Hypothesis: the environmental-samples score rewards co-occurrence frequency,
so a term attached to many taxa (generic, ubiquitous) scores higher than a
specific one. If true, thresholding up selects generic annotations.

Prediction: within the continuous channel, a term's taxon degree should
correlate POSITIVELY with its mean score.

Runs over GO, ENVO, BTO, or FOODON continuous-channel edge shapes. The GO shape was
measured first and its numbers are published; ``--shape go --degree edges``
reproduces them exactly.

Two things differ by shape and are easy to get silently wrong:

* **Orientation.** For GO the taxon is the *subject* and the term the object
  (``NCBITaxon -capable_of-> GO``). Habitat terms are the subject in legacy
  ``location_of`` edges and the object in current ``located_in`` edges; both
  are read as the same term/taxon pair. Reading the wrong column
  measures taxon degree instead of term degree — a different quantity that
  answers a different question, with no error to notice.
* **Degree.** The original run approximated distinct taxa by edge count. That
  holds only while one (term, taxon) pair appears once. It does not hold for
  the habitat shapes: MG-RAST contributes both amplicon and metagenome studies,
  so a pair can be reported twice and edge count overstates degree.

Usage:

    python ubiquity_check.py [--shape {go,envo,bto,foodon}] [--degree {taxa,edges}]
                             [--min-edges N] [--edges PATH]
"""

import argparse
from collections import defaultdict
from typing import Callable, Dict, List, Set, Tuple

if __package__:
    from .channel_compat import assert_non_empty, continuous_predicate
    from .habitat_compat import habitat_pair
else:
    from channel_compat import assert_non_empty, continuous_predicate
    from habitat_compat import habitat_pair

# shape -> (term prefix, taxon prefix, legacy term column); habitat views accept both directions
SHAPES = {
    "go": ("GO:", "NCBITaxon:", "object"),
    "envo": ("ENVO:", "NCBITaxon:", "subject"),
    "bto": ("BTO:", "NCBITaxon:", "subject"),
    "foodon": ("FOODON:", "NCBITaxon:", "subject"),
}


def parse_args() -> argparse.Namespace:
    """
    Parse the command line.

    :return: Parsed arguments, with ``degree`` defaulted per shape.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shape", choices=sorted(SHAPES), default="go", help="edge shape to measure (default: go)")
    parser.add_argument(
        "--degree",
        choices=("taxa", "edges"),
        default=None,
        help=(
            "how to count a term's degree: distinct taxa, or rows. Default is 'edges' for go, "
            "which reproduces the published run, and 'taxa' otherwise."
        ),
    )
    parser.add_argument(
        "--min-edges", type=int, default=50, help="minimum continuous-channel edges per term (default: 50)"
    )
    parser.add_argument("--edges", default="data/transformed/prego/edges.tsv", help="path to edges.tsv")
    args = parser.parse_args()
    if args.degree is None:
        args.degree = "edges" if args.shape == "go" else "taxa"
    return args


def accumulate(path: str, shape: str) -> Tuple[Dict[str, Set[str]], Dict[str, int], Dict[str, float], str]:
    """
    Scan ``edges.tsv`` once, collecting per-term taxa, edge counts and score sums.

    :param path: Path to ``edges.tsv``.
    :param shape: Key into :data:`SHAPES`.
    :return: ``(taxa_by_term, edges_by_term, score_sum_by_term, layout)``.
    """
    term_prefix, taxon_prefix, term_col = SHAPES[shape]
    taxa: Dict[str, Set[str]] = defaultdict(set)
    edges: Dict[str, int] = defaultdict(int)
    total: Dict[str, float] = defaultdict(float)
    with open(path) as handle:
        header = next(handle).rstrip("\n").split("\t")
        subject_i, object_i = header.index("subject"), header.index("object")
        predicate_i = header.index("predicate")
        score_i = header.index("prego_score")
        is_continuous, layout = continuous_predicate(header)
        term_i, taxon_i = (subject_i, object_i) if term_col == "subject" else (object_i, subject_i)
        n_continuous = 0
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < len(header):
                continue
            if shape == "go":
                term, taxon = fields[term_i], fields[taxon_i]
                if not (term.startswith(term_prefix) and taxon.startswith(taxon_prefix)):
                    continue
            else:
                pair = habitat_pair(fields[subject_i], fields[predicate_i], fields[object_i], (term_prefix,))
                if pair is None:
                    continue
                term, taxon = pair
            if not is_continuous(fields):
                continue
            n_continuous += 1
            try:
                score = float(fields[score_i])
            except ValueError:
                continue
            taxa[term].add(taxon)
            edges[term] += 1
            total[term] += score
    assert_non_empty(n_continuous, layout)
    return taxa, edges, total, layout


def spearman(rows: List[Tuple[int, float, str]]) -> float:
    """
    Rank correlation between each row's degree and its mean score.

    :param rows: Sequence of ``(degree, mean_score, term)`` tuples.
    :return: Spearman's rho, or 0.0 when it is undefined.
    """
    n = len(rows)
    by_degree = sorted(range(n), key=lambda i: rows[i][0])
    by_score = sorted(range(n), key=lambda i: rows[i][1])
    rank_d, rank_s = [0] * n, [0] * n
    for rank, i in enumerate(by_degree):
        rank_d[i] = rank
    for rank, i in enumerate(by_score):
        rank_s[i] = rank
    mean = (n - 1) / 2
    num = sum((rank_d[i] - mean) * (rank_s[i] - mean) for i in range(n))
    den = (sum((rank_d[i] - mean) ** 2 for i in range(n)) * sum((rank_s[i] - mean) ** 2 for i in range(n))) ** 0.5
    return num / den if den else 0.0


def report(rows: List[Tuple[int, float, str]], label: str) -> None:
    """
    Print the ubiquity decile table.

    :param rows: ``(degree, mean_score, term)`` tuples, sorted by degree.
    :param label: Shape name for the header.
    """
    print(f"  {'ubiquity decile':>15} {'degree range':>22} {'terms':>7} {'mean score':>11}")
    width = max(1, len(rows) // 10)
    for decile in range(10):
        lo, hi = decile * width, (decile + 1) * width if decile < 9 else len(rows)
        window = rows[lo:hi]
        if not window:
            continue
        mean_score = sum(r[1] for r in window) / len(window)
        print(f"  {decile + 1:>15} {window[0][0]:>9,}-{window[-1][0]:<11,} {len(window):>7,} {mean_score:>10.3f}")
    print(f"\n  Spearman rank correlation ({label} degree vs mean score): {spearman(rows):+.4f}")
    print("    positive => score tracks ubiquity, supporting the hypothesis")


def main() -> None:
    """Run the ubiquity check and print the decile table plus the correlation."""
    args = parse_args()
    taxa, edges, total, layout = accumulate(args.edges, args.shape)
    label = args.shape.upper()
    degree_of: Callable[[str], int] = (
        (lambda term: len(taxa[term])) if args.degree == "taxa" else (lambda term: edges[term])
    )

    rows = [(degree_of(t), total[t] / edges[t], t) for t in edges if edges[t] >= args.min_edges]
    rows.sort()
    print(f"  layout: {layout}")
    described = "distinct taxa" if args.degree == "taxa" else "edge count"
    print(f"  degree measured as: {described}")
    if rows and args.degree == "taxa":
        # Quantifies what the edge-count approximation would have overstated.
        counted = sum(edges[t] for _, _, t in rows)
        distinct = sum(len(taxa[t]) for _, _, t in rows)
        print(f"  edges per distinct taxon over these terms: {counted / max(1, distinct):.3f}x")
    print(f"  {label} terms with >={args.min_edges} continuous-channel edges: {len(rows):,}\n")
    if not rows:
        raise SystemExit(f"no {label} terms cleared --min-edges {args.min_edges}; nothing to report.")
    report(rows, label)


if __name__ == "__main__":
    main()
