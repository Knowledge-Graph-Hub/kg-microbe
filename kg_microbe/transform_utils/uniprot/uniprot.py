"""Uniprot Transonform class."""

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Union

from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEMICAL_TO_ENZYME_EDGE,
    ENZYME_CATEGORY,
    NCBITAXON_PREFIX,
    ORGANISM_TO_ENZYME_EDGE,
    UNIPROT_GENOME_FEATURES,
    UNIPROT_ORG_ID_COLUMN_NAME,
    UNIPROT_PREFIX,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates


class UniprotTransform(Transform):

    """A class used to represent a transformation process for UniProt data."""

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
        self.__enz_data = {}

        source_name = UNIPROT_GENOME_FEATURES
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # replace with downloaded data filename for this source
        input_dir = str(self.input_base_dir) + "/" + self.source_name
        # Get all organisms downloaded into raw directory
        ncbi_organisms = []
        for f in os.listdir(input_dir):
            if f.endswith(".json"):
                ncbi_organisms.append(f.split(".json")[0])

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with open(self.output_node_file, "w") as node, open(self.output_edge_file, "w") as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            # Create Organism and Enzyme nodes:
            self.get_uniprot_values_from_file(
                input_dir, ncbi_organisms, self.source_name, node_writer, edge_writer
            )

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)

    def get_uniprot_values_from_file(self, input_dir, nodes, source, node_writer, edge_writer):
        """
        Process UniProt files and extract values to write to dataframes.

        This method iterates over a list of node identifiers, reads corresponding
        JSON files from the specified input directory, and extracts UniProt data.
        The extracted data is then written to node and edge writers. If a file for
        a given node does not exist, the program will exit with an error message.

        :param input_dir: The directory where input JSON files are located.
        :type input_dir: str
        :param nodes: A list of node identifiers to process.
        :type nodes: list
        :param source: The name of the source being processed (used in superclass).
        :type source: str
        :param node_writer: An object responsible for writing node data.
        :type node_writer: object
        :param edge_writer: An object responsible for writing edge data.
        :type edge_writer: object
        """
        with tqdm(total=len(nodes) + 1, desc="Processing files") as progress:
            for i in tqdm(range(len(nodes))):
                org_file = input_dir + "/" + nodes[i] + ".json"
                if not os.path.exists(org_file):
                    print("File does not exist: ", org_file, ", exiting.")
                    sys.exit()

                else:
                    with open(org_file, encoding="utf-8") as json_file:
                        values = json.load(json_file)
                        self.write_to_df(values, edge_writer, node_writer)

                progress.set_description(f"Processing Uniprot File: {nodes[i]}.yaml")
                # After each iteration, call the update method to advance the progress bar.
                progress.update()

    def parse_binding_site(self, binding_site_entry):
        """
        Extract chemical identifiers from a binding site entry.

        This method uses regular expressions to find all occurrences of ligand IDs
        within a given binding site entry string. It specifically looks for ChEBI
        identifiers and returns a list of these identifiers found in the entry.

        :param binding_site_entry: A string containing the binding site information.
        :type binding_site_entry: str
        :return: A list of ChEBI ligand identifiers extracted from the binding site entry.
        :rtype: list
        """
        chem_list = re.findall(r'/ligand_id="ChEBI:(.*?)";', binding_site_entry)

        return chem_list

    def write_to_df(self, uniprot_values, edge_writer, node_writer):
        """
        Process UniProt entries and writes organism-enzyme relationship data to CSV files.

        This method iterates over a list of UniProt entries, extracts relevant information,
        and writes it to two separate CSV files using the provided CSV writers. One file
        contains edges representing relationships between organisms and enzymes, and the
        other contains nodes representing enzymes. It also handles binding site information
        by calling `parse_binding_site` method if available in the entry.

        :param uniprot_values: A list of dictionaries where each dictionary represents a UniProt entry.
        :type uniprot_values: list
        :param edge_writer: A CSV writer object for writing edge data.
        :type edge_writer: _csv.writer
        :param node_writer: A CSV writer object for writing node data.
        :type node_writer: _csv.writer
        """
        ##To return all organism-enzyme entries
        for entry in uniprot_values:
            organism_id = (
                entry[UNIPROT_ORG_ID_COLUMN_NAME]
                if UNIPROT_ORG_ID_COLUMN_NAME in entry.keys()
                else None
            )

            # Use primary accession number as it's ID does not change, as opposed to Entry Name
            if "Entry" in entry.keys():
                self.__enz_data["id"] = entry["Entry"]

            # example response with  multiple protein names:
            # {
            #     "Organism (ID)": "100",
            #     "Entry Name": "A0A4R1H4N5_ANCAQ",
            #     "Entry": "A0A4R1H4N5",
            #     "Protein names": "Ubiquinone biosynthesis O-methyltransferase
            #                       (2-polyprenyl-6-hydroxyphenol methylase) (EC 2.1.1.222)
            #                       (3-demethylubiquinone 3-O-methyltransferase) (EC 2.1.1.64)",
            #     "EC number": "2.1.1.222; 2.1.1.64",
            # }
            if "Protein names" in entry:
                self.__enz_data["name"] = entry["Protein names"].split("(EC")[0]

            organism_id = entry["Organism (ID)"] if "Organism (ID)" in entry.keys() else None

            # Use primary accession number as it's ID does not change, as opposed to Entry Name
            if "Entry" in entry.keys():
                self.__enz_data["id"] = entry["Entry"]

            # example response with  multiple protein names:
            # {
            #     "Organism (ID)": "100",
            #     "Entry Name": "A0A4R1H4N5_ANCAQ",
            #     "Entry": "A0A4R1H4N5",
            #     "Protein names": "Ubiquinone biosynthesis O-methyltransferase
            #                       (2-polyprenyl-6-hydroxyphenol methylase) (EC 2.1.1.222)
            #                       (3-demethylubiquinone 3-O-methyltransferase) (EC 2.1.1.64)",
            #     "EC number": "2.1.1.222; 2.1.1.64",
            # }
            if "Protein names" in entry:
                self.__enz_data["name"] = entry["Protein names"].split("(EC")[0]

                ###TO DO: add synonyms here
                # print(entry['Protein names'])
                # self.__enz_data['synonyms'] = entry['Protein names'][1:].str.replace('')
                # print(self.__enz_data['synonyms'])

                # Set name as first name mentioned
                # if 'synonyms' in entry.keys() and len :
                #    self.__enz_data['name'] = entry['names'][0]

            if "EC number" in entry:
                self.__enz_data["EC number"] = entry["EC number"].replace(";", "|")

            chem_list = []
            if "Binding site" in entry:
                chem_list = self.parse_binding_site(entry["Binding site"])

            if organism_id:
                edges_data_to_write = [
                    NCBITAXON_PREFIX + str(organism_id),
                    ORGANISM_TO_ENZYME_EDGE,
                    UNIPROT_PREFIX + ":" + self.__enz_data["id"],
                    "",
                    self.source_name,
                ]

                edge_writer.writerow(edges_data_to_write)

                if len(chem_list) > 0:
                    for chem in chem_list:
                        edges_data_to_write = [
                            chem,
                            CHEMICAL_TO_ENZYME_EDGE,
                            UNIPROT_PREFIX + ":" + self.__enz_data["id"],
                            "",
                            self.source_name,
                        ]

                        edge_writer.writerow(edges_data_to_write)

            nodes_data_to_write = [
                UNIPROT_PREFIX + ":" + self.__enz_data["id"],
                ENZYME_CATEGORY,
                self.__enz_data["name"],
                "",
                "",
                self.source_name,
                "",
            ]

            node_writer.writerow(nodes_data_to_write)
