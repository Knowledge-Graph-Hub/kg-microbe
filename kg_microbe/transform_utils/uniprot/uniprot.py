"""Uniprot Transform class."""

import csv
import os
import re
import tarfile
import uuid
from multiprocessing import Pool
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
    UNIPROT_RELEVANT_FILE_LIST,
    UNIPROT_RHEA_ID_COLUMN_NAME,
    UNIPROT_TMP_DIR,
    UNIPROT_TMP_NE_DIR,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
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
OBSOLETE_TERMS_CSV_FILE = UNIPROT_TMP_DIR / "go_obsolete_terms.tsv"
GO_CATEGORY_TREES_FILE = UNIPROT_TMP_DIR / "go_category_trees.tsv"

# Pre-compile regular expressions
CHEBI_REGEX = re.compile(r'/ligand_id="ChEBI:(.*?)";')
GO_REGEX = re.compile(r"\[(.*?)\]")
GO_CATEGORY_TREES_DICT = {}


def is_float(entry):
    """Determine if value is float, returns True/False."""
    return isinstance(entry, float)


def parse_ec(ec_entry):
    """
    Extract ec identifiers from a EC Number entry.

    This method finds all EC IDs for the corresponding entry.

    :param ec_entry: A string containing the ec information.
    :type ec_entry: str
    :return: A list of EC identifiers extracted from the EC entry.
    :rtype: list
    """
    ec_list = None
    if not is_float(ec_entry):
        ec_list = [EC_PREFIX + x.strip() for x in ec_entry.split(";")]

    return ec_list


def parse_binding_site(binding_site_entry):
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
    if not is_float(binding_site_entry):
        chem_list = re.findall(r'/ligand_id="ChEBI:(.*?)";', binding_site_entry)

    return chem_list


def parse_go_entry(go_entry):
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
    if not is_float(go_entry):
        go_list = re.findall(r"\[(.*?)\]", go_entry)
        go_list = [i for i in go_list if GO_PREFIX in i]

    return go_list


def parse_rhea_entry(rhea_entry):
    """
    Extract rhea identifiers from a rhea ID entry.

    This method finds all RHEA IDs for the corresponding entry.

    :param rhea_entry: A string containing the rhea information.
    :type rhea_entry: str
    :return: A list of RHEA identifiers extracted from the rhea entry.
    :rtype: list
    """
    rhea_list = None
    if not is_float(rhea_entry):
        rhea_list = rhea_entry.split(" ")

    return rhea_list


def get_go_relation_and_obsolete_terms(term_id, uniprot_id):
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
        go_component = GO_CATEGORY_TREES_DICT[term_id]
        go_component_label = GO_TYPES_DICT[go_component]
        go_relation = GO_CATEGORY_DICT[go_component]
    except KeyError:
        with open(OBSOLETE_TERMS_CSV_FILE, "a") as f:
            csv_writer = csv.writer(f, delimiter="\t")
            csv_writer.writerow([term_id, uniprot_id])
        go_relation = None
        go_component_label = None

    return go_relation, go_component_label


