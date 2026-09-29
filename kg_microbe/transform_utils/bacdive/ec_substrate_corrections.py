"""Apply finite reviewed legacy EC/substrate corrections without raw or global aliases."""

import csv
import json
import re
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    ENZYME_TO_SUBSTRATE_EDGE,
    HAS_INPUT_RELATION,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)

POLICY_RELATIVE = "mappings/canonical/bacdive_ec_substrate_corrections.tsv"
POLICY_PATH = Path(__file__).resolve().parents[3] / POLICY_RELATIVE
AUDIT_FILE = "ec_substrate_corrections.tsv"
REQUIRED_INPUTS = ("ec_substrate_correction_policy", "ec_substrate_legacy_mapping")
SOURCE_FIELDS = ("CHEBI_ID", "substrate", "KEGG_ID", "CAS_RN_ID", "EC_ID", "enzyme", "pseudo_CURIE", "reaction_name")
POLICY_FIELDS = SOURCE_FIELDS + (
    "correction_id",
    "corrected_chebi_id",
    "withheld_source_fields",
    "reason",
    "evidence_uri",
)
AUDIT_FIELDS = (
    "correction_id",
    "status",
    "source_file",
    "source_sha256",
    "source_line",
    "source_row_json",
    "original_edge_json",
    "emitted_edge_json",
    "withheld_source_fields",
    "reason",
    "evidence_uri",
    "policy_file",
    "policy_sha256",
)


def _rows(stream, *, policy=False):
    """Reject ambiguous TSV shape while retaining literal source values and physical ordinals."""
    reader = csv.reader(stream, delimiter="\t")
    header = next(reader, None)
    required = set(POLICY_FIELDS if policy else ("CHEBI_ID", "EC_ID", "substrate"))
    if (
        not header
        or len(set(header)) != len(header)
        or any(not value for value in header)
        or not required <= set(header)
        or (policy and set(header) != required)
    ):
        raise ValueError("Invalid EC substrate correction policy/source header")
    previous_line = reader.line_num
    for cells in reader:
        first_line = previous_line + 1
        previous_line = reader.line_num
        if len(cells) != len(header):
            raise ValueError(f"Malformed EC substrate row at line {first_line}")
        yield first_line, dict(zip(header, cells, strict=True))


def load_policy(stream):
    """Read explicit complete-row curation, never partial names or global old-ID replacements."""
    policies = []
    seen_ids, seen_rows, seen_assays = set(), set(), set()
    for _, rule in _rows(stream, policy=True):
        original = {key: rule[key] for key in SOURCE_FIELDS}
        identity = tuple(original.values())
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", rule["correction_id"])
            or not re.fullmatch(r"CHEBI:[1-9][0-9]*", rule["CHEBI_ID"])
            or not re.fullmatch(r"CHEBI:[1-9][0-9]*", rule["corrected_chebi_id"])
            or rule["corrected_chebi_id"] == rule["CHEBI_ID"]
            or rule["withheld_source_fields"] not in ("", "KEGG_ID")
            or (rule["withheld_source_fields"] and not rule["KEGG_ID"])
            or not re.fullmatch(r"EC:[0-9]+(?:\.[0-9-]+){3}", rule["EC_ID"])
            or any(not rule[key].strip() for key in ("substrate", "enzyme", "pseudo_CURIE", "reaction_name", "reason"))
            or not rule["pseudo_CURIE"].startswith("kgmicrobe.assay:")
            or not rule["evidence_uri"]
            or any(character in rule["reason"] for character in "\t\r\n")
            or any(
                not uri.startswith("https://") or any(c.isspace() for c in uri)
                for uri in rule["evidence_uri"].split("|")
            )
            or rule["correction_id"] in seen_ids
            or identity in seen_rows
            or rule["pseudo_CURIE"] in seen_assays
        ):
            raise ValueError("Invalid or duplicate EC substrate correction rule")
        seen_ids.add(rule["correction_id"])
        seen_rows.add(identity)
        seen_assays.add(rule["pseudo_CURIE"])
        policies.append(rule)
    if not policies:
        raise ValueError("Empty EC substrate correction policy")
    return policies


