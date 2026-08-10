"""
Detect silent shrinkage of MediaDive recipe coverage between builds.

Why this exists: between the 2024-12 and 2026-08 builds, solution ingredient
edges fell 76,856 -> 39,795 (-48.2%), with 2,026 of 5,093 shared solutions losing
ingredients — Modified Wolin's mineral solution went 218 -> 16. Nothing flagged
it. It surfaced ~20 months later because someone happened to inspect one medium
by hand (#728).

The cause was upstream: the MediaDive REST API now serves those shortened
recipes, and the transform reproduces them faithfully. So this is not a
correctness guard on our code — it is a *coverage* guard on a third-party source
that can change under us without notice, and whose loss is unrecoverable by
re-running.

Compares an emitted ``mediadive/edges.tsv`` against a committed baseline of
per-solution ingredient counts and reports what moved. Run it from
``make validate-mediadive-coverage``, as a release pre-flight, or any time the
mediadive raw is refreshed.

**The committed baseline records the post-regression state**, because the richer
2024 recipes are gone from upstream and cannot be recovered. It is a floor to
detect the *next* change, not a statement that current coverage is healthy.

Usage:

    python scripts/mediadive_coverage_check.py                     # vs the committed baseline
    python scripts/mediadive_coverage_check.py --update-baseline   # accept current as the new baseline
    python scripts/mediadive_coverage_check.py --compare OTHER/edges.tsv

Exit codes: 0 = within tolerance, 1 = coverage moved beyond ``--tolerance`` in
either direction.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict

DEFAULT_EDGES = Path("data/transformed/mediadive/edges.tsv")
DEFAULT_BASELINE = Path("scripts/mediadive_coverage_baseline.json")
HAS_PART = "biolink:has_part"


def parse_args() -> argparse.Namespace:
    """
    Parse the command line.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--edges", type=Path, default=DEFAULT_EDGES, help="mediadive edges.tsv to check")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="committed baseline JSON")
    parser.add_argument("--compare", type=Path, default=None, help="compare against another edges.tsv instead")
    parser.add_argument("--update-baseline", action="store_true", help="write current counts as the new baseline")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=5.0,
        help=(
            "percent change in total ingredient edges tolerated before failing, in EITHER "
            "direction. Default 5%%: normal refreshes move this by well under 1%%, and the "
            "regression that motivated this check was -48%%. Increases are checked too — a "
            "doubling means duplicated rows or a fanned-out join at least as often as it means "
            "recovered data."
        ),
    )
    parser.add_argument("--top", type=int, default=10, help="how many per-solution losses to list")
    return parser.parse_args()


def ingredient_counts(path: Path) -> Dict[str, int]:
    """
    Count non-solution ingredients per solution.

    Nested ``solution -has_part-> solution`` edges are excluded: they are
    structure, not composition, and counting them would let a solution that
    merely gained a nested reference mask the loss of real compounds.

    The solution key is normalised to bare ``solution:<id>`` because the CURIE
    prefix changed between builds (``solution:1134`` -> ``mediadive.solution:1134``);
    comparing raw subjects would report every solution as both added and removed.

    :param path: Path to a mediadive ``edges.tsv``.
    :return: Mapping of ``solution:<id>`` to ingredient count.
    :raises SystemExit: If the file is missing or has no usable edges.
    """
    if not path.exists():
        raise SystemExit(f"no mediadive edges at {path}")
    counts: Dict[str, int] = defaultdict(int)
    with path.open() as handle:
        next(handle)
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3 or fields[1] != HAS_PART:
                continue
            subject, obj = fields[0], fields[2]
            if "solution:" not in subject or "solution:" in obj:
                continue
            counts["solution:" + subject.split("solution:")[-1]] += 1
    if not counts:
        raise SystemExit(f"{path} yielded no solution ingredient edges; refusing to report on an empty comparison.")
    return dict(counts)


def summarise(counts: Dict[str, int], label: str) -> None:
    """
    Print a one-line summary of a coverage set.

    :param counts: Per-solution ingredient counts.
    :param label: Human-readable name for the set.
    """
    total = sum(counts.values())
    print(f"  {label}: {len(counts):,} solutions, {total:,} ingredient edges, {total / len(counts):.2f} mean")


def main() -> int:
    """
    Compare coverage and report.

    :return: Process exit code.
    """
    args = parse_args()
    current = ingredient_counts(args.edges)

    if args.update_baseline:
        args.baseline.write_text(json.dumps(current, indent=0, sort_keys=True) + "\n")
        summarise(current, "new baseline")
        print(f"  written to {args.baseline}")
        return 0

    if args.compare:
        previous = ingredient_counts(args.compare)
        source = str(args.compare)
    else:
        if not args.baseline.exists():
            raise SystemExit(f"no baseline at {args.baseline}; create one with --update-baseline")
        previous = json.loads(args.baseline.read_text())
        source = str(args.baseline)

    summarise(previous, f"baseline ({source})")
    summarise(current, "current  ")

    before, after = sum(previous.values()), sum(current.values())
    delta = 100 * (after - before) / before
    shared = set(previous) & set(current)
    lost = {k: (previous[k], current[k]) for k in shared if current[k] < previous[k]}
    gained = sum(1 for k in shared if current[k] > previous[k])

    print(f"\n  total ingredient edges: {before:,} -> {after:,} ({delta:+.1f}%)")
    print(f"  solutions losing ingredients: {len(lost):,} of {len(shared):,} shared")
    print(f"  solutions gaining:            {gained:,}")
    print(f"  only in baseline: {len(set(previous) - set(current)):,}   only in current: {len(set(current) - set(previous)):,}")

    if lost:
        print(f"\n  largest losses (top {args.top}):")
        for key, (was, now) in sorted(lost.items(), key=lambda kv: kv[1][1] - kv[1][0])[: args.top]:
            print(f"    {key:<24} {was:>5} -> {now:<5} ({now - was:+d})")

    if delta < -args.tolerance:
        print(
            f"\n  FAIL: coverage dropped {abs(delta):.1f}%, beyond the {args.tolerance:.1f}% tolerance.\n"
            "  Check whether MediaDive changed upstream before accepting this build — the loss is\n"
            "  not recoverable by re-running, and a release built on it silently ships thinner media."
        )
        return 1
    if delta > args.tolerance:
        # Not merely "more data". Duplicated rows, a fanned-out join, an append
        # where a truncate was meant, or a CURIE split that turns one ingredient
        # into two all inflate this number, and all corrupt the graph. Calling a
        # doubling "within tolerance" would be the more misleading answer.
        print(
            f"\n  FAIL: coverage rose {delta:.1f}%, beyond the {args.tolerance:.1f}% tolerance.\n"
            "  An increase is not self-evidently good — check for duplicated edges or a join\n"
            "  fan-out before accepting it, then re-baseline with --update-baseline."
        )
        return 1
    print(f"\n  OK: within the {args.tolerance:.1f}% tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
