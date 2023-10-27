"""Transform the traits data from NCBI and GTDB."""

import csv
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
import yaml
from oaklib.utilities.ner_utilities import get_exclusion_token_list

from kg_microbe.transform_utils.constants import (
    ACTUAL_TERM_KEY,
    BIOLOGICAL_PROCESS,
    CARBON_SUBSTRATE_CATEGORY,
    CARBON_SUBSTRATE_PREFIX,
    CARBON_SUBSTRATES_COLUMN,
    CELL_SHAPE_COLUMN,
    CHEBI_PREFIX,
    ENVO_ID_COLUMN,
    ENVO_TERMS_COLUMN,
    GO_PREFIX,
    HAS_PHENOTYPE,
    ID_COLUMN,
    ISOLATION_SOURCE_COLUMN,
    ISOLATION_SOURCE_PREFIX,
    LOCATION_OF,
    METABOLISM_CATEGORY,
    METABOLISM_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_CHEM_EDGE,
    NCBI_TO_ISOLATION_SOURCE_EDGE,
    NCBI_TO_METABOLISM_EDGE,
    NCBI_TO_PATHWAY_EDGE,
    NCBI_TO_SHAPE_EDGE,
    NCBITAXON_PREFIX,
    OBJECT_LABEL_COLUMN,
    ORG_NAME_COLUMN,
    PATHWAY_CATEGORY,
    PATHWAY_PREFIX,
    PATHWAYS_COLUMN,
    PREFERRED_TERM_KEY,
    SHAPE_CATEGORY,
    SHAPE_PREFIX,
    SUBJECT_LABEL_COLUMN,
    TAX_ID_COLUMN,
    TRAITS_DATASET_LABEL_COLUMN,
    TROPHICALLY_INTERACTS_WITH,
    TYPE_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.ner_utils import annotate
from kg_microbe.utils.pandas_utils import drop_duplicates

OUTPUT_FILE_SUFFIX = "_ner.tsv"
STOPWORDS_FN = "stopwords.txt"
PARENT_DIR = Path(__file__).resolve().parent


class TraitsTransform(Transform):

    """
    Ingest traits dataset (NCBI/GTDB).

    Essentially just ingests and transforms this file:
    https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/output/condensed_traits_NCBI.csv
    And extracts the following columns:
        - tax_id
        - org_name
        - metabolism
        - pathways
        - shape
        - carbon_substrates
        - cell_shape
        - isolation_source
    Also implements:
        -   OAK to run NLP via the 'ner_utils' module and
        -   ROBOT using 'robot_utils' module.
    """

    def __init__(self, input_dir: str, output_dir: str, nlp=True) -> None:
        """
        Initialize TraitsTransform Class.

        :param input_dir: Input file path (str)
        :param output_dir: Output file path (str)
        """
        source_name = "traits"
        super().__init__(source_name, input_dir, output_dir, nlp)  # set some variables
        self.nlp = nlp
        self.metabolism_map_yaml = PARENT_DIR / "metabolism_map.yaml"
        self.environments_file = self.input_base_dir / "environments.csv"

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):
        """
        Call method and perform needed transformations for trait data (NCBI/GTDB).

        :param data_file: Input file name.
        """
        if data_file is None:
            data_file = self.source_name + ".csv"
        input_file = self.input_base_dir / data_file
        cols_for_nlp = [TAX_ID_COLUMN, PATHWAYS_COLUMN, CARBON_SUBSTRATES_COLUMN]
        nlp_df = pd.read_csv(input_file, usecols=cols_for_nlp, low_memory=False)
        nlp_df[[TAX_ID_COLUMN, PATHWAYS_COLUMN]].dropna()
        nlp_df[TAX_ID_COLUMN] = nlp_df[TAX_ID_COLUMN].apply(lambda x: NCBITAXON_PREFIX + str(x))
        chebi_nlp_df = nlp_df[[TAX_ID_COLUMN, CARBON_SUBSTRATES_COLUMN]].dropna()
        go_nlp_df = nlp_df[[TAX_ID_COLUMN, PATHWAYS_COLUMN]].dropna()
        exclusion_list = get_exclusion_token_list([self.nlp_stopwords_dir / STOPWORDS_FN])
        go_result_fn = GO_PREFIX.strip(":").lower() + OUTPUT_FILE_SUFFIX
        chebi_result_fn = CHEBI_PREFIX.strip(":").lower() + OUTPUT_FILE_SUFFIX

        if not (self.nlp_output_dir / chebi_result_fn).is_file():
            annotate(
                chebi_nlp_df,
                CHEBI_PREFIX,
                exclusion_list,
                self.nlp_output_dir / chebi_result_fn,
                False,
            )
            chebi_result = pd.read_csv(
                str(self.nlp_output_dir / chebi_result_fn), sep="\t", low_memory=False
            )
            chebi_result = chebi_result.drop_duplicates()
            chebi_result.to_csv(str(self.nlp_output_dir / chebi_result_fn), sep="\t", index=False)
        else:
            chebi_result = pd.read_csv(
                str(self.nlp_output_dir / chebi_result_fn), sep="\t", low_memory=False
            )
        if not (self.nlp_output_dir / go_result_fn).is_file():
            annotate(
                go_nlp_df, GO_PREFIX, exclusion_list, self.nlp_output_dir / go_result_fn, False
            )
            go_result = pd.read_csv(
                str(self.nlp_output_dir / go_result_fn), sep="\t", low_memory=False
            )
            go_result = go_result.drop_duplicates()
            go_result.to_csv(str(self.nlp_output_dir / go_result_fn), sep="\t", index=False)
        else:
            go_result = pd.read_csv(
                str(self.nlp_output_dir / go_result_fn), sep="\t", low_memory=False
            )

        with open(self.metabolism_map_yaml, "r") as file:
            data = yaml.safe_load(file)

        metabolism_map = {item[ACTUAL_TERM_KEY]: item for item in data}
        envo_cols = [TYPE_COLUMN, ENVO_TERMS_COLUMN, ENVO_ID_COLUMN]
        envo_df = pd.read_csv(
            self.environments_file, low_memory=False, usecols=envo_cols
        ).drop_duplicates()
        envo_mapping = envo_df.set_index(TYPE_COLUMN).T.to_dict()
        traits_columns_of_interest = [
            TAX_ID_COLUMN,
            ORG_NAME_COLUMN,
            METABOLISM_COLUMN,
            PATHWAYS_COLUMN,
            CARBON_SUBSTRATES_COLUMN,
            CELL_SHAPE_COLUMN,
            ISOLATION_SOURCE_COLUMN,
        ]

        with open(input_file, "r") as f, open(self.output_node_file, "w") as node, open(
            self.output_edge_file, "w"
        ) as edge:
            reader = csv.DictReader(f)
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)
            for line in reader:
                pathway_nodes = None
                carbon_substrate_nodes = None
                cell_shape_node = None
                isolation_source_node = None
                metabolism_node = None

                tax_pathway_edge = None
                tax_metabolism_edge = None
                tax_isolation_source_edge = None
                tax_carbon_substrate_edge = None
                tax_to_cell_shape_edge = None

                filtered_row = {k: line[k] for k in traits_columns_of_interest}
                tax_id = NCBITAXON_PREFIX + str(filtered_row[TAX_ID_COLUMN])
                tax_name = filtered_row[ORG_NAME_COLUMN]
                tax_node = [tax_id, NCBI_CATEGORY, tax_name]

                metabolism = metabolism_map.get(filtered_row[METABOLISM_COLUMN], None)
                if metabolism:
                    metabolism_node = [
                        metabolism[ID_COLUMN.upper()],
                        METABOLISM_CATEGORY,
                        PREFERRED_TERM_KEY,
                    ]
                    tax_metabolism_edge = [
                        tax_id,
                        NCBI_TO_METABOLISM_EDGE,
                        metabolism[ID_COLUMN.upper()],
                        BIOLOGICAL_PROCESS,
                    ]
                # Get these from NER results
                pathways = (
                    None
                    if filtered_row[PATHWAYS_COLUMN].split(",") == ["NA"]
                    else filtered_row[PATHWAYS_COLUMN].split(",")
                )
                if pathways:
                    go_condition_1 = go_result[TAX_ID_COLUMN] == tax_id
                    go_condition_2 = go_result[TRAITS_DATASET_LABEL_COLUMN].isin(pathways)
                    go_result_for_tax_id = go_result.loc[go_condition_1 & go_condition_2]
                    if go_result_for_tax_id.empty:
                        pathway_nodes = [
                            [PATHWAY_PREFIX + item.strip(), PATHWAY_CATEGORY, item.strip()]
                            for item in pathways
                        ]
                        tax_pathway_edge = [
                            [
                                tax_id,
                                NCBI_TO_PATHWAY_EDGE,
                                PATHWAY_PREFIX + item.strip(),
                                BIOLOGICAL_PROCESS,
                            ]
                            for item in pathways
                        ]
                    else:
                        exact_condition_go = (
                            go_result_for_tax_id[OBJECT_LABEL_COLUMN]
                            == go_result_for_tax_id[SUBJECT_LABEL_COLUMN]
                        )
                        exact_match_go_df = go_result_for_tax_id[exact_condition_go]
                        if not exact_match_go_df.empty:
                            go_result_for_tax_id = exact_match_go_df
                        pathway_nodes = []
                        tax_pathway_edge = []
                        for row in go_result_for_tax_id.iterrows():
                            pathway_nodes.append(
                                [row[1].object_id, PATHWAY_CATEGORY, row[1].object_label]
                            )
                            tax_pathway_edge.append(
                                [tax_id, NCBI_TO_PATHWAY_EDGE, row[1].object_id, BIOLOGICAL_PROCESS]
                            )

                    node_writer.writerows(pathway_nodes)
                    edge_writer.writerows(tax_pathway_edge)

                carbon_substrates = (
                    None
                    if filtered_row[CARBON_SUBSTRATES_COLUMN].split(",") == ["NA"]
                    else filtered_row[CARBON_SUBSTRATES_COLUMN].split(",")
                )
                if carbon_substrates:
                    chebi_condition_1 = chebi_result[TAX_ID_COLUMN] == tax_id
                    chebi_condition_2 = chebi_result[TRAITS_DATASET_LABEL_COLUMN].isin(
                        carbon_substrates
                    )
                    chebi_result_for_tax_id = chebi_result.loc[
                        chebi_condition_1 & chebi_condition_2
                    ]
                    if chebi_result_for_tax_id.empty:
                        carbon_substrate_nodes = [
                            [
                                CARBON_SUBSTRATE_PREFIX + item.strip(),
                                CARBON_SUBSTRATE_CATEGORY,
                                item.strip(),
                            ]
                            for item in carbon_substrates
                        ]
                        tax_carbon_substrate_edge = [
                            [
                                tax_id,
                                NCBI_TO_CHEM_EDGE,
                                CARBON_SUBSTRATE_PREFIX + item.strip(),
                                TROPHICALLY_INTERACTS_WITH,
                            ]
                            for item in carbon_substrates
                        ]
                    else:
                        carbon_substrate_nodes = []
                        tax_carbon_substrate_edge = []
                        exact_condition_chebi = (
                            chebi_result_for_tax_id[OBJECT_LABEL_COLUMN]
                            == chebi_result_for_tax_id[SUBJECT_LABEL_COLUMN]
                        )
                        exact_match_chebi_df = chebi_result_for_tax_id[exact_condition_chebi]
                        if not exact_match_chebi_df.empty:
                            chebi_result_for_tax_id = exact_match_chebi_df

                        for row in chebi_result_for_tax_id.iterrows():
                            carbon_substrate_nodes.append(
                                [row[1].object_id, PATHWAY_CATEGORY, row[1].object_label]
                            )
                            tax_carbon_substrate_edge.append(
                                [tax_id, NCBI_TO_PATHWAY_EDGE, row[1].object_id, BIOLOGICAL_PROCESS]
                            )

                    node_writer.writerows(carbon_substrate_nodes)
                    edge_writer.writerows(tax_carbon_substrate_edge)

                cell_shape = (
                    None
                    if filtered_row[CELL_SHAPE_COLUMN] == "NA"
                    else filtered_row[CELL_SHAPE_COLUMN]
                )
                if cell_shape:
                    cell_shape_node = [SHAPE_PREFIX + cell_shape, SHAPE_CATEGORY, cell_shape]
                    tax_to_cell_shape_edge = [
                        tax_id,
                        NCBI_TO_SHAPE_EDGE,
                        SHAPE_PREFIX + cell_shape,
                        HAS_PHENOTYPE,
                    ]
                # envo_df
                isolation_source = envo_mapping.get(filtered_row[ISOLATION_SOURCE_COLUMN], None)
                if isolation_source:
                    if isolation_source[ENVO_TERMS_COLUMN] is np.NAN:
                        isolation_source_node = [
                            ISOLATION_SOURCE_PREFIX + filtered_row[ISOLATION_SOURCE_COLUMN],
                            None,
                            filtered_row[ISOLATION_SOURCE_COLUMN],
                        ]
                        tax_isolation_source_edge = [
                            tax_id,
                            NCBI_TO_ISOLATION_SOURCE_EDGE,
                            ISOLATION_SOURCE_PREFIX + filtered_row[ISOLATION_SOURCE_COLUMN],
                            LOCATION_OF,
                        ]
                    else:
                        isolation_source_node = [
                            isolation_source[ENVO_ID_COLUMN],
                            None,
                            isolation_source[ENVO_TERMS_COLUMN],
                        ]
                        tax_isolation_source_edge = [
                            tax_id,
                            NCBI_TO_ISOLATION_SOURCE_EDGE,
                            isolation_source[ENVO_ID_COLUMN],
                            LOCATION_OF,
                        ]
                nodes_data_to_write = [
                    sublist
                    for sublist in [
                        tax_node,
                        cell_shape_node,
                        isolation_source_node,
                        metabolism_node,
                    ]
                    if sublist is not None
                ]
                node_writer.writerows(nodes_data_to_write)

                edges_data_to_write = [
                    sublist
                    for sublist in [
                        tax_isolation_source_edge,
                        tax_metabolism_edge,
                        tax_to_cell_shape_edge,
                    ]
                    if sublist is not None
                ]
                if len(edges_data_to_write) > 0:
                    edge_writer.writerows(edges_data_to_write)

        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