def write_to_df(uniprot_df):
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
    node_data = []
    edge_data = []
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
        parse_ec
    )
    uniprot_parse_df[PROTEIN_ID_PARSED_COLUMN] = uniprot_df[UNIPROT_PROTEIN_ID_COLUMN_NAME].apply(
        lambda x: UNIPROT_PREFIX + x.strip()
    )
    uniprot_parse_df[PROTEIN_NAME_PARSED_COLUMN] = uniprot_df[
        UNIPROT_PROTEIN_NAME_COLUMN_NAME
    ].apply(lambda x: x.split("(EC")[0].replace("[", "(").replace("]", ")") if is_float(x) else x)
    uniprot_parse_df[BINDING_SITE_PARSED_COLUMN] = uniprot_df[
        UNIPROT_BINDING_SITE_COLUMN_NAME
    ].apply(parse_binding_site)
    uniprot_parse_df[GO_PARSED_COLUMN] = uniprot_df[UNIPROT_GO_COLUMN_NAME].apply(parse_go_entry)
    uniprot_parse_df[RHEA_PARSED_COLUMN] = uniprot_df[UNIPROT_RHEA_ID_COLUMN_NAME].apply(
        parse_rhea_entry
    )
    uniprot_parse_df[PROTEOME_PARSED_COLUMN] = uniprot_df[UNIPROT_PROTEOME_COLUMN_NAME].apply(
        lambda x: PROTEOME_PREFIX + x.split(":")[0].strip() if not is_float(x) else x
    )

    for _, entry in uniprot_parse_df.iterrows():
        # Organism node
        node_data.append([entry[ORGANISM_PARSED_COLUMN], NCBI_CATEGORY])
        # Protein node
        node_data.append(
            [entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_CATEGORY, entry[PROTEIN_NAME_PARSED_COLUMN]]
        )

        # Proteome node
        node_data.append(
            [entry[PROTEOME_PARSED_COLUMN], PROTEOME_CATEGORY, entry[PROTEOME_PARSED_COLUMN]]
        )
        # EC node
        if entry[EC_NUMBER_PARSED_COLUMN] is None:
            continue
        for ec in entry[EC_NUMBER_PARSED_COLUMN]:
            node_data.append([ec, EC_CATEGORY])
            # Protein-ec edge
            edge_data.append([entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_TO_EC_EDGE, ec])
        # CHEBI node
        if entry[BINDING_SITE_PARSED_COLUMN] is None:
            continue
        for chebi in entry[BINDING_SITE_PARSED_COLUMN]:
            node_data.append([chebi, CHEMICAL_CATEGORY])
            # Chebi-protein edge
            edge_data.append([chebi, CHEMICAL_TO_PROTEIN_EDGE, entry[PROTEIN_ID_PARSED_COLUMN]])
        # Rhea node
        if entry[RHEA_PARSED_COLUMN] is None:
            continue
        for rhea in entry[RHEA_PARSED_COLUMN]:
            node_data.append([rhea, RHEA_CATEGORY])
            # Protein-rhea edge
            edge_data.append([entry[PROTEIN_ID_PARSED_COLUMN], PROTEIN_TO_RHEA_EDGE, rhea])
        # GO node
        if entry[GO_PARSED_COLUMN] is None:
            continue
        for go in entry[GO_PARSED_COLUMN]:
            #! Excluding obsolete terms
            predicate, go_category = get_go_relation_and_obsolete_terms(
                go, entry[PROTEIN_ID_PARSED_COLUMN]
            )
            node_data.append([go, go_category])
            # Protein to go edge
            if not predicate:
                continue
            edge_data.append([entry[PROTEIN_ID_PARSED_COLUMN], predicate, go])

        # Protein-organism
        edge_data.append(
            [
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_TO_ORGANISM_EDGE,
                entry[ORGANISM_PARSED_COLUMN],
            ]
        )
        # Proteome-organism
        edge_data.append(
            [
                entry[PROTEOME_PARSED_COLUMN],
                PROTEOME_TO_ORGANISM_EDGE,
                entry[ORGANISM_PARSED_COLUMN],
            ]
        )
        # Protein-proteome
        edge_data.append(
            [
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_TO_PROTEOME_EDGE,
                entry[PROTEOME_PARSED_COLUMN],
            ]
        )

    return (node_data, edge_data)


