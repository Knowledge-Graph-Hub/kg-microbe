"""Uniprot utilities."""

import csv
import os
import re
import tarfile
import uuid
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEMICAL_CATEGORY,
    CHEMICAL_TO_PROTEIN_EDGE,
    CONTRIBUTES_TO,
    DERIVES_FROM,
    DISEASE_CATEGORY,
    EC_CATEGORY,
    EC_PREFIX,
    ENABLES,
    GENE_TO_PROTEIN_EDGE,
    GO_BIOLOGICAL_PROCESS_ID,
    GO_BIOLOGICAL_PROCESS_LABEL,
    GO_CATEGORY_TREES_FILE,
    GO_CELLULAR_COMPONENT_ID,
    GO_CELLULAR_COMPONENT_LABEL,
    GO_MOLECULAR_FUNCTION_ID,
    GO_MOLECULAR_FUNCTION_LABEL,
    GO_PREFIX,
    HAS_GENE_PRODUCT,
    HGNC_NEW_PREFIX,
    LOCATED_IN,
    MOLECULARLY_INTERACTS_WITH,
    MONDO_GENE_IDS_FILEPATH,
    MONDO_XREFS_FILEPATH,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    OMIM_PREFIX,
    ONTOLOGIES_TREES_DIR,
    PARTICIPATES_IN,
    PROTEIN_CATEGORY,
    PROTEIN_TO_DISEASE_EDGE,
    PROTEIN_TO_EC_EDGE,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE,
    PROTEIN_TO_ORGANISM_EDGE,
    PROTEIN_TO_RHEA_EDGE,
    RDFS_SUBCLASS_OF,
    RHEA_CATEGORY,
    UNIPROT_BINDING_SITE_COLUMN_NAME,
    UNIPROT_DISEASE_COLUMN_NAME,
    UNIPROT_EC_ID_COLUMN_NAME,
    UNIPROT_GENE_PRIMARY_COLUMN_NAME,
    UNIPROT_GO_COLUMN_NAME,
    UNIPROT_ORG_ID_COLUMN_NAME,
    UNIPROT_PREFIX,
    UNIPROT_PROTEIN_ID_COLUMN_NAME,
    UNIPROT_PROTEIN_NAME_COLUMN_NAME,
    UNIPROT_PROTEOME_COLUMN_NAME,
    UNIPROT_RHEA_ID_COLUMN_NAME,
)
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.pandas_utils import drop_duplicates

