"""Asserted FOODON organism, process, quality, and information-content boundaries."""

import csv
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from kg_microbe.transform_utils.constants import (
    ACTIVITY_CATEGORY,
    FOOD_CATEGORY,
    INFORMATION_CONTENT_ENTITY_CATEGORY,
    NCBI_CATEGORY,
    PHENOTYPIC_CATEGORY,
    RAW_DATA_DIR,
)
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

FOODON_GRAPH = RAW_DATA_DIR / "foodon.json"
# FOODON's whole-plant branch is not connected to COB's organism root.
ORGANISM_ROOTS = {"COB:0000022", "PO:0000003", "NCBITaxon:1"}
# Generic processing ancestry does not establish GO biological-process meaning.
# Cooking and harvesting are activities; label claims are information content,
# even where an imported assertion incorrectly uses has_quality for them.
CATEGORY_ROOTS = {
    NCBI_CATEGORY: ORGANISM_ROOTS,
    ACTIVITY_CATEGORY: {"BFO:0000015"},
    PHENOTYPIC_CATEGORY: {"PATO:0000001"},
    INFORMATION_CONTENT_ENTITY_CATEGORY: {"IAO:0000030"},
}
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


# Meat-cut child -> whole-organism parent edges quarantined by #1355 and #1356.
# Endpoint declarations are still validated, but these de-parented edges must not
# propagate whole-organism (biolink:OrganismTaxon) ancestry onto meat products.
_QUARANTINED_MEAT_PARENT_EDGES = frozenset(
    {
        ("FOODON:03309966", "FOODON:00003083"),
        ("FOODON:03306418", "FOODON:00003083"),
        ("FOODON:03308537", "FOODON:00002686"),
        ("FOODON:03308433", "FOODON:03413856"),
        ("FOODON:03308553", "FOODON:03411479"),
        ("FOODON:03309141", "FOODON:03411843"),
        ("FOODON:03309911", "FOODON:03413810"),
    }
)


def _asserted_hierarchy(graphs: list) -> tuple:
    """Require live class declarations for every endpoint of asserted subclass edges."""
    from kg_microbe.utils.graph_canonicalization import compact_identifier

    if not isinstance(graphs, list) or not graphs:
        raise ValueError("Missing FOODON ontology declarations")
    declarations = {}
    for graph in graphs:
        for node in graph.get("nodes", []):
            identifier = compact_identifier(node["id"])
            deprecated = obograph_is_deprecated(node)
            declaration = (node.get("type", ""), deprecated)
            if identifier in declarations and declarations[identifier] != declaration:
                raise ValueError(f"Conflicting FOODON declarations: {identifier}")
            declarations[identifier] = declaration
    if not declarations:
        raise ValueError("Missing FOODON ontology declarations")
    live_classes = {identifier for identifier, value in declarations.items() if value == ("CLASS", False)}
    children = defaultdict(set)
    for graph in graphs:
        for edge in graph.get("edges", []):
            if compact_identifier(edge.get("pred", "")) in {"is_a", "rdfs:subClassOf"}:
                child, parent = compact_identifier(edge["sub"]), compact_identifier(edge["obj"])
                for identifier in (child, parent):
                    if identifier not in live_classes:
                        raise ValueError(
                            f"Invalid FOODON subclass evidence: {identifier} lacks a live CLASS declaration"
                        )
                if (child, parent) in _QUARANTINED_MEAT_PARENT_EDGES:
                    continue
                children[parent].add(child)
    return children, live_classes


def _descendants(children: dict, roots: set) -> frozenset:
    """Return reflexive asserted closure, terminating even for cyclic input."""
    found = set(roots)
    queue = list(found)
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return frozenset(found)


def organism_classes(graphs: list) -> frozenset:
    """Follow asserted subclass edges downward from documented whole-organism roots."""
    children, live_classes = _asserted_hierarchy(graphs)
    return _descendants(children, ORGANISM_ROOTS & live_classes)


