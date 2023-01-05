"""Transform an ontology in Obograph JSON format."""

import os
from typing import Optional

from kgx.cli.cli_utils import transform

from kg_microbe.transform_utils.transform import Transform

ONTOLOGIES = {
    "NCBITransform": "ncbitaxon.json",
    "ChebiTransform": "chebi.json",
    "EnvoTransform": "envo.json",
    "GoTransform": "go.json",
}


class OntologyTransform(Transform):
    """Parse an Obograph JSON form of an Ontology into nodes and edges."""

    def __init__(self, input_dir: str = None, output_dir: str = None):
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
        Args:
            name: Name of the ontology
            data_file: data file to parse
            source: Source name
        Returns:
             None.
        """
        print(f"Parsing {data_file}")

        transform(
            inputs=[data_file],
            input_format="obojson",
            output=os.path.join(self.output_dir, name),
            output_format="tsv",
        )
