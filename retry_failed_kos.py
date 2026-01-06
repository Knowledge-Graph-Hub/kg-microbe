#!/usr/bin/env python3
"""Retry failed KEGG KO entries with better retry logic."""

import csv
import logging
import time
from pathlib import Path

from kg_microbe.transform_utils.kegg.utils import get_kegg_ko_details

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Failed KO IDs
FAILED_KOS = [
    "K13009", "K18648", "K18672", "K19958", "K20089", "K20113", "K20139",
    "K20244", "K20328", "K20372", "K20398", "K20421", "K20450", "K20473",
    "K20560", "K20614", "K20638", "K20662", "K20817", "K20929", "K20955",
    "K20956", "K20957", "K20958", "K20959", "K20960", "K20961", "K20962",
    "K20963", "K20964", "K20965", "K20966", "K20967", "K20968", "K20969",
    "K20970", "K20971", "K20972", "K20973", "K20974", "K20975", "K20976",
    "K20977", "K20978", "K20995", "K21106", "K22113", "K22158"
]

EDGES_FILE = Path("data/transformed/kegg/edges.tsv")
RETRY_EDGES_FILE = Path("/tmp/kegg_retry_edges.tsv")


def retry_with_backoff(ko_id: str, max_retries: int = 5):
    """Retry fetching KO details with exponential backoff."""
    for attempt in range(max_retries):
        try:
            details = get_kegg_ko_details(ko_id)
            if details:
                return details
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {ko_id}: {e}")

        if attempt < max_retries - 1:
            wait_time = (2 ** attempt) * 0.5  # 0.5, 1, 2, 4, 8 seconds
            logger.info(f"Waiting {wait_time}s before retry...")
            time.sleep(wait_time)

    return None


def main():
    """Retry failed KO entries and create additional edges."""
    new_edges = []

    logger.info(f"Retrying {len(FAILED_KOS)} failed KO entries...")

    for i, ko_id in enumerate(FAILED_KOS, 1):
        logger.info(f"Processing {i}/{len(FAILED_KOS)}: {ko_id}")

        details = retry_with_backoff(ko_id)

        if details:
            # Create pathway edges
            for pathway in details.get("pathways", []):
                new_edges.append({
                    "subject": f"KEGG:{ko_id}",
                    "predicate": "biolink:subclass_of",
                    "object": f"KEGG:{pathway['id']}",
                    "relation": "rdfs:subClassOf",
                    "primary_knowledge_source": "infores:kegg"
                })

            # Create module edges
            for module in details.get("modules", []):
                new_edges.append({
                    "subject": f"KEGG:{ko_id}",
                    "predicate": "biolink:subclass_of",
                    "object": f"KEGG:{module['id']}",
                    "relation": "rdfs:subClassOf",
                    "primary_knowledge_source": "infores:kegg"
                })

            logger.info(f"  Created {len(details.get('pathways', []))} pathway edges and {len(details.get('modules', []))} module edges")
        else:
            logger.warning(f"  Failed to fetch details for {ko_id} after all retries")

    # Write new edges to temporary file
    if new_edges:
        logger.info(f"Writing {len(new_edges)} new edges to {RETRY_EDGES_FILE}")
        with open(RETRY_EDGES_FILE, "w") as f:
            writer = csv.DictWriter(f, fieldnames=["subject", "predicate", "object", "relation", "primary_knowledge_source"], delimiter="\t")
            writer.writeheader()
            writer.writerows(new_edges)

        logger.info(f"New edges written to {RETRY_EDGES_FILE}")
        logger.info("To merge with existing edges, run:")
        logger.info(f"  tail -n +2 {RETRY_EDGES_FILE} >> {EDGES_FILE}")
    else:
        logger.warning("No new edges created")


if __name__ == "__main__":
    main()
