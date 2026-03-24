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
        # Initialize parent class (but override transform name)
        # Temporarily set transform name to METATRAITS_GTDB for output directory
        super().__init__(input_dir, output_dir, use_multiprocessing, num_workers)

        # Update transform-specific attributes
        self.name = METATRAITS_GTDB
        self.output_dir = Path(output_dir) if output_dir else Path("data/transformed") / METATRAITS_GTDB
        self.output_node_file = self.output_dir / "nodes.tsv"
        self.output_edge_file = self.output_dir / "edges.tsv"
        self.unmapped_traits_file = self.output_dir / "unmapped_traits.tsv"
        self.unresolved_taxa_file = self.output_dir / "unresolved_taxa.tsv"

        self.knowledge_source = "infores:gtdb-metatraits"

        # GTDB species name -> set of NCBITaxon IDs mapping
        self.gtdb_to_ncbi: Dict[str, Set[str]] = defaultdict(set)
        self._load_gtdb_to_ncbi_mapping()

        # GTDB transform uses GTDB metadata mapping, not OAK adapter
        # Clear the parent's ncbitaxon cache and prevent adapter initialization
        self.ncbitaxon_name_to_id.clear()  # Not needed - we use GTDB mapping
        self._ncbi_adapter = "DISABLED"  # Prevent lazy init - GTDB doesn't need OAK

    def _load_gtdb_to_ncbi_mapping(self) -> None:
        """Load GTDB species name to NCBITaxon ID mapping from GTDB metadata files."""
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
                    taxonomy_idx = header.index("gtdb_taxonomy")
                    taxid_idx = header.index("ncbi_taxid")
                except ValueError as e:
                    print(f"  Error: Could not find required columns in {metadata_file}: {e}")
                    continue

                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) > max(taxonomy_idx, taxid_idx):
                        gtdb_taxonomy = parts[taxonomy_idx]
                        ncbi_taxid = parts[taxid_idx]

                        # Extract species name from taxonomy string
                        # Format: d__Bacteria;p__...;s__Species_name
                        if gtdb_taxonomy and ncbi_taxid and ncbi_taxid not in ("none", "NA", ""):
                            tax_parts = gtdb_taxonomy.split(";")

                            # Extract species (index 6), genus (index 5), family (index 4)
                            if len(tax_parts) >= 7:
                                species = tax_parts[6].replace("s__", "")  # Remove 's__' prefix
                                if species:
                                    ncbi_id = f"NCBITaxon:{ncbi_taxid}"
                                    self.gtdb_to_ncbi[species].add(ncbi_id)

                            # Also map genus level (for gtdb_genus_summary.jsonl.gz)
                            if len(tax_parts) >= 6:
                                genus = tax_parts[5].replace("g__", "")
                                if genus:
                                    ncbi_id = f"NCBITaxon:{ncbi_taxid}"
                                    self.gtdb_to_ncbi[genus].add(ncbi_id)

                            # Also map family level (for gtdb_family_summary.jsonl.gz)
                            if len(tax_parts) >= 5:
                                family = tax_parts[4].replace("f__", "")
                                if family:
                                    ncbi_id = f"NCBITaxon:{ncbi_taxid}"
                                    self.gtdb_to_ncbi[family].add(ncbi_id)

        print(f"  Loaded {len(self.gtdb_to_ncbi)} unique GTDB → NCBITaxon mappings")

    def _get_shared_init_data(self) -> dict:
        """Override to include GTDB-specific data for workers."""
        shared_data = super()._get_shared_init_data()
        shared_data["gtdb_to_ncbi"] = dict(self.gtdb_to_ncbi)  # Convert defaultdict to dict for pickling
        return shared_data

    def _init_from_shared_data(self, shared_data: dict) -> None:
        """Override to restore GTDB-specific data in workers."""
        super()._init_from_shared_data(shared_data)

        # Restore GTDB-specific state
        self.gtdb_to_ncbi = defaultdict(set, shared_data.get("gtdb_to_ncbi", {}))

        # Disable OAK adapter in worker (GTDB uses metadata mapping only)
        self.ncbitaxon_name_to_id.clear()
        self._ncbi_adapter = "DISABLED"

    def _get_ncbitaxon_impl(self):
        """Override parent method - GTDB transform doesn't use OAK adapter."""
        raise NotImplementedError(
            "GTDB transform uses GTDB metadata mapping, not OAK adapter. "
            "This method should never be called."
        )

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """
        Resolve GTDB taxon name to NCBITaxon ID using GTDB metadata mapping.

        Overrides parent class method to use GTDB-specific mapping instead of label search.
        Uses only local GTDB metadata dictionary - no OAK API calls.

        :param search_name: GTDB species/genus/family name (e.g., "Escherichia coli")
        :return: NCBITaxon ID (e.g., "NCBITaxon:562") or None
        """
        # Try direct lookup in GTDB mapping (O(1) dictionary lookup - no OAK)
        ncbi_ids = self.gtdb_to_ncbi.get(search_name)
        if ncbi_ids:
            # If multiple NCBITaxon IDs map to same GTDB name, return first one
            # (In practice, GTDB species usually map to a single representative NCBITaxon)
            return list(ncbi_ids)[0]

        # For GTDB-only taxa (no NCBITaxon mapping), create GTDB: namespace node
        # This preserves all data including uncultured/MAG organisms
        if search_name and not search_name.startswith("NCBITaxon:"):
            # Create GTDB namespace CURIE
            # Replace spaces with underscores, keep alphanumeric and hyphens
            gtdb_id = search_name.replace(" ", "_")
            return f"GTDB:{gtdb_id}"

        return None

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
        finally:
            # Restore original file list
            METATRAITS_INPUT_FILES.clear()
            METATRAITS_INPUT_FILES.extend(original_files)

        print("\n✅ GTDB metatraits transform complete!")
        print(f"   Output: {self.output_dir}")
        print(f"   Nodes: {self.output_node_file}")
        print(f"   Edges: {self.output_edge_file}")
