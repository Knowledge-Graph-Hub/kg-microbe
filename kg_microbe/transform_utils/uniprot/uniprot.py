"""Uniprot Transonform class."""

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Union
import pandas as pd
from oaklib import get_adapter

from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEBI_PREFIX,
    CHEMICAL_CATEGORY,
    CHEMICAL_TO_EC_EDGE,
    CHEMICAL_TO_PROTEIN_EDGE,
    PROTEIN_TO_EC_EDGE,
    EC_CATEGORY,
    EC_KEY,
    EC_PREFIX,
    ENZYME_CATEGORY,
    GO_CATEGORY,
    GO_CELLULAR_COMPONENT_ID,
    GO_MOLECULAR_FUNCTION_ID,
    GO_BIOLOGICAL_PROCESS_ID,
    GO_PREFIX,
    NCBITAXON_PREFIX,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE,
    PROTEIN_TO_RHEA_EDGE,
    PROTEIN_TO_ORGANISM_EDGE,
    PROTEOME_CATEGORY,
    PROTEOME_PREFIX,
    PROTEOME_TO_ORGANISM_EDGE,
    RHEA_KEY,
    UNIPROT_GENOME_FEATURES,
    UNIPROT_ORG_ID_COLUMN_NAME,
    UNIPROT_PREFIX,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates
