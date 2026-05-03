"""
Utilities for chemical mapping lookups.

Reads the unified ingredient SSSOM mapping set
(``mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz``) and reconstructs an
entity-centric in-memory index grouped on ``object_id``. The SSSOM carries
the per-entity attributes (``canonical_name`` via ``object_label``,
``formula``/``category`` via extension columns) as well as the mappings
themselves (xrefs, canonical-name rows, synonym rows).
"""

import csv
import gzip
import re
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Module-level cache (loaded once per process). We no longer store a
# DataFrame — the SSSOM is parsed row-streamed and aggregated into the
# per-entity indices below. ``_ENTITY_COUNT`` is exposed for diagnostics
# in place of the old ``_UNIFIED_MAPPINGS`` DataFrame.
_LOADED: bool = False
_ENTITY_COUNT: int = 0
_NAME_INDEX: Optional[Dict[str, str]] = None
_CANONICAL_NAME_INDEX: Optional[Dict[str, str]] = None
_HYDRATE_FREE_NAME_INDEX: Optional[Dict[str, str]] = None
# Parent-of relationships imported from skos:narrowMatch / skos:broadMatch
# rows in the unified SSSOM. ``_PARENT_INDEX[child_curie]`` is the sorted
# list of broader (parent) CURIEs the child is narrower than. Used by
# transforms to emit ``biolink:subclass_of`` edges.
_PARENT_INDEX: Optional[Dict[str, list]] = None
_FORMULA_INDEX: Optional[Dict[str, List[str]]] = None
_XREF_INDEX: Optional[Dict[str, str]] = None
_CATEGORY_INDEX: Optional[Dict[str, str]] = None
# Primary-CURIE-keyed indices. Without these the hot-path getters
# (get_canonical_name / get_synonyms / get_xrefs / get_formula) fall back to
# scanning the full mapping on every call, which destroys throughput in any
# transform (e.g. bacdive) that enriches thousands of nodes per run.
_PRIMARY_NAME_INDEX: Optional[Dict[str, str]] = None
_PRIMARY_SYNONYMS_INDEX: Optional[Dict[str, List[str]]] = None
_PRIMARY_XREFS_INDEX: Optional[Dict[str, List[str]]] = None
_PRIMARY_FORMULA_INDEX: Optional[Dict[str, str]] = None
_CACHED_PATH: Optional[Path] = None

# Matches a trailing hydrate specifier:
#   " x n H2O", " · 6 H2O", " . 2H2O", " x 12H2O", etc.
# Separator can be "x"/"X" (via IGNORECASE), "·", ".", or "*".
# Count can be a digit sequence or the literal "n" (variable stoichiometry,
# common in MediaDive entries). Case-insensitive; anchored at end of string.
_HYDRATE_SUFFIX_RE = re.compile(
    r"\s*[x·*.]\s*(?:\d+|n)\s*h2o\s*$",
    re.IGNORECASE,
)

# Bounded LRU-style negative-lookup cache. Evicts oldest entry when full so
# memory cannot grow without bound in long-running processes. Cleared on
# mapping reload so stale misses cannot survive a mappings update.
_NEGATIVE_CACHE_MAX_SIZE = 100_000
_NEGATIVE_LOOKUP_CACHE: "OrderedDict[tuple, None]" = OrderedDict()

# Module-level Greek-letter → ASCII map used by ``normalize_name``. Kept
# module-scope so it is allocated once, not rebuilt on every call (hot path).
_GREEK_MAP = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "μ": "mu"}


def _negative_cache_add(key: tuple) -> None:
    """Add a miss to the bounded negative cache, evicting oldest if full."""
    if key in _NEGATIVE_LOOKUP_CACHE:
        _NEGATIVE_LOOKUP_CACHE.move_to_end(key)
        return
    _NEGATIVE_LOOKUP_CACHE[key] = None
    if len(_NEGATIVE_LOOKUP_CACHE) > _NEGATIVE_CACHE_MAX_SIZE:
        _NEGATIVE_LOOKUP_CACHE.popitem(last=False)


