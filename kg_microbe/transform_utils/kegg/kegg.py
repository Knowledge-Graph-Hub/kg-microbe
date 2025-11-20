"""Transform for KEGG (Kyoto Encyclopedia of Genes and Genomes) orthology."""

import logging
from pathlib import Path
from typing import List, Optional, Set

import pandas as pd

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
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
from kg_microbe.transform_utils.kegg.utils import get_kegg_ko_list
from kg_microbe.transform_utils.transform import Transform

logger = logging.getLogger(__name__)


class KEGGTransform(Transform):
    """Transform KEGG orthology data into KGX format."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize KEGGTransform.

        :param input_dir: Path to input directory (not used for KEGG)
        :param output_dir: Path to output directory (default: data/transformed)
        """
        source_name = "kegg"
        super().__init__(source_name, input_dir, output_dir)

        # Collections for nodes and edges
        self.nodes: List[dict] = []
        self.edges: List[dict] = []

        # Track seen entities to avoid duplicates
        self.seen_nodes: Set[str] = set()

        # Knowledge source
        self.knowledge_source = "infores:kegg"

    def run(self, data_file: Optional[Path] = None, show_status: bool = True) -> None:
        """
        Run the KEGG transform.

        Fetches KEGG KO entries via REST API and creates nodes.

        Note: This transform uses the KEGG REST API and may take several minutes
        due to rate limiting.

        :param data_file: Not used (kept for API compatibility)
        :param show_status: Show progress messages (default: True)
        """
        logger.info("Starting KEGG transform")

        # Fetch KO list from KEGG REST API
        logger.info("Fetching KEGG KO list...")
        ko_dict = get_kegg_ko_list()

        if not ko_dict:
            logger.error("Failed to fetch KEGG KO list")
            return

        # Create KO nodes
        logger.info(f"Creating {len(ko_dict)} KEGG KO nodes...")
        for ko_id, description in ko_dict.items():
            self.add_ko_node(ko_id, description)

        # Write output
        logger.info(f"Writing {len(self.nodes)} nodes and {len(self.edges)} edges")
        self.write_output()

        logger.info("KEGG transform complete")

    def add_ko_node(self, ko_id: str, description: str) -> None:
        """
        Add a KEGG KO node.

        :param ko_id: KO identifier (e.g., 'K00001')
        :param description: KO description
        """
        node_id = f"KEGG:{ko_id}"

        if node_id in self.seen_nodes:
            return

        # Parse description to extract name and details
        # Description format is usually: "name; detailed description [EC:x.x.x.x]"
        name = description
        desc_parts = []

        # Try to extract name (before semicolon or comma)
        if ";" in description:
            parts = description.split(";", 1)
            name = parts[0].strip()
            if len(parts) > 1:
                desc_parts.append(parts[1].strip())
        elif "," in description:
            parts = description.split(",", 1)
            name = parts[0].strip()

        node = {
            ID_COLUMN: node_id,
            CATEGORY_COLUMN: "biolink:GeneFamily",
            NAME_COLUMN: name,
            DESCRIPTION_COLUMN: description,
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(node_id)

    def add_pathway_node(self, pathway_id: str, pathway_name: str) -> None:
        """
        Add a KEGG pathway node.

        :param pathway_id: Pathway identifier (e.g., 'ko00010')
        :param pathway_name: Pathway name
        """
        node_id = f"KEGG:{pathway_id}"

        if node_id in self.seen_nodes:
            return

        node = {
            ID_COLUMN: node_id,
            CATEGORY_COLUMN: "biolink:Pathway",
            NAME_COLUMN: pathway_name,
            DESCRIPTION_COLUMN: pathway_name,
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
