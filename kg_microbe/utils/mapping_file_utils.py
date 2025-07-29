import csv
from typing import Dict
import requests

# remote URL location in metpo GitHub repository for oxygen phenotype mappings file
BACDIVE_OXYGEN_PHENOTYPE_MAPPINGS_URL = "https://raw.githubusercontent.com/berkeleybop/metpo/refs/heads/main/generated/bacdive_oxygen_phenotype_mappings.tsv"


def load_oxygen_phenotype_mappings() -> Dict[str, Dict[str, str]]:
    """Load METPO oxygen phenotype mappings file from remote location in metpo repository.

    :return: Dictionary mapping BacDive labels to METPO curie and label information.
             Format: {bacdive_label: {'curie': metpo_curie, 'label': metpo_label}}
    :rtype: Dict[str, Dict[str, str]]
    :raises requests.exceptions.HTTPError: If unable to fetch from remote URL
    :raises ValueError: If the response content is empty or invalid
    """
    mappings = {}
    
    try:
        response = requests.get(BACDIVE_OXYGEN_PHENOTYPE_MAPPINGS_URL, timeout=30)
        response.raise_for_status()
        
        if not response.text.strip():
            raise ValueError("The contents of the file at the remote URL are empty or invalid.")
        
        reader = csv.DictReader(response.text.splitlines(), delimiter='\t')
        for row in reader:
            bacdive_label = row.get('?bacdive_label', '').strip().strip('"')
            metpo_curie = row.get('?metpo_curie', '').strip().strip('"')
            metpo_label = row.get('?metpo_label', '').strip().strip('"')
            
            if bacdive_label and metpo_curie:
                mappings[bacdive_label] = {
                    'curie': metpo_curie,
                    'label': metpo_label
                }
        
        return mappings
        
    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(f"Please ensure the remote URL is accessible: {e}")