def normalize_name(
    name: str,
    strip_stereochemistry: bool = False,
    strip_hydrate: bool = False,
) -> str:
    """
    Normalize chemical name for comparison.

    :param name: Chemical name to normalize
    :param strip_stereochemistry: If True, remove stereochemistry prefixes like (R)-, (S)-, D-, L-, (+)-, (-)-
    :param strip_hydrate: If True, strip trailing hydrate suffixes like " x n H2O", " · 6 H2O", " . 2H2O"
    :return: Normalized name (lowercase, no punctuation)
    """
    if pd.isna(name) or not name:
        return ""
    # Convert to lowercase first
    normalized = str(name).lower().strip()

    # Normalize Greek letters to their spelled-out ASCII equivalents so that
    # e.g. "4-nitrophenyl β-D-glucopyranoside" (ChEBI label form) matches
    # "4-nitrophenyl beta-D-glucopyranoside" (user-provided form). Must run
    # BEFORE the non-word-char strip below, which would otherwise drop Greek
    # letters entirely and merge both forms onto a lossy "-d-..." key.
    for greek, ascii_form in _GREEK_MAP.items():
        if greek in normalized:
            normalized = normalized.replace(greek, ascii_form)

    if strip_stereochemistry:
        # Strip common stereochemistry prefixes BEFORE general punctuation removal
        # Match: (+)-, (-)-, (R)-, (S)-, D-, L- at start of string
        # Include the dash and any following spaces in the removal
        normalized = re.sub(r"^\([+-]\)-?\s*", "", normalized)  # (+)- or (-)- (with optional dash)
        normalized = re.sub(r"^\([rs]\)-?\s*", "", normalized)  # (r)- or (s)- (lowercase after .lower())
        normalized = re.sub(r"^[dl]-\s*", "", normalized)  # d- or l- (lowercase after .lower())
        normalized = normalized.strip()

    if strip_hydrate:
        # Strip trailing hydrate suffix BEFORE general punctuation removal
        # so separators like "·", "*", "." are still present to match.
        normalized = _HYDRATE_SUFFIX_RE.sub("", normalized).strip()

    # Remove extra punctuation and normalize spaces
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _iter_sssom_rows(path: Path):
    """
    Stream SSSOM data rows from a (possibly gzipped) mapping set.

    Yields ``dict`` rows. Comment/metadata lines starting with ``#`` are
    skipped; the first non-comment line is the column header.
    """
    open_fn = (
        (lambda p: gzip.open(p, "rt", encoding="utf-8", newline=""))
        if str(path).endswith(".gz")
        else (lambda p: open(p, "r", encoding="utf-8", newline=""))
    )
    with open_fn(path) as fh:
        data_lines = (line for line in fh if not line.startswith("#"))
        reader = csv.DictReader(data_lines, delimiter="\t")
        yield from reader


def load_unified_mappings(mappings_path: Optional[Path] = None) -> int:
    """
    Load the unified ingredient SSSOM mapping set.

    Reads ``mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz`` (or the
    explicit path given) and builds the in-memory per-entity indices used
    by the lookup API (``find_chebi_by_name``, ``get_canonical_name``, …).
    Per-entity attributes that SSSOM cannot express natively —
    ``object_formula`` and ``object_category`` — are read from the SSSOM
    extension columns emitted by ``scripts/consolidate_chemical_mappings.py``.

    Row-shape semantics (matches ``export_unified_sssom``):
      - ``kgm.name:`` subject + ``comment == "canonical_name"`` →
        contributes the canonical name via ``subject_label`` /
        ``object_label``.
      - ``kgm.name:`` subject + ``comment == "synonym"`` → ``subject_label``
        is added as an entity synonym.
      - other CURIE subject (not equal to object) → xref.
      - subject == object (attribute_carrier) → no-op mapping; used only
        to carry extension columns for entities with no other rows.

    Uses module-level caching to avoid reloading on multiple calls.

    :param mappings_path: Path to the unified SSSOM. If None, uses the
        default path relative to this file.
    :return: Number of distinct entities loaded (zero before first load).
    """
    global _LOADED, _ENTITY_COUNT, _CACHED_PATH

    if mappings_path is None:
        base_dir = Path(__file__).parent.parent.parent
        mappings_path = base_dir / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"

    if _LOADED and _CACHED_PATH == mappings_path:
        return _ENTITY_COUNT

    if not mappings_path.exists():
        raise FileNotFoundError(f"Unified mappings file not found: {mappings_path}")

    _CACHED_PATH = mappings_path

    # Clear negative cache on reload so stale misses cannot survive a mappings update.
    _NEGATIVE_LOOKUP_CACHE.clear()

    _build_indices(mappings_path)
    _LOADED = True
    return _ENTITY_COUNT


