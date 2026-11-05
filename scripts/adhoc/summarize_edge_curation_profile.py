#!/usr/bin/env python3
"""
Summarize the 2026-11-03 edge-curation planning profile (no issue yet).

Input: JSON from profile_edge_curation_snapshot.py. Output: JSON sizing estimates
and measured field/source percentages. Estimates are explicitly hypothetical.
"""

import argparse
import json
from pathlib import Path


def main():
    """Calculate sizing scenarios and field coverage from a verified profile."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    members = profile["members"]
    edges = members["merged-kg_edges.tsv"]
    nodes = members["merged-kg_nodes.tsv"]
    if not all(member["matches_manifest"] for member in members.values()):
        raise ValueError("Summary requires complete manifest-verified scans")
    count = edges["rows"]
    sources = edges["counts"]["primary_knowledge_source"]
    result = {
        "edges": count,
        "nodes": nodes["rows"],
        "source_field_values": len(sources),
        "predicate_field_values": len(edges["counts"]["predicate"]),
        "combined_tsv_bytes": edges["file_bytes"] + nodes["file_bytes"],
        "sources": {
            source: {"rows": number, "percent": round(100 * number / count, 3)} for source, number in sources.items()
        },
        "nonempty_field_percent": {
            field: round(100 * number / count, 3) for field, number in edges["nonempty_fields"].items()
        },
        "predicate_namespace_percent": {
            field: round(100 * number / count, 3) for field, number in edges["counts"]["predicate_namespace"].items()
        },
        "bacdive_and_two_metatraits_percent": round(
            100
            * sum(sources[source] for source in ("infores:bacdive", "infores:metatraits", "infores:gtdb-metatraits"))
            / count,
            3,
        ),
        "hypothetical_bytes_at_1000_per_edge_record": count * 1000,
        "hypothetical_bytes_at_5000_per_edge_html_page": count * 5000,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
