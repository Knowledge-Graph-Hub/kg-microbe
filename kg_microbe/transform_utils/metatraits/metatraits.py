"""MetaTraits transform class."""

import csv
import logging
from pathlib import Path
from typing import Optional, Union

from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    AUTOMATED_AGENT,
    CATEGORY_COLUMN,
    HAS_PHENOTYPE,
    HAS_PHENOTYPE_PREDICATE,
    ID_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    METATRAITS,
    METATRAITS_DATA_FILE,
    METATRAITS_RAW_DIR,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    OBSERVATION,
    PHENOTYPIC_CATEGORY,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates

logger = logging.getLogger(__name__)

METATRAITS_KNOWLEDGE_SOURCE = "infores:metatraits"

# Expected column names in the metatraits input file
METATRAITS_TAXON_COLUMN = "taxon_id"
METATRAITS_TRAIT_ID_COLUMN = "trait_id"
METATRAITS_TRAIT_LABEL_COLUMN = "trait_label"
METATRAITS_PREDICATE_COLUMN = "predicate"
METATRAITS_RELATION_COLUMN = "relation"


class MetaTraitsTransform(Transform):

    """Transform metatraits microbial trait data into KGX format.

    Ingests and transforms trait data from the MetaTraits database
    (https://metatraits.embl.de/), which provides a comprehensive
    resource for microbial trait information mapped to ontology terms
    (METPO, GO, ChEBI, EC, RHEA).

    Expected input file columns:
    - taxon_id: NCBITaxon identifier (e.g., NCBITaxon:1234)
    - trait_id: Ontology CURIE for the trait (e.g., METPO:0000001)
    - trait_label: Human-readable label for the trait
    - predicate: Biolink predicate (optional, defaults to biolink:has_phenotype)
    - relation: RO relation (optional, defaults to RO:0002200)

    Produces:
    - nodes.tsv: Taxon and trait nodes in KGX format
    - edges.tsv: Edges linking taxa to traits in KGX format
    """

    def __init__(
        self, input_dir: Optional[Union[str, Path]] = None, output_dir: Optional[Union[str, Path]] = None
    ):
        """
        Initialize MetaTraitsTransform.

        :param input_dir: Input directory path (optional).
        :param output_dir: Output directory path (optional).
        """
        source_name = METATRAITS
        super().__init__(source_name, input_dir, output_dir)
        self.knowledge_source = METATRAITS_KNOWLEDGE_SOURCE

        # Resolve input directory: prefer CLI-provided base dir, fall back to global default
        if self.input_base_dir:
            self.input_dir = Path(self.input_base_dir) / METATRAITS
        else:
            self.input_dir = METATRAITS_RAW_DIR

    def run(
        self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True
    ) -> None:
        """
        Run MetaTraitsTransform.

        :param data_file: Path to metatraits data file. Defaults to metatraits.tsv.
        :param show_status: Whether to show a progress bar.
        """
        if data_file is None:
            data_file = METATRAITS_DATA_FILE
        input_file = self.input_dir / data_file

        if not input_file.exists():
            logger.warning(
                f"MetaTraits data file not found: {input_file}. "
                "Download from https://metatraits.embl.de/ or "
                "https://drive.google.com/drive/folders/1oOqxKWnpue15QHvI3Viqk7mPag7E4jHY"
            )
            # Write empty output files with headers so downstream merge can proceed
            with open(self.output_node_file, "w") as node_file:
                node_writer = csv.writer(node_file, delimiter="\t")
                node_writer.writerow(self.node_header)
            with open(self.output_edge_file, "w") as edge_file:
                edge_writer = csv.writer(edge_file, delimiter="\t")
                edge_writer.writerow(self.edge_header)
            return

        seen_nodes: set = set()

        with (
            open(input_file, "r", encoding="utf-8") as infile,
            open(self.output_node_file, "w") as node_file,
            open(self.output_edge_file, "w") as edge_file,
        ):
            reader = csv.DictReader(infile, delimiter="\t")
            node_writer = csv.writer(node_file, delimiter="\t")
            edge_writer = csv.writer(edge_file, delimiter="\t")

            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            progress_iter = tqdm(reader, desc="Processing MetaTraits") if show_status else reader

            for row in progress_iter:
                taxon_id = row.get(METATRAITS_TAXON_COLUMN, "").strip()
                trait_id = row.get(METATRAITS_TRAIT_ID_COLUMN, "").strip()
                trait_label = row.get(METATRAITS_TRAIT_LABEL_COLUMN, "").strip()
                predicate = row.get(METATRAITS_PREDICATE_COLUMN, "").strip() or HAS_PHENOTYPE_PREDICATE
                relation = row.get(METATRAITS_RELATION_COLUMN, "").strip() or HAS_PHENOTYPE

                if not taxon_id or not trait_id:
                    continue

                # Ensure taxon has prefix
                if not taxon_id.startswith(NCBITAXON_PREFIX) and taxon_id.isdigit():
                    taxon_id = f"{NCBITAXON_PREFIX}{taxon_id}"

                # Write taxon node (once per taxon)
                if taxon_id not in seen_nodes:
                    seen_nodes.add(taxon_id)
                    taxon_node = [None] * len(self.node_header)
                    taxon_node[self.node_header.index(ID_COLUMN)] = taxon_id
                    taxon_node[self.node_header.index(CATEGORY_COLUMN)] = NCBI_CATEGORY
                    taxon_node[self.node_header.index(PROVIDED_BY_COLUMN)] = self.knowledge_source
                    node_writer.writerow(taxon_node)

                # Write trait node (once per trait)
                if trait_id not in seen_nodes:
                    seen_nodes.add(trait_id)
                    trait_node = [None] * len(self.node_header)
                    trait_node[self.node_header.index(ID_COLUMN)] = trait_id
                    trait_node[self.node_header.index(CATEGORY_COLUMN)] = PHENOTYPIC_CATEGORY
                    trait_node[self.node_header.index(NAME_COLUMN)] = trait_label
                    trait_node[self.node_header.index(PROVIDED_BY_COLUMN)] = self.knowledge_source
                    node_writer.writerow(trait_node)

                # Write edge
                edge_row = [None] * len(self.edge_header)
                edge_row[self.edge_header.index(SUBJECT_COLUMN)] = taxon_id
                edge_row[self.edge_header.index(PREDICATE_COLUMN)] = predicate
                edge_row[self.edge_header.index(OBJECT_COLUMN)] = trait_id
                edge_row[self.edge_header.index(RELATION_COLUMN)] = relation
                edge_row[self.edge_header.index(PRIMARY_KNOWLEDGE_SOURCE_COLUMN)] = self.knowledge_source
                edge_row[self.edge_header.index(KNOWLEDGE_LEVEL_COLUMN)] = OBSERVATION
                edge_row[self.edge_header.index(AGENT_TYPE_COLUMN)] = AUTOMATED_AGENT
                edge_writer.writerow(edge_row)

        drop_duplicates(self.output_node_file, sort_by_column=ID_COLUMN)
        drop_duplicates(self.output_edge_file)
