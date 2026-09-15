"""Asserted FOODON organism-class boundaries, distinct from foods and body parts."""

import csv
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from kg_microbe.transform_utils.constants import FOOD_CATEGORY, NCBI_CATEGORY, RAW_DATA_DIR

FOODON_GRAPH = RAW_DATA_DIR / "foodon.json"
# FOODON's whole-plant branch is not connected to COB's organism root.
ORGANISM_ROOTS = {"COB:0000022", "PO:0000003", "NCBITaxon:1"}
# Raw FOODON:03411744 has synonym laminariales, matching the exact label of
# NCBITaxon:2886 in the pinned taxonomy. This fixes category only, not identity.
DISPOSITIONS_FILE = Path(__file__).resolve().parents[2] / "mappings" / "foodon_model_dispositions.tsv"


@lru_cache(maxsize=2)
def _load_dispositions(path: str, size: int, mtime_ns: int) -> dict:
    """Cache curated rows with process-local stat invalidation, not a release fingerprint."""
    del size, mtime_ns
    with open(path, encoding="utf-8", newline="") as stream:
        return {row["id"]: row for row in csv.DictReader(stream, delimiter="\t")}


def foodon_dispositions() -> dict:
    """Read evidence-bearing curation; pipeline data fingerprints separately hash its content."""
    stat = DISPOSITIONS_FILE.stat()
    return _load_dispositions(str(DISPOSITIONS_FILE), stat.st_size, stat.st_mtime_ns)


def _curated_organisms() -> set:
    """Return category-only corrections; none assert identity with an NCBI taxon."""
    return {identifier for identifier, row in foodon_dispositions().items() if row["disposition"] == "organism_class"}


def organism_classes(graphs: list) -> frozenset:
    """Follow asserted subclass edges downward from documented whole-organism roots."""
    from kg_microbe.utils.graph_canonicalization import compact_identifier

    children = defaultdict(set)
    for graph in graphs:
        for edge in graph.get("edges", []):
            if edge.get("pred") in {"is_a", "rdfs:subClassOf"}:
                children[compact_identifier(edge["obj"])].add(compact_identifier(edge["sub"]))
    found = set(ORGANISM_ROOTS)
    queue = list(found)
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return frozenset(found)


@lru_cache(maxsize=2)
def _load_organism_classes(path: str, size: int, mtime_ns: int) -> frozenset:
    """Cache only an immutable ID set with process-local source-stat invalidation."""
    del size, mtime_ns
    with open(path, encoding="utf-8") as stream:
        graphs = json.load(stream)["graphs"]
    return organism_classes(graphs)


def foodon_organism_classes(path: Path | None = None) -> frozenset:
    """Read local asserted ancestry when present; never fetch ontology data implicitly."""
    path = FOODON_GRAPH if path is None else path
    if not path.is_file():
        return frozenset(_curated_organisms() | ORGANISM_ROOTS)
    stat = path.stat()
    return _load_organism_classes(str(path.resolve()), stat.st_size, stat.st_mtime_ns) | _curated_organisms()


def authoritative_foodon_category(identifier: str, *, path: Path | None = None) -> str:
    """Distinguish FOODON organism classes from the default food-material category."""
    # KGX has historically compacted this imported COB root through OBO:.
    if identifier == "OBO:COB_0000022":
        identifier = "COB:0000022"
    return NCBI_CATEGORY if identifier in foodon_organism_classes(path) else FOOD_CATEGORY
