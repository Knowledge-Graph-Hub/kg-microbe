"""Transform for Rhea."""

import csv
from collections import defaultdict
from glob import glob
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import requests_ftp
from curies import load_extended_prefix_map
from oaklib import get_adapter
from pyobo import get_id_name_mapping, get_relations_df
from pyobo.sources.rhea import RheaGetter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CHEBI_PREFIX,
    CLOSE_MATCH,
    DEBIO_MAPPER,
    EC_CATEGORY,
    EC_PREFIX,
    GO_CATEGORY,
    GO_PREFIX,
    ID_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    OBJECT_ID_COLUMN,
    OBJECT_LABEL_COLUMN,
    PREDICATE_COLUMN,
    PREDICATE_ID_COLUMN,
    PREDICATE_LABEL_COLUMN,
    PROVIDED_BY_COLUMN,
    RAW_DATA_DIR,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    RHEA_BIDIRECTIONAL_DIRECTION,
    RHEA_CATEGORY,
    RHEA_CATEGORY_COLUMN,
    RHEA_DIRECTION_CATEGORY,
    RHEA_DIRECTION_COLUMN,
    RHEA_ID_COLUMN,
    RHEA_LEFT_TO_RIGHT_DIRECTION,
    RHEA_MAPPING_ID_COLUMN,
    RHEA_MAPPING_OBJECT_COLUMN,
    RHEA_NAME_COLUMN,
    RHEA_NEW_PREFIX,
    RHEA_PREDICATE_MAPPER,
    RHEA_RIGHT_TO_LEFT_DIRECTION,
    RHEA_SUBJECT_ID_COLUMN,
    RHEA_TARGET_ID_COLUMN,
    RHEA_TMP_DIR,
    RHEA_TO_EC_EDGE,
    RHEA_TO_GO_EDGE,
    RHEA_UNDEFINED_DIRECTION,
    SPECIAL_PREFIXES,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    SUBJECT_LABEL_COLUMN,
    SUBSTRATE_CATEGORY,
    SUPERCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.oak_utils import get_label


