"""Transform GTDB taxonomy and genome data into KGX format."""

import csv
import gzip
from pathlib import Path
from typing import List, Tuple

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    DESCRIPTION_COLUMN,
    GENBANK_PREFIX,
    GENOME_CATEGORY,
    GTDB,
    GTDB_AR53_METADATA,
    GTDB_AR53_TAXONOMY,
    GTDB_BAC120_METADATA,
    GTDB_BAC120_TAXONOMY,
    GTDB_PREFIX,
    GTDB_RAW_DIR,
    ID_COLUMN,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.gtdb.utils import (
    clean_taxon_name,
    extract_accession_type,
    parse_taxonomy_string,
)
from kg_microbe.transform_utils.transform import Transform


class GTDBTransform(Transform):
    """Transform GTDB taxonomy and genome data into KGX format."""

    def __init__(self, input_dir=None, output_dir=None):
        source_name = GTDB
        super().__init__(source_name, input_dir, output_dir)
        self.nodes = []
        self.edges = []
        self.seen_nodes = set()
        self.knowledge_source = "infores:gtdb"

        # Mappings for efficient lookup
        self.taxon_to_id = {}  # "d__Bacteria" -> "GTDB:1"
        self.taxon_id_counter = 1

        # Set input directory to GTDB raw data directory
        self.input_dir = GTDB_RAW_DIR

    def run(self, data_file=None, show_status=True):
        """
        Main transform logic.

        Process:
        1. Load and parse taxonomy files
        2. Extract unique taxa and build hierarchy
        3. Load metadata for NCBI mappings
        4. Create genome nodes
        5. Write output files
        """
        print(f"Starting GTDB transform...")
        print(f"Input directory: {self.input_dir}")

        # Step 1: Parse taxonomy files
        print(f"Parsing bacterial taxonomy...")
        bac_taxa = self._parse_taxonomy_file(GTDB_BAC120_TAXONOMY)
        print(f"  Found {len(bac_taxa)} bacterial genomes")

        print(f"Parsing archaeal taxonomy...")
        ar_taxa = self._parse_taxonomy_file(GTDB_AR53_TAXONOMY)
        print(f"  Found {len(ar_taxa)} archaeal genomes")

        # Step 2: Build taxonomy tree and create nodes/edges
        print(f"Building taxonomy hierarchy...")
        all_taxa = bac_taxa + ar_taxa
        self._build_taxonomy_hierarchy(all_taxa)
        print(f"  Created {len(self.taxon_to_id)} unique GTDB taxa")

        # Step 3: Parse metadata for genomes and mappings (if files exist)
        bac_metadata_path = self.input_dir / GTDB_BAC120_METADATA
        if bac_metadata_path.exists():
            print(f"Parsing bacterial metadata...")
            self._parse_metadata_file(GTDB_BAC120_METADATA, bac_taxa)
        else:
            print(f"Bacterial metadata not found, creating genomes without NCBI mappings...")
            self._create_genomes_from_taxonomy(bac_taxa)

        ar_metadata_path = self.input_dir / GTDB_AR53_METADATA
        if ar_metadata_path.exists():
            print(f"Parsing archaeal metadata...")
            self._parse_metadata_file(GTDB_AR53_METADATA, ar_taxa)
        else:
            print(f"Archaeal metadata not found, creating genomes without NCBI mappings...")
            self._create_genomes_from_taxonomy(ar_taxa)

        print(f"  Total nodes: {len(self.nodes)}")
        print(f"  Total edges: {len(self.edges)}")

        # Step 4: Write output
        print(f"Writing output files...")
        self._write_tsv_files()
        print(f"GTDB transform complete!")

    def _parse_taxonomy_file(self, filename: str) -> List[Tuple[str, List[str]]]:
        """
        Parse GTDB taxonomy file.

        Format: accession\tgtdb_taxonomy
        Returns: List[(accession, [taxa_list])]
        """
        filepath = self.input_dir / filename
        taxa_list = []

        with open(filepath, 'r') as f:
            # Skip header if present
            header = f.readline()
            if not header.startswith('accession'):
                # No header, rewind
                f.seek(0)

            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                accession = parts[0].strip()
                taxonomy_str = parts[1].strip()

                # Parse taxonomy string into list of taxa
                taxa = parse_taxonomy_string(taxonomy_str)
                taxa_list.append((accession, taxa))

        return taxa_list

    def _build_taxonomy_hierarchy(self, all_taxa: List[Tuple[str, List[str]]]):
        """
        Build taxonomy hierarchy from parsed taxa.

        For each unique taxon at each rank:
        1. Create GTDB taxon node
        2. Create subclass_of edge to parent
        """
        unique_taxa = set()
        parent_map = {}  # child -> parent

        # Step 1: Collect unique taxa and build parent map
        for accession, taxa_list in all_taxa:
            for i, taxon in enumerate(taxa_list):
                # Clean taxon name
                taxon = clean_taxon_name(taxon)
                unique_taxa.add(taxon)

                # Determine parent (previous rank)
                if i > 0:
                    parent = clean_taxon_name(taxa_list[i - 1])
                    parent_map[taxon] = parent

        # Step 2: Create nodes for all unique taxa
        for taxon in unique_taxa:
            self._get_or_create_taxon_id(taxon)

        # Step 3: Create hierarchy edges
        for child, parent in parent_map.items():
            child_id = self.taxon_to_id[child]
            parent_id = self.taxon_to_id[parent]

            self._add_edge(
                subject=child_id,
                predicate=SUBCLASS_PREDICATE,
                obj=parent_id,
                relation=RDFS_SUBCLASS_OF,
            )

    def _parse_metadata_file(self, filename: str, taxa_list: List[Tuple[str, List[str]]]):
        """
        Parse GTDB metadata file.

        For each genome:
        1. Create GenBank genome node
        2. Create subclass_of edge to GTDB taxon
        3. Create skos:closeMatch edge to NCBITaxon (if available)
        """
        filepath = self.input_dir / filename

        # Create a mapping of accession to taxonomy for quick lookup
        accession_to_taxa = {acc: taxa for acc, taxa in taxa_list}

        # Determine if file is gzipped
        open_func = gzip.open if filename.endswith('.gz') else open
        mode = 'rt' if filename.endswith('.gz') else 'r'

        with open_func(filepath, mode) as f:
            reader = csv.DictReader(f, delimiter='\t')

            for row in reader:
                accession = row.get('accession', '').strip()
                ncbi_taxid = row.get('ncbi_taxid', '').strip()

                # Get taxonomy for this accession
                taxa = accession_to_taxa.get(accession)
                if not taxa:
                    continue

                # Get the species-level taxon (last in list)
                gtdb_taxon = clean_taxon_name(taxa[-1]) if taxa else None

                # Create genome node and edges
                self._create_genome_node(accession, gtdb_taxon, ncbi_taxid)

    def _create_genomes_from_taxonomy(self, taxa_list: List[Tuple[str, List[str]]]):
        """
        Create genome nodes from taxonomy data without metadata.

        This is used when metadata files are not available.
        """
        for accession, taxa in taxa_list:
            # Get the species-level taxon (last in list)
            gtdb_taxon = clean_taxon_name(taxa[-1]) if taxa else None

            # Create genome node and edges (without NCBI mapping)
            self._create_genome_node(accession, gtdb_taxon, ncbi_taxid=None)

    def _get_or_create_taxon_id(self, taxon_name: str) -> str:
        """
        Get or create a unique ID for a taxon.

        Args:
            taxon_name: e.g., "d__Bacteria", "s__Escherichia_coli"

        Returns:
            GTDB prefixed ID: e.g., "GTDB:1"
        """
        if taxon_name not in self.taxon_to_id:
            taxon_id = f"{GTDB_PREFIX}{self.taxon_id_counter}"
            self.taxon_to_id[taxon_name] = taxon_id
            self.taxon_id_counter += 1

            # Create node
            self._add_node(
                node_id=taxon_id,
                category=NCBI_CATEGORY,  # biolink:OrganismTaxon
                name=taxon_name,
                description=f"GTDB taxon {taxon_name}",
            )

        return self.taxon_to_id[taxon_name]

    def _create_genome_node(self, accession: str, gtdb_taxon: str, ncbi_taxid: str = None):
        """
        Create genome node and associated edges.

        Args:
            accession: "GCF_000005845.2"
            gtdb_taxon: "s__Escherichia_coli"
            ncbi_taxid: "562" (optional)
        """
        # Create genome node
        base_accession, version = extract_accession_type(accession)
        genome_id = f"{GENBANK_PREFIX}{base_accession}"

        self._add_node(
            node_id=genome_id,
            category=GENOME_CATEGORY,
            name=accession,
            description=f"GenBank genome {accession}",
        )

        # Create genome -> GTDB taxon edge
        gtdb_taxon_id = self.taxon_to_id.get(gtdb_taxon)
        if gtdb_taxon_id:
            self._add_edge(
                subject=genome_id,
                predicate=SUBCLASS_PREDICATE,
                obj=gtdb_taxon_id,
                relation=RDFS_SUBCLASS_OF,
            )

        # Create GTDB -> NCBI mapping edge (if available)
        # Only create one mapping per GTDB taxon (avoid duplicates)
        if ncbi_taxid and gtdb_taxon_id:
            # Check if we've already created this mapping
            mapping_key = (gtdb_taxon_id, ncbi_taxid)
            if not hasattr(self, '_created_mappings'):
                self._created_mappings = set()

            if mapping_key not in self._created_mappings:
                ncbi_id = f"{NCBITAXON_PREFIX}{ncbi_taxid}"
                self._add_edge(
                    subject=gtdb_taxon_id,
                    predicate=CLOSE_MATCH_PREDICATE,
                    obj=ncbi_id,
                    relation=CLOSE_MATCH_RELATION,
                )
                self._created_mappings.add(mapping_key)

    def _add_node(self, node_id: str, category: str, name: str, description: str = ""):
        """Add node to internal list."""
        if node_id not in self.seen_nodes:
            self.nodes.append(
                {
                    ID_COLUMN: node_id,
                    CATEGORY_COLUMN: category,
                    NAME_COLUMN: name,
                    DESCRIPTION_COLUMN: description,
                    PRIMARY_KNOWLEDGE_SOURCE_COLUMN: self.knowledge_source,
                }
            )
            self.seen_nodes.add(node_id)

    def _add_edge(self, subject: str, predicate: str, obj: str, relation: str):
        """Add edge to internal list."""
        self.edges.append(
            {
                SUBJECT_COLUMN: subject,
                PREDICATE_COLUMN: predicate,
                OBJECT_COLUMN: obj,
                RELATION_COLUMN: relation,
                PRIMARY_KNOWLEDGE_SOURCE_COLUMN: self.knowledge_source,
            }
        )

    def _write_tsv_files(self):
        """Write nodes and edges to TSV files."""
        # Define node fields based on what we actually use
        node_fields = [
            ID_COLUMN,
            CATEGORY_COLUMN,
            NAME_COLUMN,
            DESCRIPTION_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
        ]

        # Write nodes
        with open(self.output_node_file, 'w') as nf:
            writer = csv.DictWriter(nf, fieldnames=node_fields, delimiter='\t')
            writer.writeheader()
            writer.writerows(self.nodes)

        # Write edges
        with open(self.output_edge_file, 'w') as ef:
            writer = csv.DictWriter(ef, fieldnames=self.edge_header, delimiter='\t')
            writer.writeheader()
            writer.writerows(self.edges)
