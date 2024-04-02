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
import tarfile
from io import StringIO

from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEMICAL_TO_PROTEIN_EDGE,
    PROTEIN_TO_EC_EDGE,
    EC_PREFIX,
    ENZYME_CATEGORY,
    GO_CELLULAR_COMPONENT_ID,
    GO_MOLECULAR_FUNCTION_ID,
    GO_BIOLOGICAL_PROCESS_ID,
    NCBITAXON_PREFIX,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE,
    PROTEIN_TO_RHEA_EDGE,
    PROTEIN_TO_ORGANISM_EDGE,
    PROTEOME_CATEGORY,
    PROTEOME_PREFIX,
    PROTEOME_TO_ORGANISM_EDGE,
    RAW_DATA_DIR,
    UNIPROT_BINDING_SITE_COLUMN_NAME,
    UNIPROT_EC_ID_COLUMN_NAME,
    UNIPROT_GENOME_FEATURES,
    UNIPROT_GO_COLUMN_NAME,
    UNIPROT_ORG_ID_COLUMN_NAME,
    UNIPROT_PREFIX,
    UNIPROT_PROTEIN_ID_COLUMN_NAME,
    UNIPROT_PROTEIN_NAME_COLUMN_NAME,
    UNIPROT_PROTEOME_COLUMN_NAME,
    UNIPROT_PROTEOMES_FILE,
    UNIPROT_RHEA_ID_COLUMN_NAME,
    UNIPROT_TMP_DIR,
)

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates
from kg_microbe.utils.oak_utils import get_label

