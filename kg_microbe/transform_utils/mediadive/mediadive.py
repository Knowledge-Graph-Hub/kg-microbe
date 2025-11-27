"""
MediaDive KG.

Example script to transform downloaded data into a graph format that KGX can ingest directly,
in either TSV or JSON format:
https://github.com/NCATS-Tangerine/kgx/blob/master/data-preparation.md

Input: any file in data/raw/ (that was downloaded by placing a URL in incoming.txt/yaml
and running `run.py download`.

Output: transformed data in data/raw/MediaDive:

Output these two files:
- nodes.tsv
- edges.tsv
"""

import csv
import json
import math
import os
from pathlib import Path
from typing import Dict, Optional, Union
from urllib.parse import urlparse

import pandas as pd
import requests
import requests_cache
import yaml
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    AMOUNT_COLUMN,
    BACDIVE_ID_COLUMN,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    CAS_RN_KEY,
    CAS_RN_PREFIX,
    CHEBI_KEY,
    CHEBI_PREFIX,
    CHEBI_SOURCE,
    CHEBI_TO_ROLE_EDGE,
    COMPOUND,
    COMPOUND_ID_KEY,
    COMPOUND_KEY,
    DATA_KEY,
    GRAMS_PER_LITER_COLUMN,
    HAS_PART,
    HAS_ROLE,
    ID_COLUMN,
    INGREDIENT_CATEGORY,
    INGREDIENTS_COLUMN,
    IS_GROWN_IN,
    KEGG_KEY,
    KEGG_PREFIX,
    MEDIADIVE,
    MEDIADIVE_COMPLEX_MEDIUM_COLUMN,
    MEDIADIVE_DESC_COLUMN,
    MEDIADIVE_ID_COLUMN,
    MEDIADIVE_INGREDIENT_PREFIX,
    MEDIADIVE_LINK_COLUMN,
    MEDIADIVE_MAX_PH_COLUMN,
    MEDIADIVE_MEDIUM_PREFIX,
    MEDIADIVE_MEDIUM_STRAIN_YAML_DIR,
    MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
    MEDIADIVE_MEDIUM_TYPE_COMPLEX_LABEL,
    MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
    MEDIADIVE_MEDIUM_TYPE_DEFINED_LABEL,
    MEDIADIVE_MEDIUM_YAML_DIR,
    MEDIADIVE_MIN_PH_COLUMN,
    MEDIADIVE_REF_COLUMN,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_SOLUTION_PREFIX,
    MEDIADIVE_SOURCE_COLUMN,
    MEDIADIVE_TMP_DIR,
    MEDIUM,
    MEDIUM_CATEGORY,
    MEDIUM_STRAINS,
    MEDIUM_TO_INGREDIENT_EDGE,
    MEDIUM_TO_SOLUTION_EDGE,
    MEDIUM_TYPE_CATEGORY,
    MMOL_PER_LITER_COLUMN,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_MEDIUM_EDGE,
    NCBITAXON_ID_COLUMN,
    OBJECT_ID_COLUMN,
    PUBCHEM_KEY,
    PUBCHEM_PREFIX,
    RDFS_SUBCLASS_OF,
    RECIPE_KEY,
    ROLE_CATEGORY,
    SOLUTION,
    SOLUTION_CATEGORY,
    SOLUTION_ID_KEY,
    SOLUTION_KEY,
    SOLUTIONS_COLUMN,
    SOLUTIONS_KEY,
    SPECIES,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    TRANSLATION_TABLE_FOR_LABELS,
    UNIT_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.pandas_utils import (
    drop_duplicates,
)


class MediaDiveTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate part."""
        source_name = MEDIADIVE
        super().__init__(source_name, input_dir, output_dir)
        requests_cache.install_cache("mediadive_cache")
        self.chebi_impl = get_adapter(f"sqlite:{CHEBI_SOURCE}")
        self.translation_table = str.maketrans(TRANSLATION_TABLE_FOR_LABELS)

        # Load bulk downloaded data if available
        self.bulk_data_dir = Path("data/raw/mediadive")
        self.media_detailed = {}
        self.media_strains = {}
        self.solutions_data = {}
        self.compounds_data = {}
        self.using_bulk_data = False
        self.api_calls_avoided = 0
        self.api_calls_made = 0

        self._load_bulk_data()

    def _load_bulk_data(self):
        """
        Load bulk downloaded MediaDive data if available.

        This method loads pre-downloaded data files to avoid API calls during transform.
        Files are created by running: poetry run python download_mediadive_bulk.py
        """
        try:
            media_detailed_file = self.bulk_data_dir / "media_detailed.json"
            media_strains_file = self.bulk_data_dir / "media_strains.json"
            solutions_file = self.bulk_data_dir / "solutions.json"
            compounds_file = self.bulk_data_dir / "compounds.json"

            files_exist = all(
                [
                    media_detailed_file.exists(),
                    media_strains_file.exists(),
                    solutions_file.exists(),
                    compounds_file.exists(),
                ]
            )

            if files_exist:
                print(f"Loading bulk MediaDive data from {self.bulk_data_dir}/")

                with open(media_detailed_file) as f:
                    self.media_detailed = json.load(f)
                print(f"  Loaded {len(self.media_detailed)} detailed media recipes")

                with open(media_strains_file) as f:
                    self.media_strains = json.load(f)
                print(f"  Loaded strain associations for {len(self.media_strains)} media")

                with open(solutions_file) as f:
                    self.solutions_data = json.load(f)
                print(f"  Loaded {len(self.solutions_data)} solutions")

                with open(compounds_file) as f:
                    self.compounds_data = json.load(f)
                print(f"  Loaded {len(self.compounds_data)} compounds")

                self.using_bulk_data = True
                print("  Bulk data loaded successfully - API calls will be avoided")
            else:
                print(f"Bulk MediaDive data not found in {self.bulk_data_dir}/")
                print("  Transform will use API calls (may be slow)")
                print("  To download bulk data, run: poetry run kg download")

        except Exception as e:
            print(f"Warning: Could not load bulk data: {e}")
            print("  Transform will use API calls (may be slow)")

    def _get_mediadive_json(self, url: str) -> Dict[str, str]:
        """
        Use the API url to get a dict of information.

        :param url: Path provided by MetaDive API.
        :return: JSON response as a Dict.
        """
        r = requests.get(url, timeout=30)
        data_json = r.json()
        return data_json.get(DATA_KEY)

    def _get_label_via_oak(self, curie: str):
        prefix = curie.split(":")[0]
        if prefix.startswith(CHEBI_KEY):
            (_, label) = list(self.chebi_impl.labels([curie]))[0]
        return label

    def get_compounds_of_solution(self, id: str):
        """
        Get ingredients of solutions via bulk data or MediaDive API.

        First checks bulk downloaded data, then makes API call if needed.

        :param id: ID of solution
        :return: Dictionary of {compound_name: compound_id}
        """
        # Check bulk downloaded data first
        if self.using_bulk_data and id in self.solutions_data:
            self.api_calls_avoided += 1
            data = self.solutions_data[id]
        else:
            self.api_calls_made += 1
            url = MEDIADIVE_REST_API_BASE_URL + SOLUTION + id
            data = self._get_mediadive_json(url)

        ingredients_dict = {}
        for item in data[RECIPE_KEY]:
            if COMPOUND_ID_KEY in item and item[COMPOUND_ID_KEY] is not None:
                item[COMPOUND_KEY] = (
                    item[COMPOUND_KEY].translate(self.translation_table).replace('""', "").strip()
                    if isinstance(item[COMPOUND_KEY], str)
                    else item[COMPOUND_KEY]
                )
                ingredients_dict[item[COMPOUND_KEY]] = {
                    ID_COLUMN: self.standardize_compound_id(str(item[COMPOUND_ID_KEY])),
                    AMOUNT_COLUMN: item[AMOUNT_COLUMN],
                    UNIT_COLUMN: item[UNIT_COLUMN],
                    GRAMS_PER_LITER_COLUMN: item[GRAMS_PER_LITER_COLUMN],
                    MMOL_PER_LITER_COLUMN: item[MMOL_PER_LITER_COLUMN],
                }
            elif SOLUTION_ID_KEY in item and item[SOLUTION_ID_KEY] is not None:
                item[SOLUTION_KEY] = (
                    item[SOLUTION_KEY].translate(self.translation_table).replace('""', "").strip()
                    if isinstance(item[SOLUTION_KEY], str)
                    else item[SOLUTION_KEY]
                )

                ingredients_dict[item[SOLUTION_KEY]] = {
                    ID_COLUMN: MEDIADIVE_SOLUTION_PREFIX + str(item[SOLUTION_ID_KEY]),
                    AMOUNT_COLUMN: item[AMOUNT_COLUMN],
                    UNIT_COLUMN: item[UNIT_COLUMN],
                    GRAMS_PER_LITER_COLUMN: item[GRAMS_PER_LITER_COLUMN],
                    MMOL_PER_LITER_COLUMN: item[MMOL_PER_LITER_COLUMN],
                }
            else:
                continue
        return ingredients_dict

    def standardize_compound_id(self, id: str):
        """
        Get standardized IDs via bulk data or Metadive API.

        First checks bulk downloaded data, then makes API call if needed.

        :param id: Metadive compound ID
        :return: Standardized ID
        """
        # Check bulk downloaded data first
        if self.using_bulk_data and id in self.compounds_data:
            self.api_calls_avoided += 1
            data = self.compounds_data[id]
        else:
            self.api_calls_made += 1
            url = MEDIADIVE_REST_API_BASE_URL + COMPOUND + id
            data = self._get_mediadive_json(url)

        if data[CHEBI_KEY] is not None:
            return CHEBI_PREFIX + str(data[CHEBI_KEY])
        elif data[KEGG_KEY] is not None:
            return KEGG_PREFIX + str(data[KEGG_KEY])
        elif data[PUBCHEM_KEY] is not None:
            return PUBCHEM_PREFIX + str(data[PUBCHEM_KEY])
        elif data[CAS_RN_KEY] is not None:
            return CAS_RN_PREFIX + str(data[CAS_RN_KEY])
        else:
            return MEDIADIVE_INGREDIENT_PREFIX + id

    def download_yaml_and_get_json(
        self,
        url: str,
        target_dir: Path,
    ) -> Dict[str, str]:
        """
        Download MetaDive data using a url.

        :param url: Path provided by MetaDive API.
        """
        data_json = self._get_mediadive_json(url)
        if data_json:
            parsed_url = urlparse(url)
            fn = parsed_url.path.split("/")[-1] + ".yaml"
            if not (target_dir / fn).is_file():
                with open(str(target_dir / fn), "w") as f:
                    f.write(yaml.dump(data_json))
        return data_json

    def get_json_object(
        self, fn: Union[Path, str], url_extension: str, target_dir: Path
    ) -> Dict[str, str]:
        """
        Download YAML file if absent and return contents as a JSON object.

        First checks bulk downloaded data, then YAML cache, then makes API call.

        :param fn: YAML file path.
        :param url_extension: API endpoint extension (e.g., "medium/123")
        :param target_dir: Directory for YAML cache
        :return: Dictionary
        """
        # Extract ID from url_extension (e.g., "medium/123" -> "123")
        medium_id = url_extension.split("/")[-1]

        # Check bulk downloaded data first
        if self.using_bulk_data:
            if url_extension.startswith(MEDIUM_STRAINS):
                if medium_id in self.media_strains:
                    self.api_calls_avoided += 1
                    return self.media_strains[medium_id]
            elif url_extension.startswith(MEDIUM):
                if medium_id in self.media_detailed:
                    self.api_calls_avoided += 1
                    # Extract the recipe/solutions data structure to match API format
                    detailed_data = self.media_detailed[medium_id]
                    if RECIPE_KEY in detailed_data and SOLUTIONS_KEY in detailed_data[RECIPE_KEY]:
                        # Convert solutions dict back to list format expected by transform
                        solutions_dict = detailed_data[RECIPE_KEY][SOLUTIONS_KEY]
                        solutions_list = [
                            {ID_COLUMN: sol_id, NAME_COLUMN: sol_name}
                            for sol_id, sol_name in solutions_dict.items()
                        ]
                        return {SOLUTIONS_KEY: solutions_list}
                    return detailed_data

        # Fall back to YAML cache or API call
        if not fn.is_file():
            self.api_calls_made += 1
            url = MEDIADIVE_REST_API_BASE_URL + url_extension
            json_obj = self.download_yaml_and_get_json(url, target_dir)
        else:
            # Import YAML file fn as a dict
            with open(fn, "r") as f:
                try:
                    json_obj = yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    print(exc)
        return json_obj

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        # replace with downloaded data filename for this source
        input_file = os.path.join(self.input_base_dir, "mediadive.json")  # must exist already
        bacdive_input_file = BACDIVE_TMP_DIR / "bacdive.tsv"
        bacdive_df = pd.read_csv(
            bacdive_input_file, sep="\t", usecols=[BACDIVE_ID_COLUMN, NCBITAXON_ID_COLUMN]
        )

        # mediadive_data:List = mediadive["data"]
        # Read the JSON file into the variable input_json
        with open(input_file, "r") as f:
            input_json = json.load(f)

        COLUMN_NAMES = [
            MEDIADIVE_ID_COLUMN,
            NAME_COLUMN,
            MEDIADIVE_COMPLEX_MEDIUM_COLUMN,
            MEDIADIVE_SOURCE_COLUMN,
            MEDIADIVE_LINK_COLUMN,
            MEDIADIVE_MIN_PH_COLUMN,
            MEDIADIVE_MAX_PH_COLUMN,
            MEDIADIVE_REF_COLUMN,
            MEDIADIVE_DESC_COLUMN,
            SOLUTIONS_COLUMN,
            INGREDIENTS_COLUMN,
        ]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with (
            open(str(MEDIADIVE_TMP_DIR / "mediadive.tsv"), "w") as tsvfile,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            writer = csv.writer(tsvfile, delimiter="\t")
            # Write the column names to the output file
            writer.writerow(COLUMN_NAMES)

            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)

            # Choose the appropriate context manager based on the flag
            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(
                total=len(input_json[DATA_KEY]) + 1, desc="Processing files"
            ) as progress:
                # medium type nodes
                node_writer.writerows(
                    [
                        [
                            MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
                            MEDIUM_TYPE_CATEGORY,
                            MEDIADIVE_MEDIUM_TYPE_COMPLEX_LABEL,
                        ]
                        + [None] * (len(self.node_header) - 3),
                        [
                            MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
                            MEDIUM_TYPE_CATEGORY,
                            MEDIADIVE_MEDIUM_TYPE_DEFINED_LABEL,
                        ]
                        + [None] * (len(self.node_header) - 3),
                    ]
                )
                for dictionary in input_json[DATA_KEY]:
                    id = str(dictionary[ID_COLUMN])
                    dictionary[NAME_COLUMN] = (
                        dictionary[NAME_COLUMN]
                        .translate(self.translation_table)
                        .replace('""', "")
                        .strip()
                    )
                    fn: Path = Path(str(MEDIADIVE_MEDIUM_YAML_DIR / id) + ".yaml")
                    fn_medium_strain = Path(str(MEDIADIVE_MEDIUM_STRAIN_YAML_DIR / id) + ".yaml")
                    json_obj = self.get_json_object(fn, MEDIUM + id, MEDIADIVE_MEDIUM_YAML_DIR)
                    json_obj_medium_strain = self.get_json_object(
                        fn_medium_strain, MEDIUM_STRAINS + id, MEDIADIVE_MEDIUM_STRAIN_YAML_DIR
                    )

                    medium_id = MEDIADIVE_MEDIUM_PREFIX + str(id)  # SUBJECT

                    # Medium and Medium type edge
                    medium_type_edges = []
                    complex_medium_type = bool(dictionary[MEDIADIVE_COMPLEX_MEDIUM_COLUMN])
                    if complex_medium_type:
                        medium_type_edges = [
                            [
                                medium_id,
                                SUBCLASS_PREDICATE,
                                MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
                                RDFS_SUBCLASS_OF,
                                "MediaDive",
                            ]
                        ]
                    else:
                        medium_type_edges = [
                            [
                                medium_id,
                                SUBCLASS_PREDICATE,
                                MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
                                RDFS_SUBCLASS_OF,
                                "MediaDive",
                            ]
                        ]
                    edge_writer.writerows(medium_type_edges)

                    # Medium-Strains KG
                    if json_obj_medium_strain:
                        medium_strain_edge = []
                        medium_strain_nodes = []
                        for strain in json_obj_medium_strain:
                            if strain.get(BACDIVE_ID_COLUMN):
                                strain_id = BACDIVE_PREFIX + str(strain[BACDIVE_ID_COLUMN])
                                ncbi_strain_id = bacdive_df[
                                    bacdive_df[BACDIVE_ID_COLUMN] == strain_id
                                ][NCBITAXON_ID_COLUMN].values

                                if ncbi_strain_id.size > 0:
                                    ncbi_strain_id = list(ncbi_strain_id)[0]
                                else:
                                    ncbi_strain_id = STRAIN_PREFIX + strain_id.replace(":", "_")

                                if not (
                                    isinstance(ncbi_strain_id, float) and math.isnan(ncbi_strain_id)
                                ):
                                    medium_strain_nodes.extend(
                                        [
                                            [
                                                ncbi_strain_id,
                                                NCBI_CATEGORY,
                                                strain[SPECIES],
                                            ],
                                            [medium_id, MEDIUM_CATEGORY, dictionary[NAME_COLUMN]],
                                        ]
                                    )

                                    medium_strain_edge.extend(
                                        [
                                            [
                                                ncbi_strain_id,
                                                NCBI_TO_MEDIUM_EDGE,
                                                medium_id,
                                                IS_GROWN_IN,
                                                strain_id,
                                            ],
                                        ]
                                    )

                                    edge_writer.writerows(medium_strain_edge)

                    if SOLUTIONS_KEY not in json_obj:
                        continue
                    # solution_id_list = [solution[ID_COLUMN] for solution in json_obj[SOLUTIONS_KEY]]
                    solutions_dict = {
                        solution[ID_COLUMN]: solution[NAME_COLUMN]
                        .strip()
                        .translate(self.translation_table)
                        for solution in json_obj[SOLUTIONS_KEY]
                    }
                    ingredients_dict = {}
                    solution_ingredient_edges = []

                    for solution_id in solutions_dict.keys():
                        solution_curie = MEDIADIVE_SOLUTION_PREFIX + str(solution_id)
                        ingredients_dict.update(self.get_compounds_of_solution(str(solution_id)))
                        solution_ingredient_edges.extend(
                            [
                                [
                                    solution_curie,
                                    MEDIUM_TO_INGREDIENT_EDGE,
                                    v[ID_COLUMN],
                                    HAS_PART,
                                    MEDIADIVE_REST_API_BASE_URL + SOLUTION + str(solution_id),
                                ]
                                for _, v in ingredients_dict.items()
                            ]
                        )
                        solution_ingredient_edges.append(
                            # Add medium_solution_edge here too
                            [
                                medium_id,
                                MEDIUM_TO_SOLUTION_EDGE,
                                solution_curie,
                                HAS_PART,
                                MEDIADIVE_REST_API_BASE_URL + SOLUTION + str(solution_id),
                            ]
                        )

                    ingredient_nodes = [
                        [v[ID_COLUMN], INGREDIENT_CATEGORY, k] for k, v in ingredients_dict.items()
                    ]
                    solution_nodes = [
                        [MEDIADIVE_SOLUTION_PREFIX + str(k), SOLUTION_CATEGORY, v]
                        for k, v in solutions_dict.items()
                    ]

                    chebi_list = [
                        v[ID_COLUMN]
                        for _, v in ingredients_dict.items()
                        if str(v[ID_COLUMN]).startswith(CHEBI_PREFIX)
                    ]
                    if len(chebi_list) > 0:
                        chebi_roles = set(
                            self.chebi_impl.relationships(
                                subjects=set(chebi_list), predicates=[HAS_ROLE]
                            )
                        )
                        roles = {x for (_, _, x) in chebi_roles}
                        role_nodes = [
                            [role, ROLE_CATEGORY, self.chebi_impl.label(role)] for role in roles
                        ]
                        node_writer.writerows(role_nodes)
                        role_edges = [
                            [
                                subject,
                                CHEBI_TO_ROLE_EDGE,
                                object,
                                predicate,
                            ]
                            for (subject, predicate, object) in chebi_roles
                        ]
                        edge_writer.writerows(role_edges)

                    data = [
                        medium_id,
                        dictionary[NAME_COLUMN],
                        dictionary[MEDIADIVE_COMPLEX_MEDIUM_COLUMN],
                        dictionary[MEDIADIVE_SOURCE_COLUMN],
                        dictionary[MEDIADIVE_LINK_COLUMN],
                        dictionary[MEDIADIVE_MIN_PH_COLUMN],
                        dictionary[MEDIADIVE_MAX_PH_COLUMN],
                        dictionary[MEDIADIVE_REF_COLUMN],
                        dictionary[MEDIADIVE_DESC_COLUMN],
                        str(solutions_dict),
                        str(ingredients_dict),
                    ]

                    writer.writerow(data)  # writing the data

                    # Combine list creation and extension
                    nodes_data_to_write = [
                        [medium_id, MEDIUM_CATEGORY, dictionary[NAME_COLUMN]],
                        *solution_nodes,
                        *ingredient_nodes,
                        *medium_strain_nodes,
                    ]
                    nodes_data_to_write = [
                        sublist + [None] * (len(self.node_header) - 3)
                        for sublist in nodes_data_to_write
                    ]
                    node_writer.writerows(nodes_data_to_write)

                    edge_writer.writerows(solution_ingredient_edges)

                    progress.set_description(f"Processing mediadive: {medium_id}")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(self.output_node_file, consolidation_columns=[ID_COLUMN, NAME_COLUMN])
        drop_duplicates(self.output_edge_file, consolidation_columns=[OBJECT_ID_COLUMN])

        # Print data source and API call statistics
        print("\n" + "=" * 80)
        print("MediaDive Transform Complete")
        print("=" * 80)
        if self.using_bulk_data:
            print(f"Data source: Bulk downloaded files ({self.bulk_data_dir}/)")
            print(f"API calls avoided: {self.api_calls_avoided}")
            print(f"API calls made: {self.api_calls_made}")
            if self.api_calls_made > 0:
                print("  (Some API calls may have been needed for missing data in bulk files)")
        else:
            print("Data source: MediaDive API (slow - consider running bulk download)")
            print(f"API calls made: {self.api_calls_made}")
            print("To speed up future transforms, run: poetry run kg download")
        print("=" * 80 + "\n")

        # ! Commented out after discussing with Marcin. This is not needed for now.
        # establish_transitive_relationship(
        #     self.output_edge_file,
        #     MEDIADIVE_MEDIUM_PREFIX,
        #     MEDIADIVE_SOLUTION_PREFIX,
        #     MEDIUM_TO_INGREDIENT_EDGE,
        #     [
        #         MEDIADIVE_INGREDIENT_PREFIX,
        #         CHEBI_PREFIX,
        #         KEGG_PREFIX,
        #         PUBCHEM_PREFIX,
        #         CAS_RN_PREFIX,
        #     ],
        # )

        # # dump_ont_nodes_from(
        # #     self.output_node_file, self.input_base_dir / CHEBI_NODES_FILENAME, CHEBI_PREFIX
        # # )
        # get_ingredients_overlap(self.output_edge_file, MEDIADIVE_TMP_DIR / "ingredient_overlap.tsv")
