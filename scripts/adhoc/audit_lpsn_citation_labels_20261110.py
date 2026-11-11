"""
Audit source-owned LPSN publication labels for KG-Microbe #1834 / EdgeMech #36, 2026-11-10.

Inputs: cached LPSN API JSON records and SHA-pinned incomplete-node Parquet.
Outputs: source hash ledger, emitted nodes/edges and measured coverage receipt.
Default one actual record; --all follows a verified persisted canary. Offline:
uses production _emit/_emit_publication_nodes, not fetching or a full graph merge.
"""

import argparse
import csv
import hashlib
import inspect
import json
import os
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.tsv_io import tsv_writer


def digest(path):
    """Hash a bounded artifact or stream a larger output without loading it whole."""
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    """Emit and independently read back one canary or the complete local cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--missing-nodes", type=Path, required=True)
    parser.add_argument("--missing-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", default="784756")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if digest(args.missing_nodes) != args.missing_sha256:
        raise ValueError("Incomplete-node artifact pin mismatch")
    missing = set(pq.read_table(args.missing_nodes, columns=["id"])["id"].to_pylist())
    paths = (
        sorted(path for path in args.cache.glob("*.json") if path.stem.isdigit())
        if args.all
        else [args.cache / f"{args.record}.json"]
    )
    if not paths:
        raise ValueError("No cached source records selected")
    args.output.mkdir(parents=True, exist_ok=False)
    transform = LPSNAPITransform(input_dir=args.cache, output_dir=args.output, client=object())
    ledger, skipped = [], Counter()
    nodes_path, edges_path = args.output / "nodes.tsv", args.output / "edges.tsv"
    with atomic_write(nodes_path, newline="") as nodes_handle, atomic_write(edges_path, newline="") as edges_handle:
        nodes, edges = tsv_writer(nodes_handle), tsv_writer(edges_handle)
        nodes.writerow(transform.node_header)
        edges.writerow(transform.edge_header)
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 1024**2:
                raise ValueError("Expected bounded regular cached API record")
            raw = path.read_bytes()
            ledger.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
            record = json.loads(raw)
            if not isinstance(record, dict) or str(record.get("id")) != path.stem:
                skipped["missing_or_mismatched_record_identity"] += 1
                continue
            transform._emit(path.stem, record, nodes, edges)
        transform._emit_publication_nodes(nodes)
        for handle in (nodes_handle, edges_handle):
            handle.flush()
            os.fsync(handle.fileno())
    with nodes_path.open(newline="") as handle:
        publication_nodes = [
            row for row in csv.DictReader(handle, delimiter="\t") if row["category"] == "biolink:Publication"
        ]
    identifiers = {row["id"] for row in publication_nodes}
    if len(identifiers) != len(publication_nodes):
        raise ValueError("Publication IDs multiplied in persisted output")
    labeled = {row["id"] for row in publication_nodes if row["name"].strip()}
    conflicts = {row["id"] for row in publication_nodes if "Conflicting LPSN citation texts" in row["description"]}
    for entry in ledger:
        if digest(Path(entry["path"])) != entry["sha256"]:
            raise ValueError("Cached source changed during audit")
    if digest(args.missing_nodes) != args.missing_sha256:
        raise ValueError("Incomplete-node artifact changed during audit")
    with atomic_write(args.output / "source-records.json") as handle:
        json.dump(ledger, handle, sort_keys=True, indent=2)
        handle.write("\n")
    receipt = {
        "producer_module": inspect.getfile(LPSNAPITransform),
        "cached_records_selected": len(paths),
        "skipped_records": dict(skipped),
        "unique_publication_nodes": len(identifiers),
        "unique_source_citation_labels": len(labeled),
        "conflicting_citation_nodes": len(conflicts),
        "unlabeled_without_citation": len(identifiers - labeled - conflicts),
        "missing_node_intersection": len(identifiers & missing),
        "missing_nodes_with_source_citation_label": len(labeled & missing),
        "missing_nodes_with_conflicting_citations": len(conflicts & missing),
        "by_namespace": {
            prefix: {
                "missing_nodes": len({key for key in missing if key.startswith(prefix)}),
                "source_citation_labels": len({key for key in labeled & missing if key.startswith(prefix)}),
            }
            for prefix in ("doi:", "PMID:", "INSDC:", "IMG:")
        },
        "missing_nodes_sha256": args.missing_sha256,
        "source_record_ledger_sha256": digest(args.output / "source-records.json"),
        "nodes_sha256": digest(nodes_path),
        "edges_sha256": digest(edges_path),
        "limitations": [
            "Citation text is a source-owned display label, not an independently verified paper title.",
            "Different citation strings for one identifier remain unresolved, including formatting differences.",
            "IMG genome IDs and INSDC accessions have no owner-supplied record titles in these inputs; "
            "no names are invented.",
            "This executes the production record/node emitters; it does not rebuild or merge the full graph.",
        ],
    }
    with atomic_write(args.output / "receipt.json") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
