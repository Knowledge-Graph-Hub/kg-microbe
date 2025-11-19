"""Utility functions for Bakta genome annotations transform."""

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def parse_bakta_tsv(
    tsv_file: Path, feature_types: Optional[Set[str]] = None
) -> List[Dict[str, str]]:
    """
    Parse a Bakta TSV annotation file.

    :param tsv_file: Path to .bakta.tsv file
    :param feature_types: Set of feature types to include (default: {'cds'})
    :return: List of dictionaries with gene annotations
    """
    if feature_types is None:
        feature_types = {"cds"}

    genes = []

    with open(tsv_file, "r") as f:
        # Read all lines and filter out comment lines
        # Keep only: data lines and the header line (#Sequence Id...)
        # Filter out: lines starting with "# " (hash + space) or "##"
        lines = []
        for line in f:
            if line.startswith("##"):
                # Skip ## comments
                continue
            elif line.startswith("# "):
                # Skip # comments (with space after hash)
                continue
            else:
                # Keep header (#Sequence Id) and data lines
                lines.append(line)

        if not lines:
            return genes

        # Remove the # from the header line (first line should be #Sequence Id...)
        if lines[0].startswith("#"):
            lines[0] = lines[0][1:]  # Remove the first character (#)

        # Create CSV reader from the remaining lines
        reader = csv.DictReader(lines, delimiter="\t")

        for row in reader:
            # Filter by feature type if specified
            if row.get("Type") in feature_types:
                genes.append(row)

    return genes


def parse_dbxrefs(dbxref_string: str) -> Dict[str, List[str]]:
    """
    Parse the DbXrefs column from Bakta TSV into structured annotations.

    :param dbxref_string: Comma-separated string of database cross-references
    :return: Dictionary with annotation types as keys and lists of IDs as values
    """
    annotations = {
        "go": [],
        "ec": [],
        "uniref": [],
        "refseq": [],
        "cog": [],
        "kegg": [],
        "uniparc": [],
        "rfam": [],
        "so": [],
    }

    if not dbxref_string or dbxref_string.strip() == "":
        return annotations

    # Split by comma and process each item
    for item in dbxref_string.split(","):
        item = item.strip()

        # GO terms
        if item.startswith("GO:"):
            annotations["go"].append(item)
        # EC numbers
        elif item.startswith("EC:"):
            annotations["ec"].append(item)
        # UniRef (all three levels: 100/90/50)
        elif item.startswith("UniRef:"):
            # Extract just the ID (e.g., UniRef50_Q8EUL1)
            annotations["uniref"].append(item.replace("UniRef:", ""))
        # RefSeq
        elif item.startswith("RefSeq:"):
            annotations["refseq"].append(item.replace("RefSeq:", ""))
        # COG (only COG:COGXXXX, not COG:X letter codes)
        elif item.startswith("COG:COG"):
            annotations["cog"].append(item)
        # KEGG
        elif item.startswith("KEGG:"):
            annotations["kegg"].append(item)
        # UniParc
        elif item.startswith("UniParc:"):
            annotations["uniparc"].append(item.replace("UniParc:", ""))
        # RFAM
        elif item.startswith("RFAM:"):
            annotations["rfam"].append(item)
        # SO (Sequence Ontology)
        elif item.startswith("SO:"):
            annotations["so"].append(item)

    return annotations


def create_gene_id(samn_id: str, locus_tag: str) -> str:
    """
    Create a composite gene ID from SAMN ID and locus tag.

    :param samn_id: SAMN identifier (e.g., 'SAMN00139461')
    :param locus_tag: Gene locus tag (e.g., 'JEECHJ_00005')
    :return: Composite gene ID (e.g., 'SAMN00139461:JEECHJ_00005')
    """
    return f"{samn_id}:{locus_tag}"


def get_protein_id(annotations: Dict[str, List[str]], prefer_refseq: bool = True) -> Optional[str]:
    """
    Get the best protein identifier from annotations.

    Strategy: Prefer RefSeq, fall back to UniRef50.

    :param annotations: Dictionary of parsed annotations from parse_dbxrefs()
    :param prefer_refseq: Whether to prefer RefSeq over UniRef (default: True)
    :return: Protein ID string with prefix, or None if no protein ID found
    """
    # Prefer RefSeq if available
    if prefer_refseq and annotations.get("refseq"):
        # Return first RefSeq ID with prefix
        return f"RefSeq:{annotations['refseq'][0]}"

    # Fall back to UniRef50 (most commonly used cluster level)
    if annotations.get("uniref"):
        # Find UniRef50 entry
        for uniref_id in annotations["uniref"]:
            if "UniRef50_" in uniref_id:
                return f"UniRef:{uniref_id}"

        # If no UniRef50, use UniRef90
        for uniref_id in annotations["uniref"]:
            if "UniRef90_" in uniref_id:
                return f"UniRef:{uniref_id}"

        # Last resort: use first UniRef entry
        return f"UniRef:{annotations['uniref'][0]}"

    # No protein ID found
    return None


