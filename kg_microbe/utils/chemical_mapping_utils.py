"""Utilities for chemical mapping lookups using unified chemical mappings file."""

import gzip
import re
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Module-level cache (loaded once per process)
_UNIFIED_MAPPINGS: Optional[pd.DataFrame] = None
_NAME_INDEX: Optional[Dict[str, str]] = None
_CANONICAL_NAME_INDEX: Optional[Dict[str, str]] = None
_HYDRATE_FREE_NAME_INDEX: Optional[Dict[str, str]] = None
_FORMULA_INDEX: Optional[Dict[str, List[str]]] = None
_XREF_INDEX: Optional[Dict[str, str]] = None
_CATEGORY_INDEX: Optional[Dict[str, str]] = None
# Primary-CURIE-keyed indices. Without these the hot-path getters
# (get_canonical_name / get_synonyms / get_xrefs / get_formula) fall back to
# scanning the 119k-row DataFrame on every call, which destroys throughput in
# any transform (e.g. bacdive) that enriches thousands of nodes per run.
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
    _GREEK_MAP = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "μ": "mu"}
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


def _read_unified_tsv_gz(path: Path) -> pd.DataFrame:
    """Read one unified mapping TSV.GZ into a DataFrame (schema-tolerant)."""
    # quoting=3 (QUOTE_NONE) handles chemical names with quote characters.
    # on_bad_lines="skip" tolerates rare legacy rows with embedded tabs.
    with gzip.open(path, "rt") as f:
        df = pd.read_csv(
            f,
            sep="\t",
            dtype=str,
            quoting=3,
            engine="python",
            on_bad_lines="skip",
        )
    return df.fillna("")