def _edge(row, knowledge_source):
    """Describe the exact existing emitter's scientific/provenance fields for a source claim."""
    return {
        SUBJECT_COLUMN: row["EC_ID"].strip(),
        PREDICATE_COLUMN: ENZYME_TO_SUBSTRATE_EDGE,
        OBJECT_COLUMN: row["CHEBI_ID"].strip(),
        RELATION_COLUMN: HAS_INPUT_RELATION,
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: knowledge_source,
        KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
        AGENT_TYPE_COLUMN: MANUAL_AGENT,
    }


def _json(value):
    """Encode complete original cells reversibly inside a literal TSV cell."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def apply_corrections(source_rows, policies, *, knowledge_source):
    """Correct only complete reviewed rows; known-scope drift requires a new review."""
    corrected, audit = [], []
    for line_number, row in source_rows:
        selected, known_scope = [], False
        for rule in policies:
            # These anchors identify a potential reviewed claim, never authorize
            # its correction. Blanking one identity/record cell cannot evade the
            # complete-row comparison. Unrelated uses of the old ChEBI ID stay put.
            candidate = row.get("pseudo_CURIE") == rule["pseudo_CURIE"] or (
                row.get("CHEBI_ID") == rule["CHEBI_ID"]
                and (row.get("EC_ID") == rule["EC_ID"] or row.get("CAS_RN_ID") == rule["CAS_RN_ID"])
            )
            known_scope = known_scope or candidate
            original = {key: rule[key] for key in SOURCE_FIELDS}
            target_corrected = {**original, "CHEBI_ID": rule["corrected_chebi_id"]}
            expected = dict(target_corrected)
            if rule["withheld_source_fields"]:
                expected[rule["withheld_source_fields"]] = ""
            if row in (original, target_corrected, expected):
                selected.append((rule, expected))
        if not selected:
            if known_scope:
                raise ValueError(f"Reviewed EC substrate scope changed at line {line_number}; review required")
            corrected.append(dict(row))
            continue
        if len(selected) != 1:
            raise ValueError(f"Ambiguous EC substrate correction at line {line_number}")
        rule, expected = selected[0]
        status = "already_corrected" if row == expected else "corrected"
        corrected.append(expected)
        audit.append(
            {
                "correction_id": rule["correction_id"],
                "status": status,
                "source_line": str(line_number),
                "source_row_json": _json(row),
                "original_edge_json": _json(_edge(row, knowledge_source)),
                "emitted_edge_json": _json(_edge(expected, knowledge_source)),
                "withheld_source_fields": rule["withheld_source_fields"],
                "reason": rule["reason"],
                "evidence_uri": rule["evidence_uri"],
            }
        )
    return corrected, audit


def prepare_corrections(transform, legacy_path, *, policy_path=POLICY_PATH):
    """Bind actual policy/source reads before opening graph outputs, retaining the original admission."""
    admission = SourceAdmission()
    admission.capture(policy_path)
    admission.capture(legacy_path)
    with transform.consume_input(REQUIRED_INPUTS[0], policy_path) as policy_stream:
        policies = load_policy(policy_stream)
    with transform.consume_input(REQUIRED_INPUTS[1], legacy_path) as source_stream:
        rows, audit = apply_corrections(_rows(source_stream), policies, knowledge_source=transform.knowledge_source)
    snapshots = transform.consumed_input_snapshots
    for entry in audit:
        entry.update(
            {
                "source_file": snapshots[REQUIRED_INPUTS[1]]["path"],
                "source_sha256": snapshots[REQUIRED_INPUTS[1]]["sha256"],
                "policy_file": snapshots[REQUIRED_INPUTS[0]]["path"],
                "policy_sha256": snapshots[REQUIRED_INPUTS[0]]["sha256"],
            }
        )
    admission.verify()
    transform.verify_consumed_inputs()
    return rows, audit, admission
