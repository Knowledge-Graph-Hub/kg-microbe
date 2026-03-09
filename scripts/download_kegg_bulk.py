#!/usr/bin/env python
"""
Bulk download KEGG KO details to avoid API calls during transform.

This script downloads detailed information for all KEGG KO entries
and saves them to a JSON file for offline use during transforms.

LICENSING NOTICE:
    This script uses the KEGG REST API which is free for academic use
    by individual users. Each user should run this script themselves.

    DO NOT redistribute the resulting ko_details.json file.

    Bulk redistribution requires a KEGG Service Provider License.
    See: https://www.kegg.jp/kegg/legal.html

    The KEGG REST API has rate limiting (max 10 requests/sec).
    This script respects that limit and takes ~50 minutes to complete.

Usage:
    python scripts/download_kegg_bulk.py

Output:
    data/raw/kegg/ko_details.json (for local use only)
"""

import json
import logging
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

KEGG_REST_URL = "https://rest.kegg.jp"
REQUEST_DELAY = 0.11  # KEGG rate limit: max 10 requests per second

# Paths
RAW_DIR = Path("data/raw/kegg")
KO_LIST_FILE = RAW_DIR / "ko_list.txt"
KO_DETAILS_FILE = RAW_DIR / "ko_details.json"


def parse_ko_list(ko_list_file: Path) -> list:
    """Parse KO list file to get list of KO IDs."""
    ko_ids = []

    if not ko_list_file.exists():
        logger.error(f"KO list file not found: {ko_list_file}")
        return ko_ids

    with open(ko_list_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Format: ko:K00001<tab>description
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue

            ko_id = parts[0].replace("ko:", "")
            ko_ids.append(ko_id)

    logger.info(f"Found {len(ko_ids)} KO entries in list")
    return ko_ids


def get_ko_details(ko_id: str) -> dict:
    """Fetch detailed information for a KO entry."""
    url = f"{KEGG_REST_URL}/get/{ko_id}"

    try:
        time.sleep(REQUEST_DELAY)
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return {"ko_id": ko_id, "entry_text": response.text}
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch {ko_id}: {e}")
        return {"ko_id": ko_id, "entry_text": None, "error": str(e)}


def download_all_ko_details(ko_ids: list, output_file: Path, resume: bool = True) -> None:
    """
    Download details for all KO entries.

    :param ko_ids: List of KO identifiers
    :param output_file: Path to save JSON results
    :param resume: If True, skip already downloaded entries
    """
    # Load existing data if resuming
    existing_data = {}
    if resume and output_file.exists():
        logger.info(f"Resuming from existing file: {output_file}")
        with open(output_file, "r") as f:
            existing_data = json.load(f)
        logger.info(f"Found {len(existing_data)} existing entries")

    total = len(ko_ids)
    downloaded = 0
    skipped = 0
    failed = 0

    logger.info(f"Downloading details for {total} KO entries...")
    logger.info(f"Estimated time: ~{total * REQUEST_DELAY / 60:.1f} minutes")

    all_details = existing_data.copy()

    for i, ko_id in enumerate(ko_ids, 1):
        # Skip if already downloaded
        if ko_id in existing_data:
            skipped += 1
            if i % 1000 == 0:
                logger.info(f"Progress: {i}/{total} ({downloaded} new, {skipped} skipped, {failed} failed)")
            continue

        # Fetch details
        details = get_ko_details(ko_id)
        all_details[ko_id] = details

        if details.get("entry_text"):
            downloaded += 1
        else:
            failed += 1

        # Progress update every 100 entries
        if i % 100 == 0:
            logger.info(f"Progress: {i}/{total} ({downloaded} new, {skipped} skipped, {failed} failed)")

            # Save checkpoint every 1000 entries
            if i % 1000 == 0:
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, "w") as f:
                    json.dump(all_details, f, indent=2)
                logger.info(f"Checkpoint saved to {output_file}")

    # Final save
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(all_details, f, indent=2)

    logger.info(f"Complete! Downloaded {downloaded} new entries, skipped {skipped}, failed {failed}")
    logger.info(f"Total entries in file: {len(all_details)}")
    logger.info(f"Saved to: {output_file}")


def main():
    """Main function."""
    # Check if KO list exists
    if not KO_LIST_FILE.exists():
        logger.error(f"KO list file not found: {KO_LIST_FILE}")
        logger.error("Please run 'poetry run kg download' first")
        return

    # Parse KO list
    ko_ids = parse_ko_list(KO_LIST_FILE)

    if not ko_ids:
        logger.error("No KO entries found in list file")
        return

    # Download all details (with resume capability)
    download_all_ko_details(ko_ids, KO_DETAILS_FILE, resume=True)


if __name__ == "__main__":
    main()