def _build_indices(mappings_path: Path):
    """Build lookup indices directly from the SSSOM file (streaming)."""
    global _NAME_INDEX, _CANONICAL_NAME_INDEX, _HYDRATE_FREE_NAME_INDEX
    global _FORMULA_INDEX, _XREF_INDEX, _CATEGORY_INDEX
    global _PRIMARY_NAME_INDEX, _PRIMARY_SYNONYMS_INDEX
    global _PRIMARY_XREFS_INDEX, _PRIMARY_FORMULA_INDEX
    global _PARENT_INDEX
    global _ENTITY_COUNT

    _NAME_INDEX = {}
    _CANONICAL_NAME_INDEX = {}
    _HYDRATE_FREE_NAME_INDEX = {}
    _FORMULA_INDEX = {}
    _XREF_INDEX = {}
    _CATEGORY_INDEX = {}
    _PRIMARY_NAME_INDEX = {}
    _PRIMARY_SYNONYMS_INDEX = {}
    _PRIMARY_XREFS_INDEX = {}
    _PRIMARY_FORMULA_INDEX = {}
    _PARENT_INDEX = {}

    primary_synonyms_sets: Dict[str, set] = {}
    primary_xrefs_sets: Dict[str, set] = {}
    parent_sets: Dict[str, set] = {}

    def _index_name(curie: str, name: str):
        norm = normalize_name(name)
        if norm:
            _NAME_INDEX.setdefault(norm, curie)
            norm_hf = normalize_name(name, strip_hydrate=True)
            if norm_hf and norm_hf != norm:
                _HYDRATE_FREE_NAME_INDEX.setdefault(norm_hf, curie)
        return norm

    for row in _iter_sssom_rows(mappings_path):
        curie = (row.get("object_id") or "").strip()
        if not curie:
            continue

        # First non-empty extension attributes win per object.
        if curie not in _PRIMARY_FORMULA_INDEX:
            formula = (row.get("object_formula") or "").strip()
            if formula:
                _PRIMARY_FORMULA_INDEX[curie] = formula
                _FORMULA_INDEX.setdefault(formula, []).append(curie)

        if curie not in _CATEGORY_INDEX:
            category = (row.get("object_category") or "").strip()
            if category:
                _CATEGORY_INDEX[curie] = category

        # Canonical name: first non-empty ``object_label`` per object wins.
        if curie not in _PRIMARY_NAME_INDEX:
            obj_label = (row.get("object_label") or "").strip()
            if obj_label:
                _PRIMARY_NAME_INDEX[curie] = obj_label
                norm = _index_name(curie, obj_label)
                if norm:
                    _CANONICAL_NAME_INDEX.setdefault(norm, curie)

        subject = (row.get("subject_id") or "").strip()
        if not subject:
            continue

        predicate = (row.get("predicate_id") or "").strip()
        # skos:narrowMatch / skos:broadMatch carry parent-of (asymmetric)
        # relationships that the entity-centric indices above can't express.
        # Index them as ``child → [parents]`` so transforms can emit
        # biolink:subclass_of edges from them. ``narrowMatch`` reads as
        # "subject is narrower than object" (i.e. object is the parent);
        # ``broadMatch`` is the inverse (subject is broader than object).
        if predicate == "skos:narrowMatch":
            parent_sets.setdefault(subject, set()).add(curie)
            continue  # don't also treat the row as an xref/synonym
        if predicate == "skos:broadMatch":
            parent_sets.setdefault(curie, set()).add(subject)
            continue

        if subject.startswith("kgm.name:"):
            comment = (row.get("comment") or "").strip()
            if comment == "synonym":
                syn = (row.get("subject_label") or "").strip()
                if syn:
                    primary_synonyms_sets.setdefault(curie, set()).add(syn)
                    _index_name(curie, syn)
            # canonical_name rows already handled via object_label above.
        elif subject != curie:
            # xref row: ``subject_id`` is an equivalent CURIE.
            primary_xrefs_sets.setdefault(curie, set()).add(subject)
            norm_xref = subject.lower()
            _XREF_INDEX.setdefault(norm_xref, curie)

    # Freeze accumulated sets into deterministic lists.
    for curie, syns in primary_synonyms_sets.items():
        _PRIMARY_SYNONYMS_INDEX[curie] = sorted(syns)
    for curie, xrefs in primary_xrefs_sets.items():
        _PRIMARY_XREFS_INDEX[curie] = sorted(xrefs)
    for curie, parents in parent_sets.items():
        _PARENT_INDEX[curie] = sorted(parents)

    # Count of distinct entities: any object_id that appears in at least
    # one index. Use the union of keys to avoid double-counting.
    _ENTITY_COUNT = len(
        set(_PRIMARY_NAME_INDEX)
        | set(_PRIMARY_SYNONYMS_INDEX)
        | set(_PRIMARY_XREFS_INDEX)
        | set(_PRIMARY_FORMULA_INDEX)
        | set(_CATEGORY_INDEX)
    )


