"""
Invariants checked against the merged graph, where sources actually meet.

Each transform can only police the edges it writes itself. ``kgmicrobe.strain:*``
is a deliberately shared namespace -- LPSN mints the same CURIEs BacDive does so
the merge reconciles them -- so a rule about those nodes is only really enforced
after the merge. #892 fixed multi-parent strains inside the BacDive transform;
this module is the check that notices if another source reintroduces them (#896).
"""

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from kg_microbe.transform_utils.constants import (
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write

logger = logging.getLogger(__name__)

#: Written beside merged-kg_nodes.tsv / merged-kg_edges.tsv.
STRAIN_PARENT_REPORT = "merged_strain_parent_violations.tsv"

STRAIN_PARENT_REPORT_HEADER = ["strain_id", "parent_count", "parents", "knowledge_sources"]


def find_multi_parent_strains(
    edges_file: Path,
) -> Dict[str, Tuple[Set[str], Set[str]]]:
    """
    Return strain nodes carrying more than one NCBITaxon parent in the merged graph.

    Streams the edge file rather than loading it: the merged graph is tens of
    millions of rows, and only the strain rows are retained.

    :param edges_file: Path to ``merged-kg_edges.tsv``.
    :return: ``{strain CURIE: (parent CURIEs, knowledge sources)}`` for every strain
        with more than one distinct parent. Empty when the invariant holds.
    """
    parents: Dict[str, Set[str]] = defaultdict(set)
    sources: Dict[str, Set[str]] = defaultdict(set)
    with edges_file.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            return {}
        # First occurrence, matching `merge_kg._first_index`. A merged header can
        # carry a repeated column name -- KGX takes the column union across sources
        # -- and a last-wins lookup would read the wrong column, find no strain
        # subjects, and report a clean graph. Silent, and in the reassuring
        # direction, which is the worst way for a check like this to fail (#915).
        index = {}
        for position, name in enumerate(header):
            index.setdefault(name, position)
        needed = (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN)
        if any(column not in index for column in needed):
            logger.warning(
                "[merge-invariants] %s lacks %s; skipping the strain-parent check",
                edges_file.name,
                [c for c in needed if c not in index],
            )
            return {}
        subject_at, predicate_at, object_at = (index[c] for c in needed)
        source_at = index.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN)
        for row in reader:
            if len(row) <= object_at:
                continue
            if row[predicate_at] != SUBCLASS_PREDICATE:
                continue
            subject, obj = row[subject_at], row[object_at]
            if not subject.startswith(STRAIN_PREFIX) or not obj.startswith(NCBITAXON_PREFIX):
                continue
            parents[subject].add(obj)
            if source_at is not None and len(row) > source_at and row[source_at]:
                sources[subject].add(row[source_at])
    return {s: (p, sources.get(s, set())) for s, p in parents.items() if len(p) > 1}


def strain_parent_rows(violations: Dict[str, Tuple[Set[str], Set[str]]]) -> List[List]:
    """
    Render violations as report rows, sorted so a diff between runs is readable.

    :param violations: Result of :func:`find_multi_parent_strains`.
    :return: Rows matching :data:`STRAIN_PARENT_REPORT_HEADER`.
    """
    return [
        [strain, len(parents), "|".join(sorted(parents)), "|".join(sorted(sources))]
        for strain, (parents, sources) in sorted(violations.items())
    ]


def check_merged_invariants(edges_file: Path, output_dir: Optional[Path] = None) -> int:
    """
    Run the merged-graph invariants and write their report.

    The report is written whether or not anything was found: an absent file would
    be indistinguishable from a clean run, and a clean run is the thing worth
    being able to demonstrate.

    :param edges_file: Path to ``merged-kg_edges.tsv``.
    :param output_dir: Where to write the report; defaults to the edge file's directory.
    :return: Number of violating strain nodes.
    """
    violations = find_multi_parent_strains(edges_file)
    destination = Path(output_dir or edges_file.parent) / STRAIN_PARENT_REPORT
    with atomic_write(destination, newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(STRAIN_PARENT_REPORT_HEADER)
        writer.writerows(strain_parent_rows(violations))
    if violations:
        offenders = _sources_of(violations)
        logger.warning(
            "[merge-invariants] %s strain nodes carry more than one NCBITaxon parent "
            "(sources: %s); listed in %s. A consumer taking 'the' parent gets one "
            "decided by file order (#892, #896).",
            f"{len(violations):,}",
            ", ".join(offenders) or "unattributed",
            destination,
        )
    else:
        logger.info("[merge-invariants] no strain node carries more than one NCBITaxon parent")
    return len(violations)


def _sources_of(violations: Dict[str, Tuple[Set[str], Set[str]]]) -> List[str]:
    """
    Name the knowledge sources implicated, so the report says who to go and fix.

    :param violations: Result of :func:`find_multi_parent_strains`.
    :return: Sorted knowledge-source strings.
    """
    seen: Set[str] = set()
    for _, sources in violations.values():
        seen |= sources
    return sorted(seen)
