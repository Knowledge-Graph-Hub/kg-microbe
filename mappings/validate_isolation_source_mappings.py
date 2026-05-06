#!/usr/bin/env python3
"""
CI-friendly validator for ``mappings/isolation_source_to_ontology.tsv``.

This script is intentionally standalone (only stdlib imports) so it can run
in lightweight CI containers without installing the full ``kg_microbe``
package and its heavyweight dependencies.

The validation rules below MUST stay in sync with
:mod:`kg_microbe.utils.isolation_source_mapping_utils`. The unit test
``tests/test_isolation_source_mapping_utils.py::test_validator_rules_match_loader``
asserts the two definitions are equal so drift is caught at PR time.

Rules:

* ``DISALLOWED_OBJECT_SOURCES`` — source ontologies that are categorically
  wrong for an isolation source (e.g. ``UO``, the unit ontology).
* ``BANNED_OBJECT_LABEL_SUBSTRINGS`` — case-insensitive substrings in the
  *target* ``object_label`` that signal a family mismatch (a facility,
  document, or clinical instrument used in place of a substrate /
  body part / host / environment).

Exit codes:

* 0 — every mapped row passes the family-compatibility check.
* 1 — at least one row failed; details printed to stderr.

Usage::

    python mappings/validate_isolation_source_mappings.py [path/to/mapping.tsv]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, Iterable, Tuple

DEFAULT_MAPPING_FILE = Path(__file__).resolve().parent / "isolation_source_to_ontology.tsv"

DISALLOWED_OBJECT_SOURCES: frozenset = frozenset({
    "UO",
    "PATO",
    "METPO",
})

# Mirror of kg_microbe/utils/isolation_source_mapping_utils.py:PREDICATE_OVERRIDE_CURIES.
# Rows whose `notes` column references one of these CURIEs are exempt from the
# PATO ban (the override token re-shapes the downstream edge so PATO is well-
# formed as a quality of the source, not a broken location target). METPO is
# never exempt — METPO terms describe organism phenotypes, not source qualities.
PREDICATE_OVERRIDE_CURIES: frozenset = frozenset({
    "METPO:2000067",  # isolated from host with quality
    "METPO:2000068",  # isolated from environment with quality
})

BANNED_OBJECT_LABEL_SUBSTRINGS: Tuple[str, ...] = (
    "ability question",
    "processing plant",
    "human construction",
    "patient room",
    "indoor toilet",
    "child care environment",
    "house painting",
    "medical product document",
    "infection zone",
    "breeding waste material",
    "dependence on",
    "swab",
    "medical device",
    "food production",
    "antibiotic treatment",
)


def _has_predicate_override(row: Dict[str, str]) -> bool:
    """Return True iff the row's notes column references a known override CURIE."""
    notes = (row.get("notes") or "")
    if not notes:
        return False
    cleaned = notes.replace(";", " ").replace(",", " ").replace("(", " ").replace(")", " ")
    return any(token in PREDICATE_OVERRIDE_CURIES for token in cleaned.split())


def _row_is_trusted(row: Dict[str, str]) -> bool:
    """
    Mirror of the loader's trust policy.

    Both paths require ``skos:exactMatch``: closeMatch is never trusted for
    canonical node substitution because it only asserts similarity, not
    equivalence (see Codex review #558). Two trust paths within exactMatch:
    high-confidence auto-match, or manual curation.
    """
    predicate = (row.get("predicate_id") or "").strip()
    if predicate != "skos:exactMatch":
        return False
    confidence = (row.get("confidence") or "").strip().lower()
    justification = (row.get("mapping_justification") or "").strip()
    return (confidence == "high") or (justification == "semapv:ManualMappingCuration")


def iter_validation_failures(
    mapping_path: Path,
) -> Iterable[Tuple[int, Dict[str, str], str]]:
    """
    Yield ``(row_number, row, reason)`` for every row that violates a rule.

    A row only counts as a failure if it would be loaded at runtime *and*
    fails the family-compatibility check. Untrusted rows are skipped because
    the loader drops them anyway.
    """
    with mapping_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for idx, row in enumerate(reader, start=1):
            if not (row.get("object_id") or "").strip():
                continue  # explicitly unmapped — not a validation failure
            if not _row_is_trusted(row):
                continue  # loader would drop this; nothing to validate

            object_source = (row.get("object_source") or "").strip()
            if object_source in DISALLOWED_OBJECT_SOURCES:
                if object_source == "PATO" and _has_predicate_override(row):
                    pass  # allow — override predicate handles the inversion
                else:
                    yield idx, row, f"object_source '{object_source}' is disallowed"
                    continue

            object_label = (row.get("object_label") or "").strip().lower()
            for banned in BANNED_OBJECT_LABEL_SUBSTRINGS:
                if banned in object_label:
                    yield idx, row, f"object_label contains banned substring '{banned}'"
                    break


def main(argv: list[str]) -> int:
    """Run the validator and return a Unix exit code."""
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_MAPPING_FILE
    if not path.is_file():
        print(f"ERROR: mapping file not found at {path}", file=sys.stderr)
        return 1

    failures = list(iter_validation_failures(path))
    if not failures:
        print(f"OK: {path.name} passed family-compatibility validation.")
        return 0

    print(
        f"FAIL: {len(failures)} row(s) in {path.name} have family-mismatched ontology mappings.",
        file=sys.stderr,
    )
    print(
        "Each row below maps a label to an ontology term whose semantic family is "
        "incompatible with isolation-source semantics (e.g. units used for anatomy, "
        "facilities used for substrates, clinical assessment items used for organisms).",
        file=sys.stderr,
    )
    for row_num, row, reason in failures:
        subject = row.get("subject_label", "?")
        object_id = row.get("object_id", "?")
        object_label = row.get("object_label", "?")
        print(
            f"  row {row_num}: '{subject}' → {object_id} ('{object_label}') — {reason}",
            file=sys.stderr,
        )
    print(
        "\nFix: clear object_id / object_label / object_source / predicate_id / "
        "confidence / mapping_justification for the offending rows (set curator to "
        "'manual_review' and add a 'fix(family-mismatch): ...' note), or replace "
        "with a semantically correct ontology term.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
