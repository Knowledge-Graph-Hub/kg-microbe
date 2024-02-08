"""Ontology transform module."""

import gzip
import shutil
from pathlib import Path
from typing import Optional, Union

# from kgx.transformer import Transformer
from kgx.cli.cli_utils import transform

from kg_microbe.transform_utils.constants import (
    EXCLUSION_TERMS_FILE,
    NCBITAXON_PREFIX,
    ROBOT_REMOVED_SUFFIX,
)
from kg_microbe.utils.robot_utils import (
    convert_to_json,
    remove_convert_to_json,
)

from ..transform import Transform

ONTOLOGIES = {
    # "HpTransform": "hp.json",
    # 'GoTransform': 'go-plus.json',
    "ncbitaxon": "ncbitaxon.owl.gz",
    "chebi": "chebi.owl.gz",
    "envo": "envo.json",
    "go": "go.json",
}


class OntologyTransform(Transform):

    """OntologyTransform parses an Obograph JSON form of an Ontology into nodes nad edges."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate object."""
        source_name = "ontologies"
        super().__init__(source_name, input_dir, output_dir)

    def run(
        self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True
    ) -> None:
        """
        Transform an ontology.

        :param data_file: data file to parse
        :return: None.
        """
        if data_file:
            k = str(data_file).split(".")[0]
            data_file = self.input_base_dir / data_file
            self.parse(k, data_file, k)
        else:
            # load all ontologies
            for k in ONTOLOGIES.keys():
                data_file = self.input_base_dir / ONTOLOGIES[k]
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: Optional[Path], source: str) -> None:
        """
        Process the data_file.

        :param name: Name of the ontology.
        :param data_file: data file to parse.
        :param source: Source name.
        :return: None.
        """
        if data_file.suffixes == [".owl", ".gz"]:
            if NCBITAXON_PREFIX.strip(":").lower() in str(
                data_file
            ):  # or CHEBI_PREFIX.strip(":").lower() in str(data_file):
                if NCBITAXON_PREFIX.strip(":").lower() in str(data_file):
                    json_path = str(data_file).replace(".owl.gz", ROBOT_REMOVED_SUFFIX + ".json")
                    if not Path(json_path).is_file():
                        self.decompress(data_file)
                        with open(str(self.input_base_dir / EXCLUSION_TERMS_FILE), "r") as f:
                            terms = [
                                line.strip() for line in f if line.lower().startswith(name.lower())
                            ]
                        remove_convert_to_json(str(self.input_base_dir), name, terms)
                # elif CHEBI_PREFIX.strip(":").lower() in str(data_file):
                #     json_path = str(data_file).replace(".owl.gz", ROBOT_EXTRACT_SUFFIX + ".json")
                #     owl_path = str(data_file).strip(".gz")
                #     # Convert CHEBI owl => JSON each time to handle varying terms (if any) in CHEBI_NODES_FILENAME
                #     if not Path(owl_path).is_file():
                #         self.decompress(data_file)
                #     terms = str(self.input_base_dir / CHEBI_NODES_FILENAME)
                #     extract_convert_to_json(str(self.input_base_dir), name, terms, "BOT")
            else:
                json_path = str(data_file).replace("owl.gz", "json")
                if not Path(json_path).is_file():
                    # Unzip the file
                    self.decompress(data_file)
                    print(f"Converting {data_file} to obojson...")
                convert_to_json(str(self.input_base_dir), name)

            data_file = json_path

        transform(
            inputs=[data_file],
            input_format="obojson",
            output=self.output_dir / name,
            output_format="tsv",
        )

    def decompress(self, data_file):
        """Unzip file."""
        print(f"Decompressing {data_file}...")
        with gzip.open(data_file, "rb") as f_in:
            with open(data_file.parent / data_file.stem, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
