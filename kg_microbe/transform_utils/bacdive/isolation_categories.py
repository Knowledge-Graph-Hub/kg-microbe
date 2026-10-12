"""Retain reviewed BacDive headings and Agriculture context without false site identity."""

import csv
import hashlib
import json
import re
from pathlib import Path

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
from kg_microbe.utils.isolation_source_mapping_utils import (
    load_isolation_source_mappings,
    normalize_isolation_source_label,
)

POLICY_RELATIVE = "mappings/bacdive_isolation_category_policy.json"
MAPPING_RELATIVE = "mappings/isolation_source_to_ontology.tsv"
ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / POLICY_RELATIVE
MAPPING_PATH = ROOT / MAPPING_RELATIVE
REQUIRED_INPUTS = ("bacdive_isolation_category_policy", "bacdive_isolation_category_mapping")
RAW_INPUT = "bacdive_isolation_category_source"
AUDIT_FILE = "isolation_category_identity_dispositions.tsv"
ATTRIBUTE_TYPE = "kgmicrobe.attribute_type:bacdive_isolation_source_category"
AUDIT_FIELDS = (
    "status",
    "organism_id",
    "source_path_json",
    "source_category_json",
    "source_isolation_json",
    "source_record_json",
    "raw_value",
    "attribute_id",
    "attribute_type",
    "rejected_mapping_json",
    "original_edge_json",
    "emitted_edge_json",
    "reason",
    "native_authority_url",
    "native_authority_sha256",
    "consumed_inputs_json",
)
_EXPECTED = {"#Host Body Product": "PRIDE:0000686", "#Host Body-Site": "PRIDE:0000685", "#Agriculture": "ENVO:01001442"}
# Independently verified against the complete immutable primary file. Native
# excerpt bytes and their claimed full-file identity must advance together in a
# reviewed code/policy change, never by restamping a digest in the JSON alone.
NATIVE_COMMIT = "342b05f38fad5d9b680ef7af80ebf3ff5fa15ace"
NATIVE_FILE_SHA256 = "11a3d2ad9bf36221b3329b4d9abd633f1f4dcd9be79d1a800ab45e0d3bff4001"
NATIVE_STANZAS_SHA256 = "bfae047d8b3783e2be0ddc946de94efd74661e50d2c296f7452a3506d585b2ca"
AGRICULTURE_RULE_SHA256 = "53ba098b1496dd27e847e3d688619a43b81ac4817450bc66a7f3ae463110a5c7"


def _json(value):
    """Preserve arbitrary literal source strings reversibly in a single TSV field."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _unique_object(pairs):
    """Reject duplicate JSON keys rather than silently accepting the last rule."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate isolation-category policy key")
        result[key] = value
    return result


