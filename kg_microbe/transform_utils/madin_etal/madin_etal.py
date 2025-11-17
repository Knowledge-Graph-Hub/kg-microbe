"""Transform the Madin etal data from NCBI and GTDB."""

import csv
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
from oaklib import get_adapter
from oaklib.utilities.ner_utilities import get_exclusion_token_list
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS,
    CARBON_SUBSTRATE_CATEGORY,
    CARBON_SUBSTRATE_PREFIX,
    CARBON_SUBSTRATES_COLUMN,
    CELL_SHAPE_COLUMN,
    CHEBI_MANUAL_ANNOTATION_PATH,
    CHEBI_PREFIX,
    CHEBI_SOURCE,
    CHEBI_TO_ROLE_EDGE,
    ENVIRONMENT_CATEGORY,
    ENVO_ID_COLUMN,
    ENVO_TERMS_COLUMN,
    GO_PREFIX,
    GRAM_STAIN_COLUMN,
    HAS_PHENOTYPE,
    HAS_ROLE,
    ID_COLUMN,
    ISOLATION_SOURCE_COLUMN,
    ISOLATION_SOURCE_PREFIX,
    LOCATION_OF,
    MADIN_ETAL,
    METABOLISM_CATEGORY,
    METABOLISM_COLUMN,
    MOTILITY_COLUMN,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_CARBON_SUBSTRATE_EDGE,
    NCBI_TO_ISOLATION_SOURCE_EDGE,
    NCBI_TO_PATHWAY_EDGE,
    NCBI_TO_SHAPE_EDGE,
    NCBITAXON_PREFIX,
    OBJECT_ID_COLUMN,
    OBJECT_LABEL_COLUMN,
    ORG_NAME_COLUMN,
    PATHWAY_CATEGORY,
    PATHWAY_PREFIX,
    PATHWAYS_COLUMN,
    PHENOTYPIC_CATEGORY,
    RANGE_SALINITY_COLUMN,
    ROLE_CATEGORY,
    SHAPE_PREFIX,
    SPORULATION_COLUMN,
    SUBJECT_LABEL_COLUMN,
    TAX_ID_COLUMN,
    TRAITS_DATASET_LABEL_COLUMN,
    TROPHICALLY_INTERACTS_WITH,
    TYPE_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings, uri_to_curie
from kg_microbe.utils.ner_utils import annotate
from kg_microbe.utils.pandas_utils import drop_duplicates

OUTPUT_FILE_SUFFIX = "_ner.tsv"
STOPWORDS_FN = "stopwords.txt"
PARENT_DIR = Path(__file__).resolve().parent


