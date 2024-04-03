"""Uniprot Transonform class."""

import csv
import os
import re
import tarfile
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEMICAL_CATEGORY,
    CHEMICAL_TO_PROTEIN_EDGE,
    EC_CATEGORY,
    EC_PREFIX,
    GO_BIOLOGICAL_PROCESS_ID,
    GO_CELLULAR_COMPONENT_ID,
    GO_MOLECULAR_FUNCTION_ID,
    GO_PREFIX,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    PROTEIN_CATEGORY,
    PROTEIN_TO_EC_EDGE,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE,
    PROTEIN_TO_ORGANISM_EDGE,
    PROTEIN_TO_PROTEOME_EDGE,
    PROTEIN_TO_RHEA_EDGE,
    PROTEOME_CATEGORY,
    PROTEOME_PREFIX,
    PROTEOME_TO_ORGANISM_EDGE,
    PROVIDED_BY_COLUMN,
    RAW_DATA_DIR,
    RHEA_CATEGORY,
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

RELATIONS_DICTIONARY = {
    PROTEIN_TO_ORGANISM_EDGE: "RO:0001000",
    PROTEOME_TO_ORGANISM_EDGE: "RO:0001000",
    PROTEIN_TO_PROTEOME_EDGE: "RO:0001000",
    PROTEIN_TO_EC_EDGE: "RO:0002327",
    CHEMICAL_TO_PROTEIN_EDGE: "RO:0002436",
    PROTEIN_TO_RHEA_EDGE: "RO:0000056",
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE: "RO:0001025",
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE: "RO:0000056",
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE: "RO:0000056",
}

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
        self.go_category_trees_df = pd.read_csv(GO_CATEGORY_TREES_FILE, sep="\t", low_memory=False)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        # get descendants of important GO categories for relationship mapping
        os.makedirs(UNIPROT_TMP_DIR, exist_ok=True)

        self.write_obsolete_file_header()

        tar_file = RAW_DATA_DIR / UNIPROT_PROTEOMES_FILE
        with tarfile.open(tar_file, "r:gz") as tar:
            for member in tqdm(tar):
                if member.name.endswith(".tsv"):
                    with tar.extractfile(member) as f:
                        if f is not None:
                            file_content = f.read()
                            s = StringIO(file_content.decode("utf-8"))
                            # Read the TSV file into a DataFrame
                            df = pd.read_csv(s, sep="\t")
                            # Remove rows that match headers
                            df = df[~(df == df.columns.to_series()).all(axis=1)]
                            self.write_to_df(df)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        drop_duplicates(OBSOLETE_TERMS_CSV_FILE, sort_by="GO_Term")

    def write_obsolete_file_header(self):
        """Write obsolete header to file."""
        obsolete_terms_csv_header = ["GO_Term", "Uniprot_ID"]

        with open(OBSOLETE_TERMS_CSV_FILE, "w") as f:
            obsolete_terms_csv_writer = csv.writer(f, delimiter="\t")
            obsolete_terms_csv_writer.writerow(obsolete_terms_csv_header)

    def _get_go_category_trees(self, go_oi):
        """
        Extract category of all GO terms using oak, and write to file.

        :param go_oi: A oaklib sql_implementation class to access GO information.
        :type go_oi: oaklib sql_implementation class
        """
        with open(GO_CATEGORY_TREES_FILE, "w") as file:
            csv_writer = csv.writer(file, delimiter="\t")
            csv_writer.writerow(["GO_Category", "GO_Term"])

            go_types = [
                GO_CELLULAR_COMPONENT_ID,
                GO_MOLECULAR_FUNCTION_ID,
                GO_BIOLOGICAL_PROCESS_ID,
            ]

            for r in go_types:
                term_decendants = list(
                    go_oi.descendants(
                        start_curies=r, predicates=["rdfs:subClassOf"], reflexive=True
                    )
                )
                for term in term_decendants:
                    r_list = [r, term]
                    csv_writer.writerow(r_list)

    def _get_go_relation_and_obsolete_terms(self, term_id, uniprot_id):
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
            go_component = self.go_category_trees_df.loc[
                self.go_category_trees_df["GO_Term"] == term_id, "GO_Category"
            ].values[0]
            if go_component == GO_CELLULAR_COMPONENT_ID:
                go_relation = PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE
            elif go_component == GO_MOLECULAR_FUNCTION_ID:
                go_relation = PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE
            elif go_component == GO_BIOLOGICAL_PROCESS_ID:
                go_relation = PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE
        except IndexError:
            with open(OBSOLETE_TERMS_CSV_FILE, "a") as f:
                csv_writer = csv.writer(f, delimiter="\t")
                csv_writer.writerow([term_id, uniprot_id])
            go_relation = None
            go_component = None

        return go_relation, go_component

    def _is_float(self, entry):

        return isinstance(entry, float)

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
        chem_list = None
        if not self._is_float(binding_site_entry):
            chem_list = re.findall(r'/ligand_id="ChEBI:(.*?)";', binding_site_entry)

        return chem_list

    def parse_go_entry(self, go_entry):
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
        go_list = None
        if not self._is_float(go_entry):
            go_list = re.findall(r"\[(.*?)\]", go_entry)
            go_list = [i for i in go_list if GO_PREFIX in i]

        return go_list

    def parse_rhea_entry(self, rhea_entry):
        """
        Extract rhea identifiers from a rhea ID entry.

        This method finds all RHEA IDs for the corresponding entry.

        :param rhea_entry: A string containing the rhea information.
        :type rhea_entry: str
        :return: A list of RHEA identifiers extracted from the rhea entry.
        :rtype: list
        """
        rhea_list = None
        if not self._is_float(rhea_entry):
            rhea_list = rhea_entry.split(" ")

        return rhea_list

    def parse_ec(self, ec_entry):
        """
        Extract ec identifiers from a EC Number entry.

        This method finds all EC IDs for the corresponding entry.

        :param ec_entry: A string containing the ec information.
        :type ec_entry: str
        :return: A list of EC identifiers extracted from the EC entry.
        :rtype: list
        """
        ec_list = None
        if not self._is_float(ec_entry):
            ec_list = [EC_PREFIX + x.strip() for x in ec_entry.split(";")]

        return ec_list

    def _init_empty_dict(self, df):
        """Initializes an empty dictionary with keys taken for a given df."""
        dictionary = df.to_dict()
        dictionary = {k: None for k, _ in dictionary.items()}

        return dictionary

    def _write_node(self, id_value, category_value=None, name_value=None):
        """
        Add row to node file.

        This method will open the nodes file and add a row with the corresponding values given.

        :param id_value: A value for id of the node.
        :type subject: str
        :param category_value: A value for category of the node.
        :type category_value: str
        :param name_value: A value for name of the node.
        :type name_value: str
        """
        with open(self.output_node_file, "a") as node:
            node_writer = csv.writer(node, delimiter="\t")
            values_list = [id_value, category_value, name_value]
            row_list = values_list + ([None] * (len(self.node_header) - len(values_list)))
            row_list[self.node_header.index(PROVIDED_BY_COLUMN)] = self.source_name
            node_writer.writerow(row_list)

    def _write_edge(self, subject, predicate, object):
        """
        Add row to edge file.

        This method will open the edges file and add a row with the corresponding values given.

        :param subject: A value for subject.
        :type subject: str
        :param predicate: A value for predicate.
        :type predicate: str
        :param object: A value for object.
        :type object: str
        """
        with open(self.output_edge_file, "a") as edge:
            edge_writer = csv.writer(edge, delimiter="\t")
            values_list = [subject, predicate, object, RELATIONS_DICTIONARY[predicate]]
            row_list = values_list + ([None] * (len(self.edge_header) - len(values_list)))
            row_list[self.edge_header.index(PROVIDED_BY_COLUMN)] = self.source_name
            edge_writer.writerow(row_list)

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
        """
        parsed_columns = [
            "organism_parsed",
            "ec_number_parsed",
            "protein_parsed",
            "binding_site_parsed",
            "go_parsed",
            "rhea_parsed",
        ]
        uniprot_parse_df = pd.DataFrame(columns=parsed_columns)

        uniprot_parse_df["organism_parsed"] = uniprot_df[UNIPROT_ORG_ID_COLUMN_NAME].apply(
            lambda x: NCBITAXON_PREFIX + str(x).strip()
        )
        uniprot_parse_df["ec_number_parsed"] = uniprot_df[UNIPROT_EC_ID_COLUMN_NAME].apply(
            self.parse_ec
        )
        uniprot_parse_df["protein_id_parsed"] = uniprot_df[UNIPROT_PROTEIN_ID_COLUMN_NAME].apply(
            lambda x: UNIPROT_PREFIX + x.strip()
        )
        uniprot_parse_df["protein_name_parsed"] = uniprot_df[
            UNIPROT_PROTEIN_NAME_COLUMN_NAME
        ].apply(lambda x: x.split("(EC")[0].replace("[", "(").replace("]", ")"))
        uniprot_parse_df["binding_site_parsed"] = uniprot_df[
            UNIPROT_BINDING_SITE_COLUMN_NAME
        ].apply(self.parse_binding_site)
        uniprot_parse_df["go_parsed"] = uniprot_df[UNIPROT_GO_COLUMN_NAME].apply(
            self.parse_go_entry
        )
        uniprot_parse_df["rhea_parsed"] = uniprot_df[UNIPROT_RHEA_ID_COLUMN_NAME].apply(
            self.parse_rhea_entry
        )
        uniprot_parse_df["proteome_parsed"] = uniprot_df[UNIPROT_PROTEOME_COLUMN_NAME].apply(
            lambda x: PROTEOME_PREFIX + x.split(":")[0].strip() if not self._is_float(x) else x
        )

        with open(self.output_node_file, "w") as node, open(self.output_edge_file, "w") as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

        for _, entry in uniprot_parse_df.iterrows():
            # Organism node
            self._write_node(entry["organism_parsed"], NCBI_CATEGORY)
            # Protein node
            self._write_node(
                entry["protein_id_parsed"], PROTEIN_CATEGORY, entry["protein_name_parsed"]
            )
            # Proteome node
            self._write_node(entry["proteome_parsed"], PROTEOME_CATEGORY, entry["proteome_parsed"])
            # EC node
            if entry["ec_number_parsed"] is None:
                continue
            else:
                for ec in entry["ec_number_parsed"]:
                    self._write_node(ec, EC_CATEGORY)
                    # Protein-ec edge
                    self._write_edge(entry["protein_id_parsed"], PROTEIN_TO_EC_EDGE, ec)
            # CHEBI node
            if entry["binding_site_parsed"] is None:
                continue
            else:
                for chebi in entry["binding_site_parsed"]:
                    self._write_node(chebi, CHEMICAL_CATEGORY)
                    # Chebi-protein edge
                    self._write_edge(chebi, CHEMICAL_TO_PROTEIN_EDGE, entry["protein_id_parsed"])
            # Rhea node
            if entry["rhea_parsed"] is None:
                continue
            else:
                for rhea in entry["rhea_parsed"]:
                    self._write_node(rhea, RHEA_CATEGORY)
                    # Protein-rhea edge
                    self._write_edge(entry["protein_id_parsed"], PROTEIN_TO_RHEA_EDGE, rhea)
            # GO node
            if entry["go_parsed"] is None:
                continue
            else:
                for go in entry["go_parsed"]:
                    #! Excluding obsolete terms
                    predicate, go_category = self._get_go_relation_and_obsolete_terms(
                        go, entry["protein_id_parsed"]
                    )
                    self._write_node(go, go_category)
                    # Protein to go edge
                    if not predicate:
                        continue
                    else:
                        self._write_edge(entry["protein_id_parsed"], predicate, go)

            # Protein-organism
            self._write_edge(
                entry["protein_id_parsed"], PROTEIN_TO_ORGANISM_EDGE, entry["organism_parsed"]
            )
            # Proteome-organism
            self._write_edge(
                entry["proteome_parsed"], PROTEOME_TO_ORGANISM_EDGE, entry["organism_parsed"]
            )
            # Protein-proteome
            self._write_edge(
                entry["protein_id_parsed"], PROTEIN_TO_PROTEOME_EDGE, entry["proteome_parsed"]
            )
