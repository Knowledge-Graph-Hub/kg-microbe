"""
Opt-in scalar projection of natively validated stable-source candidate assertions.

This module transports decisions; it does not validate MIM science or authorize
publication. The adapter must call native validation and bind its exact inputs.
The global legacy ingredient and biomedical MIM prefix maps remain unchanged.
"""

import hashlib
import re
from collections import Counter, defaultdict
from importlib.resources import files

import yaml

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    INGREDIENT_BUNDLE_SHA256,
    INGREDIENT_PROFILE_COLUMN,
    INGREDIENT_RECORD_KIND,
    KNOWLEDGE_LEVEL_COLUMN,
    MIM_KNOWLEDGE_SOURCE,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATED_TO_PREDICATE,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json

STABLE_PROFILE = "mimprofile:stable-source-kgx/v1"
STABLE_PREFIX = "https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_"
ASSERTION_JSON = "ingredient_assertion_json"
PREDICATES = frozenset({"skos:exactMatch", "skos:broadMatch", "skos:closeMatch", "skos:narrowMatch"})
_LANES = frozenset(
    {"source_identity", "source_decision", "external_mapping", "companion", "consumer_hold", "candidate_context"}
)
COMPANION_MODES = frozenset({"required/v1", "absent/v1"})


def stable_ingredient_kgx_profile():
    """Load the separate versioned numeric-ingredient profile without global registration."""
    profile = yaml.safe_load(files("kg_microbe").joinpath("profiles/stable_source_kgx_v1.yaml").read_text())
    if (
        profile["profile_id"] != STABLE_PROFILE
        or profile["profile_version"] != 1
        or profile["prefixes"]["MIM.ingredient"] != STABLE_PREFIX
        or profile["original_mim_prefix"] != STABLE_PREFIX
        or profile["mode"] != "candidate_only"
        or profile["production_authorized"] is not False
        or set(profile["companion_modes"]) != COMPANION_MODES
    ):
        raise ValueError("Unsupported stable ingredient profile")
    return profile


def stable_profile_sha256():
    """Bind current packaged profile bytes; no previous context can cache its identity."""
    raw = files("kg_microbe").joinpath("profiles/stable_source_kgx_v1.yaml").read_bytes()
    return hashlib.sha256(raw).hexdigest()


def stable_graph_id(identifier):
    """Spell only an explicit stable ingredient ID in the unambiguous graph namespace."""
    if not isinstance(identifier, str):
        raise ValueError("Expected a stable MIM ingredient identifier")
    value = identifier
    if value.startswith(STABLE_PREFIX):
        value = "MIM:" + value[len(STABLE_PREFIX) :]
    if value.startswith("MIM.ingredient:"):
        value = "MIM:" + value.split(":", 1)[1]
    if not re.fullmatch(r"MIM:[0-9]{7}", value) or value == "MIM:0000000":
        raise ValueError("Expected a positive seven-digit stable MIM ingredient identifier")
    return "MIM.ingredient:" + value.split(":", 1)[1]


def stable_identifier_uri(identifier):
    """Expand the opted-in ingredient identity without reinterpreting biomedical MIM."""
    return STABLE_PREFIX + stable_graph_id(identifier).split(":", 1)[1]


def _digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[^\s:|]+:[^\s|]+", value):
        raise ValueError("Missing or malformed assertion endpoint")
    if value.startswith(("MIM:", "MIM.ingredient:", STABLE_PREFIX)):
        return stable_graph_id(value)
    return value


