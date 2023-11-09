"""
BacDive KG.

Input: any file in data/raw/ (that was downloaded by placing a URL in incoming.txt/yaml
and running `run.py download`.

Output: transformed data in data/raw/bacdive_strains.json:

Output these two files:
- nodes.tsv
- edges.tsv
"""
import csv
import json
import os
import re
from pathlib import Path
from typing import Optional, Union

from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    BACDIVE_API_BASE_URL,
    BACDIVE_ID_COLUMN,
    BACDIVE_MEDIUM_DICT,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    CULTURE_AND_GROWTH_CONDITIONS,
    CULTURE_LINK,
    CULTURE_MEDIUM,
    CULTURE_NAME,
    DSM_NUMBER,
    DSM_NUMBER_COLUMN,
    EXTERNAL_LINKS,
    EXTERNAL_LINKS_CULTURE_NUMBER,
    EXTERNAL_LINKS_CULTURE_NUMBER_COLUMN,
    GENERAL,
    GENERAL_DESCRIPTION,
    IS_GROWN_IN,
    KEYWORDS,
    KEYWORDS_COLUMN,
    MATCHING_LEVEL,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_URL_COLUMN,
    MEDIUM_CATEGORY,
    MEDIUM_ID_COLUMN,
    MEDIUM_LABEL_COLUMN,
    MEDIUM_URL_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_MEDIUM_EDGE,
    NCBITAXON_DESCRIPTION_COLUMN,
    NCBITAXON_ID,
    NCBITAXON_ID_COLUMN,
    NCBITAXON_PREFIX,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    SPECIES,
    STRAIN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates


class BacDiveTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate part."""
        source_name = "BacDive"
        super().__init__(source_name, input_dir, output_dir)
        self.ncbi_impl = get_adapter("sqlite:obo:ncbitaxon")

    def _get_label_via_oak(self, curie: str):
        prefix = curie.split(":")[0]
        if prefix.startswith("NCBI"):
            (_, label) = list(self.ncbi_impl.labels([curie]))[0]
        return label

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):
        """Run the transformation."""
        # replace with downloaded data filename for this source
        input_file = os.path.join(self.input_base_dir, "bacdive_strains.json")  # must exist already
        # Read the JSON file into the variable input_json
        with open(input_file, "r") as f:
            input_json = json.load(f)

        COLUMN_NAMES = [
            BACDIVE_ID_COLUMN,
            DSM_NUMBER_COLUMN,
            EXTERNAL_LINKS_CULTURE_NUMBER_COLUMN,
            NCBITAXON_ID_COLUMN,
            NCBITAXON_DESCRIPTION_COLUMN,
            KEYWORDS_COLUMN,
            MEDIUM_ID_COLUMN,
            MEDIUM_LABEL_COLUMN,
            MEDIUM_URL_COLUMN,
            MEDIADIVE_URL_COLUMN,
        ]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with open(str(BACDIVE_TMP_DIR / "bacdive.tsv"), "w") as csvfile, open(
            self.output_node_file, "w"
        ) as node, open(self.output_edge_file, "w") as edge:
            writer = csv.writer(csvfile, delimiter="\t")
            # Write the column names to the output file
            writer.writerow(COLUMN_NAMES)

            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            index = self.edge_header.index(PROVIDED_BY_COLUMN)
            self.edge_header[index] = PRIMARY_KNOWLEDGE_SOURCE_COLUMN
            edge_writer.writerow(self.edge_header)

            with tqdm(total=len(input_json.items()) + 1, desc="Processing files") as progress:
                for key, value in input_json.items():
                    # * Uncomment this block ONLY if you want to view the split *******
                    # * contents of the JSON file source into YAML files.
                    # import yaml
                    # from kg_microbe.transform_utils.constants import BACDIVE_YAML_DIR
                    # fn: Path = Path(str(BACDIVE_YAML_DIR / key) + ".yaml")
                    # if not fn.is_file():
                    #     with open(str(fn), "w") as outfile:
                    #         yaml.dump(value, outfile)
                    # *******************************************************************

                    # Get "General" information
                    general_info = value.get(GENERAL, {})
                    # bacdive_id = general_info.get(BACDIVE_ID) # This is the same as `key`
                    dsm_number = general_info.get(DSM_NUMBER)
                    external_links = value.get(EXTERNAL_LINKS, {})
                    culture_number_from_external_links = None
                    if EXTERNAL_LINKS_CULTURE_NUMBER in external_links:
                        culture_number_from_external_links = (
                            external_links[EXTERNAL_LINKS_CULTURE_NUMBER] or ""
                        ).split(",")

                        if dsm_number is None:
                            dsm_number = next(
                                (
                                    re.search(r"DSM (\d+)", item).group(1)
                                    for item in culture_number_from_external_links
                                    if re.search(r"DSM (\d+)", item)
                                ),
                                None,
                            )

                    # SUBJECT part
                    ncbitaxon_id = None
                    ncbi_label = None
                    ncbi_description = None

                    if NCBITAXON_ID in general_info:
                        if isinstance(general_info[NCBITAXON_ID], list):
                            ncbi_of_interest = next(
                                (
                                    ncbi[NCBITAXON_ID]
                                    for ncbi in general_info[NCBITAXON_ID]
                                    if MATCHING_LEVEL in ncbi
                                    and (
                                        ncbi[MATCHING_LEVEL] == STRAIN
                                        or (
                                            ncbi[MATCHING_LEVEL] == SPECIES
                                            and not any(
                                                ncbi_temp[MATCHING_LEVEL] == STRAIN
                                                for ncbi_temp in general_info[NCBITAXON_ID]
                                            )
                                        )
                                    )
                                ),
                                None,
                            )
                            if ncbi_of_interest is not None:
                                ncbitaxon_id = NCBITAXON_PREFIX + str(ncbi_of_interest)
                        else:
                            ncbitaxon_id = NCBITAXON_PREFIX + str(
                                general_info[NCBITAXON_ID][NCBITAXON_ID]
                            )

                        ncbi_description = general_info.get(GENERAL_DESCRIPTION, "")
                        ncbi_label = self._get_label_via_oak(ncbitaxon_id)

                    keywords = str(general_info.get(KEYWORDS, ""))

                    # OBJECT PART
                    medium_id = None
                    medium_label = None
                    medium_url = None
                    mediadive_url = None
                    if (
                        CULTURE_AND_GROWTH_CONDITIONS in value
                        and value[CULTURE_AND_GROWTH_CONDITIONS]
                    ):
                        if (
                            CULTURE_MEDIUM in value[CULTURE_AND_GROWTH_CONDITIONS]
                            and value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM]
                        ):
                            if (
                                CULTURE_LINK in value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM]
                                and value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM][
                                    CULTURE_LINK
                                ]
                            ):
                                medium_url = str(
                                    value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM][
                                        CULTURE_LINK
                                    ]
                                )
                                medium_id = next(
                                    (
                                        medium_url.replace(val, key)
                                        for key, val in BACDIVE_MEDIUM_DICT.items()
                                        if medium_url.startswith(val)
                                    ),
                                    None,
                                )
                                medium_label = value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM][
                                    CULTURE_NAME
                                ]

                                mediadive_url = medium_url.replace(
                                    BACDIVE_API_BASE_URL, MEDIADIVE_REST_API_BASE_URL
                                )

                    data = [
                        BACDIVE_PREFIX + key,
                        dsm_number,
                        culture_number_from_external_links,
                        ncbitaxon_id,
                        ncbi_description,
                        keywords,
                        medium_id,
                        medium_label,
                        medium_url,
                        mediadive_url,
                    ]

                    writer.writerow(data)  # writing the data

                    if ncbitaxon_id and medium_id:
                        # Combine list creation and extension
                        nodes_data_to_write = [
                            [ncbitaxon_id, NCBI_CATEGORY, ncbi_label],
                            [medium_id, MEDIUM_CATEGORY, medium_label],
                        ]
                        nodes_data_to_write = [
                            sublist + [None] * 11 for sublist in nodes_data_to_write
                        ]
                        node_writer.writerows(nodes_data_to_write)

                        edges_data_to_write = [
                            ncbitaxon_id,
                            NCBI_TO_MEDIUM_EDGE,
                            medium_id,
                            IS_GROWN_IN,
                            BACDIVE_PREFIX + key,
                        ]

                        edge_writer.writerow(edges_data_to_write)

                    progress.set_description(f"Processing BacDive file: {key}.yaml")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
