"""Uniprot Transform class."""

import csv
import gzip
import os
from pathlib import Path
from typing import Optional, Union

import requests
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    ASSOCIATED_WITH,
    CAS_RN_PREFIX,
    CHEBI_PREFIX,
    CHEBI_XREFS_FILEPATH,
    CHEMICAL_CATEGORY,
    CHEMICAL_TO_DISEASE_EDGE,
    CTD_CAS_RN_COLUMN,
    CTD_CHEMICAL_MESH_COLUMN,
    CTD_DISEASE_MESH_COLUMN,
    DISEASE_CATEGORY,
    MESH_PREFIX,
    MONDO_PREFIX,
    MONDO_XREFS_FILEPATH,
    NODE_NORMALIZER_URL,
    RAW_DATA_DIR,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates

RELATIONS_DICT = {
    CHEMICAL_TO_DISEASE_EDGE: ASSOCIATED_WITH,
}


class CtdTransform(Transform):

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
        source_name = "ctd"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        # Read CHEBI xrefs file for chemicals
        self.chebi_xref_dict = {}
        if CHEBI_XREFS_FILEPATH.exists():
            with open(CHEBI_XREFS_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    if CAS_RN_PREFIX in row["xref"]:
                        self.chebi_xref_dict[row["xref"]] = row["id"]
        # Read MONDO xrefs file for diseases if it exists
        self.mondo_xref_dict = {}
        if MONDO_XREFS_FILEPATH.exists():
            with open(MONDO_XREFS_FILEPATH, "r") as file:
                csv_reader = csv.DictReader(file, delimiter="\t")
                for row in csv_reader:
                    if MESH_PREFIX in row["xref"]:
                        self.mondo_xref_dict[row["xref"]] = row["id"]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        node_filename = self.output_node_file
        edge_filename = self.output_edge_file

        with open(node_filename, "w") as nf, open(edge_filename, "w") as ef:
            nodes_file_writer = csv.writer(nf, delimiter="\t")
            edges_file_writer = csv.writer(ef, delimiter="\t")

            nodes_file_writer.writerow(self.node_header)
            edges_file_writer.writerow(self.edge_header)

            ctd_tsv_file = RAW_DATA_DIR / "CTD_chemicals_diseases.tsv.gz"
            with gzip.open(ctd_tsv_file, "rt", encoding="utf-8") as file:
                # Skip lines until reaching the line containing "# Fields"
                for line in file:
                    if line.startswith("# Fields"):
                        # Read the next line as the header line
                        header_line = next(file)
                        header_line = header_line.replace("# ", "")
                        break

                # Skip lines until reaching the first non-comment line
                for line in file:
                    if not line.startswith("#"):
                        # Read the rest of the lines into a list
                        all_data = list(file)
                        break

                # Create a reader for the TSV data starting from the header line
                reader = csv.DictReader([header_line] + all_data, delimiter="\t")

                # Keep track of entities already mapped
                self.mapped_chemicals_dict = {}
                self.mapped_diseases_dict = {}
                for row in tqdm(reader):
                    node_data, edge_data = self._get_nodes_and_edges(row)
                    if len(edge_data) > 0:
                        for nodes in node_data:
                            nodes_file_writer.writerow(nodes)
                        for edges in edge_data:
                            edges_file_writer.writerow(edges)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)

    def _chemical_to_chebi(self, data):
        """
        Convert CAS-RN ID or MESH ID into CHEBI ID if available, otherwise leave unchanged.

        :param chemical_entry: A string containing the cas-rn id.
        :type chemical_entry: str
        :return: A chebi id.
        :rtype: str
        """
        cas_curie = CAS_RN_PREFIX + data[CTD_CAS_RN_COLUMN]
        mesh_curie = MESH_PREFIX + data[CTD_CHEMICAL_MESH_COLUMN]

        chemical = self.mapped_chemicals_dict.get(cas_curie)
        if chemical is None:
            chemical = self.mapped_chemicals_dict.get(mesh_curie)
        if chemical is None and data[CTD_CAS_RN_COLUMN] != "":
            chemical = self.chebi_xref_dict.get(cas_curie)
            self.mapped_chemicals_dict[cas_curie] = chemical
            self.mapped_chemicals_dict[mesh_curie] = chemical
        elif chemical is None:
            chemical = self._normalize_node_api(mesh_curie)
            self.mapped_chemicals_dict[mesh_curie] = chemical

        if chemical is None:
            chemical = mesh_curie
        return chemical

    def _disease_to_mondo(self, disease_entry):
        """
        Convert MESH ID into MONDO ID.

        :param disease_entry: A string containing the MESH id, otherwise leave unchanged.
        :type disease_entry: str
        :return: A MONDO id.
        :rtype: str
        """
        mondo_id = self.mapped_diseases_dict.get(disease_entry)
        if mondo_id is None:
            mondo_id = self.mondo_xref_dict.get(disease_entry)
            self.mapped_diseases_dict[disease_entry] = mondo_id

        if mondo_id is None:
            mondo_id = disease_entry
        return mondo_id

    # Takes cure in the form PREFIX:ID
    def _normalize_node_api(self, node_curie):

        url = NODE_NORMALIZER_URL + node_curie

        # Make the HTTP request to NodeNormalizer
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Write response to file if it contains data
        entries = response.json()[node_curie]
        try:
            if len(entries) > 1:  # .strip().split("\n")
                for iden in entries["equivalent_identifiers"]:
                    if iden["identifier"].split(":")[0] == CHEBI_PREFIX:
                        norm_node = iden["identifier"]
                        return norm_node
        # Handle case where node normalizer returns nothing
        except TypeError:
            return node_curie

        else:
            return node_curie

    def _get_nodes_and_edges(self, data):
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
        chemical = self._chemical_to_chebi(data)
        disease = self._disease_to_mondo(data[CTD_DISEASE_MESH_COLUMN])
        # Only add node if chebi and mondo nodes were found
        if CHEBI_PREFIX in chemical and MONDO_PREFIX in disease:
            # Add chemical
            node_data.append([chemical, CHEMICAL_CATEGORY])
            # Add disease
            node_data.append([disease, DISEASE_CATEGORY])
            # chemical-disease edge
            # Chebi-protein edge
            edge_data.append(
                [
                    chemical,
                    CHEMICAL_TO_DISEASE_EDGE,
                    disease,
                    RELATIONS_DICT[CHEMICAL_TO_DISEASE_EDGE],
                    "ctd",
                ]
            )
        return node_data, edge_data