RELATIONS_DICT = {
    PROTEIN_TO_ORGANISM_EDGE: DERIVES_FROM,
    PROTEIN_TO_EC_EDGE: ENABLES,
    CHEMICAL_TO_PROTEIN_EDGE: MOLECULARLY_INTERACTS_WITH,
    PROTEIN_TO_RHEA_EDGE: PARTICIPATES_IN,
    PROTEIN_TO_GO_CELLULAR_COMPONENT_EDGE: LOCATED_IN,
    PROTEIN_TO_GO_MOLECULAR_FUNCTION_EDGE: PARTICIPATES_IN,
    PROTEIN_TO_GO_BIOLOGICAL_PROCESS_EDGE: PARTICIPATES_IN,
    PROTEIN_TO_DISEASE_EDGE: CONTRIBUTES_TO,
    GENE_TO_PROTEIN_EDGE: HAS_GENE_PRODUCT,
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
DISEASE_PARSED_COLUMN = "disease_parsed"
GENE_PRIMARY_PARSED_COLUMN = "gene_primary_parsed"
GO_TERM_COLUMN = "GO_Term"
GO_CATEGORY_COLUMN = "GO_Category"
UNIPROT_ID_COLUMN = "Uniprot_ID"

# Pre-compile regular expressions
CHEBI_REGEX = re.compile(r'/ligand_id="ChEBI:(.*?)";')
GO_REGEX = re.compile(r"\[(.*?)\]")


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
    if len(str(ec_entry)) > 0:
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
    if len(str(go_entry)) > 0:
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
    if len(str(rhea_entry)) > 0:
        if not is_float(rhea_entry):
            rhea_list = rhea_entry.split(" ")

    return rhea_list


def parse_disease(disease_entry, mondo_xref_dict):
    """
    Extract OMIM ID's from a disease entry.

    This method uses regular expressions to find all occurrences of OMIM IDs.

    :param disease_entry: A string containing the disease information.
    :type disease_entry: str
    :return: A list of OMIM curies.
    :rtype: list
    """
    omim_list = None
    if not is_float(disease_entry):
        omim_list = re.findall(r"\[MIM:(\d+)\]", disease_entry)
        omim_list = [f"{OMIM_PREFIX}" + omim_number for omim_number in omim_list]

    mondo_list = convert_omim_diseases(omim_list, mondo_xref_dict)

    return mondo_list


def parse_gene(gene_entry, mondo_gene_dict):
    """
    Get gene ID from gene name entry.

    This method uses the MONDO ontology transform to get the HGNC id of a gene.

    :param gene_entry: A string containing the gene name.
    :type gene_entry: str
    :return: A gene id.
    :rtype: str
    """
    gene_id = None
    if not is_float(gene_entry):
        gene_name = gene_entry
        gene_id = next((key for key, val in mondo_gene_dict.items() if val == gene_name), None)

    return gene_id


def convert_omim_diseases(omim_list, mondo_xref_dict):
    """
    Convert OMIM ID's to a MONDO ID using MONDO xref dictionary.

    This method uses the MONDO ontology xrefs to convert OMIM to MONDO.

    :param omim_list: A list containing OMIM IDs.
    :type omim_list: list
    :param mondo_xref_dict: A dictionary of MONDO IDs and their xrefs.
    :type mondo_xref_dict: dict
    :return: A list of MONDO curies.
    :rtype: list
    """
    # Get all MONDO IDs according to OMIM xrefs
    # mondo_list = list(filter(lambda item: item[1] in omim_list, mondo_xref_dict.items()))
    mondo_list = [
        key for value in omim_list for key, val in mondo_xref_dict.items() if val == value
    ]

    return mondo_list


def get_go_relation_and_obsolete_terms(
    term_id, uniprot_id, go_category_trees_dictionary, obsolete_terms_csv_file
):
    """
    Extract category of GO term and handle obsolete terms according to oak.

    :param term_id: A string containing the GO ID.
    :type term_id: str
    :param uniprot_id: A string containing the Uniprot protein ID.
    :type uniprot_id: str
    :param go_category_dictionary: Dictionary of all GO Terms with their corresponding category.
    :type go_category_dictionary: dict
    :return: The appropriate predicate for the GO ID as it relates to the protein ID, or None if obsolete.
    :rtype: str or None
    """
    #! To handle obsolete terms
    try:
        go_component = go_category_trees_dictionary[term_id]
        go_component_label = GO_TYPES_DICT[go_component]
        go_relation = GO_CATEGORY_DICT[go_component]
    except KeyError:
        with open(obsolete_terms_csv_file, "a") as f:
            csv_writer = csv.writer(f, delimiter="\t")
            csv_writer.writerow([term_id, uniprot_id])
        go_relation = None
        go_component_label = None

    return go_relation, go_component_label


def get_nodes_and_edges(
    source_name,
    uniprot_df,
    go_category_trees_dictionary,
    mondo_xrefs_dict,
    mondo_gene_dict,
    obsolete_terms_csv_file,
):
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
        EC_NUMBER_PARSED_COLUMN,
        PROTEIN_ID_PARSED_COLUMN,
        BINDING_SITE_PARSED_COLUMN,
        GO_PARSED_COLUMN,
        RHEA_PARSED_COLUMN,
    ]
    if (
        UNIPROT_DISEASE_COLUMN_NAME in uniprot_df.columns
        and UNIPROT_GENE_PRIMARY_COLUMN_NAME in uniprot_df.columns
    ):
        parsed_columns += [
            DISEASE_PARSED_COLUMN,
            GENE_PRIMARY_PARSED_COLUMN,
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
    ].apply(
        lambda x: x.split("(EC")[0].replace("[", "(").replace("]", ")") if not is_float(x) else x
    )
    uniprot_parse_df[BINDING_SITE_PARSED_COLUMN] = uniprot_df[
        UNIPROT_BINDING_SITE_COLUMN_NAME
    ].apply(parse_binding_site)
    uniprot_parse_df[GO_PARSED_COLUMN] = uniprot_df[UNIPROT_GO_COLUMN_NAME].apply(parse_go_entry)
    uniprot_parse_df[RHEA_PARSED_COLUMN] = uniprot_df[UNIPROT_RHEA_ID_COLUMN_NAME].apply(
        parse_rhea_entry
    )
    # Fields only in human uniprot query
    if UNIPROT_DISEASE_COLUMN_NAME in uniprot_df.columns:
        uniprot_parse_df[DISEASE_PARSED_COLUMN] = uniprot_df[UNIPROT_DISEASE_COLUMN_NAME].apply(
            lambda x: parse_disease(x, mondo_xrefs_dict)
        )
    if UNIPROT_GENE_PRIMARY_COLUMN_NAME in uniprot_df.columns:
        uniprot_parse_df[GENE_PRIMARY_PARSED_COLUMN] = uniprot_df[
            UNIPROT_GENE_PRIMARY_COLUMN_NAME
        ].apply(lambda x: parse_gene(x, mondo_gene_dict))

    for _, entry in uniprot_parse_df.iterrows():
        # Organism node
        node_data.append([entry[ORGANISM_PARSED_COLUMN], NCBI_CATEGORY])
        # Protein node
        node_data.append(
            [
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_CATEGORY,
                entry[PROTEIN_NAME_PARSED_COLUMN],
                "",
                "",
                source_name,
            ]
        )

        # EC node
        if entry[EC_NUMBER_PARSED_COLUMN]:
            for ec in entry[EC_NUMBER_PARSED_COLUMN]:
                node_data.append([ec, EC_CATEGORY])
                # Protein-ec edge
                edge_data.append(
                    [
                        entry[PROTEIN_ID_PARSED_COLUMN],
                        PROTEIN_TO_EC_EDGE,
                        ec,
                        RELATIONS_DICT[PROTEIN_TO_EC_EDGE],
                        source_name,
                    ]
                )
        # CHEBI node
        if entry[BINDING_SITE_PARSED_COLUMN]:
            for chebi in entry[BINDING_SITE_PARSED_COLUMN]:
                node_data.append([chebi, CHEMICAL_CATEGORY])
                # Chebi-protein edge
                edge_data.append(
                    [
                        chebi,
                        CHEMICAL_TO_PROTEIN_EDGE,
                        entry[PROTEIN_ID_PARSED_COLUMN],
                        RELATIONS_DICT[CHEMICAL_TO_PROTEIN_EDGE],
                        source_name,
                    ]
                )
        # Rhea node
        if entry[RHEA_PARSED_COLUMN]:
            for rhea in entry[RHEA_PARSED_COLUMN]:
                node_data.append([rhea, RHEA_CATEGORY])
                # Protein-rhea edge
                edge_data.append(
                    [
                        entry[PROTEIN_ID_PARSED_COLUMN],
                        PROTEIN_TO_RHEA_EDGE,
                        rhea,
                        RELATIONS_DICT[PROTEIN_TO_RHEA_EDGE],
                        source_name,
                    ]
                )
        # GO node
        if entry[GO_PARSED_COLUMN]:
            for go in entry[GO_PARSED_COLUMN]:
                #! Excluding obsolete terms
                predicate, go_category = get_go_relation_and_obsolete_terms(
                    go,
                    entry[PROTEIN_ID_PARSED_COLUMN],
                    go_category_trees_dictionary,
                    obsolete_terms_csv_file,
                )
                node_data.append([go, go_category])
                # Protein to go edge
                if not predicate:
                    continue
                edge_data.append(
                    [
                        entry[PROTEIN_ID_PARSED_COLUMN],
                        predicate,
                        go,
                        RELATIONS_DICT[predicate],
                        source_name,
                    ]
                )
        if (
            UNIPROT_DISEASE_COLUMN_NAME in uniprot_df.columns
            and UNIPROT_GENE_PRIMARY_COLUMN_NAME in uniprot_df.columns
        ):
            # Disease node
            if entry[DISEASE_PARSED_COLUMN]:
                for disease in entry[DISEASE_PARSED_COLUMN]:
                    node_data.append([disease, DISEASE_CATEGORY])
                    # Protein-disease edge
                    edge_data.append(
                        [
                            entry[PROTEIN_ID_PARSED_COLUMN],
                            PROTEIN_TO_DISEASE_EDGE,
                            disease,
                            RELATIONS_DICT[PROTEIN_TO_DISEASE_EDGE],
                            source_name,
                        ]
                    )
            # Gene node
            if entry[GENE_PRIMARY_PARSED_COLUMN]:
                # Gene-protein edge
                edge_data.append(
                    [
                        entry[GENE_PRIMARY_PARSED_COLUMN],
                        GENE_TO_PROTEIN_EDGE,
                        entry[PROTEIN_ID_PARSED_COLUMN],
                        RELATIONS_DICT[GENE_TO_PROTEIN_EDGE],
                        source_name,
                    ]
                )

        # Removing protein-organism edges for now
        # Protein-organism
        edge_data.append(
            [
                entry[PROTEIN_ID_PARSED_COLUMN],
                PROTEIN_TO_ORGANISM_EDGE,
                entry[ORGANISM_PARSED_COLUMN],
                RELATIONS_DICT[PROTEIN_TO_ORGANISM_EDGE],
                source_name,
            ]
        )

    return (node_data, edge_data)


