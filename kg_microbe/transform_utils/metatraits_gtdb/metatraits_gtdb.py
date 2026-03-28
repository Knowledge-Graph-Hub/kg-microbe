"""
MetaTraits GTDB transform class.

Extends MetaTraitsTransform to process GTDB-based metatraits data.
Uses GTDB metadata files to map GTDB species names to NCBITaxon IDs.
"""

import gzip
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Set, Union

from kg_microbe.transform_utils.constants import METATRAITS_GTDB, RAW_DATA_DIR
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings

# Input file names for GTDB metatraits (species-level only)
METATRAITS_GTDB_INPUT_FILES = [
    "gtdb_species_summary.jsonl.gz",
    # Genus and family level commented out - only processing species-level traits
    # "gtdb_genus_summary.jsonl.gz",
    # "gtdb_family_summary.jsonl.gz",
]


class MetaTraitsGTDBTransform(MetaTraitsTransform):

    """Transform GTDB metatraits summary JSONL files into KGX nodes and edges."""

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        use_multiprocessing: bool = True,
        num_workers: Optional[int] = None,
    ):
        """
        Initialize MetaTraitsGTDBTransform.

        :param input_dir: Input directory (default: data/raw)
        :param output_dir: Output directory (default: data/transformed/metatraits_gtdb)
        :param use_multiprocessing: Enable parallel processing (default: True)
        :param num_workers: Number of workers (default: auto-detect from resources)
        """
        # Call parent's parent (Transform) with correct source name to set output directory properly
        # This ensures output goes to data/transformed/metatraits_gtdb/ not data/transformed/
        Transform.__init__(self, METATRAITS_GTDB, input_dir, output_dir)

        # Initialize MetaTraitsTransform-specific attributes (from parent class)
        self.edge_header = self.edge_header + ["has_percentage"]
        self.knowledge_source = "infores:gtdb-metatraits"

        # Load mappings (from parent class)
        self.microbial_mappings = load_microbial_trait_mappings()
        self.metpo_mappings = load_metpo_mappings("metatraits synonym")

        # Initialize chemical mapping loader (from parent class)
        try:
            self.chemical_loader = ChemicalMappingLoader()
        except (FileNotFoundError, ImportError) as e:
            print(f"  Warning: Could not load unified chemical mappings: {e}")
            self.chemical_loader = None

        # Defer adapter creation (from parent class)
        self._ncbi_adapter = None

        # NCBITaxon name cache (from parent class)
        self.ncbitaxon_name_to_id: Dict[str, str] = {}

        # Multiprocessing configuration (from parent class)
        self.use_multiprocessing = use_multiprocessing
        self.num_workers = num_workers

        # Trait name -> (curie, category, predicate) from METPO + custom_curies (from parent class)
        self.trait_mapping: Dict[str, dict] = {}
        self._build_trait_mapping()

        # Output file paths (from parent class)
        self.unmapped_traits_file = self.output_dir / "unmapped_traits.tsv"
        self.unresolved_taxa_file = self.output_dir / "unresolved_taxa.tsv"
        self.measurement_traits_file = self.output_dir / "measurement_traits.tsv"

        # GTDB species name -> set of NCBITaxon IDs mapping
        self.gtdb_to_ncbi: Dict[str, Set[str]] = defaultdict(set)
        # Genome accession -> NCBITaxon ID mapping (for equivalence links)
        self.accession_to_ncbi: Dict[str, str] = {}
        # Genome accession -> current GTDB species name (for hierarchical links)
        self.accession_to_gtdb_species: Dict[str, str] = {}
        # Track synthetic nodes that need hierarchical edges
        self.synthetic_nodes_metadata: Dict[str, Dict[str, str]] = {}
        self._load_gtdb_to_ncbi_mapping()
        self._load_gtdb_taxonomy()

        # GTDB transform uses GTDB metadata mapping, not OAK adapter
        # Clear the parent's ncbitaxon cache and prevent adapter initialization
        self.ncbitaxon_name_to_id.clear()  # Not needed - we use GTDB mapping
        self._ncbi_adapter = "DISABLED"  # Prevent lazy init - GTDB doesn't need OAK

    def _load_gtdb_to_ncbi_mapping(self) -> None:
        """
        Load GTDB species name to NCBITaxon ID mapping from GTDB metadata files.

        Also builds accession-based mapping to resolve species with renamed taxonomy.
        """
        gtdb_dir = RAW_DATA_DIR / "gtdb"

        # Process both bacterial and archaeal metadata
        for metadata_file in ["bac120_metadata.tsv.gz", "ar53_metadata.tsv.gz"]:
            filepath = gtdb_dir / metadata_file

            if not filepath.exists():
                print(f"  Warning: {filepath} not found")
                continue

            print(f"  Loading GTDB metadata from {filepath.name}...")

            with gzip.open(filepath, "rt") as f:
                header = next(f).strip().split("\t")

                # Find column indices
                try:
                    accession_idx = 0  # First column is always genome accession
                    taxonomy_idx = header.index("gtdb_taxonomy")
                    taxid_idx = header.index("ncbi_taxid")
                except ValueError as e:
                    print(f"  Error: Could not find required columns in {metadata_file}: {e}")
                    continue

                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) > max(taxonomy_idx, taxid_idx):
                        accession = parts[accession_idx]
                        gtdb_taxonomy = parts[taxonomy_idx]
                        ncbi_taxid = parts[taxid_idx]

                        # Extract species name from taxonomy string
                        # Format: d__Bacteria;p__...;s__Species_name
                        if gtdb_taxonomy and ncbi_taxid and ncbi_taxid not in ("none", "NA", ""):
                            ncbi_id = f"NCBITaxon:{ncbi_taxid}"
                            tax_parts = gtdb_taxonomy.split(";")

                            # Extract species (index 6), genus (index 5), family (index 4)
                            if len(tax_parts) >= 7:
                                species = tax_parts[6].replace("s__", "")  # Remove 's__' prefix
                                if species:
                                    self.gtdb_to_ncbi[species].add(ncbi_id)

                            # Also map genus level (for gtdb_genus_summary.jsonl.gz)
                            if len(tax_parts) >= 6:
                                genus = tax_parts[5].replace("g__", "")
                                if genus:
                                    self.gtdb_to_ncbi[genus].add(ncbi_id)

                            # Also map family level (for gtdb_family_summary.jsonl.gz)
                            if len(tax_parts) >= 5:
                                family = tax_parts[4].replace("f__", "")
                                if family:
                                    self.gtdb_to_ncbi[family].add(ncbi_id)

                            # Map genome accession to NCBITaxon for fallback lookup
                            # Accession format: GB_GCA_001788565.1 or RS_GCF_001788565.1
                            # Extract numeric part: 001788565
                            if accession:
                                # Remove prefix (GB_GCA_ or RS_GCF_) and version (.1)
                                acc_parts = accession.replace("GB_GCA_", "").replace("RS_GCF_", "").split(".")[0]
                                # Store with 'sp' prefix for matching metatraits format
                                self.accession_to_ncbi[f"sp{acc_parts}"] = ncbi_id

        print(
            f"  Loaded {len(self.gtdb_to_ncbi)} unique GTDB → NCBITaxon name mappings"
        )
        print(
            f"  Loaded {len(self.accession_to_ncbi)} unique accession → NCBITaxon mappings"
        )

    def _load_gtdb_taxonomy(self) -> None:
        """
        Load GTDB taxonomy to map genome accessions to current species names.

        This enables hierarchical linking of synthetic nodes to GTDB taxonomy.
        """
        gtdb_dir = RAW_DATA_DIR / "gtdb"

        # Process both bacterial and archaeal taxonomy
        for taxonomy_file in ["bac120_taxonomy.tsv", "ar53_taxonomy.tsv"]:
            filepath = gtdb_dir / taxonomy_file

            if not filepath.exists():
                print(f"  Warning: {filepath} not found")
                continue

            print(f"  Loading GTDB taxonomy from {filepath.name}...")

            with open(filepath, "r") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        accession = parts[0]  # e.g., GB_GCA_001788565.1
                        taxonomy = parts[1]  # e.g., d__Bacteria;...;s__MGCX01 sp001788565

                        # Extract species name from taxonomy string
                        tax_parts = taxonomy.split(";")
                        if len(tax_parts) >= 7:
                            species = tax_parts[6].replace("s__", "")  # Remove 's__' prefix
                            if species:
                                # Extract numeric accession: GB_GCA_001788565.1 → sp001788565
                                acc_parts = (
                                    accession.replace("GB_GCA_", "")
                                    .replace("RS_GCF_", "")
                                    .split(".")[0]
                                )
                                self.accession_to_gtdb_species[f"sp{acc_parts}"] = species

        print(
            f"  Loaded {len(self.accession_to_gtdb_species)} unique accession → GTDB species mappings"
        )

    def _get_shared_init_data(self) -> dict:
        """Override to include GTDB-specific data for workers."""
        shared_data = super()._get_shared_init_data()
        shared_data["gtdb_to_ncbi"] = dict(self.gtdb_to_ncbi)  # Convert defaultdict to dict for pickling
        shared_data["accession_to_ncbi"] = self.accession_to_ncbi  # Already a dict
        shared_data["accession_to_gtdb_species"] = self.accession_to_gtdb_species  # Already a dict
        return shared_data

    def _init_from_shared_data(self, shared_data: dict) -> None:
        """Override to restore GTDB-specific data in workers."""
        super()._init_from_shared_data(shared_data)

        # Restore GTDB-specific state
        self.gtdb_to_ncbi = defaultdict(set, shared_data.get("gtdb_to_ncbi", {}))
        self.accession_to_ncbi = shared_data.get("accession_to_ncbi", {})
        self.accession_to_gtdb_species = shared_data.get("accession_to_gtdb_species", {})
        self.synthetic_nodes_metadata = {}  # Will be populated during processing

        # Disable OAK adapter in worker (GTDB uses metadata mapping only)
        self.ncbitaxon_name_to_id.clear()
        self._ncbi_adapter = "DISABLED"

    def _get_ncbitaxon_impl(self):
        """Override parent method - GTDB transform doesn't use OAK adapter."""
        raise NotImplementedError(
            "GTDB transform uses GTDB metadata mapping, not OAK adapter. This method should never be called."
        )

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """
        Create GTDB synthetic node and track metadata for hierarchical linking.

        Overrides parent class method. Instead of returning NCBITaxon IDs,
        creates synthetic GTDB: nodes and stores metadata for creating:
        - rdfs:subClassOf edges to GTDB taxonomy (via genome accession)
        - owl:sameAs edges to NCBITaxon (when available)

        Strategy:
        1. Try direct lookup by current taxonomy name → use if matches
        2. Otherwise, create synthetic GTDB: node
        3. Extract accession and lookup GTDB species + NCBITaxon for edge creation
        4. Store metadata for post-processing

        :param search_name: GTDB species/genus/family name (e.g., "2-01-FULL-49-22 sp001788565")
        :return: GTDB synthetic node ID or NCBITaxon ID if current name matches
        """
        import re

        # Try direct lookup - if current taxonomy name matches, use NCBITaxon
        ncbi_ids = self.gtdb_to_ncbi.get(search_name)
        if ncbi_ids:
            # Current taxonomy - use NCBITaxon directly (no synthetic node needed)
            return list(ncbi_ids)[0]

        # Create synthetic GTDB: node for historical/renamed taxonomy
        if not search_name or search_name.startswith("NCBITaxon:"):
            return None

        gtdb_id = search_name.replace(" ", "_")
        synthetic_node_id = f"GTDB:{gtdb_id}"

        # Extract accession for hierarchical linking
        accession_match = re.search(r"\bsp\d{9}\b", search_name)
        if accession_match:
            accession = accession_match.group(0)

            # Look up current GTDB species name and NCBITaxon ID
            current_gtdb_species = self.accession_to_gtdb_species.get(accession)
            ncbi_id = self.accession_to_ncbi.get(accession)

            # Store metadata for creating hierarchical edges later
            self.synthetic_nodes_metadata[synthetic_node_id] = {
                "original_name": search_name,
                "accession": accession,
                "current_gtdb_species": current_gtdb_species,  # For subClassOf edge
                "ncbi_taxon": ncbi_id,  # For sameAs edge
            }

        return synthetic_node_id

    def _create_hierarchical_edges(self) -> None:
        """
        Create hierarchical edges for synthetic GTDB nodes.

        For each synthetic node, creates:
        1. rdfs:subClassOf edge to current GTDB species (via genome accession)
        2. owl:sameAs edge to NCBITaxon (if available)

        These edges enable graph traversal from historical taxonomy to current
        taxonomy and cross-database integration.

        Note: Reads synthetic nodes from output file since worker metadata is not
        available in main process after multiprocessing.
        """
        import csv
        import re
        from kg_microbe.transform_utils.constants import (
            ID_COLUMN,
            NAME_COLUMN,
            OBJECT_COLUMN,
            PREDICATE_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
            RDFS_SUBCLASS_OF,
            RELATION_COLUMN,
            SAME_AS_PREDICATE,
            SUBCLASS_PREDICATE,
            SUBJECT_COLUMN,
        )

        print("\n  Creating hierarchical edges for synthetic GTDB nodes...")

        # Read synthetic nodes from output file (since worker metadata not available)
        synthetic_nodes = []
        with open(self.output_node_file, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                node_id = row[ID_COLUMN]
                if node_id.startswith("GTDB:"):
                    # Extract original name from node
                    name = row.get(NAME_COLUMN, node_id.replace("GTDB:", "").replace("_", " "))
                    synthetic_nodes.append({"id": node_id, "name": name})

        if not synthetic_nodes:
            print("  No synthetic nodes found (all resolved to current taxonomy)")
            return

        print(f"  Found {len(synthetic_nodes)} synthetic GTDB nodes")

        hierarchical_edges = []

        # Create edges for each synthetic node
        for node_info in synthetic_nodes:
            node_id = node_info["id"]
            name = node_info["name"]

            # Extract accession from name
            accession_match = re.search(r"\bsp\d{9}\b", name)
            if not accession_match:
                continue

            accession = accession_match.group(0)

            # Look up current GTDB species and NCBITaxon
            current_species = self.accession_to_gtdb_species.get(accession)
            ncbi_taxon = self.accession_to_ncbi.get(accession)

            # Edge 1: rdfs:subClassOf to current GTDB species
            if current_species:
                hierarchical_edges.append(
                    {
                        SUBJECT_COLUMN: node_id,
                        PREDICATE_COLUMN: SUBCLASS_PREDICATE,
                        OBJECT_COLUMN: f"GTDB:{current_species.replace(' ', '_')}",
                        RELATION_COLUMN: RDFS_SUBCLASS_OF,
                        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: "infores:gtdb-metatraits",
                    }
                )

            # Edge 2: owl:sameAs to NCBITaxon (equivalence)
            if ncbi_taxon:
                hierarchical_edges.append(
                    {
                        SUBJECT_COLUMN: node_id,
                        PREDICATE_COLUMN: SAME_AS_PREDICATE,
                        OBJECT_COLUMN: ncbi_taxon,
                        RELATION_COLUMN: "owl:sameAs",
                        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: "infores:gtdb-metatraits",
                    }
                )

        print(f"  Created {len(hierarchical_edges)} hierarchical edges:")
        print(f"    - {sum(1 for e in hierarchical_edges if 'subClassOf' in e[RELATION_COLUMN])} subClassOf edges")
        print(f"    - {sum(1 for e in hierarchical_edges if 'sameAs' in e[RELATION_COLUMN])} sameAs edges")

        # Append to existing edge file
        if hierarchical_edges:
            with open(self.output_edge_file, "a") as f:
                writer = csv.DictWriter(f, fieldnames=self.edge_header, delimiter="\t")
                for edge in hierarchical_edges:
                    # Fill in missing columns with empty strings
                    for col in self.edge_header:
                        if col not in edge:
                            edge[col] = ""
                    writer.writerow(edge)

            print(f"  ✅ Appended {len(hierarchical_edges)} edges to {self.output_edge_file.name}")
        else:
            print("  No hierarchical edges created (no accessions found)")

    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Run MetaTraitsGTDBTransform.

        Processes GTDB metatraits JSONL files and generates KGX nodes/edges.

        :param data_file: Ignored; uses configured GTDB input file list.
        :param show_status: Whether to show progress bar.
        """
        input_base = Path(self.input_base_dir)

        # Find which GTDB input files exist
        input_files = []
        seen = set()
        for name in METATRAITS_GTDB_INPUT_FILES:
            p = input_base / name
            if p.exists() and str(p) not in seen:
                input_files.append(p)
                seen.add(str(p))
            else:
                # Try without .gz extension
                plain_name = name.replace(".gz", "")
                p = input_base / plain_name
                if p.exists() and str(p) not in seen:
                    input_files.append(p)
                    seen.add(str(p))

        if not input_files:
            raise FileNotFoundError(
                f"No GTDB metatraits JSONL files found in {input_base}. Expected one of: {METATRAITS_GTDB_INPUT_FILES}"
            )

        print(f"\nProcessing {len(input_files)} GTDB metatraits files:")
        for f in input_files:
            print(f"  - {f.name}")

        # Call parent class run() method with GTDB-specific file list
        # The parent class handles the actual processing logic
        # We've overridden _search_ncbitaxon_by_label() to use GTDB mapping

        # Temporarily replace parent's input file list with GTDB files
        from kg_microbe.transform_utils.metatraits.metatraits import METATRAITS_INPUT_FILES

        original_files = METATRAITS_INPUT_FILES.copy()
        METATRAITS_INPUT_FILES.clear()
        METATRAITS_INPUT_FILES.extend(METATRAITS_GTDB_INPUT_FILES)

        try:
            # Call parent run() method
            super().run(data_file=data_file, show_status=show_status)

            # Create hierarchical edges for synthetic GTDB nodes
            self._create_hierarchical_edges()
        finally:
            # Restore original file list
            METATRAITS_INPUT_FILES.clear()
            METATRAITS_INPUT_FILES.extend(original_files)

        print("\n✅ GTDB metatraits transform complete!")
        print(f"   Output: {self.output_dir}")
        print(f"   Nodes: {self.output_node_file}")
        print(f"   Edges: {self.output_edge_file}")
