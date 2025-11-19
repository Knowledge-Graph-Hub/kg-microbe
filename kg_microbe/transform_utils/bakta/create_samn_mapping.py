"""
Helper script to create SAMN to NCBITaxon mapping file.

This script can be used to generate the samn_to_ncbitaxon.tsv mapping file
needed by the Bakta transform. It queries NCBI databases to map BioSample
accessions (SAMN) to NCBI Taxonomy IDs.

Usage:
    python create_samn_mapping.py --input bakta_dir --output samn_to_ncbitaxon.tsv

Requirements:
    pip install biopython

Note: This requires network access to query NCBI Entrez API.
You may need to set NCBI_API_KEY environment variable for higher rate limits.
"""

import argparse
import csv
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

try:
    from Bio import Entrez
except ImportError:
    print("BioPython is required. Install with: pip install biopython")
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_all_samn_ids(bakta_dir: Path) -> list:
    """
    Extract all SAMN IDs from Bakta directory structure.

    :param bakta_dir: Path to bakta directory containing SAMN subdirectories
    :return: List of SAMN IDs
    """
    samn_ids = []

    for item in bakta_dir.iterdir():
        if item.is_dir() and re.match(r"SAMN\d+", item.name):
            samn_ids.append(item.name)

    logger.info(f"Found {len(samn_ids)} SAMN IDs in {bakta_dir}")
    return sorted(samn_ids)


def query_ncbi_for_taxon(samn_id: str, email: str = "your_email@example.com") -> Optional[str]:
    """
    Query NCBI to get NCBITaxon ID for a BioSample accession.

    :param samn_id: BioSample accession (e.g., 'SAMN00139461')
    :param email: Email for NCBI Entrez (required by NCBI)
    :return: NCBITaxon ID or None if not found
    """
    Entrez.email = email

    try:
        # Search BioSample database
        logger.debug(f"Querying NCBI for {samn_id}")
        search_handle = Entrez.esearch(db="biosample", term=samn_id, retmax=1)
        search_results = Entrez.read(search_handle)
        search_handle.close()

        if not search_results["IdList"]:
            logger.warning(f"No BioSample found for {samn_id}")
            return None

        biosample_id = search_results["IdList"][0]

        # Fetch BioSample record as XML (parse manually to avoid DTD issues)
        fetch_handle = Entrez.efetch(db="biosample", id=biosample_id, retmode="xml")
        xml_data = fetch_handle.read()
        fetch_handle.close()

        # Parse XML manually with ElementTree
        # Note: Data comes from trusted NCBI API, not user input
        root = ET.fromstring(xml_data)  # noqa: S314

        # Look for taxonomy_id attribute in Organism element
        # XML structure: <BioSampleSet><BioSample><Description><Organism taxonomy_id="...">
        for organism in root.iter("Organism"):
            taxon_id = organism.get("taxonomy_id")
            if taxon_id:
                logger.info(f"{samn_id} -> NCBITaxon:{taxon_id}")
                return taxon_id

        logger.warning(f"No taxonomy ID found for {samn_id}")
        return None

    except ET.ParseError as e:
        logger.error(f"Error parsing XML for {samn_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error querying NCBI for {samn_id}: {e}")
        return None


def create_mapping_file(
    samn_ids: list, output_file: Path, email: str, delay: float = 0.4
) -> Dict[str, str]:
    """
    Create SAMN to NCBITaxon mapping file by querying NCBI.

    :param samn_ids: List of SAMN IDs to map
    :param output_file: Path to output TSV file
    :param email: Email for NCBI Entrez
    :param delay: Delay between queries in seconds (default: 0.4s for 3 requests/sec)
    :return: Dictionary of successfully mapped IDs
    """
    mapping = {}

    # Create output file with header
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["samn_id", "ncbitaxon_id"])

        # Query each SAMN ID
        for i, samn_id in enumerate(samn_ids, 1):
            logger.info(f"Processing {i}/{len(samn_ids)}: {samn_id}")

            taxon_id = query_ncbi_for_taxon(samn_id, email)

            if taxon_id:
                writer.writerow([samn_id, taxon_id])
                mapping[samn_id] = taxon_id
                f.flush()  # Write immediately in case of interruption

            # Rate limiting: NCBI allows 3 requests/second without API key
            time.sleep(delay)

    logger.info(f"Mapping complete: {len(mapping)}/{len(samn_ids)} IDs mapped")
    logger.info(f"Mapping saved to: {output_file}")

    return mapping


def load_existing_mapping(mapping_file: Path) -> Dict[str, str]:
    """
    Load existing mapping file to avoid re-querying.

    :param mapping_file: Path to existing mapping file
    :return: Dictionary of SAMN to NCBITaxon mappings
    """
    mapping = {}

    if not mapping_file.exists():
        return mapping

    with open(mapping_file, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            mapping[row["samn_id"]] = row["ncbitaxon_id"]

    logger.info(f"Loaded {len(mapping)} existing mappings from {mapping_file}")
    return mapping


def main():
    """Run the SAMN to NCBITaxon mapping creation process."""
    parser = argparse.ArgumentParser(
        description="Create SAMN to NCBITaxon mapping file for Bakta transform"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="Path to Bakta directory containing SAMN subdirectories",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("samn_to_ncbitaxon.tsv"),
        help="Path to output mapping file (default: samn_to_ncbitaxon.tsv)",
    )
    parser.add_argument(
        "--email",
        "-e",
        type=str,
        default="your_email@example.com",
        help="Email for NCBI Entrez (required by NCBI)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.4,
        help="Delay between NCBI queries in seconds (default: 0.4 for 3 req/sec)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing mapping file (skip already mapped IDs)",
    )

    args = parser.parse_args()

    # Get all SAMN IDs from Bakta directory
    samn_ids = get_all_samn_ids(args.input)

    if not samn_ids:
        logger.error("No SAMN directories found")
        return

    # Load existing mappings if resuming
    if args.resume and args.output.exists():
        existing = load_existing_mapping(args.output)
        # Filter out already mapped IDs
        samn_ids = [sid for sid in samn_ids if sid not in existing]
        logger.info(f"Resuming: {len(samn_ids)} IDs remaining to query")

        # Append to existing file
        logger.info("Appending to existing mapping file")

    # Create mapping
    logger.info(f"Querying NCBI for {len(samn_ids)} SAMN IDs")
    logger.info(f"This will take approximately {len(samn_ids) * args.delay / 60:.1f} minutes")

    create_mapping_file(samn_ids, args.output, args.email, args.delay)

    logger.info("Done!")


if __name__ == "__main__":
    main()
