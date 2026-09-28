"""
Apply a reviewed chemical spelling correction to one complete source record.

This is not a global chemical alias or a modification of the pinned MIM release.
Schink (1984), Table 4 and the Ilyobacter tartaricus species description, link
strain GraTa2 / DSM 2382 to tartrate fermentation and the reported products.
The broad native tartrate class avoids inventing a counterion or stereoisomer.
"""

from __future__ import annotations

import csv
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Mapping, TextIO

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    CHEMICAL_CATEGORY,
    DEPRECATED_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
)

REVIEWED_LPSN_ID = "777027"
REVIEWED_SOURCE_KEY = "bergey:substrates"
REVIEWED_SOURCE_COLUMN = "Bergey_Substrates_for_end_products"
REVIEWED_LITERAL = "tartate"
REVIEWED_CITATION = "https://doi.org/10.1002/9781118960608.gbm00769"
REVIEWED_RAW_ROW_SHA256 = "de979939d39a74aad45a0edffe59cde4e11b6d294ee9fb22e848a12bd0dda13f"
PRIMARY_EVIDENCE_URI = "https://d-nb.info/1105570576/34"
TARGET_CURIE = "CHEBI:132950"
TARGET_LABEL = "tartrate"


def canonical_raw_row_sha256(row: Mapping[str, Any]) -> str:
    """Bind every literal CSV field, independently of column order or ordinal."""
    literal = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(literal.encode("utf-8", errors="surrogateescape")).hexdigest()


class RecordChemicalCuration:
    """
    Resolve one record/field while retaining native ownership of its target.

    The caller must retain the supplied ChEBI input through consumed-input
    finalization and call ``resolve`` for the reviewed field even when its
    current value is empty. A changed known record requires a new review, not
    fallback to an old or guessed chemical identity.
    """

    def __init__(self, chebi_nodes_input: str | Path | TextIO) -> None:
        """Require exactly one active, correctly named native target declaration."""
        source = (
            nullcontext(chebi_nodes_input)
            if hasattr(chebi_nodes_input, "read")
            else Path(chebi_nodes_input).open(encoding="utf-8", newline="")
        )
        found = False
        with source as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            required = {ID_COLUMN, NAME_COLUMN, CATEGORY_COLUMN, DEPRECATED_COLUMN}
            if not required.issubset(header) or len(header) != len(set(header)):
                raise ValueError("Missing or duplicate ChEBI record-curation declaration columns")
            for row in reader:
                if row[ID_COLUMN] != TARGET_CURIE:
                    continue
                if found:
                    raise ValueError(f"Duplicate ChEBI record-curation target: {TARGET_CURIE}")
                if None in row or any(row.get(column) is None for column in required):
                    raise ValueError(f"Malformed ChEBI record-curation target: {TARGET_CURIE}")
                if (row[NAME_COLUMN], row[CATEGORY_COLUMN]) != (TARGET_LABEL, CHEMICAL_CATEGORY):
                    raise ValueError(f"Unexpected ChEBI record-curation label/category: {TARGET_CURIE}")
                if row[DEPRECATED_COLUMN].strip().lower() not in {"", "false", "0"}:
                    raise ValueError(f"Deprecated or invalid ChEBI record-curation target: {TARGET_CURIE}")
                found = True
        if not found:
            raise ValueError(f"Missing authoritative ChEBI record-curation target: {TARGET_CURIE}")

    def resolve(self, row: Mapping[str, Any], source_key: str, literal: str) -> str | None:
        """Correct only the authenticated record; never normalize another label."""
        # The producer strips/stringifies its subject ID. Recognize that same
        # candidate here, but never admit a normalized or changed raw record.
        if source_key != REVIEWED_SOURCE_KEY or str(row.get("LPSN_ID")).strip() != REVIEWED_LPSN_ID:
            return None
        if (
            row.get("LPSN_ID") != REVIEWED_LPSN_ID
            or literal != REVIEWED_LITERAL
            or row.get(REVIEWED_SOURCE_COLUMN) != REVIEWED_LITERAL
            or row.get("Bergey_Article_link") != REVIEWED_CITATION
            or canonical_raw_row_sha256(row) != REVIEWED_RAW_ROW_SHA256
        ):
            raise ValueError("Reviewed tartrate record/field evidence changed for LPSN_ID 777027")
        return TARGET_CURIE
