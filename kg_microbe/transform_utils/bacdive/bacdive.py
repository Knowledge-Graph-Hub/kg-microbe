"""
BacDive KG transform.

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
    ASSESSED_ACTIVITY_RELATIONSHIP,
    ATTRIBUTE_CATEGORY,
    BACDIVE,
    BACDIVE_API_BASE_URL,
    BACDIVE_ENVIRONMENT_CATEGORY,
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
    CAPABLE_OF,
    CATEGORY_COLUMN,
    CELL_MORPHOLOGY,
    CHEBI_KEY,
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
    EC_CATEGORY,
    EC_KEY,
    EC_PREFIX,
    ENZYME_TO_ASSAY_EDGE,
    ENZYME_TO_SUBSTRATE_EDGE,
    ENZYMES,
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
    HAS_PHENOTYPE_PREDICATE,
    ID_COLUMN,
    IS_GROWN_IN,
    ISOLATION,
    ISOLATION_COLUMN,
    ISOLATION_SAMPLING_ENV_INFO,
    ISOLATION_SOURCE_CATEGORIES,
    ISOLATION_SOURCE_CATEGORIES_COLUMN,
    ISOLATION_SOURCE_CATEGORY,
    ISOLATION_SOURCE_PREFIX,
    KEYWORDS,
    KEYWORDS_COLUMN,
    LOCATION_OF,
    LPSN,
    MATCHING_LEVEL,
    MEDIADIVE_MEDIUM_PREFIX,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_URL_COLUMN,
    MEDIUM_CATEGORY,
    MEDIUM_ID_COLUMN,
    MEDIUM_KEY,
    MEDIUM_LABEL_COLUMN,
    MEDIUM_URL_COLUMN,
    METABOLITE_CATEGORY,
    METABOLITE_CHEBI_KEY,
    METABOLITE_KEY,
    METABOLITE_MAPPING_FILE,
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
    NCBI_TO_ISOLATION_SOURCE_EDGE,
    NCBI_TO_MEDIUM_EDGE,
    NCBI_TO_METABOLITE_RESISTANCE_EDGE,
    NCBI_TO_METABOLITE_SENSITIVITY_EDGE,
    NCBITAXON_DESCRIPTION_COLUMN,
    NCBITAXON_ID,
    NCBITAXON_ID_COLUMN,
    NCBITAXON_PREFIX,
    NCBITAXON_SOURCE,
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
    PREDICATE_COLUMN,
    PRODUCTION_KEY,
    RDFS_SUBCLASS_OF,
    RESISTANCE_KEY,
    RISK_ASSESSMENT,
    RISK_ASSESSMENT_COLUMN,
    SAFETY_INFO,
    SENSITIVITY_KEY,
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
    TRANSLATION_TABLE_FOR_IDS,
    TRANSLATION_TABLE_FOR_LABELS,
    TYPE_STRAIN,
    UTILIZATION_ACTIVITY,
    UTILIZATION_TYPE_TESTED,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.mapping_file_utils import (
    _build_metpo_tree,
    load_assay_kit_mappings,
    load_metpo_enzyme_mappings,
    load_metpo_mappings,
    load_metpo_metabolite_production_mappings,
    load_metpo_metabolite_utilization_mappings,
    uri_to_curie,
)
from kg_microbe.utils.oak_utils import get_label
from kg_microbe.utils.pandas_utils import drop_duplicates
from kg_microbe.utils.string_coding import remove_nextlines

# Anitibiotic resistance
if Path(METABOLITE_MAPPING_FILE).is_file():
    with open(METABOLITE_MAPPING_FILE, "r") as f:
        METABOLITE_MAP = json.load(f)
else:
    METABOLITE_MAP = {}


class BacDiveTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """Instantiate part."""
        source_name = BACDIVE
        super().__init__(source_name, input_dir, output_dir)
        self.ncbi_impl = get_adapter(f"sqlite:{NCBITAXON_SOURCE}")
        self.bacdive_metpo_mappings = load_metpo_mappings("bacdive keyword synonym")
        self.bacdive_metpo_tree = _build_metpo_tree()
        self.metpo_metabolite_utilization_mappings = load_metpo_metabolite_utilization_mappings()
        self.metpo_metabolite_production_mappings = load_metpo_metabolite_production_mappings()
        self.metpo_enzyme_mappings = load_metpo_enzyme_mappings()
        self.assay_kit_mappings = load_assay_kit_mappings()

    def _extract_value_from_json_path(self, record: dict, json_path: str):
        """
        Extract values from a BacDive record using a JSON path.

        :param record: The BacDive record dictionary
        :param json_path: Dot-separated path like "Physiology and metabolism.oxygen tolerance.oxygen tolerance"
        :return: List of extracted values (empty list if path not found)
        """
        parts = json_path.split(".")
        current = record

        # Traverse the path
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return []
            else:
                return []

        # Handle the final value
        if isinstance(current, list):
            # If it's a list of dicts, extract the last key from path from each dict
            result = []
            last_key = parts[-1]
            for item in current:
                if isinstance(item, dict):
                    value = item.get(last_key)
                    if value:
                        result.append(str(value).strip())
                elif item:
                    result.append(str(item).strip())
            return result
        elif isinstance(current, dict):
            # If it's a dict, extract the value using the last part of the path
            last_key = parts[-1]
            value = current.get(last_key)
            if value:
                return [str(value).strip()]
            return []
        elif current is not None:
            # It's a scalar value
            return [str(current).strip()]
        else:
            return []

    def _process_phenotype_by_metpo_parent(
        self, record: dict, parent_iri: str, species_with_strains: list, key: str, node_writer, edge_writer
    ):
        """
        Process phenotype data using METPO tree parent node to extract values dynamically.

        :param record: The BacDive record dictionary
        :param parent_iri: The METPO IRI of the parent node (e.g., "METPO:1000601" for oxygen preference)
        :param species_with_strains: List of organism IDs to create edges for
        :param key: BacDive ID for provenance
        :param node_writer: CSV writer for nodes
        :param edge_writer: CSV writer for edges
        """
        parent_node = self.bacdive_metpo_tree.get(parent_iri)
        if not parent_node or not parent_node.bacdive_json_paths:
            return

        for json_path in parent_node.bacdive_json_paths:
            extracted_values = self._extract_value_from_json_path(record, json_path)

            for extracted_value in extracted_values:
                if not extracted_value:
                    continue

                # Try to find a mapping for this value
                metpo_mapping = self.bacdive_metpo_mappings.get(extracted_value.strip(), None)
                if metpo_mapping:
                    # Use METPO term
                    node_id = metpo_mapping["curie"]
                    label = metpo_mapping["label"]
                    category_url = metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY)
                    predicate_biolink = metpo_mapping.get("predicate_biolink_equivalent", "")

                    # convert category URL to CURIE in nodes.tsv (KGX transform output)
                    if category_url:
                        category = uri_to_curie(category_url)
                    else:
                        category = "biolink:PhenotypicQuality"  # fallback default

                    # fallback: if no biolink equivalent use `biolink:has_phenotype`
                    if predicate_biolink:
                        predicate = uri_to_curie(predicate_biolink)
                    else:
                        predicate = HAS_PHENOTYPE_PREDICATE

                    # Write node
                    node_writer.writerow(
                        [node_id, category, label] + [None] * (len(self.node_header) - 3)
                    )

                    # Write edges for each organism
                    for organism_id in species_with_strains:
                        edge_writer.writerow(
                            [
                                organism_id,
                                predicate,
                                node_id,
                                HAS_PHENOTYPE,
                                BACDIVE_PREFIX + key,
                            ]
                        )

    def _build_keyword_map_from_record(self, record: dict, custom_curie_data: dict):
        """
        Build a keyword map for a specific BacDive record by extracting values from JSON paths.

        :param record: The BacDive record dictionary
        :param custom_curie_data: Custom CURIE data from YAML file
        :return: Dictionary mapping keywords to METPO information
        """
        # Start with the custom curie data (for non-METPO mappings)
        keyword_map = {
            second_level_key: nested_data
            for first_level_value in custom_curie_data.values()
            for second_level_key, nested_data in first_level_value.items()
        }

        # Add METPO mappings from bacdive_metpo_mappings
        for bacdive_label, mapping in self.bacdive_metpo_mappings.items():
            # use biolink_equivalent URL from METPO tree traversal or fallback to default
            category_url = mapping.get("inferred_category", "")
            predicate_biolink = mapping.get("predicate_biolink_equivalent", "")

            # Convert category URL to CURIE
            if category_url:
                category = uri_to_curie(category_url)
            else:
                category = "biolink:PhenotypicQuality"  # fallback default

            # fallback: if no biolink equivalent use `biolink:has_phenotype`
            if predicate_biolink:
                predicate = uri_to_curie(predicate_biolink)
            else:
                predicate = "biolink:has_phenotype"

            keyword_map[bacdive_label] = {
                "category": category,
                "predicate": predicate,
                "curie": mapping["curie"],
                "name": mapping["label"],
            }

        # Now traverse the tree to find nodes with JSON paths and extract values from this record
        for node in self.bacdive_metpo_tree.values():
            if node.bacdive_json_paths:
                # This node has JSON paths - extract values from the record
                for json_path in node.bacdive_json_paths:
                    extracted_values = self._extract_value_from_json_path(record, json_path)

                    # For each extracted value, find matching child nodes with that synonym
                    for value in extracted_values:
                        # Normalize the value for lookup
                        normalized_value = value.lower().replace(" ", "_").replace("-", "_")

                        # Check if this value matches any synonyms in child nodes
                        for child in node.children:
                            if value in child.synonyms:
                                # Found a match - add to keyword_map using normalized key
                                if normalized_value not in keyword_map:
                                    # Find the mapping by searching for a synonym that matches this value
                                    found_mapping = False
                                    for _syn, map_info in self.bacdive_metpo_mappings.items():
                                        if map_info["curie"] == child.iri:
                                            category_url = map_info.get("inferred_category", "")
                                            predicate_biolink = map_info.get(
                                                "predicate_biolink_equivalent", ""
                                            )

                                            # Convert category URL to CURIE
                                            if category_url:
                                                category = uri_to_curie(category_url)
                                            else:
                                                category = "biolink:PhenotypicQuality"

                                            predicate = (
                                                uri_to_curie(predicate_biolink)
                                                if predicate_biolink
                                                else "biolink:has_phenotype"
                                            )

                                            keyword_map[normalized_value] = {
                                                "category": category,
                                                "predicate": predicate,
                                                "curie": child.iri,
                                                "name": child.label,
                                            }
                                            found_mapping = True
                                            break

                                    # If not found in mappings, create a basic entry
                                    if not found_mapping and child.iri:
                                        keyword_map[normalized_value] = {
                                            "category": "biolink:PhenotypicQuality",
                                            "predicate": "biolink:has_phenotype",
                                            "curie": child.iri,
                                            "name": child.label,
                                        }

        return keyword_map

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

    def _get_isolation_edge(self, cat_dictionary):
        """Return the lowest level environment from categories."""
        # Replace keys with integers
        numbered_dict = {
            int(key.replace(BACDIVE_ENVIRONMENT_CATEGORY, "")): value
            for key, value in cat_dictionary.items()
        }
        # Get value with highest category integer
        val = numbered_dict[max(numbered_dict.keys())]

        return val

    def _get_cat_hierarchy(self, cat_dictionary):
        """Return the lowest level environment from categories."""
        edge_pairs = []

        # Replace keys with integers
        numbered_dict = {
            int(key.replace(BACDIVE_ENVIRONMENT_CATEGORY, "")): value
            for key, value in cat_dictionary.items()
        }
        # Sort keys in descending order
        sorted_keys = sorted(numbered_dict.keys(), reverse=True)
        for i in range(len(sorted_keys) - 1):
            key1 = sorted_keys[i]
            key2 = sorted_keys[i + 1]
            edge_pairs.append([numbered_dict[key1], numbered_dict[key2]])

        return edge_pairs

    def _process_antibiotic_resistance(self, item, ncbitaxon_id, key):
        chebi_key = CHEBI_PREFIX + str(item[CHEBI_KEY])
        METABOLITE_MAP[chebi_key] = (
            item[METABOLITE_KEY] if not METABOLITE_MAP.get(chebi_key) else METABOLITE_MAP[chebi_key]
        )

        if item.get(RESISTANCE_KEY) == "yes":
            antibiotic_predicate = NCBI_TO_METABOLITE_RESISTANCE_EDGE
        elif item.get(SENSITIVITY_KEY) == "yes":
            antibiotic_predicate = NCBI_TO_METABOLITE_SENSITIVITY_EDGE
        else:
            antibiotic_predicate = None

        if antibiotic_predicate:
            self.ar_nodes_data_to_write.append(
                [
                    chebi_key,
                    METABOLITE_CATEGORY,
                    item[METABOLITE_KEY],
                ]
                + [None] * (len(self.node_header) - 3)
            )
            self.ar_edges_data_to_write.append(
                [
                    ncbitaxon_id,
                    antibiotic_predicate,
                    chebi_key,
                    None,
                    BACDIVE_PREFIX + key,
                ]
            )

    def _process_metabolites(self, dictionary, ncbitaxon_id, key, node_writer, edge_writer):
        """
        Process a single antibiotic dictionary entry.

        Maps medium label -> node, and antibiotic name -> node, plus the appropriate edges.
        Includes debug print statements showing exactly which nodes and edges are written.
        Now uses numeric thresholds:
        * < 10 => NCBI_TO_METABOLITE_RESISTANCE_EDGE
        * > 30 => NCBI_TO_METABOLITE_SENSITIVITY_EDGE.
        """

        def parse_numeric_value(value_str: str) -> float:
            """
            Parse the antibiotic value string and return a single float.

            Handles strings like "30", "42-44", ">50". For ranges, returns the mean.
            For '>50', parses as 50. If parsing fails, returns None.
            """
            value_str = value_str.strip()
            if not value_str:
                return None
            # Case: range "42-44"
            if "-" in value_str and not value_str.startswith(">"):
                try:
                    lo, hi = value_str.split("-")
                    return (float(lo) + float(hi)) / 2
                except ValueError:
                    return None
            # Case: strictly ">" notation, e.g. ">50"
            if value_str.startswith(">"):
                # parse remainder
                try:
                    val = float(value_str[1:])
                    return val  # If you want to treat >50 as "50" or "50.1" is up to you
                except ValueError:
                    return None
            # Case: single numeric "30"
            try:
                return float(value_str)
            except ValueError:
                return None

        # print(f"\n--- DEBUG: Entering _process_metabolites ---")
        # print(f"Dictionary contents:\n{dictionary}\n")

        # 1) Handle 'medium' label
        medium_label = dictionary.get(MEDIUM_KEY)
        if medium_label:
            medium_id = (
                MEDIADIVE_MEDIUM_PREFIX + medium_label.replace(" ", "_").replace("-", "_").lower()
            )
            #    print(f"--> Found medium_label: '{medium_label}' => medium_id: '{medium_id}'")
            node_row = [
                medium_id,
                METABOLITE_CATEGORY,
                medium_label,
            ] + [
                None
            ] * (len(self.node_header) - 3)
            # print(f"    Writing node row for MEDIADIVE_MEDIUM_PREFIX{node_row}")
            node_writer.writerow(node_row)
        # else:
        #    print("--> No medium label found in this dictionary.")

        # 2) Map items in 'dictionary' to METABOLITE_MAP
        #    (K = antibiotic key, V = numeric/range/'>' string, e.g. "30-32")
        metabolites_with_curies = {
            k: v for k, v in dictionary.items() if k in METABOLITE_MAP.values()
        }
        if metabolites_with_curies:
            #    print(f"--> Found {len(metabolites_with_curies)} items that match METABOLITE_MAP.values():")
            for k, v in metabolites_with_curies.items():
                #        print(f"    {k} => {v}")
                numeric_val = parse_numeric_value(v)
                #        print(f"    numeric_val = {numeric_val}")

                # Determine whether it indicates resistance (<10) or sensitivity (>30)
                if numeric_val is not None and numeric_val < 15:
                    antibiotic_predicate = NCBI_TO_METABOLITE_RESISTANCE_EDGE
                elif numeric_val is not None and numeric_val > 25:
                    antibiotic_predicate = NCBI_TO_METABOLITE_SENSITIVITY_EDGE
                else:
                    # No edge if between 10 and 30 (inclusive)
                    antibiotic_predicate = None

                # Reverse lookup: which METABOLITE_MAP key gave us K?
                metabolite_id = [key_ for key_, value_ in METABOLITE_MAP.items() if value_ == k][0]
                #        print(f"    antibiotic_predicate = {antibiotic_predicate}")
                #        print(f"    metabolite_id = {metabolite_id}")

                # If there's a valid predicate and ID, write node & edge
                if antibiotic_predicate and metabolite_id:
                    node_row = [
                        metabolite_id,
                        METABOLITE_CATEGORY,
                        k,
                    ] + [
                        None
                    ] * (len(self.node_header) - 3)
                    #            print(f"    Writing node row for antibiotic: {node_row}")
                    node_writer.writerow(node_row)

                    edge_row = [
                        ncbitaxon_id,
                        antibiotic_predicate,
                        metabolite_id,
                        None,
                        BACDIVE_PREFIX + key,
                    ]
                    #            print(f"    Writing edge row for antibiotic: {edge_row}")
                    edge_writer.writerows([edge_row])
        #        else:
        #            print("    ==> No edge created (value in [10..30] range or parse failed).")
        # else:
        #    print("--> No matching antibiotics found in METABOLITE_MAP for this dictionary.")

        # print("--- DEBUG: Exiting _process_metabolites ---\n")

    def _process_medium(self, dictionary, ncbitaxon_id, key, edge_writer):
        medium_label = dictionary.get(MEDIUM_KEY)
        if medium_label:
            medium_id = (
                MEDIADIVE_MEDIUM_PREFIX + medium_label.replace(" ", "_").replace("-", "_").lower()
            )
            edge_writer.writerow(
                [
                    ncbitaxon_id,
                    NCBI_TO_MEDIUM_EDGE,
                    medium_id,
                    IS_GROWN_IN,
                    BACDIVE_PREFIX + key,
                ]
            )

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        # replace with downloaded data filename for this source
        input_file = os.path.join(self.input_base_dir, "bacdive_strains.json")  # must exist already
        # Read the JSON file into the variable input_json
        with open(input_file, "r") as f:
            input_json = json.load(f)

        # Detect format and convert to consistent format
        # Old format: dict with string keys, New format: list of dicts
        if isinstance(input_json, dict):
            # Old format: convert dict values to list
            input_json = list(input_json.values())
        elif isinstance(input_json, list):
            # New format: already a list, use as-is
            pass
        else:
            raise ValueError(f"Unexpected JSON format: expected dict or list, got {type(input_json)}")

        translation_table_for_ids = str.maketrans(TRANSLATION_TABLE_FOR_IDS)
        translation_table_for_labels = str.maketrans(TRANSLATION_TABLE_FOR_LABELS)

        # Track non-matching media links
        non_matching_media_links = set()

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
                            EC_CATEGORY,
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

            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(total=len(input_json) + 1, desc="Processing files") as progress:
                for index, value in enumerate(input_json):
                    # Build keyword_map for this specific record using JSON paths
                    keyword_map = self._build_keyword_map_from_record(value, custom_curie_data)
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

                    # Extract BacDive-ID from the new format, fallback to index if not found
                    bacdive_id = general_info.get("BacDive-ID", index)
                    key = str(bacdive_id)

                    dsm_number = general_info.get(DSM_NUMBER)
                    external_links = value.get(EXTERNAL_LINKS, {})
                    culture_number_from_external_links = None
                    isolation = value.get(ISOLATION_SAMPLING_ENV_INFO, {}).get(ISOLATION)
                    isolation_source_categories = value.get(ISOLATION_SAMPLING_ENV_INFO, {}).get(
                        ISOLATION_SOURCE_CATEGORIES, []
                    )

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
                        culture_number_translation_table = str.maketrans("", "", '()"')
                        culture_number_from_external_links = [
                            culture_number.translate(culture_number_translation_table)
                            .replace('""', "")
                            .strip()
                            for culture_number in culture_number_from_external_links
                        ]

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
                    species_with_strains = []

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
                        species_with_strains = [ncbitaxon_id]
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
                    medium_ids = []
                    medium_labels = []
                    medium_urls = []
                    mediadive_urls = []

                    if (
                        CULTURE_AND_GROWTH_CONDITIONS in value
                        and value[CULTURE_AND_GROWTH_CONDITIONS]
                    ):
                        if (
                            CULTURE_MEDIUM in value[CULTURE_AND_GROWTH_CONDITIONS]
                            and value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM]
                        ):
                            media = value[CULTURE_AND_GROWTH_CONDITIONS][CULTURE_MEDIUM]

                            if not isinstance(media, list):
                                media = [media]

                            for medium in media:
                                if CULTURE_LINK in medium and medium[CULTURE_LINK]:
                                    medium_url = str(medium[CULTURE_LINK])

                                    # Skip URLs that are just "None" as string
                                    if medium_url == "None":
                                        continue

                                    medium_id_list = [
                                        medium_url.replace(val, key)
                                        for key, val in BACDIVE_MEDIUM_DICT.items()
                                        if medium_url.startswith(val)
                                    ]

                                    # Handle DSMZ PDF URLs: https://www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium*.pdf
                                    # introducing variable below to resolve E501 (defaulting on line length limit)
                                    dsmz_medium_pattern = (
                                        "www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium"
                                    )
                                    if not medium_id_list and dsmz_medium_pattern in medium_url:
                                        match = re.search(r"DSMZ_Medium(\d+)\.pdf", medium_url)
                                        if match:
                                            medium_number = match.group(1)
                                            medium_id_list = [
                                                f"{MEDIADIVE_MEDIUM_PREFIX}{medium_number}"
                                            ]
                                    # Track non-matching URLs
                                    if not medium_id_list:
                                        non_matching_media_links.add(medium_url)
                                        continue

                                    medium_label = medium.get(CULTURE_NAME, None)
                                    mediadive_url = medium_url.replace(
                                        BACDIVE_API_BASE_URL, MEDIADIVE_REST_API_BASE_URL
                                    )

                                    # Store each medium's details in lists
                                    medium_ids.extend(medium_id_list)
                                    medium_labels.append(
                                        remove_nextlines(medium_label).translate(
                                            translation_table_for_labels
                                        )
                                    )
                                    medium_urls.append(medium_url)
                                    mediadive_urls.append(mediadive_url)

                            for mid, mlabel, murl, mdurl in zip(
                                medium_ids, medium_labels, medium_urls, mediadive_urls, strict=False
                            ):
                                data = [
                                    BACDIVE_PREFIX + key,
                                    dsm_number,
                                    culture_number_from_external_links,
                                    ncbitaxon_id,
                                    ncbi_description,
                                    str(keywords),
                                    mid,
                                    mlabel,
                                    murl,
                                    mdurl,
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
                    synonyms = lpsn.get(SYNONYMS, {}) if lpsn and SYNONYMS in lpsn else None
                    if isinstance(synonyms, list):
                        synonym_parsed = " | ".join(
                            synonym.get(SYNONYM, {}) for synonym in synonyms
                        )
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

                    # Biosafety level - using METPO mappings
                    # Parent: METPO:1001101 (biosafety level)
                    # Path: "Safety information.risk assessment.biosafety level"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1001101", species_with_strains, key, node_writer, edge_writer
                    )

                    if not all(item is None for item in name_tax_classification_data[2:]):
                        writer_3.writerow(name_tax_classification_data)

                    #! Strains of NCBITaxon species
                    if (
                        name_tax_classification
                        and name_tax_classification.get(TYPE_STRAIN) == "yes"
                    ):
                        if "," in name_tax_classification.get(STRAIN_DESIGNATION, ""):
                            strain_designations = name_tax_classification.get(
                                STRAIN_DESIGNATION
                            ).split(", ")
                            curated_strain_ids = [
                                strain_designation.strip().translate(translation_table_for_ids)
                                for strain_designation in strain_designations
                            ]
                        elif name_tax_classification.get(STRAIN_DESIGNATION):
                            curated_strain_ids = [
                                name_tax_classification.get(STRAIN_DESIGNATION)
                                .strip()
                                .translate(translation_table_for_ids)
                            ]

                        else:
                            # curated_strain_id_suffix = BACDIVE_PREFIX.replace(":", "_") + key
                            # if ncbitaxon_id:
                            #     curated_strain_id_suffix = ncbitaxon_id.replace(":", "_")
                            # else:
                            #     curated_strain_id_suffix = "NO_NCBITaxon_ID"

                            # ! As per Marcin, strain designation will be in label only.
                            curated_strain_ids = (
                                [
                                    name_tax_classification.get(STRAIN_DESIGNATION)
                                    .strip()
                                    .translate(translation_table_for_ids)
                                ]
                                if name_tax_classification.get(STRAIN_DESIGNATION)
                                else []
                            )

                        # curated_strain_ids = [
                        #     STRAIN_PREFIX
                        #     + curated_strain_id
                        #     + (
                        #         # "_of_" + ncbitaxon_id.replace(":", "_")
                        #         BACDIVE_PREFIX.replace(":", "_") + key
                        #         if str(curated_strain_id).isnumeric()
                        #         else ""
                        #     )
                        #     for curated_strain_id in curated_strain_ids
                        # ]

                        # Use just 1st strain as per Marcin.
                        # species_with_strains.extend([curated_strain_ids[0]])
                        curated_strain_id = STRAIN_PREFIX + BACDIVE_PREFIX.replace(":", "_") + key
                        species_with_strains.extend([curated_strain_id])
                        if len(curated_strain_ids) > 0:
                            prefix = BACDIVE_PREFIX.replace(":", "_")
                            strain_id = curated_strain_ids[0]
                            curated_strain_label = (
                                f"{prefix + key} as {strain_id} of {ncbitaxon_id}"
                            )

                        else:
                            curated_strain_label = (
                                f"{BACDIVE_PREFIX.replace(':', '_') + key} of {ncbitaxon_id}"
                            )

                        # curated_strain_label = name_tax_classification.get(
                        #     FULL_SCIENTIFIC_NAME, f"strain_of {ncbi_label}"
                        # )
                        # curated_strain_label = process_and_decode_label(curated_strain_label)

                        # ! Synonyms are specific to species and not the strain.
                        # if synonym_parsed is None:
                        node_writer.writerow(
                            [
                                curated_strain_id,
                                NCBI_CATEGORY,
                                curated_strain_label,
                            ]
                            + [None] * (len(self.node_header) - 3)
                            # for curated_strain_id in curated_strain_ids
                            # if curated_strain_id
                        )
                        # else:
                        #     node_writer.writerows(
                        #         [
                        #             curated_strain_id,
                        #             NCBI_CATEGORY,
                        #             curated_strain_label,
                        #         ]
                        #         + [None] * 3
                        #         + [synonym_parsed]
                        #         + [None] * (len(self.node_header) - 7)
                        #         for curated_strain_id in curated_strain_ids
                        #         if curated_strain_id
                        #     )
                        if ncbitaxon_id and curated_strain_id:
                            edge_writer.writerow(
                                [
                                    curated_strain_id,
                                    SUBCLASS_PREDICATE,
                                    ncbitaxon_id,
                                    RDFS_SUBCLASS_OF,
                                    BACDIVE_PREFIX + key,
                                ]
                                # for curated_strain_id in curated_strain_ids
                                # if curated_strain_id
                            )
                        # Equivalencies in strain IDs established as edges
                        # if len(curated_strain_ids) > 1:
                        #     for i in range(len(curated_strain_ids)):
                        #         for j in range(i + 1, len(curated_strain_ids)):
                        #             edge_writer.writerows(
                        #                 [
                        #                     [
                        #                         curated_strain_ids[i],
                        #                         SAME_AS_PREDICATE,
                        #                         curated_strain_ids[j],
                        #                         EXACT_MATCH,
                        #                         BACDIVE_PREFIX + key,
                        #                     ],
                        #                     [
                        #                         curated_strain_ids[i],
                        #                         SAME_AS_PREDICATE,
                        #                         BACDIVE_PREFIX + key,
                        #                         EXACT_MATCH,
                        #                         BACDIVE_PREFIX + key,
                        #                     ],
                        #                     [
                        #                         curated_strain_ids[j],
                        #                         SAME_AS_PREDICATE,
                        #                         BACDIVE_PREFIX + key,
                        #                         EXACT_MATCH,
                        #                         BACDIVE_PREFIX + key,
                        #                     ],
                        #                 ]
                        #             )
                    # ! ----------------------------

                    if ncbitaxon_id and medium_ids:
                        for mid, mlabel in zip(medium_ids, medium_labels, strict=False):
                            # Combine list creation and extension for nodes
                            nodes_data_to_write = [
                                [ncbitaxon_id, NCBI_CATEGORY, ncbi_label],
                                [mid, MEDIUM_CATEGORY, mlabel],
                            ]
                            nodes_data_to_write = [
                                sublist + [None] * (len(self.node_header) - 3)
                                for sublist in nodes_data_to_write
                            ]
                            node_writer.writerows(nodes_data_to_write)

                            # Combine list creation and extension for edges
                            edges_data_to_write = [
                                [
                                    organism,
                                    NCBI_TO_MEDIUM_EDGE,
                                    mid,
                                    IS_GROWN_IN,
                                    BACDIVE_PREFIX + key,
                                ]
                                for organism in species_with_strains
                            ]

                            edge_writer.writerows(edges_data_to_write)

                    if ncbitaxon_id and nodes_from_keywords:
                        # Convert to manual CHEBI ID for keywords
                        nodes_data_to_write = [
                            [
                                next(
                                    (
                                        key
                                        for key, val in METABOLITE_MAP.items()
                                        if val == value[CURIE_COLUMN].split(":")[1]
                                    ),
                                    value[CURIE_COLUMN],
                                ),
                                value[CATEGORY_COLUMN],
                                value[NAME_COLUMN],
                            ]
                            for _, value in nodes_from_keywords.items()
                        ]
                        nodes_data_to_write.append([ncbitaxon_id, NCBI_CATEGORY, ncbi_label])
                        nodes_data_to_write = [
                            sublist + [None] * (len(self.node_header) - 3)
                            for sublist in nodes_data_to_write
                        ]

                        node_writer.writerows(nodes_data_to_write)

                        for _, value in nodes_from_keywords.items():
                            # Convert to manual CHEBI ID for keywords
                            edges_data_to_write = [
                                [
                                    organism,
                                    value[PREDICATE_COLUMN],
                                    next(
                                        (
                                            key
                                            for key, val in METABOLITE_MAP.items()
                                            if val == value[CURIE_COLUMN].split(":")[1]
                                        ),
                                        value[CURIE_COLUMN],
                                    ),
                                    (
                                        HAS_PHENOTYPE
                                        if value[CATEGORY_COLUMN]
                                        in [PHENOTYPIC_CATEGORY, ATTRIBUTE_CATEGORY]
                                        else BIOLOGICAL_PROCESS
                                    ),
                                    BACDIVE_PREFIX + key,
                                ]
                                for organism in species_with_strains
                            ]

                            edge_writer.writerows(edges_data_to_write)

                    if ncbitaxon_id and culture_number_from_external_links:
                        for culture_number in culture_number_from_external_links:
                            culture_number_cleaned = culture_number.strip().replace(" ", "-")
                            strain_curie = (
                                STRAIN_PREFIX + culture_number_cleaned
                                if len(culture_number_cleaned) > 3
                                else None
                            )
                            strain_label = (
                                culture_number.strip() if len(culture_number_cleaned) > 3 else None
                            )
                            if strain_curie and strain_label:
                                node_writer.writerow(
                                    [strain_curie, NCBI_CATEGORY, strain_label]
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
                        # Normalize to list
                        enzyme_list = []
                        if isinstance(phys_and_metabolism_enzymes, list):
                            enzyme_list = phys_and_metabolism_enzymes
                        elif isinstance(phys_and_metabolism_enzymes, dict):
                            enzyme_list = [phys_and_metabolism_enzymes]
                        else:
                            print(f"{phys_and_metabolism_enzymes} data not recorded.")

                        # Process each enzyme entry
                        enzyme_data = []
                        for enzyme in enzyme_list:
                            if not isinstance(enzyme, dict):
                                continue

                            activity = enzyme.get(ACTIVITY_KEY)
                            ec_number = enzyme.get(EC_KEY)
                            value = enzyme.get("value")

                            # Only process if we have an EC number and activity mapping
                            if not ec_number or activity not in self.metpo_enzyme_mappings:
                                continue

                            # Get METPO predicate from mapping
                            metpo_predicate = self.metpo_enzyme_mappings[activity]["curie"]

                            enzyme_data.append(
                                {
                                    "ec_id": f"{EC_PREFIX}{ec_number}",
                                    "label": value,
                                    "predicate": metpo_predicate,
                                }
                            )

                        if enzyme_data:
                            # Write enzyme nodes (EC terms)
                            enzyme_nodes_to_write = [
                                [item["ec_id"], EC_CATEGORY, item["label"]]
                                + [None] * (len(self.node_header) - 3)
                                for item in enzyme_data
                            ]
                            node_writer.writerows(enzyme_nodes_to_write)

                            # Write edges from organisms to enzymes using METPO predicates
                            for item in enzyme_data:
                                enzyme_edges_to_write = [
                                    [
                                        organism,
                                        item["predicate"],
                                        item["ec_id"],
                                        CAPABLE_OF,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    for organism in species_with_strains
                                ]
                                edge_writer.writerows(enzyme_edges_to_write)

                    if phys_and_metabolism_metabolite_utilization:
                        metabolite_activity_data = None
                        if isinstance(phys_and_metabolism_metabolite_utilization, list):
                            metabolite_activity_data = []
                            for metabolite in phys_and_metabolism_metabolite_utilization:
                                # Process metabolites that have CHEBI ID
                                if METABOLITE_CHEBI_KEY in metabolite:
                                    chebi_key = f"{CHEBI_PREFIX}{metabolite[METABOLITE_CHEBI_KEY]}"
                                    utilization_type = metabolite.get(UTILIZATION_TYPE_TESTED)
                                    utilization_activity = metabolite.get(UTILIZATION_ACTIVITY)

                                    # Look up METPO predicate based on utilization type and sign
                                    metpo_predicate = None
                                    metpo_label = None
                                    if utilization_type and utilization_activity:
                                        mapping = self.metpo_metabolite_utilization_mappings.get(
                                            utilization_type
                                        )
                                        if mapping and utilization_activity in mapping:
                                            metpo_predicate = mapping[utilization_activity]["curie"]
                                            metpo_label = mapping[utilization_activity]["label"]

                                    # Only add if we found a METPO predicate mapping
                                    if metpo_predicate:
                                        metabolite_activity_data.append(
                                            {
                                                "chebi_key": chebi_key,
                                                "metabolite_name": metabolite[METABOLITE_KEY],
                                                "utilization_type": utilization_type,
                                                "metpo_predicate": metpo_predicate,
                                                "metpo_label": metpo_label,
                                            }
                                        )

                        elif isinstance(phys_and_metabolism_metabolite_utilization, dict):
                            utilization_activity = phys_and_metabolism_metabolite_utilization.get(
                                UTILIZATION_ACTIVITY
                            )
                            utilization_type = phys_and_metabolism_metabolite_utilization.get(
                                UTILIZATION_TYPE_TESTED
                            )
                            if phys_and_metabolism_metabolite_utilization.get(METABOLITE_CHEBI_KEY):
                                chebi_key = (
                                    f"{CHEBI_PREFIX}"
                                    f"{phys_and_metabolism_metabolite_utilization.get(METABOLITE_CHEBI_KEY)}"
                                )
                                metabolite_value = phys_and_metabolism_metabolite_utilization.get(
                                    METABOLITE_KEY
                                )

                                # Look up METPO predicate
                                metpo_predicate = None
                                metpo_label = None
                                if utilization_type and utilization_activity:
                                    mapping = self.metpo_metabolite_utilization_mappings.get(
                                        utilization_type
                                    )
                                    if mapping and utilization_activity in mapping:
                                        metpo_predicate = mapping[utilization_activity]["curie"]
                                        metpo_label = mapping[utilization_activity]["label"]

                                if metpo_predicate:
                                    metabolite_activity_data = [
                                        {
                                            "chebi_key": chebi_key,
                                            "metabolite_name": metabolite_value,
                                            "utilization_type": utilization_type,
                                            "metpo_predicate": metpo_predicate,
                                            "metpo_label": metpo_label,
                                        }
                                    ]
                        else:
                            print(
                                f"{phys_and_metabolism_metabolite_utilization} data not recorded."
                            )

                        if metabolite_activity_data:
                            # Write metabolite nodes
                            meta_util_nodes_to_write = [
                                [item["chebi_key"], METABOLITE_CATEGORY, item["metabolite_name"]]
                                + [None] * (len(self.node_header) - 3)
                                for item in metabolite_activity_data
                            ]
                            node_writer.writerows(meta_util_nodes_to_write)

                            # Write edges with METPO predicates
                            for item in metabolite_activity_data:
                                meta_util_edges_to_write = [
                                    [
                                        organism,
                                        item["metpo_predicate"],
                                        item["chebi_key"],
                                        HAS_PARTICIPANT,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    for organism in species_with_strains
                                ]
                                edge_writer.writerows(meta_util_edges_to_write)

                    if phys_and_metabolism_metabolite_production:
                        metabolite_production_data = None
                        if isinstance(phys_and_metabolism_metabolite_production, list):
                            metabolite_production_data = []
                            for metabolite in phys_and_metabolism_metabolite_production:
                                # Process metabolites that have CHEBI ID
                                if METABOLITE_CHEBI_KEY in metabolite:
                                    chebi_key = f"{CHEBI_PREFIX}{metabolite[METABOLITE_CHEBI_KEY]}"
                                    production = metabolite.get(PRODUCTION_KEY)

                                    # Look up METPO predicate directly using production value (yes/no)
                                    metpo_predicate = None
                                    metpo_label = None
                                    if production and production in self.metpo_metabolite_production_mappings:
                                        metpo_predicate = self.metpo_metabolite_production_mappings[
                                            production
                                        ]["curie"]
                                        metpo_label = self.metpo_metabolite_production_mappings[production][
                                            "label"
                                        ]

                                    # Only add if we found a METPO predicate mapping
                                    if metpo_predicate:
                                        metabolite_production_data.append(
                                            {
                                                "chebi_key": chebi_key,
                                                "metabolite_name": metabolite[METABOLITE_KEY],
                                                "production": production,
                                                "metpo_predicate": metpo_predicate,
                                                "metpo_label": metpo_label,
                                            }
                                        )

                        elif isinstance(phys_and_metabolism_metabolite_production, dict):
                            production = phys_and_metabolism_metabolite_production.get(PRODUCTION_KEY)
                            if phys_and_metabolism_metabolite_production.get(METABOLITE_CHEBI_KEY):
                                chebi_key = (
                                    f"{CHEBI_PREFIX}"
                                    f"{phys_and_metabolism_metabolite_production.get(METABOLITE_CHEBI_KEY)}"
                                )
                                metabolite_value = phys_and_metabolism_metabolite_production.get(
                                    METABOLITE_KEY
                                )

                                # Look up METPO predicate directly using production value (yes/no)
                                metpo_predicate = None
                                metpo_label = None
                                if production and production in self.metpo_metabolite_production_mappings:
                                    metpo_predicate = self.metpo_metabolite_production_mappings[production][
                                        "curie"
                                    ]
                                    metpo_label = self.metpo_metabolite_production_mappings[production]["label"]

                                if metpo_predicate:
                                    metabolite_production_data = [
                                        {
                                            "chebi_key": chebi_key,
                                            "metabolite_name": metabolite_value,
                                            "production": production,
                                            "metpo_predicate": metpo_predicate,
                                            "metpo_label": metpo_label,
                                        }
                                    ]
                        else:
                            print(f"{phys_and_metabolism_metabolite_production} data not recorded.")

                        if metabolite_production_data:
                            # Write metabolite nodes
                            metabolite_production_nodes_to_write = [
                                [item["chebi_key"], METABOLITE_CATEGORY, item["metabolite_name"]]
                                + [None] * (len(self.node_header) - 3)
                                for item in metabolite_production_data
                            ]
                            node_writer.writerows(metabolite_production_nodes_to_write)

                            # Write edges with METPO predicates
                            for item in metabolite_production_data:
                                metabolite_production_edges_to_write = [
                                    [
                                        organism,
                                        item["metpo_predicate"],
                                        item["chebi_key"],
                                        BIOLOGICAL_PROCESS,
                                        BACDIVE_PREFIX + key,
                                    ]
                                    for organism in species_with_strains
                                ]
                                edge_writer.writerows(metabolite_production_edges_to_write)

                    # Process oxygen tolerance using path-based extraction from METPO tree
                    # Parent: METPO:1000601 (oxygen preference)
                    # Path: "Physiology and metabolism.oxygen tolerance.oxygen tolerance"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000601", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process spore formation using path-based extraction from METPO tree
                    # Parent: METPO:1000870 (sporulation)
                    # Path: "Physiology and metabolism.spore formation.spore formation"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000870", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process nutrition type using path-based extraction from METPO tree
                    # Parent: METPO:1000631 (trophic type)
                    # Path: "Physiology and metabolism.nutrition type.type"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000631", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process cell shape using path-based extraction from METPO tree
                    # Parent: METPO:1000666 (cell shape)
                    # Path: "Morphology.cell morphology.cell shape"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000666", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process gram stain using path-based extraction from METPO tree
                    # Parent: METPO:1000697 (gram stain)
                    # Path: "Morphology.cell morphology.gram stain"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000697", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process motility using path-based extraction from METPO tree
                    # Parent: METPO:1000701 (motility)
                    # Path: "Morphology.cell morphology.motility"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000701", species_with_strains, key, node_writer, edge_writer
                    )

                    # Process halophily preference using path-based extraction from METPO tree
                    # Parent: METPO:1000629 (halophily preference)
                    # Paths: "Physiology and metabolism.halophily.halophily level"
                    self._process_phenotype_by_metpo_parent(
                        value, "METPO:1000629", species_with_strains, key, node_writer, edge_writer
                    )

                    if phys_and_metabolism_API:
                        # Process each API key separately (e.g. "API zym", "API coryne", etc.)
                        for assay_name, assay_data in phys_and_metabolism_API.items():
                            # Normalize the assay name for lookup (e.g. "API zym" -> "api zym")
                            # We are doing this because the keys in self.assay_kit_mappings dictionary
                            # are all lowercase
                            assay_name_lower = assay_name.lower()

                            # Check if we have mapping data for this kit
                            if assay_name_lower not in self.assay_kit_mappings:
                                # Skip unmapped API kits
                                continue

                            # Use the new assay kit mappings
                            kit_mappings = self.assay_kit_mappings[assay_name_lower]
                            values = self._flatten_to_dicts(assay_data)

                            # Process each well/test result
                            for entry in values:
                                if not isinstance(entry, dict):
                                    continue

                                for test_label, test_result in entry.items():
                                    # Skip if not in the mapping or if no result
                                    if test_label not in kit_mappings:
                                        continue

                                    # Get the mapping info for this test
                                    test_info = kit_mappings[test_label]
                                    test_type = test_info["type"]

                                    # Only process enzyme types for now
                                    # TODO: Add substrate handling once METPO properties are defined
                                    if test_type == "enzyme":
                                        # Use METPO enzyme activity mapping
                                        if test_result not in self.metpo_enzyme_mappings:
                                            continue

                                        metpo_predicate_info = self.metpo_enzyme_mappings[test_result]
                                        metpo_predicate = metpo_predicate_info["curie"]

                                        # Create edges for both GO terms and EC numbers
                                        go_terms = test_info.get("go_terms", [])
                                        ec_numbers = test_info.get("ec_number", [])

                                        # Process GO terms
                                        if go_terms:
                                            for go_term in go_terms:
                                                # Write GO term node
                                                node_writer.writerow(
                                                    [go_term, "biolink:MolecularActivity", test_label]
                                                    + [None] * (len(self.node_header) - 3)
                                                )

                                                # Write edges from organisms to GO term
                                                for organism in species_with_strains:
                                                    edge_writer.writerow(
                                                        [
                                                            organism,
                                                            metpo_predicate,
                                                            go_term,
                                                            CAPABLE_OF,
                                                            BACDIVE_PREFIX + key,
                                                        ]
                                                    )

                                        # Process EC numbers
                                        if ec_numbers:
                                            for ec_number in ec_numbers:
                                                ec_id = f"{EC_PREFIX}{ec_number}"
                                                # Write EC number node
                                                node_writer.writerow(
                                                    [ec_id, EC_CATEGORY, test_label]
                                                    + [None] * (len(self.node_header) - 3)
                                                )

                                                # Write edges from organisms to EC number
                                                for organism in species_with_strains:
                                                    edge_writer.writerow(
                                                        [
                                                            organism,
                                                            metpo_predicate,
                                                            ec_id,
                                                            CAPABLE_OF,
                                                            BACDIVE_PREFIX + key,
                                                        ]
                                                    )

                                        # Skip if neither GO terms nor EC numbers are available
                                        if not go_terms and not ec_numbers:
                                            continue

                    # REPLACEMENT: simple approach — each Cat1, Cat2, Cat3 becomes a node + edge to organism

                    all_values = []

                    if isinstance(isolation_source_categories, list):
                        for category in isolation_source_categories:
                            # collect all Cat1, Cat2, Cat3, etc.
                            all_values.extend(category.values())
                    elif isinstance(isolation_source_categories, dict):
                        all_values.extend(isolation_source_categories.values())

                    # Normalize strings (strip + translate)
                    all_values = [
                        val.strip().translate(translation_table_for_ids) for val in all_values
                    ]

                    # Create a node and an edge to the organism for each isolation source
                    for isol_source in all_values:
                        # Write an isolation source node
                        node_writer.writerow(
                            [
                                ISOLATION_SOURCE_PREFIX + isol_source.lower(),
                                ISOLATION_SOURCE_CATEGORY,
                                isol_source,
                            ]
                            + [None] * (len(self.node_header) - 3)
                        )
                        # Write an edge from the isolation source to each organism
                        edge_writer.writerows(
                            [
                                [
                                    ISOLATION_SOURCE_PREFIX + isol_source.lower(),
                                    NCBI_TO_ISOLATION_SOURCE_EDGE,
                                    organism,
                                    LOCATION_OF,
                                    self.source_name,
                                ]
                                for organism in species_with_strains
                            ]
                        )

                    if (
                        ncbitaxon_id
                        and phys_and_metabolism_antibiotic_resistance
                        and len(phys_and_metabolism_antibiotic_resistance) > 0
                    ):
                        self.ar_nodes_data_to_write = []
                        self.ar_edges_data_to_write = []

                        if isinstance(phys_and_metabolism_antibiotic_resistance, list):
                            for item in phys_and_metabolism_antibiotic_resistance:
                                if item.get(CHEBI_KEY):
                                    self._process_antibiotic_resistance(item, ncbitaxon_id, key)
                        elif isinstance(phys_and_metabolism_antibiotic_resistance, dict):
                            if phys_and_metabolism_antibiotic_resistance.get(CHEBI_KEY):
                                self._process_antibiotic_resistance(
                                    phys_and_metabolism_antibiotic_resistance, ncbitaxon_id, key
                                )

                        if self.ar_edges_data_to_write and self.ar_nodes_data_to_write:
                            node_writer.writerows(self.ar_nodes_data_to_write)
                            edge_writer.writerows(self.ar_edges_data_to_write)

                    if (
                        ncbitaxon_id
                        and phys_and_metabolism_antibiogram
                        and len(phys_and_metabolism_antibiogram) > 0
                    ):
                        if isinstance(phys_and_metabolism_antibiogram, list):
                            for dictionary in phys_and_metabolism_antibiogram:
                                self._process_metabolites(
                                    dictionary, ncbitaxon_id, key, node_writer, edge_writer
                                )
                                self._process_medium(dictionary, ncbitaxon_id, key, edge_writer)
                        elif isinstance(phys_and_metabolism_antibiogram, dict):
                            self._process_metabolites(
                                phys_and_metabolism_antibiogram,
                                ncbitaxon_id,
                                key,
                                node_writer,
                                edge_writer,
                            )
                            self._process_medium(
                                phys_and_metabolism_antibiogram, ncbitaxon_id, key, edge_writer
                            )

                    progress.set_description(f"Processing BacDive file: {str(index)}.yaml")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()
                # Write metabolite_map to a file
                if len(METABOLITE_MAP) > 0 and not Path(METABOLITE_MAPPING_FILE).is_file():
                    with open(METABOLITE_MAPPING_FILE, "w") as f:
                        json.dump(METABOLITE_MAP, f, indent=4)

        # Write non-matching media links to a file
        media_links_file = os.path.join(self.output_dir, "bacdive_media_links.txt")
        with open(media_links_file, "w") as f:
            f.write("# Non-matching media links found in BacDive data\n")
            f.write(f"# Total unique non-matching links: {len(non_matching_media_links)}\n")
            f.write("# These links do not match the https://mediadive.dsmz.de/medium/ pattern\n\n")
            for link in sorted(non_matching_media_links):
                f.write(f"{link}\n")

        drop_duplicates(self.output_node_file, consolidation_columns=[ID_COLUMN, NAME_COLUMN])
        drop_duplicates(self.output_edge_file, consolidation_columns=[OBJECT_ID_COLUMN])