def foodon_categories(graphs: list, *, dispositions: dict | None = None, anatomical_categories=None) -> dict:
    """
    Classify finite FOODON branches from a caller-owned native input snapshot.

    Live declared classes without a supported branch retain the existing Food
    fallback explicitly. Undeclared, retired, or nonclass IDs receive no decision;
    authoritative lookup rejects them instead of manufacturing a Food category.
    Contradictory declarations or invalid subclass evidence abort.
    """
    children, live_classes = _asserted_hierarchy(graphs)
    if anatomical_categories is None:
        from kg_microbe.utils.foodon_anatomical_categories import categories_for

        anatomical_categories = categories_for(graphs)
    result = {identifier: FOOD_CATEGORY for identifier in live_classes if identifier.startswith("FOODON:")}
    for category, roots in CATEGORY_ROOTS.items():
        identifiers = _descendants(children, roots & live_classes)
        if category == NCBI_CATEGORY:
            rows = foodon_dispositions() if dispositions is None else dispositions
            identifiers |= {
                identifier
                for identifier, row in rows.items()
                if row["disposition"] == "organism_class" and identifier in live_classes
            }
        for identifier in identifiers:
            if not identifier.startswith("FOODON:") and identifier not in ORGANISM_ROOTS:
                continue
            previous = result.get(identifier)
            if previous is not None and previous not in {FOOD_CATEGORY, category}:
                raise ValueError(f"Conflicting FOODON asserted categories for {identifier}: {previous}, {category}")
            result[identifier] = category
    # Exact approved primary projections supersede the reviewed bad organism
    # ancestry. No descendants outside this finite evidence are reclassified.
    result.update(anatomical_categories)
    return result


@lru_cache(maxsize=2)
def _load_categories(
    path: str,
    size: int,
    mtime_ns: int,
    curation_path: str,
    curation_size: int,
    curation_mtime: int,
    anatomical_signature: tuple,
):
    """Process-local cache only; producer snapshots fingerprint native bytes independently."""
    del size, mtime_ns, anatomical_signature
    with open(path, encoding="utf-8") as stream:
        graphs = json.load(stream)["graphs"]
    rows = _load_dispositions(curation_path, curation_size, curation_mtime)
    return MappingProxyType(foodon_categories(graphs, dispositions=rows))


def foodon_organism_classes(path: Path | None = None) -> frozenset:
    """Read local asserted ancestry when present; never fetch ontology data implicitly."""
    path = FOODON_GRAPH if path is None else path
    if not path.is_file():
        return frozenset(_curated_organisms() | ORGANISM_ROOTS)
    stat = path.stat()
    curation_stat = DISPOSITIONS_FILE.stat()
    from kg_microbe.utils.foodon_anatomical_categories import cache_signature

    categories = _load_categories(
        str(path.resolve()),
        stat.st_size,
        stat.st_mtime_ns,
        str(DISPOSITIONS_FILE.resolve()),
        curation_stat.st_size,
        curation_stat.st_mtime_ns,
        cache_signature(),
    )
    return frozenset(identifier for identifier, category in categories.items() if category == NCBI_CATEGORY)


def authoritative_foodon_category(identifier: str, *, path: Path | None = None, categories=None) -> str:
    """Use native branch evidence consistently for the producer and import routes."""
    # KGX has historically compacted this imported COB root through OBO:.
    if identifier == "OBO:COB_0000022":
        identifier = "COB:0000022"
    if categories is None:
        from kg_microbe.utils.foodon_anatomical_categories import FINITE_IDS, cache_signature

        path = FOODON_GRAPH if path is None else Path(path)
        if not path.is_file():
            if identifier in FINITE_IDS:
                raise FileNotFoundError(f"Required FOODON anatomical category authority is missing: {path}")
            # Direct offline callers preserve the historical fallback. Producer
            # finalization separately requires the native authority when consumed.
            return NCBI_CATEGORY if identifier in foodon_organism_classes(path) else FOOD_CATEGORY
        stat = path.stat()
        curation_stat = DISPOSITIONS_FILE.stat()
        categories = _load_categories(
            str(path.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            str(DISPOSITIONS_FILE.resolve()),
            curation_stat.st_size,
            curation_stat.st_mtime_ns,
            cache_signature(),
        )
    category = categories.get(identifier)
    if category is None:
        raise ValueError(f"No live FOODON CLASS declaration authorizes a category for {identifier}")
    return category
