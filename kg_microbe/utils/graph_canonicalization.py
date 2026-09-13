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


@lru_cache(maxsize=1)
def _uri_prefixes() -> tuple:
    """Load the local registry once, preferring specific over overlapping namespaces."""
    with open(PREFIXMAP_JSON_FILEPATH, encoding="utf-8") as stream:
        prefixes = json.load(stream)
    return tuple(sorted(((uri, prefix) for prefix, uri in prefixes.items()), key=lambda item: -len(item[0])))


def compact_identifier(identifier: str) -> str:
    """Compact registered identifiers without inventing prefixes for arbitrary URLs."""
    if not identifier.startswith(("http://", "https://")):
        return identifier
    if identifier.startswith(_OWL_TIME_DOCUMENT_IRI):
        identifier = _OWL_TIME_VOCAB_IRI + identifier[len(_OWL_TIME_DOCUMENT_IRI) :]
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
    if identifier.startswith("FOODON:"):
        canonical = FOOD_CATEGORY
    elif identifier.startswith("PATO:"):
        canonical = PHENOTYPIC_CATEGORY
    else:
        return category
    categories = set(category.split("|")) if isinstance(category, str) else set()
    categories.discard("biolink:OntologyClass")
    categories.discard("")
    categories.add(canonical)
    return "|".join(sorted(categories))
