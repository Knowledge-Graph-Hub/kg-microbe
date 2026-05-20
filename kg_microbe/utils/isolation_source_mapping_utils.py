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
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ISOLATION_SOURCE_MAPPING_FILE = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"

# Object-source ontologies that are categorically wrong for an isolation source
# UNDER THE DEFAULT EDGE SHAPE. An isolation source is a substrate / body part /
# host taxon / environment — never a quality, a phenotype assertion, or a unit.
# Source ontologies whose terms are systematically of the wrong kind belong here.
#
# Codex adversarial review #558 flagged 8 trusted rows from these prefixes
# (Acidic→PATO, Female→PATO, Juvenile→PATO, Surface-swab→SNOMED, etc.) that
# would have made organisms 'location_of' a quality, procedure, or device.
#
# EXCEPTION: PATO targets ARE legitimate when the row carries an explicit
# predicate-override token in `notes` (METPO:2000067 'isolated from host with
# quality' or METPO:2000068 'isolated from environment with quality'). Those
# tokens flip the BacDive transform's edge shape from the default
#     <source> --biolink:location_of--> <organism>
# (incoherent for a quality target) to the quality-aware
#     <organism> --METPO:2000067/2000068--> <PATO term>
# which is well-formed: a microbe IS isolated from a host/environment that bore
# the named quality. The runtime exception lives in `_row_passes_family_check`
# below; rows without the override token still hit the default ban.
#
# METPO is not exception-eligible: METPO terms describe organism phenotypes
# (psychrophilic, thermophilic, etc.), not source qualities, so the inversion
# trick doesn't help — the mapping is just wrong.
DISALLOWED_OBJECT_SOURCES: frozenset = frozenset({
    "UO",       # Unit ontology — never a substrate
    "PATO",     # Phenotypic quality — defaulted as wrong; allow when override token present
    "METPO",    # Microbial phenotype class — not the source the microbe was isolated from
    # SNOMED is admitted only via STUB_ONTOLOGY_PREFIXES; clinical-procedure
    # SNOMED terms (Surface-swab → SNOMED:258537007) are dropped by the
    # banned-substring check below.
})

# Predicate-override tokens recognized in the `notes` column. When one of these
# CURIEs appears as a whitespace-bounded token in `notes`, it becomes the
# `predicate_override` returned by `load_isolation_source_mappings`, and the
# BacDive transform emits the inverted-shape edge documented above.
PREDICATE_OVERRIDE_CURIES: frozenset = frozenset({
    "METPO:2000067",   # isolated from host with quality
    "METPO:2000068",   # isolated from environment with quality
})

