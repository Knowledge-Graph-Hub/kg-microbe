"""
Audit source-owned LPSN publication labels for KG-Microbe #1834/#1837/#1838, 2026-11-10.

Inputs: cached LPSN API JSON records and SHA-pinned incomplete-node Parquet.
Outputs: source hash ledger, emitted nodes/edges and measured coverage receipt.
Default one actual record; --all follows a verified persisted canary. Offline:
uses production run/_fetch with a canned offline client, not a full graph merge.
"""

import argparse
import csv
import hashlib
import inspect
import json
from pathlib import Path

import pyarrow.parquet as pq

from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform
from kg_microbe.transform_utils.lpsn_api.native_inputs import AUDIT_FILE
from kg_microbe.utils.atomic_io import atomic_write


class OfflineMissingClient:
    """Represent API cache misses without authentication or network calls."""

    def search(self, **kwargs):
        """Accept a production record request without contacting LPSN."""

    def retrieve(self):
        """Return a canned empty API result for records absent from the local cache."""
        return iter(())


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
    if args.cache.name != "api_cache" or args.cache.parent.name != "lpsn":
        raise ValueError("Expected the production raw/lpsn/api_cache directory")
    args.output.mkdir(parents=True, exist_ok=False)
    selection = args.output / "selected_gss_nodes.tsv"
    with atomic_write(selection, newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["id", "category"])
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 1024**2:
                raise ValueError("Expected bounded regular cached API record")
            writer.writerow([f"lpsn:{path.stem}", "biolink:OrganismTaxon"])
    transform = LPSNAPITransform(
        input_dir=args.cache.parent.parent,
        output_dir=args.output,
        client=OfflineMissingClient(),
        page_fetch=lambda record_no: None,
    )
    transform.run(data_file=selection)
    transform.verify_consumed_inputs()
    contract = transform.producer_native_inputs
    ledger = [{"record_no": record_no, **item} for record_no, item in sorted(contract["records"].items())]
    nodes_path, edges_path = transform.output_node_file, transform.output_edge_file
    with nodes_path.open(newline="") as handle:
        publication_nodes = [
            row for row in csv.DictReader(handle, delimiter="\t") if row["category"] == "biolink:Publication"
        ]
    identifiers = {row["id"] for row in publication_nodes}
    if len(identifiers) != len(publication_nodes):
        raise ValueError("Publication IDs multiplied in persisted output")
    labeled = {row["id"] for row in publication_nodes if row["name"].strip()}
    conflicts = {row["id"] for row in publication_nodes if "Conflicting LPSN citation texts" in row["description"]}
    transform.verify_consumed_inputs()
    if digest(args.missing_nodes) != args.missing_sha256:
        raise ValueError("Incomplete-node artifact changed during audit")
    with atomic_write(args.output / "source-records.json") as handle:
        json.dump(ledger, handle, sort_keys=True, indent=2)
        handle.write("\n")
    receipt = {
        "producer_module": inspect.getfile(LPSNAPITransform),
        "cached_records_selected": len(paths),
        "consumed_api_records": sum(item["state"] == "present" for item in ledger),
        "absent_selected_api_records": sum(item["state"] == "absent" for item in ledger),
        "producer_stats": dict(transform._stats),
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
        "producer_record_audit_sha256": digest(transform.output_dir / AUDIT_FILE),
        "gss_selection_sha256": digest(selection),
        "nodes_sha256": digest(nodes_path),
        "edges_sha256": digest(edges_path),
        "limitations": [
            "Citation text is a source-owned display label, not an independently verified paper title.",
            "Different citation strings for one identifier remain unresolved, including formatting differences.",
            "IMG genome IDs and INSDC accessions have no owner-supplied record titles in these inputs; "
            "no names are invented.",
            "This executes production run/_fetch using cached API records and canned empty responses for misses; "
            "it does not contact LPSN or rebuild/merge the full graph.",
            "The record contract covers GSS selection and API cache bytes/locators; pre-existing web fallback "
            "names are outside this new binding. API misses are local cache absence, not proof of a remote API answer.",
        ],
    }
    with atomic_write(args.output / "receipt.json") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
