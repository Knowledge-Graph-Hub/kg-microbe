"""Uniprot Transform class."""

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
    DERIVES_FROM,
    EC_CATEGORY,
    EC_PREFIX,
    ENABLES,
    GO_BIOLOGICAL_PROCESS_ID,
    GO_BIOLOGICAL_PROCESS_LABEL,
    GO_CELLULAR_COMPONENT_ID,
    GO_CELLULAR_COMPONENT_LABEL,
    GO_MOLECULAR_FUNCTION_ID,
    GO_MOLECULAR_FUNCTION_LABEL,
    GO_PREFIX,
    LOCATED_IN,
    MOLECULARLY_INTERACTS_WITH,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    PARTICIPATES_IN,
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
    RDFS_SUBCLASS_OF,
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

RELATIONS_DICT = {
    PROTEIN_TO_ORGANISM_EDGE: DERIVES_FROM,
    PROTEOME_TO_ORGANISM_EDGE: DERIVES_FROM,
    PROTEIN_TO_PROTEOME_EDGE: DERIVES_FROM,
    PROTEIN_TO_EC_EDGE: ENABLES,
    CHEMICAL_TO_PROTEIN_EDGE: MOLECULARLY_INTERACTS_WITH,
    PROTEIN_TO_RHEA_EDGE: PARTICIPATES_IN,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE: LOCATED_IN,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE: PARTICIPATES_IN,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE: PARTICIPATES_IN,
}

GO_CATEGORY_DICT = {
    GO_CELLULAR_COMPONENT_ID: PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE,
    GO_MOLECULAR_FUNCTION_ID: PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE,
    GO_BIOLOGICAL_PROCESS_ID: PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE,
}

GO_TYPES_DICT = {
    GO_CELLULAR_COMPONENT_ID: GO_CELLULAR_COMPONENT_LABEL,
    GO_MOLECULAR_FUNCTION_ID: GO_MOLECULAR_FUNCTION_LABEL,
    GO_BIOLOGICAL_PROCESS_ID: GO_BIOLOGICAL_PROCESS_LABEL,
}