def validate_stable_ingredient_fields(row, *, is_node):
    """Enforce the stable profile and lossless scalar envelopes at native TSV boundaries."""
    profile = stable_ingredient_kgx_profile()
    present = {key for key, value in row.items() if key.startswith("ingredient_") and value not in (None, "")}
    if row.get(INGREDIENT_PROFILE_COLUMN) != STABLE_PROFILE or present - profile["columns"].keys():
        raise ValueError("Unknown or unversioned stable ingredient extension")
    for key in present:
        if not isinstance(row[key], str):
            raise ValueError("Stable ingredient fields must remain scalar")
        record = profile["columns"][key].get("record")
        if record and record != ("node" if is_node else "edge"):
            raise ValueError("Stable ingredient field is on the wrong record")
    if not re.fullmatch(r"[a-f0-9]{64}", row.get(INGREDIENT_BUNDLE_SHA256, "")):
        raise ValueError("Stable ingredient assertion requires its source manifest fingerprint")
    if is_node:
        if row.get(INGREDIENT_RECORD_KIND) not in profile["record_kinds"]:
            raise ValueError("Unknown stable ingredient record kind")
        if row[INGREDIENT_RECORD_KIND] == "stable_concept":
            if stable_graph_id(row[ID_COLUMN]) != row[ID_COLUMN]:
                raise ValueError("Stable graph concept must use the explicit ingredient namespace")
        return
    raw = row.get(ASSERTION_JSON, "")
    envelope = read_json(raw.encode("utf-8"))
    if not isinstance(envelope, dict) or canonical_json(envelope).decode("utf-8") != raw:
        raise ValueError("Stable assertion must remain a canonical scalar JSON object")
    if envelope.get("lane") not in _LANES or not isinstance(envelope.get("payload"), dict):
        raise ValueError("Stable assertion requires an explicit lane and complete payload")
    if envelope["lane"] == "candidate_context":
        context = envelope["payload"]
        required = {
            "companion_mode",
            "status",
            "production_authorized",
            "source_manifest_sha256",
            "profile_sha256",
            "profile_id",
            "profile_version",
        }
        if (
            set(context) not in (required, required | {"selection_sha256"})
            or not isinstance(context["companion_mode"], str)
            or context["companion_mode"] not in COMPANION_MODES
            or context["status"] != "PRIVATE_NOT_KG_ACCEPTED"
            or context["production_authorized"] is not False
            or context["source_manifest_sha256"] != row[INGREDIENT_BUNDLE_SHA256]
            or context["profile_sha256"] != stable_profile_sha256()
            or context["profile_id"] != STABLE_PROFILE
            or type(context["profile_version"]) is not int
            or context["profile_version"] != 1
            or (
                "selection_sha256" in context
                and (
                    not isinstance(context["selection_sha256"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", context["selection_sha256"])
                )
            )
        ):
            raise ValueError("Candidate context must preserve its explicit mode, status and source provenance")
    if envelope.get("representation") == "active_mapping":
        payload = envelope["payload"]
        if (
            envelope["lane"] not in {"source_identity", "external_mapping"}
            or envelope.get("native_disposition") != "SUPPORTED"
            or envelope.get("consumer_disposition") != "SUPPORTED"
            or envelope.get("consumer_holds")
            or payload.get("predicate_id") not in PREDICATES
            or row[PREDICATE_COLUMN] != payload["predicate_id"]
            or row[RELATION_COLUMN] != payload["predicate_id"]
            or row[SUBJECT_COLUMN] != _identifier(payload["subject_id"])
            or row[OBJECT_COLUMN] != _identifier(payload["object_id"])
        ):
            raise ValueError("Active mapping must preserve independently supported endpoints and predicate")
        if envelope["lane"] == "source_identity" and payload["predicate_id"] != "skos:exactMatch":
            raise ValueError("Source identity requires exactMatch")
    elif envelope.get("representation") != "information_assertion" or (
        row[PREDICATE_COLUMN] != RELATED_TO_PREDICATE or row[RELATION_COLUMN] != "IAO:0000136"
    ):
        raise ValueError("Unapproved mappings must remain information assertions")


def project_stable_candidate(native_payload, *, manifest_sha256):
    """
    Project validated decisions without owner replacement, ontology inference or approval.

    Source claims and decisions, every external row/disposition, companion payloads
    and separate consumer holds survive independently. Only native-supported,
    consumer-unheld mappings receive active edges. Callers retain and verify the
    native product, producer/runtime and complete input closure around this call.
    """
    stable_ingredient_kgx_profile()
    profile_sha256 = stable_profile_sha256()
    if native_payload.get("profile_sha256") != profile_sha256:
        raise ValueError("Stable profile bytes differ from the selected current profile pin")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256):
        raise ValueError("Expected the exact source manifest fingerprint")
    if native_payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Source manifest fingerprint mismatch")
    if (
        native_payload.get("production_authorized") is not False
        or native_payload.get("status") != "PRIVATE_NOT_KG_ACCEPTED"
    ):
        raise ValueError("Only explicit private candidate-only source products are admitted")
    mode = native_payload.get("companion_mode")
    companion = native_payload.get("companion")
    if not isinstance(mode, str) or mode not in COMPANION_MODES or "companion" not in native_payload:
        raise ValueError("Candidate requires an explicit supported companion mode and presence decision")
    if mode == "absent/v1":
        if companion is not None:
            raise ValueError("Absent companion mode cannot contain supplied companion payloads")
    elif not isinstance(companion, dict) or any(
        not isinstance(companion.get(kind), list) for kind in ("mappings", "identifiers", "products", "occurrences")
    ):
        raise ValueError("Required companion mode requires every complete companion lane")
    context = {
        "companion_mode": mode,
        "status": native_payload["status"],
        "production_authorized": False,
        "source_manifest_sha256": manifest_sha256,
        "profile_sha256": profile_sha256,
        "profile_id": STABLE_PROFILE,
        "profile_version": 1,
    }
    if "selection_sha256" in native_payload:
        if not isinstance(native_payload["selection_sha256"], str) or not re.fullmatch(
            r"[a-f0-9]{64}", native_payload["selection_sha256"]
        ):
            raise ValueError("Malformed candidate selection fingerprint")
        context["selection_sha256"] = native_payload["selection_sha256"]
    if any(native_payload.get("curie_map", {}).get(key) != STABLE_PREFIX for key in ("MIM", "MIM.ingredient")):
        raise ValueError("Explicit permanent ingredient URI bindings are required")
    for key in ("claims", "source_decisions", "external_supported", "external_withheld", "external_dispositions"):
        if not isinstance(native_payload.get(key), list):
            raise ValueError(f"Missing complete native assertion lane: {key}")
    holds = native_payload.get("consumer_holds", [])
    if not isinstance(holds, list):
        raise ValueError("Consumer holds must remain separate structured evidence")
    for hold in holds:
        if not isinstance(hold, dict) or not (hold.get("owner_id") or hold.get("row_sha256")):
            raise ValueError("Consumer hold requires an exact owner or row binding")
        if hold.get("owner_id"):
            stable_graph_id(hold["owner_id"])
        if hold.get("row_sha256") and not re.fullmatch(r"[a-f0-9]{64}", hold["row_sha256"]):
            raise ValueError("Malformed consumer hold row binding")
    nodes, edges = {}, []
    candidate = "MIM.candidate:" + manifest_sha256

    def node(identifier, kind, label=""):
        """Add one explicitly identified node without merging different identifiers."""
        if identifier not in nodes:
            nodes[identifier] = {
                ID_COLUMN: identifier,
                CATEGORY_COLUMN: "biolink:InformationContentEntity"
                if kind in {"assertion_record", "candidate_manifest"}
                else "biolink:NamedThing",
                NAME_COLUMN: label,
                DESCRIPTION_COLUMN: "Candidate-only assertion transport; not production authorization",
                PROVIDED_BY_COLUMN: MIM_KNOWLEDGE_SOURCE,
                INGREDIENT_PROFILE_COLUMN: STABLE_PROFILE,
                INGREDIENT_BUNDLE_SHA256: manifest_sha256,
                INGREDIENT_RECORD_KIND: kind,
            }

    def edge(subject, predicate, obj, relation, envelope):
        """Append an edge with its complete independent assertion envelope."""
        value = {
            SUBJECT_COLUMN: subject,
            PREDICATE_COLUMN: predicate,
            OBJECT_COLUMN: obj,
            RELATION_COLUMN: relation,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: MIM_KNOWLEDGE_SOURCE,
            KNOWLEDGE_LEVEL_COLUMN: "knowledge_assertion",
            AGENT_TYPE_COLUMN: "manual_agent",
            INGREDIENT_PROFILE_COLUMN: STABLE_PROFILE,
            INGREDIENT_BUNDLE_SHA256: manifest_sha256,
            ASSERTION_JSON: canonical_json(envelope).decode("utf-8"),
        }
        validate_stable_ingredient_fields(value, is_node=False)
        edges.append(value)

    def information(envelope):
        """Retain an information assertion without authorizing an active mapping."""
        envelope = dict(envelope, representation="information_assertion")
        identifier = "MIM.assertion:" + _digest([manifest_sha256, len(edges), envelope])
        node(identifier, "assertion_record")
        edge(identifier, RELATED_TO_PREDICATE, candidate, "IAO:0000136", envelope)

    def active(envelope):
        """Emit the reviewed mapping with its original predicate and payload."""
        payload = envelope["payload"]
        subject, obj = _identifier(payload["subject_id"]), _identifier(payload["object_id"])
        for identifier, label in ((subject, payload.get("subject_label", "")), (obj, payload.get("object_label", ""))):
            kind = "stable_concept" if identifier.startswith("MIM.ingredient:") else "external_reference"
            if envelope["lane"] == "source_identity" and identifier == subject:
                kind = "source_record"
            node(identifier, kind, label)
        edge(
            subject,
            payload["predicate_id"],
            obj,
            payload["predicate_id"],
            dict(envelope, representation="active_mapping"),
        )

    node(candidate, "candidate_manifest")
    information({"lane": "candidate_context", "payload": context})
    supported_sources = {}
    for decision in native_payload["source_decisions"]:
        if not isinstance(decision, dict) or not isinstance(decision.get("payload"), dict):
            raise ValueError("Malformed native source decision")
        information({"lane": "source_decision", "payload": decision})
        if decision.get("disposition") == "SUPPORTED":
            binding = decision.get("binding") or {}
            source = binding.get("subject_id")
            if not source or source in supported_sources:
                raise ValueError("Duplicate or missing supported source decision")
            supported_sources[source] = decision
    claimed_sources = set()
    for claim in native_payload["claims"]:
        decision = supported_sources.get(claim.get("original_subject_id"))
        if (
            not decision
            or claim["original_subject_id"] in claimed_sources
            or claim.get("subject_id") != claim["original_subject_id"]
            or claim.get("original_object_id") != decision["binding"].get("object_id")
            or claim.get("payload_sha256") != decision.get("payload_sha256")
            or claim.get("object_id") != stable_graph_id(claim["original_object_id"])
            or claim.get("predicate_id") != "skos:exactMatch"
        ):
            raise ValueError("Source identity is not a one-to-one supported native decision")
        claimed_sources.add(claim["original_subject_id"])
        active(
            {
                "lane": "source_identity",
                "payload": claim,
                "native_disposition": "SUPPORTED",
                "consumer_disposition": "SUPPORTED",
            }
        )
    if claimed_sources != set(supported_sources):
        raise ValueError("Supported source decision is missing its identity claim")
    dispositions = defaultdict(list)
    for decision in native_payload["external_dispositions"]:
        dispositions[(decision.get("row_sha256"), decision.get("disposition"))].append(decision)
    observed = Counter()
    for status, key in (("SUPPORTED", "external_supported"), ("WITHHOLD", "external_withheld")):
        for row in native_payload[key]:
            stable_graph_id(row["subject_id"])
            if row.get("predicate_id") not in PREDICATES:
                raise ValueError("Unsupported external mapping predicate")
            digest = _digest(row)
            slot = (digest, status)
            index = observed[slot]
            if index >= len(dispositions[slot]):
                raise ValueError("External row has no exact native disposition")
            decision = dispositions[slot][index]
            observed[slot] += 1
            matching = [
                hold
                for hold in holds
                if (not hold.get("owner_id") or stable_graph_id(hold["owner_id"]) == stable_graph_id(row["subject_id"]))
                and (not hold.get("row_sha256") or hold["row_sha256"] == digest)
            ]
            envelope = {
                "lane": "external_mapping",
                "payload": row,
                "disposition": decision,
                "native_disposition": status,
                "consumer_disposition": "WITHHOLD" if matching else status,
                "consumer_holds": matching,
            }
            information(envelope)
            if status == "SUPPORTED" and not matching:
                active(envelope)
    if observed != Counter({key: len(value) for key, value in dispositions.items()}):
        raise ValueError("External disposition is missing its complete source row")
    if mode == "required/v1":
        for kind in ("mappings", "identifiers", "products", "occurrences"):
            for payload in companion[kind]:
                information({"lane": "companion", "kind": kind, "payload": payload})
    for hold in holds:
        information({"lane": "consumer_hold", "payload": hold})
    for value in nodes.values():
        validate_stable_ingredient_fields(value, is_node=True)
    return list(nodes.values()), edges
