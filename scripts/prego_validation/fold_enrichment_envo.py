"""
Fold enrichment of PREGO ``ENVO -location_of-> NCBITaxon`` vs a habitat gold standard.

Prints the threshold curve (overlap and retention at candidate cutoffs) and the
within-ENVO-term stratified ratio, which is what controls for term degree — the
raw fold numbers do not (see #698).

Two gold standards, measured by identical methodology so the numbers are
directly comparable:

``--gold bacdive``
    BacDive isolation records, ``ENVO -location_of-> strain`` lifted to taxon via
    ``strain -subclass_of-> NCBITaxon``. The published run.

``--gold madin``
    Madin et al. condensed traits, already ``ENVO -location_of-> NCBITaxon``.
    **Provenance-disjoint from BacDive**: counting distinct
    ``(taxon, isolation_source)`` pairs — the basis closest to what is emitted —
    BacDive contributes 1,248 of 69,430, about **1.8%** (the raw-row share is
    lower, 1,336 of 172,324 = 0.78%, because BacDive rows are less duplicated
    than the bulk GOLD rows). Treat 1.8% as an upper-bound estimate: the mapping
    from raw rows to emitted ENVO edges is many-to-many. The bulk is GOLD (52%),
    PATRIC (10%), engqvist (7%) and GenBank (7%). That makes it the first
    habitat standard that is not a re-projection of the one PREGO was originally
    scored against — the gap named in the "confounds that limit the verdict"
    section of the findings doc, where BTO was rejected as a replication because
    it projects the same BacDive isolation records as ENVO.

Both standards are **positive-only**: an absent pair is *unknown*, not false. The
column labelled overlap is therefore an overlap rate, not precision. Only the
BacDive assay standard (GO shape) carries negatives.

Usage:

    python fold_enrichment_envo.py [--gold {bacdive,madin}] [--prego PATH]
"""

import argparse
import bisect
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from channel_compat import continuous_predicate

THRESHOLDS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
GOLD_SOURCES = {
    "bacdive": "data/transformed/bacdive/edges.tsv",
    "madin": "data/transformed/madin_etal/edges.tsv",
}


