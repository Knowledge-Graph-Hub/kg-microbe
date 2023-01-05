"""Top-level functions for transforming data."""

import logging
from typing import List

from kg_microbe.transform_utils.ontology import OntologyTransform
from kg_microbe.transform_utils.ontology.ontology_transform import ONTOLOGIES
from kg_microbe.transform_utils.traits.traits import TraitsTransform

DATA_SOURCES = {
    "TraitsTransform": TraitsTransform,
    "NCBITransform": OntologyTransform,
    "ChebiTransform": OntologyTransform,
    "EnvoTransform": OntologyTransform,
    "GoTransform": OntologyTransform,
}


def transform(input_dir: str, output_dir: str, sources: List[str] = None) -> None:
    """Call scripts in kg_microbe/transform/[source name]/ to transform data.

    KGX can ingest each directly, in either TSV or JSON format.
    Args:
        input_dir: A string pointing to the directory to import data from.
        output_dir: A string pointing to the directory to output data to.
        sources: A list of sources to transform.
    Returns:
        None.
    """
    if not sources:
        # run all sources
        sources = list(DATA_SOURCES.keys())

    for source in sources:
        if source in DATA_SOURCES:
            logging.info(f"Parsing {source}")
            t = DATA_SOURCES[source](input_dir, output_dir)
            if source in ONTOLOGIES.keys():
                t.run(ONTOLOGIES[source])
            else:
                t.run()
