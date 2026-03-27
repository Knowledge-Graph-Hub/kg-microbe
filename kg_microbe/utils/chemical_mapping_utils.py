"""Utilities for chemical mapping lookups using unified chemical mappings file."""

import gzip
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Module-level cache (loaded once per process)
_UNIFIED_MAPPINGS: Optional[pd.DataFrame] = None
_NAME_INDEX: Optional[Dict[str, str]] = None
_FORMULA_INDEX: Optional[Dict[str, List[str]]] = None
_XREF_INDEX: Optional[Dict[str, str]] = None
_CACHED_PATH: Optional[Path] = None
_NEGATIVE_LOOKUP_CACHE: set = set()  # Cache for names that failed lookup


def normalize_name(name: str, strip_stereochemistry: bool = False) -> str:
    """
    Normalize chemical name for comparison.

    :param name: Chemical name to normalize
    :param strip_stereochemistry: If True, remove stereochemistry prefixes like (R)-, (S)-, D-, L-, (+)-, (-)-
    :return: Normalized name (lowercase, no punctuation)
    """
    if pd.isna(name) or not name:
        return ""
    # Convert to lowercase first
    normalized = str(name).lower().strip()

    if strip_stereochemistry:
        # Strip common stereochemistry prefixes BEFORE general punctuation removal
        # Match: (+)-, (-)-, (R)-, (S)-, D-, L- at start of string
        # Include the dash and any following spaces in the removal
        normalized = re.sub(r"^\([+-]\)-?\s*", "", normalized)  # (+)- or (-)- (with optional dash)
        normalized = re.sub(r"^\([rs]\)-?\s*", "", normalized)  # (r)- or (s)- (lowercase after .lower())
        normalized = re.sub(r"^[dl]-\s*", "", normalized)  # d- or l- (lowercase after .lower())
        normalized = normalized.strip()

    # Remove extra punctuation and normalize spaces
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def load_unified_mappings(mappings_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load unified chemical mappings file (gzipped TSV).

    Uses module-level caching to avoid reloading on multiple calls.

    :param mappings_path: Path to unified_chemical_mappings.tsv.gz
                          If None, uses default path relative to this file
    :return: DataFrame with columns: chebi_id, canonical_name, formula, synonyms, xrefs, sources
    """
    global _UNIFIED_MAPPINGS, _NAME_INDEX, _FORMULA_INDEX, _XREF_INDEX, _CACHED_PATH

    # Default path: mappings/unified_chemical_mappings.tsv.gz
    if mappings_path is None:
        base_dir = Path(__file__).parent.parent.parent
        mappings_path = base_dir / "mappings" / "unified_chemical_mappings.tsv.gz"

    # Return cached mappings if already loaded from the same path
    if _UNIFIED_MAPPINGS is not None and _CACHED_PATH == mappings_path:
        return _UNIFIED_MAPPINGS

    if not mappings_path.exists():
        raise FileNotFoundError(f"Unified mappings file not found: {mappings_path}")

    # Load gzipped TSV
    with gzip.open(mappings_path, "rt") as f:
        _UNIFIED_MAPPINGS = pd.read_csv(f, sep="\t", dtype=str)

    # Fill NaN with empty strings
    _UNIFIED_MAPPINGS = _UNIFIED_MAPPINGS.fillna("")

    # Cache the path
    _CACHED_PATH = mappings_path

    # Build indices for fast lookup
    _build_indices()

    return _UNIFIED_MAPPINGS


def _build_indices():
    """Build lookup indices from loaded mappings."""
    global _NAME_INDEX, _FORMULA_INDEX, _XREF_INDEX

    if _UNIFIED_MAPPINGS is None:
        return

    _NAME_INDEX = {}
    _FORMULA_INDEX = {}
    _XREF_INDEX = {}

    for _, row in _UNIFIED_MAPPINGS.iterrows():
        chebi_id = row["chebi_id"]

        # Index canonical name
        if row["canonical_name"]:
            norm_name = normalize_name(row["canonical_name"])
            if norm_name and norm_name not in _NAME_INDEX:
                _NAME_INDEX[norm_name] = chebi_id

        # Index synonyms
        if row["synonyms"]:
            for synonym in row["synonyms"].split("|"):
                if synonym:
                    norm_syn = normalize_name(synonym)
                    if norm_syn and norm_syn not in _NAME_INDEX:
                        _NAME_INDEX[norm_syn] = chebi_id

        # Index formula
        if row["formula"]:
            formula = row["formula"]
            if formula not in _FORMULA_INDEX:
                _FORMULA_INDEX[formula] = []
            _FORMULA_INDEX[formula].append(chebi_id)

        # Index xrefs
        if row["xrefs"]:
            for xref in row["xrefs"].split("|"):
                if xref:
                    # Normalize xref format
                    norm_xref = xref.lower().strip()
                    if norm_xref and norm_xref not in _XREF_INDEX:
                        _XREF_INDEX[norm_xref] = chebi_id


def find_chebi_by_name(name: str, synonyms: bool = True, fuzzy_stereochemistry: bool = False) -> Optional[str]:
    """
    Lookup ChEBI ID by chemical name.

    :param name: Chemical name to search for
    :param synonyms: If True, search both canonical names and synonyms
                     If False, only search canonical names
    :param fuzzy_stereochemistry: If True and exact match fails, retry with stereochemistry prefixes removed
    :return: ChEBI ID (e.g., "CHEBI:12345") or None if not found
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
    cache_key = (norm_name, synonyms, fuzzy_stereochemistry)
    if cache_key in _NEGATIVE_LOOKUP_CACHE:
        return None

    # Search in name index (includes synonyms by default)
    result = None
    if synonyms and _NAME_INDEX:
        result = _NAME_INDEX.get(norm_name)

    # Search only canonical names (no synonyms)
    if result is None and _UNIFIED_MAPPINGS is not None:
        for _, row in _UNIFIED_MAPPINGS.iterrows():
            if normalize_name(row["canonical_name"]) == norm_name:
                result = row["chebi_id"]
                break

    # If no exact match and fuzzy mode enabled, try stripping stereochemistry
    if result is None and fuzzy_stereochemistry:
        norm_name_fuzzy = normalize_name(name, strip_stereochemistry=True)
        if norm_name_fuzzy and norm_name_fuzzy != norm_name:  # Only retry if stripped version differs
            if synonyms and _NAME_INDEX:
                result = _NAME_INDEX.get(norm_name_fuzzy)

            if result is None and _UNIFIED_MAPPINGS is not None:
                for _, row in _UNIFIED_MAPPINGS.iterrows():
                    if normalize_name(row["canonical_name"]) == norm_name_fuzzy:
                        result = row["chebi_id"]
                        break

    # If lookup failed, add to negative cache to avoid retrying
    if result is None:
        _NEGATIVE_LOOKUP_CACHE.add(cache_key)

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
    Get canonical ChEBI name for a given ChEBI ID.

    :param chebi_id: ChEBI ID (e.g., "CHEBI:12345")
    :return: Canonical name or None if not found
    """
    if not chebi_id:
        return None

    # Ensure mappings are loaded
    if _UNIFIED_MAPPINGS is None:
        load_unified_mappings()

    if _UNIFIED_MAPPINGS is not None:
        # Use .loc for O(1) lookup instead of filtering
        matches = _UNIFIED_MAPPINGS.loc[_UNIFIED_MAPPINGS["chebi_id"] == chebi_id, "canonical_name"]
        if not matches.empty:
            name = matches.iloc[0]
            return name if name else None

    return None


def get_synonyms(chebi_id: str) -> List[str]:
    """
    Get all synonyms for a given ChEBI ID.

    :param chebi_id: ChEBI ID (e.g., "CHEBI:12345")
    :return: List of synonyms (may be empty)
    """
    if not chebi_id:
        return []

    # Ensure mappings are loaded
    if _UNIFIED_MAPPINGS is None:
        load_unified_mappings()

    if _UNIFIED_MAPPINGS is not None:
        # Use .loc for O(1) lookup instead of filtering
        matches = _UNIFIED_MAPPINGS.loc[_UNIFIED_MAPPINGS["chebi_id"] == chebi_id, "synonyms"]
        if not matches.empty:
            synonyms_str = matches.iloc[0]
            if synonyms_str:
                return synonyms_str.split("|")

    return []


def get_xrefs(chebi_id: str) -> List[str]:
    """
    Get all cross-references for a given ChEBI ID.

    :param chebi_id: ChEBI ID (e.g., "CHEBI:12345")
    :return: List of xrefs (e.g., ["cas:50-00-0", "kegg.compound:C00001"])
    """
    if not chebi_id:
        return []

    # Ensure mappings are loaded
    if _UNIFIED_MAPPINGS is None:
        load_unified_mappings()

    if _UNIFIED_MAPPINGS is not None:
        # Use .loc for O(1) lookup instead of filtering
        matches = _UNIFIED_MAPPINGS.loc[_UNIFIED_MAPPINGS["chebi_id"] == chebi_id, "xrefs"]
        if not matches.empty:
            xrefs_str = matches.iloc[0]
            if xrefs_str:
                return xrefs_str.split("|")

    return []


def get_formula(chebi_id: str) -> Optional[str]:
    """
    Get molecular formula for a given ChEBI ID.

    :param chebi_id: ChEBI ID (e.g., "CHEBI:12345")
    :return: Molecular formula or None if not found
    """
    if not chebi_id:
        return None

    # Ensure mappings are loaded
    if _UNIFIED_MAPPINGS is None:
        load_unified_mappings()

    if _UNIFIED_MAPPINGS is not None:
        # Use .loc for O(1) lookup instead of filtering
        matches = _UNIFIED_MAPPINGS.loc[_UNIFIED_MAPPINGS["chebi_id"] == chebi_id, "formula"]
        if not matches.empty:
            formula = matches.iloc[0]
            return formula if formula else None

    return None


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

    def find_chebi_by_name(self, name: str, synonyms: bool = True, fuzzy_stereochemistry: bool = False) -> Optional[str]:
        """
        Lookup ChEBI ID by chemical name.

        :param name: Chemical name to search for
        :param synonyms: If True, search both canonical names and synonyms
        :param fuzzy_stereochemistry: If True, retry with stereochemistry prefixes removed
        :return: ChEBI ID or None if not found
        """
        return find_chebi_by_name(name, synonyms, fuzzy_stereochemistry)

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
