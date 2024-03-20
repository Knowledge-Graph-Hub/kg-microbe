"""BactoTraits transform class."""
from kg_microbe.transform_utils.constants import BACDIVE_PREFIX, BACTOTRAITS_TMP_DIR
from kg_microbe.transform_utils.transform import Transform
import csv
from pathlib import Path
from typing import Optional, Union


class BactoTraitsTransform(Transform):
    """BactoTraits transform.
    
    Essentially just ingests and transforms this file:
    https://ordar.otelo.univ-lorraine.fr/files/ORDAR-53/BactoTraits_databaseV2_Jun2022.csv

    Columns available in the file:
    - strain n¡
    - ✓ Bacdive_ID
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

    def __init__(self, input_dir: Optional[Union[str, Path]], output_dir: Optional[Union[str, Path]]):
        """Initialize BactoTraitsTransform."""
        source_name = "BactoTraits"
        super().__init__(source_name, input_dir, output_dir)

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True) -> None:
        """Run BactoTraitsTransform."""
        if data_file is None:
            data_file = self.source_name + "_databaseV2_Jun2022.csv"
        input_file = self.input_base_dir / data_file
        # Clean the raw file
        # - the file is a CSV file with delimeter as ";"
        # - many rows have empty values
        # - we just need rows with non-empty values from column 4 onwards.
        # - we also need to remove the first 2 rows, which are not needed.
        # - row 3 is the header which needs to be preserved.
        # - we also need to remove the first column, which is not needed.
        # - second column is actually NOT BacDive ID, in spite of the header. It is actually column 3
        # - we need to convert the file to a TSV file


        BACTOTRAITS_TMP_DIR.mkdir(parents=True, exist_ok=True)
        pruned_file = BACTOTRAITS_TMP_DIR / f"{self.source_name}.tsv"
        with open(input_file, "r", encoding="ISO-8859-1") as infile, open(pruned_file, "w") as outfile:
            reader = csv.reader(infile, delimiter=";")
            writer = csv.writer(outfile, delimiter="\t")
            for i, row in enumerate(reader):
                if i > 1 and len(row) > 3:
                    # Here we need to make some adjestments to the row before writing it to the file
                    # e.g. row : DSM 3508, ATCC 15973, NCIB 8621, CCUG 18122, LMG 1261-t1, LMG 1261 1, CCTM 3043
                    # should be written as: DSM 3508\tATCC 15973, NCIB 8621, CCUG 18122, LMG 1261-t1, LMG 1261 1, CCTM 3043 and other columns as is
                    # i.e. the first column should be split into 2 columns: Bacdive_ID and culture collection codes (comma separated)
                    # row_3 = ", ".join(row[2].split(", ")[1:])  # Splitting the first column into Bacdive_ID and culture collection codes
                    # row[2] = row[2].split(", ")[0]  # Splitting the first column into Bacdive_ID and culture collection codes
                    # row.insert(3, row_3)
                    row = ["" if value == "NA" else value for value in row]
                    row[1] = BACDIVE_PREFIX+row[1] if i > 2 else "Bacdive_ID"
                    writer.writerow(row[1:])
        