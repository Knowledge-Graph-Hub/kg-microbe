"""Source-independent KGX category and identifier normalization (#1052, #1054)."""

import json
import re
from functools import lru_cache

from kg_microbe.transform_utils.constants import FOOD_CATEGORY, PHENOTYPIC_CATEGORY, PREFIXMAP_JSON_FILEPATH

_OBO_IRI = re.compile(r"^https?://purl\.obolibrary\.org/obo/([A-Za-z][A-Za-z0-9]*)_(.+)$")
# FOODON imports OWL-Time using links to its specification rather than the
# vocabulary namespace. This is an explicit known alias, not a general rule
# that guesses an identifier from a URL fragment.
_OWL_TIME_DOCUMENT_IRI = "https://www.w3.org/TR/owl-time/#time:"
_OWL_TIME_VOCAB_IRI = "http://www.w3.org/2006/time#"
# FOODON/ENVO refer to Wikidata entities through their human-readable pages.
# Only exact Q-identifier pages are aliases, not arbitrary wiki endpoints (#1074).
_WIKIDATA_ENTITY_PAGE = re.compile(r"^https://www\.wikidata\.org/wiki/(Q[0-9]+)$")


@lru_cache(maxsize=1)
def _uri_prefixes() -> tuple:
    """Load the local registry once, preferring specific over overlapping namespaces."""
    with open(PREFIXMAP_JSON_FILEPATH, encoding="utf-8") as stream:
        prefixes = json.load(stream)
    return tuple(sorted(((uri, prefix) for prefix, uri in prefixes.items()), key=lambda item: -len(item[0])))


def compact_identifier(identifier: str) -> str:
    """Compact registered identifiers without inventing prefixes for arbitrary URLs."""
    # KGX uses uppercase ORCID, while the checked-in registry uses lowercase.
    if identifier.startswith("ORCID:"):
        return "orcid:" + identifier[len("ORCID:") :]
    if not identifier.startswith(("http://", "https://")):
        return identifier
    if identifier.startswith(_OWL_TIME_DOCUMENT_IRI):
        identifier = _OWL_TIME_VOCAB_IRI + identifier[len(_OWL_TIME_DOCUMENT_IRI) :]
    wikidata = _WIKIDATA_ENTITY_PAGE.fullmatch(identifier)
    if wikidata:
        identifier = "https://www.wikidata.org/entity/" + wikidata[1]
    for uri, prefix in _uri_prefixes():
        if identifier.startswith(uri) and len(identifier) > len(uri):
            return f"{prefix}:{identifier[len(uri) :]}"
    match = _OBO_IRI.fullmatch(identifier)
    if match:
        return f"{match[1]}:{match[2]}"
    return identifier


def canonical_node_category(identifier: str, category: str) -> str:
    """Replace imported OntologyClass fallbacks without discarding substantive multi-typing."""
    identifier = compact_identifier(identifier)
    if identifier.startswith("FOODON:") or identifier in {"COB:0000022", "OBO:COB_0000022", "PO:0000003"}:
        from kg_microbe.utils.foodon_classification import authoritative_foodon_category

        canonical = authoritative_foodon_category(identifier)
    elif identifier.startswith("PATO:"):
        canonical = PHENOTYPIC_CATEGORY
    else:
        return category
    categories = set(category.split("|")) if isinstance(category, str) else set()
    categories.discard("biolink:OntologyClass")
    if canonical == "biolink:OrganismTaxon":
        # An imported Food or anatomical fallback cannot override an explicit
        # whole-organism class. Other legitimate multi-typing remains intact.
        categories.discard(FOOD_CATEGORY)
        categories.discard("biolink:AnatomicalEntity")
    categories.discard("")
    categories.add(canonical)
    return "|".join(sorted(categories))
