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

import yaml
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    ANTIBIOGRAM,
    ANTIBIOTIC_RESISTANCE,
    API_X_COLUMN,
    ATTRIBUTE_CATEGORY,
    BACDIVE_API_BASE_URL,
    BACDIVE_DIR,
    BACDIVE_ID_COLUMN,
    BACDIVE_MEDIUM_DICT,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    BIOLOGICAL_PROCESS,
    CATEGORY_COLUMN,
    CELL_MORPHOLOGY,
    COLONY_MORPHOLOGY,
    COMPOUND_PRODUCTION,
    CULTURE_AND_GROWTH_CONDITIONS,
    CULTURE_LINK,
    CULTURE_MEDIUM,
    CULTURE_NAME,
    CURIE_COLUMN,
    DSM_NUMBER,
    DSM_NUMBER_COLUMN,
    ENZYMES,
    EXTERNAL_LINKS,
    EXTERNAL_LINKS_CULTURE_NUMBER,
    EXTERNAL_LINKS_CULTURE_NUMBER_COLUMN,
    FATTY_ACID_PROFILE,
    GENERAL,
    GENERAL_DESCRIPTION,
    HALOPHILY,
    HAS_PHENOTYPE,
    IS_GROWN_IN,
    ISOLATION,
    ISOLATION_COLUMN,
    ISOLATION_SAMPLING_ENV_INFO,
    ISOLATION_SOURCE_CATEGORIES,
    ISOLATION_SOURCE_CATEGORIES_COLUMN,
    KEYWORDS,
    KEYWORDS_COLUMN,
    MATCHING_LEVEL,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_URL_COLUMN,
    MEDIUM_CATEGORY,
    MEDIUM_ID_COLUMN,
    MEDIUM_LABEL_COLUMN,
    MEDIUM_URL_COLUMN,
    METABOLITE_PRODUCTION,
    METABOLITE_TESTS,
    METABOLITE_UTILIZATION,
    MORPHOLOGY,
    MORPHOLOGY_CELL_MORPHOLOGY_COLUMN,
    MORPHOLOGY_COLONY_MORPHOLOGY_COLUMN,
    MORPHOLOGY_MULTICELLULAR_MORPHOLOGY_COLUMN,
    MORPHOLOGY_MULTIMEDIA_COLUMN,
    MORPHOLOGY_PIGMENTATION_COLUMN,
    MULTICELLULAR_MORPHOLOGY,
    MULTIMEDIA,
    MUREIN,
    NCBI_CATEGORY,
    NCBI_TO_MEDIUM_EDGE,
    NCBITAXON_DESCRIPTION_COLUMN,
    NCBITAXON_ID,
    NCBITAXON_ID_COLUMN,
    NCBITAXON_PREFIX,
    NUTRITION_TYPE,
    OBSERVATION,
    OXYGEN_TOLERANCE,
    PHENOTYPIC_CATEGORY,
    PHYSIOLOGY_AND_METABOLISM,
    PIGMENTATION,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RISK_ASSESSMENT,
    RISK_ASSESSMENT_COLUMN,
    SAFETY_INFO,
    SPECIES,
    SPORE_FORMATION,
    STRAIN,
    TOLERANCE,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.pandas_utils import drop_duplicates


class BacDiveTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """Instantiate part."""
        source_name = "BacDive"
        super().__init__(source_name, input_dir, output_dir)
        self.ncbi_impl = get_adapter("sqlite:obo:ncbitaxon")

    def _get_label_via_oak(self, curie: str):
        prefix = curie.split(":")[0]
        if prefix.startswith("NCBI"):
            (_, label) = list(self.ncbi_impl.labels([curie]))[0]
        return label

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
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
            ISOLATION_COLUMN,
            ISOLATION_SOURCE_CATEGORIES_COLUMN,
            MORPHOLOGY_MULTIMEDIA_COLUMN,
            MORPHOLOGY_MULTICELLULAR_MORPHOLOGY_COLUMN,
            MORPHOLOGY_COLONY_MORPHOLOGY_COLUMN,
            MORPHOLOGY_CELL_MORPHOLOGY_COLUMN,
            MORPHOLOGY_PIGMENTATION_COLUMN,
            RISK_ASSESSMENT_COLUMN,
        ]

        PHYS_AND_META_COL_NAMES = [
            BACDIVE_ID_COLUMN,
            OBSERVATION,
            ENZYMES,
            METABOLITE_UTILIZATION,
            METABOLITE_PRODUCTION,
            METABOLITE_TESTS,
            API_X_COLUMN,
            OXYGEN_TOLERANCE,
            SPORE_FORMATION,
            HALOPHILY,
            ANTIBIOTIC_RESISTANCE,
            MUREIN,
            COMPOUND_PRODUCTION,
            FATTY_ACID_PROFILE,
            TOLERANCE,
            ANTIBIOGRAM,
            NUTRITION_TYPE,
        ]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with (
            open(str(BACDIVE_TMP_DIR / "bacdive.tsv"), "w") as tsvfile_1,
            open(str(BACDIVE_TMP_DIR / "bacdive_physiology_metabolism.tsv"), "w") as tsvfile_2,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
            open(str(BACDIVE_DIR / "keywords.yaml"), "r") as keywords_file,
        ):
            writer = csv.writer(tsvfile_1, delimiter="\t")
            # Write the column names to the output file
            writer.writerow(COLUMN_NAMES)
            writer_2 = csv.writer(tsvfile_2, delimiter="\t")
            writer_2.writerow(PHYS_AND_META_COL_NAMES)

            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            index = self.edge_header.index(PROVIDED_BY_COLUMN)
            self.edge_header[index] = PRIMARY_KNOWLEDGE_SOURCE_COLUMN
            edge_writer.writerow(self.edge_header)

            keyword_data = yaml.safe_load(keywords_file)

            keyword_map = {
                second_level_key: nested_data
                for first_level_value in keyword_data.values()
                for second_level_key, nested_data in first_level_value.items()
            }

            # Choose the appropriate context manager based on the flag
            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(
                total=len(input_json.items()) + 1, desc="Processing files"
            ) as progress:
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
                    isolation = value.get(ISOLATION_SAMPLING_ENV_INFO, {}).get(ISOLATION)
                    isolation_source_categories = value.get(ISOLATION_SAMPLING_ENV_INFO, {}).get(
                        ISOLATION_SOURCE_CATEGORIES
                    )

                    # if value.get(ISOLATION_SAMPLING_ENV_INFO):
                    #     if set(value.get(ISOLATION_SAMPLING_ENV_INFO).keys()) - set(
                    #         [
                    #             ISOLATION,
                    #             ISOLATION_SOURCE_CATEGORIES,
                    #         ]
                    #     ):
                    # TODO: Get information from here.
                    morphology_multimedia = value.get(MORPHOLOGY, {}).get(MULTIMEDIA)
                    morphology_multicellular = value.get(MORPHOLOGY, {}).get(
                        MULTICELLULAR_MORPHOLOGY
                    )
                    morphology_colony = value.get(MORPHOLOGY, {}).get(COLONY_MORPHOLOGY)
                    morphology_cell = value.get(MORPHOLOGY, {}).get(CELL_MORPHOLOGY)
                    morphology_pigmentation = value.get(MORPHOLOGY, {}).get(PIGMENTATION)
                    phys_and_metabolism_observation = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        OBSERVATION
                    )
                    phys_and_metabolism_enzymes = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        ENZYMES
                    )
                    phys_and_metabolism_metabolite_utilization = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(METABOLITE_UTILIZATION)
                    phys_and_metabolism_metabolite_production = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(METABOLITE_PRODUCTION)
                    phys_and_metabolism_metabolite_tests = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(METABOLITE_TESTS)
                    phys_and_metabolism_API = (
                        {
                            k: v
                            for k, v in value.get(PHYSIOLOGY_AND_METABOLISM, {}).items()
                            if k.startswith("API ")
                        }
                        if any(
                            k.startswith("API ") for k in value.get(PHYSIOLOGY_AND_METABOLISM, {})
                        )
                        else None
                    )
                    phys_and_metabolism_oxygen_tolerance = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(OXYGEN_TOLERANCE)
                    phys_and_metabolism_spore_formation = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(SPORE_FORMATION)
                    phys_and_metabolism_halophily = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        HALOPHILY
                    )
                    phys_and_metabolism_antibiotic_resistance = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(ANTIBIOTIC_RESISTANCE)
                    phys_and_metabolism_murein_type = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        MUREIN
                    )
                    phys_and_metabolism_compound_production = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(COMPOUND_PRODUCTION)
                    phys_and_metabolism_fatty_acid_profile = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(FATTY_ACID_PROFILE)
                    phys_and_metabolism_tolerance = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        TOLERANCE
                    )
                    phys_and_metabolism_antibiogram = value.get(PHYSIOLOGY_AND_METABOLISM, {}).get(
                        ANTIBIOGRAM
                    )
                    phys_and_metabolism_nutrition_type = value.get(
                        PHYSIOLOGY_AND_METABOLISM, {}
                    ).get(NUTRITION_TYPE)

                    risk_assessment = value.get(SAFETY_INFO, {}).get(RISK_ASSESSMENT)

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

                    keywords = general_info.get(KEYWORDS, "")
                    nodes_from_keywords = {
                        key: keyword_map[key.lower().replace(" ", "_").replace("-", "_")]
                        for key in keywords
                        if key.lower().replace(" ", "_").replace("-", "_") in keyword_map
                    }

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
                        str(keywords),
                        medium_id,
                        medium_label,
                        medium_url,
                        mediadive_url,
                        isolation,
                        isolation_source_categories,
                        morphology_multimedia,
                        morphology_multicellular,
                        morphology_colony,
                        morphology_cell,
                        morphology_pigmentation,
                        risk_assessment,
                    ]

                    writer.writerow(data)  # writing the data

                    phys_and_meta_data = [
                        BACDIVE_PREFIX + key,
                        phys_and_metabolism_observation,
                        phys_and_metabolism_enzymes,
                        phys_and_metabolism_metabolite_utilization,
                        phys_and_metabolism_metabolite_production,
                        phys_and_metabolism_metabolite_tests,
                        phys_and_metabolism_API,
                        phys_and_metabolism_oxygen_tolerance,
                        phys_and_metabolism_spore_formation,
                        phys_and_metabolism_halophily,
                        phys_and_metabolism_antibiotic_resistance,
                        phys_and_metabolism_murein_type,
                        phys_and_metabolism_compound_production,
                        phys_and_metabolism_fatty_acid_profile,
                        phys_and_metabolism_tolerance,
                        phys_and_metabolism_antibiogram,
                        phys_and_metabolism_nutrition_type,
                    ]

                    if not all(item is None for item in phys_and_meta_data[1:]):
                        writer_2.writerow(phys_and_meta_data)

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

                    if ncbitaxon_id and nodes_from_keywords:
                        nodes_data_to_write = [
                            [value[CURIE_COLUMN], value[CATEGORY_COLUMN], key]
                            for key, value in nodes_from_keywords.items()
                        ]
                        nodes_data_to_write = [
                            sublist + [None] * 11 for sublist in nodes_data_to_write
                        ]

                        node_writer.writerows(nodes_data_to_write)

                        for _, value in nodes_from_keywords.items():
                            edges_data_to_write = [
                                ncbitaxon_id,
                                value[PREDICATE_COLUMN],
                                value[CURIE_COLUMN],
                                (
                                    HAS_PHENOTYPE
                                    if value[CATEGORY_COLUMN]
                                    in [PHENOTYPIC_CATEGORY, ATTRIBUTE_CATEGORY]
                                    else BIOLOGICAL_PROCESS
                                ),
                                BACDIVE_PREFIX + key,
                            ]

                            edge_writer.writerow(edges_data_to_write)

                    progress.set_description(f"Processing BacDive file: {key}.yaml")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
