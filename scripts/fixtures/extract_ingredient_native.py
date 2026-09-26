"""Reproduce the native ingredient acceptance excerpts from their hash-pinned source files."""

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

import ijson


def sha256(path):
    """Hash a source without loading the ontology graph into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    """Require the recorded input versions and reproduce each expected output byte."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--origin", type=Path, default=Path("tests/resources/ingredient_bundle/native/acceptance-native-origin.json")
    )
    args = parser.parse_args()
    origin = json.loads(args.origin.read_text())
    for name, expected in origin["sources"].items():
        path = args.source_root / name
        if sha256(path) != expected["sha256"]:
            raise ValueError("Source is not the pinned acceptance input: " + name)
    args.output.mkdir(parents=True, exist_ok=False)
    nodes = {}
    for name, expected in origin["sources"].items():
        if not name.endswith("_nodes.tsv"):
            continue
        selected = set(expected["selected_ids"])
        with (args.source_root / name).open(newline="") as stream:
            rows = [
                row for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE) if row["id"] in selected
            ]
        nodes[name.removeprefix("data/transformed/")] = rows
    with (args.source_root / "data/transformed/ontologies/chebi_edges.tsv").open(newline="") as stream:
        pairs = {("CHEBI:17712", "CHEBI:15318"), ("CHEBI:29673", "CHEBI:26580")}
        edges = [
            row
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if (row["subject"], row["object"]) in pairs and row["predicate"] == "biolink:subclass_of"
        ]
    path = args.source_root / "data/raw/chebi.json"
    selected = set(origin["sources"]["data/raw/chebi.json"]["selected_ids"])
    with path.open("rb") as stream:
        raw_nodes = [row for row in ijson.items(stream, "graphs.item.nodes.item") if row["id"] in selected]
    with path.open("rb") as stream:
        raw_edges = [
            row
            for row in ijson.items(stream, "graphs.item.edges.item")
            if row["sub"] in selected and row["obj"] in selected
        ]
    with path.open("rb") as stream:
        meta = next(ijson.items(stream, "graphs.item.meta"))
    with path.open("rb") as stream:
        graph_id = next(ijson.items(stream, "graphs.item.id"))
    authority = {
        "graphs": [
            {
                "id": graph_id,
                "meta": meta,
                "nodes": sorted(raw_nodes, key=lambda row: row["id"]),
                "edges": sorted(raw_edges, key=lambda row: json.dumps(row, sort_keys=True)),
            }
        ]
    }
    for name, value in (
        ("native-nodes.json", nodes),
        ("native-edges.json", edges),
        ("chebi-authority.json", authority),
    ):
        (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    for name in ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml"):
        shutil.copyfile(args.source_root / "data/raw" / name, args.output / name)
    for name, expected in origin["members"].items():
        if sha256(args.output / name) != expected["sha256"]:
            raise ValueError("Regenerated fixture differs: " + name)
    # Verify source stability across extraction as well as the entry-time pin.
    for name, expected in origin["sources"].items():
        if sha256(args.source_root / name) != expected["sha256"]:
            raise ValueError("Source changed during extraction: " + name)
    shutil.copyfile(args.origin, args.output / "acceptance-native-origin.json")
    print("Reproduced all six native fixture members byte for byte.")


if __name__ == "__main__":
    main()
