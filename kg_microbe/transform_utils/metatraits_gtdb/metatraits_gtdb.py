"""
MetaTraits GTDB transform class.

Extends MetaTraitsTransform to process GTDB-based metatraits data.
Uses GTDB metadata files to map GTDB species names to NCBITaxon IDs.
"""

import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Optional, Set, Tuple, Union

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    AUTOMATED_AGENT,
    BROAD_MATCH_PREDICATE,
    BROAD_MATCH_RELATION,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    GTDB,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    METATRAITS_GTDB,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PREDICTION,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RAW_DATA_DIR,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.gtdb.utils import clean_taxon_name
from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.external_identifiers import load_taxid_merges
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings
from kg_microbe.utils.tsv_io import tsv_dict_writer

# Input file names for GTDB metatraits (species-level only)
METATRAITS_GTDB_INPUT_FILES = [
    "gtdb_species_summary.jsonl.gz",
    # Genus and family level commented out - only processing species-level traits
    # "gtdb_genus_summary.jsonl.gz",
    # "gtdb_family_summary.jsonl.gz",
]

HISTORICAL_BRIDGE_AUDIT = "historical_taxonomy_dispositions.tsv"
CANONICAL_MAPPING_INPUT = "metatraits_gtdb_canonical_mappings"
BRIDGE_AUDIT_COLUMNS = (
    "subject",
    "original_node_json",
    "accession_hint",
    "candidate_species_json",
    "candidate_ncbi_json",
    "proposed_edges_json",
    "canonical_evidence_json",
    "disposition",
    "reason",
)


def _register_numeric_candidate(lookup, conflicts, token, value):
    """Keep conflicting hint values unresolved, never choose by input row order."""
    if token in conflicts:
        conflicts[token].add(value)
    elif token in lookup and lookup[token] != value:
        conflicts[token] = {lookup.pop(token), value}
    else:
        lookup[token] = value