# file to keep track of obsolete terms from GO not included in graph
OBSOLETE_TERMS_CSV_FILE = UNIPROT_TMP_DIR / "go_obsolete_terms.csv"
GO_CATEGORY_TREES_FILE = UNIPROT_TMP_DIR / "go_category_trees.csv"

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
        self.go_oi = get_adapter("sqlite:obo:go")
        # Check if the file already exists
        if not GO_CATEGORY_TREES_FILE.exists():
            self._get_go_category_trees(self.go_oi)
        self.go_category_trees_df = pd.read_csv(GO_CATEGORY_TREES_FILE,sep='\t',low_memory=False)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        # get descendants of important GO categories for relationship mapping
        os.makedirs(UNIPROT_TMP_DIR, exist_ok=True)

        self.write_obsolete_file_header()

        with open(self.output_node_file, "w") as node, open(self.output_edge_file, "w") as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            tar_file = RAW_DATA_DIR / UNIPROT_PROTEOMES_FILE
            with tarfile.open(tar_file,'r:gz') as tar:
                for member in tqdm(tar):
                    if member.name.endswith('.tsv'):
                        with tar.extractfile(member) as f:
                            if f is not None:
                                file_content = f.read()
                                s = StringIO(file_content.decode('utf-8'))
                                # Read the TSV file into a DataFrame
                                df = pd.read_csv(s, sep='\t')
                                all_edges_to_write,all_nodes_to_write = self.write_to_df(df)
                                for row in all_edges_to_write:
                                    edge_writer.writerow(row)
                                for row in all_nodes_to_write:
                                    node_writer.writerow(row)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        drop_duplicates(OBSOLETE_TERMS_CSV_FILE,sort_by = "GO_Term")

    def write_obsolete_file_header(self):
        """
        Write obsolete header to file.
        """
        obsolete_terms_csv_header = ["GO_Term","Uniprot_ID"]

        with open(OBSOLETE_TERMS_CSV_FILE,'w') as f:
            obsolete_terms_csv_writer = csv.writer(f,delimiter="\t")
            obsolete_terms_csv_writer.writerow(obsolete_terms_csv_header)

    def _get_go_category_trees(self,go_oi):
        """
        Extract category of all GO terms using oak, and write to file.

        :param go_oi: A oaklib sql_implementation class to access GO information.
        :type go_oi: oaklib sql_implementation class
        """
        with open(GO_CATEGORY_TREES_FILE, "w") as file:
            csv_writer = csv.writer(file, delimiter="\t")
            csv_writer.writerow(["GO_Category","GO_Term"])

            go_types = [GO_CELLULAR_COMPONENT_ID,GO_MOLECULAR_FUNCTION_ID,GO_BIOLOGICAL_PROCESS_ID]

            for r in go_types:
                term_decendants = list(go_oi.descendants(start_curies=r,predicates=["rdfs:subClassOf"],reflexive=True))
                for term in term_decendants:
                    r_list = [r,term]
                    csv_writer.writerow(r_list)

    def _get_go_relation_and_obsolete_terms(self,term_id,uniprot_id):
        """
        Extract category of GO term and handle obsolete terms according to oak.

        :param term_id: A string containing the GO ID.
        :type term_id: str
        :param uniprot_id: A string containing the Uniprot protein ID.
        :type uniprot_id: str
        :return: The appropriate predicate for the GO ID as it relates to the protein ID, or None if obsolete.
        :rtype: str or None
        """
        #! To handle obsolete terms
        try:
            go_component =  self.go_category_trees_df.loc[ self.go_category_trees_df["GO_Term"] == term_id,"GO_Category"].values[0]
            if go_component == GO_CELLULAR_COMPONENT_ID:
                go_relation = PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE
            elif go_component == GO_MOLECULAR_FUNCTION_ID:
                go_relation = PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE
            elif go_component == GO_BIOLOGICAL_PROCESS_ID:
                go_relation = PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE
        except IndexError:
            with open(OBSOLETE_TERMS_CSV_FILE,'a') as f:
                csv_writer = csv.writer(f, delimiter="\t")
                csv_writer.writerow([term_id,uniprot_id])
            go_relation = None

        return go_relation

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
        if len(binding_site_entry) > 0:
            chem_list = re.findall(r'/ligand_id="ChEBI:(.*?)";', binding_site_entry)
        else: chem_list = binding_site_entry

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
        if len(go_entry) > 0:
            go_list = re.findall("\[(.*?)\]", go_entry)
            go_list = [i for i in go_list if "GO" in i]
        else: go_list = go_entry

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
        if len(rhea_entry) > 0:
            rhea_list = rhea_entry.split(" ")
        else: rhea_list = rhea_entry

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
        if len(ec_entry) > 0:
            ec_list = ec_entry.split(";")
        else: ec_list = ec_entry

        return ec_list

    def parse_organism_entries(self,entry):
        """
        Extract all values from each column in entry.

        This method will handle existing and blank values for all columns in entry.

        :param entry: A series containing all columns for the corresponding entry.
        :type entry: series
        """
        columns_without_floats = [UNIPROT_ORG_ID_COLUMN_NAME,UNIPROT_PROTEIN_ID_COLUMN_NAME,UNIPROT_PROTEIN_NAME_COLUMN_NAME]
        columns_with_floats = [UNIPROT_EC_ID_COLUMN_NAME,UNIPROT_BINDING_SITE_COLUMN_NAME,UNIPROT_GO_COLUMN_NAME,UNIPROT_RHEA_ID_COLUMN_NAME,UNIPROT_PROTEOME_COLUMN_NAME]

        for col in columns_without_floats:
            self.__enz_data[col] = entry[col] if entry[col] else None

        for col in columns_with_floats:
            self.__enz_data[col] = entry[col] if not isinstance(entry[col],float) else []

    def write_to_df(self, uniprot_df):
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
        all_edges_to_write = []
        all_nodes_to_write = []
        ##To return all organism-enzyme entries
        for _,entry in uniprot_df.iterrows():

            #Parse all columns, handling blank values
            self.parse_organism_entries(entry)

            ec_list = self.parse_ec(self.__enz_data[UNIPROT_EC_ID_COLUMN_NAME])

            chem_list = self.parse_binding_site(self.__enz_data[UNIPROT_BINDING_SITE_COLUMN_NAME])
            
            go_list = self.parse_go_entry(self.__enz_data[UNIPROT_GO_COLUMN_NAME])

            rhea_list = self.parse_rhea_entry(self.__enz_data[UNIPROT_RHEA_ID_COLUMN_NAME])

            #Get one protein name only
            self.__enz_data[UNIPROT_PROTEIN_NAME_COLUMN_NAME] = self.__enz_data[UNIPROT_PROTEIN_NAME_COLUMN_NAME].split("(EC")[0].replace('[','(').replace(']',')')

            # Write protein-organism edges
            edges_data_to_write = [
                UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
                PROTEIN_TO_ORGANISM_EDGE,
                NCBITAXON_PREFIX + str(self.__enz_data[UNIPROT_ORG_ID_COLUMN_NAME]),
                "",
                self.source_name,
            ]

            all_edges_to_write.append(edges_data_to_write)

            # Write GO edges
            if len(go_list) > 0:
                for go in go_list:
                    #! Excluding obsolete terms
                    predicate = self._get_go_relation_and_obsolete_terms(go, UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME])
                    if not predicate:
                        continue
                    edges_data_to_write = [
                        UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
                        predicate,
                        go,
                        "",
                        self.source_name,
                    ]

                    all_edges_to_write.append(edges_data_to_write)
                    #edge_writer.writerow(edges_data_to_write)

                    # Write GO nodes, excluding info other than ID
                    nodes_data_to_write = [go] + [""] * (len(self.node_header)-1)
                    all_nodes_to_write.append(nodes_data_to_write)
                    
            # Write binding site edges
            if len(chem_list) > 0:
                for chem in chem_list:
                    edges_data_to_write = [
                        chem,
                        CHEMICAL_TO_PROTEIN_EDGE,
                        UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
                        "",
                        self.source_name,
                    ]

                    all_edges_to_write.append(edges_data_to_write)

                    # Write CHEBI nodes, excluding info other than ID
                    nodes_data_to_write = [chem] + [""] * (len(self.node_header)-1)
                    all_nodes_to_write.append(nodes_data_to_write)

            # Write rhea edges
            if len(rhea_list) > 0:
                for rhea in rhea_list:
                    edges_data_to_write = [
                        UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
                        PROTEIN_TO_RHEA_EDGE,
                        rhea,
                        "",
                        self.source_name,
                    ]

                    all_edges_to_write.append(edges_data_to_write)

                    # Write Rhea nodes, excluding info other than ID
                    nodes_data_to_write = [rhea] + [""] * (len(self.node_header)-1)
                    all_nodes_to_write.append(nodes_data_to_write)

            # Write EC edges
            if len(ec_list) > 0:
                for ec in ec_list:
                    edges_data_to_write = [
                        UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
                        PROTEIN_TO_EC_EDGE,
                        EC_PREFIX + ec,
                        "",
                        self.source_name,
                    ]

                    all_edges_to_write.append(edges_data_to_write)

                #Write EC nodes, excluding info other than ID
                nodes_data_to_write = [EC_PREFIX + ec] + [""] * (len(self.node_header)-1)
                all_nodes_to_write.append(nodes_data_to_write)

            if UNIPROT_PROTEOME_COLUMN_NAME in self.__enz_data.keys() and not isinstance(self.__enz_data[UNIPROT_PROTEOME_COLUMN_NAME],list):
                # Write organism-proteome edges
                edges_data_to_write = [
                    PROTEOME_PREFIX + self.__enz_data[UNIPROT_PROTEOME_COLUMN_NAME],
                    PROTEOME_TO_ORGANISM_EDGE,
                    NCBITAXON_PREFIX + str(self.__enz_data[UNIPROT_ORG_ID_COLUMN_NAME]),
                    "",
                    self.source_name,
                ]

                all_edges_to_write.append(edges_data_to_write)

                #Write proteome node
                nodes_data_to_write = [
                    PROTEOME_PREFIX + self.__enz_data[UNIPROT_PROTEOME_COLUMN_NAME],
                    PROTEOME_CATEGORY,
                    PROTEOME_PREFIX + self.__enz_data[UNIPROT_PROTEOME_COLUMN_NAME],
                    "",
                    "",
                    self.source_name] + [""] * (len(self.node_header)-6)
                
                all_nodes_to_write.append(nodes_data_to_write)

        # Write protein node
        nodes_data_to_write = [
            UNIPROT_PREFIX + self.__enz_data[UNIPROT_PROTEIN_ID_COLUMN_NAME],
            ENZYME_CATEGORY,
            self.__enz_data[UNIPROT_PROTEIN_NAME_COLUMN_NAME],
            "",
            "",
            self.source_name] + [""] * (len(self.node_header)-6)

        all_nodes_to_write.append(nodes_data_to_write)

        return all_edges_to_write,all_nodes_to_write