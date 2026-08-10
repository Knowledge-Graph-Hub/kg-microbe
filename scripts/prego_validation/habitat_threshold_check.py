"""
Cost of each habitat score threshold, in coverage and in specificity.

``fold_enrichment_envo.py`` answers "does precision improve as tau rises?" using
the BacDive isolation gold. It cannot answer "what do we lose?", because a
positive-only standard cannot enumerate the true edges a threshold discards.
This script measures the losses that *are* observable without a gold standard:

* how many edges, distinct habitat terms and distinct taxa survive;
* whether the survivors are the specific habitats or the ubiquitous ones.

The second is the question ``ubiquity_check.py`` raises. For GO the score rises
steeply out of the rare deciles and then flattens, so raising tau strips the
rare, informative annotations first. Whether habitat terms behave the same way
determines whether a habitat threshold is safe, and the answer is not
transferable between shapes.

Term degree is distinct taxa, not edge count: MG-RAST contributes both amplicon
and metagenome studies, so one (term, taxon) pair can appear twice.

Usage:

    python habitat_threshold_check.py [--shape {envo,bto}] [--edges PATH]
"""

import argparse
import statistics
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from channel_compat import assert_non_empty, continuous_predicate

THRESHOLDS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
PREFIX = {"envo": "ENVO:", "bto": "BTO:"}


def parse_args() -> argparse.Namespace:
    """
    Parse the command line.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shape", choices=sorted(PREFIX), default="envo", help="habitat vocabulary (default: envo)")
    parser.add_argument("--edges", default="data/transformed/prego/edges.tsv", help="path to edges.tsv")
    return parser.parse_args()


def load(path: str, prefix: str) -> Tuple[List[Tuple[str, str, float]], str]:
    """
    Read every continuous-channel habitat edge.

    :param path: Path to ``edges.tsv``.
    :param prefix: CURIE prefix of the habitat vocabulary.
    :return: ``(rows, layout)`` where each row is ``(term, taxon, score)``.
    """
    rows: List[Tuple[str, str, float]] = []
    with open(path) as handle:
        header = next(handle).rstrip("\n").split("\t")
        subject_i, object_i = header.index("subject"), header.index("object")
        score_i = header.index("prego_score")
        is_continuous, layout = continuous_predicate(header)
        n_continuous = 0
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= score_i:
                continue
            if not (fields[subject_i].startswith(prefix) and fields[object_i].startswith("NCBITaxon:")):
                continue
            if not is_continuous(fields):
                continue
            n_continuous += 1
            try:
                rows.append((fields[subject_i], fields[object_i], float(fields[score_i])))
            except ValueError:
                continue
    assert_non_empty(n_continuous, layout)
    return rows, layout


def degrees(rows: List[Tuple[str, str, float]]) -> Dict[str, int]:
    """
    Distinct-taxon degree per habitat term, over the unfiltered edge set.

    Computed once on the full set so that "specificity of what survives" is
    measured against a fixed notion of how ubiquitous each term is. Recomputing
    degree inside each threshold would make the baseline move with the filter.

    :param rows: ``(term, taxon, score)`` tuples.
    :return: Term to distinct-taxon count.
    """
    taxa: Dict[str, Set[str]] = defaultdict(set)
    for term, taxon, _ in rows:
        taxa[term].add(taxon)
    return {term: len(t) for term, t in taxa.items()}


def main() -> None:
    """Print the retention and specificity table across thresholds."""
    args = parse_args()
    rows, layout = load(args.edges, PREFIX[args.shape])
    degree = degrees(rows)
    total_edges = len(rows)
    total_terms = len(degree)
    total_taxa = len({taxon for _, taxon, _ in rows})

    print(f"  layout: {layout}")
    print(f"  {args.shape.upper()} continuous-channel edges: {total_edges:,}")
    print(f"  distinct terms: {total_terms:,}   distinct taxa: {total_taxa:,}\n")
    print(
        f"  {'>= tau':>7} {'edges':>10} {'kept':>7} {'terms':>7} {'kept':>7} "
        f"{'taxa':>8} {'kept':>7} {'median term degree':>19}"
    )
    for tau in THRESHOLDS:
        kept = [r for r in rows if r[2] >= tau]
        if not kept:
            print(f"  {tau:>7.1f} {0:>10,} {0.0:>6.1f}% {0:>7,} {0.0:>6.1f}% {0:>8,} {0.0:>6.1f}% {'-':>19}")
            continue
        terms = {r[0] for r in kept}
        taxa = {r[1] for r in kept}
        # Degree of the term each surviving edge belongs to: the ubiquity of what
        # the threshold actually keeps, weighted by how much of it there is.
        median_degree = statistics.median(degree[r[0]] for r in kept)
        print(
            f"  {tau:>7.1f} {len(kept):>10,} {100 * len(kept) / total_edges:>6.1f}% "
            f"{len(terms):>7,} {100 * len(terms) / total_terms:>6.1f}% "
            f"{len(taxa):>8,} {100 * len(taxa) / total_taxa:>6.1f}% {median_degree:>19,.0f}"
        )
    print(
        "\n  median term degree rising with tau => the threshold preferentially keeps\n"
        "  ubiquitous habitats; flat or falling => specific habitats survive too."
    )


if __name__ == "__main__":
    main()