def load_unified_mappings(mappings_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load unified chemical mappings file(s) (gzipped TSV).

    The unified mapping is split across two files:

      - ``unified_chemical_mappings.tsv.gz`` — chemicals, compounds, and
        media-ingredient prefixes (CHEBI, kgmicrobe.compound, NCIT, FOODON,
        UBERON, ENVO).
      - ``unified_other_mappings.tsv.gz`` — reserved for non-chemical,
        non-ingredient mappings. Optional; loaded if present.

    Both files share the same schema; this function concatenates them into
    a single in-memory DataFrame so downstream lookup APIs are unchanged.

    Uses module-level caching to avoid reloading on multiple calls.

    :param mappings_path: Path to unified_chemical_mappings.tsv.gz. If None,
        uses the default path relative to this file and also looks for the
        sibling ``unified_other_mappings.tsv.gz`` in the same directory.
    :return: DataFrame with columns: id, category, canonical_name, formula,
             synonyms, xrefs, sources. Legacy baselines using ``chebi_id`` as
             the primary column are silently upgraded to ``id`` in memory.
    """
    global _UNIFIED_MAPPINGS, _NAME_INDEX, _HYDRATE_FREE_NAME_INDEX
    global _FORMULA_INDEX, _XREF_INDEX, _CATEGORY_INDEX, _CACHED_PATH

    # Default path: mappings/unified_chemical_mappings.tsv.gz
    if mappings_path is None:
        base_dir = Path(__file__).parent.parent.parent
        mappings_path = base_dir / "mappings" / "unified_chemical_mappings.tsv.gz"

    # Return cached mappings if already loaded from the same path
    if _UNIFIED_MAPPINGS is not None and _CACHED_PATH == mappings_path:
        return _UNIFIED_MAPPINGS

    if not mappings_path.exists():
        raise FileNotFoundError(f"Unified mappings file not found: {mappings_path}")

    # Always load the chemical file.
    frames = [_read_unified_tsv_gz(mappings_path)]

    # Optionally load the sibling "other" file, if it lives alongside the
    # chemical file. Missing is fine — that file is only written when it has
    # at least one row.
    other_path = mappings_path.with_name("unified_other_mappings.tsv.gz")
    if other_path.exists() and other_path != mappings_path:
        frames.append(_read_unified_tsv_gz(other_path))

    _UNIFIED_MAPPINGS = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    # Upgrade legacy baselines that used `chebi_id` as the primary column.
    if "id" not in _UNIFIED_MAPPINGS.columns and "chebi_id" in _UNIFIED_MAPPINGS.columns:
        _UNIFIED_MAPPINGS = _UNIFIED_MAPPINGS.rename(columns={"chebi_id": "id"})
    if "category" not in _UNIFIED_MAPPINGS.columns:
        # Legacy files omit category. Default to ChemicalSubstance for CHEBI
        # entries, empty otherwise — downstream code must tolerate empty.
        _UNIFIED_MAPPINGS["category"] = _UNIFIED_MAPPINGS["id"].map(
            lambda x: "biolink:ChemicalSubstance" if str(x).startswith("CHEBI:") else ""
        )

    # Cache the path
    _CACHED_PATH = mappings_path

    # Clear negative cache on reload so stale misses cannot survive a mappings update.
    _NEGATIVE_LOOKUP_CACHE.clear()

    # Build indices for fast lookup
    _build_indices()

    return _UNIFIED_MAPPINGS


def _build_indices():
    """Build lookup indices from loaded mappings."""
    global _NAME_INDEX, _CANONICAL_NAME_INDEX, _HYDRATE_FREE_NAME_INDEX
    global _FORMULA_INDEX, _XREF_INDEX, _CATEGORY_INDEX
    global _PRIMARY_NAME_INDEX, _PRIMARY_SYNONYMS_INDEX
    global _PRIMARY_XREFS_INDEX, _PRIMARY_FORMULA_INDEX

    if _UNIFIED_MAPPINGS is None:
        return

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

    for _, row in _UNIFIED_MAPPINGS.iterrows():
        curie = row["id"]

        # Index category so downstream transforms can classify without prefix routing.
        category = row.get("category", "")
        if curie and category:
            _CATEGORY_INDEX[curie] = category

        # Primary-key indices: O(1) lookups for the hot-path getters below.
        if curie:
            if row["canonical_name"]:
                _PRIMARY_NAME_INDEX[curie] = row["canonical_name"]
            if row["synonyms"]:
                _PRIMARY_SYNONYMS_INDEX[curie] = [
                    s for s in row["synonyms"].split("|") if s
                ]
            if row["xrefs"]:
                _PRIMARY_XREFS_INDEX[curie] = [
                    x for x in row["xrefs"].split("|") if x
                ]
            if row["formula"]:
                _PRIMARY_FORMULA_INDEX[curie] = row["formula"]

        # Index canonical name (both full name index and canonical-only index)
        if row["canonical_name"]:
            norm_name = normalize_name(row["canonical_name"])
            if norm_name:
                if norm_name not in _NAME_INDEX:
                    _NAME_INDEX[norm_name] = curie
                if norm_name not in _CANONICAL_NAME_INDEX:
                    _CANONICAL_NAME_INDEX[norm_name] = curie
            # Hydrate-free index: only add if stripping actually changed the name,
            # so lookups with a hydrate suffix can reach the anhydrous entry.
            norm_hydrate_free = normalize_name(row["canonical_name"], strip_hydrate=True)
            if norm_hydrate_free and norm_hydrate_free != norm_name:
                _HYDRATE_FREE_NAME_INDEX.setdefault(norm_hydrate_free, curie)

        # Index synonyms (name index only)
        if row["synonyms"]:
            for synonym in row["synonyms"].split("|"):
                if synonym:
                    norm_syn = normalize_name(synonym)
                    if norm_syn and norm_syn not in _NAME_INDEX:
                        _NAME_INDEX[norm_syn] = curie
                    norm_syn_hydrate_free = normalize_name(synonym, strip_hydrate=True)
                    if norm_syn_hydrate_free and norm_syn_hydrate_free != norm_syn:
                        _HYDRATE_FREE_NAME_INDEX.setdefault(norm_syn_hydrate_free, curie)

        # Index formula
        if row["formula"]:
            formula = row["formula"]
            if formula not in _FORMULA_INDEX:
                _FORMULA_INDEX[formula] = []
            _FORMULA_INDEX[formula].append(curie)

        # Index xrefs
        if row["xrefs"]:
            for xref in row["xrefs"].split("|"):
                if xref:
                    # Normalize xref format
                    norm_xref = xref.lower().strip()
                    if norm_xref and norm_xref not in _XREF_INDEX:
                        _XREF_INDEX[norm_xref] = curie


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
    if _UNIFIED_MAPPINGS is None:
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
    if _UNIFIED_MAPPINGS is None:
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
    if _UNIFIED_MAPPINGS is None:
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
    if _UNIFIED_MAPPINGS is None:
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
    if _UNIFIED_MAPPINGS is None:
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
    if _UNIFIED_MAPPINGS is None:
        load_unified_mappings()
    if _PRIMARY_XREFS_INDEX is None:
        return []
    return list(_PRIMARY_XREFS_INDEX.get(chebi_id, ()))


def get_formula(chebi_id: str) -> Optional[str]:
    """
    Get molecular formula for a given CURIE.

    :param chebi_id: Primary CURIE (e.g., "CHEBI:12345")
    :return: Molecular formula or None if not found
    """
    if not chebi_id:
        return None
    if _UNIFIED_MAPPINGS is None:
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
    :return: Biolink category (e.g. "biolink:ChemicalSubstance",
             "biolink:Food") or None if not found.
    """
    if not curie:
        return None
    if _UNIFIED_MAPPINGS is None:
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
