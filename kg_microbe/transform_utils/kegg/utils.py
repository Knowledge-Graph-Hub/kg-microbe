"""Utility functions for KEGG transform."""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# KEGG REST API base URL
KEGG_REST_URL = "https://rest.kegg.jp"

# Rate limiting: KEGG requests max 10 requests per second
REQUEST_DELAY = 0.11  # seconds between requests (slightly over 0.1 for safety)


def parse_kegg_ko_list_file(ko_list_file: Path) -> Dict[str, str]:
    """
    Parse KEGG KO list from downloaded file.

    File format: ko:K00001<tab>description

    :param ko_list_file: Path to downloaded ko_list.txt file
    :return: Dictionary mapping KO ID to description
    """
    ko_dict = {}

    if not ko_list_file.exists():
        logger.error(f"KEGG KO list file not found: {ko_list_file}")
        return ko_dict

    with open(ko_list_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Format: ko:K00001<tab>description
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue

            ko_id = parts[0].replace("ko:", "")  # Remove ko: prefix
            description = parts[1].strip()

            ko_dict[ko_id] = description

    logger.info(f"Parsed {len(ko_dict)} KEGG KO entries from file")
    return ko_dict


def get_kegg_ko_list() -> Dict[str, str]:
    """
    Fetch list of all KEGG Orthology (KO) entries.

    Returns dictionary mapping KO ID to description.

    :return: Dictionary mapping KO ID (e.g., 'K00001') to description
    """
    url = f"{KEGG_REST_URL}/list/ko"
    logger.info(f"Fetching KEGG KO list from {url}")

    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch KEGG KO list: {e}")
        return {}

    ko_dict = {}
    for line in response.text.strip().split("\n"):
        if not line:
            continue

        # Format: ko:K00001<tab>description
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue

        ko_id = parts[0].replace("ko:", "")  # Remove ko: prefix
        description = parts[1].strip()

        ko_dict[ko_id] = description

    logger.info(f"Fetched {len(ko_dict)} KEGG KO entries")
    return ko_dict


def get_kegg_ko_details(ko_id: str) -> Optional[Dict[str, any]]:
    """
    Fetch detailed information for a specific KEGG KO entry.

    :param ko_id: KO identifier (e.g., 'K00001')
    :return: Dictionary with KO details (name, definition, pathway, etc.)
    """
    url = f"{KEGG_REST_URL}/get/{ko_id}"

    try:
        # Rate limiting
        time.sleep(REQUEST_DELAY)

        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch details for {ko_id}: {e}")
        return None

    # Parse the response
    details = parse_kegg_entry(response.text)
    return details


def parse_kegg_entry(entry_text: str) -> Dict[str, any]:
    """
    Parse KEGG entry text format.

    KEGG entries have a specific format with sections like:
    ENTRY       K00001
    NAME        E1.1.1.1, adh
    DEFINITION  alcohol dehydrogenase [EC:1.1.1.1]
    PATHWAY     ko00010  Glycolysis / Gluconeogenesis
    MODULE      M00001  Glycolysis
    ...

    :param entry_text: Raw text from KEGG API
    :return: Dictionary with parsed fields
    """
    details = {
        "entry": "",
        "name": "",
        "definition": "",
        "pathways": [],
        "modules": [],
        "genes": [],
    }

    current_section = None
    for line in entry_text.split("\n"):
        line = line.rstrip()

        if not line:
            continue

        # Check if this is a new section (starts with non-whitespace)
        if line[0] != " ":
            parts = line.split(None, 1)
            section_name = parts[0]
            section_value = parts[1] if len(parts) > 1 else ""

            current_section = section_name

            if section_name == "ENTRY":
                details["entry"] = section_value.split()[0]
            elif section_name == "NAME":
                details["name"] = section_value
            elif section_name == "DEFINITION":
                details["definition"] = section_value
            elif section_name == "PATHWAY":
                # Format: ko00010  Glycolysis / Gluconeogenesis
                pathway_parts = section_value.split(None, 1)
                if len(pathway_parts) == 2:
                    details["pathways"].append(
                        {
                            "id": pathway_parts[0],
                            "name": pathway_parts[1],
                        }
                    )
            elif section_name == "MODULE":
                # Format: M00001  Glycolysis
                module_parts = section_value.split(None, 1)
                if len(module_parts) == 2:
                    details["modules"].append(
                        {
                            "id": module_parts[0],
                            "name": module_parts[1],
                        }
                    )
        else:
            # Continuation line (starts with whitespace)
            if current_section == "PATHWAY":
                # Additional pathway lines
                pathway_line = line.strip()
                pathway_parts = pathway_line.split(None, 1)
                if len(pathway_parts) == 2:
                    details["pathways"].append(
                        {
                            "id": pathway_parts[0],
                            "name": pathway_parts[1],
                        }
                    )
            elif current_section == "MODULE":
                # Additional module lines
                module_line = line.strip()
                module_parts = module_line.split(None, 1)
                if len(module_parts) == 2:
                    details["modules"].append(
                        {
                            "id": module_parts[0],
                            "name": module_parts[1],
                        }
                    )
            elif current_section == "NAME":
                # NAME field can continue on multiple lines
                details["name"] += " " + line.strip()
            elif current_section == "DEFINITION":
                # DEFINITION field can continue on multiple lines
                details["definition"] += " " + line.strip()

    return details


def extract_ko_ids_from_list(ko_ids: List[str], max_fetch: Optional[int] = None) -> Dict[str, Dict]:
    """
    Fetch details for a list of KO IDs.

    :param ko_ids: List of KO identifiers
    :param max_fetch: Maximum number of entries to fetch (for testing)
    :return: Dictionary mapping KO ID to details
    """
    ko_details = {}

    total = len(ko_ids)
    if max_fetch:
        total = min(total, max_fetch)
        ko_ids = ko_ids[:max_fetch]

    logger.info(f"Fetching details for {total} KO entries")

    for i, ko_id in enumerate(ko_ids):
        if (i + 1) % 100 == 0:
            logger.info(f"Fetched {i + 1}/{total} KO entries")

        details = get_kegg_ko_details(ko_id)
        if details:
            ko_details[ko_id] = details

    return ko_details
