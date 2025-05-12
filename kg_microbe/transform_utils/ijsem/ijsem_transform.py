"""IJSEM tranform script."""

import os
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.constants import IJSEM_RESOURCE_FN
from kg_microbe.transform_utils.transform import Transform



class IJSEMTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate."""
        source_name = "ijsem"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        # replace with downloaded data filename for this source
        input_file = os.path.join(self.input_base_dir, "ijsem.zip")  # must exist already
        data_file = os.path.join(self.input_base_dir, IJSEM_RESOURCE_FN)  # must exist already

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        # Unzip file
        if not Path(data_file).is_file():
            os.system(f"unzip {input_file} -d {self.input_base_dir}")

        # transform data, something like:
        with (
            open(data_file, "r", encoding="latin-1") as f,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            # write headers (change default node/edge headers if necessary
            node.write("\t".join(self.node_header) + "\n")
            edge.write("\t".join(self.edge_header) + "\n")

            # transform data, something like:
            for i, line in enumerate(f):
                if i == 0:
                    # capture header
                    header = line.strip().split("\t")
                else:
                    # capture data
                    data = line.strip().split("\t")
                    data_dict = dict(zip(header, data))

                import pdb; pdb.set_trace()

        
