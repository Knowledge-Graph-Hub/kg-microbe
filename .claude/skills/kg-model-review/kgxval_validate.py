"""
Run monarch-initiative/kgxval's biolink domain/range validation on a KG-Microbe KGX pair.

kgxval (https://github.com/monarch-initiative/kgxval) validates KGX edges against
the Biolink Model with BMT: for every unique (subject-category, object-category,
predicate) signature it flags

  * BAD BIOLINK  — predicate (or edge category) is not a Biolink element
  * BAD SUBJECT  — subject node categories are outside the predicate's domain
  * BAD OBJECT   — object node categories are outside the predicate's range

using BMT's *actual* domain/range descendants — an authoritative complement to
kg_model_review.py's hand-curated DomainRange check.

kgxval requires Python >=3.13 and is not a kg-microbe dependency, so this driver
is meant to run in kgxval's own environment, e.g. via uv:

    uv run --python 3.13 \
        --with 'kgxval @ git+https://github.com/monarch-initiative/kgxval' \
        python kgxval_validate.py <nodes.tsv> <edges.tsv> <out.csv>

Why this wrapper instead of the `ingest_summary` CLI: that CLI expects a
JSONL ingest-directory tree and ships with the biolink sub/obj check disabled
(`ExcelDFFlags(blink_subobj=False)`). kgxval's `Ingest` reads TSV natively, but
its `TSVDictGen` does not split KG-Microbe's pipe-delimited `category` column,
so multi-category nodes (e.g. ``METPO:1001000|biolink:Procedure``) and
non-biolink categories (METPO/…) would produce spurious errors. We therefore
build the node→category map ourselves — splitting on ``|`` and keeping only the
``biolink:`` components — then hand it to kgxval's own validator.
"""

import csv
import sys
from pathlib import Path

from bmt.utils import parse_name
from kgxval.biolink_validation.check_kgx_sub_obj_pred import (
    findSubObjErrorsForIngest,
    validationErrorsToFile,
)
from kgxval.dir.Ingest import Ingest

# KG-Microbe merged edges can exceed the default field-size limit on long
# provenance columns; lift the cap so csv.DictReader never truncates a row.
# sys.maxsize can overflow C long on some platforms — halve until accepted.
_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_limit)
        break
    except OverflowError:
        _limit //= 2


def build_node_category_map(nodes_path: Path) -> dict[str, tuple[str, ...]]:
    """
    Map each node id to its tuple of BMT-parsed biolink categories.

    KG-Microbe stores ``category`` as a pipe-delimited string that may mix
    biolink and non-biolink (METPO, …) CURIEs. We keep only the ``biolink:``
    components so kgxval's domain/range checks run against real Biolink classes.
    A node with no biolink category maps to an empty tuple; kgxval then reports
    its incident edges as BAD SUBJECT / BAD OBJECT (an empty category set can't
    intersect any predicate's domain/range). The summary surfaces these as
    ``(no biolink category)`` so they are visible, not silently dropped — worth
    knowing if a future METPO-only-category node is emitted (none exist today).
    """
    node_to_cat: dict[str, tuple[str, ...]] = {}
    with open(nodes_path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            raw = row.get("category") or ""
            cats = [c for c in raw.split("|") if c.startswith("biolink:")]
            node_to_cat[row["id"]] = tuple(parse_name(c) for c in cats)
    return node_to_cat


def main() -> int:
    """Validate a nodes/edges TSV pair and write a kgxval error CSV."""
    if len(sys.argv) != 4:
        print("usage: kgxval_validate.py <nodes.tsv> <edges.tsv> <out.csv>", file=sys.stderr)
        return 2
    nodes_path, edges_path, out_csv = (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])

    ingest = Ingest("kg-microbe", nodes_path, edges_path, "normalized")
    # Inject our correctly-split category map (bypasses TSVDictGen's no-split
    # behaviour) and tolerate edges whose endpoint is absent from nodes.tsv
    # (return an empty category tuple instead of raising).
    node_to_cat = build_node_category_map(nodes_path)
    ingest.node_to_category = node_to_cat
    ingest.get_node_id_category = lambda node_id: node_to_cat.get(node_id, ())

    errors = findSubObjErrorsForIngest(ingest)
    validationErrorsToFile(errors, out_csv)

    by_type: dict[str, int] = {}
    for e in errors:
        by_type[e.error] = by_type.get(e.error, 0) + 1
    print(f"kgxval: {len(errors)} distinct (predicate,signature) errors across {len(node_to_cat):,} nodes")
    for etype, cnt in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {etype}: {cnt}")
    print(f"wrote {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