def process_lines(
    all_lines, headers, node_header, edge_header, node_filename, edge_filename, progress_class
):
    """
    Process a member of a tarfile containing UniProt data.

    This method reads the content of a member file, processes the data, and writes
    the resulting node and edge data to the provided CSV files. It uses a lock to
    ensure that the files are written to correctly and that no data is lost.

    :param all_lines: A list of lines from the member file.
    :param headers: A list of headers for the data.
    :param node_header: A list of headers for the node data.
    :param edge_header: A list of headers for the edge data.
    :param node_filename: The name of the file to write node data to.
    :param edge_filename: The name of the file to write edge data to.
    :param progress_class: The class to use for progress tracking. (tqdm or dummy)
    """
    list_of_rows = [s.split("\t") for s in all_lines[1:]]
    df = pd.DataFrame(list_of_rows, columns=headers)
    df = df[~(df == df.columns.to_series()).all(axis=1)]
    df.drop_duplicates(inplace=True)

    node_data, edge_data = write_to_df(df)
    # Write node and edge data to unique files
    if len(node_data) > 0:
        with open(node_filename, "w", newline="") as nf:
            node_writer = csv.writer(nf, delimiter="\t")
            node_writer.writerow(node_header)  # Write header
            for node in progress_class(node_data, desc="Writing node data"):
                if len(node) < len(node_header):
                    node.extend([None] * (len(node_header) - len(node)))
                node_writer.writerow(node)

    if len(edge_data) > 0:
        with open(edge_filename, "w", newline="") as ef:
            edge_writer = csv.writer(ef, delimiter="\t")
            edge_writer.writerow(edge_header)  # Write header
            for edge in progress_class(edge_data, desc="Writing edge data"):
                if len(edge) < len(edge_header):
                    edge.extend([None] * (len(edge_header) - len(edge)))
                edge_writer.writerow(edge)

    return node_filename, edge_filename


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
        source_name = UNIPROT_GENOME_FEATURES
        super().__init__(source_name, input_dir, output_dir)
        self.go_oi = get_adapter("sqlite:obo:go")
        # Check if the file already exists
        if not GO_CATEGORY_TREES_FILE.exists():
            self.get_go_category_trees(self.go_oi)
        # Read into a dictionary
        with open(GO_CATEGORY_TREES_FILE, "r") as file:
            csv_reader = csv.DictReader(file, delimiter="\t")
            for row in csv_reader:
                GO_CATEGORY_TREES_DICT[row[GO_TERM_COLUMN]] = row[GO_CATEGORY_COLUMN]

    def check_string_in_tar(
        self,
        tar_file,
        progress_class,
        regex_pattern=r"UP\d+: (Chromosome|Plasmid .+)",
        min_line_count=1000,
    ):
        """
        Look for a specific string in tsvs in the tarfile and return the content of matching members.

        :param tar_file: The path to the tarfile containing the tsv files.
        :param progress_class: The class to use for progress tracking. (tqdm or dummy)
        :param regex_pattern: The regex pattern to search for in the tsv files.
        :param min_line_count: The minimum number of lines that must match the pattern.
        """
        # Compile the regex pattern outside of the loop for efficiency
        pattern = re.compile(regex_pattern)
        relevant_files = []
        relevant_files_list_exists = False

        # ! This is shelved for now since just getting filenames from a tsv should suffice.
        # # Check if UNIPROT_RELEVANT_CONTENT_FILE exists
        # if os.path.exists(UNIPROT_RELEVANT_CONTENT_FILE):
        #     # Read the existing file and return its content as a list of lines
        #     with open(UNIPROT_RELEVANT_CONTENT_FILE, "r", encoding="utf-8") as f:
        #         return [line.rstrip("\n") for line in f]
        if os.path.exists(UNIPROT_RELEVANT_FILE_LIST):
            # Read the existing tsv file and return its content as a list of lines
            with open(UNIPROT_RELEVANT_FILE_LIST, "r", encoding="utf-8") as f:
                relevant_files = [line.rstrip("\n") for line in f]
                relevant_files_list_exists = True

        # Initialize the list to store matching members' content
        matching_members_content = []

        with tarfile.open(tar_file, "r:gz") as tar:
            if relevant_files_list_exists:
                members = [member for member in tar.getmembers() if member.name in relevant_files]
            else:
                members = tar.getmembers()

            for member in progress_class(members, desc="Inspecting tsvs in tarfile"):
                # Check if the member name is in the list of relevant files
                if member.name.endswith(".tsv"):
                    with tar.extractfile(member) as file:
                        if file is not None:
                            # Read the content as a text stream using decode
                            content = file.read().decode("utf-8")
                            # Split the content into lines and count occurrences
                            lines = content.splitlines()
                            count = sum(bool(pattern.search(line)) for line in lines)
                            if count > min_line_count:
                                # Add only unique lines to the set
                                matching_members_content.extend(lines)
                                # Add the member name to the list
                                relevant_files.append(member.name)

        # ! This is shelved for now since just getting filenames from a tsv should suffice.
        # # Write the content to the file as text
        # with open(UNIPROT_RELEVANT_CONTENT_FILE, "w", encoding="utf-8") as f:
        #     f.write("\n".join(matching_members_content))
        if not relevant_files_list_exists:
            with open(UNIPROT_RELEVANT_FILE_LIST, "w", encoding="utf-8") as f:
                f.write("\n".join(relevant_files))

        # Return the list of lines
        return matching_members_content

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        n_workers = os.cpu_count()

        # get descendants of important GO categories for relationship mapping
        os.makedirs(UNIPROT_TMP_DIR, exist_ok=True)
        os.makedirs(UNIPROT_TMP_NE_DIR, exist_ok=True)

        self.write_obsolete_file_header()

        tar_file = RAW_DATA_DIR / UNIPROT_PROTEOMES_FILE
        progress_class = tqdm if show_status else DummyTqdm
        all_lines = self.check_string_in_tar(tar_file, progress_class=progress_class)
        member_header = all_lines[0].split("\t")
        chunk_size = len(all_lines) // n_workers
        print(f"Processing {len(all_lines)- 1} lines in {n_workers} chunks")
        line_chunks = [all_lines[i : i + chunk_size] for i in range(0, len(all_lines), chunk_size)]

        with Pool(n_workers) as pool:
            results = pool.starmap(
                process_lines,
                [
                    (
                        line_chunk,
                        member_header,
                        self.node_header,
                        self.edge_header,
                        f"{UNIPROT_TMP_NE_DIR}/node_{uuid.uuid4()}.tsv",
                        f"{UNIPROT_TMP_NE_DIR}/edge_{uuid.uuid4()}.tsv",
                        progress_class,
                    )
                    for line_chunk in line_chunks
                ],
            )
            results = [result for result in results if result != (None, None)]

        # Combine individual node and edge files
        combined_node_filename = self.output_node_file
        combined_edge_filename = self.output_edge_file

        with open(combined_node_filename, "w", newline="") as cnf, open(
            combined_edge_filename, "w", newline=""
        ) as cef:
            node_writer = csv.writer(cnf, delimiter="\t")
            edge_writer = csv.writer(cef, delimiter="\t")

            # Write headers
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            for node_file, edge_file in progress_class(
                results, desc="Combining node and edge files"
            ):
                # Append node data
                if node_file:
                    with open(node_file, "r") as nf:
                        next(nf)  # Skip header
                        node_writer.writerows(csv.reader(nf, delimiter="\t"))
                    # Remove temporary files
                    os.remove(node_file)

                if edge_file:
                    # Append edge data
                    with open(edge_file, "r") as ef:
                        next(ef)  # Skip header
                        edge_writer.writerows(csv.reader(ef, delimiter="\t"))
                    # Remove temporary files
                    os.remove(edge_file)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        drop_duplicates(OBSOLETE_TERMS_CSV_FILE, sort_by_column=GO_TERM_COLUMN)

    def write_obsolete_file_header(self):
        """Write obsolete header to file."""
        obsolete_terms_csv_header = [GO_TERM_COLUMN, UNIPROT_ID_COLUMN]

        with open(OBSOLETE_TERMS_CSV_FILE, "w") as f:
            obsolete_terms_csv_writer = csv.writer(f, delimiter="\t")
            obsolete_terms_csv_writer.writerow(obsolete_terms_csv_header)

    def get_go_category_trees(self, go_oi):
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
