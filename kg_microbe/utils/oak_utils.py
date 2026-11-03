"""Description: This file contains utility functions for the OAK client."""

import sqlite3
from typing import List

from oaklib.datamodels.search import SearchConfiguration, SearchProperty
from sqlalchemy.exc import SQLAlchemyError

from kg_microbe.utils.ontology_utils import FatalOntologyError


def get_label(oi, curie: str):
    """Return a label, keeping an absent term distinct from an unusable authority."""
    try:
        labels = list(oi.labels([curie]))
    except (sqlite3.Error, SQLAlchemyError, OSError) as error:
        # These failures can occur after successful adapter preflight. They
        # must escape per-record ``except Exception`` fallback handlers too.
        raise FatalOntologyError(f"Ontology label lookup failed for {curie}: {error}") from error
    if labels:
        return labels[0][1]
    # A successful empty lookup is the ordinary missing-term fallback.
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