def find_chebi_by_name(
    name: str,
    synonyms: bool = True,
    fuzzy_stereochemistry: bool = False,
    fuzzy_hydrate: bool = False,
) -> Optional[str]:
    """
    Lookup entry CURIE by ingredient name.

    The unified mapping is keyed on a generic CURIE (`id`), so this function
    returns any supported ontology CURIE — CHEBI for chemicals, or
    FOODON/UBERON/ENVO for food/anatomy/environment ingredients — when the
    name matches. The legacy function name is retained for API stability.

    :param name: Ingredient name to search for
    :param synonyms: If True, search both canonical names and synonyms
                     If False, only search canonical names
    :param fuzzy_stereochemistry: If True and exact match fails, retry with stereochemistry prefixes removed
    :param fuzzy_hydrate: If True and exact match fails, retry with trailing hydrate suffixes
                          (e.g. " x n H2O", " · 6 H2O") stripped from the query and also check
                          a hydrate-free index of canonical/synonym names. Useful for MediaDive
                          inorganic-hydrate ingredient names.
    :return: CURIE (e.g., "CHEBI:12345", "FOODON:00002441") or None if not found
    """
    global _NEGATIVE_LOOKUP_CACHE

    if not name:
        return None

    # Ensure mappings are loaded
    if not _LOADED:
        load_unified_mappings()

    # Try exact match first
    norm_name = normalize_name(name)
    if not norm_name:
        return None

    # Check negative lookup cache - skip if we've already failed to find this name
    cache_key = (norm_name, synonyms, fuzzy_stereochemistry, fuzzy_hydrate)
    if cache_key in _NEGATIVE_LOOKUP_CACHE:
        _NEGATIVE_LOOKUP_CACHE.move_to_end(cache_key)  # LRU touch
        return None

    # Select index: full (with synonyms) or canonical-only.
    # Both are dicts, giving O(1) lookups and eliminating the prior iterrows scan.
    primary_index = _NAME_INDEX if synonyms else _CANONICAL_NAME_INDEX

    result = None
    if primary_index:
        result = primary_index.get(norm_name)

    # If no exact match and fuzzy mode enabled, try stripping stereochemistry.
    # Only retry if the stripped form actually differs from the exact form.
    if result is None and fuzzy_stereochemistry:
        norm_name_fuzzy = normalize_name(name, strip_stereochemistry=True)
        if norm_name_fuzzy and norm_name_fuzzy != norm_name and primary_index:
            result = primary_index.get(norm_name_fuzzy)

    # Hydrate fallback:
    #   1) Strip trailing hydrate suffix from the query and retry against the
    #      primary index (handles query "CaCl2 x 2 H2O" → entry "calcium chloride").
    #   2) Look up the un-stripped query in the hydrate-free index (handles the
    #      reverse: query "calcium chloride" → canonical "calcium chloride x n H2O").
    if result is None and fuzzy_hydrate:
        norm_name_no_hydrate = normalize_name(name, strip_hydrate=True)
        if norm_name_no_hydrate and norm_name_no_hydrate != norm_name and primary_index:
            result = primary_index.get(norm_name_no_hydrate)
        if result is None and _HYDRATE_FREE_NAME_INDEX:
            result = _HYDRATE_FREE_NAME_INDEX.get(norm_name)

    # If lookup failed, add to bounded negative cache to avoid retrying
    if result is None:
        _negative_cache_add(cache_key)

    return result


def find_chebi_by_formula(formula: str) -> List[str]:
    """
    Lookup ChEBI IDs by molecular formula.

    Note: May return multiple ChEBI IDs if formula matches multiple compounds.

    :param formula: Molecular formula (e.g., "H2O", "C6H12O6")
    :return: List of ChEBI IDs (may be empty if not found)
    """
    if not formula:
        return []

    # Ensure mappings are loaded
    if not _LOADED:
        load_unified_mappings()

    if _FORMULA_INDEX:
        return _FORMULA_INDEX.get(formula, [])

    return []


