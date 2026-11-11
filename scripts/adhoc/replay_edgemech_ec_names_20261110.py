"""
Replay EdgeMech #36/#1674 EC names through current public merge (2026-11-10).

Inputs: existing KG-Microbe ontology/BacDive node outputs and local Biolink schema.
Outputs: bounded extracted inputs, diagnostic merge archive and SHA-bound receipt.
This is merge acceptance only; it does not claim full producer/archive freshness.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import yaml

IDS = (
    "EC:3.4.11.6", "EC:4.1.1.5", "EC:3.1.1.32", "EC:4.4.1.1",
    "EC:1.7.5.1", "EC:3.5.1.19", "EC:1.7.2.1", "EC:1.7.2.4",
)


def digest(path):
    """Hash exact input or output bytes without loading graph-scale files."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def select(path, identifiers):
    """Keep exact declared rows, requiring one declaration per selected identifier."""
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = reader.fieldnames
        rows = [row for row in reader if row["id"] in identifiers]
    if len(rows) != len(identifiers) or {row["id"] for row in rows} != identifiers:
        raise ValueError(f"Missing or duplicate selected declarations in {path}")
    return header, rows


def main():
    """Run identical canary/batch paths with one or eight real node pairs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, choices=(1, 8), default=1)
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    os.environ["KG_MICROBE_BIOLINK_MODEL"] = str(source / "data/raw/biolink-model.yaml")
    os.environ["KG_MICROBE_BIOLINK_PREDICATE_MAP"] = str(source / "data/raw/predicate_mapping.yaml")
    from kg_microbe.merge_utils.merge_kg import load_and_merge
    from kg_microbe.utils.graph_schema import CANONICAL_EDGE_HEADER

    identifiers = set(IDS[:args.count])
    output.mkdir(parents=True, exist_ok=False)
    sources, inputs, expected = {}, [], {}
    for key, relative in (("blank_bacdive", "bacdive/nodes.tsv"), ("named_ec", "ontologies/ec_nodes.tsv")):
        original = source / "data/transformed" / relative
        header, rows = select(original, identifiers)
        for row in rows:
            if key == "blank_bacdive" and row["name"]:
                raise ValueError("Expected actual blank BacDive contribution")
            if key == "named_ec":
                if not row["name"]:
                    raise ValueError("Expected actual nonblank ontology contribution")
                expected[row["id"]] = row["name"]
        nodes, edges = output / f"{key}_nodes.tsv", output / f"{key}_edges.tsv"
        with nodes.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE,
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        edges.write_text("\t".join(CANONICAL_EDGE_HEADER) + "\n")
        sources[key] = {"input": {"format": "tsv", "filename": [str(nodes), str(edges)]}}
        inputs.append({"path": str(original), "sha256": digest(original),
                       "selected_path": str(nodes), "selected_sha256": digest(nodes)})
    config = output / "merge.yaml"
    config.write_text(yaml.safe_dump({
        "configuration": {"output_directory": str(output / "published"), "allow_unfinalized_sources": True},
        "merged_graph": {"source": sources, "destination": {
            "tsv": {"format": "tsv", "filename": "merged", "compression": "tar.gz"}}},
    }, sort_keys=False))
    load_and_merge(str(config))
    archive_path = output / "published/merged.tar.gz"
    with tarfile.open(archive_path) as archive:
        raw = archive.extractfile("merged_nodes.tsv").read()
        manifest = json.load(archive.extractfile("manifest.json"))
    if hashlib.sha256(raw).hexdigest() != manifest["members"]["merged_nodes.tsv"]["sha256"]:
        raise ValueError("Persisted archive node bytes differ from embedded manifest")
    actual = {row["id"]: row["name"] for row in csv.DictReader(
        io.StringIO(raw.decode()), delimiter="\t", quoting=csv.QUOTE_NONE)}
    if actual != expected:
        raise ValueError(f"Nonblank authoritative names lost: {actual!r} != {expected!r}")
    receipt = {"count": len(actual), "names": actual, "inputs": inputs,
               "archive_sha256": digest(archive_path), "config_sha256": digest(config),
               "limitation": "Diagnostic bounded node-only merge; source freshness checks opted out. "
                             "No graph assertions or full release acceptance are claimed."}
    receipt_path = output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(receipt_path), "count": len(actual), "receipt_sha256": digest(receipt_path)}))


if __name__ == "__main__":
    main()
