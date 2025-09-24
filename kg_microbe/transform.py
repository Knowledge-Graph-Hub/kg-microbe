"""Transform module."""

import logging
from pathlib import Path
from typing import List, Optional

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.bactotraits.bactotraits import BactoTraitsTransform
from kg_microbe.transform_utils.constants import (
    BACDIVE,
    BACTOTRAITS,
    CTD,
    DISBIOME,
    MADIN_ETAL,
    MEDIADIVE,
    ONTOLOGIES,
    RHEAMAPPINGS,
    UNIPROT_FUNCTIONAL_MICROBES,
    UNIPROT_HUMAN,
    WALLEN_ETAL,
)
from kg_microbe.transform_utils.ctd.ctd import CTDTransform
from kg_microbe.transform_utils.disbiome.disbiome import DisbiomeTransform
from kg_microbe.transform_utils.madin_etal.madin_etal import MadinEtAlTransform
from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.transform_utils.ontologies.ontologies_transform import (
    ONTOLOGIES_MAP,
    OntologiesTransform,
)
from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import RheaMappingsTransform
from kg_microbe.transform_utils.uniprot_functional_microbes.uniprot_functional_microbes import (
    UniprotFunctionalMicrobesTransform,
)
from kg_microbe.transform_utils.uniprot_human.uniprot_human import UniprotHumanTransform
from kg_microbe.transform_utils.wallen_etal.wallen_etal import WallenEtAlTransform

DATA_SOURCES = {
    # "DrugCentralTransform": DrugCentralTransform,
    # "OrphanetTransform": OrphanetTransform,
    # "OMIMTransform": OMIMTransform,
    # "ReactomeTransform": ReactomeTransform,
    # "GOCAMTransform": GOCAMTransform,
    # "TCRDTransform": TCRDTransform,
    # "ProteinAtlasTransform": ProteinAtlasTransform,
    # "STRINGTransform": STRINGTransform,
    ONTOLOGIES: OntologiesTransform,
    BACDIVE: BacDiveTransform,
    MEDIADIVE: MediaDiveTransform,
    MADIN_ETAL: MadinEtAlTransform,
    RHEAMAPPINGS: RheaMappingsTransform,
    BACTOTRAITS: BactoTraitsTransform,
    #UNIPROT_HUMAN: UniprotHumanTransform,
    #CTD: CTDTransform,
    #DISBIOME: DisbiomeTransform,
    #WALLEN_ETAL: WallenEtAlTransform,
    #UNIPROT_FUNCTIONAL_MICROBES: UniprotFunctionalMicrobesTransform,
}


def transform(
    input_dir: Optional[Path],
    output_dir: Optional[Path],
    sources: List[str] = None,
    show_status: bool = True,
) -> None:
    """
    Transform based on resource and class declared in DATA_SOURCES.

    Call scripts in kg_microbe/transform/[source name]/ to
    transform each source into a graph format that
    KGX can ingest directly, in either TSV or JSON format:
    https://github.com/biolink/kgx/blob/master/data-preparation.md

    :param input_dir: A string pointing to the directory to import data from.
    :param output_dir: A string pointing to the directory to output data to.
    :param sources: A list of sources to transform.
    """
    if not sources:
        # run all sources
        sources = list(DATA_SOURCES.keys())

    for source in sources:
        if source in DATA_SOURCES:
            logging.info(f"Parsing {source}")
            t = DATA_SOURCES[source](input_dir, output_dir)
            if source in ONTOLOGIES_MAP.keys():
                t.run(ONTOLOGIES_MAP[source])
            else:
                t.run(show_status=show_status)
