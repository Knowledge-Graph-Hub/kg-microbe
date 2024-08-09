"""Disbiome Transform class."""

import csv
import json
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
    DISBIOME,
    DISBIOME_DISEASE_NAME,
    DISBIOME_ELEVATED,
    DISBIOME_ORGANISM_ID,
    DISBIOME_ORGANISM_NAME,
    DISBIOME_REDUCED,
    DISBIOME_TMP_DIR,
    DISEASE_CATEGORY,
    DISIOME_QUALITATIVE_OUTCOME,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
)
from kg_microbe.transform_utils.wallen_etal.wallen_etal import MICROBE_NOT_FOUND_STR
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates


class DisbiomeTransform(Transform):

    """A class used to represent a transformation process for Disbiome data."""

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
        source_name = DISBIOME
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run DisbiomeTransform."""
        if data_file is None:
            data_file = self.source_name + ".json"
        input_file = self.input_base_dir / data_file

        # Convert Disbiome taxa names to NCBITaxon IDs
        with open(input_file, "r") as file:
            json_data = json.load(file)
        # Flatten JSON data into a DataFrame
        disbiome_df = pd.json_normalize(json_data)[
            [
                DISBIOME_DISEASE_NAME,
                DISIOME_QUALITATIVE_OUTCOME,
                DISBIOME_ORGANISM_NAME,
                DISBIOME_ORGANISM_ID,
            ]
        ]
        # Cast all organism IDs to str
        disbiome_df[DISBIOME_ORGANISM_ID] = disbiome_df[DISBIOME_ORGANISM_ID].apply(
            lambda x: str(int(x)) if isinstance(x, float) and x.is_integer() else x
        )
        # Replace na values
        disbiome_df = disbiome_df.fillna(MICROBE_NOT_FOUND_STR)

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        node_filename = self.output_node_file
        edge_filename = self.output_edge_file

        # Get disease ID mappings if they exist
        #! TODO: string matching with MONDO for diseases not already mapped in Disbiome
        self.disease_labels_dict = {}
        DISEASE_LABELS_FILEPATH = DISBIOME_TMP_DIR / "Disbiome_Labels.csv"
        if DISEASE_LABELS_FILEPATH.exists():
            with open(DISEASE_LABELS_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    self.disease_labels_dict[row["orig_node"]] = row["entity_uri"]

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

        # Remove microbes that are not in NCBITaxon
        ncbitaxon_label_set = set(self.ncbitaxon_label_dict.values())
        exclude_microbes = disbiome_df[DISBIOME_ORGANISM_ID].apply(
            lambda x: NCBITAXON_PREFIX + x not in ncbitaxon_label_set or MICROBE_NOT_FOUND_STR in x
        )
        # Use the mask to set microbe_id to MICROBE_NOT_FOUND_STR where the condition is not met
        disbiome_df = disbiome_df[~exclude_microbes]

        # Get microbe ID mappings if they exist
        self.microbe_labels_dict = {}
        DISBIOME_TMP_FILEPATH = DISBIOME_TMP_DIR / "Disbiome_Microbe_Labels.csv"
        if DISBIOME_TMP_FILEPATH.exists():
            with open(DISBIOME_TMP_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    self.microbe_labels_dict[row["orig_node"]] = row["entity_uri"]
        # Convert taxa names to NCBITaxon IDs
        for i in range(len(disbiome_df)):
            microbe = disbiome_df.iloc[i].loc[DISBIOME_ORGANISM_NAME]
            microbe_id = disbiome_df.iloc[i].loc[DISBIOME_ORGANISM_ID]
            # Get microbe id from NCBITaxon
            if microbe_id == MICROBE_NOT_FOUND_STR:
                microbe_id = self.ncbitaxon_label_dict.get(microbe)
                if not microbe_id:
                    # Try with brackets around genus name
                    microbe_brackets = re.sub(r"^(\w+)", r"[\1]", microbe)
                    microbe_id = self.ncbitaxon_label_dict.get(microbe_brackets)
                    if not microbe_id:
                        microbe_id = NCBITAXON_PREFIX + MICROBE_NOT_FOUND_STR
                self.microbe_labels_dict[microbe] = microbe_id
            else:
                self.microbe_labels_dict[microbe] = NCBITAXON_PREFIX + microbe_id

        # Write to tmp file
        os.makedirs(DISBIOME_TMP_DIR, exist_ok=True)
        with open(DISBIOME_TMP_FILEPATH, mode="w", newline="") as file:
            tmp_writer = csv.writer(file, delimiter="\t")
            tmp_writer.writerow(["orig_node", "entity_uri"])
            for key, value in self.microbe_labels_dict.items():
                tmp_writer.writerow([key, value])

        with open(node_filename, "w") as nf, open(edge_filename, "w") as ef:
            nodes_file_writer = csv.writer(nf, delimiter="\t")
            edges_file_writer = csv.writer(ef, delimiter="\t")

            nodes_file_writer.writerow(self.node_header)
            edges_file_writer.writerow(self.edge_header)

            for i in range(len(disbiome_df)):
                microbe = self.microbe_labels_dict[disbiome_df.iloc[i].loc[DISBIOME_ORGANISM_NAME]]
                # Ignore microbes without an index
                if MICROBE_NOT_FOUND_STR not in microbe:
                    disease = disbiome_df.iloc[i].loc[DISBIOME_DISEASE_NAME]
                    disease_id = self.disease_labels_dict[disease]
                    direction = disbiome_df.iloc[i].loc[DISIOME_QUALITATIVE_OUTCOME]
                    # Add disease
                    nodes_file_writer.writerow(
                        [disease_id, DISEASE_CATEGORY] + [None] * (len(self.node_header) - 2)
                    )
                    # Add microbe
                    nodes_file_writer.writerow(
                        [microbe, NCBI_CATEGORY] + [None] * (len(self.node_header) - 2)
                    )
                    if direction == DISBIOME_ELEVATED:
                        predicate = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE
                        relation = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF
                    elif direction == DISBIOME_REDUCED:
                        predicate = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE
                        relation = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF
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

        drop_duplicates(node_filename)
        drop_duplicates(edge_filename)