ORGANISM_PARSED_COLUMN = "organism_parsed"
EC_NUMBER_PARSED_COLUMN = "ec_number_parsed"
PROTEIN_ID_PARSED_COLUMN = "protein_id_parsed"
PROTEIN_NAME_PARSED_COLUMN = "protein_name_parsed"
BINDING_SITE_PARSED_COLUMN = "binding_site_parsed"
GO_PARSED_COLUMN = "go_parsed"
RHEA_PARSED_COLUMN = "rhea_parsed"
PROTEOME_PARSED_COLUMN = "proteome_parsed"
GO_TERM_COLUMN = "GO_Term"
GO_CATEGORY_COLUMN = "GO_Category"
UNIPROT_ID_COLUMN = "Uniprot_ID"

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
        # Read into a dictionary
        self.go_category_trees_dict = {}
        with open(GO_CATEGORY_TREES_FILE, "r") as file:
            csv_reader = csv.DictReader(file, delimiter="\t")
            for row in csv_reader:
                self.go_category_trees_dict[row[GO_TERM_COLUMN]] = row[GO_CATEGORY_COLUMN]

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
        drop_duplicates(OBSOLETE_TERMS_CSV_FILE, sort_by=GO_TERM_COLUMN)

    def write_obsolete_file_header(self):
        """Write obsolete header to file."""
        obsolete_terms_csv_header = [GO_TERM_COLUMN, UNIPROT_ID_COLUMN]

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
            csv_writer.writerow([GO_CATEGORY_COLUMN, GO_TERM_COLUMN])

            for id in GO_TYPES_DICT.keys():
                term_decendants = list(
                    go_oi.descendants(
                        start_curies=id, predicates=[RDFS_SUBCLASS_OF], reflexive=True
                    )
                )
                for term in term_decendants:
                    r_list = [id, term]
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
            go_component = self.go_category_trees_dict[term_id]
            go_component_label = GO_TYPES_DICT[go_component]
            go_relation = GO_CATEGORY_DICT[go_component]
        except KeyError:
            with open(OBSOLETE_TERMS_CSV_FILE, "a") as f:
                csv_writer = csv.writer(f, delimiter="\t")
                csv_writer.writerow([term_id, uniprot_id])
            go_relation = None
            go_component_label = None

        return go_relation, go_component_label

    def _is_float(self, entry):
        """Determine if value is float, returns True/False."""
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
        """Initialize an empty dictionary with keys taken for a given df."""
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
            values_list = [subject, predicate, object, RELATIONS_DICT[predicate]]
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
            ORGANISM_PARSED_COLUMN,
            PROTEOME_PARSED_COLUMN,
            EC_NUMBER_PARSED_COLUMN,
            PROTEIN_ID_PARSED_COLUMN,
            BINDING_SITE_PARSED_COLUMN,
            GO_PARSED_COLUMN,
            RHEA_PARSED_COLUMN,
        ]
        uniprot_parse_df = pd.DataFrame(columns=parsed_columns)

        uniprot_parse_df[ORGANISM_PARSED_COLUMN] = uniprot_df[UNIPROT_ORG_ID_COLUMN_NAME].apply(
            lambda x: NCBITAXON_PREFIX + str(x).strip()
        )
        uniprot_parse_df[EC_NUMBER_PARSED_COLUMN] = uniprot_df[UNIPROT_EC_ID_COLUMN_NAME].apply(
            self.parse_ec
        )
        uniprot_parse_df[PROTEIN_ID_PARSED_COLUMN] = uniprot_df[
            UNIPROT_PROTEIN_ID_COLUMN_NAME
        ].apply(lambda x: UNIPROT_PREFIX + x.strip())
        uniprot_parse_df[PROTEIN_NAME_PARSED_COLUMN] = uniprot_df[
            UNIPROT_PROTEIN_NAME_COLUMN_NAME
        ].apply(lambda x: x.split("(EC")[0].replace("[", "(").replace("]", ")"))
        uniprot_parse_df[BINDING_SITE_PARSED_COLUMN] = uniprot_df[
            UNIPROT_BINDING_SITE_COLUMN_NAME
        ].apply(self.parse_binding_site)
        uniprot_parse_df[GO_PARSED_COLUMN] = uniprot_df[UNIPROT_GO_COLUMN_NAME].apply(
            self.parse_go_entry
        )
        uniprot_parse_df[RHEA_PARSED_COLUMN] = uniprot_df[UNIPROT_RHEA_ID_COLUMN_NAME].apply(
            self.parse_rhea_entry
        )
        uniprot_parse_df[PROTEOME_PARSED_COLUMN] = uniprot_df[UNIPROT_PROTEOME_COLUMN_NAME].apply(
            lambda x: PROTEOME_PREFIX + x.split(":")[0].strip() if not self._is_float(x) else x
        )

        for _, entry in uniprot_parse_df.iterrows():
            # Organism node
            self._write_node(entry[ORGANISM_PARSED_COLUMN], NCBI_CATEGORY)
            # Protein node
            self._write_node(
                entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_CATEGORY, entry[PROTEIN_NAME_PARSED_COLUMN]
            )
            # Proteome node
            self._write_node(
                entry[PROTEOME_PARSED_COLUMN], PROTEOME_CATEGORY, entry[PROTEOME_PARSED_COLUMN]
            )
            # EC node
            if entry[EC_NUMBER_PARSED_COLUMN] is None:
                continue
            for ec in entry[EC_NUMBER_PARSED_COLUMN]:
                self._write_node(ec, EC_CATEGORY)
                # Protein-ec edge
                self._write_edge(entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_TO_EC_EDGE, ec)
            # CHEBI node
            if entry[BINDING_SITE_PARSED_COLUMN] is None:
                continue
            for chebi in entry[BINDING_SITE_PARSED_COLUMN]:
                self._write_node(chebi, CHEMICAL_CATEGORY)
                # Chebi-protein edge
                self._write_edge(chebi, CHEMICAL_TO_PROTEIN_EDGE, entry[PROTEIN_ID_PARSED_COLUMN])
            # Rhea node
            if entry[RHEA_PARSED_COLUMN] is None:
                continue
            for rhea in entry[RHEA_PARSED_COLUMN]:
                self._write_node(rhea, RHEA_CATEGORY)
                # Protein-rhea edge
                self._write_edge(entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_TO_RHEA_EDGE, rhea)
            # GO node
            if entry[GO_PARSED_COLUMN] is None:
                continue
            for go in entry[GO_PARSED_COLUMN]:
                #! Excluding obsolete terms
                predicate, go_category = self._get_go_relation_and_obsolete_terms(
                    go, entry[PROTEIN_ID_PARSED_COLUMN]
                )
                self._write_node(go, go_category)
                # Protein to go edge
                if not predicate:
                    continue
                self._write_edge(entry[PROTEIN_ID_PARSED_COLUMN], predicate, go)

            # Protein-organism
            self._write_edge(
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_TO_ORGANISM_EDGE,
                entry[ORGANISM_PARSED_COLUMN],
            )
            # Proteome-organism
            self._write_edge(
                entry[PROTEOME_PARSED_COLUMN],
                PROTEOME_TO_ORGANISM_EDGE,
                entry[ORGANISM_PARSED_COLUMN],
            )
            # Protein-proteome
            self._write_edge(
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_TO_PROTEOME_EDGE,
                entry[PROTEOME_PARSED_COLUMN],
            )
