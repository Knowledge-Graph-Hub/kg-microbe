"""Audit six reviewed historical cross-references without restoring or remapping graph assertions."""

import json
import re
from pathlib import Path

from kg_microbe.transform_utils.rhea_mappings.native_rdf import LABEL, RDFS, RH

DATA_INPUTS = ("mappings/rhea_legacy_xref_dispositions.json",)
POLICY_PATH = Path(__file__).resolve().parents[3] / DATA_INPUTS[0]
INPUT_ROLE = "rhea_legacy_xref_dispositions"
REQUIRED_INPUTS = (INPUT_ROLE,)
AUDIT_FILE = "rhea_legacy_xref_dispositions.tsv"
REQUIRED_AUDIT_FILES = (AUDIT_FILE,)
DISPOSITION = "legacy_only_selected_snapshot_exclusion"
RUNTIME_SCOPE = "selected_indexed_labels_statuses_xrefs_variant_roles; historical_explanations_not_revalidated"
# Prevent an explicit no-prior-history contract from waiving this
# reviewed production cohort, even if only one of its identity fields changes.
REVIEWED_SNAPSHOT_ID = "rhea-cache-142-20260907"
REVIEWED_RDF_SHA256 = "8ee48d7044cf3eef1001fa730dae2a491902ab25b259b519d6826796bb8acedf"
AUDIT_HEADER = (
    "subject",
    "native_predicate",
    "original_object",
    "legacy_normalized_object",
    "legacy_locator",
    "legacy_line",
    "legacy_input_sha256",
    "disposition",
    "reason",
    "historical_snapshot_id",
    "historical_rdf_sha256",
    "historical_rdf_bytes",
    "selected_snapshot_id",
    "selected_rdf_sha256",
    "selected_rdf_bytes",
    "policy_sha256",
    "historical_label",
    "historical_context",
    "selected_context",
    "validated_native_assertions",
    "normalization_evidence",
    "runtime_validation_scope",
)
_SUBJECTS = {"RHEA:15929", "RHEA:19441", "RHEA:22140", "RHEA:28338", "RHEA:47152", "RHEA:58872"}
_REASONS = {
    "reaction_definition_and_annotation_changed",
    "subreaction_annotation_removed",
    "more_specific_native_annotation",
    "different_activity_annotation",
}
_ROOT_FIELDS = {
    "schema_version",
    "expected_count",
    "scope_note",
    "historical_snapshot",
    "selected_snapshot",
    "legacy_sources",
    "exclusions",
    "preserved_directional_go_annotations",
}
_EXCLUSION_FIELDS = {
    "subject",
    "native_predicate",
    "original_object",
    "normalized_object",
    "legacy_locator",
    "legacy_line",
    "reason",
    "historical_label",
    "historical_context",
    "selected_context",
    "required_native_assertions",
    "normalization_evidence",
}
_NORMALIZATION_FIELDS = {
    "authority_locator",
    "authority_sha256",
    "predicate",
    "audit_locator",
    "audit_sha256",
    "audit_line",
}


def _keys(value, expected, description):
    """Require the finite reviewed object shape, including rejection of unknown fields."""
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"Unsupported Rhea legacy {description} fields")


def _text(value, description):
    """Require explicit scalar text that remains a single TSV field without implicit coercion."""
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\t\r\n"):
        raise ValueError(f"Invalid Rhea legacy {description}")


def _hash(value):
    """Reject incomplete or malformed byte identities."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid Rhea legacy SHA-256")


def _positive_integer(value, description):
    """Reject booleans and nonpositive lengths or source line numbers."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"Invalid Rhea legacy {description}")


def _identity(value):
    """Validate a complete byte identity without selecting any filesystem path."""
    _keys(value, {"sha256", "bytes"}, "identity")
    _hash(value["sha256"])
    _positive_integer(value["bytes"], "byte count")


def _rhea(value):
    """Accept only explicit canonical numeric reaction identifiers."""
    if not isinstance(value, str) or re.fullmatch(r"RHEA:[1-9][0-9]*", value) is None:
        raise ValueError("Invalid Rhea legacy reaction identifier")


