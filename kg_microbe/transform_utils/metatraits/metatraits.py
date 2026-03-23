"""
Metatraits transform class.

Reads metatraits summary JSONL files from data/raw, resolves taxon names to NCBITaxon IDs,
maps trait names to METPO/ontology terms, and outputs KGX nodes.tsv and edges.tsv.
"""

import csv
import gzip
import json
import multiprocessing
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd
import yaml
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    BIOLOGICAL_PROCESS,
    CURIE_COLUMN,
    CUSTOM_CURIES_YAML_FILE,
    HAS_PHENOTYPE,
    ID_COLUMN,
    METATRAITS,
    NCBI_CATEGORY,
    NCBITAXON_NODES_FILE,
    NCBITAXON_SOURCE,
    OBSERVATION,
    RAW_DATA_DIR,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings, uri_to_curie
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings
from kg_microbe.utils.oak_utils import search_by_label
from kg_microbe.utils.pandas_utils import drop_duplicates

# METPO predicate -> biolink predicate (for relation lookup)
METPO_TO_BIOLINK_PREDICATE = {
    # Capability and phenotype
    "METPO:2000101": "biolink:has_attribute",  # has quality
    "METPO:2000102": "biolink:has_phenotype",  # has phenotype
    "METPO:2000103": "biolink:capable_of",  # capable of
    # Chemical interactions (positive)
    "METPO:2000001": "biolink:interacts_with",  # organism interacts with chemical
    "METPO:2000002": "biolink:interacts_with",  # assimilates
    "METPO:2000003": "biolink:produces",  # builds acid from
    "METPO:2000004": "biolink:produces",  # builds base from
    "METPO:2000005": "biolink:produces",  # builds gas from
    "METPO:2000006": "biolink:capable_of",  # uses as carbon source
    "METPO:2000007": "biolink:capable_of",  # degrades
    "METPO:2000008": "biolink:capable_of",  # uses as electron acceptor
    "METPO:2000009": "biolink:capable_of",  # uses as electron donor
    "METPO:2000010": "biolink:capable_of",  # uses as energy source
    "METPO:2000011": "biolink:capable_of",  # ferments
    "METPO:2000012": "biolink:capable_of",  # uses for growth
    "METPO:2000013": "biolink:capable_of",  # hydrolyzes
    "METPO:2000014": "biolink:capable_of",  # uses as nitrogen source
    "METPO:2000015": "biolink:interacts_with",  # uses in other way
    "METPO:2000016": "biolink:capable_of",  # oxidizes
    "METPO:2000017": "biolink:capable_of",  # reduces
    "METPO:2000018": "biolink:capable_of",  # requires for growth
    "METPO:2000020": "biolink:capable_of",  # uses as sulfur source
    # Chemical interactions (negative)
    "METPO:2000027": "biolink:interacts_with",  # does not assimilate
    "METPO:2000028": "biolink:produces",  # does not build acid from
    "METPO:2000031": "biolink:capable_of",  # does not use as carbon source
    "METPO:2000037": "biolink:capable_of",  # does not ferment
    "METPO:2000038": "biolink:capable_of",  # does not use for growth
    "METPO:2000039": "biolink:capable_of",  # does not hydrolyze
    "METPO:2000044": "biolink:capable_of",  # does not reduce
    "METPO:2000046": "biolink:capable_of",  # does not use for respiration
    # Production
    "METPO:2000202": "biolink:produces",  # produces
    "METPO:2000222": "biolink:produces",  # does not produce
    # Enzyme activity
    "METPO:2000302": "biolink:capable_of",  # shows activity of
    "METPO:2000303": "biolink:capable_of",  # does not show activity of
    # Growth medium
    "METPO:2000517": "biolink:capable_of",  # grows in
    "METPO:2000518": "biolink:capable_of",  # does not grow in
}

# Biolink predicate -> RO relation
PREDICATE_TO_RELATION = {
    "biolink:produces": "RO:0002234",
    "biolink:capable_of": BIOLOGICAL_PROCESS,
    "biolink:has_phenotype": HAS_PHENOTYPE,
    "biolink:has_attribute": "RO:0000086",  # has quality
    "biolink:interacts_with": "RO:0002434",  # interacts with
}

# Input file names (transform accepts either ncbi_* or metatraits_* convention)
METATRAITS_INPUT_FILES = [
    "ncbi_species_summary.jsonl.gz",
    "ncbi_genus_summary.jsonl.gz",
    "ncbi_family_summary.jsonl.gz",
    "metatraits_species_summary.jsonl.gz",
    "metatraits_genus_summary.jsonl.gz",
    "metatraits_family_summary.jsonl.gz",
]


def _get_ncbitaxon_adapter():
    """Get OAK adapter for NCBITaxon; use pre-built sqlite:obo:ncbitaxon if local source invalid."""
    # Use .db file instead of .owl (NCBITAXON_SOURCE points to .owl)
    local_db = NCBITAXON_SOURCE.parent / "ncbitaxon.db"

    # Try local database first, fall back to remote if corrupted/missing
    if local_db.exists():
        local_path = f"sqlite:{local_db}"
        try:
            adapter = get_adapter(local_path)
            # Verify adapter works (e.g. has statements table)
            list(adapter.basic_search("Bacteria", limit=1))
            print(f"  Using local NCBITaxon database: {local_db}")
            return adapter
        except Exception as e:
            print(f"  Local NCBITaxon database invalid ({e.__class__.__name__}), using remote fallback")

    # Fallback: download pre-built OBO database (~2GB)
    print("  Downloading NCBITaxon database from OBO library (this may take a few minutes)...")
    return get_adapter("sqlite:obo:ncbitaxon")