def load_policy(stream):
    """Require the exact finite reviewed scope and immutable primary authority locator."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    authority = policy.get("native_authority", {})
    rules = policy.get("rules", [])
    commit = authority.get("commit", "")
    if (
        policy.get("version") != 1
        or policy.get("disposition") != "retain_record_scoped_source_category_attribute"
        or not policy.get("reason")
        or commit != NATIVE_COMMIT
        or authority.get("url")
        != f"https://raw.githubusercontent.com/PRIDE-Archive/pride-ontology/{commit}/pride_cv.obo"
        or authority.get("sha256") != NATIVE_FILE_SHA256
        or hashlib.sha256(_json(authority.get("stanzas")).encode()).hexdigest() != NATIVE_STANZAS_SHA256
        or len(rules) != 3
        or {rule.get("raw_value") for rule in rules} != set(_EXPECTED)
    ):
        raise ValueError("Invalid isolation-category policy or native authority pin")
    for rule in rules:
        original = rule.get("rejected_mapping", {})
        target = _EXPECTED[rule["raw_value"]]
        if rule["raw_value"] == "#Agriculture":
            if hashlib.sha256(_json(rule).encode()).hexdigest() != AGRICULTURE_RULE_SHA256:
                raise ValueError("Agriculture source-category policy or native authority changed")
            continue
        stanza = authority.get("stanzas", {}).get(target, "")
        if (
            rule.get("raw_field") != "Cat1"
            or original.get("object_id") != target
            or original.get("subject_label_normalized") != normalize_isolation_source_label(rule["raw_value"][1:])
            or original.get("predicate_id") != "skos:exactMatch"
            or original.get("source_dataset") != "bacdive"
            or f"\nid: {target}\n" not in stanza
            or "\nis_a: NCIT:C12219 ! Anatomic Structure, System, or Substance\n" not in stanza
            or "\nis_a: PRIDE:0000674 ! Human gut\n" not in stanza
        ):
            raise ValueError("Isolation-category policy scope or native witness changed")
    return policy


def prepare_policy(transform, *, policy_path=POLICY_PATH, mapping_path=MAPPING_PATH):
    """Bind actual policy/mapping reads and reject reintroduced external identities before output."""
    with transform.consume_input(REQUIRED_INPUTS[0], policy_path) as stream:
        policy = load_policy(stream)
    with transform.consume_input(REQUIRED_INPUTS[1], mapping_path) as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        expected_fields = set(policy["rules"][0]["rejected_mapping"])
        if (
            not reader.fieldnames
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
            or set(reader.fieldnames) != expected_fields
        ):
            raise ValueError("Invalid isolation-source mapping header")
        rows = list(reader)
        if any(set(row) != expected_fields or any(value is None for value in row.values()) for row in rows):
            raise ValueError("Invalid isolation-source mapping row shape")
        # The constructor can precede this run or a mapping-table edit. Always
        # build the runtime lookup from these exact admitted bytes, not an older
        # dictionary whose values the current receipt cannot justify.
        current_mappings = load_isolation_source_mappings(Path(stream.name))
    for rule in policy["rules"]:
        original = rule["rejected_mapping"]
        selected = [
            row
            for row in rows
            if normalize_isolation_source_label(row["subject_label_normalized"] or row["subject_label"])
            == original["subject_label_normalized"]
        ]
        if len(selected) != 1 or any(
            selected[0].get(key) for key in ("object_id", "object_label", "object_source", "predicate_id")
        ):
            raise ValueError("Reviewed isolation-category identity reintroduced or mapping scope changed")
    transform.isolation_source_mappings = current_mappings
    if HAS_ATTRIBUTE_TYPE_COLUMN not in transform.node_header:
        transform.node_header.append(HAS_ATTRIBUTE_TYPE_COLUMN)
    transform._isolation_category_type_emitted = False
    return policy


def emit_category_attributes(
    transform,
    categories,
    isolation,
    organism_id,
    node_writer,
    edge_writer,
    audit_writer,
    policy,
    *,
    native_record_id,
    native_record=None,
    clinical_handler=None,
):
    """Emit each reviewed raw occurrence as an attribute and return every other literal value unchanged."""
    if isinstance(categories, dict):
        entries = [(None, categories)]
    elif isinstance(categories, list):
        entries = list(enumerate(categories))
    elif categories is None:
        return []
    else:
        raise ValueError("Isolation-source category container is not an object or list")
    remaining = []
    rules = {rule["raw_value"]: rule for rule in policy["rules"]}
    scope = {normalize_isolation_source_label(value[1:]) for value in rules}
    for index, category in entries:
        if not isinstance(category, dict):
            raise ValueError("Isolation-source category entry is not an object")
        for field, value in category.items():
            if clinical_handler is not None and clinical_handler(index, category, field, value):
                continue
            rule = rules.get(value) if isinstance(value, str) else None
            normalized = normalize_isolation_source_label(value.lstrip("#")) if isinstance(value, str) else ""
            sanitized = (
                normalize_isolation_source_label(value.strip().translate(str.maketrans(TRANSLATION_TABLE_FOR_IDS)))
                if isinstance(value, str)
                else ""
            )
            if (normalized in scope or sanitized in scope) and (
                rule is None
                or field != rule["raw_field"]
                or any(category.get(key) != expected for key, expected in rule.get("required_context", {}).items())
            ):
                raise ValueError("Reviewed isolation-category source field/value changed; review required")
            if rule is None:
                remaining.append(value)
                continue
            if (
                isinstance(native_record_id, bool)
                or not isinstance(native_record_id, (int, str))
                or not re.fullmatch(r"[1-9][0-9]*", str(native_record_id))
                or organism_id != f"kgmicrobe.strain:bacdive_{native_record_id}"
            ):
                raise ValueError("Isolation-category observation requires a BacDive record identity")
            source_path = [ISOLATION_SAMPLING_ENV_INFO, ISOLATION_SOURCE_CATEGORIES]
            if index is not None:
                source_path.append(index)
            source_path.append(field)
            witness = {"organism_id": organism_id, "source_path": source_path, "category": category}
            agriculture = value == "#Agriculture"
            if agriculture and (
                not isinstance(native_record, dict)
                or native_record.get("General", {}).get("BacDive-ID") != native_record_id
            ):
                raise ValueError("Agriculture observation requires its complete native source record")
            identifier = "kgmicrobe.isolation_category:" + hashlib.sha256(_json(witness).encode()).hexdigest()
            if not transform._isolation_category_type_emitted:
                node_writer.writerow(
                    transform._create_node_row(
                        ATTRIBUTE_TYPE,
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
                description="Record-scoped source classification, not an ontology identity or physical site. "
                + _json(witness),
            )
            node[transform.node_header.index(HAS_ATTRIBUTE_TYPE_COLUMN)] = ATTRIBUTE_TYPE
            node_writer.writerow(node)
            common = {
                PRIMARY_KNOWLEDGE_SOURCE_COLUMN: transform.knowledge_source,
                KNOWLEDGE_LEVEL_COLUMN: OBSERVATION,
                AGENT_TYPE_COLUMN: MANUAL_AGENT,
                PUBLICATIONS_COLUMN: "https://bacdive.dsmz.de/strain/" + organism_id.rsplit("_", 1)[1],
            }
            emitted = {
                **common,
                SUBJECT_COLUMN: organism_id,
                PREDICATE_COLUMN: HAS_ATTRIBUTE_PREDICATE,
                OBJECT_COLUMN: identifier,
                RELATION_COLUMN: HAS_ATTRIBUTE_RELATION,
            }
            edge_writer.writerow([emitted.get(column, "") for column in transform.edge_header])
            original = {
                **common,
                SUBJECT_COLUMN: rule["rejected_mapping"]["object_id"],
                PREDICATE_COLUMN: NCBI_TO_ISOLATION_SOURCE_EDGE,
                OBJECT_COLUMN: organism_id,
                RELATION_COLUMN: LOCATION_OF,
            }
            audit = {
                "status": "process_location_rejected_source_category_retained"
                if agriculture
                else "external_identity_rejected_source_category_retained",
                "organism_id": organism_id,
                "source_path_json": _json(source_path),
                "source_category_json": _json(category),
                "source_isolation_json": _json(isolation),
                "source_record_json": _json(native_record) if agriculture else "",
                "raw_value": value,
                "attribute_id": identifier,
                "attribute_type": ATTRIBUTE_TYPE,
                "rejected_mapping_json": _json(rule["rejected_mapping"]),
                "original_edge_json": _json(original),
                "emitted_edge_json": _json(emitted),
                "reason": rule.get("reason", policy["reason"]),
                "native_authority_url": rule.get("native_authority", policy["native_authority"])["url"],
                "native_authority_sha256": rule.get("native_authority", policy["native_authority"])["sha256"],
                "consumed_inputs_json": _json(
                    {role: transform.consumed_input_snapshots[role] for role in (*REQUIRED_INPUTS, RAW_INPUT)}
                ),
            }
            audit_writer.writerow([audit[column] for column in AUDIT_FIELDS])
    return remaining
