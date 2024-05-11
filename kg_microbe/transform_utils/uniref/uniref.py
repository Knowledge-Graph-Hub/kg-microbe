"""UniRef Transformation Module."""

import csv
import gc
import os
import sys
from pathlib import Path
from typing import Optional, Union

from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CLUSTER_CATEGORY,
    NCBI_CATEGORY,
    NCBI_TO_CLUSTER_EDGE,
    NCBITAXON_PREFIX,
    OCCURS_IN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.pandas_utils import drop_duplicates

csv.field_size_limit(sys.maxsize - 1)  # _csv.Error: field larger than field limit (131072)


class UnirefTransform(Transform):

    """UniRef Transformation Class."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """Instantiate part."""
        source_name = "Uniref"
        super().__init__(source_name, input_dir, output_dir)
        self.ncbi_impl = get_adapter("sqlite:obo:ncbitaxon")

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        input_file = os.path.join(
            self.input_base_dir, "uniref90_api_subset.tsv"
        )  # must exist already

        progress_class = tqdm if show_status else DummyTqdm

        with open(input_file, "r") as tsvfile, open(self.output_node_file, "w") as nodes_file, open(
            self.output_edge_file, "w"
        ) as edges_file:
            # Create a CSV reader specifying the delimiter as a tab character
            tsvreader = csv.DictReader(tsvfile, delimiter="\t")
            node_writer = csv.writer(nodes_file, delimiter="\t")
            edge_writer = csv.writer(edges_file, delimiter="\t")

            # Write the header for the files
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            with progress_class(desc="Processing clusters...") as progress:
                # Iterate over each row in the TSV file
                for row in tsvreader:
                    # Extract the desired fields
                    cluster_id = row["Cluster ID"].replace("_", ":")
                    cluster_name = row["Cluster Name"].lstrip("Cluster:").strip()
                    ncbitaxon_ids = [
                        NCBITAXON_PREFIX + x.strip() for x in row["Organism IDs"].split(";") if x
                    ]
                    ncbi_labels = [
                        ncbi_label.strip()
                        for ncbi_label in row["Organisms"].split(";")
                        if ncbi_label
                    ]
                    nodes_data_to_write = [
                        [ncbitaxon_id, NCBI_CATEGORY, ncbi_label]
                        for ncbitaxon_id, ncbi_label in zip(
                            ncbitaxon_ids, ncbi_labels, strict=False
                        )
                    ]
                    # nodes_data_to_write.append([cluster_id, CLUSTER_CATEGORY, cluster_name])
                    nodes_data_to_write = [
                        sublist + [None] * (len(self.node_header) - 3)
                        for sublist in nodes_data_to_write
                    ]
                    node_writer.writerows(nodes_data_to_write)
                    gc.collect()

                    # # Write the nodes data directly to the file
                    # for ncbitaxon_id, ncbi_label in zip(ncbitaxon_ids, ncbi_labels, strict=False):
                    #     node_data_to_write = [
                    #         ncbitaxon_id,
                    #         NCBI_CATEGORY,
                    #         ncbi_label,
                    #     ]
                    #     # Extend the row to match the header length
                    #     node_data_to_write.extend([None] * (len(self.node_header) - 3))
                    #     node_writer.writerow(node_data_to_write)

                    # Write the cluster node
                    cluster_node_data = [cluster_id, CLUSTER_CATEGORY, cluster_name]
                    cluster_node_data.extend([None] * (len(self.node_header) - 3))
                    node_writer.writerow(cluster_node_data)

                    # Write the edge for the cluster
                    edges_data_to_write = [
                        [
                            ncbitaxon_id,
                            NCBI_TO_CLUSTER_EDGE,
                            cluster_id,
                            OCCURS_IN,
                            cluster_id.split(":")[0],
                        ]
                        for ncbitaxon_id in ncbitaxon_ids
                    ]
                    edge_writer.writerows(edges_data_to_write)
                    # # Write the edges for the cluster
                    # for ncbitaxon_id in ncbitaxon_ids:
                    #     edge_data_to_write = [
                    #         NCBITAXON_PREFIX + ncbitaxon_id.strip(),
                    #         NCBI_TO_CLUSTER_EDGE,
                    #         cluster_id,
                    #         OCCURS_IN,
                    #         cluster_id.split(":")[0],
                    #     ]
                    #     edge_writer.writerow(edge_data_to_write)

                    progress.set_description(f"Processing Cluster: {cluster_id}")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update(500)
                    gc.collect()

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