def parse_args() -> argparse.Namespace:
    """
    Parse the command line.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--gold", choices=sorted(GOLD_SOURCES), default="bacdive", help="habitat gold standard (default: bacdive)"
    )
    parser.add_argument("--gold-edges", default=None, help="override the gold edges.tsv path")
    parser.add_argument("--prego", default="data/transformed/prego/edges.tsv", help="path to PREGO edges.tsv")
    parser.add_argument(
        "--min-term-edges", type=int, default=100, help="minimum comparable edges for within-term stratification"
    )
    parser.add_argument(
        "--channel",
        choices=("any", "continuous", "genome"),
        default="any",
        help=(
            "restrict PREGO edges by channel. Required for an honest independence claim against "
            "--gold madin: PREGO's genome-channel habitat edges are all JGI IMG, and 52%% of Madin's "
            "isolation rows come from GOLD, which is also JGI. Scoring those against each other is "
            "circular, and they are 53%% of everything retained at tau>=3. 'continuous' keeps only the "
            "MG-RAST/MGnify edges, which share no provenance with GOLD."
        ),
    )
    return parser.parse_args()


def load_gold_bacdive(path: str) -> Set[Tuple[str, str]]:
    """
    Build ``(ENVO, taxon)`` pairs from BacDive isolation records.

    BacDive records isolation against a *strain*, so each pair is lifted to the
    strain's parent taxon. Pairs whose strain has no taxon edge are dropped.

    :param path: Path to the BacDive ``edges.tsv``.
    :return: Set of ``(ENVO CURIE, NCBITaxon CURIE)`` pairs.
    """
    strain_taxon: Dict[str, str] = {}
    env_strain: List[Tuple[str, str]] = []
    with open(path) as handle:
        next(handle)
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            subject, predicate, obj = fields[0], fields[1], fields[2]
            if subject.startswith("kgmicrobe.strain:") and predicate == "biolink:subclass_of":
                if obj.startswith("NCBITaxon:"):
                    strain_taxon[subject] = obj
            elif subject.startswith("ENVO:") and predicate == "biolink:location_of":
                if obj.startswith("kgmicrobe.strain:"):
                    env_strain.append((subject, obj))
    return {(env, strain_taxon[strain]) for env, strain in env_strain if strain in strain_taxon}


def load_gold_madin(path: str) -> Set[Tuple[str, str]]:
    """
    Build ``(ENVO, taxon)`` pairs from Madin et al. condensed traits.

    Already taxon-level, so no strain lifting is needed — one fewer step than
    BacDive, and one fewer place for the two standards to diverge for reasons
    unrelated to their content.

    :param path: Path to the madin_etal ``edges.tsv``.
    :return: Set of ``(ENVO CURIE, NCBITaxon CURIE)`` pairs.
    """
    gold: Set[Tuple[str, str]] = set()
    with open(path) as handle:
        next(handle)
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            subject, predicate, obj = fields[0], fields[1], fields[2]
            if subject.startswith("ENVO:") and predicate == "biolink:location_of":
                if obj.startswith("NCBITaxon:"):
                    gold.add((subject, obj))
    return gold


def main() -> None:
    """Measure fold enrichment and the within-term stratified ratio."""
    args = parse_args()
    gold_path = args.gold_edges or GOLD_SOURCES[args.gold]
    loader = load_gold_bacdive if args.gold == "bacdive" else load_gold_madin
    gold = loader(gold_path)
    if not gold:
        raise SystemExit(f"no ENVO->taxon pairs found in {gold_path}; refusing to report on an empty gold standard.")
    gold_env = {e for e, _ in gold}
    gold_tax = {t for _, t in gold}
    print(f"  gold ({args.gold}): {len(gold):,} ENVO->taxon pairs ({len(gold_env):,} ENVO, {len(gold_tax):,} taxa)")
    print(f"  prego channel filter: {args.channel}")

    labelled: List[Tuple[float, bool]] = []
    all_scores: List[float] = []
    per_term: Dict[str, List[Tuple[float, bool]]] = defaultdict(list)
    shared_env: Set[str] = set()
    shared_tax: Set[str] = set()
    with open(args.prego) as handle:
        header = next(handle).rstrip("\n").split("\t")
        si, oi = header.index("subject"), header.index("object")
        sci = header.index("prego_score")
        chi = header.index("prego_channel")
        # Layout-aware, via the shared helper. A hand-rolled `prego_channel ==
        # "environmental_samples"` is valid only post-#703, and on a pre-#703 file
        # it selects nothing — reporting "no comparable edges" for a file that is
        # entirely comparable. That is the exact failure channel_compat exists to
        # prevent; three scripts had already been caught by it.
        is_continuous, layout = continuous_predicate(header)
        if args.channel == "genome" and "prego_evidence" not in header:
            raise SystemExit(
                f"--channel genome needs the post-#703 layout; this file is {layout}. "
                "Re-run against a current edges.tsv, or use --channel any."
            )
        keep = {
            "any": lambda f: True,
            "continuous": is_continuous,
            "genome": lambda f: f[chi] == "annotated_genomes_isolates",
        }[args.channel]
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= max(sci, chi):
                continue
            subject, obj = fields[si], fields[oi]
            if not (subject.startswith("ENVO:") and obj.startswith("NCBITaxon:")):
                continue
            if not keep(fields):
                continue
            try:
                score = float(fields[sci])
            except ValueError:
                continue
            all_scores.append(score)
            if subject in gold_env:
                shared_env.add(subject)
            if obj in gold_tax:
                shared_tax.add(obj)
            if subject in gold_env and obj in gold_tax:
                hit = (subject, obj) in gold
                labelled.append((score, hit))
                per_term[subject].append((score, hit))

    if not labelled:
        raise SystemExit("no PREGO edges are comparable to this gold standard; nothing to report.")

    # Baseline over the SHARED entity space, per the TISSUES protocol.
    base = sum(1 for e, t in gold if e in shared_env and t in shared_tax) / (len(shared_env) * len(shared_tax))
    labelled.sort()
    all_scores.sort()
    n_all = len(all_scores)
    print(f"  comparable {len(labelled):,} of {n_all:,} ENVO edges | baseline {base:.5f}\n")
    print(f"  {'>= T':>6} {'overlap':>10} {'fold':>8} {'kept':>10} {'kept %':>8}")
    for threshold in THRESHOLDS:
        sub = [hit for score, hit in labelled if score >= threshold]
        if not sub:
            continue
        rate = sum(sub) / len(sub)
        kept = n_all - bisect.bisect_left(all_scores, threshold)
        print(f"  {threshold:>6.2f} {rate:>10.4f} {rate / base:>7.2f}x {kept:>10,} {100 * kept / n_all:>7.2f}%")

    up = dn = lo_hits = lo_n = hi_hits = hi_n = 0
    for _term, rows in per_term.items():
        if len(rows) < args.min_term_edges:
            continue
        rows.sort(key=lambda r: r[0])
        # Tie-safe boundary: move the split to the next score change. An index
        # median splits a tie block, letting sort order rather than the score
        # decide which rows land in which half — the same defect fixed in
        # quality.enrichment_by_window. It materially moved these numbers.
        mid = len(rows) // 2
        while mid < len(rows) and rows[mid][0] == rows[mid - 1][0]:
            mid += 1
        if mid == 0 or mid >= len(rows):
            continue
        low, high = rows[:mid], rows[mid:]
        low_rate = sum(1 for _, hit in low if hit) / len(low)
        high_rate = sum(1 for _, hit in high if hit) / len(high)
        lo_hits += sum(1 for _, hit in low if hit)
        lo_n += len(low)
        hi_hits += sum(1 for _, hit in high if hit)
        hi_n += len(high)
        up, dn = (up + 1, dn) if high_rate > low_rate else (up, dn + 1)
    if not lo_n or not hi_n or not lo_hits:
        print(f"\n  within-term (>={args.min_term_edges} edges): too few comparable terms to stratify")
        return
    print(f"\n  within-term (>={args.min_term_edges} edges): {up + dn} terms, higher-score half agrees MORE in {up}")
    ratio = (hi_hits / hi_n) / (lo_hits / lo_n)
    print(f"    pooled low {lo_hits / lo_n:.4f} vs high {hi_hits / hi_n:.4f} -> {ratio:.2f}x")


if __name__ == "__main__":
    main()
