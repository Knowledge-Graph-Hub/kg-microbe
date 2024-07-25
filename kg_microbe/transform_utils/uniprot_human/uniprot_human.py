"""UniprotHuman Transform class."""

import os
from pathlib import Path
from typing import Optional, Union

from oaklib import get_adapter

from kg_microbe.transform_utils.constants import (
    GO_CATEGORY_TREES_FILE,
    RAW_DATA_DIR,
    UNIPROT_GENOME_FEATURES_HUMAN,
    UNIPROT_HUMAN_FILE,
    UNIPROT_HUMAN_RELEVANT_FILE_LIST,
    UNIPROT_HUMAN_TMP_DIR,
    UNIPROT_HUMAN_TMP_NE_DIR,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.uniprot_utils import (
    create_pool,
    get_go_category_trees,
    prepare_go_dictionary,
    prepare_mondo_dictionary,
    write_obsolete_file_header,
)

# file to keep track of obsolete terms from GO not included in graph
OBSOLETE_TERMS_CSV_FILE = UNIPROT_HUMAN_TMP_DIR / "go_obsolete_terms.tsv"


class UniprotHumanTransform(Transform):

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
        source_name = UNIPROT_GENOME_FEATURES_HUMAN
        super().__init__(source_name, input_dir, output_dir)
        self.go_oi = get_adapter("sqlite:obo:go")
        # Check if the file already exists
        if not GO_CATEGORY_TREES_FILE.exists():
            get_go_category_trees(self.go_oi)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Load Uniprot data from downloaded files, then transforms into graph format."""
        os.makedirs(UNIPROT_HUMAN_TMP_DIR, exist_ok=True)
        os.makedirs(UNIPROT_HUMAN_TMP_NE_DIR, exist_ok=True)
        go_category_trees_dict = prepare_go_dictionary()
        mondo_xrefs_dict, mondo_gene_dict = prepare_mondo_dictionary()

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)
        n_workers = os.cpu_count()
        chunk_size_denominator = 150 * n_workers

        write_obsolete_file_header(OBSOLETE_TERMS_CSV_FILE)

        tar_file = RAW_DATA_DIR / UNIPROT_HUMAN_FILE
        create_pool(
            self.source_name,
            tar_file,
            n_workers,
            chunk_size_denominator,
            show_status,
            self.node_header,
            self.edge_header,
            self.output_node_file,
            self.output_edge_file,
            go_category_trees_dict,
            mondo_xrefs_dict,
            mondo_gene_dict,
            OBSOLETE_TERMS_CSV_FILE,
            UNIPROT_HUMAN_RELEVANT_FILE_LIST,
            UNIPROT_HUMAN_TMP_NE_DIR,
        )
