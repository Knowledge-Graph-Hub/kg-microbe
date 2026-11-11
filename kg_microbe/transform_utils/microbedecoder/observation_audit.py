"""Retain suppressed source observations without treating missing reports as biology."""

from __future__ import annotations

import csv
import hashlib
import json
from itertools import zip_longest

from kg_microbe.transform_utils.constants import (
    BERGEY_KNOWLEDGE_SOURCE,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    LPSN_PREFIX,
    MICROBEDECODER,
    SOURCE_ATTRIBUTE_PREFIX,
    SOURCE_COLUMN,
    SOURCE_RECORD_COLUMN,
)
from kg_microbe.transform_utils.microbedecoder.utils import (
    LPSN_ID_COLUMN,
    format_citation,
    is_empty_cell,
    slugify_label,
    split_multivalue,
)

AUDIT_FILE = "reported_observations.tsv"
AUDIT_FIELDS = (
    "disposition",
    SOURCE_RECORD_COLUMN,
    SOURCE_COLUMN,
    "source_cell_json",
    "original_claim_json",
    "emitted_claim_json",
    "evidence_uri",
    "curation_rationale",
)
SNAPSHOT_AUDIT_ONLY = "bacdive_snapshot_disabled_preserved_observation"
PLACEHOLDER_AUDIT_ONLY = "missing_or_unspecified_report_not_biological_assertion"
BERGEY_PLACEHOLDERS = {
    "Bergey_Type_of_metabolism": "Other",
    "Bergey_Substrates_for_end_products": "Not reported",
}


def source_attribute_curie(column, literal):
    """Preserve the existing exact column/literal identifier without declaring a node."""
    identity = json.dumps([MICROBEDECODER, column, literal], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogateescape")).hexdigest()
    return f"{SOURCE_ATTRIBUTE_PREFIX}{MICROBEDECODER}_{slugify_label(column)}_{digest}"


def audit_row(claim, native, disposition):
    """Retain every original assertion field and its unsplit native cell as escaped JSON."""

    def encode(value):
        """Encode native byte surrogates and control characters losslessly for literal TSV."""
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)

    column = claim[SOURCE_COLUMN]
    return {
        "disposition": disposition,
        SOURCE_RECORD_COLUMN: claim[SOURCE_RECORD_COLUMN],
        SOURCE_COLUMN: column,
        "source_cell_json": encode(native.get(column)),
        "original_claim_json": encode(claim),
        "emitted_claim_json": "null",
        "evidence_uri": "",
        "curation_rationale": "",
    }


def expected_rows(raw_stream, *, raw_sha256, fields, accepted, selected, include_snapshot):
    """Independently replay the exact finite suppression rules from the admitted native CSV."""
    from kg_microbe.transform_utils.microbedecoder.bacdive_join_dispositions import _snapshot_projection
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

    # Only the pure row builder is used: no transform construction, adapters or output writes.
    builder = MicrobeDecoderTransform.__new__(MicrobeDecoderTransform)
    builder.edge_header = list(fields)
    for ordinal, native in enumerate(csv.DictReader(raw_stream), 1):
        source_id = native.get(LPSN_ID_COLUMN)
        if is_empty_cell(source_id):
            continue
        source_id = str(source_id).strip()
        subject = LPSN_PREFIX + accepted.get(source_id, source_id)
        record = f"sha256:{raw_sha256}#record={ordinal}"
        builder._source_record = record
        citation = native.get("Bergey_Article_link")
        for column, literal in BERGEY_PLACEHOLDERS.items():
            for token in split_multivalue(native.get(column)):
                if token != literal:
                    continue
                values = builder._make_edge_row(
                    subject,
                    HAS_ATTRIBUTE_PREDICATE,
                    source_attribute_curie(column, literal),
                    HAS_ATTRIBUTE_RELATION,
                    BERGEY_KNOWLEDGE_SOURCE,
                    publications=format_citation(citation),
                    source_citation=citation,
                    source_column=column,
                    value=literal,
                )
                claim = dict(zip(fields, (value or "" for value in values), strict=True))
                yield audit_row(claim, native, PLACEHOLDER_AUDIT_ONLY)
        if not include_snapshot:
            item = selected.get(record)
            node = item["snapshot_node"] if item else None
            if node:
                subject = node["id"]
            for claim in _snapshot_projection(fields, record, subject, native):
                yield audit_row(claim, native, SNAPSHOT_AUDIT_ONLY)


def verify_rows(audit_stream, expected):
    """Require complete ordered observation occurrences; no dropped, duplicated or changed cells."""
    reader = csv.DictReader(audit_stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    if reader.fieldnames != list(AUDIT_FIELDS):
        raise ValueError("MicrobeDecoder observation audit header changed")
    # The separate mandatory FAPROTAX native verifier checks every FAPROTAX row.
    selected = (row for row in reader if row.get(SOURCE_COLUMN) != "FAPROTAX_Type_of_metabolism")
    for actual, original in zip_longest(selected, expected):
        if actual != original:
            raise ValueError("MicrobeDecoder observation audit differs from admitted native observations")
