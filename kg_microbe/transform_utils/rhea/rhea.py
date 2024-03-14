"""Transform for Rhea."""

import csv
from glob import glob
from pathlib import Path
from typing import Optional, Union

from pyobo import get_id_name_mapping, get_relations_df, get_sssom_df
from pyobo.sources.rhea import RheaGetter

from kg_microbe.transform_utils.constants import (
    CHEBI_PREFIX,
    CLOSE_MATCH,
    DEBIO_MAPPER,
    DEBIO_PREDICATE_MAPPER,
    EC_CATEGORY,
    EC_PREFIX,
    GO_CATEGORY,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PROVIDED_BY_COLUMN,
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
    RHEA_RIGHT_TO_LEFT_DIRECTION,
    RHEA_SUBJECT_ID_COLUMN,
    RHEA_TARGET_ID_COLUMN,
    RHEA_TMP_DIR,
    RHEA_TO_EC_EDGE,
    RHEA_TO_GO_EDGE,
    RHEA_UNDEFINED_DIRECTION,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    SUPERCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform


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

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        fn1 = "id_label_mapping.tsv"
        fn2 = "sssom.tsv"
        rhea_relation = get_relations_df("rhea")
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
        rhea_relation[PROVIDED_BY_COLUMN] = "Rhea"

        rhea_relation = rhea_relation[self.edge_header]

        rhea_nodes = get_id_name_mapping("rhea")
        if not (RHEA_TMP_DIR / fn2).exists():
            rhea_sssom = get_sssom_df("rhea")
            rhea_sssom[RHEA_SUBJECT_ID_COLUMN] = rhea_sssom[RHEA_SUBJECT_ID_COLUMN].str.replace(
                r"(rhea)(:\d+)", lambda m: m.group(1).upper() + m.group(2), regex=True
            )
            rhea_sssom.to_csv(RHEA_TMP_DIR / fn2, sep="\t", index=False)

        with open(RHEA_TMP_DIR / fn1, "w") as tmp_file, open(
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
                [DEBIO_MAPPER.get(RHEA_UNDEFINED_DIRECTION), RHEA_DIRECTION_CATEGORY, RHEA_UNDEFINED_DIRECTION]
                + [None] * 11
            )
            nodes_file_writer.writerow(
                [DEBIO_MAPPER.get(RHEA_LEFT_TO_RIGHT_DIRECTION), RHEA_DIRECTION_CATEGORY, RHEA_LEFT_TO_RIGHT_DIRECTION]
                + [None] * 11
            )
            nodes_file_writer.writerow(
                [DEBIO_MAPPER.get(RHEA_RIGHT_TO_LEFT_DIRECTION), RHEA_DIRECTION_CATEGORY, RHEA_RIGHT_TO_LEFT_DIRECTION]
                + [None] * 11
            )

            for k, v in rhea_nodes.items():
                tmp_file_writer.writerow(
                    [RHEA_NEW_PREFIX + k, RHEA_CATEGORY, v, RHEA_UNDEFINED_DIRECTION]
                )
                nodes_file_writer.writerow([RHEA_NEW_PREFIX + k, RHEA_CATEGORY, v] + [None] * 11)

                tmp_file_writer.writerow(
                    [
                        RHEA_NEW_PREFIX + str(int(k) + 1),
                        RHEA_CATEGORY,
                        v,
                        DEBIO_MAPPER.get(RHEA_LEFT_TO_RIGHT_DIRECTION),
                    ]
                )
                nodes_file_writer.writerow(
                    [RHEA_NEW_PREFIX + str(int(k) + 1), RHEA_CATEGORY, v] + [None] * 11
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
                    [RHEA_NEW_PREFIX + str(int(k) + 2), RHEA_CATEGORY, v] + [None] * 11
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
                    [RHEA_NEW_PREFIX + str(int(k) + 3), RHEA_CATEGORY, v] + [None] * 11
                )

            # Get files that begin with "rhea2" and end with ".tsv" in self.input_base_dir
            pattern = f"{self.input_base_dir}/rhea2*.tsv"
            matching_files = glob(pattern)

            relation = CLOSE_MATCH
            ks = "Rhea"
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
                    # edges = "subject	predicate	object	relation	primary_knowledge_source"
                    # nodes = "id	category	name"
                    for row in mapping_tsv_reader:
                        subject = RHEA_NEW_PREFIX + str(row[rhea_idx])
                        object = xref_prefix + str(row[xref_idx])
                        nodes_file_writer.writerow([object, category, None] + [None] * 11)
                        edges_file_writer.writerow([subject, predicate, object, relation, ks])

                with open(RHEA_TMP_DIR / "all_terms.txt", "w") as test:
                    for term in RheaGetter().iter_terms():
                        test.write(f"{term}\n\n-------------------\n\n")
                        # if term.reference.prefix == CHEBI_PREFIX.rstrip(":").lower():
                        #     import pdb; pdb.set_trace()
                # TODO: Add the sssom.tsv file to the edges.tsv file
                # with open(RHEA_TMP_DIR / fn2) as sssom_file:
                #     rhea_sssom_reader = csv.reader(sssom_file, delimiter="\t")
                #     header = next(rhea_sssom_reader)

                #     for row in rhea_sssom_reader:
                #         pass