class RheaMappingsTransform(Transform):

    """Template for how the transform class would be designed."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """Instantiate part."""
        source_name = "RheaMappings"
        super().__init__(source_name, input_dir, output_dir)
        self.converter = load_extended_prefix_map(RAW_DATA_DIR / "epm.json")
        self.reference_cache = defaultdict(lambda: None)
        self.chebi_oi = get_adapter("sqlite:obo:chebi")
        self.go_oi = get_adapter("sqlite:obo:go")
        self.ec_oi = get_adapter("sqlite:obo:eccode")

    def _reference_to_tuple(self, ref):
        """Convert a reference to a tuple."""
        # Check if the result is already cached
        if ref in self.reference_cache:
            return self.reference_cache[ref]

        # Use the mapping if the prefix is a special case, otherwise standardize it
        prefix = SPECIAL_PREFIXES.get(ref.prefix, self.converter.standardize_prefix(ref.prefix))

        # Cache the result before returning
        result = (f"{prefix}:{ref.identifier}", ref.name)
        self.reference_cache[ref] = result

        return result

    def _get_label_based_on_prefix(self, id):
        if id.startswith(CHEBI_PREFIX.rstrip(":")):
            return get_label(self.chebi_oi, id)
        elif id.startswith(GO_PREFIX.rstrip(":")):
            return get_label(self.go_oi, id)
        elif id.startswith(EC_PREFIX.rstrip(":")):
            return get_label(self.ec_oi, id)
        # Add more conditions as needed
        else:
            return None

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        fn1 = "id_label_mapping.tsv"
        ks = "RheaViaPyObo"
        # fn2 = "sssom.tsv"
        # TODO: Remove the line below once bioversions new version is released
        requests_ftp.monkeypatch_session()
        rhea_relation = get_relations_df("rhea", use_tqdm=show_status)
        rhea_relation["relation_ns"] = rhea_relation["relation_ns"].apply(
            lambda x: self.converter.standardize_prefix(x)
        )
        rhea_relation[RELATION_COLUMN] = (
            rhea_relation["relation_ns"] + ":" + rhea_relation["relation_id"]
        )

        rhea_relation[RHEA_MAPPING_ID_COLUMN.lower()] = RHEA_NEW_PREFIX + rhea_relation[
            RHEA_MAPPING_ID_COLUMN.lower()
        ].astype(str)
        rhea_relation[RHEA_TARGET_ID_COLUMN] = RHEA_NEW_PREFIX + rhea_relation[
            RHEA_TARGET_ID_COLUMN
        ].astype(str)

        rhea_relation[PREDICATE_COLUMN] = rhea_relation[RELATION_COLUMN].apply(
            lambda x: (
                x.replace(RDFS_SUBCLASS_OF, SUBCLASS_PREDICATE)
                if x == RDFS_SUBCLASS_OF
                else SUPERCLASS_PREDICATE
            )
        )
        rhea_relation = rhea_relation.drop(columns=["relation_ns", "relation_id", "target_ns"])
        rhea_relation = rhea_relation.rename(
            columns={
                RHEA_MAPPING_ID_COLUMN.lower(): SUBJECT_COLUMN,
                RHEA_TARGET_ID_COLUMN: OBJECT_COLUMN,
            }
        )
        rhea_relation[PROVIDED_BY_COLUMN] = ks

        rhea_relation = rhea_relation[self.edge_header]

        rhea_nodes = get_id_name_mapping("rhea")
        # # TODO: Add the sssom.tsv file to the edges.tsv file
        # if not (RHEA_TMP_DIR / fn2).is_file():
        #     rhea_sssom = get_sssom_df("rhea")
        #     rhea_sssom[RHEA_SUBJECT_ID_COLUMN] = rhea_sssom[RHEA_SUBJECT_ID_COLUMN].str.replace(
        #         r"(rhea)(:\d+)", lambda m: m.group(1).upper() + m.group(2), regex=True
        #     )
        #     rhea_sssom.to_csv(RHEA_TMP_DIR / fn2, sep="\t", index=False)

        with open(RHEA_TMP_DIR / f"rhea_{fn1}", "w") as tmp_file, open(
            self.output_dir / "nodes.tsv", "w"
        ) as nodes_file, open(self.output_dir / "edges.tsv", "w") as edges_file:
            tmp_file_writer = csv.writer(tmp_file, delimiter="\t")
            nodes_file_writer = csv.writer(nodes_file, delimiter="\t")
            edges_file_writer = csv.writer(edges_file, delimiter="\t")

            tmp_file_writer.writerow(
                [RHEA_ID_COLUMN, RHEA_CATEGORY_COLUMN, RHEA_NAME_COLUMN, RHEA_DIRECTION_COLUMN]
            )
            nodes_file_writer.writerow(self.node_header)
            edges_file_writer.writerow(self.edge_header)
            edges_file_writer.writerows(rhea_relation.values.tolist())

            # write direction for rhea nodes
            nodes_file_writer.writerow(
                [
                    DEBIO_MAPPER.get(RHEA_LEFT_TO_RIGHT_DIRECTION),
                    RHEA_DIRECTION_CATEGORY,
                    RHEA_LEFT_TO_RIGHT_DIRECTION,
                ]
                + [None] * (len(self.node_header) - 3)
            )
            nodes_file_writer.writerow(
                [
                    DEBIO_MAPPER.get(RHEA_RIGHT_TO_LEFT_DIRECTION),
                    RHEA_DIRECTION_CATEGORY,
                    RHEA_RIGHT_TO_LEFT_DIRECTION,
                ]
                + [None] * (len(self.node_header) - 3)
            )

            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(
                total=len(rhea_nodes.items()) + 1, desc="Processing RHEA mappings..."
            ) as progress:
                for k, v in rhea_nodes.items():
                    tmp_file_writer.writerow(
                        [RHEA_NEW_PREFIX + k, RHEA_CATEGORY, v, RHEA_UNDEFINED_DIRECTION]
                    )
                    nodes_file_writer.writerow(
                        [RHEA_NEW_PREFIX + k, RHEA_CATEGORY, v]
                        + [None] * (len(self.node_header) - 3)
                    )

                    tmp_file_writer.writerow(
                        [
                            RHEA_NEW_PREFIX + str(int(k) + 1),
                            RHEA_CATEGORY,
                            v,
                            DEBIO_MAPPER.get(RHEA_LEFT_TO_RIGHT_DIRECTION),
                        ]
                    )
                    nodes_file_writer.writerow(
                        [RHEA_NEW_PREFIX + str(int(k) + 1), RHEA_CATEGORY, v]
                        + [None] * (len(self.node_header) - 3)
                    )

                    tmp_file_writer.writerow(
                        [
                            RHEA_NEW_PREFIX + str(int(k) + 2),
                            RHEA_CATEGORY,
                            v,
                            DEBIO_MAPPER.get(RHEA_RIGHT_TO_LEFT_DIRECTION),
                        ]
                    )
                    nodes_file_writer.writerow(
                        [RHEA_NEW_PREFIX + str(int(k) + 2), RHEA_CATEGORY, v]
                        + [None] * (len(self.node_header) - 3)
                    )

                    tmp_file_writer.writerow(
                        [
                            RHEA_NEW_PREFIX + str(int(k) + 3),
                            RHEA_CATEGORY,
                            v,
                            DEBIO_MAPPER.get(RHEA_BIDIRECTIONAL_DIRECTION),
                        ]
                    )
                    nodes_file_writer.writerow(
                        [RHEA_NEW_PREFIX + str(int(k) + 3), RHEA_CATEGORY, v]
                        + [None] * (len(self.node_header) - 3)
                    )
                    progress.set_description(f"Processing RHEA node: {RHEA_NEW_PREFIX + k} ...")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

            # Get files that begin with "rhea2" and end with ".tsv" in self.input_base_dir
            pattern = f"{self.input_base_dir}/rhea2*.tsv"
            matching_files = glob(pattern)

            relation = CLOSE_MATCH
            with progress_class(
                total=len(matching_files), desc="Processing Rhea mappings..."
            ) as progress:
                for file in matching_files:
                    if "rhea2ec" in file:
                        xref_prefix = EC_PREFIX
                        predicate = RHEA_TO_EC_EDGE
                        category = EC_CATEGORY
                    elif "rhea2go" in file:
                        xref_prefix = ""  # GO prefix already in the file
                        predicate = RHEA_TO_GO_EDGE
                        category = GO_CATEGORY

                    with open(file, "r") as tmp_file:
                        mapping_tsv_reader = csv.reader(tmp_file, delimiter="\t")
                        # Read the header
                        header = next(mapping_tsv_reader)
                        rhea_idx, xref_idx = (
                            index
                            for index, column_name in enumerate(header)
                            if column_name in {RHEA_MAPPING_ID_COLUMN, RHEA_MAPPING_OBJECT_COLUMN}
                        )

                        for row in mapping_tsv_reader:
                            subject_info = RHEA_NEW_PREFIX + str(row[rhea_idx])
                            object = xref_prefix + str(row[xref_idx])
                            nodes_file_writer.writerow(
                                [object, category, None] + [None] * (len(self.node_header) - 3)
                            )
                            edges_file_writer.writerow(
                                [subject_info, predicate, object, relation, ks]
                            )

                    with open(RHEA_TMP_DIR / "all_terms.tsv", "w", newline="") as tsvfile:
                        all_terms_writer = csv.writer(tsvfile, delimiter="\t")
                        # Write headers
                        all_terms_writer.writerow(
                            [
                                RHEA_SUBJECT_ID_COLUMN,
                                SUBJECT_LABEL_COLUMN,
                                PREDICATE_ID_COLUMN,
                                PREDICATE_LABEL_COLUMN,
                                OBJECT_ID_COLUMN,
                                OBJECT_LABEL_COLUMN,
                            ]
                        )
                        # Create an instance of RheaGetter outside the loop to avoid repeated instantiation
                        rhea_getter = RheaGetter()
                        # Iterate over all terms
                        for term in rhea_getter.iter_terms():
                            # Extract subject information
                            subject_info = self._reference_to_tuple(term.reference)
                            # Iterate over relationships
                            for predicate, objects in term.relationships.items():
                                predicate_info = self._reference_to_tuple(predicate)
                                for obj in objects:
                                    object_info = self._reference_to_tuple(obj)
                                    # Write the row in the specified format
                                    all_terms_writer.writerow(
                                        [*subject_info, *predicate_info, *object_info]
                                    )
                                    if any(
                                        object_info[0].startswith(prefix)
                                        for prefix in [CHEBI_PREFIX, EC_PREFIX, GO_PREFIX]
                                    ):
                                        if object_info[0].startswith(CHEBI_PREFIX):
                                            category = SUBSTRATE_CATEGORY
                                        elif object_info[0].startswith(GO_PREFIX):
                                            category = GO_CATEGORY
                                        else:
                                            category = EC_CATEGORY
                                        nodes_file_writer.writerow(
                                            [object_info[0], category, object_info[1]]
                                            + [None] * (len(self.node_header) - 3)
                                        )
                                        edges_file_writer.writerow(
                                            [
                                                subject_info[0],
                                                RHEA_PREDICATE_MAPPER.get(
                                                    predicate_info[1], predicate_info[1]
                                                ),
                                                object_info[0],
                                                predicate_info[0],
                                                ks,
                                            ]
                                        )
                progress.set_description(f"Processing {file} ...")
                # After each iteration, call the update method to advance the progress bar.
                progress.update()
        # Add labels for the nodes
        nodes_df = pd.read_csv(
            self.output_dir / "nodes.tsv", sep="\t", low_memory=False
        ).drop_duplicates()
        no_name_df = nodes_df[nodes_df[NAME_COLUMN].isna()][
            [ID_COLUMN, NAME_COLUMN]
        ].drop_duplicates()
        no_name_df[NAME_COLUMN] = no_name_df[ID_COLUMN].apply(
            lambda x: self._get_label_based_on_prefix(x)
        )
        nodes_df.update(no_name_df)
        nodes_df.to_csv(self.output_dir / "nodes.tsv", sep="\t", index=False)
