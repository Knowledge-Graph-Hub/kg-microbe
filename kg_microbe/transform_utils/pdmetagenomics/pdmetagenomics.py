"""PdMetagenomics Transform class."""

import csv
import os
import re
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from kg_microbe.transform_utils.constants import (
    ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF,
    ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE,
    ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF,
    ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE,
    DISEASE_CATEGORY,
    NCBI_CATEGORY,
    PDMETAGENOMICS_TMP_DIR,
)
from kg_microbe.transform_utils.transform import Transform

# Constants
PD_METAGENOMIC_TAB_NAME = "Supplementary Data 1"
FDR_COLUMN = "FDR"
SPECIES_COLUMN = "Species"
PD_ABUNDANCE_COLUMN = "RA in PD"
NHC_ABUNDANCE_COLUMN = "RA in NHC"
MICROBE_NOT_FOUND_STR = "not_found"
PARKINSONS_DISEASE_MONDO_ID = "MONDO:0005180"


class PdMetagenomicsTransform(Transform):

    """A class used to represent a transformation process for PdMetagenomics data."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """
        Initialize the class with optional input and output directories.

        This constructor initializes the class with the provided input and output
        directories, sets up internal data structures, and calls the superclass
        initializer with a specific source name.

        :param input_dir: The directory where input files are located.
                          If None, a default directory may be used.
        :type input_dir: Optional[Path]
        :param output_dir: The directory where output files will be saved.
                           If None, a default directory may be used.
        :type output_dir: Optional[Path]
        """
        source_name = "PdMetagenomics"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run PdMetagenomicsTransform."""
        if data_file is None:
            data_file = "PdMetagenomics.xlsx"
        input_file = self.input_base_dir / data_file

        pdmetagenomics_df = pd.read_excel(
            input_file, skiprows=3, sheet_name=PD_METAGENOMIC_TAB_NAME
        )
        pdmetagenomics_df[FDR_COLUMN] = pd.to_numeric(
            pdmetagenomics_df[FDR_COLUMN], errors="coerce"
        )

        significant_pdmetagenomics_df = pdmetagenomics_df[
            pdmetagenomics_df[FDR_COLUMN].apply(lambda x: isinstance(x, float))
        ]
        significant_pdmetagenomics_df = significant_pdmetagenomics_df.dropna(subset=[FDR_COLUMN])
        significant_pdmetagenomics_df = pdmetagenomics_df[(pdmetagenomics_df[FDR_COLUMN] < 0.05)]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        node_filename = self.output_node_file
        edge_filename = self.output_edge_file

        self.microbe_labels_dict = {}
        PD_METAGENOMICS_TMP_FILEPATH = PDMETAGENOMICS_TMP_DIR / "Pd_Microbe_Labels.csv"
        if PD_METAGENOMICS_TMP_FILEPATH.exists():
            with open(PD_METAGENOMICS_TMP_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    self.microbe_labels_dict[row["orig_node"]] = row["entity_uri"]

        else:
            # Get all NCBITaxon IDs
            self.ncbitaxon_label_dict = {}
            #! TODO: Find a better way to get this path
            ncbitaxon_nodes_file = (
                Path(__file__).parents[3]
                / "data"
                / "transformed"
                / "ontologies"
                / "ncbitaxon_nodes.tsv"
            )
            # Get NCBITaxon IDs from ontology nodes file
            if ncbitaxon_nodes_file.exists():
                with open(ncbitaxon_nodes_file, "r") as file:
                    csv_reader = csv.DictReader(file, delimiter="\t")
                    for row in csv_reader:
                        self.ncbitaxon_label_dict[row["name"]] = row["id"]

            # Convert taxa names to NCBITaxon IDs
            for i in range(len(significant_pdmetagenomics_df)):
                species = significant_pdmetagenomics_df.iloc[i].loc[SPECIES_COLUMN]
                species_id = self.ncbitaxon_label_dict.get(species)
                if not species_id:
                    # Try with brackets around genus name
                    species_brackets = re.sub(r"^(\w+)", r"[\1]", species)
                    species_id = self.ncbitaxon_label_dict.get(species_brackets)
                    if not species_id:
                        species_id = MICROBE_NOT_FOUND_STR
                self.microbe_labels_dict[species] = species_id
                # Converts 58 out of 79 significantly abundant microbes

            # Write to tmp file
            os.makedirs(PDMETAGENOMICS_TMP_DIR, exist_ok=True)
            with open(PD_METAGENOMICS_TMP_FILEPATH, mode="w", newline="") as file:
                tmp_writer = csv.writer(file, delimiter="\t")
                tmp_writer.writerow(["orig_node", "entity_uri"])
                for key, value in self.microbe_labels_dict.items():
                    tmp_writer.writerow([key, value])

        with open(node_filename, "w") as nf, open(edge_filename, "w") as ef:
            nodes_file_writer = csv.writer(nf, delimiter="\t")
            edges_file_writer = csv.writer(ef, delimiter="\t")

            nodes_file_writer.writerow(self.node_header)
            edges_file_writer.writerow(self.edge_header)

            disease_id = PARKINSONS_DISEASE_MONDO_ID
            nodes_file_writer.writerow([disease_id, DISEASE_CATEGORY])

            for i in range(len(significant_pdmetagenomics_df)):
                microbe = self.microbe_labels_dict[
                    significant_pdmetagenomics_df.iloc[i].loc[SPECIES_COLUMN]
                ]
                if microbe != MICROBE_NOT_FOUND_STR:
                    predicate, relation = self.get_disease_direction(
                        significant_pdmetagenomics_df.iloc[i].loc[PD_ABUNDANCE_COLUMN],
                        significant_pdmetagenomics_df.iloc[i].loc[NHC_ABUNDANCE_COLUMN],
                    )
                    # Add microbe
                    nodes_file_writer.writerow([microbe, NCBI_CATEGORY])
                    # microbe-disease edge
                    edges_file_writer.writerow(
                        [
                            microbe,
                            predicate,
                            disease_id,
                            relation,
                            self.source_name,
                        ]
                    )

    def get_disease_direction(self, pd_abundance, nhc_abundance):
        """
        Determine direction of microbe-disease relationship.

        :param pd_abundance: Abundance value in PD group.
        :type pd_abundance: float
        :param nhc_abundance: Abundance value in NHC group.
        :type nhc_abundance: float
        """
        if pd_abundance > nhc_abundance:
            direction = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE
            relation = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF
        elif nhc_abundance > pd_abundance:
            direction = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE
            relation = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF

        return direction, relation
