"""Transform for COG (Clusters of Orthologous Groups) functional classifications."""

import logging
from pathlib import Path
from typing import List, Optional, Set

import pandas as pd

from kg_microbe.transform_utils.cog.utils import (
    get_category_group_name,
    parse_cog_definitions,
    parse_functional_categories,
    split_functional_categories,
)
from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    COG,
    COG_RAW_DIR,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform

logger = logging.getLogger(__name__)


class COGTransform(Transform):

    """Transform COG functional classifications into KGX format."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize COGTransform.

        :param input_dir: Path to input directory (default: data/raw)
        :param output_dir: Path to output directory (default: data/transformed)
        """
        source_name = COG
        super().__init__(source_name, input_dir, output_dir)

        # Collections for nodes and edges
        self.nodes: List[dict] = []
        self.edges: List[dict] = []

        # Track seen entities to avoid duplicates
        self.seen_nodes: Set[str] = set()

        # Knowledge source
        self.knowledge_source = "infores:cog"

    def run(self, data_file: Optional[Path] = None, show_status: bool = True) -> None:
        """
        Run the COG transform.

        :param data_file: Not used (kept for API compatibility)
        :param show_status: Show progress messages (default: True)
        """
        logger.info("Starting COG transform")

        # Check if output files already exist
        if self.output_node_file.exists() and self.output_edge_file.exists():
            logger.info(f"COG transform output already exists at {self.output_dir}")
            logger.info("Skipping transform. Delete output files to regenerate.")
            return

        # Define input files
        cog_def_file = COG_RAW_DIR / "cog-24.def.tab"
        cog_fun_file = COG_RAW_DIR / "cog-24.fun.tab"

        # Check files exist
        if not cog_def_file.exists():
            logger.error(f"COG definitions file not found: {cog_def_file}")
            logger.error("Please run 'poetry run kg download' first")
            return

        if not cog_fun_file.exists():
            logger.error(f"COG functional categories file not found: {cog_fun_file}")
            logger.error("Please run 'poetry run kg download' first")
            return

        # Parse COG data
        logger.info("Parsing COG definitions...")
        cog_defs = parse_cog_definitions(cog_def_file)

        logger.info("Parsing functional categories...")
        func_cats = parse_functional_categories(cog_fun_file)

        # Create functional category nodes
        logger.info(f"Creating {len(func_cats)} functional category nodes...")
        for cat_id, cat_data in func_cats.items():
            self.add_functional_category_node(cat_id, cat_data)

        # Create group nodes and category->group edges
        logger.info("Creating COG group hierarchy...")
        group_ids = set(cat_data["group"] for cat_data in func_cats.values())
        for group_id in sorted(group_ids):
            self.add_group_node(group_id)

        # Create category->group edges
        for cat_id, cat_data in func_cats.items():
            group_id = cat_data["group"]
            self.add_edge(
                f"COG_CAT:{cat_id}",
                "biolink:subclass_of",
                f"COG_GROUP:{group_id}",
                "rdfs:subClassOf",
            )

        # Create COG nodes and edges
        logger.info(f"Processing {len(cog_defs)} COG entries...")
        for cog_id, cog_data in cog_defs.items():
            self.add_cog_node(cog_id, cog_data)

            # Add edges to functional categories
            categories = split_functional_categories(cog_data["functional_category"])
            for cat_id in categories:
                if cat_id in func_cats:
                    self.add_edge(
                        f"COG:{cog_id}",
                        "biolink:subclass_of",
                        f"COG_CAT:{cat_id}",
                        "rdfs:subClassOf",
                    )

        # Write output
        logger.info(f"Writing {len(self.nodes)} nodes and {len(self.edges)} edges")
        self.write_output()

        logger.info("COG transform complete")

    def add_functional_category_node(self, cat_id: str, cat_data: dict) -> None:
        """
        Add a functional category node.

        :param cat_id: Category ID (single letter, e.g., 'C', 'P')
        :param cat_data: Category data dictionary
        """
        node_id = f"COG_CAT:{cat_id}"

        if node_id in self.seen_nodes:
            return

        # Get group name from group ID
        group_name = get_category_group_name(cat_data["group"])

        node = {
            ID_COLUMN: node_id,
            CATEGORY_COLUMN: "biolink:OntologyClass",
            NAME_COLUMN: cat_data["description"],
            DESCRIPTION_COLUMN: f"{group_name} - {cat_data['description']}",
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(node_id)

    def add_group_node(self, group_id: str) -> None:
        """
        Add a COG functional category group node.

        :param group_id: Group ID (1-4)
        """
        node_id = f"COG_GROUP:{group_id}"

        if node_id in self.seen_nodes:
            return

        # Get group name
        group_name = get_category_group_name(group_id)

        node = {
            ID_COLUMN: node_id,
            CATEGORY_COLUMN: "biolink:OntologyClass",
            NAME_COLUMN: group_name,
            DESCRIPTION_COLUMN: f"COG functional category group: {group_name}",
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(node_id)

    def add_cog_node(self, cog_id: str, cog_data: dict) -> None:
        """
        Add a COG node.

        :param cog_id: COG identifier (e.g., 'COG0178')
        :param cog_data: COG data dictionary
        """
        node_id = f"COG:{cog_id}"

        if node_id in self.seen_nodes:
            return

        # Build description from available fields
        description_parts = []
        if cog_data["name"]:
            description_parts.append(cog_data["name"])
        if cog_data["gene_name"]:
            description_parts.append(f"Gene: {cog_data['gene_name']}")
        if cog_data["pathway"]:
            description_parts.append(f"Pathway: {cog_data['pathway']}")

        description = " | ".join(description_parts) if description_parts else ""

        node = {
            ID_COLUMN: node_id,
            CATEGORY_COLUMN: "biolink:GeneFamily",
            NAME_COLUMN: cog_data["name"],
            DESCRIPTION_COLUMN: description,
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(node_id)

    def add_edge(self, subject: str, predicate: str, obj: str, relation: str) -> None:
        """
        Add an edge to the collection.

        :param subject: Subject node ID
        :param predicate: Biolink predicate
        :param obj: Object node ID
        :param relation: RO or other relation ontology term
        """
        edge = {
            SUBJECT_COLUMN: subject,
            PREDICATE_COLUMN: predicate,
            OBJECT_COLUMN: obj,
            RELATION_COLUMN: relation,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: self.knowledge_source,
        }

        self.edges.append(edge)

    def write_output(self) -> None:
        """Write nodes and edges to TSV files."""
        # Convert to DataFrames
        nodes_df = pd.DataFrame(self.nodes, columns=self.node_header)
        edges_df = pd.DataFrame(self.edges, columns=self.edge_header)

        # Drop duplicates
        nodes_df = nodes_df.drop_duplicates(subset=[ID_COLUMN])
        edges_df = edges_df.drop_duplicates()

        # Write to TSV
        nodes_df.to_csv(self.output_node_file, sep="\t", index=False)
        edges_df.to_csv(self.output_edge_file, sep="\t", index=False)

        logger.info(f"Wrote {len(nodes_df)} nodes to {self.output_node_file}")
        logger.info(f"Wrote {len(edges_df)} edges to {self.output_edge_file}")
