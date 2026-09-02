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
    CATEGORY_COLUMN,
    NAME_COLUMN,
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
    # Derived from the edge file's name so the two reports describe one graph.
    # Absent is normal: the strain-parent check needs no nodes file, and callers
    # pointing at an arbitrary edge dump may not have one.
    nodes_file = edges_file.parent / edges_file.name.replace("_edges.tsv", "_nodes.tsv")
    stubs = find_stub_nodes(nodes_file) if nodes_file.is_file() else {}
    if stubs:
        stub_destination = Path(output_dir or edges_file.parent) / STUB_NODE_REPORT
        with atomic_write(stub_destination, newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(STUB_NODE_REPORT_HEADER)
            writer.writerows(stub_node_rows(stubs))
        unexpected = {p: c for p, c in stubs.items() if p not in EXPECTED_STUB_PREFIXES}
        if unexpected:
            logger.warning(
                "[merge-invariants] %s nodes across %s prefixes were invented by KGX for endpoints "
                "no source declared (%s); listed in %s. A source references them, so it should "
                "declare them (#918).",
                f"{sum(len(c) for c in unexpected.values()):,}",
                len(unexpected),
                ", ".join(sorted(unexpected)),
                stub_destination,
            )

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


#: Written beside the merged TSVs, alongside the strain-parent report.
STUB_NODE_REPORT = "merged_stub_nodes.tsv"

STUB_NODE_REPORT_HEADER = ["prefix", "count", "expected", "examples"]

#: Prefixes we reference deliberately without ever supplying a node for them.
#: These are cross-reference identifiers -- a GOLD study id, an IMG genome id, a
#: GTDB taxon string -- that name a record in someone else's system. We assert
#: edges to them on purpose and do not ingest those systems as nodes, so a stub is
#: the correct outcome, not a gap. Everything else is reported (#918).
EXPECTED_STUB_PREFIXES = {
    "IMG": "IMG genome and taxon identifiers, referenced from GOLD",
    "GOLD": "GOLD study, project and biosample identifiers",
    "GTDB": "GTDB taxon strings, referenced as cross-references",
}

#: What KGX types a node it invented for an undeclared endpoint.
NAMED_THING_CATEGORY = "biolink:NamedThing"


def find_stub_nodes(nodes_file: Path) -> Dict[str, List[str]]:
    """
    Return nodes KGX synthesized because an edge referenced something undeclared.

    The merge leaves no endpoint without a node row -- KGX invents one -- so the
    question worth asking after a merge is not "what is missing" but "what arrived
    as an invention". Those rows are typed ``biolink:NamedThing`` and carry no
    name, which is the shape #892 objected to.

    :param nodes_file: Path to ``merged-kg_nodes.tsv``.
    :return: ``{CURIE prefix: [CURIEs]}``, sorted, empty when none.
    """
    by_prefix: Dict[str, List[str]] = defaultdict(list)
    with nodes_file.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            return {}
        index: Dict[str, int] = {}
        for position, name in enumerate(header):
            index.setdefault(name, position)
        if CATEGORY_COLUMN not in index or NAME_COLUMN not in index:
            logger.warning("[merge-invariants] %s lacks category/name; skipping the stub-node check", nodes_file.name)
            return {}
        category_at, name_at = index[CATEGORY_COLUMN], index[NAME_COLUMN]
        for row in reader:
            if len(row) <= max(category_at, name_at):
                continue
            if row[category_at] != NAMED_THING_CATEGORY or row[name_at].strip():
                continue
            by_prefix[row[0].split(":", 1)[0]].append(row[0])
    return {prefix: sorted(curies) for prefix, curies in sorted(by_prefix.items())}


def stub_node_rows(stubs: Dict[str, List[str]]) -> List[List]:
    """
    Render stub counts per prefix, flagging the ones we did not intend.

    :param stubs: Result of :func:`find_stub_nodes`.
    :return: Rows matching :data:`STUB_NODE_REPORT_HEADER`.
    """
    return [
        [
            prefix,
            len(curies),
            "yes" if prefix in EXPECTED_STUB_PREFIXES else "no",
            "|".join(curies[:3]),
        ]
        for prefix, curies in sorted(stubs.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