class MadinEtAlTransform(Transform):

    """
    Ingest Madin et al dataset (NCBI/GTDB).

    Essentially just ingests and transforms this file:
    https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/output/condensed_traits_NCBI.csv
    And extracts the following columns:
        - tax_id
        - org_name
        - metabolism
        - pathways
        - carbon_substrates
        - cell_shape
        - range_salinity
        - motility
        - gram_stain
        - sporulation
        - isolation_source
    Also implements:
        -   OAK to run NLP via the 'ner_utils' module and
        -   ROBOT using 'robot_utils' module.
    """

    def __init__(self, input_dir: str, output_dir: str, nlp=True) -> None:
        """
        Initialize MadinEtAlTransform Class.

        :param input_dir: Input file path (str)
        :param output_dir: Output file path (str)
        """
        source_name = MADIN_ETAL
        super().__init__(source_name, input_dir, output_dir, nlp)  # set some variables
        self.nlp = nlp
        self.madin_metpo_mappings = load_metpo_mappings("madin synonym or field")
        self.environments_file = self.input_base_dir / "environments.csv"

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """
        Call method and perform needed transformations for trait data (NCBI/GTDB).

        :param data_file: Input file name.
        """
        if data_file is None:
            data_file = self.source_name + ".csv"
        input_file = self.input_base_dir / data_file
        cols_for_nlp = [PATHWAYS_COLUMN, CARBON_SUBSTRATES_COLUMN]
        nlp_df = pd.read_csv(input_file, usecols=cols_for_nlp, low_memory=False)
        # nlp_df[TAX_ID_COLUMN] = nlp_df[TAX_ID_COLUMN].apply(lambda x: NCBITAXON_PREFIX + str(x))
        chebi_nlp_df = nlp_df[[CARBON_SUBSTRATES_COLUMN]].dropna()
        go_nlp_df = nlp_df[[PATHWAYS_COLUMN]].dropna()
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
                CHEBI_MANUAL_ANNOTATION_PATH,
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
        chebi_list = chebi_result[OBJECT_ID_COLUMN].to_list()
        oi = get_adapter(f"sqlite:{CHEBI_SOURCE}")
        chebi_roles = set(oi.relationships(subjects=set(chebi_list), predicates=[HAS_ROLE]))
        roles = {x for (_, _, x) in chebi_roles}
        role_nodes = [[role, ROLE_CATEGORY, oi.label(role)] for role in roles]
        role_edges = [
            [
                subject,
                CHEBI_TO_ROLE_EDGE,
                object,
                predicate,
            ]
            for (subject, predicate, object) in chebi_roles
        ]

        if not (self.nlp_output_dir / go_result_fn).is_file():
            annotate(
                go_nlp_df,
                GO_PREFIX,
                exclusion_list,
                self.nlp_output_dir / go_result_fn,
                False,
                None,
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
            RANGE_SALINITY_COLUMN,
            MOTILITY_COLUMN,
            GRAM_STAIN_COLUMN,
            SPORULATION_COLUMN,
            ISOLATION_SOURCE_COLUMN,
        ]
        with open(input_file, "r") as f:
            total_lines = sum(1 for line in f)

        with (
            open(input_file, "r") as f,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            reader = csv.DictReader(f)
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            node_writer.writerows(role_nodes)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)
            edge_writer.writerows(role_edges)

            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(total=total_lines, desc="Processing files") as progress:
                for line in reader:
                    pathway_nodes = None
                    carbon_substrate_nodes = None
                    cell_shape_node = None
                    range_salinity_node = None
                    motility_node = None
                    gram_stain_node = None
                    sporulation_node = None
                    isolation_source_node = None
                    metabolism_node = None

                    tax_pathway_edge = None
                    tax_metabolism_edge = None
                    tax_isolation_source_edge = None
                    tax_carbon_substrate_edge = None
                    tax_to_cell_shape_edge = None
                    tax_to_range_salinity_edge = None
                    tax_to_motility_edge = None
                    tax_to_gram_stain_edge = None
                    tax_to_sporulation_edge = None

                    filtered_row = {k: line[k] for k in traits_columns_of_interest}
                    tax_id = NCBITAXON_PREFIX + str(filtered_row[TAX_ID_COLUMN])
                    tax_name = filtered_row[ORG_NAME_COLUMN]
                    tax_node = [tax_id, NCBI_CATEGORY, tax_name]

                    # block handling "metabolism" column from Madin etal dataset/CSV sheet
                    metabolism = self.madin_metpo_mappings.get(
                        filtered_row[METABOLISM_COLUMN], None
                    )
                    if metabolism:
                        # create metabolism node and edge to tax_id
                        # use biolink_equivalent URL from METPO tree traversal or fallback to default
                        category = uri_to_curie(metabolism.get("inferred_category", METABOLISM_CATEGORY))
                        predicate_biolink = metabolism.get("predicate_biolink_equivalent", "")
                        # fallback: if no biolink equivalent use `biolink:has_phenotype`
                        if predicate_biolink:
                            predicate = uri_to_curie(predicate_biolink)
                        else:
                            predicate = "biolink:has_phenotype"
                        metabolism_node = [
                            metabolism["curie"],
                            category,
                            metabolism["label"],
                        ]
                        tax_metabolism_edge = [
                            tax_id,
                            predicate,
                            metabolism["curie"],
                            BIOLOGICAL_PROCESS,
                        ]

                    # block handling "pathways" column from Madin etal dataset/CSV sheet
                    # Get these from NER results
                    pathways = (
                        None
                        if filtered_row[PATHWAYS_COLUMN].split(",") == ["NA"]
                        else [
                            pathway.strip() for pathway in filtered_row[PATHWAYS_COLUMN].split(",")
                        ]
                    )
                    if pathways:
                        pathway_nodes = []
                        tax_pathway_edge = []

                        # First try to find mappings in METPO
                        pathways_not_in_metpo = []
                        for pathway in pathways:
                            metpo_mapping = self.madin_metpo_mappings.get(pathway.strip(), None)
                            # print(f"Pathway: {pathway}, METPO mapping: {metpo_mapping}")
                            if metpo_mapping:
                                # create pathway node and edge to tax_id
                                # use biolink_equivalent URL from METPO tree traversal or fallback to default
                                category = uri_to_curie(metpo_mapping.get("inferred_category", PATHWAY_CATEGORY))
                                predicate_biolink = metpo_mapping.get(
                                    "predicate_biolink_equivalent", ""
                                )
                                # fallback: if no biolink equivalent use `biolink:capable_of`
                                if predicate_biolink:
                                    predicate = uri_to_curie(predicate_biolink)
                                else:
                                    predicate = "biolink:capable_of"
                                pathway_nodes.append(
                                    [
                                        metpo_mapping["curie"],
                                        category,
                                        metpo_mapping["label"],
                                    ]
                                )
                                tax_pathway_edge.append(
                                    [
                                        tax_id,
                                        predicate,
                                        metpo_mapping["curie"],
                                        BIOLOGICAL_PROCESS,
                                    ]
                                )
                            else:
                                pathways_not_in_metpo.append(pathway)

                        # For pathways not found in METPO, fall back to NER results
                        if pathways_not_in_metpo:
                            go_condition = go_result[TRAITS_DATASET_LABEL_COLUMN].isin(
                                pathways_not_in_metpo
                            )
                            go_result_for_tax_id = go_result.loc[go_condition]
                            if go_result_for_tax_id.empty:
                                # Use fallback naming if no NER results
                                for item in pathways_not_in_metpo:
                                    pathway_nodes.append(
                                        [
                                            PATHWAY_PREFIX + item.strip(),
                                            PATHWAY_CATEGORY,
                                            item.strip(),
                                        ]
                                    )
                                    tax_pathway_edge.append(
                                        [
                                            tax_id,
                                            NCBI_TO_PATHWAY_EDGE,
                                            PATHWAY_PREFIX + item.strip().lower(),
                                            BIOLOGICAL_PROCESS,
                                        ]
                                    )
                            else:
                                exact_condition_go = (
                                    go_result_for_tax_id[OBJECT_LABEL_COLUMN]
                                    == go_result_for_tax_id[SUBJECT_LABEL_COLUMN]
                                )
                                exact_match_go_df = go_result_for_tax_id[exact_condition_go]
                                if not exact_match_go_df.empty:
                                    go_result_for_tax_id = exact_match_go_df
                                for row in go_result_for_tax_id.iterrows():
                                    pathway_nodes.append(
                                        [row[1].object_id, PATHWAY_CATEGORY, row[1].object_label]
                                    )
                                    tax_pathway_edge.append(
                                        [
                                            tax_id,
                                            NCBI_TO_PATHWAY_EDGE,
                                            row[1].object_id,
                                            BIOLOGICAL_PROCESS,
                                        ]
                                    )

                        node_writer.writerows(pathway_nodes)
                        edge_writer.writerows(tax_pathway_edge)

                    # block handling "carbon substrates" column from Madin etal dataset/CSV sheet
                    carbon_substrates = (
                        None
                        if filtered_row[CARBON_SUBSTRATES_COLUMN].split(",") == ["NA"]
                        else [
                            substrate.strip()
                            for substrate in filtered_row[CARBON_SUBSTRATES_COLUMN].split(",")
                        ]
                    )

                    if carbon_substrates:
                        carbon_substrate_nodes = []
                        tax_carbon_substrate_edge = []

                        # First try to find mappings in METPO
                        carbon_substrates_not_in_metpo = []
                        for substrate in carbon_substrates:
                            metpo_mapping = self.madin_metpo_mappings.get(substrate.strip(), None)
                            # print(f"Substrate: {substrate}, METPO mapping: {metpo_mapping}")
                            if metpo_mapping:
                                # create carbon substrate node and edge to tax_id
                                # use biolink_equivalent URL from METPO tree traversal or fallback to default
                                category = uri_to_curie(metpo_mapping.get(
                                    "inferred_category", CARBON_SUBSTRATE_CATEGORY
                                ))
                                predicate_biolink = metpo_mapping.get(
                                    "predicate_biolink_equivalent", ""
                                )
                                # fallback: if no biolink equivalent use `biolink:consumes`
                                if predicate_biolink:
                                    predicate = uri_to_curie(predicate_biolink)
                                else:
                                    predicate = "biolink:consumes"
                                carbon_substrate_nodes.append(
                                    [
                                        metpo_mapping["curie"],
                                        category,
                                        metpo_mapping["label"],
                                    ]
                                )
                                tax_carbon_substrate_edge.append(
                                    [
                                        tax_id,
                                        predicate,
                                        metpo_mapping["curie"],
                                        TROPHICALLY_INTERACTS_WITH,
                                    ]
                                )
                            else:
                                carbon_substrates_not_in_metpo.append(substrate)

                        # For carbon substrates not found in METPO, fall back to ChEBI NER results
                        if carbon_substrates_not_in_metpo:
                            chebi_condition = chebi_result[TRAITS_DATASET_LABEL_COLUMN].isin(
                                carbon_substrates_not_in_metpo
                            )
                            chebi_result_for_tax_id = chebi_result.loc[chebi_condition]
                            if chebi_result_for_tax_id.empty:
                                # Use fallback naming if no NER results
                                for item in carbon_substrates_not_in_metpo:
                                    carbon_substrate_nodes.append(
                                        [
                                            CARBON_SUBSTRATE_PREFIX + item.strip(),
                                            CARBON_SUBSTRATE_CATEGORY,
                                            item.strip(),
                                        ]
                                    )
                                    tax_carbon_substrate_edge.append(
                                        [
                                            tax_id,
                                            NCBI_TO_CARBON_SUBSTRATE_EDGE,
                                            CARBON_SUBSTRATE_PREFIX + item.strip(),
                                            TROPHICALLY_INTERACTS_WITH,
                                        ]
                                    )
                            else:
                                exact_condition_chebi = (
                                    chebi_result_for_tax_id[OBJECT_LABEL_COLUMN]
                                    == chebi_result_for_tax_id[SUBJECT_LABEL_COLUMN]
                                )
                                exact_match_chebi_df = chebi_result_for_tax_id[
                                    exact_condition_chebi
                                ]
                                if not exact_match_chebi_df.empty:
                                    chebi_result_for_tax_id = exact_match_chebi_df
                                for row in chebi_result_for_tax_id.iterrows():
                                    carbon_substrate_nodes.append(
                                        [
                                            row[1].object_id,
                                            CARBON_SUBSTRATE_CATEGORY,
                                            row[1].object_label,
                                        ]
                                    )
                                    tax_carbon_substrate_edge.append(
                                        [
                                            tax_id,
                                            NCBI_TO_CARBON_SUBSTRATE_EDGE,
                                            row[1].object_id,
                                            BIOLOGICAL_PROCESS,
                                        ]
                                    )

                        node_writer.writerows(carbon_substrate_nodes)
                        edge_writer.writerows(tax_carbon_substrate_edge)

                    # block handling "cell shape" column from Madin etal dataset/CSV sheet
                    cell_shape = (
                        None
                        if filtered_row[CELL_SHAPE_COLUMN] == "NA"
                        else filtered_row[CELL_SHAPE_COLUMN]
                    )
                    if cell_shape:
                        # First try to find mapping in METPO
                        metpo_mapping = self.madin_metpo_mappings.get(cell_shape.strip(), None)
                        # print(f"Cell shape: {cell_shape}, METPO mapping: {metpo_mapping}")
                        if metpo_mapping:
                            # create cell shape node and edge to tax_id
                            # use biolink_equivalent URL from METPO tree traversal or fallback to default
                            category = uri_to_curie(metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY))
                            predicate_biolink = metpo_mapping.get(
                                "predicate_biolink_equivalent", ""
                            )
                            # fallback: if no biolink equivalent use `biolink:has_phenotype`
                            if predicate_biolink:
                                predicate = uri_to_curie(predicate_biolink)
                            else:
                                predicate = "biolink:has_phenotype"
                            cell_shape_node = [
                                metpo_mapping["curie"],
                                category,
                                metpo_mapping["label"],
                            ]
                            tax_to_cell_shape_edge = [
                                tax_id,
                                predicate,
                                metpo_mapping["curie"],
                                HAS_PHENOTYPE,
                            ]
                        else:
                            # Fall back to original logic
                            cell_shape_node = [
                                SHAPE_PREFIX + cell_shape,
                                PHENOTYPIC_CATEGORY,
                                cell_shape,
                            ]
                            tax_to_cell_shape_edge = [
                                tax_id,
                                NCBI_TO_SHAPE_EDGE,
                                SHAPE_PREFIX + cell_shape,
                                HAS_PHENOTYPE,
                            ]

                    # block handling "range_salinity" column from Madin etal dataset/CSV sheet
                    range_salinity = (
                        None
                        if filtered_row[RANGE_SALINITY_COLUMN] == "NA"
                        else filtered_row[RANGE_SALINITY_COLUMN]
                    )
                    if range_salinity:
                        # Try to find mapping in METPO
                        metpo_mapping = self.madin_metpo_mappings.get(range_salinity.strip(), None)
                        if metpo_mapping:
                            # create range_salinity node and edge to tax_id
                            # use biolink_equivalent URL from METPO tree traversal or fallback to default
                            category = uri_to_curie(metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY))
                            predicate_biolink = metpo_mapping.get(
                                "predicate_biolink_equivalent", ""
                            )
                            # fallback: if no biolink equivalent use `biolink:has_phenotype`
                            if predicate_biolink:
                                predicate = uri_to_curie(predicate_biolink)
                            else:
                                predicate = "biolink:has_phenotype"
                            range_salinity_node = [
                                metpo_mapping["curie"],
                                category,
                                metpo_mapping["label"],
                            ]
                            tax_to_range_salinity_edge = [
                                tax_id,
                                predicate,
                                metpo_mapping["curie"],
                                HAS_PHENOTYPE,
                            ]

                    # block handling "motility" column from Madin etal dataset/CSV sheet
                    motility = (
                        None
                        if filtered_row[MOTILITY_COLUMN] == "NA"
                        else filtered_row[MOTILITY_COLUMN]
                    )
                    if motility:
                        # Try to find mapping in METPO using compound key first, then simple key
                        compound_key = f"motility.{motility.strip()}"
                        metpo_mapping = self.madin_metpo_mappings.get(
                            compound_key,
                            self.madin_metpo_mappings.get(motility.strip(), None)
                        )
                        if metpo_mapping:
                            # create motility node and edge to tax_id
                            # use biolink_equivalent URL from METPO tree traversal or fallback to default
                            category = uri_to_curie(metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY))
                            predicate_biolink = metpo_mapping.get(
                                "predicate_biolink_equivalent", ""
                            )
                            # fallback: if no biolink equivalent use `biolink:has_phenotype`
                            if predicate_biolink:
                                predicate = uri_to_curie(predicate_biolink)
                            else:
                                predicate = "biolink:has_phenotype"
                            motility_node = [
                                metpo_mapping["curie"],
                                category,
                                metpo_mapping["label"],
                            ]
                            tax_to_motility_edge = [
                                tax_id,
                                predicate,
                                metpo_mapping["curie"],
                                HAS_PHENOTYPE,
                            ]

                    # block handling "gram_stain" column from Madin etal dataset/CSV sheet
                    gram_stain = (
                        None
                        if filtered_row[GRAM_STAIN_COLUMN] == "NA"
                        else filtered_row[GRAM_STAIN_COLUMN]
                    )
                    if gram_stain:
                        # Try to find mapping in METPO
                        metpo_mapping = self.madin_metpo_mappings.get(gram_stain.strip(), None)
                        if metpo_mapping:
                            # create gram_stain node and edge to tax_id
                            # use biolink_equivalent URL from METPO tree traversal or fallback to default
                            category = uri_to_curie(metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY))
                            predicate_biolink = metpo_mapping.get(
                                "predicate_biolink_equivalent", ""
                            )
                            # fallback: if no biolink equivalent use `biolink:has_phenotype`
                            if predicate_biolink:
                                predicate = uri_to_curie(predicate_biolink)
                            else:
                                predicate = "biolink:has_phenotype"
                            gram_stain_node = [
                                metpo_mapping["curie"],
                                category,
                                metpo_mapping["label"],
                            ]
                            tax_to_gram_stain_edge = [
                                tax_id,
                                predicate,
                                metpo_mapping["curie"],
                                HAS_PHENOTYPE,
                            ]

                    # block handling "sporulation" column from Madin etal dataset/CSV sheet
                    sporulation = (
                        None
                        if filtered_row[SPORULATION_COLUMN] == "NA"
                        else filtered_row[SPORULATION_COLUMN]
                    )
                    if sporulation:
                        # Try to find mapping in METPO using compound key first, then simple key
                        compound_key = f"sporulation.{sporulation.strip()}"
                        metpo_mapping = self.madin_metpo_mappings.get(
                            compound_key,
                            self.madin_metpo_mappings.get(sporulation.strip(), None)
                        )
                        if metpo_mapping:
                            # create sporulation node and edge to tax_id
                            # use biolink_equivalent URL from METPO tree traversal or fallback to default
                            category = uri_to_curie(metpo_mapping.get("inferred_category", PHENOTYPIC_CATEGORY))
                            predicate_biolink = metpo_mapping.get(
                                "predicate_biolink_equivalent", ""
                            )
                            # fallback: if no biolink equivalent use `biolink:has_phenotype`
                            if predicate_biolink:
                                predicate = uri_to_curie(predicate_biolink)
                            else:
                                predicate = "biolink:has_phenotype"
                            sporulation_node = [
                                metpo_mapping["curie"],
                                category,
                                metpo_mapping["label"],
                            ]
                            tax_to_sporulation_edge = [
                                tax_id,
                                predicate,
                                metpo_mapping["curie"],
                                HAS_PHENOTYPE,
                            ]

                    # envo_df
                    isolation_source = envo_mapping.get(filtered_row[ISOLATION_SOURCE_COLUMN], None)
                    if isolation_source:
                        if isolation_source[ENVO_TERMS_COLUMN] is np.NAN:
                            isolation_source_node = [
                                [
                                    ISOLATION_SOURCE_PREFIX + filtered_row[ISOLATION_SOURCE_COLUMN],
                                    None,
                                    filtered_row[ISOLATION_SOURCE_COLUMN],
                                ]
                            ]
                            tax_isolation_source_edge = [
                                [
                                    ISOLATION_SOURCE_PREFIX + filtered_row[ISOLATION_SOURCE_COLUMN],
                                    NCBI_TO_ISOLATION_SOURCE_EDGE,
                                    tax_id,
                                    LOCATION_OF,
                                ]
                            ]
                        else:
                            if "," in isolation_source[ENVO_ID_COLUMN]:
                                curies = [
                                    x.strip() for x in isolation_source[ENVO_ID_COLUMN].split(",")
                                ]
                                labels = [
                                    x.strip()
                                    for x in isolation_source[ENVO_TERMS_COLUMN].split(",")
                                ]
                                if len(labels) == 1 and len(labels) != len(curies):
                                    labels = [labels[0] for _ in range(len(curies))]
                                category = [ENVIRONMENT_CATEGORY for _ in range(len(curies))]
                                preds = [NCBI_TO_ISOLATION_SOURCE_EDGE for _ in range(len(curies))]
                                relations = [LOCATION_OF for _ in range(len(curies))]
                                isolation_source_node = [
                                    list(item) for item in zip(curies, category, labels)  # noqa
                                ]
                                tax_id_list = [tax_id for _ in range(len(labels))]

                                tax_isolation_source_edge = [
                                    list(item)
                                    for item in zip(curies, preds, tax_id_list, relations)  # noqa
                                ]
                            else:
                                isolation_source_node = [
                                    [
                                        isolation_source[ENVO_ID_COLUMN],
                                        ENVIRONMENT_CATEGORY,
                                        isolation_source[ENVO_TERMS_COLUMN],
                                    ]
                                ]
                                tax_isolation_source_edge = [
                                    [
                                        isolation_source[ENVO_ID_COLUMN],
                                        NCBI_TO_ISOLATION_SOURCE_EDGE,
                                        tax_id,
                                        LOCATION_OF,
                                    ]
                                ]
                    nodes_data_to_write = [
                        sublist
                        for sublist in [
                            tax_node,
                            cell_shape_node,
                            range_salinity_node,
                            motility_node,
                            gram_stain_node,
                            sporulation_node,
                            metabolism_node,
                        ]
                        if sublist is not None
                    ]
                    node_writer.writerows(nodes_data_to_write)
                    if isolation_source_node:
                        node_writer.writerows(isolation_source_node)

                    edges_data_to_write = [
                        sublist
                        for sublist in [
                            tax_metabolism_edge,
                            tax_to_cell_shape_edge,
                            tax_to_range_salinity_edge,
                            tax_to_motility_edge,
                            tax_to_gram_stain_edge,
                            tax_to_sporulation_edge,
                        ]
                        if sublist is not None
                    ]
                    if len(edges_data_to_write) > 0:
                        edge_writer.writerows(edges_data_to_write)
                    if tax_isolation_source_edge:
                        edge_writer.writerows(tax_isolation_source_edge)

                    progress.set_description(f"Processing taxonomy: {tax_id}")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(self.output_node_file, consolidation_columns=[ID_COLUMN, NAME_COLUMN])
        drop_duplicates(self.output_edge_file, consolidation_columns=[OBJECT_ID_COLUMN])
        # dump_ont_nodes_from(
        #     self.output_node_file, self.input_base_dir / CHEBI_NODES_FILENAME, CHEBI_PREFIX
        # )
