"""Retain four finite native clinical classifications without inventing external site identity."""

import csv
import hashlib
import json
import re
from pathlib import Path

from kg_microbe.transform_utils.bacdive import isolation_categories
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    ATTRIBUTE_CATEGORY,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    ISOLATION_SAMPLING_ENV_INFO,
    ISOLATION_SOURCE_CATEGORIES,
    KNOWLEDGE_LEVEL_COLUMN,
    LOCATION_OF,
    MANUAL_AGENT,
    NCBI_TO_ISOLATION_SOURCE_EDGE,
    OBJECT_COLUMN,
    OBSERVATION,
    ONTOLOGY_CLASS_CATEGORY,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
    TRANSLATION_TABLE_FOR_IDS,
)
from kg_microbe.utils.clinical_mesh_categories import (
    CLINICAL_MESH_POLICY_FILE,
    load_clinical_mesh_evidence,
    load_clinical_mesh_policy,
)
from kg_microbe.utils.isolation_source_mapping_utils import normalize_isolation_source_label

POLICY_RELATIVE = "mappings/bacdive_clinical_mesh_policy.json"
REQUIRED_INPUTS = ("bacdive_clinical_mesh_policy", "bacdive_clinical_mesh_native")
AUDIT_FILE = "clinical_isolation_category_dispositions.tsv"
AUDIT_FIELDS = (
    "status",
    "organism_id",
    "source_path_json",
    "source_category_json",
    "source_isolation_json",
    "raw_value",
    "original_mapping_json",
    "original_edge_json",
    "emitted_edge_json",
    "attribute_id",
    "attribute_type",
    "site_category",
    "reason",
    "native_evidence_json",
    "consumed_inputs_json",
)