from kg_microbe.utils.oak_utils import get_label

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
        self.chebi_oi = get_adapter("sqlite:obo:chebi")
        self.go_oi = get_adapter("sqlite:obo:go")
        self.ec_oi = get_adapter("sqlite:obo:eccode")

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # replace with downloaded data filename for this source
        input_dir = str(self.input_base_dir) + "/" + self.source_name
        # Get all organisms downloaded into raw directory
        ncbi_organisms = []
        for f in os.listdir(input_dir):
            #if f.endswith(".json"):
            if f.endswith(".tsv"):
                ncbi_organisms.append(f.split(".tsv")[0])

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

    def _get_label_based_on_prefix(self, id):
        if id.startswith(CHEBI_PREFIX.rstrip(":")):
            return get_label(self.chebi_oi, id)
        elif id.startswith(GO_PREFIX.rstrip(":")):
            return get_label(self.go_oi, id)
        elif id.startswith(EC_PREFIX.rstrip(":")):
            return get_label(self.ec_oi, id)
        # Add more conditions as needed
        else:
            return None
        
    def _get_go_relation(self,term_id,go_oi):

        go_types = [GO_CELLULAR_COMPONENT_ID,GO_MOLECULAR_FUNCTION_ID,GO_BIOLOGICAL_PROCESS_ID]
        term_ancestors = list(go_oi.ancestors(start_curies=term_id,predicates=["rdfs:subClassOf"],reflexive=False))

        #GO:0035065 not working for some reason, handling exception for now
        try:
            go_component = list(set(term_ancestors).intersection(go_types))[0]
            if go_component == GO_CELLULAR_COMPONENT_ID:
                go_relation = PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE
            elif go_component == GO_MOLECULAR_FUNCTION_ID:
                go_relation = PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE
            elif go_component == GO_BIOLOGICAL_PROCESS_ID:
                go_relation = PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE
        except IndexError:
            go_relation = PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE

        return go_relation


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
                org_file = input_dir + "/" + nodes[i] + ".tsv"
                if not os.path.exists(org_file):
                    print("File does not exist: ", org_file, ", exiting.")
                    sys.exit()

                else:
                    df = pd.read_csv(org_file, sep="\t", low_memory=False)
                    #Remove headers from df file based on first column name
                    df = df[df[df.columns[0]] != df.columns[0]]
                    self.write_to_df(df, edge_writer, node_writer)

                progress.set_description(f"Processing Uniprot File: {nodes[i]}.tsv")
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

    def parse_go_entry(self,go_entry):
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
        go_list = re.findall("\[(.*?)\]", go_entry)
        go_list = [i for i in go_list if "GO" in i]

        return go_list
    
    def parse_rhea_entry(self,rhea_entry):
        """
        Extract rhea identifiers from a rhea ID entry.

        This method finds all RHEA IDs for the corresponding entry.

        :param rhea_entry: A string containing the rhea information.
        :type rhea_entry: str
        :return: A list of RHEA identifiers extracted from the rhea entry.
        :rtype: list
        """
        rhea_list = rhea_entry.split(" ")

        return rhea_list
    
    def parse_ec(self,ec_entry):
        """
        Extract ec identifiers from a EC Number entry.

        This method finds all EC IDs for the corresponding entry.

        :param ec_entry: A string containing the ec information.
        :type ec_entry: str
        :return: A list of EC identifiers extracted from the EC entry.
        :rtype: list
        """
        ec_list = ec_entry.split(";")

        return ec_list


    def write_to_df(self, uniprot_df, edge_writer, node_writer):
        """
        Process UniProt entries and writes organism-enzyme relationship data to CSV files.

        This method iterates over a list of UniProt entries, extracts relevant information,
        and writes it to two separate CSV files using the provided CSV writers. One file
        contains edges representing relationships between organisms and enzymes, and the
        other contains nodes representing enzymes. It also handles binding site information
        by calling `parse_binding_site` method if available in the entry.

        :param uniprot_df: A dataframe where each row represents a UniProt entry.
        :type uniprot_df: dataframe
        :param edge_writer: A CSV writer object for writing edge data.
        :type edge_writer: _csv.writer
        :param node_writer: A CSV writer object for writing node data.
        :type node_writer: _csv.writer
        """
        ##To return all organism-enzyme entries
        for i in range(len(uniprot_df)):
            entry = uniprot_df.iloc[i]
            #Drop columns that do not have an entry
            entry = entry.dropna()
            organism_id = (
                entry[UNIPROT_ORG_ID_COLUMN_NAME]
                if UNIPROT_ORG_ID_COLUMN_NAME in uniprot_df.columns
                else None
            )

            # Use primary accession number as it's ID does not change, as opposed to Entry Name
            if "Entry" in uniprot_df.columns:
                self.__enz_data["id"] = entry["Entry"]

            if "Protein names" in entry:
                self.__enz_data["name"] = entry["Protein names"].split("(EC")[0]

            organism_id = entry["Organism (ID)"] if "Organism (ID)" in uniprot_df.columns else None

            # Use primary accession number as it's ID does not change, as opposed to Entry Name
            if "Entry" in uniprot_df.columns:
                self.__enz_data["id"] = entry["Entry"]

            ec_list = []
            if "EC number" in entry:
                ec_list = self.parse_ec(entry["EC number"])

            chem_list = []
            if "Binding site" in entry:
                chem_list = self.parse_binding_site(entry["Binding site"])
            
            go_list = []
            if "Gene Ontology (GO)" in entry:
                go_list = self.parse_go_entry(entry["Gene Ontology (GO)"])

            if "Proteomes" in entry:
                self.__enz_data["Proteomes"] = str(entry["Proteomes"]).split(":")[0]

            rhea_list = []
            if "Rhea ID" in entry:
                rhea_list = self.parse_rhea_entry(entry["Rhea ID"])

            if organism_id:

                # Write protein-organism edges
                edges_data_to_write = [
                    UNIPROT_PREFIX + self.__enz_data["id"],
                    PROTEIN_TO_ORGANISM_EDGE,
                    NCBITAXON_PREFIX + str(organism_id),
                    "",
                    self.source_name,
                ]

                edge_writer.writerow(edges_data_to_write)

                # Write GO edges
                if len(go_list) > 0:
                    for go in go_list:
                        edges_data_to_write = [
                            UNIPROT_PREFIX + self.__enz_data["id"],
                            self._get_go_relation(go,self.go_oi),
                            go,
                            "",
                            self.source_name,
                        ]

                        edge_writer.writerow(edges_data_to_write)

                        # Write GO nodes
                        nodes_data_to_write = [go, "", self._get_label_based_on_prefix(go)] + [""] * (len(self.node_header)-3)
                        node_writer.writerow(nodes_data_to_write)
                        
                # Write binding site edges
                if len(chem_list) > 0:
                    for chem in chem_list:
                        edges_data_to_write = [
                            chem,
                            CHEMICAL_TO_PROTEIN_EDGE,
                            UNIPROT_PREFIX + self.__enz_data["id"],
                            "",
                            self.source_name,
                        ]

                        edge_writer.writerow(edges_data_to_write)

                        # Write CHEBI nodes
                        nodes_data_to_write = [chem, "", self._get_label_based_on_prefix(chem)] + [""] * (len(self.node_header)-3)
                        node_writer.writerow(nodes_data_to_write)

                # Write rhea edges
                if len(rhea_list) > 0:
                    for rhea in rhea_list:
                        edges_data_to_write = [
                            UNIPROT_PREFIX + self.__enz_data["id"],
                            PROTEIN_TO_RHEA_EDGE,
                            rhea,
                            "",
                            self.source_name,
                        ]

                        edge_writer.writerow(edges_data_to_write)

                        # Write Rhea nodes, oaklib is incomplete
                        nodes_data_to_write = [rhea] + [""] * (len(self.node_header)-1)
                        node_writer.writerow(nodes_data_to_write)


                # Write EC edges
                ec_list
                if len(ec_list) > 0:
                    for ec in ec_list:
                        edges_data_to_write = [
                            UNIPROT_PREFIX + self.__enz_data["id"],
                            PROTEIN_TO_EC_EDGE,
                            EC_PREFIX + ec,
                            "",
                            self.source_name,
                        ]

                        edge_writer.writerow(edges_data_to_write)

                    #Write EC nodes
                    nodes_data_to_write = [EC_PREFIX + ec, "", self._get_label_based_on_prefix(EC_PREFIX + ec)] + [""] * (len(self.node_header)-3)
                    node_writer.writerow(nodes_data_to_write)

                if "Proteomes" in self.__enz_data.keys():
                    # Write organism-proteome edges
                    edges_data_to_write = [
                        PROTEOME_PREFIX + self.__enz_data["Proteomes"],
                        PROTEOME_TO_ORGANISM_EDGE,
                        NCBITAXON_PREFIX + str(organism_id),
                        "",
                        self.source_name,
                    ]

                    edge_writer.writerow(edges_data_to_write)

                    #Write proteome node
                    nodes_data_to_write = [
                        PROTEOME_PREFIX + self.__enz_data["Proteomes"],
                        PROTEOME_CATEGORY,
                        PROTEOME_PREFIX + self.__enz_data["Proteomes"],
                        "",
                        "",
                        self.source_name] + [""] * (len(self.node_header)-6)
                    

                    node_writer.writerow(nodes_data_to_write)

            # Write protein node
            nodes_data_to_write = [
                UNIPROT_PREFIX + self.__enz_data["id"],
                ENZYME_CATEGORY,
                self.__enz_data["name"].replace('[','(').replace(']',')'),
                "",
                "",
                self.source_name] + [""] * (len(self.node_header)-6)

            node_writer.writerow(nodes_data_to_write)