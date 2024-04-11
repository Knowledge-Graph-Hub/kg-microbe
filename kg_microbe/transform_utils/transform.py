"""Transform utility module."""

import shutil
from pathlib import Path
from typing import Optional, Union

import yaml

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    IRI_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBJECT_COLUMN,
    SUBSETS_COLUMN,
    SYNONYM_COLUMN,
    XREF_COLUMN,
)


class Transform:

    """Parent class for transforms, that sets up a lot of default file info."""

    DATA_DIR = Path(__file__).parent / "data"
    DEFAULT_INPUT_DIR = DATA_DIR / "raw"
    DEFAULT_OUTPUT_DIR = DATA_DIR / "transformed"

    def __init__(
        self,
        source_name,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        nlp: bool = False,
    ):
        """
        Instantiate Transform object.

        :param source_name: Name of resource.
        :param input_dir: Location of input directory, defaults to None
        :param output_dir: Location of output directory, defaults to None
        :param nlp: Boolean for possibility of using NLP or not, defaults to False
        """
        # default columns, can be appended to or overwritten as necessary
        self.source_name = source_name
        self.node_header = [
            ID_COLUMN,
            CATEGORY_COLUMN,
            NAME_COLUMN,
            DESCRIPTION_COLUMN,
            XREF_COLUMN,
            PROVIDED_BY_COLUMN,
            SYNONYM_COLUMN,
            IRI_COLUMN,
            OBJECT_COLUMN,
            PREDICATE_COLUMN,
            RELATION_COLUMN,
            SAME_AS_COLUMN,
            SUBJECT_COLUMN,
            SUBSETS_COLUMN,
        ]
        self.edge_header = [
            SUBJECT_COLUMN,
            PREDICATE_COLUMN,  # was "edge_label",
            OBJECT_COLUMN,
            RELATION_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
        ]

        # default dirs
        self.input_base_dir = Path(input_dir) if input_dir else self.DEFAULT_INPUT_DIR
        self.output_base_dir = Path(output_dir) if output_dir else self.DEFAULT_OUTPUT_DIR
        self.output_dir = self.output_base_dir / source_name

        # default filenames
        self.output_node_file = self.output_dir / "nodes.tsv"
        self.output_edge_file = self.output_dir / "edges.tsv"
        self.output_json_file = self.output_dir / "nodes_edges.json"
        self.subset_terms_file = self.input_base_dir / "subset_terms.tsv"

        Path.mkdir(self.output_dir, exist_ok=True, parents=True)

        if nlp:
            self.nlp_dir = self.input_base_dir / "nlp"
            self.nlp_input_dir = self.nlp_dir / "input"
            self.nlp_output_dir = self.nlp_dir / "output"
            self.nlp_terms_dir = self.nlp_dir / "terms"
            self.nlp_stopwords_dir = self.nlp_dir / "stopwords"

            # Delete previously developed files
            if Path.exists(self.nlp_input_dir):
                shutil.rmtree(self.nlp_input_dir)
                shutil.rmtree(self.nlp_stopwords_dir)

            Path.mkdir(self.nlp_dir, exist_ok=True, parents=True)
            Path.mkdir(self.nlp_input_dir, exist_ok=True, parents=True)
            Path.mkdir(self.nlp_output_dir, exist_ok=True, parents=True)
            Path.mkdir(self.nlp_terms_dir, exist_ok=True, parents=True)
            Path.mkdir(self.nlp_stopwords_dir, exist_ok=True, parents=True)

            with open("stopwords.yaml", "r") as stop_list:
                doc = yaml.safe_load(stop_list)  # , Loader=yaml.FullLoader)
                stop_words = doc["English"]

            with open(self.nlp_stopwords_dir / "stopWords.txt", "w") as stop_terms:
                # stop_terms.write(stop_words)
                for word in stop_words.split(" "):
                    stop_terms.write(word + "\n")

            self.output_nlp_file = self.nlp_output_dir / "nlpOutput.tsv"

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):
        """
        Run the transform.

        :param data_file: Input data file, defaults to None
        """
        pass

    def pass_through(self, nodes_file: str, edges_file: str) -> None:
        """
        Copy nodes and edges files to output directory.

        :param nodes_file: nodes files to take from raw directory and put in transform
                directory
        :param edges_file: edges files to take from raw directory and put in transform
                directory
        """
        for f in [nodes_file, edges_file]:
            shutil.copy(f, self.output_dir)
