"""Disbiome Transform class."""

import csv
import json
import os
from pathlib import Path
from typing import Optional, Union
import pandas as pd

from kg_microbe.transform_utils.constants import ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF, ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE, ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF, ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE, CHEBI_PREFIX, DISBIOME_DISEASE_NAME, DISBIOME_ELEVATED, DISBIOME_ORGANISM_ID, DISBIOME_REDUCED, DISBIOME_TMP_DIR, DISEASE_CATEGORY, DISIOME_QUALITATIVE_OUTCOME, NCBI_CATEGORY, NCBITAXON_PREFIX
from kg_microbe.transform_utils.transform import Transform

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
        source_name = "disbiome"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run DisbiomeTransform."""
        if data_file is None:
            data_file = "disbiome.json"
        input_file = self.input_base_dir / data_file

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        node_filename =  self.output_node_file
        edge_filename = self.output_edge_file

        self.disease_labels_dict = {}
        DISEASE_LABELS_FILEPATH = DISBIOME_TMP_DIR / "Disbiome_Labels.csv"
        if DISEASE_LABELS_FILEPATH.exists():
            with open(DISEASE_LABELS_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    self.disease_labels_dict[row["orig_node"]] = row["entity_uri"]

        # Read JSON data into a pandas DataFrame
        with open(input_file, 'r') as file:
            json_data = json.load(file)
        # Flatten JSON data into a DataFrame
        df = pd.json_normalize(json_data)[[DISBIOME_DISEASE_NAME,DISIOME_QUALITATIVE_OUTCOME,DISBIOME_ORGANISM_ID]]
        df = df.dropna()

        with open(node_filename, "w") as nf, open(edge_filename, "w") as ef:
            nodes_file_writer = csv.writer(nf, delimiter="\t")
            edges_file_writer = csv.writer(ef, delimiter="\t")

            nodes_file_writer.writerow(self.node_header)
            edges_file_writer.writerow(self.edge_header)

            for i in range(len(df)):
                microbe = str(int(df.iloc[i].loc[DISBIOME_ORGANISM_ID]))
                disease = df.iloc[i].loc[DISBIOME_DISEASE_NAME]
                disease_id = self.disease_labels_dict[disease]
                direction = df.iloc[i].loc[DISIOME_QUALITATIVE_OUTCOME]
                #print(microbe,disease_id,direction)
                # Add disease
                nodes_file_writer.writerow([disease_id, DISEASE_CATEGORY])
                # Add microbe
                nodes_file_writer.writerow([NCBITAXON_PREFIX + microbe, NCBI_CATEGORY])
                if direction == DISBIOME_ELEVATED:
                    predicate = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF_PREDICATE
                    relation = ASSOCIATED_WITH_INCREASED_LIKELIHOOD_OF
                elif direction == DISBIOME_REDUCED:
                    predicate = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF_PREDICATE
                    relation = ASSOCIATED_WITH_DECREASED_LIKELIHOOD_OF
                # microbe-disease edge
                edges_file_writer.writerow(
                    [
                        NCBITAXON_PREFIX + microbe,
                        predicate,
                        disease_id,
                        relation,
                        "disbiome",
                    ]
                )
