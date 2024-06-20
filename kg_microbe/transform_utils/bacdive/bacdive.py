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
    ACTIVITY_KEY,
    ANTIBIOGRAM,
    ANTIBIOTIC_RESISTANCE,
    API_X_COLUMN,
    ASSAY_PREFIX,
    ASSAY_TO_NCBI_EDGE,
    ASSESSED_ACTIVITY_RELATIONSHIP,
    ATTRIBUTE_CATEGORY,
    BACDIVE_API_BASE_URL,
    BACDIVE_ID_COLUMN,
    BACDIVE_MAPPING_CAS_RN_ID,
    BACDIVE_MAPPING_CHEBI_ID,
    BACDIVE_MAPPING_EC_ID,
    BACDIVE_MAPPING_ENZYME_LABEL,
    BACDIVE_MAPPING_FILE,
    BACDIVE_MAPPING_KEGG_ID,
    BACDIVE_MAPPING_PSEUDO_ID_COLUMN,
    BACDIVE_MAPPING_SUBSTRATE_LABEL,
    BACDIVE_MEDIUM_DICT,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    BIOLOGICAL_PROCESS,
    CATEGORY_COLUMN,
    CELL_MORPHOLOGY,
    CHEBI_PREFIX,
    CLASS,
    COLONY_MORPHOLOGY,
    COMPOUND_PRODUCTION,
    CULTURE_AND_GROWTH_CONDITIONS,
    CULTURE_LINK,
    CULTURE_MEDIUM,
    CULTURE_NAME,
    CURIE_COLUMN,
    CUSTOM_CURIES_YAML_FILE,
    DOMAIN,
    DSM_NUMBER,
    DSM_NUMBER_COLUMN,
    EC_KEY,
    EC_PREFIX,
    ENZYME_TO_ASSAY_EDGE,
    ENZYME_TO_SUBSTRATE_EDGE,
    ENZYMES,
    EXACT_MATCH,
    EXTERNAL_LINKS,
    EXTERNAL_LINKS_CULTURE_NUMBER,
    EXTERNAL_LINKS_CULTURE_NUMBER_COLUMN,
    FAMILY,
    FATTY_ACID_PROFILE,
    FULL_SCIENTIFIC_NAME,
    GENERAL,
    GENERAL_DESCRIPTION,
    GENUS,
    HALOPHILY,
    HAS_PARTICIPANT,
    HAS_PHENOTYPE,
    ID_COLUMN,
    IS_GROWN_IN,
    ISOLATION,
    ISOLATION_COLUMN,
    ISOLATION_SAMPLING_ENV_INFO,
    ISOLATION_SOURCE_CATEGORIES,
    ISOLATION_SOURCE_CATEGORIES_COLUMN,
    ISOLATION_SOURCE_PREFIX,
    KEYWORDS,
    KEYWORDS_COLUMN,
    LOCATION_OF,
    LPSN,
    MATCHING_LEVEL,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_URL_COLUMN,
    MEDIUM_CATEGORY,
    MEDIUM_ID_COLUMN,
    MEDIUM_LABEL_COLUMN,
    MEDIUM_URL_COLUMN,
    METABOLITE_CATEGORY,
    METABOLITE_CHEBI_KEY,
    METABOLITE_KEY,
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
    NAME_COLUMN,
    NAME_TAX_CLASSIFICATION,
    NCBI_CATEGORY,
    NCBI_TO_ENZYME_EDGE,
    NCBI_TO_ISOLATION_SOURCE_EDGE,
    NCBI_TO_MEDIUM_EDGE,
    NCBI_TO_METABOLITE_PRODUCTION_EDGE,
    NCBI_TO_METABOLITE_UTILIZATION_EDGE,
    NCBITAXON_DESCRIPTION_COLUMN,
    NCBITAXON_ID,
    NCBITAXON_ID_COLUMN,
    NCBITAXON_PREFIX,
    NUTRITION_TYPE,
    OBJECT_ID_COLUMN,
    OBSERVATION,
    ORDER,
    OXYGEN_TOLERANCE,
    PARTICIPATES_IN,
    PHENOTYPIC_CATEGORY,
    PHYLUM,
    PHYSIOLOGY_AND_METABOLISM,
    PIGMENTATION,
    PLUS_SIGN,
    PREDICATE_COLUMN,
    PRODUCTION_KEY,
    RDFS_SUBCLASS_OF,
    RISK_ASSESSMENT,
    RISK_ASSESSMENT_COLUMN,
    SAFETY_INFO,
    SAME_AS_PREDICATE,
    SPECIES,
    SPORE_FORMATION,
    STRAIN,
    STRAIN_DESIGNATION,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    SUBSTRATE_CATEGORY,
    SUBSTRATE_TO_ASSAY_EDGE,
    SYNONYM,
    SYNONYMS,
    TOLERANCE,
    TYPE_STRAIN,
    UTILIZATION_ACTIVITY,
    UTILIZATION_TYPE_TESTED,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.oak_utils import get_label
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

    def _flatten_to_dicts(self, obj):
        if isinstance(obj, dict):
            # If it's a dictionary, return it in a list
            return [obj]
        elif isinstance(obj, list):
            # If it's a list, iterate over its elements
            dicts = []
            for item in obj:
                # Recursively flatten each item and extend the result list
                dicts.extend(self._flatten_to_dicts(item))
            return dicts
        else:
            # If it's neither a list nor a dictionary, return an empty list
            return []

    def _get_substrate_id(self, record):
        # Check for 'CHEBI_ID' first
        if record.get(BACDIVE_MAPPING_CHEBI_ID):
            return record[BACDIVE_MAPPING_CHEBI_ID]

        # If 'CHEBI_ID' is empty or not present, check 'KEGG_ID'
        if record.get(BACDIVE_MAPPING_KEGG_ID):
            return record[BACDIVE_MAPPING_KEGG_ID]

        # If 'KEGG_ID' is empty or not present, check 'CAS_RN_ID'
        if record.get(BACDIVE_MAPPING_CAS_RN_ID):
            return record[BACDIVE_MAPPING_CAS_RN_ID]

        # If none are present, return None or an appropriate default value
        return None

    def _get_enzyme_id(self, record):
        # Check for 'EC_ID' first
        if record.get(BACDIVE_MAPPING_EC_ID):
            return record[BACDIVE_MAPPING_EC_ID]

        # If none are present, return None or an appropriate default value
        return None

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

        NAME_TAX_CLASSIFICATION_COL_NAMES = [
            BACDIVE_ID_COLUMN,
            NCBITAXON_ID_COLUMN,
            DOMAIN,
            PHYLUM,
            CLASS,
            ORDER,
            FAMILY,
            GENUS,
            SPECIES,
            FULL_SCIENTIFIC_NAME,
            STRAIN_DESIGNATION,
            TYPE_STRAIN,
            SYNONYMS,
            LPSN,
        ]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with (
            open(str(BACDIVE_TMP_DIR / "bacdive.tsv"), "w") as tsvfile_1,
            open(str(BACDIVE_TMP_DIR / "bacdive_physiology_metabolism.tsv"), "w") as tsvfile_2,
            open(str(BACDIVE_TMP_DIR / BACDIVE_MAPPING_FILE), "r") as tsvfile_3,
            open(str(BACDIVE_TMP_DIR / "bacdive_name_tax_classification.tsv"), "w") as tsvfile_4,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
            open(CUSTOM_CURIES_YAML_FILE, "r") as cc_file,
        ):
            writer = csv.writer(tsvfile_1, delimiter="\t")
            # Write the column names to the output file
            writer.writerow(COLUMN_NAMES)
            writer_2 = csv.writer(tsvfile_2, delimiter="\t")
            writer_2.writerow(PHYS_AND_META_COL_NAMES)
            writer_3 = csv.writer(tsvfile_4, delimiter="\t")
            writer_3.writerow(NAME_TAX_CLASSIFICATION_COL_NAMES)

            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            custom_curie_data = yaml.safe_load(cc_file)
            bacdive_mappings_list_of_dicts = list(csv.DictReader(tsvfile_3, delimiter="\t"))

            # ! BacDive Mapping file processing.
            # Nodes to be written to the node file.
            # Get substrate from the bacdive mapping file
            assay_nodes_to_write = []
            # Edges to be written to the edge file.
            assay_edges_to_write = []
            for assay in bacdive_mappings_list_of_dicts:
                # enzyme to assay edge.
                ec_id = self._get_enzyme_id(assay)
                if ec_id:
                    assay_nodes_to_write.append(
                        [
                            ec_id,
                            PHENOTYPIC_CATEGORY,
                            assay[BACDIVE_MAPPING_ENZYME_LABEL],
                        ]
                        + [None] * (len(self.node_header) - 3)
                    )
                    assay_edges_to_write.append(
                        [
                            ec_id,
                            ENZYME_TO_ASSAY_EDGE,
                            assay[BACDIVE_MAPPING_PSEUDO_ID_COLUMN],
                            ASSESSED_ACTIVITY_RELATIONSHIP,
                            BACDIVE_MAPPING_FILE,
                        ]
                    )
                # substrate to assay edge.
                substrate_id = self._get_substrate_id(assay)
                if substrate_id:
                    assay_nodes_to_write.append(
                        [
                            substrate_id,
                            SUBSTRATE_CATEGORY,
                            assay[BACDIVE_MAPPING_SUBSTRATE_LABEL],
                        ]
                        + [None] * (len(self.node_header) - 3)
                    )
                    assay_edges_to_write.append(
                        [
                            substrate_id,
                            SUBSTRATE_TO_ASSAY_EDGE,
                            assay[BACDIVE_MAPPING_PSEUDO_ID_COLUMN],
                            PARTICIPATES_IN,
                            BACDIVE_MAPPING_FILE,
                        ]
                    )
                # substrate to enzyme edge
                if ec_id and substrate_id:
                    assay_edges_to_write.append(
                        [
                            ec_id,
                            ENZYME_TO_SUBSTRATE_EDGE,
                            substrate_id,
                            PARTICIPATES_IN,
                            BACDIVE_MAPPING_FILE,
                        ]
                    )
                if assay_edges_to_write:
                    edge_writer.writerows(assay_edges_to_write)
                if assay_nodes_to_write:
                    node_writer.writerows(assay_nodes_to_write)

            keyword_map = {
                second_level_key: nested_data
                for first_level_value in custom_curie_data.values()
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
                        ISOLATION_SOURCE_CATEGORIES, []
                    )

                    # if value.get(ISOLATION_SAMPLING_ENV_INFO):
                    #     # TODO: Get information from here.
                    #     import pdb

                    #     pdb.set_trace()
                    #     if set(value.get(ISOLATION_SAMPLING_ENV_INFO).keys()) - set(
                    #         [
                    #             ISOLATION,
                    #             ISOLATION_SOURCE_CATEGORIES,
                    #         ]
                    #     ):
                    #         import pdb

                    #         pdb.set_trace()
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
                    name_tax_classification = value.get(NAME_TAX_CLASSIFICATION, {})

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
                        ncbi_label = get_label(self.ncbi_impl, ncbitaxon_id)
                        if ncbi_label is None:
                            ncbi_label = ncbi_description

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

                    lpsn = name_tax_classification.get(LPSN)
                    synonyms = lpsn.get(SYNONYMS, {}) if SYNONYMS in lpsn else None
                    if isinstance(synonyms, list):
                        synonym_parsed = " | ".join(synonym.get(SYNONYM, {}) for synonym in synonyms)
                    elif isinstance(synonyms, dict):
                        synonym_parsed = synonyms.get(SYNONYM, {})
                    else:
                        synonym_parsed = None

                    name_tax_classification_data = [
                        BACDIVE_PREFIX + key,
                        ncbitaxon_id,
                        name_tax_classification.get(DOMAIN),
                        name_tax_classification.get(PHYLUM),
                        name_tax_classification.get(CLASS),
                        name_tax_classification.get(ORDER),
                        name_tax_classification.get(FAMILY),
                        name_tax_classification.get(GENUS),
                        name_tax_classification.get(SPECIES),
                        name_tax_classification.get(FULL_SCIENTIFIC_NAME),
                        name_tax_classification.get(STRAIN_DESIGNATION),
                        name_tax_classification.get(TYPE_STRAIN),
                        synonym_parsed,
                        lpsn,
                    ]

                    if not all(item is None for item in name_tax_classification_data[2:]):
                        writer_3.writerow(name_tax_classification_data)

                    if ncbitaxon_id and medium_id:
                        # Combine list creation and extension
                        nodes_data_to_write = [
                            [ncbitaxon_id, NCBI_CATEGORY, ncbi_label],
                            [medium_id, MEDIUM_CATEGORY, medium_label],
                        ]
                        nodes_data_to_write = [
                            sublist + [None] * (len(self.node_header) - 3)
                            for sublist in nodes_data_to_write
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
                            [value[CURIE_COLUMN], value[CATEGORY_COLUMN], value[NAME_COLUMN]]
                            for _, value in nodes_from_keywords.items()
                        ]
                        nodes_data_to_write.append([ncbitaxon_id, NCBI_CATEGORY, ncbi_label])
                        nodes_data_to_write = [
                            sublist + [None] * (len(self.node_header) - 3)
                            for sublist in nodes_data_to_write
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

                    if ncbitaxon_id and culture_number_from_external_links:
                        for culture_number in culture_number_from_external_links:
                            culture_number_cleaned = culture_number.strip().replace(" ", "-")
                            strain_curie = STRAIN_PREFIX + culture_number_cleaned
                            node_writer.writerow(
                                [strain_curie, NCBI_CATEGORY, culture_number.strip()]
                                + [None] * (len(self.node_header) - 3)
                            )
                            edge_writer.writerow(
                                [
                                    strain_curie,
                                    SUBCLASS_PREDICATE,
                                    ncbitaxon_id,
                                    RDFS_SUBCLASS_OF,
                                    BACDIVE_PREFIX + key,
                                ]
                            )

                    if phys_and_metabolism_enzymes:
                        postive_activity_enzymes = None
                        if isinstance(phys_and_metabolism_enzymes, list):
                            postive_activity_enzymes = [
                                {f"{EC_PREFIX}{enzyme.get(EC_KEY)}": f"{enzyme.get('value')}"}
                                for enzyme in phys_and_metabolism_enzymes
                                if enzyme.get(ACTIVITY_KEY) == PLUS_SIGN and enzyme.get(EC_KEY)
                            ]
                        elif isinstance(phys_and_metabolism_enzymes, dict):
                            activity = phys_and_metabolism_enzymes.get(ACTIVITY_KEY)
                            if activity == PLUS_SIGN and phys_and_metabolism_enzymes.get(EC_KEY):
                                ec_value = f"{EC_PREFIX}{phys_and_metabolism_enzymes.get(EC_KEY)}"
                                value = phys_and_metabolism_enzymes.get("value")
                                postive_activity_enzymes = [{ec_value: value}]

                        else:
                            print(f"{phys_and_metabolism_enzymes} data not recorded.")
                        if postive_activity_enzymes:
                            enzyme_nodes_to_write = [
                                [k, PHENOTYPIC_CATEGORY, v] + [None] * (len(self.node_header) - 3)
                                for inner_dict in postive_activity_enzymes
                                for k, v in inner_dict.items()
                            ]
                            enzyme_nodes_to_write.append(
                                [ncbitaxon_id, NCBI_CATEGORY, ncbi_label]
                                + [None] * (len(self.node_header) - 3)
                            )
                            node_writer.writerows(enzyme_nodes_to_write)

                            for inner_dict in postive_activity_enzymes:
                                for k, _ in inner_dict.items():
                                    enzyme_edges_to_write = [
                                        ncbitaxon_id,
                                        NCBI_TO_ENZYME_EDGE,
                                        k,
                                        HAS_PHENOTYPE,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    edge_writer.writerow(enzyme_edges_to_write)

                    if phys_and_metabolism_metabolite_utilization:
                        positive_chebi_activity = None
                        if isinstance(phys_and_metabolism_metabolite_utilization, list):
                            positive_chebi_activity = []
                            # no_chebi_activity = defaultdict(list)
                            for metabolite in phys_and_metabolism_metabolite_utilization:
                                # ! NO CURIE associated to metabolite.
                                # if (
                                #     METABOLITE_CHEBI_KEY not in metabolite
                                #     and metabolite.get(UTILIZATION_ACTIVITY) == PLUS_SIGN
                                # ):
                                #     no_chebi_activity.setdefault("NO_CURIE", []).append(
                                #         [
                                #             metabolite[METABOLITE_KEY],
                                #             metabolite.get(UTILIZATION_TYPE_TESTED),
                                #         ]
                                #     )
                                #     positive_chebi_activity.append(no_chebi_activity)

                                if (
                                    METABOLITE_CHEBI_KEY in metabolite
                                    and metabolite.get(UTILIZATION_ACTIVITY) == PLUS_SIGN
                                ):
                                    chebi_key = f"{CHEBI_PREFIX}{metabolite[METABOLITE_CHEBI_KEY]}"
                                    positive_chebi_activity.append(
                                        {
                                            chebi_key: [
                                                metabolite[METABOLITE_KEY],
                                                metabolite.get(UTILIZATION_TYPE_TESTED),
                                            ]
                                        }
                                    )

                        elif isinstance(phys_and_metabolism_metabolite_utilization, dict):
                            utilization_activity = phys_and_metabolism_metabolite_utilization.get(
                                UTILIZATION_ACTIVITY
                            )
                            if (
                                utilization_activity == PLUS_SIGN
                                and phys_and_metabolism_metabolite_utilization.get(
                                    METABOLITE_CHEBI_KEY
                                )
                            ):
                                chebi_key = (
                                    f"{CHEBI_PREFIX}"
                                    f"{phys_and_metabolism_metabolite_utilization.get(METABOLITE_CHEBI_KEY)}"
                                )
                                metabolite_value = phys_and_metabolism_metabolite_utilization.get(
                                    METABOLITE_KEY
                                )
                                positive_chebi_activity = [{chebi_key: metabolite_value}]
                        else:
                            print(
                                f"{phys_and_metabolism_metabolite_utilization} data not recorded."
                            )
                        if positive_chebi_activity:
                            meta_util_nodes_to_write = [
                                [k, METABOLITE_CATEGORY, v[0]]
                                + [None] * (len(self.node_header) - 3)
                                for inner_dict in positive_chebi_activity
                                for k, v in inner_dict.items()
                            ]
                            node_writer.writerows(meta_util_nodes_to_write)

                            for inner_dict in positive_chebi_activity:
                                for k, _ in inner_dict.items():
                                    meta_util_edges_to_write = [
                                        ncbitaxon_id,
                                        NCBI_TO_METABOLITE_UTILIZATION_EDGE,
                                        k,
                                        HAS_PARTICIPANT,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    edge_writer.writerow(meta_util_edges_to_write)

                    if phys_and_metabolism_metabolite_production:
                        positive_chebi_production = None
                        if isinstance(phys_and_metabolism_metabolite_production, list):
                            positive_chebi_production = []
                            # no_chebi_production = defaultdict(list)
                            for metabolite in phys_and_metabolism_metabolite_production:
                                if (
                                    METABOLITE_CHEBI_KEY in metabolite
                                    and metabolite.get(PRODUCTION_KEY) == "yes"
                                ):
                                    chebi_key = f"{CHEBI_PREFIX}{metabolite[METABOLITE_CHEBI_KEY]}"
                                    positive_chebi_production.append(
                                        {chebi_key: metabolite[METABOLITE_KEY]}
                                    )
                                # ! NO CURIE associated to metabolite.
                                # if (
                                #     METABOLITE_CHEBI_KEY not in metabolite and metabolite.get(PRODUCTION_KEY) == "yes"
                                # ):
                                #     no_chebi_production.setdefault("NO_CURIE", []).append(metabolite[METABOLITE_KEY])
                                #     positive_chebi_production.append(no_chebi_production)

                        elif isinstance(phys_and_metabolism_metabolite_production, dict):
                            production = phys_and_metabolism_metabolite_production.get(
                                PRODUCTION_KEY
                            )
                            if (
                                production == "yes"
                                and phys_and_metabolism_metabolite_production.get(
                                    METABOLITE_CHEBI_KEY
                                )
                            ):
                                chebi_key = (
                                    f"{CHEBI_PREFIX}"
                                    f"{phys_and_metabolism_metabolite_production.get(METABOLITE_CHEBI_KEY)}"
                                )
                                metabolite_value = phys_and_metabolism_metabolite_production.get(
                                    METABOLITE_KEY
                                )
                                positive_chebi_production = [{chebi_key: metabolite_value}]

                        else:
                            print(f"{phys_and_metabolism_metabolite_production} data not recorded.")

                        if positive_chebi_production:
                            metabolite_production_nodes_to_write = [
                                [k, METABOLITE_CATEGORY, v] + [None] * (len(self.node_header) - 3)
                                for inner_dict in positive_chebi_production
                                for k, v in inner_dict.items()
                            ]
                            node_writer.writerows(metabolite_production_nodes_to_write)

                            for inner_dict in positive_chebi_production:
                                for k, _ in inner_dict.items():
                                    metabolite_production_edges_to_write = [
                                        ncbitaxon_id,
                                        NCBI_TO_METABOLITE_PRODUCTION_EDGE,
                                        k,
                                        BIOLOGICAL_PROCESS,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    edge_writer.writerow(metabolite_production_edges_to_write)

                    if phys_and_metabolism_API:
                        values = self._flatten_to_dicts(list(phys_and_metabolism_API.values()))
                        assay_name = list(phys_and_metabolism_API.keys())[0]
                        assay_name_norm = assay_name.replace(" ", "_")
                        meta_assay = {
                            assay_name_norm + ":" + k
                            for k, v in values[0].items()
                            if v == PLUS_SIGN
                        }

                        if meta_assay:
                            metabolism_nodes_to_write = [
                                [
                                    ASSAY_PREFIX + m.replace(":", "_"),
                                    PHENOTYPIC_CATEGORY,
                                    assay_name + " - " + m.split(":")[-1],
                                ]
                                + [None] * (len(self.node_header) - 3)
                                for m in meta_assay
                                if not m.startswith(ASSAY_PREFIX)
                            ]
                            node_writer.writerows(metabolism_nodes_to_write)

                            metabolism_edges_to_write = [
                                [
                                    ASSAY_PREFIX + m.replace(":", "_"),
                                    ASSAY_TO_NCBI_EDGE,
                                    ncbitaxon_id,
                                    ASSESSED_ACTIVITY_RELATIONSHIP,
                                    BACDIVE_PREFIX + key,
                                ]
                                for m in meta_assay
                                if not m.startswith(ASSAY_PREFIX)
                            ]

                            edge_writer.writerows(metabolism_edges_to_write)

                    if (
                        name_tax_classification
                        and name_tax_classification.get(TYPE_STRAIN) == "yes"
                    ):
                        if "," in name_tax_classification.get(STRAIN_DESIGNATION, ""):
                            strain_designations = name_tax_classification.get(
                                STRAIN_DESIGNATION
                            ).split(", ")
                            curated_strain_ids = [
                                strain_designation.strip()
                                .replace(" ", "-")
                                .replace('"', "")
                                .replace("(", "")
                                .replace(")", "")
                                for strain_designation in strain_designations
                            ]
                        else:
                            curated_strain_ids = [
                                name_tax_classification.get(
                                    STRAIN_DESIGNATION, f"of_{ncbitaxon_id}"
                                )
                                .strip()
                                .replace(" ", "-")
                                .replace('"', "")
                                .replace("(", "")
                                .replace(")", "")
                            ]
                        curated_strain_label = (
                            name_tax_classification.get(
                                FULL_SCIENTIFIC_NAME, f"strain_of {ncbi_label}"
                            )
                            .replace("<l>", "")
                            .replace("</l>", "")
                        )
                        curated_strain_label = re.sub(r"\s+", " ", curated_strain_label)
                        curated_strain_label = re.sub(r"<[^>]+>", "", curated_strain_label)
                        curated_strain_label = re.sub(r"\s+", " ", curated_strain_label).strip()
                        if synonym_parsed is None:
                            node_writer.writerows(
                                [STRAIN_PREFIX + curated_strain_id, NCBI_CATEGORY, curated_strain_label]
                                + [None] * (len(self.node_header) - 3)
                                for curated_strain_id in curated_strain_ids
                                if curated_strain_id
                            )
                        else:
                            node_writer.writerows(
                                [STRAIN_PREFIX + curated_strain_id, NCBI_CATEGORY, curated_strain_label]
                                + [None] * 3 
                                + [synonym_parsed] + [None] * (len(self.node_header) - 7)
                                for curated_strain_id in curated_strain_ids
                                if curated_strain_id
                            )
                        edge_writer.writerows(
                            [
                                STRAIN_PREFIX + curated_strain_id,
                                SUBCLASS_PREDICATE,
                                ncbitaxon_id,
                                RDFS_SUBCLASS_OF,
                                BACDIVE_PREFIX + key,
                            ]
                            for curated_strain_id in curated_strain_ids
                        )
                        # Equivalencies in strain IDs established as edges
                        if len(curated_strain_ids) > 1:
                            for i in range(len(curated_strain_ids)):
                                for j in range(i + 1, len(curated_strain_ids)):
                                    edge_writer.writerow(
                                        [
                                            STRAIN_PREFIX + curated_strain_ids[i],
                                            SAME_AS_PREDICATE,
                                            STRAIN_PREFIX + curated_strain_ids[j],
                                            EXACT_MATCH,
                                            BACDIVE_PREFIX + key,
                                        ]
                                    )

                    # Uncomment and handle isolation_source code
                    all_values = []
                    if isinstance(isolation_source_categories, list):
                        for category in isolation_source_categories:
                            all_values.extend(category.values())
                    elif isinstance(isolation_source_categories, dict):
                        all_values.extend(category.values())
                    all_values = [
                        ISOLATION_SOURCE_PREFIX
                        + i.replace(" ", "_").replace("-", "_").replace("#", "")
                        for i in all_values
                    ]
                    for isol_source in all_values:
                        node_writer.writerow(
                            [isol_source, "", isolation] + [None] * (len(self.node_header) - 3)
                        )
                        edge_writer.writerow(
                            [
                                ncbitaxon_id,
                                NCBI_TO_ISOLATION_SOURCE_EDGE,
                                isol_source,
                                LOCATION_OF,
                                self.source_name,
                            ]
                        )

                    progress.set_description(f"Processing BacDive file: {key}.yaml")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(self.output_node_file, consolidation_columns=[ID_COLUMN, NAME_COLUMN])
        drop_duplicates(self.output_edge_file, consolidation_columns=[OBJECT_ID_COLUMN])