def prepare_go_dictionary():
    """Generate dictionary of GO categories for each GO term."""
    go_category_trees_dict = {}
    with open(GO_CATEGORY_TREES_FILE, "r") as file:
        csv_reader = csv.DictReader(file, delimiter="\t")
        for row in csv_reader:
            go_category_trees_dict[row[GO_TERM_COLUMN]] = row[GO_CATEGORY_COLUMN]

    return go_category_trees_dict


def prepare_mondo_dictionary():
    """Generate dictionaries for disease xrefs and gene names from MONDO."""
    # Only needed to be run once, keeping code for future
    # Read MONDO xrefs file for diseases if it exists
    mondo_xrefs_dict = {}
    if MONDO_XREFS_FILEPATH.exists():
        with open(MONDO_XREFS_FILEPATH, "r") as file:
            csv_reader = csv.DictReader(file, delimiter="\t")
            for row in csv_reader:
                if OMIM_PREFIX in row["xref"]:
                    mondo_xrefs_dict[row["id"]] = row["xref"]
    # Read MONDO nodes file for gene names
    mondo_gene_dict = {}
    if MONDO_GENE_IDS_FILEPATH.exists():
        with open(MONDO_GENE_IDS_FILEPATH, "r") as file:
            csv_reader = csv.DictReader(file, delimiter="\t")
            for row in csv_reader:
                mondo_gene_dict[row["id"]] = row["name"]
    #! TODO: use oak
    else:
        mondo_nodes_file = (
            Path(__file__).parents[2] / "data" / "transformed" / "ontologies" / "mondo_nodes.tsv"
        )
        if mondo_nodes_file.exists():
            with open(mondo_nodes_file, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    if HGNC_NEW_PREFIX in row["id"]:
                        mondo_gene_dict[row["id"]] = row["name"]
        mondo_gene_df = pd.DataFrame(list(mondo_gene_dict.items()), columns=["id", "name"])
        mondo_gene_df.to_csv(MONDO_GENE_IDS_FILEPATH, sep="\t", index=False)

    return mondo_xrefs_dict, mondo_gene_dict


def process_lines(
    source_name,
    all_lines,
    headers,
    node_header,
    edge_header,
    node_filename,
    edge_filename,
    progress_class,
    go_category_dictionary,
    mondo_xrefs_dict,
    mondo_gene_dict,
    obsolete_terms_csv_file,
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
    :param go_category_dictionary: Dictionary of all GO Terms with their corresponding category.
    """
    list_of_rows = [s.split("\t") for s in all_lines[1:]]
    df = pd.DataFrame(list_of_rows, columns=headers)
    df = df[~(df == df.columns.to_series()).all(axis=1)]
    df.drop_duplicates(inplace=True)

    node_data, edge_data = get_nodes_and_edges(
        source_name,
        df,
        go_category_dictionary,
        mondo_xrefs_dict,
        mondo_gene_dict,
        obsolete_terms_csv_file,
    )
    # Write node and edge data to unique files
    # if len(node_data) > 0:
    with open(node_filename, "w", newline="") as nf:
        node_writer = csv.writer(nf, delimiter="\t")
        node_writer.writerow(node_header)  # Write header
        for node in progress_class(node_data, desc="Writing node data"):
            if len(node) < len(node_header):
                node.extend([None] * (len(node_header) - len(node)))
            node_writer.writerow(node)

    # if len(edge_data) > 0:
    with open(edge_filename, "w", newline="") as ef:
        edge_writer = csv.writer(ef, delimiter="\t")
        edge_writer.writerow(edge_header)  # Write header
        for edge in progress_class(edge_data, desc="Writing edge data"):
            if len(edge) < len(edge_header):
                edge.extend([None] * (len(edge_header) - len(edge)))
            edge_writer.writerow(edge)

    return node_filename, edge_filename


def check_string_in_tar(
    tar_file,
    uniprot_relevant_file_list,
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
    # # Check if uniprot_relevant_file_list exists
    # if os.path.exists(uniprot_relevant_file_list):
    #     # Read the existing file and return its content as a list of lines
    #     with open(uniprot_relevant_file_list, "r", encoding="utf-8") as f:
    #         return [line.rstrip("\n") for line in f]
    if os.path.exists(uniprot_relevant_file_list):
        # Read the existing tsv file and return its content as a list of lines
        with open(uniprot_relevant_file_list, "r", encoding="utf-8") as f:
            relevant_files = [line.rstrip("\n") for line in f]
            relevant_files_list_exists = True

    # Initialize the list to store matching members' content
    matching_members_content = []
    with tarfile.open(tar_file, "r:gz") as tar:
        if relevant_files_list_exists:
            members = [member for member in tar.getmembers() if member.name in relevant_files]
            # members = [
            #     member for member in tar.getmembers()
            # ]  # if member.name in relevant_files]
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
                        # No assembled proteomes case, otherwise only grab assembled proteomes
                        if count == 0:
                            count = len(lines)
                        if count > min_line_count:
                            # Get only first proteome listed if multiple
                            proteome_column_index = next(
                                (
                                    i
                                    for i, value in enumerate(lines[0].split("\t"))
                                    if UNIPROT_PROTEOME_COLUMN_NAME == value
                                ),
                                None,
                            )
                            lines = [
                                "\t".join(
                                    line.split("\t")[:proteome_column_index]
                                    + [line.split("\t")[proteome_column_index].split(";")[0]]
                                    + line.split("\t")[proteome_column_index + 1 :]
                                )
                                for line in lines
                            ]
                            # Add only unique lines to the set
                            matching_members_content.extend(lines)
                            # Add the member name to the list
                            relevant_files.append(member.name)

    # ! This is shelved for now since just getting filenames from a tsv should suffice.
    # # Write the content to the file as text
    # with open(uniprot_relevant_content_file, "w", encoding="utf-8") as f:
    #     f.write("\n".join(matching_members_content))
    if not relevant_files_list_exists:
        with open(uniprot_relevant_file_list, "w", encoding="utf-8") as f:
            f.write("\n".join(relevant_files))

    # Return the list of lines
    return matching_members_content


def create_pool(
    source_name,
    tar_file,
    n_workers,
    chunk_size_denominator,
    show_status,
    node_header,
    edge_header,
    output_node_file,
    output_edge_file,
    go_category_trees_dict,
    mondo_xrefs_dict,
    mondo_gene_dict,
    obsolete_terms_csv_file,
    uniprot_relevant_file_list,
    uniprot_tmp_ne_dir,
):
    """Process tar file in parallel threads."""
    progress_class = tqdm if show_status else DummyTqdm
    all_lines = check_string_in_tar(
        tar_file, uniprot_relevant_file_list, progress_class=progress_class
    )
    member_header = all_lines[0].split("\t")
    chunk_size = len(all_lines) // (chunk_size_denominator)
    print(
        f"Processing {len(all_lines)- 1} lines in {chunk_size_denominator} chunks of size {chunk_size}..."
    )
    line_chunks = [all_lines[i : i + chunk_size] for i in range(0, len(all_lines), chunk_size)]

    with Pool(n_workers) as pool:
        results = pool.starmap(
            process_lines,
            [
                (
                    source_name,
                    line_chunk,
                    member_header,
                    node_header,
                    edge_header,
                    f"{uniprot_tmp_ne_dir}/node_{uuid.uuid4()}.tsv",
                    f"{uniprot_tmp_ne_dir}/edge_{uuid.uuid4()}.tsv",
                    progress_class,
                    go_category_trees_dict,
                    mondo_xrefs_dict,
                    mondo_gene_dict,
                    obsolete_terms_csv_file,
                )
                for line_chunk in line_chunks
            ],
        )
        results = [result for result in results if result != (None, None)]

    # Combine individual node and edge files
    combined_node_filename = output_node_file
    combined_edge_filename = output_edge_file

    with open(combined_node_filename, "w", newline="") as cnf, open(
        combined_edge_filename, "w", newline=""
    ) as cef:
        node_writer = csv.writer(cnf, delimiter="\t")
        edge_writer = csv.writer(cef, delimiter="\t")

        # Write headers
        node_writer.writerow(node_header)
        edge_writer.writerow(edge_header)

        for node_file, edge_file in progress_class(results, desc="Combining node and edge files"):
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

    drop_duplicates(combined_node_filename)
    drop_duplicates(combined_edge_filename)
    drop_duplicates(obsolete_terms_csv_file, sort_by_column=GO_TERM_COLUMN)


def write_obsolete_file_header(obsolete_terms_csv_file):
    """Write obsolete header to file."""
    obsolete_terms_csv_header = [GO_TERM_COLUMN, UNIPROT_ID_COLUMN]

    with open(obsolete_terms_csv_file, "w") as f:
        obsolete_terms_csv_writer = csv.writer(f, delimiter="\t")
        obsolete_terms_csv_writer.writerow(obsolete_terms_csv_header)


def get_go_category_trees(go_oi):
    """
    Extract category of all GO terms using oak, and write to file.

    :param go_oi: A oaklib sql_implementation class to access GO information.
    :type go_oi: oaklib sql_implementation class
    """
    os.makedirs(ONTOLOGIES_TREES_DIR, exist_ok=True)
    with open(GO_CATEGORY_TREES_FILE, "w") as file:
        csv_writer = csv.writer(file, delimiter="\t")
        csv_writer.writerow([GO_CATEGORY_COLUMN, GO_TERM_COLUMN])

        for id in GO_TYPES_DICT.keys():
            term_decendants = list(
                go_oi.descendants(start_curies=id, predicates=[RDFS_SUBCLASS_OF], reflexive=True)
            )
            for term in term_decendants:
                r_list = [id, term]
                csv_writer.writerow(r_list)
