"""
Loader and validator for the BacDive isolation-source → ontology mapping table.

The mapping table at ``mappings/isolation_source_to_ontology.tsv`` records both
high-quality manual mappings and lower-quality automated lexical hits. The
loader applies a conservative confidence policy so that only trustworthy rows
are honored at runtime; everything else is dropped (and the BacDive transform
emits the raw ``isolation_source:*`` placeholder node instead).

Policy (applied in order; first match wins):
1. Drop the row if it carries no ``object_id`` (explicitly unmapped).
2. Drop the row if its ``object_source`` is in :data:`DISALLOWED_OBJECT_SOURCES`
   (e.g. ``UO`` — units of measurement are never an isolation source).
3. Drop the row if its ``object_label`` matches a banned-family substring for
   the subject's apparent kind (anatomy / host / generic environment) — these
   indicate a family mismatch like an anatomical label being mapped to a
   facility, document, or clinical condition.
4. Honor the row if ``predicate_id == 'skos:exactMatch'`` and
   ``confidence == 'high'``.
5. Honor the row if ``mapping_justification == 'semapv:ManualMappingCuration'``
   (any row that has been touched by a human curator).
6. Otherwise drop. In practice this rejects ``ols4_auto`` lexical
   ``skos:closeMatch`` rows that are most prone to false positives.

This loader is intentionally strict. Promoting an automated lexical hit to
"trusted" should be a deliberate curator action (set predicate to exactMatch
or change the mapping_justification to ManualMappingCuration) rather than an
implicit upgrade.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ISOLATION_SOURCE_MAPPING_FILE = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"

# Object-source ontologies that are categorically wrong for an isolation source.
# UO is the unit of measurement ontology; UO terms can never represent a sample
# substrate, body part, host, or environment. Any other source ontology with a
# similar problem belongs here.
DISALLOWED_OBJECT_SOURCES: frozenset = frozenset({"UO"})

# Ontology prefixes that the BacDive isolation_source mapping TSV references
# but that are NOT loaded by the ontologies transform (see ONTOLOGIES_MAP in
# kg_microbe/transform_utils/ontologies/ontologies_transform.py). Each
# prefix has only a tiny number of distinct IDs in use and loading the full
# ontology would be wasteful, so the BacDive transform writes a thin node
# row per resolved CURIE using the object_label from the mapping TSV. The
# category is biolink:OntologyClass for all stubs because they're top-level
# categorical terms (host body site, microbial community, ...) rather than
# specific anatomy / environmental features.
STUB_ONTOLOGY_PREFIXES: frozenset = frozenset({
    "PRIDE",  # 3 IDs: host body site, host body product, antibiotic treatment
    "PCO",    # 1 active ID: microbial community (PCO:1000004)
})
STUB_ONTOLOGY_CATEGORY = "biolink:OntologyClass"

# Substrings in the *target* label that signal a family mismatch with any
# isolation-source label kind. These are facilities, documents, processes, or
# clinical instruments, not substrates / body parts / hosts / environments.
# The check is case-insensitive and substring-based.
BANNED_OBJECT_LABEL_SUBSTRINGS: Tuple[str, ...] = (
    "ability question",
    "processing plant",
    "human construction",
    "patient room",
    "indoor toilet",
    "child care environment",
    "house painting",
    "medical product document",
    "infection zone",
    "breeding waste material",
    "industrial waste material",
    "dependence on",
)


def _row_passes_family_check(row: Dict[str, str]) -> bool:
    """
    Return ``True`` iff the row is not in a known family-mismatch class.

    Centralizes the rejection rules so the same logic is shared by the
    runtime loader and the standalone validator script.
    """
    object_source = (row.get("object_source") or "").strip()
    object_label = (row.get("object_label") or "").strip().lower()

    if object_source in DISALLOWED_OBJECT_SOURCES:
        return False

    for banned in BANNED_OBJECT_LABEL_SUBSTRINGS:
        if banned in object_label:
            return False

    return True


def _row_is_trusted(row: Dict[str, str]) -> bool:
    """Apply the trust policy described in the module docstring."""
    predicate = (row.get("predicate_id") or "").strip()
    confidence = (row.get("confidence") or "").strip().lower()
    justification = (row.get("mapping_justification") or "").strip()

    if predicate == "skos:exactMatch" and confidence == "high":
        return True
    if justification == "semapv:ManualMappingCuration":
        return True
    return False


def iter_validation_failures(
    mapping_path: Optional[Path] = None,
) -> Iterable[Tuple[int, Dict[str, str], str]]:
    """
    Yield ``(row_number, row, reason)`` tuples for rows that fail family validation.

    ``row_number`` is 1-based and counts data rows after the header (so the
    first data row is row 1). Used by the standalone validator script.
    """
    path = Path(mapping_path) if mapping_path else DEFAULT_ISOLATION_SOURCE_MAPPING_FILE
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for idx, row in enumerate(reader, start=1):
            if not (row.get("object_id") or "").strip():
                continue  # explicitly unmapped — not a validation failure

            object_source = (row.get("object_source") or "").strip()
            if object_source in DISALLOWED_OBJECT_SOURCES:
                yield idx, row, f"object_source '{object_source}' is disallowed"
                continue

            object_label = (row.get("object_label") or "").strip().lower()
            for banned in BANNED_OBJECT_LABEL_SUBSTRINGS:
                if banned in object_label:
                    yield idx, row, f"object_label contains banned substring '{banned}'"
                    break


def load_isolation_source_mappings(
    mapping_path: Optional[Path] = None,
) -> Dict[str, Tuple[str, str]]:
    """
    Load trusted isolation-source mappings keyed by normalized subject label.

    The key is the lowercased ``subject_label_normalized`` (or, as a fallback,
    the lowercased ``subject_label``) — this matches the canonicalization the
    BacDive transform already applies before lookups (lowercasing the raw
    BacDive isolation-source string).

    :param mapping_path: Optional override for the TSV path. Defaults to the
        committed ``mappings/isolation_source_to_ontology.tsv`` next to this repo.
    :returns: ``{normalized_label: (object_id, object_label)}`` for every row
        that passes both the family-compatibility check and the trust policy.
        Rows that are explicitly unmapped, family-mismatched, or below the
        trust threshold are silently skipped (with INFO-level logging of the
        skip count).
    """
    path = Path(mapping_path) if mapping_path else DEFAULT_ISOLATION_SOURCE_MAPPING_FILE
    if not path.is_file():
        logger.warning("Isolation-source mapping file not found at %s; loader will return empty dict.", path)
        return {}

    mappings: Dict[str, Tuple[str, str]] = {}
    skipped_unmapped = 0
    skipped_family = 0
    skipped_low_trust = 0

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            object_id = (row.get("object_id") or "").strip()
            if not object_id:
                skipped_unmapped += 1
                continue
            if not _row_passes_family_check(row):
                skipped_family += 1
                logger.warning(
                    "Dropping family-mismatched mapping: '%s' → %s ('%s')",
                    row.get("subject_label"),
                    object_id,
                    row.get("object_label"),
                )
                continue
            if not _row_is_trusted(row):
                skipped_low_trust += 1
                continue

            raw_key = row.get("subject_label_normalized") or row.get("subject_label") or ""
            key = normalize_isolation_source_label(raw_key)
            if not key:
                continue
            object_label = (row.get("object_label") or "").strip()
            mappings[key] = (object_id, object_label)

    logger.info(
        "Loaded %d isolation-source ontology mappings from %s "
        "(skipped: %d unmapped, %d family-mismatched, %d low-trust)",
        len(mappings),
        path.name,
        skipped_unmapped,
        skipped_family,
        skipped_low_trust,
    )
    return mappings


_NORMALIZE_PUNCT_RE = re.compile(r"[-_,/]+")
_NORMALIZE_WS_RE = re.compile(r"\s+")


def normalize_isolation_source_label(label: str) -> str:
    """
    Normalize a raw BacDive isolation-source label to the loader key form.

    The mapping table stores keys with hyphens, commas, underscores, and
    slashes collapsed to single spaces, then lowercased. This matches the
    ``subject_label_normalized`` column in
    ``mappings/isolation_source_to_ontology.tsv`` (e.g. ``Bovinae-Cow,-Cattle``
    → ``bovinae cow cattle``).
    """
    if not label:
        return ""
    spaced = _NORMALIZE_PUNCT_RE.sub(" ", label.lower())
    return _NORMALIZE_WS_RE.sub(" ", spaced).strip()


__all__: List[str] = [
    "DEFAULT_ISOLATION_SOURCE_MAPPING_FILE",
    "DISALLOWED_OBJECT_SOURCES",
    "BANNED_OBJECT_LABEL_SUBSTRINGS",
    "STUB_ONTOLOGY_PREFIXES",
    "STUB_ONTOLOGY_CATEGORY",
    "iter_validation_failures",
    "load_isolation_source_mappings",
    "normalize_isolation_source_label",
]