# Ontology prefixes that the BacDive isolation_source mapping TSV references
# but that are NOT loaded by the ontologies transform (see ONTOLOGIES_MAP in
# kg_microbe/transform_utils/ontologies/ontologies_transform.py). Each prefix
# either has only a tiny number of distinct IDs in use, or its full load is
# impractical (mesh and NCIT are huge clinical thesauri).
#
# Two stub-import paths exist for these prefixes:
#
# 1. NCIT and mesh: a SemSQL-backed enriched stub source. The
#    OntologiesStubsTransform (kg_microbe/transform_utils/ontologies_stubs/)
#    queries data/raw/ncit.db and data/raw/mesh.db via OAK to fetch
#    rdfs:label, exact synonyms, and dbxrefs for every NCIT/mesh CURIE that
#    appears anywhere under mappings/. Output:
#    data/transformed/ontologies_stubs/{ncit,mesh}_nodes.tsv. This is the
#    preferred path — stubs carry full metadata, not just a label. The
#    BacDive inline emit at bacdive.py defers to this transform for these
#    two prefixes (see the `not in {"NCIT", "mesh"}` branch there).
#
# 2. The long-tail prefixes (PRIDE, PCO, GENEPIO, FAO, BTO, SNOMED): each
#    has 1-3 IDs in the whole repo, so the BacDive transform writes a thin
#    label-only node row inline at edge-emit time using the object_label
#    from the mapping TSV. Setting up SemSQL DBs for these would be
#    overkill.
#
# The category is biolink:OntologyClass for all stubs because they're
# typically categorical terms (host body site, microbial community,
# abscess, etc.) rather than specific anatomy / environmental features
# whose canonical metadata would come from a loaded ontology.
#
# Codex adversarial review #558 found that without stubs for these prefixes
# the BacDive transform was emitting edges to dangling node IDs because the
# ontologies pipeline didn't supply nodes for mesh:*, NCIT:*, GENEPIO:*,
# FAO:*, BTO:*, or SNOMED:* targets. The build-time check in BacDive's
# __init__ now verifies every trusted target prefix is either loaded by the
# ontologies transform OR included in this stub set, and aborts otherwise.
STUB_ONTOLOGY_PREFIXES: frozenset = frozenset({
    "PRIDE",    # 3 IDs: host body site, host body product, antibiotic treatment
    "PCO",      # 1 active ID: microbial community (PCO:1000004)
    "mesh",     # 9 IDs: Abscess, Wound, Inflammation, Built-environment, Periodontal-pocket, etc.
    "NCIT",     # 7 trusted IDs: Aspirate, Blood-culture, Lesion, Parasite, Protozoa, etc.
    "GENEPIO",  # 1 ID: caecal content
    "FAO",      # 1 ID: mycorrhiza (Fungal Anatomy Ontology)
    "BTO",      # 1 ID: wound fluid (BRENDA Tissue Ontology)
    "SNOMED",   # 1 ID after filtering: sugary food (clinical procedure rows are dropped via banned substrings)
})
STUB_ONTOLOGY_CATEGORY = "biolink:OntologyClass"

# Substrings in the *target* label that signal a family mismatch with any
# isolation-source label kind. These are facilities, documents, processes, or
# clinical instruments, not substrates / body parts / hosts / environments.
# The check is case-insensitive and substring-based.
#
# Note: NCIT and SNOMED contain a mix of substrates AND clinical procedures /
# devices. The label-substring check catches the procedure / device rows
# (e.g. NCIT:C17627 'Swab', NCIT:C16830 'Medical Device', SNOMED:258537007
# 'Surface swab') without rejecting the legitimate substrate rows in those
# prefixes (NCIT:C13347 'Aspirate', NCIT:C16403 'Blood Culture', etc.).
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
    "dependence on",
    # Codex adversarial review #558 — clinical procedure / device / process
    # labels that are NOT isolation sources:
    "swab",                # NCIT:C17627, SNOMED:258537007
    "medical device",      # NCIT:C16830
    "food production",     # FOODON:03530206 (a process, not a substrate)
    "antibiotic treatment",  # PRIDE:0001000 (a treatment, not a substrate)
)


def _extract_predicate_override(row: Dict[str, str]) -> Optional[str]:
    """
    Return the predicate-override CURIE referenced in the row's ``notes``, or ``None``.

    Scans the ``notes`` column for whitespace-bounded tokens matching any
    member of :data:`PREDICATE_OVERRIDE_CURIES`. Returns the first match.
    """
    notes = (row.get("notes") or "")
    if not notes:
        return None
    # Notes uses free-form punctuation; split conservatively on whitespace and
    # the same separators microbial_trait_mappings._resolve_biolink_predicate uses.
    cleaned = notes.replace(";", " ").replace(",", " ").replace("(", " ").replace(")", " ")
    for token in cleaned.split():
        if token in PREDICATE_OVERRIDE_CURIES:
            return token
    return None


