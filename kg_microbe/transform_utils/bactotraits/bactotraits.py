"""BactoTraits transform class."""

import ast
import csv
from pathlib import Path
from typing import Optional, Union

import yaml
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    ASSOCIATED_WITH,
    BACDIVE_CULTURE_COLLECTION_NUMBER_COLUMN,
    BACDIVE_ID_COLUMN,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    BACTOTRAITS,
    BACTOTRAITS_TMP_DIR,
    BIOLOGICAL_PROCESS,
    CAPABLE_OF_PREDICATE,
    CATEGORY_COLUMN,
    COMBO_KEY,
    CURIE_COLUMN,
    CUSTOM_CURIES_YAML_FILE,
    HAS_PHENOTYPE,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_PATHWAY_EDGE,
    NCBITAXON_ID_COLUMN,
    NCBITAXON_SOURCE,
    PREDICATE_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.oak_utils import get_label
from kg_microbe.utils.pandas_utils import drop_duplicates


class BactoTraitsTransform(Transform):

    """
    BactoTraits transform.

    Essentially just ingests and transforms this file:
    https://ordar.otelo.univ-lorraine.fr/files/ORDAR-53/BactoTraits_databaseV2_Jun2022.csv

    Columns available in the file:
    - strain n¡
    - Bacdive_ID
    - culture collection codes
    - Kingdom
    - Phylum
    - Class
    - Order
    - Family
    - Genus
    - Species
    - Full_name
    - pHO_0_to_6
    - pHO_6_to_7
    - pHO_7_to_8
    - pHO_8_to_14
    - pHR_0_to_4
    - pHR_4_to_6
    - pHR_6_to_7
    - pHR_7_to_8
    - pHR_8_to_10
    - 10_to_14
    - pHd_<=1
    - pHd_1_2
    - pHd_2_3
    - pHd_3_4
    - pHd_4_5
    - pHd_5_9
    - NaO_<=1
    - NaO_1_to_3
    - NaO_3_to_8
    - NaO_>8
    - NaR_<=1
    - NaR_1_to_3
    - NaR_3_to_8
    - NaR_>8
    - Nad_<=1
    - Nad_1_3
    - Nad_3_8
    - Nad_>8
    - TO_<=10
    - TO_10_to_22
    - TO_22_to_27
    - TO_27_to_30
    - TO_30_to_34
    - TO_34_to_40
    - TO_>40
    - TR_<=10
    - TR_10_to_22
    - TR_22_to_27
    - TR_27_to_30
    - TR_30_to_34
    - TR_34_to_40
    - TR_>40
    - Td_1_5
    - Td_5_10
    - Td_10_20
    - Td_20_30
    - Td_>30
    - Ox_anaerobic
    - Ox_aerobic
    - Ox_facultative_aerobe_anaerobe
    - Ox_microerophile
    - G_negative
    - G_positive
    - non-motile
    - motile
    - spore
    - no_spore
    - GC_<=42.65
    - GC_42.65_57.0
    - GC_57.0_66.3
    - GC_>66.3
    - W_<=0.5
    - W_0.5_0.65
    - W_0.65_0.9
    - W_>0.9
    - L_<=1.3
    - L_1.3_2
    - L_2_3
    - L_>3
    - S_rod
    - S_sphere
    - S_curved_spiral
    - S_filament
    - S_ovoid
    - S_star_dumbbell_pleomorphic
    - TT_heterotroph
    - TT_autotroph
    - TT_organotroph
    - TT_lithotroph
    - TT_chemotroph
    - TT_phototroph
    - TT_copiotroph_diazotroph
    - TT_methylotroph
    - TT_oligotroph
    - Pigment_pink
    - Pigment_yellow
    - Pigment_brown
    - Pigment_black
    - Pigment_orange
    - Pigment_white
    - Pigment_cream
    - Pigment_red
    - Pigment_green
    - Pigment_carotenoid

    """

    def __init__(
        self, input_dir: Optional[Union[str, Path]], output_dir: Optional[Union[str, Path]]
    ):
        """Initialize BactoTraitsTransform."""
        source_name = BACTOTRAITS
        super().__init__(source_name, input_dir, output_dir)
        self.ncbi_impl = get_adapter(f"sqlite:{NCBITAXON_SOURCE}")

    def _clean_row(self, row):
        # Create a translation table that maps unwanted characters to None
        translation_table = str.maketrans("", "", '"()')

        return [value.translate(translation_table).strip() for value in row]

    def run(
        self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True
    ) -> None:
        """Run BactoTraitsTransform."""
        if data_file is None:
            data_file = "BactoTraits_databaseV2_Jun2022.csv"
        input_file = self.input_base_dir / data_file
        # Clean the raw file
        # - the file is a CSV file with delimiter as ";"
        # - many rows have empty values
        # - we just need rows with non-empty values from column 4 onwards.
        # - we also need to remove the first 2 rows, which are not needed.
        # - row 3 is the header which needs to be preserved.
        # - we also need to remove the first column, which is not needed.
        # - second column is actually NOT BacDive ID, in spite of the header. It is actually column 3
        # - we need to convert the file to a TSV file

        BACTOTRAITS_TMP_DIR.mkdir(parents=True, exist_ok=True)
        bacdive_ncbitaxon_dict = {}
        mapping_file = BACTOTRAITS_TMP_DIR / f"{self.source_name}_mapping.tsv"
        if mapping_file.exists():
            with open(mapping_file, "r") as mapping_file:
                mapping_reader = csv.DictReader(mapping_file, delimiter="\t")
                for row in mapping_reader:
                    bacdive_ncbitaxon_dict[row["Bacdive_ID"]] = row[NCBITAXON_ID_COLUMN]
        else:
            with open(BACDIVE_TMP_DIR / "bacdive.tsv", "r") as bacdive_file, open(
                mapping_file, "w"
            ) as mapping_file:
                # get 3 columns from bacdive.tsv: ['bacdive_id', 'culture_collection_number', 'ncbitaxon_id']
                bacdive_reader = csv.DictReader(bacdive_file, delimiter="\t")
                mapping_writer = csv.writer(mapping_file, delimiter="\t")
                mapping_writer.writerow(
                    ["Bacdive_ID", BACDIVE_CULTURE_COLLECTION_NUMBER_COLUMN, NCBITAXON_ID_COLUMN]
                )
                for row in bacdive_reader:
                    collection_number_list = row[BACDIVE_CULTURE_COLLECTION_NUMBER_COLUMN]
                    # Determine the value for the second column based on whether collection_number_list is not empty.
                    second_column_value = (
                        self._clean_row(ast.literal_eval(collection_number_list))
                        if collection_number_list
                        else ""
                    )

                    # Write the row with the determined values.
                    mapping_writer.writerow(
                        [
                            row[BACDIVE_ID_COLUMN],
                            second_column_value,
                            row[NCBITAXON_ID_COLUMN],
                        ]
                    )
                    bacdive_ncbitaxon_dict[row[BACDIVE_ID_COLUMN]] = row[NCBITAXON_ID_COLUMN]

        pruned_file = BACTOTRAITS_TMP_DIR / f"{self.source_name}.tsv"
        with (
            open(input_file, "r", encoding="ISO-8859-1") as infile,
            open(pruned_file, "w") as outfile,
            open(CUSTOM_CURIES_YAML_FILE, "r") as cc_file,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            reader = csv.reader(infile, delimiter=";")
            writer = csv.writer(outfile, delimiter="\t")
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)
            custom_curie_data = yaml.safe_load(cc_file)
            custom_curie_map = {
                second_level_key: nested_data
                for first_level_value in custom_curie_data.values()
                for second_level_key, nested_data in first_level_value.items()
            }
            combo_curie_map = {
                key: value for key, value in custom_curie_map.items() if COMBO_KEY in value
            }
            unique_combo_node_data = [
                (
                    inner_curie_map[CURIE_COLUMN],
                    inner_curie_map[CATEGORY_COLUMN],
                    inner_curie_map[NAME_COLUMN],
                )
                for _, v in combo_curie_map.items()
                for inner_curie_map in v[COMBO_KEY]
            ]
            unique_combo_edge_data = [
                (
                    v[CURIE_COLUMN],
                    CAPABLE_OF_PREDICATE,
                    inner_curie_map[CURIE_COLUMN],
                    ASSOCIATED_WITH,
                    "BactoTraits.csv",
                )
                for _, v in combo_curie_map.items()
                for inner_curie_map in v[COMBO_KEY]
            ]
            combo_edge_data = [list(edge) for edge in unique_combo_edge_data]
            combo_node_data = [list(edge) for edge in unique_combo_node_data]

            progress_class = tqdm if show_status else DummyTqdm
            with progress_class() as progress:
                for i, row in enumerate(reader):
                    if i > 1 and len(row) > 3:
                        row = ["" if value == "NA" else value for value in row]
                        if row[1] == "":
                            continue
                        else:
                            row[1] = BACDIVE_PREFIX + row[1] if i > 2 else "Bacdive_ID"
                        ncbitaxon_id = bacdive_ncbitaxon_dict.get(row[1], "")
                        row.insert(2, ncbitaxon_id) if i > 2 else row.insert(2, NCBITAXON_ID_COLUMN)
                        writer.writerow(row[1:])
                        # Create nodes from this row
                        if i == 2:
                            header = row
                            dict_keys = header[1:]
                        elif i > 2:
                            row_as_dict = dict(zip(dict_keys, row[1:], strict=False))
                            row_as_dict_with_values = {
                                k.strip(): v for k, v in row_as_dict.items() if v and v != "0"
                            }

                            nodes_from_custom_curie_map = {
                                key: custom_curie_map[
                                    key.lower().replace(" ", "_").replace("-", "_")
                                ]
                                for key in row_as_dict_with_values.keys()
                                if key.lower().replace(" ", "_").replace("-", "_")
                                in custom_curie_map
                            }

                            nodes_data_to_write = [
                                [value[CURIE_COLUMN], value[CATEGORY_COLUMN], value[NAME_COLUMN]]
                                for _, value in nodes_from_custom_curie_map.items()
                                if value[CURIE_COLUMN]
                            ]
                            if ncbitaxon_id:
                                ncbi_label = get_label(self.ncbi_impl, ncbitaxon_id)
                                if ncbi_label:
                                    ncbi_label = str(ncbi_label).strip()
                                nodes_data_to_write.append(
                                    [
                                        ncbitaxon_id,
                                        NCBI_CATEGORY,
                                        ncbi_label,
                                    ]
                                )
                            nodes_data_to_write = [
                                sublist + [None] * (len(self.node_header) - 3)
                                for sublist in nodes_data_to_write
                            ]

                            node_writer.writerows(nodes_data_to_write)
                            # Create edges from this row
                            if ncbitaxon_id:
                                edges_data_to_write = [
                                    [
                                        ncbitaxon_id,
                                        value[PREDICATE_COLUMN],
                                        value[CURIE_COLUMN],
                                        (
                                            BIOLOGICAL_PROCESS
                                            if value[PREDICATE_COLUMN] == NCBI_TO_PATHWAY_EDGE
                                            else HAS_PHENOTYPE
                                        ),
                                        "BactoTraits.csv",
                                    ]
                                    for _, value in nodes_from_custom_curie_map.items()
                                    if value[CURIE_COLUMN]
                                ]
                                edge_writer.writerows(edges_data_to_write)

                    progress.set_description(f"Processing line #{i}")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update(1)
                node_writer.writerows(combo_node_data)
                edge_writer.writerows(combo_edge_data)
        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