def find_chebi_by_xref(xref: str) -> Optional[str]:
    """
    Lookup ChEBI ID by cross-reference (KEGG, CAS, etc.).

    :param xref: Cross-reference identifier (e.g., "cas:50-00-0", "kegg.compound:C00001")
    :return: ChEBI ID (e.g., "CHEBI:12345") or None if not found
    """
    if not xref:
        return None

    # Ensure mappings are loaded
    if not _LOADED:
        load_unified_mappings()

    # Normalize xref format
    norm_xref = xref.lower().strip()

    if _XREF_INDEX:
        return _XREF_INDEX.get(norm_xref)

    return None


def get_canonical_name(chebi_id: str) -> Optional[str]:
    """
    Get canonical name for a given CURIE.

    :param chebi_id: Primary CURIE (e.g., "CHEBI:12345", "FOODON:00002441")
    :return: Canonical name or None if not found
    """
    if not chebi_id:
        return None
    if not _LOADED:
        load_unified_mappings()
    if _PRIMARY_NAME_INDEX is None:
        return None
    name = _PRIMARY_NAME_INDEX.get(chebi_id)
    return name if name else None


def get_synonyms(chebi_id: str) -> List[str]:
    """
    Get all synonyms for a given CURIE.

    :param chebi_id: Primary CURIE (e.g., "CHEBI:12345")
    :return: List of synonyms (may be empty)
    """
    if not chebi_id:
        return []
    if not _LOADED:
        load_unified_mappings()
    if _PRIMARY_SYNONYMS_INDEX is None:
        return []
    return list(_PRIMARY_SYNONYMS_INDEX.get(chebi_id, ()))


def get_xrefs(chebi_id: str) -> List[str]:
    """
    Get all cross-references for a given CURIE.

    :param chebi_id: Primary CURIE (e.g., "CHEBI:12345")
    :return: List of xrefs (e.g., ["cas:50-00-0", "kegg.compound:C00001"])
    """
    if not chebi_id:
        return []
    if not _LOADED:
        load_unified_mappings()
    if _PRIMARY_XREFS_INDEX is None:
        return []
    return list(_PRIMARY_XREFS_INDEX.get(chebi_id, ()))


def get_parents(curie: str) -> List[str]:
    """
    Get parent CURIEs for an entity (asymmetric narrowMatch / broadMatch).

    Returns the list of broader / parent CURIEs that ``curie`` is a kind-of.
    Populated from MIM ``skos:narrowMatch`` rows in the unified SSSOM (where
    e.g. ``MIM:Vermont_Soil → ENVO:00001998 narrowMatch`` translates to
    ``kgmicrobe.ingredient:vermont_soil`` having parent ``ENVO:00001998``).

    Transforms call this when emitting an ingredient / solution / sample edge
    to also write a ``biolink:subclass_of`` edge to the broader OBO term, so
    OBO-aware reasoners can navigate from kg-microbe-minted CURIEs back to
    the canonical hierarchy.

    :param curie: child CURIE
    :return: sorted list of parent CURIEs (empty if no narrowMatch row exists)
    """
    if not curie:
        return []
    if not _LOADED:
        load_unified_mappings()
    if _PARENT_INDEX is None:
        return []
    return list(_PARENT_INDEX.get(curie, ()))


def get_formula(chebi_id: str) -> Optional[str]:
    """
    Get molecular formula for a given CURIE.

    :param chebi_id: Primary CURIE (e.g., "CHEBI:12345")
    :return: Molecular formula or None if not found
    """
    if not chebi_id:
        return None
    if not _LOADED:
        load_unified_mappings()
    if _PRIMARY_FORMULA_INDEX is None:
        return None
    formula = _PRIMARY_FORMULA_INDEX.get(chebi_id)
    return formula if formula else None


def get_category(curie: str) -> Optional[str]:
    """
    Get the biolink category stored for a CURIE in the unified mapping.

    Category is a data column on each row of the unified mapping — there is
    no prefix-to-category table in code. Returns None if the CURIE is not
    present or has no category recorded.

    :param curie: Primary CURIE (e.g. "CHEBI:15377", "FOODON:00002441")
    :return: Biolink category (e.g. "biolink:ChemicalEntity",
             "biolink:Food") or None if not found.
    """
    if not curie:
        return None
    if not _LOADED:
        load_unified_mappings()
    if _CATEGORY_INDEX:
        return _CATEGORY_INDEX.get(curie)
    return None


