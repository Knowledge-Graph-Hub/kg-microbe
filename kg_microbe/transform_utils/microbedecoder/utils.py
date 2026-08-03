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

# Identity crosswalk MicrobeDecoder pre-joins per row. Emit each as a
# `biolink:close_match` edge from `lpsn:<LPSN_ID>` to the target CURIE.
# `(column, prefix, formatter)`: formatter takes the raw cell value and
# returns the local ID part (or None to skip). None formatter means the raw
# value is already the local ID.
CROSSWALK_COLUMNS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("NCBI_Taxonomy_ID", "NCBITaxon:", None),
    ("GTDB_ID", "GTDB:", None),
    ("BacDive_ID", "bacdive:", None),
    ("GOLD_Organism_ID", "GOLD:", None),
    ("IMG_Genome_ID", "IMG:", None),
)

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


# Multi-value cell splitter. Bergey / VPI / Literature end-product columns
# use comma-separated values ("acetate, lactate, ethanol"), occasionally with
# semicolons in the raw source text. Whitespace is collapsed; empties are
# dropped. The strict=False regex is deliberate — one place, one rule.
#
# Known v1 limitation: a chemical name containing a literal comma (e.g.
# ``2,3-butanediol``) will over-split into ``2`` and ``3-butanediol``. The
# same limitation exists in madin_etal's multi-value handling; MicrobeDecoder
# rows use simple end-product names in practice ("acetate", "lactate",
# "butanol"). A follow-up can promote this to a smarter parser once a
# curated exceptions list exists.
_MULTIVALUE_SPLIT = re.compile(r"\s*[,;]\s*")


def split_multivalue(cell: object) -> List[str]:
    """Split a multi-value cell into a list of trimmed non-empty tokens."""
    if cell is None:
        return []
    text = str(cell).strip()
    if not text or text.lower() in _EMPTY_MARKERS:
        return []
    return [tok for tok in (t.strip() for t in _MULTIVALUE_SPLIT.split(text)) if tok]


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