class MetaTraitsGTDBTransform(MetaTraitsTransform):
    """Transform GTDB metatraits summary JSONL files into KGX nodes and edges."""

    # Only identical current subjects may reuse canonical mappings (#1285).
    TRANSFORM_INPUTS = (*MetaTraitsTransform.TRANSFORM_INPUTS, GTDB)
    DATA_INPUTS = (*MetaTraitsTransform.DATA_INPUTS, "data/raw/taxdump.tar.gz")
    CODE_INPUTS = ("kg_microbe/transform_utils/metatraits",)
    REQUIRED_CONSUMED_INPUTS = (*MetaTraitsTransform.REQUIRED_CONSUMED_INPUTS, CANONICAL_MAPPING_INPUT)
    REQUIRED_AUDIT_FILES = (*MetaTraitsTransform.REQUIRED_AUDIT_FILES, HISTORICAL_BRIDGE_AUDIT)

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
        self.edge_header = self.edge_header + ["has_percentage", "value", "unit"]
        self.knowledge_source = "infores:gtdb-metatraits"

        # Load mappings (from parent class)
        self.microbial_mappings = load_microbial_trait_mappings()
        self.metpo_mappings = load_metpo_mappings("metatraits synonym")
        self.special_chemical_mappings = self._load_special_chemical_mappings()
        # Chemical name synonyms migrated to unified_chemical_mappings.tsv.gz (Phase 2, 2026-04-07)
        # Lookups now handled by self.chemical_loader.find_chebi_by_name()
        self.ec_to_go = self._load_ec_to_go()
        self.enzyme_name_to_go = self._load_enzyme_name_to_go()
        self.ncbi_to_gtdb_mappings = self._load_ncbi_gtdb_mappings()

        # Load METPO binned range classes for data-driven classification (from parent class)
        self.metpo_binned_ranges = self._load_metpo_binned_ranges()

        # Load comprehensive METPO class/predicate lookups from ontology (from parent class)
        self.metpo_label_to_class = {}
        self.metpo_synonym_to_class = {}
        self.metpo_pattern_to_predicate = {}
        self._load_metpo_lookups()

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

        # GTDB name -> how many member genomes carry each NCBITaxon id. A set
        # here, read back with list(...)[0], picked a taxid in hash order: a
        # fifth of GTDB species carry more than one (species record plus
        # subspecies/strain ids), so ~22% of this transform's edges changed
        # subject on every run (#1006).
        self.gtdb_to_ncbi: Dict[str, Counter] = defaultdict(Counter)
        # Genome accession -> NCBITaxon ID mapping (for cross-database links)
        self.accession_to_ncbi: Dict[str, str] = {}
        # Genome accession -> current GTDB species name (for hierarchical links)
        self.accession_to_gtdb_species: Dict[str, str] = {}
        self.accession_ncbi_conflicts = {}
        self.accession_species_conflicts = {}
        # Track synthetic nodes that need hierarchical edges
        self.synthetic_nodes_metadata: Dict[str, Dict[str, str]] = {}
        self._load_gtdb_to_ncbi_mapping()
        self._load_gtdb_taxonomy()
        # Computed here, while the parent's name -> id map is still loaded:
        # for a GTDB name whose genomes carry several taxids, the id whose
        # NCBITaxon label *is* that name is the species record, and beats the
        # genome-count majority (#1008). Only this small dict travels to the
        # workers; the 925k-entry name map does not.
        # This class re-implements the parent's __init__ by hand and never
        # calls _load_ncbitaxon_labels (its workers never use OAK), so the map
        # is empty here; load it once, in the parent process only, and drop it
        # again below.
        MetaTraitsTransform._load_ncbitaxon_labels(self)
        self.gtdb_preferred_ncbi: Dict[str, str] = {}
        for name, counts in self.gtdb_to_ncbi.items():
            if len(counts) > 1:
                labelled = self.ncbitaxon_name_to_id.get(name.lower())
                if labelled in counts:
                    self.gtdb_preferred_ncbi[name] = labelled
        ambiguous = sum(1 for counts in self.gtdb_to_ncbi.values() if len(counts) > 1)
        print(
            f"  {len(self.gtdb_preferred_ncbi):,} of {ambiguous:,} ambiguous GTDB names have an NCBITaxon "
            "record labelled with that name; it is preferred over the genome-count majority (#1008)"
        )

        # GTDB transform uses GTDB metadata mapping, not OAK adapter
        # Clear the parent's ncbitaxon cache and prevent adapter initialization
        self.ncbitaxon_name_to_id.clear()  # Not needed - we use GTDB mapping
        self._ncbi_adapter = "DISABLED"  # Prevent lazy init - GTDB doesn't need OAK

    def _get_input_file_names(self):
        """
        Override parent to return GTDB-specific input file names.

        :return: List of GTDB metatraits input file names
        """
        return METATRAITS_GTDB_INPUT_FILES

    def _load_gtdb_to_ncbi_mapping(self) -> None:
        """
        Load GTDB species name to NCBITaxon ID mapping from GTDB metadata files.

        Also builds accession-based mapping to resolve species with renamed taxonomy.
        """
        raw_dir = Path(getattr(self, "input_base_dir", RAW_DATA_DIR))
        gtdb_dir = raw_dir / "gtdb"
        taxid_merges = load_taxid_merges(raw_dir)
        self.gtdb_to_ncbi = defaultdict(Counter)
        self.accession_to_ncbi = {}
        self.accession_ncbi_conflicts = {}

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
                        # Retirement precedes genome majority/label selection,
                        # matching canonical GTDB's pre-fan-in normalization.
                        ncbi_taxid = taxid_merges.get(ncbi_taxid, ncbi_taxid)

                        # Extract species name from taxonomy string
                        # Format: d__Bacteria;p__...;s__Species_name
                        if gtdb_taxonomy and ncbi_taxid and ncbi_taxid not in ("none", "NA", ""):
                            ncbi_id = f"NCBITaxon:{ncbi_taxid}"
                            tax_parts = gtdb_taxonomy.split(";")

                            # Extract species (index 6), genus (index 5), family (index 4)
                            if len(tax_parts) >= 7:
                                species = tax_parts[6].replace("s__", "")  # Remove 's__' prefix
                                if species:
                                    self.gtdb_to_ncbi[species][ncbi_id] += 1

                            # Also map genus level (for gtdb_genus_summary.jsonl.gz)
                            if len(tax_parts) >= 6:
                                genus = tax_parts[5].replace("g__", "")
                                if genus:
                                    self.gtdb_to_ncbi[genus][ncbi_id] += 1

                            # Also map family level (for gtdb_family_summary.jsonl.gz)
                            if len(tax_parts) >= 5:
                                family = tax_parts[4].replace("f__", "")
                                if family:
                                    self.gtdb_to_ncbi[family][ncbi_id] += 1

                            # Map genome accession to NCBITaxon for fallback lookup
                            # Accession format: GB_GCA_001788565.1 or RS_GCF_001788565.1
                            # Extract numeric part: 001788565
                            if accession:
                                # Remove prefix (GB_GCA_ or RS_GCF_) and version (.1)
                                acc_parts = accession.replace("GB_GCA_", "").replace("RS_GCF_", "").split(".")[0]
                                # Store with 'sp' prefix for matching metatraits format
                                _register_numeric_candidate(
                                    self.accession_to_ncbi,
                                    self.accession_ncbi_conflicts,
                                    f"sp{acc_parts}",
                                    ncbi_id,
                                )

        ambiguous = sum(1 for counts in self.gtdb_to_ncbi.values() if len(counts) > 1)
        print(f"  Loaded {len(self.gtdb_to_ncbi)} unique GTDB → NCBITaxon name mappings")
        print(
            f"  {ambiguous:,} of them carry more than one NCBI taxid across their genomes; "
            "the taxid most genomes carry is used, ties to the lowest id (#1006)"
        )
        print(f"  Loaded {len(self.accession_to_ncbi)} unique accession → NCBITaxon mappings")

    def _load_gtdb_taxonomy(self) -> None:
        """
        Load GTDB taxonomy to map genome accessions to current species names.

        This enables hierarchical linking of synthetic nodes to GTDB taxonomy.
        """
        # Keep taxonomy and metadata in the same explicitly selected release.
        raw_dir = Path(getattr(self, "input_base_dir", RAW_DATA_DIR))
        gtdb_dir = raw_dir / "gtdb"
        self.accession_to_gtdb_species = {}
        self.accession_species_conflicts = {}

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
                                acc_parts = accession.replace("GB_GCA_", "").replace("RS_GCF_", "").split(".")[0]
                                _register_numeric_candidate(
                                    self.accession_to_gtdb_species,
                                    self.accession_species_conflicts,
                                    f"sp{acc_parts}",
                                    species,
                                )

        print(f"  Loaded {len(self.accession_to_gtdb_species)} unique accession → GTDB species mappings")

    def _get_shared_init_data(self) -> dict:
        """Override to include GTDB-specific data for workers."""
        shared_data = super()._get_shared_init_data()
        shared_data["gtdb_to_ncbi"] = dict(self.gtdb_to_ncbi)  # Convert defaultdict to dict for pickling
        shared_data["gtdb_preferred_ncbi"] = self.gtdb_preferred_ncbi
        shared_data["accession_to_ncbi"] = self.accession_to_ncbi  # Already a dict
        shared_data["accession_to_gtdb_species"] = self.accession_to_gtdb_species  # Already a dict
        return shared_data

    def _init_from_shared_data(self, shared_data: dict) -> None:
        """Override to restore GTDB-specific data in workers."""
        super()._init_from_shared_data(shared_data)

        # Restore GTDB-specific state
        self.gtdb_to_ncbi = defaultdict(Counter, shared_data.get("gtdb_to_ncbi", {}))
        self.gtdb_preferred_ncbi = shared_data.get("gtdb_preferred_ncbi", {})
        self.accession_to_ncbi = shared_data.get("accession_to_ncbi", {})
        self.accession_to_gtdb_species = shared_data.get("accession_to_gtdb_species", {})
        self.synthetic_nodes_metadata = {}  # Will be populated during processing

        # Disable OAK adapter in worker (GTDB uses metadata mapping only)
        self.ncbitaxon_name_to_id.clear()
        self._ncbi_adapter = "DISABLED"

    @staticmethod
    def _pick_ncbi_id(counts: "Counter", preferred: Optional[str] = None) -> str:
        """
        Choose one NCBITaxon id for a GTDB name, deterministically.

        The record whose NCBITaxon label is the GTDB name wins when it is one
        of the candidates (#1008). Otherwise the id most member genomes carry
        -- in practice the species-level record; subspecies and strain ids are
        usually one genome each -- with ties to the lowest numeric id, so the
        answer never depends on iteration order (#1006).

        :param counts: ``{NCBITaxon CURIE: number of genomes}``.
        :param preferred: The species-labelled candidate, if the parent found one.
        :return: The chosen CURIE.
        """
        if preferred is not None and preferred in counts:
            return preferred

        def numeric(curie: str) -> int:
            """Extract the numeric taxid for deterministic lowest-ID tie breaking."""
            tail = curie.rsplit(":", 1)[-1]
            return int(tail) if tail.isdigit() else 0

        return max(counts, key=lambda curie: (counts[curie], -numeric(curie)))

    def _get_ncbitaxon_impl(self):
        """Override parent method - GTDB transform doesn't use OAK adapter."""
        raise NotImplementedError(
            "GTDB transform uses GTDB metadata mapping, not OAK adapter. This method should never be called."
        )

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """
        Retain unmatched source taxon names without asserting historical containment.

        Overrides parent class method. Instead of returning NCBITaxon IDs,
        creates synthetic GTDB: nodes and stores candidate correspondence hints.
        A numeric hint does not prove historical containment or authorize copying
        a current taxon's canonical crosswalk to a distinct historical subject.

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
            return self._pick_ncbi_id(ncbi_ids, self.gtdb_preferred_ncbi.get(search_name))

        # Create synthetic GTDB: node for historical/renamed taxonomy
        if not search_name or search_name.startswith("NCBITaxon:"):
            return None

        # Retain the species rank prefix so the CURIE matches the canonical
        # GTDB scheme emitted by the gtdb transform (GTDB:s__<species>), e.g.
        # GTDB:s__Escherichia_coli. The lookup maps above stay prefix-stripped
        # because they must match the prefix-free metatraits input labels;
        # only the emitted CURIE carries s__. Input is species-level only
        # (gtdb_species_summary.jsonl.gz; genus/family summaries disabled).
        gtdb_id = clean_taxon_name(search_name)
        synthetic_node_id = f"GTDB:s__{gtdb_id}"

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
                "ncbi_taxon": ncbi_id,  # For a canonical GTDB mapping edge
            }

        return synthetic_node_id

    def _load_canonical_ncbi_mappings(self, pairs: Set[Tuple[str, str]]) -> Dict[Tuple[str, str], Tuple[str, str]]:
        """
        Read requested mapping decisions from the canonical GTDB transform.

        The #883 fan-in rule uses *all* GTDB taxa, not just the historical
        taxa in this input. Recomputing it over synthetic nodes or counting
        genomes instead of taxa would silently strengthen broad_match back
        to close_match. Reuse the exact upstream pair and relation instead;
        an absent pair supplies no evidence for a cross-database assertion.

        The edge file is streamed and only requested pairs are retained.
        """
        edge_file = self.output_base_dir / GTDB / "edges.tsv"
        if not edge_file.is_file():
            raise FileNotFoundError(
                f"Canonical GTDB mappings not found at {edge_file}. Run the gtdb transform before metatraits_gtdb."
            )
        expected_relations = {
            CLOSE_MATCH_PREDICATE: CLOSE_MATCH_RELATION,
            BROAD_MATCH_PREDICATE: BROAD_MATCH_RELATION,
        }
        mappings = {}
        self._canonical_mapping_evidence = {}
        with self.consume_input(CANONICAL_MAPPING_INPUT, edge_file) as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
            required = {SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN}
            if (
                not reader.fieldnames
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or not required <= set(reader.fieldnames)
            ):
                raise ValueError("Malformed canonical GTDB mapping header")
            for edge in reader:
                if None in edge or None in edge.values():
                    raise ValueError("Malformed canonical GTDB mapping row")
                pair = (edge[SUBJECT_COLUMN], edge[OBJECT_COLUMN])
                if pair not in pairs:
                    continue
                predicate = edge[PREDICATE_COLUMN]
                relation = edge[RELATION_COLUMN]
                if predicate not in expected_relations or relation != expected_relations[predicate]:
                    raise ValueError(f"Invalid canonical GTDB mapping for {pair}: {predicate} / {relation}")
                mapping = (predicate, relation)
                if pair in mappings and mappings[pair] != mapping:
                    raise ValueError(f"Conflicting canonical GTDB mappings for {pair}")
                mappings[pair] = mapping
                self._canonical_mapping_evidence.setdefault(pair, []).append(dict(edge))
        return mappings

    def _create_hierarchical_edges(self) -> None:
        """
        Audit unproven historical bridges; retain only exact-current crosswalks.

        A numeric accession hint establishes neither taxon containment nor a
        portable SKOS match. Preserve proposed inferences as producer audit rows,
        not graph edges. Existing trait observations and declarations are untouched.

        Note: Reads synthetic nodes from output file since worker metadata is not
        available in main process after multiprocessing.
        """
        import re

        print("\n  Reviewing historical GTDB correspondence hints...")

        # Read synthetic nodes from output file (since worker metadata not available)
        synthetic_nodes = []
        with open(self.output_node_file, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                node_id = row[ID_COLUMN]
                if node_id.startswith("GTDB:"):
                    # Extract original name from node
                    name = row.get(NAME_COLUMN, node_id.replace("GTDB:", "").replace("_", " "))
                    synthetic_nodes.append({"id": node_id, "name": name, "row": dict(row)})

        print(f"  Found {len(synthetic_nodes)} synthetic GTDB nodes")

        hierarchical_edges = []
        mapping_candidates = []
        audit_rows = {}
        provenance = {
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: self.knowledge_source,
            KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
            AGENT_TYPE_COLUMN: AUTOMATED_AGENT,
        }

        # Create edges for each synthetic node
        for node_info in synthetic_nodes:
            node_id = node_info["id"]
            name = node_info["name"]
            if node_id in audit_rows:
                raise ValueError(f"Duplicate source GTDB node in historical bridge input: {node_id}")

            # Extract accession from name
            accession_match = re.search(r"\bsp\d{9}\b", name)
            if not accession_match:
                audit_rows[node_id] = {
                    "subject": node_id,
                    "original_node_json": json.dumps(node_info["row"], sort_keys=True),
                    "accession_hint": "",
                    "candidate_species_json": "[]",
                    "candidate_ncbi_json": "[]",
                    "proposed_edges_json": "[]",
                    "canonical_evidence_json": "[]",
                    "disposition": "unresolved_no_numeric_hint",
                    "reason": "Source observations retained; no historical correspondence evidence.",
                }
                continue

            accession = accession_match.group(0)

            # Look up current GTDB species and NCBITaxon
            current_species = self.accession_to_gtdb_species.get(accession)
            ncbi_taxon = self.accession_to_ncbi.get(accession)
            species_conflicts = getattr(self, "accession_species_conflicts", {}).get(accession, set())
            ncbi_conflicts = getattr(self, "accession_ncbi_conflicts", {}).get(accession, set())
            proposed = []
            audit = {
                "subject": node_id,
                "original_node_json": json.dumps(node_info["row"], sort_keys=True),
                "accession_hint": accession,
                "candidate_species_json": json.dumps(
                    sorted(species_conflicts or ([current_species] if current_species else []))
                ),
                "candidate_ncbi_json": json.dumps(sorted(ncbi_conflicts or ([ncbi_taxon] if ncbi_taxon else []))),
                "proposed_edges_json": "[]",
                "canonical_evidence_json": "[]",
                "disposition": "quarantined_ambiguous_numeric_hint"
                if species_conflicts or ncbi_conflicts
                else "unresolved_no_current_species",
                "reason": "A numeric name token is not an assembly identity or a taxon-containment assertion.",
            }
            audit_rows[node_id] = audit

            # Preserve the formerly invented subclass proposal only in the audit.
            if current_species:
                current_id = f"GTDB:s__{clean_taxon_name(current_species)}"
                # A missing direct NCBI mapping does not establish that the
                # source GTDB name is historical. Retain its declaration and
                # observations without asserting a reflexive subclass route.
                if node_id != current_id:
                    proposed.append(
                        {
                            SUBJECT_COLUMN: node_id,
                            PREDICATE_COLUMN: SUBCLASS_PREDICATE,
                            # s__ prefix matches the canonical gtdb-transform CURIE
                            # scheme (GTDB:s__<species>) so this subClassOf edge lands
                            # on a real GTDB taxonomy node in the merged graph.
                            OBJECT_COLUMN: current_id,
                            RELATION_COLUMN: RDFS_SUBCLASS_OF,
                            **provenance,
                        }
                    )
                    if not (species_conflicts or ncbi_conflicts):
                        audit["disposition"] = "quarantined_unsupported_historical_bridge"
                elif not (species_conflicts or ncbi_conflicts):
                    audit["disposition"] = "exact_current_subject_no_self_hierarchy"
                audit["proposed_edges_json"] = json.dumps(proposed, sort_keys=True)
                # Inspect canonical evidence, but it cannot authorize substituting
                # a distinct source subject for the canonical assertion's subject.
                if ncbi_taxon:
                    mapping_candidates.append((node_id, current_id, ncbi_taxon))

        # Preserve GTDB's whole-release fan-in decision only for the identical subject.
        # Ambiguous numeric hints must retain canonical candidate evidence too.
        # These combinations are lookup requests, not newly asserted matches.
        audit_pairs = {
            subject: {
                (f"GTDB:s__{clean_taxon_name(species)}", ncbi)
                for species in json.loads(audit["candidate_species_json"])
                for ncbi in json.loads(audit["candidate_ncbi_json"])
            }
            for subject, audit in audit_rows.items()
        }
        mappings = self._load_canonical_ncbi_mappings(set().union(*audit_pairs.values()))
        for subject, pairs in audit_pairs.items():
            evidence = [row for pair in sorted(pairs) for row in self._canonical_mapping_evidence.get(pair, [])]
            audit_rows[subject]["canonical_evidence_json"] = json.dumps(evidence, sort_keys=True)
        missing_mappings = 0
        for node_id, current_id, ncbi_taxon in mapping_candidates:
            mapping = mappings.get((current_id, ncbi_taxon))
            if mapping is None:
                missing_mappings += 1
                continue
            predicate, relation = mapping
            proposed_mapping = {
                SUBJECT_COLUMN: node_id,
                PREDICATE_COLUMN: predicate,
                OBJECT_COLUMN: ncbi_taxon,
                RELATION_COLUMN: relation,
                **provenance,
                # GTDB's fan-in-derived similarity is a prediction. A
                # historical subject supplies no stronger direct evidence.
                KNOWLEDGE_LEVEL_COLUMN: PREDICTION,
            }
            audit = audit_rows[node_id]
            if node_id == current_id:
                hierarchical_edges.append(proposed_mapping)
                audit["disposition"] = "retained_exact_current_subject_mapping"
                audit["reason"] = (
                    "Canonical GTDB assertion has the same subject and object; no historical substitution."
                )
            else:
                proposed = json.loads(audit["proposed_edges_json"])
                proposed.append(proposed_mapping)
                audit["proposed_edges_json"] = json.dumps(proposed, sort_keys=True)

        audit_file = self.output_dir / HISTORICAL_BRIDGE_AUDIT
        with atomic_write(audit_file, encoding="utf-8", newline="") as handle:
            writer = tsv_dict_writer(handle, fieldnames=BRIDGE_AUDIT_COLUMNS)
            writer.writeheader()
            writer.writerows(audit_rows.values())
        self.record_producer_audit(HISTORICAL_BRIDGE_AUDIT)
        print(
            f"  Audited {len(audit_rows)} GTDB source nodes; retained {len(hierarchical_edges)} exact-current mappings:"
        )
        print(f"    - {sum(1 for e in hierarchical_edges if 'subClassOf' in e[RELATION_COLUMN])} subClassOf edges")
        for predicate in (CLOSE_MATCH_PREDICATE, BROAD_MATCH_PREDICATE):
            print(f"    - {sum(e[PREDICATE_COLUMN] == predicate for e in hierarchical_edges)} {predicate} edges")
        if missing_mappings:
            print(f"    - {missing_mappings} NCBI links skipped: no matching canonical GTDB mapping")

        # Append to existing edge file
        if hierarchical_edges:
            with open(self.output_edge_file, "a") as f:
                writer = tsv_dict_writer(f, fieldnames=self.edge_header)
                for edge in hierarchical_edges:
                    # Fill in missing columns with empty strings
                    for col in self.edge_header:
                        if col not in edge:
                            edge[col] = ""
                    writer.writerow(edge)

            print(f"  ✅ Appended {len(hierarchical_edges)} edges to {self.output_edge_file.name}")
        else:
            print("  No additional canonical mappings; unsupported historical bridges are audit-only")

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

        # Call parent class run() method
        # The parent class will use our overridden _get_input_file_names()
        # to get the GTDB-specific file list without mutating module-level globals
        # We've also overridden _search_ncbitaxon_by_label() to use GTDB mapping
        super().run(data_file=data_file, show_status=show_status)

        # Create hierarchical edges for synthetic GTDB nodes
        self._create_hierarchical_edges()

        print("\n✅ GTDB metatraits transform complete!")
        print(f"   Output: {self.output_dir}")
        print(f"   Nodes: {self.output_node_file}")
        print(f"   Edges: {self.output_edge_file}")