def _target(identifier, predicate):
    """Expand exact EC/GO target spellings without a resolver or replacement inference."""
    if isinstance(identifier, str):
        if predicate == RDFS + "seeAlso" and re.fullmatch(r"GO:[0-9]{7}", identifier):
            return "http://purl.obolibrary.org/obo/" + identifier.replace(":", "_")
        if predicate == RH + "ec" and re.fullmatch(r"EC:[0-9]+(?:\.(?:[0-9]+|n[0-9]+|-)){3}", identifier):
            return "http://purl.uniprot.org/enzyme/" + identifier[3:]
    raise ValueError("Unsupported Rhea legacy cross-reference predicate or target")


def _unique_json_keys(pairs):
    """Reject duplicate JSON fields, even when the last occurrence has a valid value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate Rhea legacy policy key: {key}")
        result[key] = value
    return result


def _assertions(values, subject):
    """Validate finite selected context and require the focal reaction label and status."""
    if not isinstance(values, list) or not values:
        raise ValueError("Missing Rhea legacy selected context")
    seen = set()
    for assertion in values:
        _keys(assertion, {"subject", "predicate", "value"}, "assertion")
        _rhea(assertion["subject"])
        predicate, value = assertion["predicate"], assertion["value"]
        _text(value, "assertion value")
        if predicate == RH + "status":
            if value != RH + "Approved":
                raise ValueError("Unsupported Rhea legacy context status")
        elif predicate == RDFS + "seeAlso":
            if re.fullmatch(r"http://purl\.obolibrary\.org/obo/GO_[0-9]{7}", value) is None:
                raise ValueError("Unsupported Rhea legacy context GO resource")
        elif predicate == RH + "ec":
            prefix = "http://purl.uniprot.org/enzyme/"
            if not value.startswith(prefix) or _target("EC:" + value[len(prefix) :], predicate) != value:
                raise ValueError("Unsupported Rhea legacy context EC resource")
        elif predicate != LABEL:
            raise ValueError("Unsupported Rhea legacy context predicate")
        key = (assertion["subject"], predicate, value)
        if key in seen:
            raise ValueError("Duplicate Rhea legacy selected assertion")
        seen.add(key)
    for predicate in (LABEL, RH + "status"):
        if sum(s == subject and p == predicate for s, p, _ in seen) != 1:
            raise ValueError("Missing or ambiguous focal Rhea legacy context")
    if not any(p in {RH + "ec", RDFS + "seeAlso"} for _, p, _ in seen):
        raise ValueError("Missing explicit selected Rhea cross-reference context")


def read_legacy_policy(stream):
    """Parse six reviewed exclusions or explicit absent history, never a general remapping language."""
    policy = json.load(stream, object_pairs_hook=_unique_json_keys)
    _keys(policy, _ROOT_FIELDS, "policy")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported Rhea legacy policy schema")
    if type(policy["expected_count"]) is not int or policy["expected_count"] not in {0, 6}:
        raise ValueError("Unsupported Rhea legacy expected count")
    _text(policy["scope_note"], "scope note")
    selected = policy["selected_snapshot"]
    _keys(selected, {"snapshot_id", "rdf"}, "snapshot")
    _text(selected["snapshot_id"], "snapshot identifier")
    _identity(selected["rdf"])
    if policy["expected_count"] == 0:
        if (
            selected["snapshot_id"] == REVIEWED_SNAPSHOT_ID
            or selected["rdf"]["sha256"] == REVIEWED_RDF_SHA256
            or policy["historical_snapshot"] is not None
            or policy["legacy_sources"] != {}
            or policy["exclusions"] != []
            or policy["preserved_directional_go_annotations"] != []
        ):
            raise ValueError(
                "Empty Rhea legacy history requires a different snapshot with no declared historical cohort"
            )
        return policy
    for key in ("historical_snapshot", "selected_snapshot"):
        _keys(policy[key], {"snapshot_id", "rdf"}, "snapshot")
        _text(policy[key]["snapshot_id"], "snapshot identifier")
        _identity(policy[key]["rdf"])
    sources = policy["legacy_sources"]
    _keys(sources, {"data/raw/rhea2ec.tsv", "data/raw/rhea2go.tsv"}, "source locators")
    for identity in sources.values():
        _identity(identity)
    exclusions = policy["exclusions"]
    if not isinstance(exclusions, list) or len(exclusions) != 6:
        raise ValueError("Rhea legacy policy requires exactly six exclusions")
    subjects = set()
    for row in exclusions:
        _keys(row, _EXCLUSION_FIELDS, "exclusion")
        _rhea(row["subject"])
        if row["subject"] not in _SUBJECTS or row["subject"] in subjects:
            raise ValueError("Unknown or duplicate Rhea legacy exclusion subject")
        subjects.add(row["subject"])
        for key in ("original_object", "normalized_object"):
            _target(row[key], row["native_predicate"])
        expected_locator = "data/raw/rhea2ec.tsv" if row["native_predicate"] == RH + "ec" else "data/raw/rhea2go.tsv"
        _text(row["reason"], "reason")
        if row["legacy_locator"] != expected_locator or row["reason"] not in _REASONS:
            raise ValueError("Unsupported Rhea legacy locator or reason")
        _positive_integer(row["legacy_line"], "source line")
        for key in ("historical_label", "historical_context", "selected_context"):
            _text(row[key], key)
        _assertions(row["required_native_assertions"], row["subject"])
        normalization = row["normalization_evidence"]
        if row["original_object"] == row["normalized_object"]:
            if normalization is not None:
                raise ValueError("Unexpected Rhea legacy normalization evidence")
        else:
            _keys(normalization, _NORMALIZATION_FIELDS, "normalization evidence")
            if (
                row["native_predicate"] != RDFS + "seeAlso"
                or normalization["predicate"] != "IAO:0100001"
                or normalization["authority_locator"] != "data/raw/go.db"
                or normalization["audit_locator"] != "data/transformed/rhea_mappings/go_reference_resolution.tsv"
            ):
                raise ValueError("Unsupported Rhea legacy GO normalization evidence")
            _hash(normalization["authority_sha256"])
            _hash(normalization["audit_sha256"])
            _positive_integer(normalization["audit_line"], "audit line")
    variants = policy["preserved_directional_go_annotations"]
    if not isinstance(variants, list) or len(variants) != 7:
        raise ValueError("Rhea legacy policy must preserve seven variant GO annotations")
    variant_subjects = set()
    for variant in variants:
        _keys(variant, {"subject", "master", "direction", "object"}, "directional annotation")
        _rhea(variant["subject"])
        _rhea(variant["master"])
        _text(variant["direction"], "direction")
        if (
            variant["subject"] == variant["master"]
            or variant["subject"] in variant_subjects
            or variant["direction"] not in {"LR", "RL"}
        ):
            raise ValueError("Invalid or duplicate Rhea legacy directional annotation")
        variant_subjects.add(variant["subject"])
        _target(variant["object"], RDFS + "seeAlso")
    return policy


def _require(native, subject, predicate, value):
    """Check exact indexed native assertions, never deriving them from historical prose."""
    values = native.reactions.get(subject, {}).get(predicate, ())
    if not isinstance(values, (tuple, list, set, frozenset)) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"Malformed native Rhea context for {subject}")
    if value not in values or (predicate in {LABEL, RH + "status"} and set(values) != {value}):
        raise ValueError(f"Selected native Rhea context changed: {subject} {predicate} {value}")


def _require_variant_direction(native, variant):
    """Align the recorded LR/RL annotation with exact native master-side roles, not ID arithmetic."""
    master = RH + variant["master"][5:]
    left, right = master + "_L", master + "_R"
    substrates, products = (left, right) if variant["direction"] == "LR" else (right, left)
    expected = {"substrates": {substrates}, "products": {products}, "side": set(), "substratesOrProducts": set()}
    for role, targets in expected.items():
        values = native.reactions[variant["subject"]].get(RH + role, ())
        if (
            not isinstance(values, (tuple, list, set, frozenset))
            or not all(isinstance(value, str) for value in values)
            or set(values) != targets
        ):
            raise ValueError(f"Selected native Rhea direction context changed: {variant['subject']} {role}")


def load_legacy_xref_audit(transform, release_policy, native, *, policy_path=POLICY_PATH):
    """
    Consume the policy and return its zero or six scalar audit rows before publication.

    The caller must already have loaded the native RDF through load_pinned_inputs.
    This checks that consumed RDF digest and selected release contract agree with
    this policy; it does not read historical RDF/tables, transform native records,
    rewrite references, or claim to revalidate comments or GO subclass evidence.
    Write all returned rows atomically with AUDIT_HEADER and record_producer_audit
    only after success; declare this module's required input/audit/data constants.
    """
    with transform.consume_input(INPUT_ROLE, policy_path) as stream:
        policy = read_legacy_policy(stream)
        selected, historical = policy["selected_snapshot"], policy["historical_snapshot"]
        consumed = transform.consumed_input_snapshots
        if (
            release_policy.get("snapshot_id") != selected["snapshot_id"]
            or release_policy.get("files", {}).get("rhea.rdf.gz", {}).get("sha256") != selected["rdf"]["sha256"]
            or release_policy.get("files", {}).get("rhea.rdf.gz", {}).get("bytes") != selected["rdf"]["bytes"]
            or consumed.get("rhea_rdf", {}).get("sha256") != selected["rdf"]["sha256"]
            or getattr(transform, "_consumed_input_error", None) is not None
        ):
            raise ValueError("Rhea legacy policy does not match the consumed selected snapshot")
        for variant in policy["preserved_directional_go_annotations"]:
            _require(native, variant["subject"], RH + "status", RH + "Approved")
            _require(native, variant["subject"], RDFS + "seeAlso", _target(variant["object"], RDFS + "seeAlso"))
            _require(native, variant["master"], RH + "directionalReaction", RH + variant["subject"][5:])
            _require_variant_direction(native, variant)
        audit = []
        for row in policy["exclusions"]:
            for assertion in row["required_native_assertions"]:
                _require(native, assertion["subject"], assertion["predicate"], assertion["value"])
            current = native.reactions[row["subject"]].get(row["native_predicate"], ())
            for identifier in {row["original_object"], row["normalized_object"]}:
                if _target(identifier, row["native_predicate"]) in current:
                    raise ValueError(
                        f"Legacy Rhea assertion is present in selected native data: {row['subject']} {identifier}"
                    )
            audit.append(
                {
                    "subject": row["subject"],
                    "native_predicate": row["native_predicate"],
                    "original_object": row["original_object"],
                    "legacy_normalized_object": row["normalized_object"],
                    "legacy_locator": row["legacy_locator"],
                    "legacy_line": str(row["legacy_line"]),
                    "legacy_input_sha256": policy["legacy_sources"][row["legacy_locator"]]["sha256"],
                    "disposition": DISPOSITION,
                    "reason": row["reason"],
                    "historical_snapshot_id": historical["snapshot_id"],
                    "historical_rdf_sha256": historical["rdf"]["sha256"],
                    "historical_rdf_bytes": str(historical["rdf"]["bytes"]),
                    "selected_snapshot_id": selected["snapshot_id"],
                    "selected_rdf_sha256": selected["rdf"]["sha256"],
                    "selected_rdf_bytes": str(selected["rdf"]["bytes"]),
                    "policy_sha256": consumed[INPUT_ROLE]["sha256"],
                    "historical_label": row["historical_label"],
                    "historical_context": row["historical_context"],
                    "selected_context": row["selected_context"],
                    "validated_native_assertions": json.dumps(
                        row["required_native_assertions"], sort_keys=True, separators=(",", ":")
                    ),
                    "normalization_evidence": json.dumps(
                        row["normalization_evidence"], sort_keys=True, separators=(",", ":")
                    ),
                    "runtime_validation_scope": RUNTIME_SCOPE,
                }
            )
        return tuple(audit)
