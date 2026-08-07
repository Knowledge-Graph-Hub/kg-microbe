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
KEEP_TAXON_TO_BTO = "taxon_to_bto"
DROP_INVERSE_TAXON_TO_GO = "inverse_go_to_taxon"
DROP_INVERSE_ENVO_TO_TAXON = "inverse_taxon_to_envo"
DROP_INVERSE_TAXON_TO_BTO = "inverse_bto_to_taxon"
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
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type == PREGO_TYPE_BTO:
        return KEEP_TAXON_TO_BTO
    # Inverses of the four canonical directions — drop, don't re-emit.
    if entity1_type in _GO_TYPES and entity2_type == PREGO_TYPE_NCBITAXON:
        return DROP_INVERSE_TAXON_TO_GO
    if entity1_type == PREGO_TYPE_NCBITAXON and entity2_type == PREGO_TYPE_ENVO:
        return DROP_INVERSE_ENVO_TO_TAXON
    if entity1_type == PREGO_TYPE_BTO and entity2_type == PREGO_TYPE_NCBITAXON:
        return DROP_INVERSE_TAXON_TO_BTO
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


def iter_dictionary_entities(path: Path) -> Iterator[Tuple[int, int, str]]:
    """
    Yield ``(serial, entity_type, source_id)`` triples from ``prego_entities.tsv``.

    JensenLab tagger convention: three tab-separated columns per row —
    serial (unique positive integer), entity type (positive for NCBI-species
    proteins, negative for the standardized vocabularies), and the
    source-native identifier. Malformed rows are silently skipped; ~2.5 M
    well-formed rows in the full PREGO dictionary.
    """
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) != 3:
                continue
            try:
                yield int(parts[0]), int(parts[1]), parts[2]
            except ValueError:
                continue


def iter_dictionary_names(path: Path) -> Iterator[Tuple[int, str]]:
    """
    Yield ``(serial, synonym)`` pairs from ``prego_names.tsv``.

    ~13.9 M rows in the full dictionary. Callers must be O(1) per row —
    materialising as a list defeats the streaming intent.
    """
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) != 2:
                continue
            try:
                yield int(parts[0]), parts[1]
            except ValueError:
                continue


# ---------------------------------------------------------------------------
# CURIE construction from tagger (type, source_id) pairs.
# ---------------------------------------------------------------------------


def entity_to_curie(entity_type: int, source_id: str) -> Optional[str]:
    """
    Return the KG-Microbe CURIE for a tagger ``(type, source_id)`` pair, or None.

    Handles the direct-mapping types (NCBITaxon, all 3 GO namespaces, ENVO,
    BTO). DOID is intentionally NOT handled here — DOID→MONDO xref
    resolution is context-dependent (needs the ontologies output's xref
    map) so ``_load_dictionary`` routes DOID synonyms to their MONDO
    CURIEs separately.
    """
    if entity_type == PREGO_TYPE_NCBITAXON and source_id:
        return f"NCBITaxon:{source_id}"
    if entity_type in _GO_TYPES and source_id.startswith("GO:"):
        return source_id
    if entity_type == PREGO_TYPE_ENVO and source_id.startswith("ENVO:"):
        return source_id
    if entity_type == PREGO_TYPE_BTO and source_id.startswith("BTO:"):
        return source_id
    return None


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


# ---------------------------------------------------------------------------
# Channel identification and per-channel edge metadata.
#
# PREGO's own column 6 was emitted as `prego_channel`, but it is not a channel:
# across the real archives it holds evidence tallies ("402 of 487 samples"),
# resource classes ("Isolates", "Genome annotation", "Metagenome-Assembled
# Genome", "Single Amplified Genome", each also in a "* GOLD" variant),
# citations ("PMID:24914180"), and habitat names ("Aquatic", "Groundwater",
# "Plants"). Its ~24k distinct values made channel-selection — one of the two
# filters the ingest plan promises — impossible.
#
# The actual channel is the archive: environmental_samples vs
# annotated_genomes_isolates vs literature. That is what PREGO's paper means by
# a channel, and it is the axis with distinct scoring semantics.
# ---------------------------------------------------------------------------

CHANNEL_ENVIRONMENTAL = "environmental_samples"
CHANNEL_GENOMES = "annotated_genomes_isolates"
CHANNEL_LITERATURE = "literature"

# Evidence classes for the raw column, so the grab-bag becomes filterable.
EVIDENCE_SAMPLE_COUNT = "sample_count"
EVIDENCE_RESOURCE_CLASS = "resource_class"
EVIDENCE_PUBLICATION = "publication"
EVIDENCE_HABITAT = "habitat"
EVIDENCE_UNKNOWN = "unknown"

_RESOURCE_CLASS_PREFIXES = (
    "Isolates",
    "Genome annotation",
    "Metagenome-Assembled Genome",
    "Single Amplified Genome",
)


def channel_for_archive(archive_name: str) -> str:
    """
    Return the PREGO channel an archive belongs to.

    :param archive_name: Archive filename or stem, e.g. ``environmental_samples.tar.gz``.
    :return: One of the CHANNEL_* constants, or the normalised stem when the
        archive is not one of the three documented channels.
    """
    stem = archive_name.split("/")[-1]
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = stem.replace("-", "_").lower()
    for known in (CHANNEL_ENVIRONMENTAL, CHANNEL_GENOMES, CHANNEL_LITERATURE):
        if stem.startswith(known):
            return known
    return stem


def classify_evidence(value: str) -> str:
    """
    Classify a raw PREGO column-6 value.

    :param value: The raw value as shipped.
    :return: One of the EVIDENCE_* constants.
    """
    if not value:
        return EVIDENCE_UNKNOWN
    parts = value.split()
    if len(parts) == 4 and parts[1] == "of" and parts[3] == "samples" and parts[0].isdigit():
        return EVIDENCE_SAMPLE_COUNT
    if value.startswith("PMID:"):
        return EVIDENCE_PUBLICATION
    if value.startswith(_RESOURCE_CLASS_PREFIXES):
        return EVIDENCE_RESOURCE_CLASS
    return EVIDENCE_HABITAT


def edge_metadata_for(channel: str, evidence_class: str) -> Tuple[str, str]:
    """
    Return ``(knowledge_level, agent_type)`` for a PREGO edge.

    PREGO edges shipped with both fields empty, so 44.7M text-mined and
    statistically-derived associations were indistinguishable from curated
    assertions anywhere in the merged KG. The values differ by channel because
    the channels are generated by genuinely different processes — a single
    constant would misdescribe most of them.

    A citation in the evidence column overrides the channel default: those rows
    combine curated metadata with text mining over the linked abstract, which
    the authors themselves score one tier lower.

    :param channel: One of the CHANNEL_* constants.
    :param evidence_class: One of the EVIDENCE_* constants.
    :return: Biolink ``knowledge_level`` and ``agent_type`` values.
    """
    if evidence_class == EVIDENCE_PUBLICATION or channel == CHANNEL_LITERATURE:
        return "prediction", "text_mining_agent"
    if channel == CHANNEL_ENVIRONMENTAL:
        # Scores are computed from taxon-sample co-occurrence statistics.
        return "statistical_association", "data_analysis_pipeline"
    if channel == CHANNEL_GENOMES:
        # Derived from genome annotation pipelines over curated resources.
        return "knowledge_assertion", "automated_agent"
    return "not_provided", "not_provided"
