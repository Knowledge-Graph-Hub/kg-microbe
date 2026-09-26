"""Resolve explicit BacDive item references without spreading record-wide citations."""

import re

from kg_microbe.utils.provenance import serialize_knowledge_sources

_DOI = re.compile(r"10\.\d{4,9}/[^\s|]+", re.ASCII)
_DOI_PREFIX = re.compile(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)


def publication_doi(value):
    """Normalize a complete DOI field, excluding catalogue and BacDive record identifiers."""
    if not isinstance(value, str):
        return None
    doi = _DOI_PREFIX.sub("", value.strip()).lower()
    if (
        not _DOI.fullmatch(doi)
        or doi.startswith("10.13145/bacdive")
        or any(ord(character) < 32 or ord(character) == 127 for character in doi)
    ):
        return None
    return f"doi:{doi}"


def _reference_key(value):
    """Normalize numeric string/int reference keys without coercing malformed values."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value).strip()
    return str(int(value)) if value.isascii() and value.isdigit() else None


def reference_dois(record):
    """Index unambiguous publication DOI references; contradictory duplicate IDs stay unresolved."""
    references = record.get("Reference")
    if isinstance(references, dict):
        references = [references]
    if not isinstance(references, list):
        return {}
    found = {}
    for reference in references:
        if not isinstance(reference, dict):
            continue
        key = _reference_key(reference.get("@id"))
        doi = publication_doi(reference.get("doi/url"))
        if key is not None and doi:
            found.setdefault(key, set()).add(doi)
    return {key: next(iter(dois)) for key, dois in found.items() if len(dois) == 1}


def item_publications(item, references):
    """Return only the publications named by this item's explicit reference pointer(s)."""
    keys = item.get("@ref")
    if not isinstance(keys, list):
        keys = [keys]
    return serialize_knowledge_sources([references.get(_reference_key(key)) for key in keys])