def _json(value):
    """Encode literal context reversibly and without TSV-delimiter ambiguity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def prepare_policy(transform, *, policy_path=CLINICAL_MESH_POLICY_FILE, native_path=None):
    """Require actual native evidence and exact admitted mappings before opening graph outputs."""
    with transform.consume_input(REQUIRED_INPUTS[0], policy_path) as stream:
        policy = load_clinical_mesh_policy(stream)
    native_path = native_path or Path(transform.input_base_dir) / policy["native_file"]
    with transform.consume_input(REQUIRED_INPUTS[1], native_path) as stream:
        transform._clinical_mesh_evidence = load_clinical_mesh_evidence(policy, stream)
    mapping_role = isolation_categories.REQUIRED_INPUTS[1]
    mapping_path = transform.consumed_input_snapshots[mapping_role]["path"]
    with transform.consume_input(mapping_role, mapping_path) as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for rule in policy["rules"]:
        original = rule["original_mapping"]
        selected = [
            row
            for row in rows
            if normalize_isolation_source_label(row["subject_label_normalized"] or row["subject_label"])
            == original["subject_label_normalized"]
        ]
        if len(selected) != 1:
            raise ValueError("Clinical isolation mapping missing or duplicated")
        identity_fields = ("object_id", "object_label", "object_source", "predicate_id")
        if rule["action"] == "retain_unresolved_source_category":
            if any(selected[0][key] for key in identity_fields):
                raise ValueError("Unresolved clinical isolation identity reintroduced")
        elif any(selected[0][key] != original[key] for key in identity_fields):
            raise ValueError("Reviewed clinical isolation site identity changed")
    return policy


def emit_occurrence(
    transform,
    category_index,
    category,
    field,
    value,
    *,
    isolation,
    organism_id,
    native_record_id,
    node_writer,
    edge_writer,
    audit_writer,
    policy,
):
    """Intercept exactly one original raw leaf; never mutate its group or PRIDE coordinates."""
    rules = {rule["category"][rule["field"]]: rule for rule in policy["rules"]}
    scope = {rule["original_mapping"]["subject_label_normalized"] for rule in policy["rules"]}
    if not isinstance(value, str):
        return False
    rule = rules.get(value)
    normalized = normalize_isolation_source_label(value.lstrip("#"))
    sanitized = normalize_isolation_source_label(value.strip().translate(str.maketrans(TRANSLATION_TABLE_FOR_IDS)))
    if rule is None and normalized not in scope and sanitized not in scope:
        return False
    if rule is None or field != rule["field"] or category != rule["category"]:
        raise ValueError("Reviewed clinical isolation source path/value changed; review required")
    if (
        isinstance(native_record_id, bool)
        or not isinstance(native_record_id, (int, str))
        or not re.fullmatch(r"[1-9][0-9]*", str(native_record_id))
        or organism_id != f"kgmicrobe.strain:bacdive_{native_record_id}"
    ):
        raise ValueError("Clinical isolation observation requires a BacDive record identity")
    source_path = [ISOLATION_SAMPLING_ENV_INFO, ISOLATION_SOURCE_CATEGORIES]
    if category_index is not None:
        source_path.append(category_index)
    source_path.append(field)
    witness = {"organism_id": organism_id, "source_path": source_path, "category": category}
    common = {
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: transform.knowledge_source,
        KNOWLEDGE_LEVEL_COLUMN: OBSERVATION,
        AGENT_TYPE_COLUMN: MANUAL_AGENT,
        PUBLICATIONS_COLUMN: f"https://bacdive.dsmz.de/strain/{native_record_id}",
    }
    original = {
        **common,
        SUBJECT_COLUMN: rule["original_mapping"]["object_id"],
        PREDICATE_COLUMN: NCBI_TO_ISOLATION_SOURCE_EDGE,
        OBJECT_COLUMN: organism_id,
        RELATION_COLUMN: LOCATION_OF,
    }
    identifier, attribute_type = "", ""
    if rule["action"] == "retain_source_site":
        emitted = original.copy()
    else:
        identifier = "kgmicrobe.isolation_category:" + hashlib.sha256(_json(witness).encode()).hexdigest()
        attribute_type = isolation_categories.ATTRIBUTE_TYPE
        if not transform._isolation_category_type_emitted:
            node_writer.writerow(
                transform._create_node_row(
                    attribute_type,
                    ONTOLOGY_CLASS_CATEGORY,
                    "BacDive isolation source category field",
                    description="Local source-schema type for BacDive isolation source category observations; "
                    "not an external ontology identity or a physical site class.",
                )
            )
            transform._isolation_category_type_emitted = True
        node = transform._create_node_row(
            identifier,
            ATTRIBUTE_CATEGORY,
            f"BacDive isolation source category: {value[1:]}",
            description="Record-scoped source classification; external identity unresolved, "
            "not an inferred clinical fact or physical site. " + _json(witness),
        )
        node[transform.node_header.index(HAS_ATTRIBUTE_TYPE_COLUMN)] = attribute_type
        node_writer.writerow(node)
        emitted = {
            **common,
            SUBJECT_COLUMN: organism_id,
            PREDICATE_COLUMN: HAS_ATTRIBUTE_PREDICATE,
            OBJECT_COLUMN: identifier,
            RELATION_COLUMN: HAS_ATTRIBUTE_RELATION,
        }
    edge_writer.writerow([emitted.get(column, "") for column in transform.edge_header])
    audit = {
        "status": rule["action"],
        "organism_id": organism_id,
        "source_path_json": _json(source_path),
        "source_category_json": _json(category),
        "source_isolation_json": _json(isolation),
        "raw_value": value,
        "original_mapping_json": _json(rule["original_mapping"]),
        "original_edge_json": _json(original),
        "emitted_edge_json": _json(emitted),
        "attribute_id": identifier,
        "attribute_type": attribute_type,
        "site_category": rule["projection"] or "",
        "reason": rule["reason"],
        "native_evidence_json": _json(
            {
                "url": policy["native_url"],
                "namespace": policy["native_namespace"],
                "selected_statements_sha256": policy["selected_native_statements_sha256"],
                "selected_statement_count": policy["selected_native_statement_count"],
                "concept": rule["concept"],
                "scope": "complete selected descriptor/preferred-concept records, not full-file digest",
            }
        ),
        "consumed_inputs_json": _json(
            {
                role: transform.consumed_input_snapshots[role]
                for role in (*REQUIRED_INPUTS, *isolation_categories.REQUIRED_INPUTS, isolation_categories.RAW_INPUT)
            }
        ),
    }
    audit_writer.writerow([audit[column] for column in AUDIT_FIELDS])
    return True
