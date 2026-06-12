r"""
Dump unmapped MediaDive ingredients for manual / MediaIngredientMech curation.

MediaDive ingredients that cannot be resolved to ChEBI / KEGG / PubChem / CAS
fall back to the `mediadive.ingredient:N` CURIE in the transformed output.
This script collects those rows from `data/transformed/mediadive/nodes.tsv`,
retries the lookup with `fuzzy_hydrate=True` (recovering anhydrous matches for
`MgCl2 x 6 H2O`-style names), and writes the remaining still-unmapped rows to
a TSV of curation-candidate rows so curators can fill the `ontology_id` /
`mapping_status` columns and feed the result into MediaIngredientMech; the
resulting mappings return to kg-microbe via
`mappings/ingredient_mappings.sssom.tsv`.

Output columns:
    id                MediaDive ingredient CURIE (`mediadive.ingredient:N`)
    preferred_term    MediaDive display name
    identifier        empty (to be filled by curator with ChEBI/FOODON/ENVO ID)
    mapping_status    UNMAPPED
    ontology_id       empty
    ontology_source   empty
    mapping_quality   empty
    occurrences       count of recipes referencing this ingredient (1 if not computable)
    parent_ingredient empty
    variant_type      empty

Usage:
    poetry run python scripts/dump_unmapped_mediadive_ingredients.py \\
        [--nodes data/transformed/mediadive/nodes.tsv] \\
        [--output mappings/mediadive_unmapped_ingredients_to_curate.tsv]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

MEDIADIVE_INGREDIENT_PREFIX = "mediadive.ingredient:"

MIM_COLUMNS = [
    "id",
    "preferred_term",
    "identifier",
    "mapping_status",
    "ontology_id",
    "ontology_source",
    "mapping_quality",
    "occurrences",
    "parent_ingredient",
    "variant_type",
]


def iter_unmapped_rows(nodes_path: Path):
    """Yield (id, name) tuples for mediadive.ingredient:* nodes in the transformed file."""
    with nodes_path.open("r", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            node_id = row.get("id") or ""
            if not node_id.startswith(MEDIADIVE_INGREDIENT_PREFIX):
                continue
            yield node_id, (row.get("name") or "").strip()


def main():
    """Compute and write still-unmapped MediaDive ingredients after fuzzy retry."""
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--nodes",
        type=Path,
        default=repo_root / "data" / "transformed" / "mediadive" / "nodes.tsv",
        help="Path to transformed mediadive nodes.tsv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "mappings" / "mediadive_unmapped_ingredients_to_curate.tsv",
        help="Output TSV (MIM-compatible schema).",
    )
    args = parser.parse_args()

    if not args.nodes.exists():
        raise SystemExit(f"nodes file not found: {args.nodes}")

    loader = ChemicalMappingLoader()

    total = 0
    recovered_by_fuzzy = 0
    still_unmapped_rows = []
    for node_id, name in iter_unmapped_rows(args.nodes):
        total += 1
        if not name:
            continue
        # Retry with fuzzy_hydrate=True — this is the same widening mediadive.py
        # now applies at transform time. If it resolves here, treat as recoverable
        # on the next transform run and skip the curation dump.
        if loader.find_chebi_by_name(name, fuzzy_hydrate=True):
            recovered_by_fuzzy += 1
            continue
        still_unmapped_rows.append((node_id, name))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(MIM_COLUMNS)
        for node_id, name in sorted(still_unmapped_rows, key=lambda r: r[1].lower()):
            writer.writerow([node_id, name, "", "UNMAPPED", "", "", "", 1, "", ""])

    print(f"Scanned {total} mediadive.ingredient:* nodes in {args.nodes}")
    print(
        f"  Recoverable via fuzzy_hydrate (will self-heal on next transform): {recovered_by_fuzzy}"
    )
    print(f"  Still unmapped (written to {args.output}): {len(still_unmapped_rows)}")


if __name__ == "__main__":
    main()
