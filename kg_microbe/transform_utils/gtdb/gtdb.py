"""Transform GTDB taxonomy and genome data into KGX format."""

import csv
import gzip
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from kg_microbe.transform_utils.constants import (
    BROAD_MATCH_PREDICATE,
    BROAD_MATCH_RELATION,
    CATEGORY_COLUMN,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    DESCRIPTION_COLUMN,
    GENOME_CATEGORY,
    GTDB,
    GTDB_AR53_METADATA,
    GTDB_AR53_TAXONOMY,
    GTDB_BAC120_METADATA,
    GTDB_BAC120_TAXONOMY,
    GTDB_NCBI_POOLING_REPORT,
    GTDB_PREFIX,
    GTDB_RAW_DIR,
    ID_COLUMN,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.gtdb.utils import (
    assembly_archive,
    assembly_curie,
    clean_taxon_name,
    parse_taxonomy_string,
    strip_gtdb_prefix,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer


class GTDBTransform(Transform):
    """Transform GTDB taxonomy and genome data into KGX format."""

    def __init__(self, input_dir=None, output_dir=None):
        """
        Initialize GTDB transform.

        Args:
            input_dir: Input directory path (optional)
            output_dir: Output directory path (optional)

        """
        source_name = GTDB
        super().__init__(source_name, input_dir, output_dir)
        self.nodes = []
        self.edges = []
        self.seen_nodes = set()
        self.knowledge_source = "infores:gtdb"

        # Name -> CURIE cache. CURIEs are deterministic (derived from the
        # cleaned taxon string) so this is purely a dedup/perf cache, not an
        # ID allocator. Example: "d__Bacteria" -> "GTDB:d__Bacteria".
        self.taxon_to_id = {}
        self._created_mappings = set()  # Track GTDB->NCBI mappings to avoid duplicates
        # GTDB->NCBI pairs, held until every metadata row is read: the right
        # predicate for one of these edges depends on how many *other* GTDB
        # taxa land on the same NCBI taxon, which is not knowable row by row
        # (#883).
        self._ncbi_mappings: List[Tuple[str, str]] = []

        # Resolve input directory: prefer CLI-provided base dir, fall back to global default
        if self.input_base_dir:
            self.input_dir = Path(self.input_base_dir) / GTDB
        else:
            self.input_dir = GTDB_RAW_DIR

    def run(self, data_file=None, show_status=True):
        """
        Run the GTDB transform.

        Process:
        1. Load and parse taxonomy files
        2. Extract unique taxa and build hierarchy
        3. Load metadata for NCBI mappings
        4. Create genome nodes
        5. Write output files
        """
        print("Starting GTDB transform...")
        print(f"Input directory: {self.input_dir}")

        # Step 1: Parse taxonomy files
        print("Parsing bacterial taxonomy...")
        bac_taxa = self._parse_taxonomy_file(GTDB_BAC120_TAXONOMY)
        print(f"  Found {len(bac_taxa)} bacterial genomes")

        print("Parsing archaeal taxonomy...")
        ar_taxa = self._parse_taxonomy_file(GTDB_AR53_TAXONOMY)
        print(f"  Found {len(ar_taxa)} archaeal genomes")

        # Step 2: Build taxonomy tree and create nodes/edges
        print("Building taxonomy hierarchy...")
        all_taxa = bac_taxa + ar_taxa
        self._build_taxonomy_hierarchy(all_taxa)
        print(f"  Created {len(self.taxon_to_id)} unique GTDB taxa")

        # Step 3: Parse metadata for genomes and mappings (if files exist)
        bac_metadata_path = self.input_dir / GTDB_BAC120_METADATA
        if bac_metadata_path.exists():
            print("Parsing bacterial metadata...")
            self._parse_metadata_file(GTDB_BAC120_METADATA, bac_taxa)
        else:
            print("Bacterial metadata not found, creating genomes without NCBI mappings...")
            self._create_genomes_from_taxonomy(bac_taxa)

        ar_metadata_path = self.input_dir / GTDB_AR53_METADATA
        if ar_metadata_path.exists():
            print("Parsing archaeal metadata...")
            self._parse_metadata_file(GTDB_AR53_METADATA, ar_taxa)
        else:
            print("Archaeal metadata not found, creating genomes without NCBI mappings...")
            self._create_genomes_from_taxonomy(ar_taxa)

        # After every metadata row: the predicate depends on the whole set (#883).
        mapping_counts = self._emit_ncbi_mapping_edges()
        pooled = self._write_ncbi_pooling_report()
        print(
            f"  GTDB->NCBITaxon mappings: {mapping_counts[CLOSE_MATCH_PREDICATE]:,} close_match (1:1), "
            f"{mapping_counts[BROAD_MATCH_PREDICATE]:,} broad_match onto {pooled:,} shared NCBI taxa; "
            f"see {GTDB_NCBI_POOLING_REPORT}"
        )

        print(f"  Total nodes: {len(self.nodes)}")
        print(f"  Total edges: {len(self.edges)}")

        # Step 4: Write output
        print("Writing output files...")
        self._write_tsv_files()
        print("GTDB transform complete!")

    def _parse_taxonomy_file(self, filename: str) -> List[Tuple[str, List[str]]]:
        r"""
        Parse GTDB taxonomy file.

        Format: accession\tgtdb_taxonomy
        Returns: List[(accession, [taxa_list])]
        """
        filepath = self.input_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(
                f"GTDB taxonomy file not found at '{filepath}'. "
                "Please run the GTDB downloader to fetch the required taxonomy files."
            )

        taxa_list = []

        with open(filepath, "r") as f:
            # Skip header if present
            header = f.readline()
            if not header.startswith("accession"):
                # No header, rewind
                f.seek(0)

            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split("\t")
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
        for _accession, taxa_list in all_taxa:
            for i, taxon in enumerate(taxa_list):
                # Clean taxon name
                taxon = clean_taxon_name(taxon)
                unique_taxa.add(taxon)

                # Determine parent (previous rank)
                if i > 0:
                    parent = clean_taxon_name(taxa_list[i - 1])
                    parent_map[taxon] = parent

        # Step 2: Create nodes for all unique taxa in deterministic order
        for taxon in sorted(unique_taxa):
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
        1. Create the ncbi.assembly genome node
        2. Create subclass_of edge to GTDB taxon
        3. Create skos:closeMatch edge to NCBITaxon (if available)
        """
        filepath = self.input_dir / filename

        # Create a mapping of accession to taxonomy for quick lookup
        accession_to_taxa = {acc: taxa for acc, taxa in taxa_list}

        # Determine if file is gzipped
        open_func = gzip.open if filename.endswith(".gz") else open
        mode = "rt" if filename.endswith(".gz") else "r"

        with open_func(filepath, mode) as f:
            reader = csv.DictReader(f, delimiter="\t")

            for row in reader:
                accession = row.get("accession", "").strip()
                ncbi_taxid = row.get("ncbi_taxid", "").strip()
                # The same physical assembly's GenBank accession; "none" is how
                # GTDB spells absent here (#882).
                genbank_accession = row.get("ncbi_genbank_assembly_accession", "").strip()
                if genbank_accession.lower() in {"", "none", "na"}:
                    genbank_accession = None

                # Get taxonomy for this accession
                taxa = accession_to_taxa.get(accession)
                if not taxa:
                    continue

                # Get the species-level taxon (last in list)
                gtdb_taxon = clean_taxon_name(taxa[-1]) if taxa else None

                # Create genome node and edges
                self._create_genome_node(accession, gtdb_taxon, ncbi_taxid, genbank_accession)

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
        r"""
        Get or create the canonical CURIE for a taxon.

        The CURIE is derived deterministically from the cleaned taxon
        string -- e.g. "s__Escherichia coli" -> "GTDB:s__Escherichia_coli".
        This matches the Bioregistry-registered GTDB identifier scheme
        (regex `^[cdfgops]__\\w+\\S+$`, URI pattern
        `https://gtdb.ecogenomic.org/tree?r={id}`), so the resulting CURIE
        is resolvable on the GTDB website and stable across builds.

        Args:
            taxon_name: e.g., "d__Bacteria", "s__Escherichia coli"
                        (raw or already cleaned -- this method idempotently
                        re-cleans so callers don't have to remember).

        Returns:
            GTDB-prefixed CURIE: e.g., "GTDB:d__Bacteria",
            "GTDB:s__Escherichia_coli".

        """
        cleaned = clean_taxon_name(taxon_name)
        if cleaned not in self.taxon_to_id:
            taxon_id = f"{GTDB_PREFIX}{cleaned}"
            self.taxon_to_id[cleaned] = taxon_id

            # Create node
            self._add_node(
                node_id=taxon_id,
                category=NCBI_CATEGORY,  # biolink:OrganismTaxon
                name=cleaned,
                description=f"GTDB taxon {cleaned}",
            )

        return self.taxon_to_id[cleaned]

    def _create_genome_node(
        self,
        accession: str,
        gtdb_taxon: str,
        ncbi_taxid: str = None,
        genbank_accession: str = None,
    ):
        """
        Create genome node and associated edges.

        The node id is the ``ncbi.assembly:`` CURIE for the accession GTDB
        classified, version intact (#882). ``genbank_accession`` is GTDB's
        ``ncbi_genbank_assembly_accession`` column: for a genome GTDB took from
        RefSeq it names the *same physical assembly* in GenBank, so it is
        recorded in ``same_as``. Without it a consumer holding one of an
        assembly's two accessions found nothing -- measured on the 2026-09-10
        output, 0 of 901,341 genomes were reachable by both.

        A second node for the paired accession was considered and rejected: one
        physical assembly is one thing, and declaring both would double the
        largest node block after NCBITaxon to say nothing new.

        Args:
            accession: "RS_GCF_000005845.2" or "GCF_000005845.2"
            gtdb_taxon: "s__Escherichia_coli"
            ncbi_taxid: "562" (optional)
            genbank_accession: "GCA_000005845.2" (optional; from GTDB metadata)

        """
        # Create genome node
        genome_id = assembly_curie(accession)
        paired = assembly_curie(genbank_accession) if genbank_accession else ""
        same_as = paired if paired and paired != genome_id else ""

        # The NCBI accession, not GTDB's RS_/GB_-prefixed key: "RefSeq assembly
        # RS_GCF_000005845.2" named a string RefSeq does not issue. GTDB's form
        # is recoverable (RS_ for GCF, GB_ for GCA) and adds nothing here.
        ncbi_accession = strip_gtdb_prefix(accession)
        self._add_node(
            node_id=genome_id,
            category=GENOME_CATEGORY,
            name=ncbi_accession,
            description=f"{assembly_archive(accession)} assembly {ncbi_accession}",
            same_as=same_as,
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

        # Record the GTDB -> NCBI mapping; the edges are emitted once every
        # row has been read (see _emit_ncbi_mapping_edges).
        # Dedup on (gtdb_taxon_id, ncbi_taxid) to allow multiple NCBI IDs per GTDB taxon
        if ncbi_taxid and gtdb_taxon_id:
            mapping_key = (gtdb_taxon_id, ncbi_taxid)
            if mapping_key not in self._created_mappings:
                self._ncbi_mappings.append((gtdb_taxon_id, f"{NCBITAXON_PREFIX}{ncbi_taxid}"))
                self._created_mappings.add(mapping_key)

    def _emit_ncbi_mapping_edges(self) -> Dict[str, int]:
        """
        Emit the GTDB->NCBITaxon mapping edges, choosing the predicate by fan-in.

        NCBI carries coarse placeholder taxa -- ``bacterium``, ``uncultured
        bacterium``, ``Pseudomonadota bacterium`` -- that park unclassified
        sequence; GTDB names every genome, so the bridge between them is
        many-to-one and severely so at the top: 0.3% of NCBI taxa absorb 42.7%
        of the links, one of them 3,492 GTDB taxa (#883).

        ``close_match`` is defined as "semantically similar but not strictly
        equivalent, **broader**, or narrower", so it is the wrong predicate the
        moment two GTDB taxa share an NCBI taxon: that NCBI taxon is broader.
        A 1:1 mapping keeps ``close_match``; anything many-to-one becomes
        ``broad_match`` (``skos:broadMatch``, i.e. the object is the broader
        term), which is what the data supports. No threshold is chosen -- the
        line is exactly "is this NCBI taxon shared".

        :return: Counts of the edges emitted, by predicate.
        """
        fan_in: Counter = Counter(ncbi_id for _, ncbi_id in self._ncbi_mappings)
        counts = {CLOSE_MATCH_PREDICATE: 0, BROAD_MATCH_PREDICATE: 0}
        for gtdb_taxon_id, ncbi_id in self._ncbi_mappings:
            shared = fan_in[ncbi_id] > 1
            predicate = BROAD_MATCH_PREDICATE if shared else CLOSE_MATCH_PREDICATE
            relation = BROAD_MATCH_RELATION if shared else CLOSE_MATCH_RELATION
            self._add_edge(subject=gtdb_taxon_id, predicate=predicate, obj=ncbi_id, relation=relation)
            counts[predicate] += 1
        return counts

    def _write_ncbi_pooling_report(self) -> int:
        """
        Write the NCBI taxa that several GTDB taxa map onto.

        Written on every run, empty or not: an absent report cannot be told
        from a check that never ran. It is the deny-list a query needs to
        exclude the grab-bags deliberately rather than discovering them in a
        result set (#883).

        :return: Number of pooled NCBI taxa reported.
        """
        pooled: Dict[str, list] = {}
        for gtdb_taxon_id, ncbi_id in self._ncbi_mappings:
            pooled.setdefault(ncbi_id, []).append(gtdb_taxon_id)
        rows = sorted(
            ((ncbi_id, taxa) for ncbi_id, taxa in pooled.items() if len(taxa) > 1),
            key=lambda item: (-len(item[1]), item[0]),
        )
        report = self.output_dir / GTDB_NCBI_POOLING_REPORT
        with open(report, "w", newline="") as handle:
            writer = tsv_writer(handle)
            writer.writerow(["ncbi_taxon", "gtdb_taxa", "predicate", "examples"])
            for ncbi_id, taxa in rows:
                writer.writerow([ncbi_id, len(taxa), BROAD_MATCH_PREDICATE, "|".join(sorted(taxa)[:3])])
        return len(rows)

    def _add_node(self, node_id: str, category: str, name: str, description: str = "", same_as: str = ""):
        """Add node to internal list."""
        if node_id not in self.seen_nodes:
            self.nodes.append(
                {
                    ID_COLUMN: node_id,
                    CATEGORY_COLUMN: category,
                    NAME_COLUMN: name,
                    DESCRIPTION_COLUMN: description,
                    SAME_AS_COLUMN: same_as,
                    PROVIDED_BY_COLUMN: self.knowledge_source,
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
            SAME_AS_COLUMN,
            PROVIDED_BY_COLUMN,
        ]

        # Write nodes
        with open(self.output_node_file, "w") as nf:
            writer = tsv_dict_writer(nf, fieldnames=node_fields)
            writer.writeheader()
            writer.writerows(self.nodes)

        # Write edges
        with open(self.output_edge_file, "w") as ef:
            writer = tsv_dict_writer(ef, fieldnames=self.edge_header)
            writer.writeheader()
            writer.writerows(self.edges)
