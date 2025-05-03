#!/usr/bin/env python3

import csv
import urllib.parse
from pathlib import Path
from loguru import logger
from kgx.cli.cli_utils import transform as kgx_transform

# Directory and file definitions
DATA_DIR      = Path("../data/merged/20250222")
ORIG_NODES    = DATA_DIR / "merged-kg_nodes.tsv"
ORIG_EDGES    = DATA_DIR / "merged-kg_edges.tsv"
# Use hyphens so KGX auto-detection recognizes '-nodes.tsv' and '-edges.tsv'
CLEAN_NODES   = DATA_DIR / "merged-kg-safe-nodes.tsv"
CLEAN_EDGES   = DATA_DIR / "merged-kg-safe-edges.tsv"
OUTPUT_FILE   = "kg-microbe.nt.gz"


def clean_nodes(src: Path, dest: Path):
    """
    Percent-encode the suffix of each CURIE in the 'id' column to make valid IRIs.
    """
    logger.info(f"Cleaning nodes TSV: {src} -> {dest}")
    with src.open("r", encoding="utf-8") as fin, dest.open("w", encoding="utf-8") as fout:
        header = fin.readline()
        fout.write(header)
        cols = header.rstrip("\n").split("\t")
        try:
            id_idx = cols.index("id")
        except ValueError:
            logger.error("'id' column not found in nodes TSV header")
            raise
        for line in fin:
            parts = line.rstrip("\n").split("\t")
            original = parts[id_idx]
            if ":" in original:
                prefix, suffix = original.rsplit(":", 1)
                parts[id_idx] = f"{prefix}:{urllib.parse.quote(suffix, safe='-._~')}"
            else:
                parts[id_idx] = urllib.parse.quote(original, safe='-._~')
            fout.write("\t".join(parts) + "\n")


def clean_edges(src: Path, dest: Path):
    """
    Percent-encode 'subject' and 'object' CURIEs to make valid IRIs.
    """
    logger.info(f"Cleaning edges TSV: {src} -> {dest}")
    with src.open("r", encoding="utf-8") as fin, dest.open("w", encoding="utf-8") as fout:
        header = fin.readline()
        fout.write(header)
        cols = header.rstrip("\n").split("\t")
        try:
            subj_idx = cols.index("subject")
            obj_idx  = cols.index("object")
        except ValueError as e:
            logger.error(f"Missing expected column: {e}")
            raise
        for line in fin:
            parts = line.rstrip("\n").split("\t")
            parts[subj_idx] = urllib.parse.quote(parts[subj_idx], safe=":-._~")
            parts[obj_idx]  = urllib.parse.quote(parts[obj_idx],  safe=":-._~")
            fout.write("\t".join(parts) + "\n")


def count_rows(path: Path) -> int:
    """Return number of data rows (excluding header) in TSV."""
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def main():
    # 1) Clean source TSVs
    clean_nodes(ORIG_NODES, CLEAN_NODES)
    clean_edges(ORIG_EDGES, CLEAN_EDGES)

    # 2) Log row counts for verification
    logger.info(f"{CLEAN_NODES} has {count_rows(CLEAN_NODES)} rows")
    logger.info(f"{CLEAN_EDGES} has {count_rows(CLEAN_EDGES)} rows")

    # 3) Run KGX transform on cleaned TSVs
    inputs = [str(CLEAN_NODES), str(CLEAN_EDGES)]
    logger.info(f"Running KGX transform on: {inputs}")
    kgx_transform(
        inputs=inputs,
        input_format="tsv",
        stream=True,
        output=OUTPUT_FILE,
        output_format="nt",
        output_compression="gz",
    )
    logger.info(f"RDF export complete: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

