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
import warnings

# Suppress pkg_resources deprecation warning from eutils (via oaklib)
# eutils is unmaintained but required by oaklib; warning doesn't affect functionality
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*", category=UserWarning)
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Set, Tuple, Union  # noqa: E402

import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from oaklib import get_adapter  # noqa: E402
from tqdm import tqdm  # noqa: E402

from kg_microbe.transform_utils.constants import (  # noqa: E402
    AUTOMATED_AGENT,
    BIOLOGICAL_PROCESS,
    CURIE_COLUMN,
    CUSTOM_CURIES_YAML_FILE,
    HAS_PHENOTYPE,
    ID_COLUMN,
    INFERRED_SUBCLASS_RELATION,
    METATRAITS,
    NCBI_CATEGORY,
    NCBITAXON_NODES_FILE,
    NCBITAXON_SOURCE,
    OBSERVATION,
    PROVISIONAL_SPECIES_PREFIX,
    RAW_DATA_DIR,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform  # noqa: E402
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader  # noqa: E402
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings, uri_to_curie  # noqa: E402
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings  # noqa: E402
from kg_microbe.utils.oak_utils import search_by_label  # noqa: E402
from kg_microbe.utils.pandas_utils import drop_duplicates  # noqa: E402

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
# NOTE: Only process species-level files, not genus or family summaries
METATRAITS_INPUT_FILES = [
    "ncbi_species_summary.jsonl.gz",
    "metatraits_species_summary.jsonl.gz",
]


def _get_ncbitaxon_adapter():
    """Get OAK adapter for NCBITaxon; creates symlink to OAK cache if available."""
    # Use .db file instead of .owl (NCBITAXON_SOURCE points to .owl)
    local_db = NCBITAXON_SOURCE.parent / "ncbitaxon.db"
    oak_cache = Path.home() / ".data" / "oaklib" / "ncbitaxon.db"

    # Try local database first (could be file or symlink)
    if local_db.exists():
        local_path = f"sqlite:{local_db}"
        try:
            adapter = get_adapter(local_path)
            # Verify adapter works (e.g. has statements table)
            list(adapter.basic_search("Bacteria", limit=1))
            print(f"  Using local NCBITaxon database: {local_db}")
            return adapter
        except Exception as e:
            print(f"  Local NCBITaxon database invalid ({e.__class__.__name__}), trying fallback")
            # Remove invalid symlink, or quarantine regular file to avoid data loss
            try:
                if local_db.is_symlink():
                    local_db.unlink()
                    print(f"  Removed invalid symlink: {local_db}")
                else:
                    quarantine_path = local_db.with_suffix(local_db.suffix + ".quarantine")
                    local_db.rename(quarantine_path)
                    print(f"  Quarantined potentially corrupted database: {quarantine_path}")
            except OSError as unlink_err:
                # If cleanup fails, continue to fallback mechanisms
                print(f"  Could not remove/quarantine database ({unlink_err}), continuing to fallback")

    # If OAK cache exists but no local symlink, create it
    if oak_cache.exists() and not local_db.exists():
        try:
            print(f"  Creating symlink to cached database: {local_db} -> {oak_cache}")
            local_db.symlink_to(oak_cache)
            print("  Using cached NCBITaxon database from OAK")
            return get_adapter(f"sqlite:{local_db}")
        except FileExistsError:
            # Another worker created the symlink - verify and use it
            if local_db.exists() and local_db.is_symlink():
                return get_adapter(f"sqlite:{local_db}")
            else:
                print("  Symlink race condition - file exists but invalid, using remote adapter")
        except Exception as e:
            print(f"  Failed to create symlink ({e}), using remote adapter")

    # Fallback: use OAK remote adapter (downloads to cache if not present)
    if oak_cache.exists():
        print("  Using cached NCBITaxon database from OAK")
    else:
        print("  Downloading NCBITaxon database from OBO library (~2GB, one-time download)...")

    adapter = get_adapter("sqlite:obo:ncbitaxon")

    # After first download, create symlink for future runs
    if oak_cache.exists() and not local_db.exists():
        try:
            local_db.symlink_to(oak_cache)
            print(f"  Created symlink for future use: {local_db}")
        except FileExistsError:
            pass  # Another worker already created it - no need to log
        except Exception:  # noqa: S110
            pass  # Symlink creation is optional, don't fail if it doesn't work

    return adapter


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

    # Reconstruct transform instance in worker process using correct class
    transform_class = shared_init.get("transform_class", MetaTraitsTransform)
    transform = transform_class.__new__(transform_class)
    transform._init_from_shared_data(shared_init)

    try:
        # Process file
        result = transform._process_single_file(input_file, temp_dir, show_status)
        return result
    finally:
        # Clean up OAK adapter resources to prevent semaphore leaks
        try:
            if hasattr(transform, "_ncbi_adapter") and transform._ncbi_adapter is not None:
                if hasattr(transform._ncbi_adapter, "engine") and transform._ncbi_adapter.engine is not None:
                    transform._ncbi_adapter.engine.dispose()
            transform._ncbi_adapter = None
        except Exception:  # noqa: S110
            pass  # Ignore cleanup errors


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

    # Measurement traits that should be excluded from unmapped_traits.tsv
    # These represent quantitative measurements, not ontology classes
    MEASUREMENT_TRAITS = {
        "temperature growth",
        "temperature minimum",
        "temperature maximum",
        "ph minimum",
        "ph maximum",
        "ph growth",
        "salinity growth",
        "salinity minimum",
        "salinity maximum",
        "genome size",
        "gene count",
        "estimated genome size",
        "estimated gene count",
        "coding density",
        "cell length minimum",
        "cell length maximum",
        "cell width minimum",
        "cell width maximum",
    }

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
        self.metpo_mappings = load_metpo_mappings("metatraits synonym")

        # Initialize unified chemical mapping loader for ChEBI lookups
        try:
            self.chemical_loader = ChemicalMappingLoader()
        except (FileNotFoundError, ImportError) as e:
            print(f"  Warning: Could not load unified chemical mappings: {e}")
            self.chemical_loader = None

        # Load special chemical mappings for high-frequency unmapped traits
        self.special_chemical_mappings = self._load_special_chemical_mappings()

        # Load chemical name synonyms for ChEBI lookup fallback
        self.chemical_name_synonyms = self._load_chemical_name_synonyms()

        # Load EC to GO mappings (primary source for enzyme activities with EC numbers)
        self.ec_to_go = self._load_ec_to_go()

        # Load enzyme name to GO mappings (fallback for enzymes without EC numbers)
        self.enzyme_name_to_go = self._load_enzyme_name_to_go()

        # Load NCBI to GTDB taxon mappings for unresolved taxa fallback
        self.ncbi_to_gtdb_mappings = self._load_ncbi_gtdb_mappings()

        # Load METPO binned range classes for data-driven classification
        self.metpo_binned_ranges = self._load_metpo_binned_ranges()

        # Load comprehensive METPO class/predicate lookups from ontology
        self.metpo_label_to_class = {}  # label → {curie, category, name, predicate}
        self.metpo_synonym_to_class = {}  # synonym → {curie, category, name, predicate}
        self.metpo_pattern_to_predicate = {}  # pattern keyword → {positive_id, negative_id}
        self._load_metpo_lookups()

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
        self.measurement_traits_file = self.output_dir / "measurement_traits.tsv"

        # Multiprocessing configuration
        self.use_multiprocessing = use_multiprocessing
        self.num_workers = num_workers

    def _get_input_file_names(self) -> List[str]:
        """
        Get list of expected input file names.

        Subclasses can override this to use different input files
        without mutating module-level globals.

        :return: List of input file names to search for
        """
        return METATRAITS_INPUT_FILES

    def _load_metpo_binned_ranges(self) -> Dict[str, List[dict]]:
        """
        Load METPO binned range classes from metpo.json.

        Extracts binned classes (those with range_min/range_max properties)
        organized by parameter type for data-driven classification.

        :return: Dict mapping parameter type to list of binned class dicts
        """
        metpo_json_path = RAW_DATA_DIR / "metpo.json"
        if not metpo_json_path.exists():
            print(f"  Warning: METPO JSON not found at {metpo_json_path}, using empty ranges")
            return {}

        try:
            with open(metpo_json_path) as f:
                data = json.load(f)

            nodes = data.get("graphs", [{}])[0].get("nodes", [])
            binned_classes = {}

            for node in nodes:
                node_id = node.get("id", "")
                label = node.get("lbl", "")

                # Extract range properties
                props = {p["pred"]: p["val"] for p in node.get("meta", {}).get("basicPropertyValues", [])}

                range_min = props.get("https://w3id.org/metpo/range_min")
                range_max = props.get("https://w3id.org/metpo/range_max")

                # Only include binned classes with 'optimum' in label and range data
                if "optimum" in label.lower() and (range_min or range_max):
                    curie = node_id.replace("https://w3id.org/metpo/", "METPO:")
                    unit = props.get("http://qudt.org/schema/qudt/ucumCode", "")

                    # Extract synonyms
                    synonyms = [s["val"] for s in node.get("meta", {}).get("synonyms", [])]

                    # Determine parameter type
                    param_type = None
                    if "temperature" in label.lower():
                        param_type = "temperature"
                    elif "ph" in label.lower():
                        param_type = "pH"
                    elif "nacl" in label.lower():
                        param_type = "NaCl"

                    if param_type:
                        if param_type not in binned_classes:
                            binned_classes[param_type] = []

                        binned_classes[param_type].append(
                            {
                                "curie": curie,
                                "label": label,
                                "range_min": (float(range_min) if range_min is not None else None),
                                "range_max": (float(range_max) if range_max is not None else None),
                                "unit": unit,
                                "synonyms": synonyms,
                            }
                        )

            # Sort by range_min for each parameter (None values last)
            for param_type in binned_classes:
                binned_classes[param_type].sort(key=lambda x: x["range_min"] if x["range_min"] is not None else -999)

            print(
                f"  Loaded METPO binned ranges: "
                f"temperature={len(binned_classes.get('temperature', []))}, "
                f"pH={len(binned_classes.get('pH', []))}, "
                f"NaCl={len(binned_classes.get('NaCl', []))}"
            )
            return binned_classes

        except Exception as e:
            print(f"  Error loading METPO binned ranges: {e}")
            return {}

    def _load_metpo_lookups(self) -> None:
        """
        Load METPO classes and predicates with labels/synonyms for pattern matching.

        Creates reverse lookup dictionaries:
        - label → class data (for direct label matching)
        - synonym → class data (for synonym matching)
        - pattern keyword → predicate ID (for trait pattern resolution)
        """
        metpo_json_path = RAW_DATA_DIR / "metpo.json"
        if not metpo_json_path.exists():
            print(f"  Warning: METPO JSON not found at {metpo_json_path}")
            return

        try:
            with open(metpo_json_path) as f:
                data = json.load(f)

            nodes = data.get("graphs", [{}])[0].get("nodes", [])

            for node in nodes:
                node_id = node.get("id", "")
                label = node.get("lbl", "")
                node_type = node.get("type", "")

                if not label:
                    continue

                curie = node_id.replace("https://w3id.org/metpo/", "METPO:")

                # Extract synonyms
                synonyms = [s["val"] for s in node.get("meta", {}).get("synonyms", [])]

                # Determine category and predicate based on node type
                if node_type == "CLASS":
                    category = "biolink:PhenotypicQuality"
                    predicate = "biolink:has_phenotype"
                elif node_type == "PROPERTY":
                    # Properties are predicates, not traits
                    # Store pattern keyword → {positive: ID, negative: ID} mapping
                    is_negative = label.lower().startswith("does not ")

                    for synonym in synonyms + [label]:
                        pattern_key = synonym.lower().strip()

                        # Initialize dict if not exists
                        if pattern_key not in self.metpo_pattern_to_predicate:
                            self.metpo_pattern_to_predicate[pattern_key] = {"positive": None, "negative": None}

                        # Store as positive or negative
                        if is_negative:
                            self.metpo_pattern_to_predicate[pattern_key]["negative"] = curie
                        else:
                            self.metpo_pattern_to_predicate[pattern_key]["positive"] = curie
                    continue
                else:
                    continue

                # Create class data
                class_data = {
                    "curie": curie,
                    "category": category,
                    "name": label,
                    "predicate": predicate,
                }

                # Add to label lookup
                self.metpo_label_to_class[label.lower()] = class_data

                # Add to synonym lookups
                for synonym in synonyms:
                    self.metpo_synonym_to_class[synonym.lower()] = class_data

            print(
                f"  Loaded METPO lookups: "
                f"{len(self.metpo_label_to_class)} labels, "
                f"{len(self.metpo_synonym_to_class)} synonyms, "
                f"{len(self.metpo_pattern_to_predicate)} pattern predicates"
            )

        except Exception as e:
            print(f"  Error loading METPO lookups: {e}")

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

    def _load_special_chemical_mappings(self) -> Dict[str, dict]:
        """
        Load special chemical mappings from TSV file for high-frequency unmapped traits.

        Maps trait patterns like "electron acceptor: sulfur compounds" to parent class
        ontology terms (e.g., CHEBI:26833) or environmental materials (e.g., ENVO terms).

        :return: Dictionary mapping trait_pattern (lowercase) -> {curie, category, name, predicate}
        """
        mappings_file = Path(__file__).parent / "mappings" / "special_chemical_mappings.tsv"
        special_mappings = {}

        if not mappings_file.exists():
            print(f"  Warning: Special chemical mappings file not found: {mappings_file}")
            return special_mappings

        try:
            with open(mappings_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    trait_pattern = row["trait_pattern"].strip().lower()
                    special_mappings[trait_pattern] = {
                        "curie": row["ontology_id"].strip(),
                        "category": row["category"].strip(),
                        "name": row["ontology_name"].strip(),
                        "predicate": row["predicate"].strip(),
                    }
            print(f"  Loaded {len(special_mappings)} special chemical mappings")
        except Exception as e:
            print(f"  Warning: Could not load special chemical mappings: {e}")

        return special_mappings

    def _load_chemical_name_synonyms(self) -> Dict[str, dict]:
        """
        Load chemical name synonyms for ChEBI lookup fallback.

        Maps MetaTraits simplified names to correct ChEBI search names
        for chemicals that fail direct lookup due to name normalization issues.

        :return: Dictionary mapping metatraits_name (lowercase) -> {chebi_id, chebi_label, chebi_search_name}
        """
        mappings_file = Path(__file__).parent / "mappings" / "chemical_name_synonyms.tsv"
        synonyms = {}

        if not mappings_file.exists():
            print(f"  Warning: Chemical name synonyms file not found: {mappings_file}")
            return synonyms

        try:
            with open(mappings_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    metatraits_name = row["metatraits_name"].strip().lower()
                    synonyms[metatraits_name] = {
                        "chebi_id": row["chebi_id"].strip(),
                        "chebi_label": row["chebi_label"].strip(),
                        "chebi_search_name": row["chebi_search_name"].strip(),
                    }
            print(f"  Loaded {len(synonyms)} chemical name synonyms")
        except Exception as e:
            print(f"  Warning: Could not load chemical name synonyms: {e}")

        return synonyms

    def _load_ec_to_go(self) -> Dict[str, dict]:
        """
        Load EC to GO mappings from ec2go.txt.

        Maps EC numbers to GO molecular function terms.
        Format: EC:1.1.1.1 > GO:alcohol dehydrogenase (NAD+) activity ; GO:0004022

        :return: Dictionary mapping ec_number (e.g., "1.1.1.1") -> {go_id, go_label}
        """
        ec2go_file = RAW_DATA_DIR / "ec2go.txt"
        ec_mappings = {}

        if not ec2go_file.exists():
            print(f"  Warning: EC to GO mappings file not found: {ec2go_file}")
            return ec_mappings

        try:
            import re

            with open(ec2go_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line.startswith("!") or not line:
                        continue

                    # Parse format: EC:1.1.1.1 > GO:label ; GO:0004022
                    match = re.match(r"^EC:([\d.-]+)\s*>\s*GO:(.+?)\s*;\s*(GO:\d+)\s*$", line)
                    if match:
                        ec_number = match.group(1).strip()
                        go_label = match.group(2).strip()
                        go_id = match.group(3).strip()

                        ec_mappings[ec_number] = {"go_id": go_id, "go_label": go_label}

            print(f"  Loaded {len(ec_mappings)} EC to GO mappings")
        except Exception as e:
            print(f"  Warning: Could not load EC to GO mappings: {e}")

        return ec_mappings

    def _load_enzyme_name_to_go(self) -> Dict[str, dict]:
        """
        Load enzyme name to GO term mappings for enzymes without EC numbers.

        Maps enzyme names (e.g., "glycyl tryptophan arylamidase") to GO molecular
        function terms for enzymes that don't have EC numbers in MetaTraits data.

        :return: Dictionary mapping enzyme_name (lowercase) -> {go_id, go_label, ec_number, notes}
        """
        mappings_file = Path(__file__).parent / "mappings" / "enzyme_name_to_go.tsv"
        enzyme_mappings = {}

        if not mappings_file.exists():
            print(f"  Warning: Enzyme name to GO mappings file not found: {mappings_file}")
            return enzyme_mappings

        try:
            with open(mappings_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    enzyme_name = row["enzyme_name"].strip().lower()
                    enzyme_mappings[enzyme_name] = {
                        "go_id": row["go_id"].strip(),
                        "go_label": row["go_label"].strip(),
                        "ec_number": row.get("ec_number", "").strip(),
                        "notes": row.get("notes", "").strip(),
                    }
            print(f"  Loaded {len(enzyme_mappings)} enzyme name to GO mappings")
        except Exception as e:
            print(f"  Warning: Could not load enzyme name to GO mappings: {e}")

        return enzyme_mappings

    def _load_ncbi_gtdb_mappings(self) -> Dict[str, dict]:
        """
        Load NCBI to GTDB taxon mappings for unresolved taxa fallback.

        Maps unresolved NCBI taxa to GTDB genera/species where possible.
        Enables trait ingestion for organisms not in NCBITaxon.

        :return: Dictionary mapping ncbi_name (lowercase) -> {gtdb_genus, gtdb_species, mapping_type, confidence}
        """
        mappings_file = Path(__file__).parent / "mappings" / "ncbi_to_gtdb_taxa.tsv"
        gtdb_mappings = {}

        if not mappings_file.exists():
            print(f"  Warning: NCBI to GTDB mappings file not found: {mappings_file}")
            return gtdb_mappings

        try:
            with open(mappings_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    ncbi_name = row["ncbi_name"].strip().lower()
                    gtdb_mappings[ncbi_name] = {
                        "gtdb_genus": row["gtdb_genus"].strip(),
                        "gtdb_species": row["gtdb_species"].strip(),
                        "mapping_type": row["mapping_type"].strip(),
                        "confidence": row["confidence"].strip(),
                    }
            print(f"  Loaded {len(gtdb_mappings)} NCBI to GTDB taxon mappings")
        except Exception as e:
            print(f"  Warning: Could not load NCBI to GTDB mappings: {e}")

        return gtdb_mappings

    def _get_ncbitaxon_impl(self):
        """Return OAK adapter for NCBITaxon, creating it on first use."""
        if self._ncbi_adapter is None:
            self._ncbi_adapter = _get_ncbitaxon_adapter()
        return self._ncbi_adapter

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """
        Resolve taxon name to NCBITaxon ID with GTDB fallback.

        Resolution strategy:
        1. Check NCBI taxonomy (via ncbitaxon_nodes.tsv cache or OAK)
        2. If not found, check NCBI→GTDB mapping file
        3. If GTDB mapping exists, search for GTDB genus/species in NCBI

        :param search_name: Taxon name to resolve
        :return: NCBITaxon ID or None
        """
        key = search_name.lower()

        # Try NCBI cache first
        ncbitaxon_id = self.ncbitaxon_name_to_id.get(key)
        if ncbitaxon_id:
            return ncbitaxon_id

        # Try NCBI OAK lookup
        results = search_by_label(self._get_ncbitaxon_impl(), search_name, limit=1)
        if results:
            ncbitaxon_id = results[0]
            self.ncbitaxon_name_to_id[key] = ncbitaxon_id
            return ncbitaxon_id

        # NCBI lookup failed - try GTDB mapping fallback
        gtdb_mapping = self.ncbi_to_gtdb_mappings.get(key)
        if gtdb_mapping:
            gtdb_genus = gtdb_mapping["gtdb_genus"]
            gtdb_species = gtdb_mapping["gtdb_species"]
            mapping_type = gtdb_mapping["mapping_type"]

            # Try exact species match first (for high-confidence exact_species mappings)
            if gtdb_species and gtdb_species != "NA" and mapping_type == "exact_species":
                # Search for "Genus species" in NCBI
                species_name = f"{gtdb_genus} {gtdb_species.replace('_', ' ')}"
                species_results = search_by_label(self._get_ncbitaxon_impl(), species_name, limit=1)
                if species_results:
                    ncbitaxon_id = species_results[0]
                    self.ncbitaxon_name_to_id[key] = ncbitaxon_id
                    return ncbitaxon_id

            # Fallback to genus level (for genus_level/family_level mappings)
            genus_results = search_by_label(self._get_ncbitaxon_impl(), gtdb_genus, limit=1)
            if genus_results:
                ncbitaxon_id = genus_results[0]
                # Cache with original name for future lookups
                self.ncbitaxon_name_to_id[key] = ncbitaxon_id
                return ncbitaxon_id

        return None

    def _parse_taxonomic_components(self, tax_name: str) -> dict:
        """
        Parse taxonomic components from strain-level names.

        Handles patterns:
        - "Genus sp. STRAIN_ID" → genus only
        - "Genus species STRAIN_ID" → genus + species
        - "Family bacterium STRAIN_ID" → family only
        - "Candidatus Genus species" → genus + species
        - "uncultured Genus sp." → genus only

        :param tax_name: Taxon name to parse
        :return: dict with 'genus', 'species', 'strain_id', 'type' keys
        """
        import re

        # Remove prefixes
        cleaned = re.sub(r"^(uncultured|Candidatus)\s+", "", tax_name, flags=re.IGNORECASE)

        # Pattern 1: "Genus sp. STRAIN_ID"
        match = re.match(r"^([A-Z][a-z]+)\s+sp\.\s+(.+)$", cleaned)
        if match:
            return {
                "genus": match.group(1),
                "species": None,
                "strain_id": match.group(2),
                "type": "strain",
            }

        # Pattern 2: "Family/Genus bacterium STRAIN_ID"
        match = re.match(r"^([A-Z][a-z]+)\s+bacterium\s+(.+)$", cleaned)
        if match:
            return {
                "genus": match.group(1),  # Could be family
                "species": None,
                "strain_id": match.group(2),
                "type": "bacterium",
            }

        # Pattern 3: "Genus species" (valid binomial)
        match = re.match(r"^([A-Z][a-z]+)\s+([a-z]+)$", cleaned)
        if match:
            return {
                "genus": match.group(1),
                "species": match.group(2),
                "strain_id": None,
                "type": "species",
            }

        # Pattern 4: "Genus species STRAIN_ID" (three words)
        match = re.match(r"^([A-Z][a-z]+)\s+([a-z]+)\s+(.+)$", cleaned)
        if match:
            return {
                "genus": match.group(1),
                "species": match.group(2),
                "strain_id": match.group(3),
                "type": "strain",
            }

        return {"genus": None, "species": None, "strain_id": None, "type": "unknown"}

    def _create_provisional_strain_node(
        self, tax_name: str, genus: str, species: Optional[str], strain_id: str, node_writer
    ) -> str:
        """
        Create provisional strain node.

        :param tax_name: Original taxon name
        :param genus: Genus name
        :param species: Species epithet (optional)
        :param strain_id: Strain identifier
        :param node_writer: Streaming node writer
        :return: Strain node CURIE (e.g., "kgmicrobe.strain:Genus_sp_STRAIN")
        """
        # Create strain ID from components
        if species:
            strain_curie = f"{STRAIN_PREFIX}{genus}_{species}_{strain_id}".replace(" ", "_")
        else:
            strain_curie = f"{STRAIN_PREFIX}{genus}_sp_{strain_id}".replace(" ", "_")

        # Create node
        node_writer.write_row(
            self._create_node_row(
                strain_curie,
                NCBI_CATEGORY,
                tax_name,  # Use original name as label
                description=f"Provisional strain node for {tax_name}",
            )
        )

        return strain_curie

    def _create_provisional_species_node(self, genus: str, species: str, node_writer) -> str:
        """
        Create provisional species node (reuses BacDive pattern).

        :param genus: Genus name
        :param species: Species epithet
        :param node_writer: Streaming node writer
        :return: Species node CURIE (e.g., "kgmicrobe.species:Genus_species")
        """
        species_curie = f"{PROVISIONAL_SPECIES_PREFIX}{genus}_{species}"
        species_name = f"{genus} {species}"

        node_writer.write_row(
            self._create_node_row(
                species_curie,
                NCBI_CATEGORY,
                species_name,
                description=f"Provisional species node for {species_name}",
            )
        )

        return species_curie

    def _search_higher_ranks_in_ncbitaxon(self, genus: str) -> Optional[tuple]:
        """
        Search for genus or higher ranks (family, order, class) in NCBITaxon.

        Follows BacDive strategy: try genus → family → order → class → phylum.

        :param genus: Genus name to search
        :return: (ncbitaxon_id, rank_name) or None
        """
        # Try genus first
        genus_id = self._search_ncbitaxon_by_label(genus)
        if genus_id:
            return (genus_id, "genus")

        # Try adding common suffixes for higher ranks
        rank_suffixes = {
            "aceae": "family",  # Pseudomonadaceae
            "ales": "order",  # Pseudomonadales
            "ia": "class",  # Gammaproteobacteria
            "ota": "phylum",  # Pseudomonadota
        }

        for suffix, rank in rank_suffixes.items():
            test_name = genus + suffix
            taxon_id = self._search_ncbitaxon_by_label(test_name)
            if taxon_id:
                return (taxon_id, rank)

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
        # Check special mappings first (parent classes, materials, etc.)
        trait_key = trait_name.strip().lower()
        if trait_key in self.special_chemical_mappings:
            return self.special_chemical_mappings[trait_key].copy()

        if not self.chemical_loader:
            return None

        import re

        # Extract chemical name and predicate from patterns using METPO lookups
        # Try common pattern keywords loaded from METPO
        pattern_keywords = [
            "carbon source",
            "assimilation",
            "produces",
            "ferments",
            "hydrolyzes",
            "oxidizes",
            "reduces",
            "degrades",
            "utilizes",
        ]

        for keyword in pattern_keywords:
            # Create pattern: "keyword: [chemical]"
            pattern = rf"^{re.escape(keyword)}:\s*(.+)$"
            match = re.match(pattern, trait_name.lower())
            if match:
                chemical_name = match.group(1).strip()

                # Lookup predicate from METPO (use positive predicate)
                predicate_data = self.metpo_pattern_to_predicate.get(keyword.lower())
                if not predicate_data or not predicate_data.get("positive"):
                    continue

                metpo_predicate = predicate_data["positive"]

                # Lookup chemical
                chebi_id = self.chemical_loader.find_chebi_by_name(chemical_name)

                # If direct lookup fails, try synonym mapping
                if not chebi_id and chemical_name in self.chemical_name_synonyms:
                    synonym_data = self.chemical_name_synonyms[chemical_name]
                    chebi_id = synonym_data["chebi_id"]
                    canonical_name = synonym_data["chebi_label"]
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name,
                        "predicate": metpo_predicate,
                    }

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
        # Check special mappings first (parent classes, materials, etc.)
        trait_key = trait_name.strip().lower()
        if trait_key in self.special_chemical_mappings:
            return self.special_chemical_mappings[trait_key].copy()

        if not self.chemical_loader:
            return None

        import re

        # Pattern keywords and their lookup types (chemical vs material)
        # lookup_type: "chemical" = ChEBI only, "material" = ChEBI or fallback to hardcoded
        pattern_configs = [
            ("electron acceptor", "chemical"),
            ("electron donor", "chemical"),
            ("respiration", "chemical"),
            ("reduction", "chemical"),
            ("oxidation", "chemical"),
            ("oxidation in darkness", "chemical"),
            ("denitrification", "chemical"),
            ("ammonification", "chemical"),
            ("degradation", "material"),
            ("hydrolysis", "material"),
        ]

        for keyword, _lookup_type in pattern_configs:
            # Create pattern: "keyword: [substance]"
            pattern = rf"^{re.escape(keyword)}:\s*(.+)$"
            match = re.match(pattern, trait_name.lower())
            if match:
                substance_name = match.group(1).strip()

                # Lookup predicate from METPO (use positive predicate)
                predicate_data = self.metpo_pattern_to_predicate.get(keyword.lower())
                if not predicate_data or not predicate_data.get("positive"):
                    continue

                metpo_predicate = predicate_data["positive"]

                # Try ChEBI lookup first
                chebi_id = self.chemical_loader.find_chebi_by_name(substance_name)

                # If direct lookup fails, try synonym mapping
                if not chebi_id and substance_name in self.chemical_name_synonyms:
                    synonym_data = self.chemical_name_synonyms[substance_name]
                    chebi_id = synonym_data["chebi_id"]
                    canonical_name = synonym_data["chebi_label"]
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name,
                        "predicate": metpo_predicate,
                    }

                if chebi_id:
                    canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name or substance_name,
                        "predicate": metpo_predicate,
                    }

                # Material fallbacks are now in special_chemical_mappings.tsv
                # (urea, gelatin, esculin, starch, casein)
                # No need for hardcoded fallbacks here

        return None

    def _resolve_growth_substrate(self, trait_name: str) -> Optional[dict]:
        """
        Resolve growth substrate patterns (growth, fermentation, acid/gas/base production).

        Handles patterns like:
        - "growth: cellobiose" -> CHEBI:17057
        - "fermentation: lactose" -> CHEBI:17716 (already handled by chemical resolver)
        - "builds acid from: glucose" -> CHEBI:17234
        - "builds gas from: glucose" -> CHEBI:17234
        - "builds base from: acetate" -> CHEBI:30089

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        # Check special mappings first (parent classes, materials, etc.)
        trait_key = trait_name.strip().lower()
        if trait_key in self.special_chemical_mappings:
            return self.special_chemical_mappings[trait_key].copy()

        if not self.chemical_loader:
            return None

        import re

        # Use METPO pattern predicates instead of hardcoded IDs
        pattern_configs = [
            (r"^growth:\s*(.+)$", "growth"),
            (r"^builds acid from:\s*(.+)$", "builds acid from"),
            (r"^builds gas from:\s*(.+)$", "builds gas from"),
            (r"^builds base from:\s*(.+)$", "builds base from"),
        ]

        for pattern, keyword in pattern_configs:
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

                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get(keyword)
                if not predicate_data or not predicate_data.get("positive"):
                    continue
                metpo_predicate = predicate_data["positive"]

                # Try ChEBI lookup
                chebi_id = self.chemical_loader.find_chebi_by_name(substrate_name)

                # If direct lookup fails, try synonym mapping
                if not chebi_id and substrate_name in self.chemical_name_synonyms:
                    synonym_data = self.chemical_name_synonyms[substrate_name]
                    chebi_id = synonym_data["chebi_id"]
                    canonical_name = synonym_data["chebi_label"]
                    return {
                        "curie": chebi_id,
                        "category": "biolink:ChemicalSubstance",
                        "name": canonical_name,
                        "predicate": metpo_predicate,
                    }

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
        Resolve trophic mode and growth type patterns using METPO lookups.

        Handles patterns like:
        - "growth: phototrophy" -> METPO:1000660 (phototrophic)
        - "growth: chemoheterotrophy" -> METPO:1000636 (chemoheterotrophic)
        - "aerobic growth" -> METPO:1000602 (aerobic)
        - "anaerobic growth" -> METPO:1000603 (anaerobic)

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        import re

        # Pattern: growth: [trophic_mode]
        # Use METPO lookups for trophic modes instead of hardcoded mappings
        match = re.match(r"^growth:\s*(.+)$", trait_name.lower())
        if match:
            mode = match.group(1).strip()

            # Try direct label lookup first
            metpo_class = self.metpo_label_to_class.get(mode)
            if not metpo_class:
                # Try synonym lookup
                metpo_class = self.metpo_synonym_to_class.get(mode)

            # If not found, try space-to-underscore conversion for compound terms
            if not metpo_class and " " in mode:
                mode_underscore = mode.replace(" ", "_")
                metpo_class = self.metpo_label_to_class.get(mode_underscore)
                if not metpo_class:
                    metpo_class = self.metpo_synonym_to_class.get(mode_underscore)

            # If not found, try converting "-trophy"/"-otrophy" suffix to "-troph"/"-otroph" or "-trophic"/"-otrophic"
            if not metpo_class and ("trophy" in mode or "otrophy" in mode):
                variants = []

                if mode.endswith("trophy"):
                    # "phototrophy" → "phototroph", "phototrophic"
                    variants.append(mode[:-1])  # Remove 'y'
                    variants.append(mode[:-1] + "ic")  # Add 'ic'
                elif mode.endswith("otrophy"):
                    # "anoxygenic phototrophy" → "anoxygenic phototroph", "anoxygenic phototrophic"
                    variants.append(mode[:-1])  # Remove 'y'
                    variants.append(mode[:-1] + "ic")  # Add 'ic'

                # Also try with underscore for compound terms
                if " " in mode:
                    for variant in variants[:]:  # Copy list to avoid modifying during iteration
                        variants.append(variant.replace(" ", "_"))

                # Special case: "anoxygenic phototrophy" → try "aerobic_anoxygenic_phototrophy"
                if "anoxygenic" in mode and "phototrophy" in mode:
                    variants.append("aerobic_anoxygenic_phototrophy")

                # Try all variants
                for variant in variants:
                    metpo_class = self.metpo_label_to_class.get(variant)
                    if not metpo_class:
                        metpo_class = self.metpo_synonym_to_class.get(variant)
                    if metpo_class:
                        break

            if metpo_class:
                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get("has phenotype")
                predicate = predicate_data["positive"] if predicate_data else "biolink:has_phenotype"

                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": predicate,
                }

        # Pattern: aerobic growth / anaerobic growth
        # Use METPO lookups instead of hardcoded IDs
        predicate_data = self.metpo_pattern_to_predicate.get("has phenotype")
        predicate = predicate_data["positive"] if predicate_data else "biolink:has_phenotype"

        if trait_name.lower().startswith("aerobic growth"):
            metpo_class = self.metpo_synonym_to_class.get("aerobe")
            if metpo_class:
                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": predicate,
                }
        elif trait_name.lower().startswith("anaerobic growth"):
            metpo_class = self.metpo_synonym_to_class.get("anaerobe")
            if metpo_class:
                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": predicate,
                }

        return None

    def _resolve_enzyme_activity(self, trait_name: str) -> Optional[dict]:
        """
        Resolve enzyme activity patterns with or without EC numbers.

        Resolution strategy:
        1. Extract EC number and lookup in ec2go (primary source)
        2. If no EC or lookup fails, try enzyme_name_to_go (curated fallback)
        3. If both fail, return None (allows trait_mapping fallback)

        Handles patterns like:
        - "enzyme activity: alkaline phosphatase (EC3.1.3.1)" -> GO via ec2go
        - "enzyme activity: glycyl tryptophan arylamidase" -> GO via enzyme_name_to_go
        - "enzyme activity: DNase" -> None (trait_mapping handles it)

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        import re

        # Get predicate from METPO lookups (used for all enzyme mappings)
        predicate_data = self.metpo_pattern_to_predicate.get("shows activity of")
        predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"

        # Pattern: enzyme activity: [name] (EC[number])
        ec_match = re.match(r"^enzyme activity:\s*(.+?)\s*\(EC\s*([\d.BbXx-]+)\)\s*$", trait_name, re.IGNORECASE)
        if ec_match:
            enzyme_name = ec_match.group(1).strip()
            ec_number = ec_match.group(2).strip().upper()

            # Try EC to GO lookup (primary)
            # Normalize EC number (remove "EC" prefix if present, handle malformed like B15)
            ec_normalized = ec_number.replace("EC", "").strip()

            if ec_normalized in self.ec_to_go:
                go_mapping = self.ec_to_go[ec_normalized]
                return {
                    "curie": go_mapping["go_id"],
                    "category": "biolink:MolecularActivity",
                    "name": go_mapping["go_label"],
                    "predicate": predicate,
                }

            # EC lookup failed, fall back to using EC number directly
            # (for cases where EC is valid but not in ec2go mapping)
            # Only use if EC number looks valid (digits and dots/dashes)
            if re.match(r"^[\d.-]+$", ec_normalized):
                return {
                    "curie": f"EC:{ec_normalized}",
                    "category": "biolink:MolecularActivity",
                    "name": enzyme_name,
                    "predicate": predicate,
                }

        # Pattern: enzyme activity: [name] (without EC number)
        # Try curated enzyme_name_to_go mapping
        no_ec_match = re.match(r"^enzyme activity:\s*(.+)$", trait_name, re.IGNORECASE)
        if no_ec_match:
            enzyme_name = no_ec_match.group(1).strip().lower()

            # Check curated enzyme_name_to_go mapping
            if enzyme_name in self.enzyme_name_to_go:
                go_mapping = self.enzyme_name_to_go[enzyme_name]

                return {
                    "curie": go_mapping["go_id"],
                    "category": "biolink:MolecularActivity",
                    "name": go_mapping["go_label"],
                    "predicate": predicate,
                }

        # Let this fall through to trait_mapping or return None
        # This allows METPO mappings to handle other non-EC enzyme activities
        return None

    def _resolve_required_for_growth(self, trait_name: str) -> Optional[dict]:
        """
        Resolve 'required for growth: [substance]' patterns.

        Handles patterns like:
        - "required for growth: biotin" -> CHEBI:15956
        - "required for growth: sodium chloride" -> CHEBI:26710
        - "required for growth: yeast extract" -> FOODON:03316079

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        match = re.match(r"^required for growth:\s*(.+)$", trait_name.lower())
        if match:
            substance = match.group(1).strip()

            # Try ChEBI lookup first
            chebi_id = self.chemical_loader.find_chebi_by_name(substance)
            canonical_name = None

            # Fallback to synonym mapping
            if not chebi_id and substance in self.chemical_name_synonyms:
                synonym_data = self.chemical_name_synonyms[substance]
                chebi_id = synonym_data["chebi_id"]
                canonical_name = synonym_data["chebi_label"]

            # Fallback to special chemical mappings
            if not chebi_id and substance in self.special_chemical_mappings:
                special_mapping = self.special_chemical_mappings[substance]
                chebi_id = special_mapping["curie"]
                canonical_name = special_mapping["name"]

            if chebi_id:
                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get("required for growth")
                predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"

                # Get canonical name if not already set
                if not canonical_name and self.chemical_loader:
                    canonical_name = self.chemical_loader.get_canonical_name(chebi_id)

                return {
                    "curie": chebi_id,
                    "category": "biolink:ChemicalSubstance",
                    "name": canonical_name or substance,
                    "predicate": predicate,
                }

        return None

    def _resolve_phenotype_trait(self, trait_name: str) -> Optional[dict]:
        """
        Resolve simple phenotype traits using METPO lookups.

        Handles patterns like:
        - "aerotolerant" -> METPO:1000609 (aerotolerant)
        - "facultative anaerobe" -> METPO:1000605 (facultatively anaerobic)
        - "acidophilic" -> METPO:1003003 (acidophilic)
        - "capnophilic" -> METPO:1005021 (capnophilic)

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        normalized = trait_name.lower().strip()

        # Try direct label lookup first
        metpo_class = self.metpo_label_to_class.get(normalized)
        if not metpo_class:
            # Try synonym lookup
            metpo_class = self.metpo_synonym_to_class.get(normalized)

        if metpo_class:
            # Get predicate from METPO lookups
            predicate_data = self.metpo_pattern_to_predicate.get("has phenotype")
            predicate = predicate_data["positive"] if predicate_data else "biolink:has_phenotype"

            return {
                "curie": metpo_class["curie"],
                "category": metpo_class["category"],
                "name": metpo_class["name"],
                "predicate": predicate,
            }

        return None

    def _parse_quantitative_value(self, majority_label: str) -> Optional[float]:
        """
        Parse numeric value from majority_label format.

        Handles formats like:
        - "Median: 14.8 Celsius" → 14.8
        - "Median: 3.1 % NaCl (w/v)" → 3.1
        - "Median: 6.6 pH" → 6.6

        :param majority_label: The majority label string
        :return: Float value or None if cannot parse
        """
        import re

        # Pattern: Median: 14.8 ...
        match = re.search(r"Median:\s*(-?\d+(?:\.\d+)?)", majority_label)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _classify_into_binned_range(self, value: Optional[float], param_type: str) -> Optional[dict]:
        """
        Classify a value into appropriate METPO binned range class.

        Uses range_min/range_max from METPO ontology loaded at initialization.

        :param value: Numeric value to classify
        :param param_type: Parameter type ('temperature', 'pH', or 'NaCl')
        :return: Binned class dict or None
        """
        if value is None:
            return None

        bins = self.metpo_binned_ranges.get(param_type, [])
        if not bins:
            return None

        # Find the bin that contains this value
        for bin_class in bins:
            range_min = bin_class["range_min"]
            range_max = bin_class["range_max"]

            # Check if value falls in this bin
            # range_min is inclusive lower bound (None = -infinity)
            # range_max is inclusive upper bound (None = +infinity)
            lower_ok = range_min is None or value >= range_min
            upper_ok = range_max is None or value <= range_max

            if lower_ok and upper_ok:
                return {
                    "curie": bin_class["curie"],
                    "category": "biolink:PhenotypicQuality",
                    "name": bin_class["label"],
                    "predicate": "biolink:has_phenotype",
                }

        # No bin found (shouldn't happen if METPO data is complete)
        return None

    def _classify_temperature_optimum_bin(self, temp_opt: Optional[float]) -> Optional[dict]:
        """
        Classify temperature optimum into METPO binned range class.

        Uses METPO temperature optimum classes loaded from ontology.

        :param temp_opt: Optimal/growth temperature (Celsius)
        :return: Binned class dict or None
        """
        return self._classify_into_binned_range(temp_opt, "temperature")

    def _classify_temperature_phenotypes(self, temp_min: Optional[float], temp_max: Optional[float]) -> List[dict]:
        """
        Classify temperature phenotypes based on min/max values.

        Uses METPO temperature phenotype classes based on maximum temperature,
        with additional facultative classifications based on minimum.

        :param temp_min: Minimum temperature (Celsius)
        :param temp_max: Maximum temperature (Celsius)
        :return: List of phenotype dicts
        """
        phenotypes = []

        if temp_max is not None:
            # Primary classification based on maximum temperature - use METPO lookups
            phenotype_label = None
            if temp_max >= 80:
                phenotype_label = "hyperthermophilic"
            elif temp_max >= 60:
                phenotype_label = "thermophilic"
            elif temp_max < 20:
                phenotype_label = "psychrophilic"
            else:  # 20 <= temp_max < 60
                phenotype_label = "mesophilic"

            if phenotype_label:
                metpo_class = self.metpo_label_to_class.get(phenotype_label)
                if metpo_class:
                    phenotypes.append(
                        {
                            "curie": metpo_class["curie"],
                            "category": metpo_class["category"],
                            "name": metpo_class["name"],
                            "predicate": "biolink:has_phenotype",
                        }
                    )

        # Additional classification based on minimum temperature
        if temp_min is not None and temp_min < 15:
            metpo_class = self.metpo_label_to_class.get("facultative psychrophilic")
            if metpo_class:
                phenotypes.append(
                    {
                        "curie": metpo_class["curie"],
                        "category": metpo_class["category"],
                        "name": metpo_class["name"],
                        "predicate": "biolink:has_phenotype",
                    }
                )

        return phenotypes

    def _classify_nacl_optimum_bin(self, nacl_opt: Optional[float]) -> Optional[dict]:
        """
        Classify NaCl optimum into METPO binned range class.

        Uses METPO NaCl optimum classes loaded from ontology.

        :param nacl_opt: Optimal/growth salinity (% NaCl)
        :return: Binned class dict or None
        """
        return self._classify_into_binned_range(nacl_opt, "NaCl")

    def _classify_salinity_phenotypes(self, sal_min: Optional[float], sal_max: Optional[float]) -> List[dict]:
        """
        Classify salinity/halophily phenotypes based on min/max NaCl values.

        Uses METPO halophily classes based on maximum salinity tolerance.

        :param sal_min: Minimum salinity (% NaCl)
        :param sal_max: Maximum salinity (% NaCl)
        :return: List of phenotype dicts
        """
        phenotypes = []

        if sal_max is not None:
            # Classification based on maximum salinity tolerance - use METPO lookups
            phenotype_label = None
            if sal_max >= 15:
                phenotype_label = "extremely halophilic"
            elif sal_max >= 3:
                phenotype_label = "moderately halophilic"
            elif sal_max >= 1:
                phenotype_label = "slightly halophilic"
            else:
                phenotype_label = "non halophilic"

            if phenotype_label:
                metpo_class = self.metpo_label_to_class.get(phenotype_label)
                if metpo_class:
                    phenotypes.append(
                        {
                            "curie": metpo_class["curie"],
                            "category": metpo_class["category"],
                            "name": metpo_class["name"],
                            "predicate": "biolink:has_phenotype",
                        }
                    )

        return phenotypes

    def _classify_ph_optimum_bin(self, ph_opt: Optional[float]) -> Optional[dict]:
        """
        Classify pH optimum into METPO binned range class.

        Uses METPO pH optimum classes loaded from ontology.

        :param ph_opt: Optimal/growth pH
        :return: Binned class dict or None
        """
        return self._classify_into_binned_range(ph_opt, "pH")

    def _classify_ph_phenotypes(self, ph_min: Optional[float], ph_max: Optional[float]) -> List[dict]:
        """
        Classify pH preference phenotypes based on min/max pH values.

        Uses METPO pH phenotype classes based on pH range.

        :param ph_min: Minimum pH
        :param ph_max: Maximum pH
        :return: List of phenotype dicts
        """
        phenotypes = []

        if ph_min is not None and ph_max is not None:
            # Classification based on pH range - use METPO lookups
            if ph_max < 6.0:
                # Only grows in acidic conditions
                metpo_class = self.metpo_label_to_class.get("acidophilic")
                if metpo_class:
                    phenotypes.append(
                        {
                            "curie": metpo_class["curie"],
                            "category": metpo_class["category"],
                            "name": metpo_class["name"],
                            "predicate": "biolink:has_phenotype",
                        }
                    )
                # Check for obligate vs facultative
                if ph_min < 4.0:
                    metpo_class = self.metpo_label_to_class.get("obligately acidophilic")
                    if metpo_class:
                        phenotypes.append(
                            {
                                "curie": metpo_class["curie"],
                                "category": metpo_class["category"],
                                "name": metpo_class["name"],
                                "predicate": "biolink:has_phenotype",
                            }
                        )
            elif ph_min > 8.5:
                # Only grows in alkaline conditions
                # Use METPO:1003002 (alkaphilic) with synonym "alkaliphilic"
                metpo_class = self.metpo_label_to_class.get("alkaliphilic")
                if not metpo_class:
                    metpo_class = self.metpo_synonym_to_class.get("alkaliphilic")
                if metpo_class:
                    phenotypes.append(
                        {
                            "curie": metpo_class["curie"],
                            "category": metpo_class["category"],
                            "name": metpo_class["name"],
                            "predicate": "biolink:has_phenotype",
                        }
                    )
            elif ph_min >= 5.5 and ph_max <= 8.5:
                # Grows in neutral range
                metpo_class = self.metpo_label_to_class.get("neutrophilic")
                if metpo_class:
                    phenotypes.append(
                        {
                            "curie": metpo_class["curie"],
                            "category": metpo_class["category"],
                            "name": metpo_class["name"],
                            "predicate": "biolink:has_phenotype",
                        }
                    )
            # Broad pH tolerance (min < 5.5 and max > 8.5) - skip for now

        return phenotypes

    def _resolve_pigmentation_trait(self, trait_name: str, majority_label: str) -> Optional[dict]:
        """
        Resolve pigmentation/cell color traits using METPO pigmentation classes.

        Handles patterns like:
        - "cell color: yellow pigment" (true/false)

        Uses METPO pigmentation classes (METPO:1003022-1003031).

        :param trait_name: The trait name to resolve
        :param majority_label: The majority boolean value
        :return: dict with METPO pigmentation term or None if no match
        """
        import re

        # Extract boolean value
        has_pigment = "true" in majority_label.lower()

        # Pattern: cell color: yellow pigment
        color_match = re.match(r"^cell\s+color:\s*(\w+)\s+pigment$", trait_name.lower())
        if color_match:
            color = color_match.group(1)

            # Lookup color pigmentation class from METPO by label
            # Labels are like "yellow pigmented", "orange pigmented", etc.
            label_to_search = f"{color} pigmented"
            metpo_class = self.metpo_label_to_class.get(label_to_search.lower())

            if has_pigment and metpo_class:
                return metpo_class
            elif not has_pigment:
                # Non-pigmented - no specific METPO class for this
                # Skip for now - negative assertions less informative
                return None

        return None

    def _resolve_fermentation_trait(self, trait_name: str, majority_label: str) -> Optional[dict]:
        """
        Resolve fermentation capability traits.

        Handles patterns like:
        - "fermentation: D-glucose" (true/false)
        - "fermentation: lactose" (true/false)

        Uses METPO:2000011 (ferments) or METPO:2000037 (does not ferment).

        :param trait_name: The trait name to resolve
        :param majority_label: The majority boolean value
        :return: dict with fermentation details or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        # Pattern: fermentation: [substrate]
        match = re.match(r"^fermentation:\s*(.+)$", trait_name.lower())
        if match:
            substrate = match.group(1).strip()

            # Determine predicate based on boolean value using METPO pattern lookup
            can_ferment = "true" in majority_label.lower()
            predicate_data = self.metpo_pattern_to_predicate.get("fermentation")
            if not predicate_data:
                return None
            predicate = predicate_data["positive"] if can_ferment else predicate_data["negative"]

            # Lookup ChEBI ID for substrate
            chebi_id = self.chemical_loader.find_chebi_by_name(substrate)

            if chebi_id:
                canonical_name = self.chemical_loader.get_canonical_name(chebi_id)
                return {
                    "curie": chebi_id,
                    "category": "biolink:ChemicalEntity",
                    "name": canonical_name or substrate,
                    "predicate": predicate,
                }

        return None

    def _resolve_ph_preference_trait(self, trait_name: str, majority_label: str) -> Optional[dict]:
        """
        Resolve pH preference categorical traits.

        Handles patterns like:
        - "pH preference" with value "alkaliphile: (100%)"
        - "pH preference" with value "acidophile: (100%)"

        :param trait_name: The trait name to resolve
        :param majority_label: The categorical value
        :return: dict with pH preference phenotype or None if no match
        """
        if trait_name.lower() != "ph preference":
            return None

        # Check if majority_label is empty or no robust majority
        if not majority_label or "no robust majority" in majority_label.lower():
            # Cannot determine pH preference without clear majority value
            return None

        # Map pH preference values to METPO classes using lookups
        if "alkaliphile" in majority_label.lower():
            # Use METPO:1003002 (alkaphilic) with synonym "alkaliphilic"
            metpo_class = self.metpo_label_to_class.get("alkaliphilic")
            if not metpo_class:
                metpo_class = self.metpo_synonym_to_class.get("alkaliphilic")
            if metpo_class:
                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": "biolink:has_phenotype",
                }
        elif "acidophile" in majority_label.lower() or "acidophil" in majority_label.lower():
            # Use METPO lookup for acidophilic
            metpo_class = self.metpo_label_to_class.get("acidophilic")
            if metpo_class:
                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": "biolink:has_phenotype",
                }
        elif "neutrophile" in majority_label.lower() or "neutrophil" in majority_label.lower():
            # Use METPO lookup for neutrophilic
            metpo_class = self.metpo_label_to_class.get("neutrophilic")
            if metpo_class:
                return {
                    "curie": metpo_class["curie"],
                    "category": metpo_class["category"],
                    "name": metpo_class["name"],
                    "predicate": "biolink:has_phenotype",
                }

        return None

    def _resolve_energy_source(self, trait_name: str) -> Optional[dict]:
        """
        Resolve energy source patterns: energy source: [compound].

        Handles patterns like:
        - "energy source: glucose" -> CHEBI:17234

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        match = re.match(r"^energy source:\s*(.+)$", trait_name.lower())
        if match:
            compound = match.group(1).strip()
            chebi_id = self.chemical_loader.find_chebi_by_name(compound)
            if chebi_id:
                canonical_name = self.chemical_loader.get_canonical_name(chebi_id)

                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get("energy source")
                predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"

                return {
                    "curie": chebi_id,
                    "category": "biolink:ChemicalSubstance",
                    "name": canonical_name or compound,
                    "predicate": predicate,
                }
        return None

    def _resolve_nitrogen_source(self, trait_name: str) -> Optional[dict]:
        """
        Resolve nitrogen source patterns: nitrogen source: [compound].

        Handles patterns like:
        - "nitrogen source: ammonia" -> CHEBI:16134

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        match = re.match(r"^nitrogen source:\s*(.+)$", trait_name.lower())
        if match:
            compound = match.group(1).strip()
            chebi_id = self.chemical_loader.find_chebi_by_name(compound)
            if chebi_id:
                canonical_name = self.chemical_loader.get_canonical_name(chebi_id)

                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get("nitrogen source")
                predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"

                return {
                    "curie": chebi_id,
                    "category": "biolink:ChemicalSubstance",
                    "name": canonical_name or compound,
                    "predicate": predicate,
                }
        return None

    def _resolve_sulfur_source(self, trait_name: str) -> Optional[dict]:
        """
        Resolve sulfur source patterns: sulfur source: [compound].

        Handles patterns like:
        - "sulfur source: sulfate" -> CHEBI:16189

        :param trait_name: The trait name to resolve
        :return: dict with curie, category, name, predicate or None if no match
        """
        if not self.chemical_loader:
            return None

        import re

        match = re.match(r"^sulfur source:\s*(.+)$", trait_name.lower())
        if match:
            compound = match.group(1).strip()
            chebi_id = self.chemical_loader.find_chebi_by_name(compound)
            if chebi_id:
                canonical_name = self.chemical_loader.get_canonical_name(chebi_id)

                # Get predicate from METPO lookups
                predicate_data = self.metpo_pattern_to_predicate.get("sulfur source")
                predicate = predicate_data["positive"] if predicate_data else "biolink:capable_of"

                return {
                    "curie": chebi_id,
                    "category": "biolink:ChemicalSubstance",
                    "name": canonical_name or compound,
                    "predicate": predicate,
                }
        return None

    def _resolve_growth_temperature_observation(
        self, trait_name: str, majority_label: str
    ) -> Optional[dict]:
        """
        Resolve specific growth temperature observations.

        Handles patterns like:
        - "growth: 42 degrees Celsius" (true/false)
        - "growth: 37 degrees celsius" (true/false)

        Uses METPO:2000054 (has growth temperature observation) as predicate.
        Returns a dict marking this as a known pattern with the observation details.

        :param trait_name: The trait name to resolve
        :param majority_label: The majority boolean value (e.g., "true: (92%)")
        :return: dict with observation details or None if no match
        """
        import re

        # Pattern: growth: <number> degrees Celsius/celsius
        match = re.match(r"^growth:\s*(\d+(?:\.\d+)?)\s*degrees?\s*celsius$", trait_name.lower())
        if not match:
            return None

        temp_value = float(match.group(1))
        can_grow = "true" in majority_label.lower()

        # Use METPO observation predicate
        # Note: This is a known pattern but we defer quantitative observation modeling
        # Return marker dict to indicate pattern was recognized
        return {
            "observation_type": "growth_temperature",
            "predicate": "METPO:2000054",  # has growth temperature observation
            "value": temp_value,
            "unit": "Cel",
            "can_grow": can_grow,
            "deferred": True,  # Mark as recognized but not yet modeled
        }

    def _resolve_growth_nacl_observation(self, trait_name: str, majority_label: str) -> Optional[dict]:
        """
        Resolve specific growth NaCl/salinity observations.

        Handles patterns like:
        - "growth: 6.5% NaCl" (true/false)
        - "growth: 10% NaCl" (true/false)
        - "growth: 1% sodium chloride" (true/false)

        Uses METPO:2000508 (has growth NaCl observation) as predicate.
        Returns a dict marking this as a known pattern with the observation details.

        :param trait_name: The trait name to resolve
        :param majority_label: The majority boolean value
        :return: dict with observation details or None if no match
        """
        import re

        # Pattern 1: growth: <number>% NaCl
        match = re.match(r"^growth:\s*(\d+(?:\.\d+)?)\s*%\s*nacl$", trait_name.lower())

        # Pattern 2: growth: <number>% sodium chloride
        if not match:
            match = re.match(
                r"^growth:\s*(\d+(?:\.\d+)?)\s*%\s*sodium\s+chloride$", trait_name.lower()
            )

        if not match:
            return None

        nacl_percent = float(match.group(1))
        can_grow = "true" in majority_label.lower()

        # Use METPO observation predicate
        # Note: This is a known pattern but we defer quantitative observation modeling
        return {
            "observation_type": "growth_nacl",
            "predicate": "METPO:2000508",  # has growth NaCl observation
            "value": nacl_percent,
            "unit": "%",
            "can_grow": can_grow,
            "deferred": True,  # Mark as recognized but not yet modeled
        }

    def _is_measurement_trait(self, trait_name: str) -> bool:
        """
        Check if trait is a measurement (quantitative value, not ontology class).

        Measurement traits include temperature, pH, salinity, genome size, etc.
        These should be excluded from unmapped_traits.tsv and logged separately.

        :param trait_name: The trait name to check
        :return: True if this is a measurement trait
        """
        return trait_name.lower().strip() in self.MEASUREMENT_TRAITS

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

    def _calculate_optimal_workers_for_chunking(self) -> int:
        """
        Calculate optimal worker count for chunked processing (single file split into chunks).

        Unlike _calculate_optimal_workers, this doesn't limit by file count.

        :return: Optimal number of workers
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

            # For chunking, don't limit by file count (we're splitting 1 file)
            optimal = min(max_cpu_workers, max_memory_workers)

            print("  Resource-aware worker selection (chunked mode):")
            print(f"    CPU cores: {cpu_cores} → max {max_cpu_workers} workers")
            print(f"    Available memory: {available_memory_gb:.1f}GB → max {max_memory_workers} workers")
            print(f"    Selected: {optimal} parallel workers for chunking")

            return optimal

        except ImportError:
            print("  Warning: psutil not installed, using CPU count only")
            cpu_cores = multiprocessing.cpu_count()
            optimal = max(1, cpu_cores - 1)
            print(f"    CPU cores: {cpu_cores} → using {optimal} workers")
            return optimal

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
            "transform_class": self.__class__,  # Pass actual class for worker instantiation
            "input_base_dir": str(self.input_base_dir),
            "output_dir": str(self.output_dir),
            "knowledge_source": self.knowledge_source,
            "ncbitaxon_name_to_id": self.ncbitaxon_name_to_id,
            "trait_mapping": self.trait_mapping,
            "microbial_mappings": self.microbial_mappings,
            "metpo_mappings": self.metpo_mappings,
            "metpo_binned_ranges": self.metpo_binned_ranges,
            "metpo_label_to_class": self.metpo_label_to_class,
            "metpo_synonym_to_class": self.metpo_synonym_to_class,
            "metpo_pattern_to_predicate": self.metpo_pattern_to_predicate,
            "special_chemical_mappings": self.special_chemical_mappings,
            "chemical_name_synonyms": self.chemical_name_synonyms,
            "ec_to_go": self.ec_to_go,
            "enzyme_name_to_go": self.enzyme_name_to_go,
            "ncbi_to_gtdb_mappings": self.ncbi_to_gtdb_mappings,
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
        self.metpo_binned_ranges = shared_data["metpo_binned_ranges"]
        self.metpo_label_to_class = shared_data["metpo_label_to_class"]
        self.metpo_synonym_to_class = shared_data["metpo_synonym_to_class"]
        self.metpo_pattern_to_predicate = shared_data["metpo_pattern_to_predicate"]
        self.special_chemical_mappings = shared_data["special_chemical_mappings"]
        self.chemical_name_synonyms = shared_data["chemical_name_synonyms"]
        self.ec_to_go = shared_data["ec_to_go"]
        self.enzyme_name_to_go = shared_data["enzyme_name_to_go"]
        self.ncbi_to_gtdb_mappings = shared_data["ncbi_to_gtdb_mappings"]

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
        measurement_traits: List[Tuple[str, str, str, int]] = []
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
                        # Try strain resolution strategy
                        components = self._parse_taxonomic_components(tax_name)
                        genus = components["genus"]
                        species = components["species"]
                        strain_id = components["strain_id"]

                        if genus and strain_id:
                            # CASE 1: Strain-level name (e.g., "Arthrobacter sp. SF27")
                            # Create provisional strain node
                            tax_id = self._create_provisional_strain_node(
                                tax_name, genus, species, strain_id, node_writer
                            )

                            # Link to parent taxon
                            if species:
                                # Try exact species match
                                species_name = f"{genus} {species}"
                                species_id = self._search_ncbitaxon_by_label(species_name)

                                if species_id:
                                    # strain → NCBITaxon:species
                                    parent_id = species_id
                                    relation = "rdfs:subClassOf"
                                else:
                                    # Create provisional species → search genus
                                    parent_id = self._create_provisional_species_node(genus, species, node_writer)
                                    relation = INFERRED_SUBCLASS_RELATION

                                    # Link provisional species → NCBITaxon:genus or higher
                                    genus_id = self._search_ncbitaxon_by_label(genus)
                                    if genus_id:
                                        edge_writer.write_row(
                                            [
                                                parent_id,
                                                SUBCLASS_PREDICATE,
                                                genus_id,
                                                INFERRED_SUBCLASS_RELATION,
                                                self.knowledge_source,
                                                OBSERVATION,
                                                AUTOMATED_AGENT,
                                            ]
                                        )
                                    else:
                                        # Search higher ranks
                                        higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                        if higher_rank:
                                            edge_writer.write_row(
                                                [
                                                    parent_id,
                                                    SUBCLASS_PREDICATE,
                                                    higher_rank[0],
                                                    INFERRED_SUBCLASS_RELATION,
                                                    self.knowledge_source,
                                                    OBSERVATION,
                                                    AUTOMATED_AGENT,
                                                ]
                                            )
                            else:
                                # Only genus available - search genus
                                genus_id = self._search_ncbitaxon_by_label(genus)
                                if genus_id:
                                    parent_id = genus_id
                                    relation = INFERRED_SUBCLASS_RELATION
                                else:
                                    # Search higher ranks
                                    higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                    if higher_rank:
                                        parent_id = higher_rank[0]
                                        relation = INFERRED_SUBCLASS_RELATION
                                    else:
                                        # Still can't resolve - mark as unresolved
                                        unresolved_taxa.append(tax_name)
                                        continue

                            # Create strain → parent edge
                            edge_writer.write_row(
                                [
                                    tax_id,
                                    SUBCLASS_PREDICATE,
                                    parent_id,
                                    relation,
                                    self.knowledge_source,
                                    OBSERVATION,
                                    AUTOMATED_AGENT,
                                ]
                            )

                        elif genus and species:
                            # CASE 2: Valid species name without NCBITaxon match (e.g., "Algoriphagus aquimaris")
                            # Create provisional species
                            tax_id = self._create_provisional_species_node(genus, species, node_writer)

                            # Link to genus or higher rank
                            genus_id = self._search_ncbitaxon_by_label(genus)
                            if genus_id:
                                edge_writer.write_row(
                                    [
                                        tax_id,
                                        SUBCLASS_PREDICATE,
                                        genus_id,
                                        INFERRED_SUBCLASS_RELATION,
                                        self.knowledge_source,
                                        OBSERVATION,
                                        AUTOMATED_AGENT,
                                    ]
                                )
                            else:
                                higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                if higher_rank:
                                    edge_writer.write_row(
                                        [
                                            tax_id,
                                            SUBCLASS_PREDICATE,
                                            higher_rank[0],
                                            INFERRED_SUBCLASS_RELATION,
                                            self.knowledge_source,
                                            OBSERVATION,
                                            AUTOMATED_AGENT,
                                        ]
                                    )
                                else:
                                    # Can't resolve genus - still mark as unresolved
                                    unresolved_taxa.append(tax_name)
                                    continue
                        else:
                            # CASE 3: Cannot parse - keep as unresolved
                            unresolved_taxa.append(tax_name)
                            continue

                    summaries = obj.get("summaries", [])

                    # First pass: collect quantitative values for phenotype classification
                    quant_data = {
                        "temp_min": None,
                        "temp_max": None,
                        "temp_growth": None,
                        "sal_min": None,
                        "sal_max": None,
                        "sal_growth": None,
                        "ph_min": None,
                        "ph_max": None,
                        "ph_growth": None,
                    }

                    for s in summaries:
                        trait_name = s.get("name", "").strip()
                        if not trait_name:
                            continue
                        majority_label = s.get("majority_label", "")

                        # Extract quantitative values
                        if trait_name == "temperature minimum":
                            quant_data["temp_min"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "temperature maximum":
                            quant_data["temp_max"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "temperature growth":
                            quant_data["temp_growth"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "salinity minimum":
                            quant_data["sal_min"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "salinity maximum":
                            quant_data["sal_max"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "salinity growth":
                            quant_data["sal_growth"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "pH minimum":
                            quant_data["ph_min"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "pH maximum":
                            quant_data["ph_max"] = self._parse_quantitative_value(majority_label)
                        elif trait_name == "pH growth":
                            quant_data["ph_growth"] = self._parse_quantitative_value(majority_label)

                    # Create binned optimum value edges (not raw quantitative values)
                    # Temperature optimum bin
                    temp_opt_bin = self._classify_temperature_optimum_bin(quant_data["temp_growth"])
                    if temp_opt_bin:
                        curie = temp_opt_bin["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, temp_opt_bin["category"], temp_opt_bin["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                temp_opt_bin["predicate"],
                                curie,
                                temp_opt_bin["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    # NaCl optimum bin
                    nacl_opt_bin = self._classify_nacl_optimum_bin(quant_data["sal_growth"])
                    if nacl_opt_bin:
                        curie = nacl_opt_bin["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, nacl_opt_bin["category"], nacl_opt_bin["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                nacl_opt_bin["predicate"],
                                curie,
                                nacl_opt_bin["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    # pH optimum bin
                    ph_opt_bin = self._classify_ph_optimum_bin(quant_data["ph_growth"])
                    if ph_opt_bin:
                        curie = ph_opt_bin["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, ph_opt_bin["category"], ph_opt_bin["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                ph_opt_bin["predicate"],
                                curie,
                                ph_opt_bin["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    # Classify and create phenotype edges
                    temp_phenotypes = self._classify_temperature_phenotypes(
                        quant_data["temp_min"], quant_data["temp_max"]
                    )
                    for phenotype in temp_phenotypes:
                        curie = phenotype["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, phenotype["category"], phenotype["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                phenotype["predicate"],
                                curie,
                                phenotype["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    sal_phenotypes = self._classify_salinity_phenotypes(quant_data["sal_min"], quant_data["sal_max"])
                    for phenotype in sal_phenotypes:
                        curie = phenotype["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, phenotype["category"], phenotype["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                phenotype["predicate"],
                                curie,
                                phenotype["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    ph_phenotypes = self._classify_ph_phenotypes(quant_data["ph_min"], quant_data["ph_max"])
                    for phenotype in ph_phenotypes:
                        curie = phenotype["curie"]
                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_writer.write_row(
                                self._create_node_row(curie, phenotype["category"], phenotype["name"])
                            )
                        edge_writer.write_row(
                            [
                                tax_id,
                                phenotype["predicate"],
                                curie,
                                phenotype["predicate"],
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                                100.0,
                            ]
                        )

                    # Second pass: process regular traits
                    for s in summaries:
                        trait_name = s.get("name", "").strip()
                        if not trait_name:
                            continue

                        # Skip quantitative traits (already processed)
                        if trait_name in [
                            "temperature minimum",
                            "temperature maximum",
                            "temperature growth",
                            "salinity minimum",
                            "salinity maximum",
                            "salinity growth",
                            "pH minimum",
                            "pH maximum",
                            "pH growth",
                        ]:
                            continue

                        majority_label = s.get("majority_label", "")
                        percentages = s.get("percentages", {}) or {}
                        # Preserve 0.0 as float (avoid 'or 0' which coerces to int)
                        pct_true = float(percentages.get("true") if percentages.get("true") is not None else 0)

                        # Lookup order (METPO-first priority):
                        # Tier 1: METPO ontology mappings (HIGHEST PRIORITY - authoritative source)
                        # Tier 2: Curated external ontology mappings (ChEBI, GO, EC only)
                        # Tier 3: Pattern-based resolvers (chemical, metabolic, growth, trophic, enzyme, phenotype)

                        # Tier 1: METPO ontology mappings (FIRST)
                        mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(trait_name.lower())
                        if mapping:
                            curie = mapping["curie"]
                            category = mapping["category"]
                            pred = self._to_biolink_predicate(mapping["predicate"])
                            label = mapping["name"]
                        else:
                            # Tier 2: Manual mappings (external ontologies + METPO terms not in synonyms)
                            micro_mapping = self.microbial_mappings.get(trait_name) or self.microbial_mappings.get(
                                trait_name.lower()
                            )
                            if micro_mapping:
                                # Manual mapping (ChEBI, GO, EC, or METPO term not in METPO synonyms)
                                curie = micro_mapping["object_id"]
                                category = micro_mapping["object_category"]
                                pred = micro_mapping["biolink_predicate"]
                                label = micro_mapping["object_label"]
                            elif temp_obs := self._resolve_growth_temperature_observation(trait_name, majority_label):
                                # Tier 3.0a: Growth temperature observations (growth: 42 degrees Celsius)
                                # Known pattern but deferred - skip without adding to unmapped
                                if temp_obs.get("deferred"):
                                    continue
                                # If not deferred (future implementation), create edge
                                curie = f"kgmicrobe.observation:{tax_id}_{trait_name}"
                                category = "biolink:Attribute"
                                pred = "biolink:has_attribute"
                                label = f"Growth at {temp_obs['value']} {temp_obs['unit']}"
                            elif nacl_obs := self._resolve_growth_nacl_observation(trait_name, majority_label):
                                # Tier 3.0b: Growth NaCl observations (growth: 6.5% NaCl)
                                # Known pattern but deferred - skip without adding to unmapped
                                if nacl_obs.get("deferred"):
                                    continue
                                # If not deferred (future implementation), create edge
                                curie = f"kgmicrobe.observation:{tax_id}_{trait_name}"
                                category = "biolink:Attribute"
                                pred = "biolink:has_attribute"
                                label = f"Growth at {nacl_obs['value']}{nacl_obs['unit']} NaCl"
                            elif pigmentation := self._resolve_pigmentation_trait(trait_name, majority_label):
                                # Tier 3.0c: Pigmentation (cell color: yellow pigment)
                                curie = pigmentation["curie"]
                                category = pigmentation["category"]
                                pred = pigmentation["predicate"]
                                label = pigmentation["name"]
                            elif fermentation := self._resolve_fermentation_trait(trait_name, majority_label):
                                # Tier 3.0d: Fermentation (fermentation: D-glucose)
                                curie = fermentation["curie"]
                                category = fermentation["category"]
                                pred = self._to_biolink_predicate(fermentation["predicate"])
                                label = fermentation["name"]
                            elif ph_pref := self._resolve_ph_preference_trait(trait_name, majority_label):
                                # Tier 3.0e: pH preference (pH preference: alkaliphile)
                                curie = ph_pref["curie"]
                                category = ph_pref["category"]
                                pred = ph_pref["predicate"]
                                label = ph_pref["name"]
                            elif chemical_mapping := self._resolve_chemical_trait(trait_name):
                                # Tier 3.1: Chemical resolver (produces, ferments, carbon source, etc.)
                                curie = chemical_mapping["curie"]
                                category = chemical_mapping["category"]
                                pred = self._to_biolink_predicate(chemical_mapping["predicate"])
                                label = chemical_mapping["name"]
                            elif metabolic_mapping := self._resolve_metabolic_trait(trait_name):
                                # Tier 3.2: Metabolic processes (electron acceptors, respiration, oxidation, reduction)
                                curie = metabolic_mapping["curie"]
                                category = metabolic_mapping["category"]
                                pred = self._to_biolink_predicate(metabolic_mapping["predicate"])
                                label = metabolic_mapping["name"]
                            elif growth_mapping := self._resolve_growth_substrate(trait_name):
                                # Tier 3.3: Growth substrates (growth: X, builds acid from: X)
                                curie = growth_mapping["curie"]
                                category = growth_mapping["category"]
                                pred = self._to_biolink_predicate(growth_mapping["predicate"])
                                label = growth_mapping["name"]
                            elif trophic_mapping := self._resolve_trophic_mode(trait_name):
                                # Tier 3.4: Trophic modes (phototrophy, chemoheterotrophy, aerobic/anaerobic)
                                curie = trophic_mapping["curie"]
                                category = trophic_mapping["category"]
                                pred = self._to_biolink_predicate(trophic_mapping["predicate"])
                                label = trophic_mapping["name"]
                            elif enzyme_mapping := self._resolve_enzyme_activity(trait_name):
                                # Tier 3.5: Enzyme activities with EC numbers or GO mappings
                                curie = enzyme_mapping["curie"]
                                category = enzyme_mapping["category"]
                                pred = self._to_biolink_predicate(enzyme_mapping["predicate"])
                                label = enzyme_mapping["name"]
                            elif required_mapping := self._resolve_required_for_growth(trait_name):
                                # Tier 3.55: Required for growth (required for growth: biotin)
                                curie = required_mapping["curie"]
                                category = required_mapping["category"]
                                pred = self._to_biolink_predicate(required_mapping["predicate"])
                                label = required_mapping["name"]
                            elif phenotype_mapping := self._resolve_phenotype_trait(trait_name):
                                # Tier 3.6: Simple phenotypes (aerotolerant, facultative, acidophilic)
                                curie = phenotype_mapping["curie"]
                                category = phenotype_mapping["category"]
                                pred = self._to_biolink_predicate(phenotype_mapping["predicate"])
                                label = phenotype_mapping["name"]
                            elif energy_mapping := self._resolve_energy_source(trait_name):
                                # Tier 3.7: Energy sources (energy source: glucose)
                                curie = energy_mapping["curie"]
                                category = energy_mapping["category"]
                                pred = self._to_biolink_predicate(energy_mapping["predicate"])
                                label = energy_mapping["name"]
                            elif nitrogen_mapping := self._resolve_nitrogen_source(trait_name):
                                # Tier 3.8: Nitrogen sources (nitrogen source: ammonia)
                                curie = nitrogen_mapping["curie"]
                                category = nitrogen_mapping["category"]
                                pred = self._to_biolink_predicate(nitrogen_mapping["predicate"])
                                label = nitrogen_mapping["name"]
                            elif sulfur_mapping := self._resolve_sulfur_source(trait_name):
                                # Tier 3.9: Sulfur sources (sulfur source: sulfate)
                                curie = sulfur_mapping["curie"]
                                category = sulfur_mapping["category"]
                                pred = self._to_biolink_predicate(sulfur_mapping["predicate"])
                                label = sulfur_mapping["name"]
                            else:
                                # No mapping found - check if measurement trait or unmapped
                                if self._is_measurement_trait(trait_name):
                                    # Measurement trait - log separately
                                    measurement_traits.append(
                                        (
                                            trait_name,
                                            tax_name,
                                            majority_label,
                                            s.get("num_observations", 0),
                                        )
                                    )
                                else:
                                    # Unmapped trait (not a measurement)
                                    unmapped_traits.append(
                                        (
                                            trait_name,
                                            tax_name,
                                            majority_label,
                                            s.get("num_observations", 0),
                                        )
                                    )
                                continue

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
            "measurement_traits": measurement_traits,
            "unresolved_taxa": unresolved_taxa,
        }

    def _merge_worker_outputs(self, results: List[Dict[str, Any]], temp_dir: Path) -> None:
        """
        Merge temporary output files from parallel workers using chunked processing.

        Uses chunked reading and writing to keep peak memory bounded even for
        large outputs. Deduplication is done in a final pass.

        :param results: List of result dictionaries from workers
        :param temp_dir: Temporary directory containing worker output files
        """
        print("  Merging worker outputs...")

        # Process nodes: concatenate with chunked reading, then deduplicate
        print("    Concatenating node files...")
        first_file = True
        for result in results:
            # Read in chunks to reduce peak memory
            for chunk in pd.read_csv(result["nodes_file"], sep="\t", dtype=str, chunksize=50000):
                chunk.to_csv(
                    self.output_node_file,
                    sep="\t",
                    index=False,
                    mode="w" if first_file else "a",
                    header=first_file,
                )
                first_file = False

        # Deduplicate nodes in chunks
        print("    Deduplicating nodes...")
        temp_dedup = temp_dir / "nodes_dedup.tsv"
        seen_ids = set()
        first_chunk = True
        for chunk in pd.read_csv(self.output_node_file, sep="\t", dtype=str, chunksize=50000):
            # Filter out duplicates within and across chunks
            chunk = chunk[~chunk[ID_COLUMN].isin(seen_ids)]
            chunk = chunk.drop_duplicates(subset=[ID_COLUMN])
            seen_ids.update(chunk[ID_COLUMN])

            chunk.to_csv(temp_dedup, sep="\t", index=False, mode="w" if first_chunk else "a", header=first_chunk)
            first_chunk = False

        # Replace with deduplicated file and sort
        temp_dedup.replace(self.output_node_file)
        print("    Sorting nodes...")
        nodes_df = pd.read_csv(self.output_node_file, sep="\t", dtype=str)
        nodes_df = nodes_df.sort_values(by=ID_COLUMN)
        nodes_df.to_csv(self.output_node_file, sep="\t", index=False)

        # Process edges: concatenate with chunked reading, then deduplicate
        print("    Concatenating edge files...")
        first_file = True
        for result in results:
            for chunk in pd.read_csv(result["edges_file"], sep="\t", dtype=str, chunksize=50000):
                chunk.to_csv(
                    self.output_edge_file,
                    sep="\t",
                    index=False,
                    mode="w" if first_file else "a",
                    header=first_file,
                )
                first_file = False

        # Deduplicate edges in chunks
        print("    Deduplicating edges...")
        temp_dedup_edges = temp_dir / "edges_dedup.tsv"
        seen_edges = set()
        first_chunk = True
        for chunk in pd.read_csv(self.output_edge_file, sep="\t", dtype=str, chunksize=50000):
            # Create tuple key for each edge row
            chunk_tuples = chunk.apply(tuple, axis=1)
            mask = ~chunk_tuples.isin(seen_edges)
            chunk = chunk[mask]
            seen_edges.update(chunk_tuples[mask])

            chunk.to_csv(temp_dedup_edges, sep="\t", index=False, mode="w" if first_chunk else "a", header=first_chunk)
            first_chunk = False

        # Replace with deduplicated file
        temp_dedup_edges.replace(self.output_edge_file)

        # Merge unmapped traits, measurement traits, and unresolved taxa lists
        all_unmapped = []
        all_measurements = []
        all_unresolved = set()
        for result in results:
            all_unmapped.extend(result["unmapped_traits"])
            all_measurements.extend(result["measurement_traits"])
            all_unresolved.update(result["unresolved_taxa"])

        # Write unmapped traits
        with open(self.unmapped_traits_file, "w", newline="") as uf:
            uw = csv.writer(uf, delimiter="\t")
            uw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            uw.writerows(all_unmapped)

        # Write measurement traits
        with open(self.measurement_traits_file, "w", newline="") as mf:
            mw = csv.writer(mf, delimiter="\t")
            mw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            mw.writerows(all_measurements)

        # Write unresolved taxa
        with open(self.unresolved_taxa_file, "w", newline="") as rf:
            rw = csv.writer(rf, delimiter="\t")
            rw.writerow(["tax_name"])
            for t in sorted(all_unresolved):
                rw.writerow([t])

        # Cleanup temp files
        shutil.rmtree(temp_dir)
        print("  Merge complete.")

    def _split_file_into_chunks(self, input_file: Path, num_chunks: int, temp_dir: Path) -> List[Path]:
        """
        Split a single JSONL file into multiple chunk files for parallel processing.

        :param input_file: Input JSONL file to split
        :param num_chunks: Number of chunks to create
        :param temp_dir: Directory to write chunk files
        :return: List of chunk file paths
        """
        # Count total items first
        print(f"  Counting items in {input_file.name}...")
        with _open_jsonl(input_file) as f:
            total_items = sum(1 for line in f if line.strip())

        chunk_size = (total_items + num_chunks - 1) // num_chunks  # Ceiling division
        print(f"  Splitting {total_items} items into {num_chunks} chunks (~{chunk_size} items each)...")

        # Create chunk files
        chunk_files = []
        chunk_dir = temp_dir / "chunks"
        chunk_dir.mkdir(exist_ok=True, parents=True)

        current_chunk = 0
        items_in_chunk = 0
        chunk_file = None
        chunk_handle = None

        try:
            with _open_jsonl(input_file) as f:
                for line in tqdm(f, total=total_items, desc="  Creating chunks"):
                    line = line.strip()
                    if not line:
                        continue

                    # Start new chunk if needed
                    if items_in_chunk == 0:
                        if chunk_handle:
                            chunk_handle.close()
                        chunk_file = chunk_dir / f"chunk_{current_chunk:04d}.jsonl"
                        chunk_files.append(chunk_file)
                        chunk_handle = open(chunk_file, "w")

                    # Write to current chunk
                    chunk_handle.write(line + "\n")
                    items_in_chunk += 1

                    # Move to next chunk if full
                    if items_in_chunk >= chunk_size:
                        items_in_chunk = 0
                        current_chunk += 1

            if chunk_handle:
                chunk_handle.close()

        except Exception:
            if chunk_handle:
                chunk_handle.close()
            raise

        print(f"  Created {len(chunk_files)} chunk files")
        return chunk_files

    def _run_parallel_chunked(
        self, input_file: Path, show_status: bool = True, num_workers: Optional[int] = None
    ) -> None:
        """
        Process a single file in parallel by splitting into chunks.

        :param input_file: Input file to process
        :param show_status: Whether to show progress bars
        :param num_workers: Number of workers (None = auto-detect)
        """
        if num_workers is None:
            # For chunked processing, don't limit by file count (we're splitting 1 file)
            # Pass a dummy list to avoid file count limitation
            num_workers = self._calculate_optimal_workers_for_chunking()

        # Setup: create temp output directory
        temp_dir = self.output_dir / "temp"
        temp_dir.mkdir(exist_ok=True, parents=True)

        # Split file into chunks
        chunk_files = self._split_file_into_chunks(input_file, num_workers, temp_dir)

        # Process chunks using existing parallel infrastructure
        self._run_parallel(chunk_files, show_status, num_workers)

        # Cleanup chunk files
        chunk_dir = temp_dir / "chunks"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)

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
        measurement_traits: List[Tuple[str, str, str, int]] = []
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
                            # Try strain resolution strategy
                            components = self._parse_taxonomic_components(tax_name)
                            genus = components["genus"]
                            species = components["species"]
                            strain_id = components["strain_id"]

                            if genus and strain_id:
                                # CASE 1: Strain-level name (e.g., "Arthrobacter sp. SF27")
                                # Create provisional strain node
                                tax_id = self._create_provisional_strain_node(
                                    tax_name, genus, species, strain_id, node_writer
                                )

                                # Link to parent taxon
                                if species:
                                    # Try exact species match
                                    species_name = f"{genus} {species}"
                                    species_id = self._search_ncbitaxon_by_label(species_name)

                                    if species_id:
                                        # strain → NCBITaxon:species
                                        parent_id = species_id
                                        relation = "rdfs:subClassOf"
                                    else:
                                        # Create provisional species → search genus
                                        parent_id = self._create_provisional_species_node(genus, species, node_writer)
                                        relation = INFERRED_SUBCLASS_RELATION

                                        # Link provisional species → NCBITaxon:genus or higher
                                        genus_id = self._search_ncbitaxon_by_label(genus)
                                        if genus_id:
                                            edge_writer.write_row(
                                                [
                                                    parent_id,
                                                    SUBCLASS_PREDICATE,
                                                    genus_id,
                                                    INFERRED_SUBCLASS_RELATION,
                                                    self.knowledge_source,
                                                    OBSERVATION,
                                                    AUTOMATED_AGENT,
                                                ]
                                            )
                                        else:
                                            # Search higher ranks
                                            higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                            if higher_rank:
                                                edge_writer.write_row(
                                                    [
                                                        parent_id,
                                                        SUBCLASS_PREDICATE,
                                                        higher_rank[0],
                                                        INFERRED_SUBCLASS_RELATION,
                                                        self.knowledge_source,
                                                        OBSERVATION,
                                                        AUTOMATED_AGENT,
                                                    ]
                                                )
                                else:
                                    # Only genus available - search genus
                                    genus_id = self._search_ncbitaxon_by_label(genus)
                                    if genus_id:
                                        parent_id = genus_id
                                        relation = INFERRED_SUBCLASS_RELATION
                                    else:
                                        # Search higher ranks
                                        higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                        if higher_rank:
                                            parent_id = higher_rank[0]
                                            relation = INFERRED_SUBCLASS_RELATION
                                        else:
                                            # Still can't resolve - mark as unresolved
                                            unresolved_taxa.append(tax_name)
                                            continue

                                # Create strain → parent edge
                                edge_writer.write_row(
                                    [
                                        tax_id,
                                        SUBCLASS_PREDICATE,
                                        parent_id,
                                        relation,
                                        self.knowledge_source,
                                        OBSERVATION,
                                        AUTOMATED_AGENT,
                                    ]
                                )

                            elif genus and species:
                                # CASE 2: Valid species name without NCBITaxon match (e.g., "Algoriphagus aquimaris")
                                # Create provisional species
                                tax_id = self._create_provisional_species_node(genus, species, node_writer)

                                # Link to genus or higher rank
                                genus_id = self._search_ncbitaxon_by_label(genus)
                                if genus_id:
                                    edge_writer.write_row(
                                        [
                                            tax_id,
                                            SUBCLASS_PREDICATE,
                                            genus_id,
                                            INFERRED_SUBCLASS_RELATION,
                                            self.knowledge_source,
                                            OBSERVATION,
                                            AUTOMATED_AGENT,
                                        ]
                                    )
                                else:
                                    higher_rank = self._search_higher_ranks_in_ncbitaxon(genus)
                                    if higher_rank:
                                        edge_writer.write_row(
                                            [
                                                tax_id,
                                                SUBCLASS_PREDICATE,
                                                higher_rank[0],
                                                INFERRED_SUBCLASS_RELATION,
                                                self.knowledge_source,
                                                OBSERVATION,
                                                AUTOMATED_AGENT,
                                            ]
                                        )
                                    else:
                                        # Can't resolve genus - still mark as unresolved
                                        unresolved_taxa.append(tax_name)
                                        continue
                            else:
                                # CASE 3: Cannot parse - keep as unresolved
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

                            # Lookup order (METPO-first priority):
                            # Tier 1: METPO ontology mappings (FIRST)
                            mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(trait_name.lower())
                            if mapping:
                                curie = mapping["curie"]
                                category = mapping["category"]
                                pred = self._to_biolink_predicate(mapping["predicate"])
                                label = mapping["name"]
                            else:
                                # Tier 2: Manual mappings (external ontologies + METPO terms not in synonyms)
                                micro_mapping = self.microbial_mappings.get(trait_name) or self.microbial_mappings.get(
                                    trait_name.lower()
                                )
                                if micro_mapping:
                                    # Manual mapping (ChEBI, GO, EC, or METPO term not in METPO synonyms)
                                    curie = micro_mapping["object_id"]
                                    category = micro_mapping["object_category"]
                                    pred = micro_mapping["biolink_predicate"]
                                    label = micro_mapping["object_label"]
                                elif pigmentation := self._resolve_pigmentation_trait(trait_name, majority_label):
                                    # Tier 3.0b: Pigmentation
                                    curie = pigmentation["curie"]
                                    category = pigmentation["category"]
                                    pred = pigmentation["predicate"]
                                    label = pigmentation["name"]
                                elif fermentation := self._resolve_fermentation_trait(trait_name, majority_label):
                                    # Tier 3.0c: Fermentation
                                    curie = fermentation["curie"]
                                    category = fermentation["category"]
                                    pred = self._to_biolink_predicate(fermentation["predicate"])
                                    label = fermentation["name"]
                                elif ph_pref := self._resolve_ph_preference_trait(trait_name, majority_label):
                                    # Tier 3.0d: pH preference
                                    curie = ph_pref["curie"]
                                    category = ph_pref["category"]
                                    pred = ph_pref["predicate"]
                                    label = ph_pref["name"]
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
                                elif required_mapping := self._resolve_required_for_growth(trait_name):
                                    curie = required_mapping["curie"]
                                    category = required_mapping["category"]
                                    pred = self._to_biolink_predicate(required_mapping["predicate"])
                                    label = required_mapping["name"]
                                elif phenotype_mapping := self._resolve_phenotype_trait(trait_name):
                                    curie = phenotype_mapping["curie"]
                                    category = phenotype_mapping["category"]
                                    pred = self._to_biolink_predicate(phenotype_mapping["predicate"])
                                    label = phenotype_mapping["name"]
                                elif energy_mapping := self._resolve_energy_source(trait_name):
                                    curie = energy_mapping["curie"]
                                    category = energy_mapping["category"]
                                    pred = self._to_biolink_predicate(energy_mapping["predicate"])
                                    label = energy_mapping["name"]
                                elif nitrogen_mapping := self._resolve_nitrogen_source(trait_name):
                                    curie = nitrogen_mapping["curie"]
                                    category = nitrogen_mapping["category"]
                                    pred = self._to_biolink_predicate(nitrogen_mapping["predicate"])
                                    label = nitrogen_mapping["name"]
                                elif sulfur_mapping := self._resolve_sulfur_source(trait_name):
                                    curie = sulfur_mapping["curie"]
                                    category = sulfur_mapping["category"]
                                    pred = self._to_biolink_predicate(sulfur_mapping["predicate"])
                                    label = sulfur_mapping["name"]
                                else:
                                    # No mapping found - check if measurement trait or unmapped
                                    if self._is_measurement_trait(trait_name):
                                        # Measurement trait - log separately
                                        measurement_traits.append(
                                            (
                                                trait_name,
                                                tax_name,
                                                majority_label,
                                                s.get("num_observations", 0),
                                            )
                                        )
                                    else:
                                        # Unmapped trait (not a measurement)
                                        unmapped_traits.append(
                                            (
                                                trait_name,
                                                tax_name,
                                                majority_label,
                                                s.get("num_observations", 0),
                                            )
                                        )
                                    continue

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

        # Write unmapped traits, measurement traits, and unresolved taxa
        with open(self.unmapped_traits_file, "w", newline="") as uf:
            uw = csv.writer(uf, delimiter="\t")
            uw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            uw.writerows(unmapped_traits)

        with open(self.measurement_traits_file, "w", newline="") as mf:
            mw = csv.writer(mf, delimiter="\t")
            mw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            mw.writerows(measurement_traits)

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
        for name in self._get_input_file_names():
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
                f"No metatraits JSONL files found in {input_base}. Expected one of: {self._get_input_file_names()}"
            )

        # Check environment variable for disabling multiprocessing
        use_mp = self.use_multiprocessing
        if os.environ.get("METATRAITS_MULTIPROCESSING", "").lower() in ("false", "0", "no"):
            use_mp = False
            print("  Multiprocessing disabled via METATRAITS_MULTIPROCESSING environment variable")

        # Decide whether to use parallel or sequential processing
        try:
            if use_mp and len(input_files) > 1:
                # Multiple files: distribute files across workers
                self._run_parallel(input_files, show_status, self.num_workers)
            elif use_mp and len(input_files) == 1:
                # Single file: split into chunks for parallel processing
                workers = self.num_workers or "auto"
                print(f"  Using parallel chunked processing (splitting 1 file across {workers} workers)")
                self._run_parallel_chunked(input_files[0], show_status, self.num_workers)
            else:
                # No multiprocessing: sequential
                self._run_sequential(input_files, show_status)
        finally:
            # Clean up OAK adapter resources
            try:
                if hasattr(self, "_ncbi_adapter") and self._ncbi_adapter is not None:
                    if hasattr(self._ncbi_adapter, "engine") and self._ncbi_adapter.engine is not None:
                        self._ncbi_adapter.engine.dispose()
                self._ncbi_adapter = None
            except Exception:  # noqa: S110
                pass  # Ignore cleanup errors
