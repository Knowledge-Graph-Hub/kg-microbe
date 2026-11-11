"""
Replay EdgeMech #36 BTO metadata with exact existing authority bytes, 2026-11-10.

Inputs: pinned gap Parquet/manifest and KG-Microbe raw bto.db.gz.
Outputs: production-emitted bounded nodes/audit and hashed component receipt.
This exercises metadata loading/emission, not full PREGO association regeneration.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from kg_microbe.transform_utils.prego import bto_metadata
from kg_microbe.transform_utils.prego.prego import _BTO_CATEGORY, PregoTransform
from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer


def digest(path):
    """Bind exact bounded component inputs and persisted outputs."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def main():
    """Use the identical production metadata path for one canary and the complete BTO cohort."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gap-manifest", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.gap_manifest.read_bytes())
    gaps = args.gap_manifest.parent / "nodes.parquet"
    if digest(gaps) != manifest["nodes_artifact_sha256"]:
        raise ValueError("Node gap artifact hash mismatch")
    selected = sorted((row for row in pq.read_table(gaps).to_pylist() if row["id"].startswith("BTO:")),
                      key=lambda row: (-row["affected_occurrences"], row["id"]))
    if not args.all:
        selected = selected[:1]
    if not selected:
        raise ValueError("No BTO gaps selected")
    args.output.mkdir(parents=True, exist_ok=False)
    producer = PregoTransform(args.raw, args.output, shapes="habitat")
    producer._bto_metadata, producer._bto_version = bto_metadata.load_bto_metadata(producer)
    nodes = producer.output_node_file
    audit = producer.output_dir / bto_metadata.AUDIT_FILE
    with nodes.open("w", newline="") as node_stream, audit.open("w", newline="") as audit_stream:
        writer = tsv_writer(node_stream)
        writer.writerow(producer.node_header)
        producer._bto_audit_writer = tsv_dict_writer(audit_stream, fieldnames=bto_metadata.AUDIT_COLUMNS)
        producer._bto_audit_writer.writeheader()
        for row in selected:
            producer._emit_node(writer, row["id"], _BTO_CATEGORY)
    producer._bto_audit_writer = None
    with nodes.open() as stream:
        actual = list(csv.DictReader(stream, delimiter="\t"))
    if {row["id"] for row in actual} != {row["id"] for row in selected}:
        raise ValueError("Persisted node IDs differ from selected real gaps")
    authority = producer.consumed_input_snapshots[bto_metadata.ROLE]
    if digest(Path(authority["path"])) != authority["sha256"]:
        raise ValueError("BTO authority changed during replay")
    receipt = {
        "nodes": len(actual), "labelled": sum(bool(row["name"]) for row in actual),
        "retired": sum(row["deprecated"] == "True" for row in actual),
        "unresolved_ids": [row["id"] for row in actual if not row["name"]],
        "authority": authority, "authority_version_iri": producer._bto_version,
        "gap_manifest_sha256": digest(args.gap_manifest), "gap_nodes_sha256": digest(gaps),
        "nodes_sha256": digest(nodes), "audit_sha256": digest(audit),
        "limitations": ["Component replay of real IDs and existing SemSQL bytes, not a full PREGO producer run.",
                        "The selected BTO database declares release 2021-10-26; no current-release claim.",
                        "No identifier, category, association or KG admission was changed by this replay."],
    }
    path = args.output / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(path), "nodes": receipt["nodes"], "labelled": receipt["labelled"],
                      "receipt_sha256": digest(path)}))


if __name__ == "__main__":
    main()
