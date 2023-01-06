"""Transform an ontology in Obograph JSON format."""

import gzip
import os
import shutil
from typing import Optional

from kgx.cli.cli_utils import transform

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.robot_utils import convert_to_json

ONTOLOGIES = {
    "NCBITransform": "ncbitaxon.json",
    "ChebiTransform": "chebi.owl.gz",
    "EnvoTransform": "envo.json",
    "GoTransform": "go.json",
}


class OntologyTransform(Transform):
    """Parse a raw form of an Ontology into nodes and edges."""

    def __init__(
        self, input_dir: Optional[str] = None, output_dir: Optional[str] = None
    ):
        """Initialize."""
        source_name = "ontologies"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Optional[str] = None) -> None:
        """Perform transformations to process an ontology.

        Args:
            data_file: data file to parse
        Returns:
            None.
        """
        if data_file:
            k = data_file.split(".")[0]
            data_file = os.path.join(self.input_base_dir, data_file)
            self.parse(k, data_file, k)
        else:
            # load all ontologies
            for k in ONTOLOGIES.keys():
                data_file = os.path.join(self.input_base_dir, ONTOLOGIES[k])
                self.parse(k, data_file, k)

    def parse(self, name: str, data_file: str, source: str) -> None:
        """Process the data_file.

        If the file is is compressed,
        decompress it.
        If the file isn't in obojson format,
        convert it first.
        Args:
            name: Name of the ontology
            data_file: data file to parse
            source: Source name
        Returns:
             None.
        """
        print(f"Parsing {data_file}")

        convert_this = False
        decompress_this = False

        if name in ["chebi"]:
            convert_this = True
            decompress_this = True

        if decompress_this:
            print("Decompressing...")
            outpath = data_file[:-3]
            with gzip.open(data_file, "rb") as data_file_gz:
                with open(outpath, "wb") as data_file_new:
                    shutil.copyfileobj(data_file_gz, data_file_new)
            
        if convert_this:
            print("Converting to obojson...")
            convert_to_json(self.input_base_dir, "CHEBI")
            data_file = os.path.join(self.input_base_dir, name + ".json")

        transform(
            inputs=[data_file],
            input_format="obojson",
            output=os.path.join(self.output_dir, name),
            output_format="tsv",
        )