def _open_jsonl(path: Path):
    """
    Open JSONL file; use gzip for .gz files, plain text otherwise.

    If a .gz file is not actually gzip-compressed (e.g. misnamed plain JSON),
    falls back to plain text.
    """
    if path.name.endswith(".gz"):
        try:
            f = gzip.open(path, "rt", encoding="utf-8")
            f.read(1)  # Trigger gzip header read
            f.seek(0)
            return f
        except gzip.BadGzipFile:
            return open(path, "r", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def _process_file_worker(args: Tuple[Path, Path, Dict[str, Any], bool]) -> Dict[str, Any]:
    """
    Worker function for parallel file processing.

    Must be module-level for multiprocessing pickle support.

    :param args: Tuple of (input_file, temp_dir, shared_init_data, show_status)
    :return: Dictionary with processing results
    """
    input_file, temp_dir, shared_init, show_status = args

    # Reconstruct transform instance in worker process
    transform = MetaTraitsTransform.__new__(MetaTraitsTransform)
    transform._init_from_shared_data(shared_init)

    # Process file
    result = transform._process_single_file(input_file, temp_dir, show_status)

    return result


class _StreamingRowWriter:

    """Streaming TSV writer that writes rows incrementally to avoid memory accumulation."""

    def __init__(self, output_file: Path, header: List[str]):
        """
        Initialize streaming writer.

        :param output_file: Path to output TSV file
        :param header: Column header list
        """
        self.output_file = output_file
        self.header = header
        self.file_handle = None
        self.writer = None

    def __enter__(self):
        """Open file and write header."""
        self.output_file.parent.mkdir(exist_ok=True, parents=True)
        self.file_handle = open(self.output_file, "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file_handle, delimiter="\t")
        self.writer.writerow(self.header)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close file handle."""
        if self.file_handle:
            self.file_handle.close()

    def write_row(self, row: List):
        """Write a single row to the TSV file."""
        if self.writer:
            self.writer.writerow(row)


class MetaTraitsTransform(Transform):

    """Transform metatraits summary JSONL files into KGX nodes and edges."""

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        use_multiprocessing: bool = True,
        num_workers: Optional[int] = None,
    ):
        """
        Initialize MetaTraitsTransform.

        :param input_dir: Input directory (default: data/raw)
        :param output_dir: Output directory (default: data/transformed)
        :param use_multiprocessing: Enable parallel processing (default: True)
        :param num_workers: Number of workers (default: auto-detect from resources)
        """
        super().__init__(METATRAITS, input_dir, output_dir)
        self.edge_header = self.edge_header + ["has_percentage"]
        self.knowledge_source = "infores:metatraits"
        self.microbial_mappings = load_microbial_trait_mappings()
        self.metpo_mappings = load_metpo_mappings("madin synonym or field")

        # Initialize unified chemical mapping loader for ChEBI lookups
        try:
            self.chemical_loader = ChemicalMappingLoader()
        except (FileNotFoundError, ImportError) as e:
            print(f"  Warning: Could not load unified chemical mappings: {e}")
            self.chemical_loader = None

        # Defer adapter creation until first cache miss (avoids ~2GB download when
        # ncbitaxon_nodes.tsv has full coverage)
        self._ncbi_adapter = None

        # Taxon name -> NCBITaxon ID cache
        self.ncbitaxon_name_to_id: Dict[str, str] = {}
        self._load_ncbitaxon_labels()

        # Trait name -> (curie, category, predicate) from METPO + custom_curies (fallback)
        self.trait_mapping: Dict[str, dict] = {}
        self._build_trait_mapping()

        self.unmapped_traits_file = self.output_dir / "unmapped_traits.tsv"
        self.unresolved_taxa_file = self.output_dir / "unresolved_taxa.tsv"

        # Multiprocessing configuration
        self.use_multiprocessing = use_multiprocessing
        self.num_workers = num_workers

    def _load_ncbitaxon_labels(self) -> None:
        """Load NCBITaxon labels from ontologies output, data/raw, or OAK fallback."""
        # Prefer ontologies transform output, then data/raw/ncbitaxon_nodes.tsv (manual placement)
        for path in [NCBITAXON_NODES_FILE, RAW_DATA_DIR / "ncbitaxon_nodes.tsv"]:
            if path.exists():
                try:
                    with open(path) as f:
                        f.readline()  # skip header
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 3:
                                node_id = parts[0]
                                name = parts[2]
                                if node_id.startswith("NCBITaxon:") and name:
                                    self.ncbitaxon_name_to_id[name.lower()] = node_id
                    print(f"  Loaded {len(self.ncbitaxon_name_to_id)} NCBITaxon labels from {path.name}")
                    return
                except Exception as e:
                    print(f"Warning: Could not load NCBITaxon labels from {path}: {e}")

    def _get_ncbitaxon_impl(self):
        """Return OAK adapter for NCBITaxon, creating it on first use."""
        if self._ncbi_adapter is None:
            self._ncbi_adapter = _get_ncbitaxon_adapter()
        return self._ncbi_adapter

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """Resolve taxon name to NCBITaxon ID. Caches OAK results to avoid repeated lookups."""
        key = search_name.lower()
        ncbitaxon_id = self.ncbitaxon_name_to_id.get(key)
        if ncbitaxon_id:
            return ncbitaxon_id
        results = search_by_label(self._get_ncbitaxon_impl(), search_name, limit=1)
        if results:
            ncbitaxon_id = results[0]
            self.ncbitaxon_name_to_id[key] = ncbitaxon_id
            return ncbitaxon_id
        return None

    def _build_trait_mapping(self) -> None:
        """Build trait name -> (curie, category, predicate) from METPO and custom_curies."""
        for synonym, metpo_data in self.metpo_mappings.items():
            category_url = metpo_data.get("inferred_category", "")
            category = uri_to_curie(category_url) if category_url else "biolink:PhenotypicQuality"
            predicate_biolink = metpo_data.get("predicate_biolink_equivalent", "")
            predicate = uri_to_curie(predicate_biolink) if predicate_biolink else "biolink:has_phenotype"
            self.trait_mapping[synonym] = {
                "curie": metpo_data["curie"],
                "category": category,
                "name": metpo_data["label"],
                "predicate": predicate,
            }
            self.trait_mapping[synonym.lower()] = self.trait_mapping[synonym]

        if CUSTOM_CURIES_YAML_FILE.exists():
            with open(CUSTOM_CURIES_YAML_FILE) as f:
                custom_data = yaml.safe_load(f)
            custom_map = {
                k: v for first in (custom_data or {}).values() if isinstance(first, dict) for k, v in first.items()
            }
            for key, value in custom_map.items():
                if not isinstance(value, dict):
                    continue
                if key not in self.trait_mapping and key.lower() not in self.trait_mapping:
                    curie = value.get("curie") or value.get(CURIE_COLUMN)
                    if curie:
                        self.trait_mapping[key] = {
                            "curie": curie,
                            "category": value.get("category", "biolink:PhenotypicQuality"),
                            "name": value.get("name", key),
                            "predicate": value.get("predicate", "biolink:has_phenotype"),
                        }
                        self.trait_mapping[key.lower()] = self.trait_mapping[key]

    def _resolve_chemical_trait(self, trait_name: str) -> Optional[dict]:
        """
        Resolve chemical-related trait names to ChEBI IDs using unified mappings.

        Handles patterns like:
        - "carbon source: glucose" -> CHEBI:17234
        - "produces: ethanol" -> CHEBI:16236
        - "ferments: lactose" -> CHEBI:17716

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        # Extract chemical name and predicate from common patterns
        patterns = [
            (r"^carbon source:\s*(.+)$", "METPO:2000006"),  # uses as carbon source
            (r"^produces:\s*(.+)$", "METPO:2000202"),  # produces
            (r"^ferments:\s*(.+)$", "METPO:2000011"),  # ferments
            (r"^hydrolyzes:\s*(.+)$", "METPO:2000013"),  # hydrolyzes
            (r"^oxidizes:\s*(.+)$", "METPO:2000016"),  # oxidizes
            (r"^reduces:\s*(.+)$", "METPO:2000017"),  # reduces
            (r"^degrades:\s*(.+)$", "METPO:2000007"),  # degrades
            (r"^utilizes:\s*(.+)$", "METPO:2000001"),  # organism interacts with chemical
        ]

        for pattern, metpo_predicate in patterns:
            match = re.match(pattern, trait_name.lower())
            if match:
                chemical_name = match.group(1).strip()
                chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)
                if chebi_id:
                    canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name or chemical_name,
                        "predicate": metpo_predicate,
                    }

        return None

    def _resolve_metabolic_trait(self, trait_name: str) -> Optional[dict]:
        """
        Resolve metabolic process trait names (electron acceptors, respiration, reduction, oxidation, etc.).

        Handles patterns like:
        - "electron acceptor: sulfate" -> CHEBI:16189
        - "respiration: nitrate" -> CHEBI:17632
        - "reduction: elemental sulfur" -> CHEBI:26833
        - "oxidation: methanol" -> CHEBI:17790
        - "denitrification: nitrate" -> CHEBI:17632
        - "degradation: cellulose" -> CHEBI:18246
        - "hydrolysis: urea" -> CHEBI:16199

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        # Patterns: (regex, METPO_predicate, lookup_type)
        # lookup_type: "chemical" = ChEBI, "material" = ChEBI or ENVO
        patterns = [
            # Electron acceptors → METPO:2000008 (uses as electron acceptor)
            (r"^electron acceptor:\s*(.+)$", "METPO:2000008", "chemical"),
            # Respiration → METPO:2000008 (respiration uses electron acceptor)
            (r"^respiration:\s*(.+)$", "METPO:2000008", "chemical"),
            # Reduction → METPO:2000017 (reduces)
            (r"^reduction:\s*(.+)$", "METPO:2000017", "chemical"),
            # Oxidation → METPO:2000016 (oxidizes)
            (r"^oxidation:\s*(.+)$", "METPO:2000016", "chemical"),
            (r"^oxidation in darkness:\s*(.+)$", "METPO:2000016", "chemical"),
            # Denitrification → METPO:2000017 (reduces nitrate/nitrite/N2O)
            (r"^denitrification:\s*(.+)$", "METPO:2000017", "chemical"),
            # Ammonification → METPO:2000014 (uses as nitrogen source)
            (r"^ammonification:\s*(.+)$", "METPO:2000014", "chemical"),
            # Degradation → METPO:2000007 (degrades)
            (r"^degradation:\s*(.+)$", "METPO:2000007", "material"),
            # Hydrolysis → METPO:2000013 (hydrolyzes) - extend existing
            (r"^hydrolysis:\s*(.+)$", "METPO:2000013", "material"),
        ]

        for pattern, metpo_predicate, lookup_type in patterns:
            match = re.match(pattern, trait_name.lower())
            if match:
                substance_name = match.group(1).strip()

                # Try ChEBI lookup first
                chebi_id = self.chemical_loader.find_chebi_by_name(substance_name)
                if chebi_id:
                    canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name or substance_name,
                        "predicate": metpo_predicate,
                    }

                # If ChEBI lookup fails for materials, return None (let fallback handle it)
                # or create custom CURIE for well-known materials
                if lookup_type == "material":
                    # Common materials without ChEBI IDs
                    material_mappings = {
                        "urea": ("CHEBI:16199", "urea"),
                        "casein": ("KGM:casein", "casein"),  # protein mixture, no ChEBI
                        "gelatin": ("KGM:gelatin", "gelatin"),  # protein mixture, no ChEBI
                        "esculin": ("CHEBI:4806", "esculin"),
                        "starch": ("CHEBI:28017", "starch"),
                    }
                    if substance_name in material_mappings:
                        curie, name = material_mappings[substance_name]
                        return {
                            "curie": curie,
                            "category": "biolink:ChemicalSubstance",
                            "name": name,
                            "predicate": metpo_predicate,
                        }

        return None

    def _resolve_growth_substrate(self, trait_name: str) -> Optional[dict]:
        """
        Resolve growth substrate patterns (growth, fermentation, acid production).

        Handles patterns like:
        - "growth: cellobiose" -> CHEBI:17057
        - "fermentation: lactose" -> CHEBI:17716 (already handled by chemical resolver)
        - "builds acid from: glucose" -> CHEBI:17234

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        patterns = [
            (r"^growth:\s*(.+)$", "METPO:2000012"),  # uses for growth
            (r"^builds acid from:\s*(.+)$", "METPO:2000003"),  # builds acid from
        ]

        for pattern, metpo_predicate in patterns:
            match = re.match(pattern, trait_name.lower())
            if match:
                substrate_name = match.group(1).strip()

                # Skip non-chemical growth patterns (trophic modes)
                non_chemical_patterns = [
                    "phototrophy",
                    "chemoheterotrophy",
                    "photoautotrophy",
                    "photoheterotrophy",
                    "anoxygenic photoautotrophy",
                    "anoxygenic phototrophy",
                ]
                if substrate_name in non_chemical_patterns:
                    return None

                # Try ChEBI lookup
                chebi_id = self.chemical_loader.find_chebi_by_name(substrate_name)
                if chebi_id:
                    canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name or substrate_name,
                        "predicate": metpo_predicate,
                    }

        return None

    def _resolve_trophic_mode(self, trait_name: str) -> Optional[dict]:
        """
        Resolve trophic mode and growth type patterns.

        Handles patterns like:
        - "growth: phototrophy" -> GO:0009579
        - "growth: chemoheterotrophy" -> GO:0044281
        - "aerobic growth: ..." -> aerobe phenotype
        - "anaerobic growth: ..." -> anaerobe phenotype

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        import re

        # Trophic mode mappings (growth: X where X is a trophic mode)
        trophic_mappings = {
            "phototrophy": ("GO:0009579", "phototrophic process", "biolink:BiologicalProcess"),
            "chemoheterotrophy": (
                "GO:0044281",
                "small molecule metabolic process",
                "biolink:BiologicalProcess",
            ),
            "photoautotrophy": (
                "GO:0009541",
                "photoautotrophic process",
                "biolink:BiologicalProcess",
            ),
            "photoheterotrophy": (
                "GO:0009581",
                "photoheterotrophic process",
                "biolink:BiologicalProcess",
            ),
            "anoxygenic photoautotrophy": (
                "GO:0019685",
                "photosynthesis, anoxygenic",
                "biolink:BiologicalProcess",
            ),
            "anoxygenic phototrophy": (
                "GO:0019685",
                "photosynthesis, anoxygenic",
                "biolink:BiologicalProcess",
            ),
        }

        # Pattern: growth: [trophic_mode]
        match = re.match(r"^growth:\s*(.+)$", trait_name.lower())
        if match:
            mode = match.group(1).strip()
            if mode in trophic_mappings:
                curie, name, category = trophic_mappings[mode]
                return {
                    "curie": curie,
                    "category": category,
                    "name": name,
                    "predicate": "METPO:2000103",  # capable of
                }

        # Pattern: aerobic growth / anaerobic growth
        if trait_name.lower().startswith("aerobic growth"):
            return {
                "curie": "METPO:1001003",  # aerobe phenotype
                "category": "biolink:PhenotypicQuality",
                "name": "aerobe",
                "predicate": "METPO:2000102",  # has phenotype
            }
        elif trait_name.lower().startswith("anaerobic growth"):
            return {
                "curie": "METPO:1001004",  # anaerobe phenotype
                "category": "biolink:PhenotypicQuality",
                "name": "anaerobe",
                "predicate": "METPO:2000102",  # has phenotype
            }

        return None

    def _resolve_enzyme_activity(self, trait_name: str) -> Optional[dict]:
        """
        Resolve enzyme activity patterns with or without EC numbers.

        Handles patterns like:
        - "enzyme activity: alkaline phosphatase (EC3.1.3.1)" -> EC:3.1.3.1
        - "enzyme activity: DNase" -> lookup by name (fallback to trait mapping)

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        import re

        # Pattern: enzyme activity: [name] (EC[number])
        ec_match = re.match(r"^enzyme activity:\s*(.+?)\s*\(EC\s*([\d.]+)\)\s*$", trait_name, re.IGNORECASE)
        if ec_match:
            enzyme_name = ec_match.group(1).strip()
            ec_number = ec_match.group(2).strip()
            return {
                "curie": f"EC:{ec_number}",
                "category": "biolink:MolecularActivity",
                "name": enzyme_name,
                "predicate": "METPO:2000302",  # shows activity of
            }

        # Pattern: enzyme activity: [name] (without EC number)
        # Let this fall through to trait_mapping or return None
        # This allows METPO mappings to handle non-EC enzyme activities
        return None

    def _resolve_phenotype_trait(self, trait_name: str) -> Optional[dict]:
        """
        Resolve simple phenotype traits.

        Handles patterns like:
        - "aerotolerant" -> METPO:1001025
        - "facultative anaerobe" -> METPO:1001026
        - "acidophilic" -> METPO phenotype

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        # Simple phenotype mappings
        phenotype_mappings = {
            "aerotolerant": ("METPO:1001025", "aerotolerant"),
            "facultative anaerobe": ("METPO:1001026", "facultative anaerobe"),
            "acidophilic": ("METPO:1001015", "acidophile"),
            "capnophilic": ("KGM:capnophilic", "capnophilic"),  # No METPO ID
        }

        normalized = trait_name.lower().strip()
        if normalized in phenotype_mappings:
            curie, name = phenotype_mappings[normalized]
            return {
                "curie": curie,
                "category": "biolink:PhenotypicQuality",
                "name": name,
                "predicate": "METPO:2000102",  # has phenotype
            }

        return None

    def _create_node_row(
        self,
        node_id: str,
        category: str,
        name: str,
        description: Optional[str] = None,
        xref: Optional[str] = None,
        synonym: Optional[str] = None,
        same_as: Optional[str] = None,
    ) -> List:
        """Create a node row matching node_header."""
        node_row = [None] * len(self.node_header)
        node_row[0] = node_id
        node_row[1] = category
        node_row[2] = name
        node_row[3] = description
        node_row[4] = xref
        node_row[5] = self.knowledge_source
        node_row[6] = synonym
        node_row[7] = same_as
        return node_row

    def _to_biolink_predicate(self, predicate: str) -> str:
        """Map METPO or other predicate to biolink predicate for relation lookup."""
        if predicate.startswith("biolink:"):
            return predicate
        return METPO_TO_BIOLINK_PREDICATE.get(predicate, "biolink:has_phenotype")

    def _get_relation_for_predicate(self, predicate: str) -> str:
        """Return RO relation for a given predicate (preserves produces/capable_of/has_phenotype)."""
        biolink_pred = self._to_biolink_predicate(predicate)
        return PREDICATE_TO_RELATION.get(biolink_pred, HAS_PHENOTYPE)

    def _calculate_optimal_workers(self, input_files: List[Path]) -> int:
        """
        Calculate optimal number of workers based on system resources.

        :param input_files: List of input files to process
        :return: Optimal number of parallel workers
        """
        # Check environment variable override first
        if os.environ.get("METATRAITS_WORKERS"):
            try:
                workers = int(os.environ["METATRAITS_WORKERS"])
                print(f"  Using METATRAITS_WORKERS environment variable: {workers} workers")
                return workers
            except ValueError:
                print("  Warning: Invalid METATRAITS_WORKERS value, using auto-detection")

        try:
            import psutil

            cpu_cores = multiprocessing.cpu_count()
            max_cpu_workers = max(1, cpu_cores - 1)

            # Estimate 3GB per worker (OAK adapter ~2GB + overhead)
            available_memory_gb = psutil.virtual_memory().available / (1024**3)
            max_memory_workers = max(1, int(available_memory_gb / 3))

            max_file_workers = len(input_files)

            optimal = min(max_cpu_workers, max_memory_workers, max_file_workers)

            print("  Resource-aware worker selection:")
            print(f"    CPU cores: {cpu_cores} → max {max_cpu_workers} workers")
            print(f"    Available memory: {available_memory_gb:.1f}GB → max {max_memory_workers} workers")
            print(f"    Input files: {max_file_workers}")
            print(f"    Selected: {optimal} parallel workers")

            return optimal

        except ImportError:
            print("  Warning: psutil not installed, using CPU count only")
            cpu_cores = multiprocessing.cpu_count()
            optimal = min(max(1, cpu_cores - 1), len(input_files))
            print(f"    CPU cores: {cpu_cores} → using {optimal} workers")
            return optimal

    def _get_shared_init_data(self) -> Dict[str, Any]:
        """
        Get read-only initialization data for workers.

        :return: Dictionary with shared initialization data
        """
        return {
            "input_base_dir": str(self.input_base_dir),
            "output_dir": str(self.output_dir),
            "knowledge_source": self.knowledge_source,
            "ncbitaxon_name_to_id": self.ncbitaxon_name_to_id,
            "trait_mapping": self.trait_mapping,
            "microbial_mappings": self.microbial_mappings,
            "metpo_mappings": self.metpo_mappings,
            # Note: chemical_loader not included (too large, reconstruct in worker)
        }

    def _init_from_shared_data(self, shared_data: Dict[str, Any]) -> None:
        """
        Initialize transform instance in worker from shared data.

        :param shared_data: Shared initialization data from main process
        """
        self.input_base_dir = Path(shared_data["input_base_dir"])
        self.output_dir = Path(shared_data["output_dir"])
        self.knowledge_source = shared_data["knowledge_source"]
        self.ncbitaxon_name_to_id = shared_data["ncbitaxon_name_to_id"]
        self.trait_mapping = shared_data["trait_mapping"]
        self.microbial_mappings = shared_data["microbial_mappings"]
        self.metpo_mappings = shared_data["metpo_mappings"]

        # Reconstruct chemical loader (too large to pickle efficiently)
        try:
            self.chemical_loader = ChemicalMappingLoader()
        except Exception:
            self.chemical_loader = None

        # Worker-local state
        self._ncbi_adapter = None  # Lazy init per worker

        # Reconstruct headers
        self.node_header = [
            ID_COLUMN,
            "category",
            "name",
            "description",
            "xref",
            "provided_by",
            "synonym",
            "same_as",
        ]
        self.edge_header = [
            "subject",
            "predicate",
            "object",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "has_percentage",
        ]

    def _process_single_file(self, input_file: Path, temp_output_dir: Path, show_status: bool = True) -> Dict[str, Any]:
        """
        Process a single JSONL file and write to temporary output files.

        :param input_file: Path to input JSONL file
        :param temp_output_dir: Directory for temporary output files
        :param show_status: Whether to show progress bar
        :return: Dictionary with processing results
        """
        temp_nodes_file = temp_output_dir / f"{input_file.stem}_nodes.tsv"
        temp_edges_file = temp_output_dir / f"{input_file.stem}_edges.tsv"

        seen_taxon_nodes: Set[str] = set()
        seen_trait_nodes: Set[str] = set()
        unmapped_traits: List[Tuple[str, str, str, int]] = []
        unresolved_taxa: List[str] = []

        # Process file with streaming writers
        with (
            _StreamingRowWriter(temp_nodes_file, self.node_header) as node_writer,
            _StreamingRowWriter(temp_edges_file, self.edge_header) as edge_writer,
        ):
            with _open_jsonl(input_file) as f:
                line_iter = tqdm(f, desc=f"  {input_file.name}", leave=False) if show_status else f
                for line in line_iter:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    tax_name = obj.get("tax_name")
                    if not tax_name:
                        continue

                    tax_id = self._search_ncbitaxon_by_label(tax_name)
                    if not tax_id:
                        unresolved_taxa.append(tax_name)
                        continue

                    summaries = obj.get("summaries", [])
                    for s in summaries:
                        trait_name = s.get("name", "").strip()
                        if not trait_name:
                            continue

                        majority_label = s.get("majority_label", "")
                        percentages = s.get("percentages", {}) or {}
                        # Preserve 0.0 as float (avoid 'or 0' which coerces to int)
                        pct_true = float(percentages.get("true") if percentages.get("true") is not None else 0)

                        # Lookup order (Tier 1-2.0):
                        # Tier 1: Curated microbial-trait-mappings
                        # Tier 1.5: Chemical trait resolver (produces, ferments, carbon source, etc.)
                        # Tier 1.6: Metabolic process resolver (electron acceptor, respiration, oxidation)
                        # Tier 1.7: Growth substrate resolver (growth: X, builds acid from: X)
                        # Tier 1.8: Trophic mode resolver (phototrophy, aerobic/anaerobic)
                        # Tier 1.9: Enzyme activity resolver (enzyme activity with EC numbers)
                        # Tier 2.0: Phenotype resolver (aerotolerant, facultative, acidophilic)
                        # Tier 2/3: METPO mappings + custom_curies (fallback)

                        micro_mapping = self.microbial_mappings.get(trait_name) or self.microbial_mappings.get(
                            trait_name.lower()
                        )
                        if micro_mapping:
                            # Tier 1: Curated mappings
                            curie = micro_mapping["object_id"]
                            category = micro_mapping["object_category"]
                            pred = micro_mapping["biolink_predicate"]
                            label = micro_mapping["object_label"]
                        elif chemical_mapping := self._resolve_chemical_trait(trait_name):
                            # Tier 1.5: Chemical resolver (produces, ferments, carbon source, etc.)
                            curie = chemical_mapping["curie"]
                            category = chemical_mapping["category"]
                            pred = self._to_biolink_predicate(chemical_mapping["predicate"])
                            label = chemical_mapping["name"]
                        elif metabolic_mapping := self._resolve_metabolic_trait(trait_name):
                            # Tier 1.6: Metabolic processes (electron acceptors, respiration, oxidation, reduction)
                            curie = metabolic_mapping["curie"]
                            category = metabolic_mapping["category"]
                            pred = self._to_biolink_predicate(metabolic_mapping["predicate"])
                            label = metabolic_mapping["name"]
                        elif growth_mapping := self._resolve_growth_substrate(trait_name):
                            # Tier 1.7: Growth substrates (growth: X, builds acid from: X)
                            curie = growth_mapping["curie"]
                            category = growth_mapping["category"]
                            pred = self._to_biolink_predicate(growth_mapping["predicate"])
                            label = growth_mapping["name"]
                        elif trophic_mapping := self._resolve_trophic_mode(trait_name):
                            # Tier 1.8: Trophic modes (phototrophy, chemoheterotrophy, aerobic/anaerobic)
                            curie = trophic_mapping["curie"]
                            category = trophic_mapping["category"]
                            pred = self._to_biolink_predicate(trophic_mapping["predicate"])
                            label = trophic_mapping["name"]
                        elif enzyme_mapping := self._resolve_enzyme_activity(trait_name):
                            # Tier 1.9: Enzyme activities with EC numbers
                            curie = enzyme_mapping["curie"]
                            category = enzyme_mapping["category"]
                            pred = self._to_biolink_predicate(enzyme_mapping["predicate"])
                            label = enzyme_mapping["name"]
                        elif phenotype_mapping := self._resolve_phenotype_trait(trait_name):
                            # Tier 2.0: Simple phenotypes (aerotolerant, facultative, acidophilic)
                            curie = phenotype_mapping["curie"]
                            category = phenotype_mapping["category"]
                            pred = self._to_biolink_predicate(phenotype_mapping["predicate"])
                            label = phenotype_mapping["name"]
                        else:
                            # Tier 2/3: Fallback to METPO/custom_curies
                            mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(trait_name.lower())
                            if not mapping:
                                unmapped_traits.append(
                                    (
                                        trait_name,
                                        tax_name,
                                        majority_label,
                                        s.get("num_observations", 0),
                                    )
                                )
                                continue
                            curie = mapping["curie"]
                            category = mapping["category"]
                            pred = self._to_biolink_predicate(mapping["predicate"])
                            label = mapping["name"]

                        if tax_id not in seen_taxon_nodes:
                            seen_taxon_nodes.add(tax_id)
                            node_writer.write_row(
                                self._create_node_row(
                                    tax_id,
                                    NCBI_CATEGORY,
                                    tax_name,
                                )
                            )

                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(self._create_node_row(curie, category, label))

                        relation = self._get_relation_for_predicate(pred)
                        edge_writer.write_row(
                            [
                                tax_id,
                                pred,
                                curie,
                                relation,
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                pct_true,
                            ]
                        )

        return {
            "nodes_file": temp_nodes_file,
            "edges_file": temp_edges_file,
            "unmapped_traits": unmapped_traits,
            "unresolved_taxa": unresolved_taxa,
        }

    def _merge_worker_outputs(self, results: List[Dict[str, Any]], temp_dir: Path) -> None:
        """
        Merge temporary output files from parallel workers.

        :param results: List of result dictionaries from workers
        :param temp_dir: Temporary directory containing worker output files
        """
        print("  Merging worker outputs...")

        # Concatenate all temp node files
        all_nodes = []
        for result in results:
            nodes_df = pd.read_csv(result["nodes_file"], sep="\t", dtype=str)
            all_nodes.append(nodes_df)

        nodes_df = pd.concat(all_nodes, ignore_index=True)

        # Deduplicate nodes
        nodes_df = drop_duplicates(nodes_df, subset=[ID_COLUMN], sort_by=ID_COLUMN)

        # Write final output
        nodes_df.to_csv(self.output_node_file, sep="\t", index=False)

        # Same for edges
        all_edges = []
        for result in results:
            edges_df = pd.read_csv(result["edges_file"], sep="\t", dtype=str)
            all_edges.append(edges_df)

        edges_df = pd.concat(all_edges, ignore_index=True)

        # Deduplicate edges
        edges_df = drop_duplicates(edges_df)

        # Write final output
        edges_df.to_csv(self.output_edge_file, sep="\t", index=False)

        # Merge unmapped traits and unresolved taxa lists
        all_unmapped = []
        all_unresolved = set()
        for result in results:
            all_unmapped.extend(result["unmapped_traits"])
            all_unresolved.update(result["unresolved_taxa"])

        # Write unmapped traits
        with open(self.unmapped_traits_file, "w", newline="") as uf:
            uw = csv.writer(uf, delimiter="\t")
            uw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            uw.writerows(all_unmapped)

        # Write unresolved taxa
        with open(self.unresolved_taxa_file, "w", newline="") as rf:
            rw = csv.writer(rf, delimiter="\t")
            rw.writerow(["tax_name"])
            for t in sorted(all_unresolved):
                rw.writerow([t])

        # Cleanup temp files
        shutil.rmtree(temp_dir)
        print("  Merge complete.")

    def _run_parallel(
        self, input_files: List[Path], show_status: bool = True, num_workers: Optional[int] = None
    ) -> None:
        """
        Process files in parallel using multiprocessing.

        :param input_files: List of input files to process
        :param show_status: Whether to show progress bars
        :param num_workers: Number of workers (None = auto-detect)
        """
        if num_workers is None:
            num_workers = self._calculate_optimal_workers(input_files)

        # Setup: create temp output directory
        temp_dir = self.output_dir / "temp"
        temp_dir.mkdir(exist_ok=True, parents=True)

        # Prepare worker arguments
        shared_init = self._get_shared_init_data()
        worker_args = [(f, temp_dir, shared_init, show_status) for f in input_files]

        # Execute in parallel
        print(f"  Processing {len(input_files)} files with {num_workers} parallel workers...")
        with multiprocessing.Pool(num_workers) as pool:
            if show_status:
                results = list(
                    tqdm(
                        pool.imap(_process_file_worker, worker_args),
                        total=len(input_files),
                        desc="Processing files in parallel",
                    )
                )
            else:
                results = pool.map(_process_file_worker, worker_args)

        # Merge results
        self._merge_worker_outputs(results, temp_dir)

    def _run_sequential(self, input_files: List[Path], show_status: bool = True) -> None:
        """
        Process files sequentially (original implementation).

        :param input_files: List of input files to process
        :param show_status: Whether to show progress bars
        """
        seen_taxon_nodes: Set[str] = set()
        seen_trait_nodes: Set[str] = set()
        unmapped_traits: List[Tuple[str, str, str, int]] = []
        unresolved_taxa: List[str] = []

        # Create output directory
        Path.mkdir(self.output_dir, exist_ok=True, parents=True)

        # Use streaming writers to avoid memory accumulation
        with (
            _StreamingRowWriter(self.output_node_file, self.node_header) as node_writer,
            _StreamingRowWriter(self.output_edge_file, self.edge_header) as edge_writer,
        ):
            iterable = tqdm(input_files, desc="Processing files") if show_status else input_files

            for input_path in iterable:
                with _open_jsonl(input_path) as f:
                    line_iter = tqdm(f, desc=f"  {input_path.name}", leave=False) if show_status else f
                    for line in line_iter:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        tax_name = obj.get("tax_name")
                        if not tax_name:
                            continue

                        tax_id = self._search_ncbitaxon_by_label(tax_name)
                        if not tax_id:
                            unresolved_taxa.append(tax_name)
                            continue

                        summaries = obj.get("summaries", [])
                        for s in summaries:
                            trait_name = s.get("name", "").strip()
                            if not trait_name:
                                continue

                            majority_label = s.get("majority_label", "")
                            percentages = s.get("percentages", {}) or {}
                            # Preserve 0.0 as float (avoid 'or 0' which coerces to int)
                            pct_true = float(percentages.get("true") if percentages.get("true") is not None else 0)

                            # Lookup order (Tier 1-2.0):
                            micro_mapping = self.microbial_mappings.get(trait_name) or self.microbial_mappings.get(
                                trait_name.lower()
                            )
                            if micro_mapping:
                                curie = micro_mapping["object_id"]
                                category = micro_mapping["object_category"]
                                pred = micro_mapping["biolink_predicate"]
                                label = micro_mapping["object_label"]
                            elif chemical_mapping := self._resolve_chemical_trait(trait_name):
                                curie = chemical_mapping["curie"]
                                category = chemical_mapping["category"]
                                pred = self._to_biolink_predicate(chemical_mapping["predicate"])
                                label = chemical_mapping["name"]
                            elif metabolic_mapping := self._resolve_metabolic_trait(trait_name):
                                curie = metabolic_mapping["curie"]
                                category = metabolic_mapping["category"]
                                pred = self._to_biolink_predicate(metabolic_mapping["predicate"])
                                label = metabolic_mapping["name"]
                            elif growth_mapping := self._resolve_growth_substrate(trait_name):
                                curie = growth_mapping["curie"]
                                category = growth_mapping["category"]
                                pred = self._to_biolink_predicate(growth_mapping["predicate"])
                                label = growth_mapping["name"]
                            elif trophic_mapping := self._resolve_trophic_mode(trait_name):
                                curie = trophic_mapping["curie"]
                                category = trophic_mapping["category"]
                                pred = self._to_biolink_predicate(trophic_mapping["predicate"])
                                label = trophic_mapping["name"]
                            elif enzyme_mapping := self._resolve_enzyme_activity(trait_name):
                                curie = enzyme_mapping["curie"]
                                category = enzyme_mapping["category"]
                                pred = self._to_biolink_predicate(enzyme_mapping["predicate"])
                                label = enzyme_mapping["name"]
                            elif phenotype_mapping := self._resolve_phenotype_trait(trait_name):
                                curie = phenotype_mapping["curie"]
                                category = phenotype_mapping["category"]
                                pred = self._to_biolink_predicate(phenotype_mapping["predicate"])
                                label = phenotype_mapping["name"]
                            else:
                                mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(
                                    trait_name.lower()
                                )
                                if not mapping:
                                    unmapped_traits.append(
                                        (
                                            trait_name,
                                            tax_name,
                                            majority_label,
                                            s.get("num_observations", 0),
                                        )
                                    )
                                    continue
                                curie = mapping["curie"]
                                category = mapping["category"]
                                pred = self._to_biolink_predicate(mapping["predicate"])
                                label = mapping["name"]

                            if tax_id not in seen_taxon_nodes:
                                seen_taxon_nodes.add(tax_id)
                                node_writer.write_row(
                                    self._create_node_row(
                                        tax_id,
                                        NCBI_CATEGORY,
                                        tax_name,
                                    )
                                )

                            if curie not in seen_trait_nodes:
                                seen_trait_nodes.add(curie)
                                node_writer.write_row(self._create_node_row(curie, category, label))

                            relation = self._get_relation_for_predicate(pred)
                            edge_writer.write_row(
                                [
                                    tax_id,
                                    pred,
                                    curie,
                                    relation,
                                    self.knowledge_source,
                                    OBSERVATION,
                                    AUTOMATED_AGENT,
                                    pct_true,
                                ]
                            )

        # Streaming writers close when exiting context manager
        # Run deduplication on the output files
        drop_duplicates(self.output_node_file, sort_by_column=ID_COLUMN)
        drop_duplicates(self.output_edge_file)

        # Write unmapped traits and unresolved taxa
        with open(self.unmapped_traits_file, "w", newline="") as uf:
            uw = csv.writer(uf, delimiter="\t")
            uw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            uw.writerows(unmapped_traits)

        with open(self.unresolved_taxa_file, "w", newline="") as rf:
            rw = csv.writer(rf, delimiter="\t")
            rw.writerow(["tax_name"])
            for t in sorted(set(unresolved_taxa)):
                rw.writerow([t])

    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Run MetaTraitsTransform with optional multiprocessing.

        :param data_file: Ignored; uses configured input file list.
        :param show_status: Whether to show progress bar.
        """
        input_base = Path(self.input_base_dir)

        # Find which input files exist
        input_files: List[Path] = []
        seen: Set[str] = set()
        for name in METATRAITS_INPUT_FILES:
            p = input_base / name
            if p.exists() and str(p) not in seen:
                input_files.append(p)
                seen.add(str(p))
            else:
                plain_name = name.replace(".gz", "")
                p = input_base / plain_name
                if p.exists() and str(p) not in seen:
                    input_files.append(p)
                    seen.add(str(p))

        if not input_files:
            raise FileNotFoundError(
                f"No metatraits JSONL files found in {input_base}. Expected one of: {METATRAITS_INPUT_FILES}"
            )

        # Check environment variable for disabling multiprocessing
        use_mp = self.use_multiprocessing
        if os.environ.get("METATRAITS_MULTIPROCESSING", "").lower() in ("false", "0", "no"):
            use_mp = False
            print("  Multiprocessing disabled via METATRAITS_MULTIPROCESSING environment variable")

        # Decide whether to use parallel or sequential processing
        if use_mp and len(input_files) > 1:
            self._run_parallel(input_files, show_status, self.num_workers)
        else:
            if use_mp and len(input_files) == 1:
                print("  Using sequential processing (only 1 input file)")
            self._run_sequential(input_files, show_status)
