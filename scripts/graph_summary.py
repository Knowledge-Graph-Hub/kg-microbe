#!/usr/bin/env python3
"""Summarize merged KG TSVs without extracting the standard release archive."""

import argparse
import tarfile
from collections import Counter
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path
from typing import Iterator, TextIO

NODE_PREFIXES = ("NCBITaxon:", "CHEBI:", "PubChem:", "KEGG:", "CAS-RN:", "ingredient:", "solution:", "medium:")
EDGE_PAIRS = (
    ("taxon -> medium", ("NCBITaxon:", "medium:")),
    ("medium -> ingredient", ("medium:", "ingredient:")),
    ("medium -> solution", ("medium:", "solution:")),
    ("solution -> CHEBI", ("solution:", "CHEBI:")),
    ("ingredient -> solution", ("ingredient:", "solution:")),
    ("taxon -> CHEBI", ("NCBITaxon:", "CHEBI:")),
    ("taxon -> GO", ("NCBITaxon:", "GO:")),
)
EDGE_TRAITS = (
    "oxygen:",
    "salinity:",
    "pH:",
    "temperature:",
    "pathways:",
    "gram_stain:",
    "isolation_source:",
    "carbon_substrate:",
    "cell_shape:",
    "pathogen:",
)


@contextmanager
def graph_stream(merged_dir: Path, kind: str) -> Iterator[TextIO]:
    """Yield a node or edge stream from loose TSVs or the standard archive."""
    filename = f"merged-kg_{kind}.tsv"
    loose_path = merged_dir / filename
    if loose_path.is_file():
        with loose_path.open(encoding="utf-8", errors="replace") as stream:
            yield stream
        return

    archive_path = merged_dir / "merged-kg.tar.gz"
    if not archive_path.is_file():
        raise FileNotFoundError(f"Expected {loose_path} or {archive_path}")
    with tarfile.open(archive_path, "r:gz") as archive:
        member = next((item for item in archive.getmembers() if Path(item.name).name == filename), None)
        if member is None:
            raise FileNotFoundError(f"{filename} is not present in {archive_path}")
        raw_stream = archive.extractfile(member)
        if raw_stream is None:
            raise OSError(f"Could not read {member.name} from {archive_path}")
        with TextIOWrapper(raw_stream, encoding="utf-8", errors="replace") as stream:
            yield stream


def summarize(merged_dir: Path) -> str:
    """Return the human-readable graph summary."""
    node_counts: Counter[str] = Counter()
    node_total = 0
    with graph_stream(merged_dir, "nodes") as nodes:
        next(nodes, None)
        for line in nodes:
            node_total += 1
            identifier = line.split("\t", 1)[0]
            for prefix in NODE_PREFIXES:
                if identifier.startswith(prefix):
                    node_counts[prefix] += 1

    edge_counts: Counter[str] = Counter()
    edge_total = 0
    with graph_stream(merged_dir, "edges") as edges:
        next(edges, None)
        for line in edges:
            edge_total += 1
            for label, tokens in EDGE_PAIRS:
                if all(token in line for token in tokens):
                    edge_counts[label] += 1
            for trait in EDGE_TRAITS:
                if trait in line:
                    edge_counts[f"taxon -> {trait[:-1]}"] += 1

    lines = [f"NODES\t{node_total}"]
    lines.extend(f"{prefix}\t{node_counts[prefix]}" for prefix in NODE_PREFIXES)
    lines.append(f"EDGES\t{edge_total}")
    lines.extend(f"{label}\t{edge_counts[label]}" for label, _ in EDGE_PAIRS)
    lines.extend(f"taxon -> {trait[:-1]}\t{edge_counts[f'taxon -> {trait[:-1]}']}" for trait in EDGE_TRAITS)
    return "\n".join(lines)


def main() -> None:
    """Run the merged graph summary command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("merged_dir", nargs="?", type=Path, default=Path("data/merged"))
    args = parser.parse_args()
    print(summarize(args.merged_dir))


if __name__ == "__main__":
    main()
