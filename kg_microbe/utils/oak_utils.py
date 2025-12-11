"""Description: This file contains utility functions for the OAK client."""

from typing import List

from oaklib.datamodels.search import SearchConfiguration, SearchProperty


def get_label(oi, curie: str):
    """Return the label of a given curie via oaklib."""
    try:
        (_, label) = list(oi.labels([curie]))[0]
        return label
    except Exception as e:
        print(f"Warning: Could not get label for {curie}: {e}")
        # Return the curie without prefix as fallback
        return curie.split(":")[-1] if ":" in curie else curie


def search_by_label(oi, label: str, limit: int = 5) -> List[str]:
    """
    Search ontology for entities by label/name.

    Args:
        oi: OAK OntologyInterface instance
        label: The label/name to search for
        limit: Maximum results

    Returns:
        List of CURIEs matching the search
    """
    config = SearchConfiguration(
        properties=[SearchProperty.LABEL],
        limit=limit,
    )
    return list(oi.basic_search(label, config=config))
