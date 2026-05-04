"""Validation utilities for knowledge graph construction."""

import re
from pathlib import Path
from typing import Optional, Set

import yaml


def validate_curie(curie: str) -> bool:
    """
    Validate that a string follows CURIE format (PREFIX:ID).

    Valid CURIEs must:
    - Start with a letter
    - Have a prefix of alphanumeric characters and underscores
    - Have a colon separator
    - Have a non-empty ID part

    :param curie: String to validate
    :return: True if valid CURIE format, False otherwise
    """
    if not curie or not isinstance(curie, str):
        return False

    # CURIE pattern: PREFIX:ID where PREFIX starts with letter, contains alphanumeric/underscore
    # and ID is any non-whitespace characters
    pattern = r"^[A-Za-z][A-Za-z0-9_.]*:\S+$"
    return bool(re.match(pattern, curie))


# Namespace prefixes used by KG-Microbe custom terms
KGMICROBE_CUSTOM_PREFIXES = {
    "kgmicrobe.activity",
    "kgmicrobe.trait",
    "kgmicrobe.compound",
    "kgmicrobe.pathway",
    "kgmicrobe.ingredient",
}


def load_valid_kgm_terms(custom_curies_path: Optional[Path] = None) -> Set[str]:
    """
    Load valid KG-Microbe custom terms from custom_curies.yaml.

    :param custom_curies_path: Path to custom_curies.yaml file
                               If None, uses default path relative to this file
    :return: Set of valid CURIEs (e.g., {"kgmicrobe.trait:voges_proskauer_test_positive"})
    """
    if custom_curies_path is None:
        # Default path: kg_microbe/transform_utils/custom_curies.yaml
        base_dir = Path(__file__).parent.parent
        custom_curies_path = base_dir / "transform_utils" / "custom_curies.yaml"

    if not custom_curies_path.exists():
        return set()

    try:
        with open(custom_curies_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        kgm_terms = set()
        for prefix in KGMICROBE_CUSTOM_PREFIXES:
            section = config.get(prefix, {})
            if section:
                for term_id in section.keys():
                    kgm_terms.add(f"{prefix}:{term_id}")

        return kgm_terms
    except (OSError, yaml.YAMLError):
        return set()


def validate_kgm_term(curie: str, valid_kgm_terms: Optional[Set[str]] = None) -> bool:
    """
    Validate that a KG-Microbe custom term exists in custom_curies.yaml.

    :param curie: CURIE to validate (e.g., "kgmicrobe.trait:voges_proskauer_test_positive")
    :param valid_kgm_terms: Pre-loaded set of valid terms
                            If None, will load from custom_curies.yaml
    :return: True if the term is valid, False otherwise
    """
    if not curie:
        return False
    prefix = curie.split(":", 1)[0] if ":" in curie else ""
    if prefix not in KGMICROBE_CUSTOM_PREFIXES:
        return False

    if valid_kgm_terms is None:
        valid_kgm_terms = load_valid_kgm_terms()

    return curie in valid_kgm_terms


def validate_curie_prefix(curie: str, allowed_prefixes: Set[str]) -> bool:
    """
    Validate that a CURIE uses an allowed prefix.

    :param curie: CURIE to validate
    :param allowed_prefixes: Set of allowed prefixes (e.g., {"CHEBI", "GO", "METPO"})
    :return: True if CURIE prefix is in allowed set, False otherwise
    """
    if not validate_curie(curie):
        return False

    prefix = curie.split(":", 1)[0]
    return prefix in allowed_prefixes


def get_curie_prefix(curie: str) -> Optional[str]:
    """
    Extract prefix from a CURIE.

    :param curie: CURIE string
    :return: Prefix (e.g., "CHEBI" from "CHEBI:12345") or None if invalid
    """
    if not validate_curie(curie):
        return None

    return curie.split(":", 1)[0]


def get_curie_id(curie: str) -> Optional[str]:
    """
    Extract ID from a CURIE.

    :param curie: CURIE string
    :return: ID (e.g., "12345" from "CHEBI:12345") or None if invalid
    """
    if not validate_curie(curie):
        return None

    return curie.split(":", 1)[1]
