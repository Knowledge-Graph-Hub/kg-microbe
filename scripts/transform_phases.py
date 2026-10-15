#!/usr/bin/env python3
"""
Group the registered transform sources into dependency phases for a parallel run (#1567).

A source reads the outputs it lists in ``TRANSFORM_INPUTS``, and ``kg transform``
refuses to start it until each of those has a completion marker. Sources in one
phase depend only on sources in earlier phases, so a phase can run concurrently
once the previous one has finished. The phases come from the registry in
``kg_microbe/transform.py``, never a hand-kept list, so a new or retired source
moves to the right phase by itself.

The default selection is the default ``kg transform`` batch: every registered
source except the explicit-only ones. An optional source with no input (Bakta
without a dataset) is left out, with whatever depends on it, exactly as that
batch skips it; it would fail if named with ``-s``.

Usage::

    poetry run python scripts/transform_phases.py [-i RAW_DIR] [-s SOURCE ...]

prints one line per phase, its sources separated by spaces, and the skipped
sources with their reasons on stderr.
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]


def plan(sources: Optional[Iterable[str]] = None, input_dir: Optional[Path] = None) -> Tuple[List[List[str]], Dict]:
    """
    Return the dependency phases of ``sources`` and the sources skipped, with reasons.

    :param sources: Source names; the default ``kg transform`` batch when ``None``.
    :param input_dir: Raw input directory the run will read; ``data/raw`` when ``None``.
    :return: ``(phases, skipped)``. Each phase lists sources in registry order. An
        upstream outside the selection is not waited for: ``kg transform`` then
        requires its completed output, as it does for any single source.
    :raises ValueError: When a source is not registered or is a single ontology, or the
        declarations form a cycle.
    """
    import kg_microbe.transform as dispatcher

    if sources is None:
        selected = [name for name in dispatcher.DATA_SOURCES if name not in dispatcher.EXPLICIT_ONLY_SOURCES]
    else:
        selected = list(dict.fromkeys(sources))
        unknown = sorted(set(selected) - set(dispatcher.DATA_SOURCES))
        single = [name for name in unknown if name in dispatcher._ontology_map()]
        if single:
            # A single ontology withdraws the ontologies marker that every other
            # phase's readers rely on, so it never runs beside them (#1660).
            raise ValueError(
                f"Single ontologies are not planned: {', '.join(single)}. "
                "Run `kg transform -s <ontology>` on its own, or plan `ontologies`"
            )
        if unknown:
            raise ValueError(
                f"Unknown transform source(s): {', '.join(unknown)}. "
                f"Registered sources: {', '.join(sorted(dispatcher.DATA_SOURCES))}"
            )
    skipped = dispatcher._not_applicable(selected, dispatcher._absent_optional_inputs(selected, input_dir))
    remaining = [name for name in dispatcher.DATA_SOURCES if name in selected and name not in skipped]
    depth: Dict[str, int] = {}
    while len(depth) < len(remaining):
        placed = len(depth)
        for name in remaining:
            if name in depth:
                continue
            upstream = [u for u in getattr(dispatcher.DATA_SOURCES[name], "TRANSFORM_INPUTS", ()) if u in remaining]
            if all(u in depth for u in upstream):
                depth[name] = 1 + max((depth[u] for u in upstream), default=-1)
        if len(depth) == placed:
            raise ValueError(
                f"TRANSFORM_INPUTS form a cycle among: {', '.join(n for n in remaining if n not in depth)}"
            )
    phases: List[List[str]] = [[] for _ in range(1 + max(depth.values(), default=-1))]
    for name in remaining:
        phases[depth[name]].append(name)
    return phases, skipped


def main(argv: Optional[List[str]] = None) -> int:
    """
    Print the phases, one per line, and the skipped sources on stderr.

    :param argv: Command-line arguments; ``sys.argv[1:]`` when ``None``.
    :return: Process exit code: 0, or 2 for an unknown source or a cycle.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "-i", "--input-dir", type=Path, default=Path("data/raw"), help="raw input directory, as `kg transform -i`"
    )
    parser.add_argument("-s", "--source", action="append", dest="sources", help="source to plan (repeatable)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        phases, skipped = plan(args.sources, args.input_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, reason in skipped.items():
        print(f"skipped {name}: {reason}", file=sys.stderr)
    for phase in phases:
        print(" ".join(phase))
    return 0


if __name__ == "__main__":
    sys.exit(main())