def get_go_aspect(go_id: str, go_adapter) -> str:
    """
    Determine the aspect (namespace) of a GO term.

    :param go_id: GO identifier (e.g., 'GO:0003677')
    :param go_adapter: OAK adapter for GO ontology (can be None)
    :return: One of 'biological_process', 'molecular_function', 'cellular_component'
    """
    # If no adapter available, default to molecular_function
    if go_adapter is None:
        return "molecular_function"

    try:
        # Get the term from the ontology
        term = go_adapter.get_entity(go_id)
        if term:
            # Try to get namespace/aspect from metadata
            metadata = go_adapter.entity_metadata_map(go_id)
            if metadata and "namespace" in metadata:
                return metadata["namespace"]

            # Fallback: query for namespace property
            for stmt in go_adapter.query([go_id], predicates=["oio:hasOBONamespace"]):
                if stmt.value:
                    return stmt.value

    except Exception as e:
        logger.warning(f"Could not determine aspect for {go_id}: {e}")

    # Default to molecular_function if unknown
    return "molecular_function"


def get_biolink_category_for_go(aspect: str) -> str:
    """
    Map GO aspect to Biolink category.

    :param aspect: GO aspect ('biological_process', 'molecular_function', 'cellular_component')
    :return: Biolink category string
    """
    aspect_map = {
        "biological_process": "biolink:BiologicalProcess",
        "molecular_function": "biolink:MolecularActivity",
        "cellular_component": "biolink:CellularComponent",
    }

    return aspect_map.get(aspect, "biolink:MolecularActivity")


def get_biolink_predicate_for_go(aspect: str) -> Tuple[str, str]:
    """
    Get Biolink predicate and RO relation for a GO aspect.

    :param aspect: GO aspect ('biological_process', 'molecular_function', 'cellular_component')
    :return: Tuple of (predicate, relation)
    """
    predicate_map = {
        "biological_process": ("biolink:involved_in", "RO:0002331"),
        "molecular_function": ("biolink:enables", "RO:0002327"),
        "cellular_component": ("biolink:located_in", "RO:0001025"),
    }

    return predicate_map.get(aspect, ("biolink:enables", "RO:0002327"))


def load_samn_to_ncbitaxon_mapping(mapping_file: Path) -> Dict[str, str]:
    """
    Load SAMN to NCBITaxon mapping from TSV file.

    :param mapping_file: Path to TSV file with columns: samn_id, ncbitaxon_id
    :return: Dictionary mapping SAMN IDs to NCBITaxon IDs
    """
    mapping = {}

    if not mapping_file.exists():
        logger.warning(f"SAMN to NCBITaxon mapping file not found: {mapping_file}")
        return mapping

    with open(mapping_file, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            samn_id = row.get("samn_id", "").strip()
            ncbitaxon_id = row.get("ncbitaxon_id", "").strip()

            if samn_id and ncbitaxon_id:
                # Ensure SAMN has SAMN prefix
                if not samn_id.startswith("SAMN"):
                    samn_id = f"SAMN{samn_id}"

                # Ensure NCBITaxon has NCBITaxon prefix
                if not ncbitaxon_id.startswith("NCBITaxon:"):
                    ncbitaxon_id = f"NCBITaxon:{ncbitaxon_id}"

                mapping[samn_id] = ncbitaxon_id

    logger.info(f"Loaded {len(mapping)} SAMN to NCBITaxon mappings")
    return mapping


def extract_samn_from_path(path: Path) -> Optional[str]:
    """
    Extract SAMN ID from directory or file path.

    :param path: Path containing SAMN ID
    :return: SAMN ID (e.g., 'SAMN00139461') or None if not found
    """
    # Try to match SAMN pattern in path
    match = re.search(r"SAMN\d+", str(path))
    if match:
        return match.group(0)
    return None


def get_all_samn_directories(base_dir: Path) -> List[Path]:
    """
    Get all SAMN directories in the base Bakta directory.

    :param base_dir: Base directory containing SAMN subdirectories
    :return: List of paths to SAMN directories
    """
    samn_dirs = []

    if not base_dir.exists():
        logger.error(f"Bakta base directory does not exist: {base_dir}")
        return samn_dirs

    for item in base_dir.iterdir():
        if item.is_dir() and re.match(r"SAMN\d+", item.name):
            samn_dirs.append(item)

    logger.info(f"Found {len(samn_dirs)} SAMN directories in {base_dir}")
    return sorted(samn_dirs)


def find_bakta_tsv(samn_dir: Path) -> Optional[Path]:
    """
    Find the .bakta.tsv file in a SAMN directory.

    :param samn_dir: Path to SAMN directory
    :return: Path to .bakta.tsv file or None if not found
    """
    # Look for *.bakta.tsv file
    tsv_files = list(samn_dir.glob("*.bakta.tsv"))

    if not tsv_files:
        logger.warning(f"No .bakta.tsv file found in {samn_dir}")
        return None

    if len(tsv_files) > 1:
        logger.warning(f"Multiple .bakta.tsv files found in {samn_dir}, using first")

    return tsv_files[0]
