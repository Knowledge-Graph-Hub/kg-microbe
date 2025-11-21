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
    HAS_PHENOTYPE,
    HAS_ROLE,
    ID_COLUMN,
    ISOLATION_SOURCE_COLUMN,
    ISOLATION_SOURCE_PREFIX,
    LOCATION_OF,
    MADIN_ETAL,
    METABOLISM_CATEGORY,
    METABOLISM_COLUMN,
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
    RANGE_TMP_COLUMN,
    ROLE_CATEGORY,
    SHAPE_PREFIX,
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
        Initialize MadinEtAlTransform Class.

        :param input_dir: Input file path (str)
        :param output_dir: Output file path (str)
        :param nlp: Whether to use NLP for named entity recognition (default: True)
        """
        source_name = MADIN_ETAL
        # Initialize parent Transform class with source info and directories
        super().__init__(source_name, input_dir, output_dir, nlp)
        self.nlp = nlp
        # Load METPO (Microbial Ecology Traits and Phenotypes Ontology) mappings for standardization
        self.madin_metpo_mappings = load_metpo_mappings("madin synonym or field")
        # Path to environments data file for ENVO (Environment Ontology) mapping
        self.environments_file = self.input_base_dir / "environments.csv"

    def _get_metpo_node_and_edge(
        self,
        trait_value: str,
        tax_id: str,
        default_category: str,
        default_predicate: str,
        default_relation: str,
    ) -> tuple:
        """
        Create node and edge using METPO mapping if available.

        :param trait_value: The trait value to map
        :param tax_id: Organism taxonomy ID
        :param default_category: Default category if no METPO mapping
        :param default_predicate: Default predicate if no Biolink equivalent
        :param default_relation: Relation type for edge
        :return: Tuple of (node, edge) or (None, None) if no mapping
        """
        metpo_mapping = self.madin_metpo_mappings.get(trait_value.strip(), None)
        if not metpo_mapping:
            return None, None

        # Extract category from METPO or use default
        category = uri_to_curie(metpo_mapping.get("inferred_category", default_category))
        # Look more into this 
        predicate_biolink = metpo_mapping.get("predicate_biolink_equivalent", "")

        # Use Biolink predicate if available, otherwise use default
        if predicate_biolink:
            predicate = uri_to_curie(predicate_biolink)
        else:
            predicate = default_predicate #fallback

        node = [metpo_mapping["curie"], category, metpo_mapping["label"]]
        edge = [tax_id, predicate, metpo_mapping["curie"], default_relation]

        return node, edge

    def _process_isolation_source(
        self, isolation_source_value: str, tax_id: str, envo_mapping: dict
    ) -> tuple:
        """
        Process isolation source and map to ENVO terms.

        :param isolation_source_value: The isolation source text
        :param tax_id: Organism taxonomy ID
        :param envo_mapping: Dictionary mapping isolation sources to ENVO terms
        :return: Tuple of (isolation_source_nodes, isolation_source_edges)
        """
        isolation_source = envo_mapping.get(isolation_source_value, None)
        if not isolation_source:
            return None, None

        # Check if ENVO mapping exists
        if isolation_source[ENVO_TERMS_COLUMN] is np.NAN:
            # No ENVO mapping, create custom node
            nodes = [
                [
                    ISOLATION_SOURCE_PREFIX + isolation_source_value,
                    None,
                    isolation_source_value,
                ]
            ]
            edges = [
                [
                    ISOLATION_SOURCE_PREFIX + isolation_source_value,
                    NCBI_TO_ISOLATION_SOURCE_EDGE,
                    tax_id,
                    LOCATION_OF,
                ]
            ]
        else:
            # Handle multiple ENVO terms (comma-separated)
            if "," in isolation_source[ENVO_ID_COLUMN]:
                curies = [x.strip() for x in isolation_source[ENVO_ID_COLUMN].split(",")]
                labels = [x.strip() for x in isolation_source[ENVO_TERMS_COLUMN].split(",")]

                # Handle case where one label applies to multiple CURIEs
                if len(labels) == 1 and len(labels) != len(curies):
                    labels = [labels[0] for _ in range(len(curies))]

                # Create multiple environment nodes
                nodes = [
                    [curie, ENVIRONMENT_CATEGORY, label]
                    for curie, label in zip(curies, labels, strict=False)
                ]
                # Create multiple edges: environment -> location_of -> organism
                edges = [
                    [curie, NCBI_TO_ISOLATION_SOURCE_EDGE, tax_id, LOCATION_OF]
                    for curie in curies
                ]
            else:
                # Single ENVO term mapping
                nodes = [
                    [
                        isolation_source[ENVO_ID_COLUMN],
                        ENVIRONMENT_CATEGORY,
                        isolation_source[ENVO_TERMS_COLUMN],
                    ]
                ]
                edges = [
                    [
                        isolation_source[ENVO_ID_COLUMN],
                        NCBI_TO_ISOLATION_SOURCE_EDGE,
                        tax_id,
                        LOCATION_OF,
                    ]
                ]

        return nodes, edges

    def _process_ner_fallback(
        self,
        items_to_process: list,
        ner_results: pd.DataFrame,
        tax_id: str,
        column_name: str,
        category: str,
        prefix: str,
        edge_type: str,
        relation: str,
    ) -> tuple:
        """
        Process items using NER results as fallback when METPO mapping not found.

        :param items_to_process: List of items that need NER mapping
        :param ner_results: DataFrame with NER results
        :param tax_id: Organism taxonomy ID
        :param column_name: Column name being processed
        :param category: Node category
        :param prefix: Prefix for custom node IDs
        :param edge_type: Edge type/predicate
        :param relation: Relation type for edge
        :return: Tuple of (nodes, edges)
        """
        nodes = []
        edges = []

        # Filter NER results to items in this organism's data
        condition = ner_results[TRAITS_DATASET_LABEL_COLUMN].isin(items_to_process)
        filtered_results = ner_results.loc[condition]

        if filtered_results.empty:
            # No NER results found, use custom naming scheme
            for item in items_to_process:
                nodes.append([prefix + item.strip(), category, item.strip()])
                edges.append([tax_id, edge_type, prefix + item.strip().lower(), relation])
        else:
            # Prefer exact matches between input text and ontology term label
            filtered_results = self._filter_ner_results_exact_match(filtered_results)

            # Create nodes and edges for NER-annotated items
            for row in filtered_results.iterrows():
                nodes.append([row[1].object_id, category, row[1].object_label])
                edges.append([tax_id, edge_type, row[1].object_id, relation])

        return nodes, edges

    def _parse_comma_separated_values(self, value: str, na_value: str = "NA") -> list:
        """
        Parse comma-separated values from a cell, handling NA values.

        :param value: The cell value to parse
        :param na_value: String representing NA/missing values
        :return: List of parsed values or None if all NA
        """
        if not value or value == na_value:
            return None

        values = value.split(",")
        if values == [na_value]:
            return None

        return [v.strip() for v in values]

    def _filter_ner_results_exact_match(self, ner_results: pd.DataFrame) -> pd.DataFrame:
        """
        Filter NER results to prefer exact matches between input and output labels.

        :param ner_results: DataFrame with NER results
        :return: Filtered DataFrame with exact matches if available
        """
        exact_condition = (
            ner_results[OBJECT_LABEL_COLUMN] == ner_results[SUBJECT_LABEL_COLUMN]
        )
        exact_match_df = ner_results[exact_condition]

        if not exact_match_df.empty:
            return exact_match_df
        return ner_results

    def _perform_ner_if_needed(
        self,
        data_df: pd.DataFrame,
        prefix: str,
        output_filename: str,
        exclusion_list: list,
        manual_annotation_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Perform NER on data if results don't already exist (caching).

        :param data_df: DataFrame with data to annotate
        :param prefix: Ontology prefix (e.g., "CHEBI:", "GO:")
        :param output_filename: Output filename for NER results
        :param exclusion_list: List of words to exclude from NER
        :param manual_annotation_path: Optional path to manual annotations
        :return: DataFrame with NER results
        """
        output_path = self.nlp_output_dir / output_filename

        if not output_path.is_file():
            # Run NLP to identify entities
            annotate(
                data_df,
                prefix,
                exclusion_list,
                output_path,
                False,
                manual_annotation_path,
            )
            # Load and deduplicate results
            result = pd.read_csv(str(output_path), sep="\t", low_memory=False)
            result = result.drop_duplicates()
            result.to_csv(str(output_path), sep="\t", index=False)
        else:
            # Load cached results
            result = pd.read_csv(str(output_path), sep="\t", low_memory=False)

        return result

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """
        Call method and perform needed transformations for trait data (NCBI/GTDB).

        :param data_file: Input file name (defaults to source_name + ".csv")
        :param show_status: Whether to show progress bars during processing
        """
        # Use default filename if none provided
        if data_file is None:
            data_file = self.source_name + ".csv"
        input_file = self.input_base_dir / data_file

        # Define which columns need NLP processing for entity recognition
        cols_for_nlp = [PATHWAYS_COLUMN, CARBON_SUBSTRATES_COLUMN]
        # Load only the columns that need NLP processing to save memory
        nlp_df = pd.read_csv(input_file, usecols=cols_for_nlp, low_memory=False)
        # nlp_df[TAX_ID_COLUMN] = nlp_df[TAX_ID_COLUMN].apply(lambda x: NCBITAXON_PREFIX + str(x))
        # Separate carbon substrates (chemicals) from pathways (biological processes)
        chebi_nlp_df = nlp_df[[CARBON_SUBSTRATES_COLUMN]].dropna()
        go_nlp_df = nlp_df[[PATHWAYS_COLUMN]].dropna()

        # Build list of words to exclude from NER (common words, stopwords)
        exclusion_list = get_exclusion_token_list([self.nlp_stopwords_dir / STOPWORDS_FN])

        # Generate output filenames for NER results
        go_result_fn = GO_PREFIX.strip(":").lower() + OUTPUT_FILE_SUFFIX  # "go_ner.tsv"
        chebi_result_fn = CHEBI_PREFIX.strip(":").lower() + OUTPUT_FILE_SUFFIX  # "chebi_ner.tsv"

        # Perform ChEBI NER for carbon substrates
        chebi_result = self._perform_ner_if_needed(
            chebi_nlp_df,
            CHEBI_PREFIX,
            chebi_result_fn,
            exclusion_list,
            CHEBI_MANUAL_ANNOTATION_PATH
        )
        # Extract chemical roles from ChEBI ontology
        # For example, "glucose" (CHEBI:17234) has_role "nutrient" (CHEBI:33284)
        chebi_list = chebi_result[OBJECT_ID_COLUMN].to_list()
        oi = get_adapter(f"sqlite:{CHEBI_SOURCE}")  # Connect to ChEBI database
        # Query ontology for all "has_role" relationships for identified chemicals
        chebi_roles = set(oi.relationships(subjects=set(chebi_list), predicates=[HAS_ROLE]))
        # Extract unique role IDs from relationships
        roles = {x for (_, _, x) in chebi_roles}
        # Create nodes for each role (e.g., "nutrient", "carbon source")
        role_nodes = [[role, ROLE_CATEGORY, oi.label(role)] for role in roles]
        # Create edges connecting chemicals to their roles
        role_edges = [
            [
                subject,  # Chemical ChEBI ID
                CHEBI_TO_ROLE_EDGE,
                object,  # Role ChEBI ID
                predicate,  # Relationship type (has_role)
            ]
            for (subject, predicate, object) in chebi_roles
        ]

        # Perform GO NER for pathways
        go_result = self._perform_ner_if_needed(
            go_nlp_df,
            GO_PREFIX,
            go_result_fn,
            exclusion_list,
            None  # No manual annotations for GO
        )

        # Load environment mappings from ENVO (Environment Ontology)
        # Maps free text like "soil" to standardized ENVO terms
        envo_cols = [TYPE_COLUMN, ENVO_TERMS_COLUMN, ENVO_ID_COLUMN]
        envo_df = pd.read_csv(
            self.environments_file, low_memory=False, usecols=envo_cols
        ).drop_duplicates()
        # Convert to dictionary for fast lookup: environment_type -> {ENVO_ID, ENVO_term}
        envo_mapping = envo_df.set_index(TYPE_COLUMN).T.to_dict()

        # Define which trait columns to extract from the main dataset
        traits_columns_of_interest = [
            TAX_ID_COLUMN,              # Organism NCBI taxonomy ID
            ORG_NAME_COLUMN,            # Organism name
            METABOLISM_COLUMN,          # Metabolic type (aerobe/anaerobe)
            PATHWAYS_COLUMN,            # Biological pathways
            CARBON_SUBSTRATES_COLUMN,   # Carbon sources used
            CELL_SHAPE_COLUMN,          # Morphology (rod/cocci)
            ISOLATION_SOURCE_COLUMN,    # Where organism was found
        ]
        # Count total lines for progress bar
        with open(input_file, "r") as f:
            total_lines = sum(1 for line in f)

        # Open input data file and output KG files simultaneously
        with (
            open(input_file, "r") as f,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            reader = csv.DictReader(f)  # Read CSV as dictionary (column name -> value)
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)  # Write node file header
            node_writer.writerows(role_nodes)  # Write chemical role nodes first
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)  # Write edge file header
            edge_writer.writerows(role_edges)  # Write chemical-to-role edges first

            # Choose progress bar implementation based on show_status flag
            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(total=total_lines, desc="Processing files") as progress:
                # Process each organism (row) in the dataset
                for line in reader:
                    # Initialize variables for this organism's trait nodes and edges
                    pathway_nodes = None
                    carbon_substrate_nodes = None
                    cell_shape_node = None
                    range_tmp_nodes = None
                    isolation_source_node = None
                    metabolism_node = None

                    tax_pathway_edge = None
                    tax_metabolism_edge = None
                    tax_isolation_source_edge = None
                    tax_carbon_substrate_edge = None
                    tax_to_cell_shape_edge = None
                    tax_range_tmp_edge = None

                    # Extract only the trait columns we need
                    filtered_row = {k: line[k] for k in traits_columns_of_interest}
                    # Create standardized taxonomy ID (e.g., "NCBITaxon:562")
                    tax_id = NCBITAXON_PREFIX + str(filtered_row[TAX_ID_COLUMN])
                    tax_name = filtered_row[ORG_NAME_COLUMN]
                    # Create organism node
                    tax_node = [tax_id, NCBI_CATEGORY, tax_name]

                    # Process METABOLISM trait (e.g., "aerobe", "anaerobe", "facultative")
                    if not pd.isna(filtered_row[METABOLISM_COLUMN]):
                        metabolism_node, tax_metabolism_edge = self._get_metpo_node_and_edge(
                            filtered_row[METABOLISM_COLUMN],
                            tax_id,
                            METABOLISM_CATEGORY,
                            "biolink:has_phenotype",
                            BIOLOGICAL_PROCESS
                        )

                    # Process PATHWAYS column (comma-separated biological pathways)
                    # Example: "glycolysis, photosynthesis, TCA cycle"
                    pathways = self._parse_comma_separated_values(filtered_row[PATHWAYS_COLUMN])
                    if pathways:
                        pathway_nodes = []
                        tax_pathway_edge = []

                        # Try to map pathways to METPO ontology terms first
                        pathways_not_in_metpo = []
                        for pathway in pathways:
                            node, edge = self._get_metpo_node_and_edge(
                                pathway,
                                tax_id,
                                PATHWAY_CATEGORY,
                                "biolink:capable_of",
                                BIOLOGICAL_PROCESS
                            )
                            if node and edge:
                                pathway_nodes.append(node)
                                tax_pathway_edge.append(edge)
                            else:
                                # No METPO mapping, will use NER results as fallback
                                pathways_not_in_metpo.append(pathway)

                        # For pathways not found in METPO, use NER results (GO terms)
                        if pathways_not_in_metpo:
                            ner_nodes, ner_edges = self._process_ner_fallback(
                                pathways_not_in_metpo,
                                go_result,
                                tax_id,
                                PATHWAYS_COLUMN,
                                PATHWAY_CATEGORY,
                                PATHWAY_PREFIX,
                                NCBI_TO_PATHWAY_EDGE,
                                BIOLOGICAL_PROCESS,
                            )
                            pathway_nodes.extend(ner_nodes)
                            tax_pathway_edge.extend(ner_edges)

                        # Write all pathway nodes and edges to files
                        node_writer.writerows(pathway_nodes)
                        edge_writer.writerows(tax_pathway_edge)

                    # Process CARBON_SUBSTRATES column (comma-separated chemicals)
                    # Example: "glucose, acetate, citrate"
                    carbon_substrates = self._parse_comma_separated_values(
                        filtered_row[CARBON_SUBSTRATES_COLUMN]
                    )

                    if carbon_substrates:
                        carbon_substrate_nodes = []
                        tax_carbon_substrate_edge = []

                        # Try to map carbon substrates to METPO ontology terms first
                        carbon_substrates_not_in_metpo = []
                        for substrate in carbon_substrates:
                            node, edge = self._get_metpo_node_and_edge(
                                substrate,
                                tax_id,
                                CARBON_SUBSTRATE_CATEGORY,
                                "biolink:consumes",
                                TROPHICALLY_INTERACTS_WITH
                            )
                            if node and edge:
                                carbon_substrate_nodes.append(node)
                                tax_carbon_substrate_edge.append(edge)
                            else:
                                # No METPO mapping, will use NER results as fallback
                                carbon_substrates_not_in_metpo.append(substrate)

                        # For carbon substrates not found in METPO, use NER results (ChEBI terms)
                        if carbon_substrates_not_in_metpo:
                            ner_nodes, ner_edges = self._process_ner_fallback(
                                carbon_substrates_not_in_metpo,
                                chebi_result,
                                tax_id,
                                CARBON_SUBSTRATES_COLUMN,
                                CARBON_SUBSTRATE_CATEGORY,
                                CARBON_SUBSTRATE_PREFIX,
                                NCBI_TO_CARBON_SUBSTRATE_EDGE,
                                BIOLOGICAL_PROCESS,
                            )
                            carbon_substrate_nodes.extend(ner_nodes)
                            tax_carbon_substrate_edge.extend(ner_edges)

                        # Write all carbon substrate nodes and edges to files
                        node_writer.writerows(carbon_substrate_nodes)
                        edge_writer.writerows(tax_carbon_substrate_edge)

                    # Process CELL_SHAPE trait (e.g., "rod", "cocci", "spiral")
                    if filtered_row[CELL_SHAPE_COLUMN] != "NA":
                        cell_shape = filtered_row[CELL_SHAPE_COLUMN]
                        # Try to map to METPO ontology term
                        cell_shape_node, tax_to_cell_shape_edge = self._get_metpo_node_and_edge(
                            cell_shape,
                            tax_id,
                            PHENOTYPIC_CATEGORY,
                            "biolink:has_phenotype",
                            HAS_PHENOTYPE
                        )

                        # If no METPO mapping, create custom node
                        if not cell_shape_node:
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
                    # Process RANGE_TMP (temperature types where organism survives)
                    # Map to METPO if possible, otherwise create custom nodes with
                    if filtered_row.get(RANGE_TMP_COLUMN) and filtered_row[RANGE_TMP_COLUMN] != "NA":
                        ranges = self._parse_comma_separated_values(filtered_row[RANGE_TMP_COLUMN])
                        if ranges:
                            range_tmp_nodes = []
                            tax_range_tmp_edge = []
                            for r in ranges:
                                node, edge = self._get_metpo_node_and_edge(
                                    r,
                                    tax_id,
                                    PHENOTYPIC_CATEGORY,
                                    "biolink:has_phenotype",
                                    HAS_PHENOTYPE,
                                )
                                if node and edge:
                                    range_tmp_nodes.append(node)
                                    tax_range_tmp_edge.append(edge)
                                else:
                                    # Fallback: create a custom node and edge
                                    rid = f"range_tmp:{r}"
                                    range_tmp_nodes.append([rid, PHENOTYPIC_CATEGORY, r])
                                    tax_range_tmp_edge.append([tax_id, "biolink:has_phenotype", rid, HAS_PHENOTYPE])

                    # Process ISOLATION_SOURCE (environment where organism was found)
                    isolation_source_node, tax_isolation_source_edge = self._process_isolation_source(
                        filtered_row[ISOLATION_SOURCE_COLUMN],
                        tax_id,
                        envo_mapping
                    )
                    nodes_data_to_write = [
                        sublist
                        for sublist in [
                            tax_node,
                            cell_shape_node,
                            metabolism_node,
                            # include range tmp nodes (written separately below if list)
                        ]
                        if sublist is not None
                    ]
                    # Write organism and trait nodes to file
                    node_writer.writerows(nodes_data_to_write)
                    # Write isolation source nodes separately (may be multiple)
                    if isolation_source_node:
                        node_writer.writerows(isolation_source_node)
                    # Write range_tmp nodes (may be multiple)
                    if range_tmp_nodes:
                        node_writer.writerows(range_tmp_nodes)

                    # Collect all edges to write (filter out None values)
                    edges_data_to_write = [
                        sublist
                        for sublist in [
                            tax_metabolism_edge,
                            tax_to_cell_shape_edge,
                            # tax_range_tmp_edge may be a list of edges
                        ]
                        if sublist is not None
                    ]
                    # Write organism-trait relationship edges to file
                    if len(edges_data_to_write) > 0:
                        edge_writer.writerows(edges_data_to_write)
                    # Write isolation source edges separately (may be multiple)
                    if tax_isolation_source_edge:
                        edge_writer.writerows(tax_isolation_source_edge)
                    # Write range_tmp edges separately (may be multiple)
                    if tax_range_tmp_edge:
                        edge_writer.writerows(tax_range_tmp_edge)

                    # Update progress bar with current organism being processed
                    progress.set_description(f"Processing taxonomy: {tax_id}")
                    progress.update()

        # Remove duplicate nodes (same ID and name)
        drop_duplicates(self.output_node_file, consolidation_columns=[ID_COLUMN, NAME_COLUMN])
        # Remove duplicate edges (same object ID)
        drop_duplicates(self.output_edge_file, consolidation_columns=[OBJECT_ID_COLUMN])
        # dump_ont_nodes_from(
        #     self.output_node_file, self.input_base_dir / CHEBI_NODES_FILENAME, CHEBI_PREFIX
        # )
