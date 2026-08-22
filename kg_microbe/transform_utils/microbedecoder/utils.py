"""
Helpers for the MicrobeDecoder transform.

Column definitions and light per-cell parsers so ``microbedecoder.py`` stays
focused on row → node/edge emission and cross-ref wiring. All heavy semantic
work (label → CURIE resolution, NER fallback) reuses existing utilities in
``kg_microbe.utils`` — see the transform module docstring for the full list.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Column groups (matches the wide `database.csv` produced by MicrobeDecoder's
# `Database/assembleDatabase.R`). Grouped by source-of-record so the transform
# can tag every emitted edge with the correct `provided_by` / knowledge_source
# without a per-column switch statement.
# ---------------------------------------------------------------------------

# Primary key + attribute columns emitted directly on the LPSN organism node.
LPSN_ID_COLUMN = "LPSN_ID"
LPSN_STATUS_COLUMN = "LPSN_status"
#: Naming columns, used to label stubs for ids the lpsn transform cannot
#: supply (botanical-code cyanobacteria absent from lpsn_gss.csv, #811).
LPSN_GENUS_COLUMN = "LPSN_Genus"
LPSN_SPECIES_COLUMN = "LPSN_Species"
LPSN_SUBSPECIES_COLUMN = "LPSN_Subspecies"

# Identity crosswalk MicrobeDecoder pre-joins per row. Emit each as a
# `biolink:close_match` edge from `lpsn:<LPSN_ID>` to the target CURIE.
# `(column, emitted_prefix, source_prefix)`: `source_prefix` is the CURIE
# prefix the raw cell may already carry when it differs from the emitted
# one; None means the source uses the emitted prefix (or a bare local ID).
#
# BacDive emits `kgmicrobe.strain:bacdive_<id>` because that is the CURIE the
# bacdive transform actually mints for a strain (99,392 node rows). The bare
# `bacdive:<id>` form this used to emit is not a node anywhere in the graph,
# so all ~19 K of these edges dangled and KGX turned them into empty stubs.
CROSSWALK_COLUMNS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("NCBI_Taxonomy_ID", "NCBITaxon:", None),
    ("GTDB_ID", "GTDB:", None),
    ("BacDive_ID", "kgmicrobe.strain:bacdive_", "bacdive:"),
    ("GOLD_Organism_ID", "GOLD:", None),
    ("IMG_Genome_ID", "IMG:", None),
)

# The BacDive crosswalk is not an identifier equivalence like the others. Its
# target is a *strain*, not another name for the same taxon, and the source says
# which strain: MicrobeDecoder's strain designation equals LPSN's own
# `nomenclatural_type` for 98.9% of the 21,247 rows that match a GSS record, and
# shares a culture-collection number for another 1.1% — so the row means "this
# BacDive record is the type strain of this LPSN name". That is what makes it
# strictly 1:1 where bacdive's relation is many-to-one.
#
# `close_match` asserted near-identity between a name and a strain, and after
# #680 collided head-on with bacdive's `strain -subclass_of-> lpsn` over 18,425
# of the same pairs (#687): skos:closeMatch and proper subsumption cannot both
# hold. Emitting the same subsumption bacdive does makes the two transforms
# agree instead, so merge collapses the duplicates and keeps both provenances.
#
# The type-strain *specificity* is still unexpressed — no Biolink or METPO
# predicate carries it — and is deferred rather than invented here.
BACDIVE_CROSSWALK_COLUMN = "BacDive_ID"

# Metabolism / fermentation column groups. Each entry drives one predicate
# family; see :func:`iter_metabolism_columns` for the emission rules.
#
# Layout: ``group_label`` is the source-of-record tag used in
# ``primary_knowledge_source``; ``columns`` maps a semantic role to the
# actual database.csv column name.
METABOLISM_GROUPS: Tuple[Dict[str, object], ...] = (
    {
        "group_label": "bergey",
        "columns": {
            "type_of_metabolism": "Bergey_Type_of_metabolism",
            "major_end_products": "Bergey_Major_end_products",
            "minor_end_products": "Bergey_Minor_end_products",
            "substrates": "Bergey_Substrates_for_end_products",
            "end_products_text": "Bergey_Text_for_end_products",
            "substrates_text": "Bergey_Text_for_substrates",
        },
    },
    {
        "group_label": "vpi",
        "columns": {
            "type_of_metabolism": "VPI_Type_of_metabolism",
            "major_end_products": "VPI_Major_end_products",
            "minor_end_products": "VPI_Minor_end_products",
        },
    },
    {
        "group_label": "literature",
        "columns": {
            "type_of_metabolism": "Literature_Type_of_metabolism",
            "major_end_products": "Literature_Major_end_products",
            "minor_end_products": "Literature_Minor_end_products",
            "substrates": "Literature_Substrates_for_end_products",
            "end_products_text": "Literature_Text_for_end_products",
            "citation": "Literature_Citation",
        },
    },
    {
        "group_label": "faprotax",
        "columns": {
            "type_of_metabolism": "FAPROTAX_Type_of_metabolism",
        },
    },
)

# BacDive_* snapshot MicrobeDecoder ships. Ingested with MicrobeDecoder
# provenance (user decision) so the 2024-11-07 snapshot the paper's analyses
# ran on stays reproducible. Fresher `bacdive` transform is authoritative;
# merge-time dedup keeps both edges around, distinguishable via
# `primary_knowledge_source`.
BACDIVE_SNAPSHOT_COLUMNS: Tuple[str, ...] = (
    "BacDive_Antibiotic_resistance",
    "BacDive_Antibiotic_sensitivity",
    "BacDive_Cell_length",
    "BacDive_Cell_shape",
    "BacDive_Cell_width",
    "BacDive_Colony_size",
    "BacDive_Enzyme_activity",
    "BacDive_Flagellum_arrangement",
    "BacDive_Gram_stain",
    "BacDive_Incubation_period",
    "BacDive_Indole_test",
    "BacDive_Metabolite_production",
    "BacDive_Metabolite_utilization",
    "BacDive_Motility",
    "BacDive_Oxygen_tolerance",
    "BacDive_pH_for_growth",
    "BacDive_Pathogenicity_animal",
    "BacDive_Pathogenicity_human",
    "BacDive_Pathogenicity_plant",
    "BacDive_Salt_concentration",
    "BacDive_Salt_concentration_unit",
    "BacDive_Spore_formation",
    "BacDive_Temperature_for_growth",
    "BacDive_Voges_proskauer",
    "BacDive_Isolation_category_1",
    "BacDive_Isolation_category_2",
    "BacDive_Isolation_category_3",
)


# Multi-value cell splitters. Two variants because MicrobeDecoder's
# column-family conventions are not uniform:
#
# ``_MULTIVALUE_SPLIT`` (comma OR semicolon) is used for the metabolism
# and BacDive-snapshot columns whose Bergey / VPI / Literature end-products
# use comma-separated values ("acetate, lactate, ethanol") and occasionally
# semicolons in the raw source text.
#
# ``_MULTIVALUE_SPLIT_COMMA_ONLY`` is used for the identity-crosswalk
# columns (``NCBI_Taxonomy_ID``, ``GTDB_ID``, ``BacDive_ID``,
# ``GOLD_Organism_ID``, ``IMG_Genome_ID``). Only ``IMG_Genome_ID`` actually
# multi-values in practice — it packs multiple genome IDs per row
# comma-separated. The other four columns are single-value but sometimes
# contain internal semicolons that are part of the identifier itself
# (``GTDB_ID`` uses semicolons as rank separators, e.g.
# ``d__Bacteria;g__Bacillus;s__Bacillus subtilis``); a semicolon split
# would shred those into three orphan CURIEs (issue #655 regression net).
#
# Separators inside brackets are NOT separators (#838). Splitting on every
# comma cut four real labels in half, each fragment then reaching
# ``microbedecoder_unmapped_labels_to_curate.tsv`` as its own unmappable
# "term":
#
#   "O/129 (2,4-diamino-6,7-di-iso-propylpteridine phosphate)"
#       -> "0129 (2"  +  "7-di-iso-propylpteridine phosphate)"   (1,212 occ)
#   "#Herbaceous plants (Grass, Crops)"
#       -> "#Herbaceous plants (Grass"  +  "Crops)"              (1,021 occ)
#   "#Bovinae (Cow, Cattle)"     -> ... (200 occ)
#   "#Suidae (Pig, Swine)"       -> ... (156 occ)
#
# The matched occurrence counts are what proved these were one string each:
# every label with an unclosed ``(`` paired exactly with one carrying an
# orphan ``)``. MediaIngredientMech hit the same defect on the ingredient side
# (its #308) and had to tombstone the fragments after the fact.
#
# Still a known limitation, shared with ``madin_etal``: a comma inside a
# chemical name with no brackets around it (``2,3-butanediol``) is
# indistinguishable from a separator by any structural rule, and still
# over-splits. MicrobeDecoder rows use simple end-product names in practice.
_MULTIVALUE_SEPARATORS = ",;"
_COMMA_ONLY_SEPARATORS = ","
_OPENERS = "([{"
_CLOSERS = ")]}"


def split_multivalue(cell: object) -> List[str]:
    """
    Split a multi-value cell on comma OR semicolon, outside brackets only.

    :param cell: Raw cell value.
    :return: Trimmed, non-empty tokens.
    """
    return _split(cell, _MULTIVALUE_SEPARATORS)


def split_multivalue_comma_only(cell: object) -> List[str]:
    """
    Split a multi-value cell on comma ONLY (preserves in-value semicolons).

    Use for identity-crosswalk cells (``IMG_Genome_ID`` and friends) where
    a raw semicolon is part of the identifier (``GTDB_ID`` rank separator)
    rather than a value separator.
    """
    return _split(cell, _COMMA_ONLY_SEPARATORS)


def _split(cell: object, separators: str) -> List[str]:
    """
    Split a cell on separators that sit outside any bracket.

    An unclosed bracket leaves the depth above zero for the rest of the
    string, so everything after it stays in one token. That is the
    conservative reading: with the structure broken we cannot tell where a
    value ends, and inventing a boundary is what produced the orphan fragments
    in the first place.

    :param cell: Raw cell value.
    :param separators: Characters that separate values at bracket depth zero.
    :return: Trimmed, non-empty tokens.
    """
    if cell is None:
        return []
    text = str(cell).strip()
    if not text or text.lower() in _EMPTY_MARKERS:
        return []

    tokens: List[str] = []
    buffer: List[str] = []
    depth = 0
    for char in text:
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            # Clamp at zero: a stray closer must not drive the depth negative
            # and make every later separator look nested.
            depth = max(0, depth - 1)
        if depth == 0 and char in separators:
            tokens.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    tokens.append("".join(buffer))
    return [tok for tok in (t.strip() for t in tokens) if tok]


# Values MicrobeDecoder uses to indicate "no data" for a cell. Detected
# case-insensitively before splitting, so a lone "NA" doesn't emit a
# `kgmicrobe.fermentation:na` placeholder.
_EMPTY_MARKERS = frozenset({"na", "n/a", "none", "nan", "unknown", "-"})


def is_empty_cell(cell: object) -> bool:
    """Report whether a cell value should be treated as absent."""
    if cell is None:
        return True
    text = str(cell).strip()
    return not text or text.lower() in _EMPTY_MARKERS


# Slugify a raw label for use as the local part of a `kgmicrobe.fermentation:`
# placeholder CURIE. Lowercase, alphanumerics + underscore, whitespace
# collapsed. Matches the pattern other transforms use for provisional CURIEs
# (see madin_etal / mediadive ingredient slugs) so the placeholder table
# stays consistent.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify_label(label: str) -> str:
    """Produce a stable CURIE-safe slug from a raw source label."""
    cleaned = _SLUG_STRIP.sub("_", label.strip().lower()).strip("_")
    return cleaned or "unlabeled"


# Publication attribute formatter. MicrobeDecoder's `Literature_Citation`
# column carries either a DOI, a PMID, or free-text — normalise to a
# `PMID:<int>` or `doi:<slug>` CURIE where possible; otherwise return the raw
# citation string as a fallback attribute value (which the KGX loader carries
# through without validation).
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID[:\s]?\s*(\d+)", re.IGNORECASE)


def format_citation(raw: object) -> Optional[str]:
    """
    Return a ``PMID:`` / ``doi:`` CURIE for the citation cell, or None.

    Accepts free text; extracts the first DOI or PMID it finds. Returns None
    when the cell is empty (per :func:`is_empty_cell`) or contains no
    recognisable citation token — the caller can then decide whether to drop
    the citation attribute or store the raw prose.
    """
    if is_empty_cell(raw):
        return None
    text = str(raw)
    pmid_match = _PMID_RE.search(text)
    if pmid_match:
        return f"PMID:{pmid_match.group(1)}"
    doi_match = _DOI_RE.search(text)
    if doi_match:
        return f"doi:{doi_match.group(0)}"
    return None


def iter_metabolism_columns(
    row: Dict[str, object],
) -> Iterable[Tuple[str, Dict[str, object]]]:
    """
    Yield (``group_label``, ``fields``) for every metabolism source with data.

    ``fields`` carries the raw cell values for each column-role the group
    declares (see :data:`METABOLISM_GROUPS`). Groups whose columns are all
    empty (via :func:`is_empty_cell`) are skipped so the caller only iterates
    over sources that actually contributed to this row. Missing columns
    (source doesn't declare that role) simply are absent from ``fields``.
    """
    for group in METABOLISM_GROUPS:
        columns: Dict[str, str] = group["columns"]  # type: ignore[assignment]
        raw_fields = {role: row.get(col) for role, col in columns.items() if col in row}
        if not any(not is_empty_cell(v) for v in raw_fields.values()):
            continue
        yield str(group["group_label"]), raw_fields
