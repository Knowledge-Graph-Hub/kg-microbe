r"""Dump MicrobeDecoder unmapped labels as a tracked curation queue.

Reads the per-run ``data/transformed/microbedecoder/unmapped_labels.tsv``
that ``MicrobeDecoderTransform`` emits and writes a *tracked* curation
asset at ``mappings/microbedecoder_unmapped_labels_to_curate.tsv``.

The pattern mirrors ``dump_unmapped_mediadive_ingredients.py``:

- The per-run report is gitignored under ``data/transformed/`` and
  regenerates on every ``kg transform -s microbedecoder`` run.
- The tracked curation queue lives under ``mappings/`` and gets
  refreshed by this script when a curator is ready to work through a
  new batch. Downstream loaders (METPO submission, chemical mappings,
  bacdive trait vocab) pick up the resulting mappings; the next
  transform run then shrinks the report as those labels resolve.

The queue is scoped and sorted so curators can grab the top N rows and
work them in one sitting. Rows with fewer than ``--min-occurrences``
observations are dropped (default 10 — filters the long tail of
per-strain literal values). Placeholder prefix filtering (``--prefix``)
splits the workload: pathway labels belong in a METPO PR, compound
labels in ``mappings/canonical/chemical_mappings.tsv``, trait labels in
``kgmicrobe.trait`` yaml or a METPO proposal.

Output columns (a superset of the input, so a curator's edits are
preservable in-place):

    placeholder_curie   kgmicrobe.{pathway,compound,trait}:<slug> from the run
    category            biolink category the placeholder carries
    label               raw source label
    source_columns      pipe-set of source columns the label appeared under
    occurrences         edges this placeholder anchors (last run)
    target_curie        (empty) curator fills — CHEBI / METPO / GO / EC
    target_label        (empty) curator fills — human-readable target name
    mapping_status      UNMAPPED at emit time; curator sets MAPPED / PROPOSED / SKIP
    curator_notes       (empty) free-text

Usage::

    poetry run python scripts/dump_unmapped_microbedecoder_labels.py
    poetry run python scripts/dump_unmapped_microbedecoder_labels.py --prefix pathway --min-occurrences 100
    poetry run python scripts/dump_unmapped_microbedecoder_labels.py --input <path> --output <path>
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable, List, Optional

# Columns of the output curation TSV. Order deliberately preserves the
# input columns first (so the curator sees the raw report shape) and
# adds the four curation columns at the end.
CURATION_COLUMNS: List[str] = [
    "placeholder_curie",
    "category",
    "label",
    "source_columns",
    "occurrences",
    "target_curie",
    "target_label",
    "mapping_status",
    "curator_notes",
]

# Filter placeholder-prefix families the transform emits. The transform
# routes unmatched labels into these three by facet — see the
# add-transform skill's placeholder-prefix table.
_PLACEHOLDER_FACETS = {
    "pathway": "kgmicrobe.pathway:",
    "compound": "kgmicrobe.compound:",
    "trait": "kgmicrobe.trait:",
}


def _iter_report_rows(input_path: Path) -> Iterable[dict]:
    """Yield rows from the per-run unmapped_labels.tsv report."""
    with input_path.open("r", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        yield from reader


def _filter_and_sort(
    rows: Iterable[dict],
    prefix_filter: Optional[str],
    min_occurrences: int,
) -> List[dict]:
    """Apply the prefix and min-occurrences filters; sort descending by count."""
    filtered: List[dict] = []
    prefix_string = _PLACEHOLDER_FACETS.get(prefix_filter) if prefix_filter else None
    for row in rows:
        curie = row.get("placeholder_curie", "")
        if prefix_string is not None and not curie.startswith(prefix_string):
            continue
        try:
            count = int(row.get("occurrences", "0") or 0)
        except ValueError:
            count = 0
        if count < min_occurrences:
            continue
        filtered.append({**row, "occurrences": count})
    filtered.sort(key=lambda r: (-int(r["occurrences"]), r["placeholder_curie"]))
    return filtered


def _write_curation_queue(rows: List[dict], output_path: Path) -> None:
    """Write the filtered rows plus empty curator columns."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CURATION_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "placeholder_curie": row.get("placeholder_curie", ""),
                    "category": row.get("category", ""),
                    "label": row.get("label", ""),
                    "source_columns": row.get("source_columns", ""),
                    "occurrences": row["occurrences"],
                    "target_curie": "",
                    "target_label": "",
                    "mapping_status": "UNMAPPED",
                    "curator_notes": "",
                }
            )


def main() -> None:
    """Parse args and dump the filtered / sorted curation queue."""
    repo_root = Path(__file__).resolve().parent.parent
    default_input = repo_root / "data" / "transformed" / "microbedecoder" / "unmapped_labels.tsv"
    default_output = repo_root / "mappings" / "microbedecoder_unmapped_labels_to_curate.tsv"

    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help=f"Path to unmapped_labels.tsv (default: {default_input}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Path to write the curation queue TSV (default: {default_output}).",
    )
    parser.add_argument(
        "--prefix",
        choices=sorted(_PLACEHOLDER_FACETS),
        default=None,
        help=(
            "Restrict to one placeholder facet (pathway / compound / trait). "
            "Default: emit all three."
        ),
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=10,
        help=(
            "Drop labels with fewer than this many occurrences in the last "
            "run — filters the long tail of per-strain literals. Default: 10. "
            "Set 0 to keep everything."
        ),
    )
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(
            f"[dump-unmapped-microbedecoder] {args.input} not found. "
            "Run `poetry run kg transform -s microbedecoder` first — "
            "the transform emits the report."
        )

    rows = _filter_and_sort(
        _iter_report_rows(args.input),
        prefix_filter=args.prefix,
        min_occurrences=args.min_occurrences,
    )
    _write_curation_queue(rows, args.output)
    print(
        f"[dump-unmapped-microbedecoder] wrote {len(rows):,} curation rows to {args.output} "
        f"(prefix={args.prefix or 'all'}, min_occurrences={args.min_occurrences})"
    )


if __name__ == "__main__":
    main()
