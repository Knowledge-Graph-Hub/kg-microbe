"""Uniprot TrEMBL dat file Transform."""

from os import makedirs
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.constants import UNIPROT_DATA_LIST, UNIPROT_TREMBL_TMP_DIR
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.trembl_utils import unzip_trembl_file


class UniprotTrEMBLTransform(Transform):
    """Uniprot TrEMBL transform."""

    def __init__(
        self, input_dir: Optional[Union[str, Path]], output_dir: Optional[Union[str, Path]]
    ):
        """Initialize UniprotTrEMBLTransform."""
        source_name = "UniprotTrEMBLTransform"
        super().__init__(source_name, input_dir, output_dir)
        makedirs(UNIPROT_TREMBL_TMP_DIR, exist_ok=True)

    def run(
        self, file_path: Union[Optional[Path], Optional[str]] = None, show_status: bool = True
    ) -> None:
        """Run UniprotTrEMBLTransform."""
        data_list = UNIPROT_DATA_LIST

        for data in data_list:
            data_dir = self.input_base_dir / data
            if not (UNIPROT_TREMBL_TMP_DIR / f"{data}.tsv").exists():
                for uniprot_dir in data_dir.iterdir():
                    for file_path in uniprot_dir.iterdir():
                        if file_path.suffix == ".gz":
                            unzip_trembl_file(file_path)
            # ! ONLY FOR RERUNs
            # else:
            #     os.remove(UNIPROT_TREMBL_TMP_DIR / f"{data}.tsv")

        # ! Actual transform process begins here ...
