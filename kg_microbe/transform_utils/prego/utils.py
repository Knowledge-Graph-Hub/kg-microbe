"""
Helpers for the PREGO transform.

Keeps ``prego.py`` focused on row → edge emission. Everything here is a pure
function that :func:`prego.PregoTransform._process_row` can call without
touching the transform's own state.

The JensenLab tagger convention is documented in
``docs/PREGO_INGEST_PLAN.md`` §Phase 3. The nine-column ``database_pairs.tsv``
schema and the integer entity-type codes live in the constants below; the
canonical-direction filter (:func:`classify_row`) implements the dedup step
described in the plan's §Phase 6a (every unique association appears twice in
the raw archives as ``(X, Y)`` AND as ``(Y, X)`` — the filter keeps one
canonical direction per row shape and drops the inverse in O(1) memory).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

# ---------------------------------------------------------------------------
# JensenLab tagger entity type codes. Positive integers are NCBI taxonomy IDs
# for species-specific proteins; negative integers are the standardized
# vocabularies. Only the ones PREGO uses in practice are listed.
# ---------------------------------------------------------------------------
PREGO_TYPE_NCBITAXON = -2
PREGO_TYPE_GO_BP = -21  # biological_process
PREGO_TYPE_GO_CC = -22  # cellular_component
PREGO_TYPE_GO_MF = -23  # molecular_function
PREGO_TYPE_BTO = -25  # BTO tissues
PREGO_TYPE_DOID = -26  # DOID diseases
PREGO_TYPE_ENVO = -27  # ENVO environments

# All three GO namespaces route to the same biolink predicate.
_GO_TYPES = frozenset({PREGO_TYPE_GO_BP, PREGO_TYPE_GO_CC, PREGO_TYPE_GO_MF})

# Nine-column schema of ``database_pairs.tsv`` (canary-verified 2026-08-04).
DATABASE_PAIRS_COLUMNS: Tuple[str, ...] = (
    "entity1_type",
    "entity1_id",
    "entity2_type",
    "entity2_id",
    "source",
    "channel",
    "score",
    "direct_flag",
    "evidence_url",
)
DATABASE_PAIRS_NCOL = len(DATABASE_PAIRS_COLUMNS)


# ---------------------------------------------------------------------------
# Row classification.
# ---------------------------------------------------------------------------

# Sentinel outcomes for :func:`classify_row`. Kept as short strings so the
# unmapped-associations report reads clearly for a curator scanning it.
KEEP_TAXON_TO_GO = "taxon_to_go"
KEEP_ENVO_TO_TAXON = "envo_to_taxon"
KEEP_TAXON_TO_DOID = "taxon_to_doid"
DROP_INVERSE_TAXON_TO_GO = "inverse_go_to_taxon"
DROP_INVERSE_ENVO_TO_TAXON = "inverse_taxon_to_envo"
DROP_BTO_DEFERRED_V2 = "bto_deferred_v2"
DROP_TAXON_TAXON_HOST = "taxon_taxon_host"
DROP_UNKNOWN_SHAPE = "unknown_shape"


def classify_row(entity1_type: int, entity2_type: int) -> str:
    """
    Return a short outcome tag for one raw PREGO row.

    Callers use the tag either to route the row to :func:`build_edge` (any
    ``KEEP_*`` tag) or to increment the unmapped-associations report bucket
    (any ``DROP_*`` tag). See the module docstring for the canonical-direction
    dedup rationale.
    """
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type in _GO_TYPES:
        return KEEP_TAXON_TO_GO
    if entity1_type == PREGO_TYPE_ENVO and entity2_type == PREGO_TYPE_NCBITAXON:
        return KEEP_ENVO_TO_TAXON
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type == PREGO_TYPE_DOID:
        return KEEP_TAXON_TO_DOID
    # Inverses of the three canonical directions — drop, don't re-emit.
    if entity1_type in _GO_TYPES and entity2_type == PREGO_TYPE_NCBITAXON:
        return DROP_INVERSE_TAXON_TO_GO
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type == PREGO_TYPE_ENVO:
        return DROP_INVERSE_ENVO_TO_TAXON
    # BTO deferred per v1 scope (see docs/PREGO_INGEST_PLAN.md §Explicitly out-of-scope).
    if entity2_type == PREGO_TYPE_BTO or entity1_type == PREGO_TYPE_BTO:
        return DROP_BTO_DEFERRED_V2
    # Taxon-taxon host / co-occurrence rows (e.g. → NCBITaxon:9606 human).
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type == PREGO_TYPE_NCBITAXON:
        return DROP_TAXON_TAXON_HOST
    return DROP_UNKNOWN_SHAPE


# ---------------------------------------------------------------------------
# Node category resolution for stub emission. The `ontologies` transform is
# the authoritative source of names + categories for these CURIEs; PREGO's
# stubs only exist so its own edges have endpoints in its own nodes.tsv, and
# the merge step dedups on id and prefers the ontologies row's richer info.
# ---------------------------------------------------------------------------

_GO_CATEGORY_BY_TYPE: Dict[int, str] = {
    PREGO_TYPE_GO_BP: "biolink:BiologicalProcess",
    PREGO_TYPE_GO_CC: "biolink:CellularComponent",
    PREGO_TYPE_GO_MF: "biolink:MolecularActivity",
}


def go_category_for_type(entity_type: int) -> str:
    """Return the biolink category matching a GO tagger type integer."""
    return _GO_CATEGORY_BY_TYPE.get(entity_type, "biolink:OntologyClass")


# ---------------------------------------------------------------------------
# DOID → MONDO xref lookup.
# ---------------------------------------------------------------------------


def load_doid_to_mondo(mondo_nodes_file: Path) -> Dict[str, str]:
    """
    Build a ``{DOID:xxx: MONDO:yyy}`` lookup from the ontologies output.

    Reads ``data/transformed/ontologies/mondo_nodes.tsv``, which carries a
    pipe-delimited ``xref`` column containing DOID / MESH / NCIT / ... aliases
    per MONDO term. The lookup is small enough (a few tens of thousands of
    DOID entries) to sit in memory for the full PREGO run.

    Returns an empty dict if the file does not exist — the transform will
    then log-and-skip every DOID row rather than crash, which is the correct
    behavior when the ontologies transform hasn't been re-run.
    """
    lookup: Dict[str, str] = {}
    if not mondo_nodes_file.is_file():
        return lookup
    with mondo_nodes_file.open("r", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            mondo_id = row.get("id", "")
            if not mondo_id.startswith("MONDO:"):
                continue
            xrefs = (row.get("xref") or "").split("|")
            for xref in xrefs:
                if xref.startswith("DOID:"):
                    # Prefer first-seen mapping; MONDO xrefs are curated one-to-one
                    # for DOID so collisions are rare, but if one occurs the first
                    # row wins (deterministic per file order).
                    lookup.setdefault(xref, mondo_id)
    return lookup


# ---------------------------------------------------------------------------
# Raw-row iterator.
# ---------------------------------------------------------------------------


def iter_database_pairs(path: Path) -> Iterator[Tuple[list, Optional[str]]]:
    """
    Yield ``(row, error)`` pairs from a ``database_pairs.tsv``.

    ``row`` is the raw split list of exactly nine strings when the row is
    well-formed and ``error`` is ``None``. When a row is malformed, ``row``
    is the raw list (may be any length) and ``error`` is a short reason
    string. Callers should count malformed rows and continue rather than
    raise — real files carry ~10^8 rows, and one bad line shouldn't sink
    the whole transform.

    Encoded as a plain generator over line-oriented reads; the caller is
    responsible for opening a stream-friendly file handle (raw TSV, or
    ``tarfile.extractfile()`` output). No CSV quoting is expected — PREGO
    files are pure tab-delimited, no embedded quotes.
    """
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip("\n\r")
            if not line:
                continue
            row = line.split("\t")
            if len(row) != DATABASE_PAIRS_NCOL:
                yield row, f"malformed line {lineno}: got {len(row)} cols, want {DATABASE_PAIRS_NCOL}"
                continue
            yield row, None