def get_node_enrichment(curie: str) -> Dict[str, str]:
    """
    Return KGX enrichment fields for a chemical/ingredient CURIE.

    Returns a dict with keys ``xref``, ``synonym``, ``name`` suitable for
    populating the corresponding KGX node columns. Values are pipe-joined
    strings (KGX multivalued convention) or empty strings when absent.

    - ``xref``: equivalent CURIEs from the unified mapping's ``xrefs`` column.
      Under KGX semantics these are cross-references (CURIE-shaped), not names.
    - ``synonym``: alternative free-text names from the ``synonyms`` column.
    - ``name``: canonical name for the CURIE, or empty string when unknown.

    :param curie: Primary CURIE (e.g. "CHEBI:15377", "FOODON:00002441").
    :return: Dict with ``xref``, ``synonym``, ``name`` keys.
    """
    empty = {"xref": "", "synonym": "", "name": ""}
    if not curie:
        return empty
    xrefs = get_xrefs(curie)
    synonyms = get_synonyms(curie)
    name = get_canonical_name(curie) or ""
    return {
        "xref": "|".join(xrefs) if xrefs else "",
        "synonym": "|".join(synonyms) if synonyms else "",
        "name": name,
    }


class ChemicalMappingLoader:

    """
    Loader class for unified chemical mappings.

    Provides convenient API for chemical entity lookups.
    Uses module-level caching internally.
    """

    def __init__(self, mappings_path: Optional[Path] = None):
        """
        Initialize loader.

        :param mappings_path: Path to unified_chemical_mappings.tsv.gz
                              If None, uses default path
        """
        self.mappings_path = mappings_path
        # Load mappings on initialization
        load_unified_mappings(self.mappings_path)

    def find_chebi_by_name(
        self,
        name: str,
        synonyms: bool = True,
        fuzzy_stereochemistry: bool = False,
        fuzzy_hydrate: bool = False,
    ) -> Optional[str]:
        """
        Lookup ChEBI ID by chemical name.

        :param name: Chemical name to search for
        :param synonyms: If True, search both canonical names and synonyms
        :param fuzzy_stereochemistry: If True, retry with stereochemistry prefixes removed
        :param fuzzy_hydrate: If True, retry with trailing hydrate suffixes stripped
        :return: ChEBI ID or None if not found
        """
        return find_chebi_by_name(name, synonyms, fuzzy_stereochemistry, fuzzy_hydrate)

    def find_chebi_by_formula(self, formula: str) -> List[str]:
        """
        Lookup ChEBI IDs by molecular formula.

        :param formula: Molecular formula
        :return: List of ChEBI IDs
        """
        return find_chebi_by_formula(formula)

    def find_chebi_by_xref(self, xref: str) -> Optional[str]:
        """
        Lookup ChEBI ID by cross-reference.

        :param xref: Cross-reference identifier
        :return: ChEBI ID or None if not found
        """
        return find_chebi_by_xref(xref)

    def get_canonical_name(self, chebi_id: str) -> Optional[str]:
        """
        Get canonical ChEBI name.

        :param chebi_id: ChEBI ID
        :return: Canonical name or None if not found
        """
        return get_canonical_name(chebi_id)

    def get_synonyms(self, chebi_id: str) -> List[str]:
        """
        Get all synonyms for ChEBI ID.

        :param chebi_id: ChEBI ID
        :return: List of synonyms
        """
        return get_synonyms(chebi_id)

    def get_xrefs(self, chebi_id: str) -> List[str]:
        """
        Get all cross-references for ChEBI ID.

        :param chebi_id: ChEBI ID
        :return: List of xrefs
        """
        return get_xrefs(chebi_id)

    def get_parents(self, curie: str) -> List[str]:
        """
        Get parent CURIEs (asymmetric narrowMatch) for an entity.

        :param curie: child CURIE
        :return: List of parent CURIEs (empty if none recorded)
        """
        return get_parents(curie)

    def get_formula(self, chebi_id: str) -> Optional[str]:
        """
        Get molecular formula for ChEBI ID.

        :param chebi_id: ChEBI ID
        :return: Molecular formula or None if not found
        """
        return get_formula(chebi_id)

    def get_category(self, curie: str) -> Optional[str]:
        """
        Get the biolink category recorded for a CURIE.

        :param curie: Primary CURIE.
        :return: Biolink category string or None.
        """
        return get_category(curie)

    def get_node_enrichment(self, curie: str) -> Dict[str, str]:
        """
        Get KGX node enrichment fields (xref, synonym, name) for a CURIE.

        :param curie: Primary CURIE.
        :return: Dict with ``xref``, ``synonym``, ``name`` keys.
        """
        return get_node_enrichment(curie)