def _row_passes_family_check(row: Dict[str, str]) -> bool:
    """
    Return ``True`` iff the row is not in a known family-mismatch class.

    Centralizes the rejection rules so the same logic is shared by the
    runtime loader and the standalone validator script.

    PATO targets are an exception: they are allowed when the row carries
    an explicit predicate-override token in ``notes`` (METPO:2000067 or
    METPO:2000068). The override re-shapes the downstream edge so that
    the PATO term is a quality of the source rather than a (broken)
    location target. METPO targets do NOT get the same exception because
    METPO terms describe organism phenotypes, not source qualities.
    """
    object_source = (row.get("object_source") or "").strip()
    object_label = (row.get("object_label") or "").strip().lower()

    if object_source in DISALLOWED_OBJECT_SOURCES:
        if object_source == "PATO" and _extract_predicate_override(row):
            pass  # allow — override predicate handles the inversion
        else:
            return False

    for banned in BANNED_OBJECT_LABEL_SUBSTRINGS:
        if banned in object_label:
            return False

    return True


def _row_is_trusted(row: Dict[str, str]) -> bool:
    """
    Apply the trust policy described in the module docstring.

    Substitution into the BacDive graph requires ``skos:exactMatch`` —
    i.e. the curator (or the auto-matcher's high-confidence pass) has
    asserted that the BacDive label and the ontology term denote the
    SAME entity. ``skos:closeMatch`` rows are NOT trusted for canonical
    node substitution because they only assert similarity; promoting
    them would connect organisms to devices, qualities, phenotype
    classes, etc., as if those were the source entity itself
    (Codex adversarial review #558 found 41 such bad-substitution
    candidates in the table — Catheter→NCIT 'Catheter Device',
    Child→PATO juvenile, Humid→NCIT humidity quality, etc.).

    Two acceptable trust paths, both requiring exactMatch:
      1. Auto-matcher hit with high confidence
         (``skos:exactMatch`` + ``confidence == 'high'``).
      2. Manual curation
         (``skos:exactMatch`` + ``mapping_justification ==
         'semapv:ManualMappingCuration'``).

    Anything else — closeMatch under any justification, low/medium
    auto-matcher confidence — is dropped, leaving the BacDive transform
    to emit its placeholder ``isolation_source:*`` node.
    """
    predicate = (row.get("predicate_id") or "").strip()
    if predicate != "skos:exactMatch":
        return False

    confidence = (row.get("confidence") or "").strip().lower()
    justification = (row.get("mapping_justification") or "").strip()
    return (confidence == "high") or (justification == "semapv:ManualMappingCuration")


def load_isolation_source_mappings(
    mapping_path: Optional[Path] = None,
) -> Dict[str, Tuple[str, str, str, Optional[str]]]:
    """
    Load trusted isolation-source mappings keyed by normalized subject label.

    The key is the lowercased ``subject_label_normalized`` (or, as a fallback,
    the lowercased ``subject_label``) — this matches the canonicalization the
    BacDive transform already applies before lookups (lowercasing the raw
    BacDive isolation-source string).

    :param mapping_path: Optional override for the TSV path. Defaults to the
        committed ``mappings/isolation_source_to_ontology.tsv`` next to this repo.
    :returns: ``{normalized_label: (object_id, object_label, object_source,
        predicate_override)}`` for every row that passes both the
        family-compatibility check and the trust policy. The fourth element is
        the override CURIE (METPO:2000067 / METPO:2000068) if the row's
        ``notes`` column references one, otherwise ``None``. Rows that are
        explicitly unmapped, family-mismatched, or below the trust threshold
        are silently skipped (with INFO-level logging of the skip count).
    """
    path = Path(mapping_path) if mapping_path else DEFAULT_ISOLATION_SOURCE_MAPPING_FILE
    if not path.is_file():
        logger.warning("Isolation-source mapping file not found at %s; loader will return empty dict.", path)
        return {}

    mappings: Dict[str, Tuple[str, str, str, Optional[str]]] = {}
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
            object_source = (row.get("object_source") or "").strip()
            predicate_override = _extract_predicate_override(row)
            mappings[key] = (object_id, object_label, object_source, predicate_override)

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
    "PREDICATE_OVERRIDE_CURIES",
    "BANNED_OBJECT_LABEL_SUBSTRINGS",
    "STUB_ONTOLOGY_PREFIXES",
    "STUB_ONTOLOGY_CATEGORY",
    "load_isolation_source_mappings",
    "normalize_isolation_source_label",
]
