"""Utilities for handling mapping files from remote sources."""
import csv
from typing import Dict

import requests

# remote URL location in metpo GitHub repository for ROBOT template
# which will be used as the source of METPO mappings
METPO_ROBOT_TEMPLATE_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/src/templates/metpo_sheet.tsv"


def load_metpo_mappings(synonym_column: str) -> Dict[str, Dict[str, str]]:
    """
    Load METPO mappings from ROBOT template file (in metpo repository) for a specific synonym column.

    :param synonym_column: The column name to use for synonyms (e.g., 'bacdive keyword synonym', 'madin synonym', etc.)
    :return: Dictionary mapping synonyms to METPO curie and label information.
             Format: {synonym: {'curie': metpo_curie, 'label': metpo_label}}
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    mappings = {}

    try:
        response = requests.get(METPO_ROBOT_TEMPLATE_URL, timeout=30)
        response.raise_for_status()

        if not response.text.strip():
            raise ValueError("The contents of the file at the remote URL are empty or invalid.")

        lines = response.text.splitlines()
        # Skip the second header row and use the first row for column names
        reader = csv.DictReader(lines[2:], fieldnames=lines[0].split('\t'), delimiter='\t')
        for row in reader:
            synonym = row.get(synonym_column, '').strip()
            metpo_curie = row.get(' ID', '').strip()
            metpo_label = row.get('label', '').strip()

            if synonym and metpo_curie:
                mappings[synonym] = {
                    'curie': metpo_curie,
                    'label': metpo_label
                }

        return mappings

    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(f"Please ensure the remote URL is accessible: {e}") from e
