"""Finite native-evidence identity decisions for PREGO's retired ENVO subjects."""

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from kg_microbe.utils.ontology_metadata import metadata_identifier, obograph_is_deprecated

POLICY_FILE = Path(__file__).resolve().parents[3] / "mappings" / "prego_envo_identity_dispositions.tsv"
POLICY_COLUMNS = (
    "original_id",
    "disposition",
    "replacement_id",
    "replaced_by",
    "consider",
    "native_record_sha256",
    "target_record_sha256",
    "reviewed_release",
    "rationale",
)
AUDIT_COLUMNS = (
    "source_assertion_id",
    "original_subject",
    "normalized_subject",
    "disposition",
    "archive",
    "archive_sha256",
    "member",
    "payload_sha256",
    "physical_line",
    "original_record_json",
    "emitted_edge_json",
    "subject_node_json",
    "native_proof_json",
    "policy_sha256",
    "envo_sha256",
    "foodon_sha256",
)
_CURIE = re.compile(r"(?:ENVO|FOODON):[0-9]+\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REPLACED_BY = "IAO:0100001"
_CONSIDER = "http://www.geneontology.org/formats/oboInOwl#consider"
REVIEWED_ENVO_IDS = frozenset(
    {
        "ENVO:00000373",
        "ENVO:00002002",
        "ENVO:00002004",
        "ENVO:00002036",
        "ENVO:00002041",
        "ENVO:00002265",
        "ENVO:00002297",
        "ENVO:01000009",
        "ENVO:01000105",
        "ENVO:01000159",
    }
)


def record_digest(record):
    """Bind the full selected native declaration, including all annotations."""
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _declarations(stream):
    """Index exact declarations, refusing inconsistent duplicates before graph output opens."""
    document = json.load(stream)
    if not isinstance(document, dict) or not isinstance(document.get("graphs"), list) or not document["graphs"]:
        raise ValueError("PREGO identity authority requires a nonempty OBOGraph document")
    result = {}
    for graph in document["graphs"]:
        for node in graph.get("nodes", []):
            identifier = metadata_identifier(node.get("id", ""))
            if not identifier:
                continue
            obograph_is_deprecated(node)
            if identifier in result and result[identifier] != node:
                raise ValueError(f"Conflicting native declarations for {identifier}")
            result[identifier] = node
    if not result:
        raise ValueError("PREGO identity authority has no declarations")
    return result


def _annotations(node, predicate):
    """Return the complete explicit annotation target set; never follow consider hints."""
    return tuple(
        sorted(
            {
                metadata_identifier(item.get("val", ""))
                for item in node.get("meta", {}).get("basicPropertyValues", [])
                if metadata_identifier(item.get("pred", "")) == metadata_identifier(predicate)
            }
        )
    )


def _targets(value):
    """Validate sorted, unique policy annotation sets without accepting partial identifiers."""
    values = tuple(value.split("|")) if value else ()
    if values != tuple(sorted(set(values))) or any(not _CURIE.fullmatch(item) for item in values):
        raise ValueError(f"Malformed PREGO identity targets: {value!r}")
    return values


@dataclass(frozen=True)
class IdentityDecision:
    """One immutable decision with exact native proof and truthful node context."""

    original_id: str
    target_id: str
    disposition: str
    name: str
    deprecated: bool
    proof_json: str


def load_identity_decisions(policy_stream, envo_stream, foodon_stream):
    """Validate every finite policy row against its immutable selected native declarations."""
    envo, foodon = _declarations(envo_stream), _declarations(foodon_stream)
    reader = csv.DictReader(policy_stream, delimiter="\t")
    if reader.fieldnames != list(POLICY_COLUMNS):
        raise ValueError("Malformed PREGO identity policy header")
    decisions = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed PREGO identity policy row")
        old, target = row["original_id"], row["replacement_id"]
        if not _CURIE.fullmatch(old) or not old.startswith("ENVO:") or old in decisions:
            raise ValueError(f"Invalid or duplicate PREGO identity key: {old!r}")
        if not row["rationale"] or not row["reviewed_release"].startswith("https://"):
            raise ValueError(f"Missing reviewed PREGO identity evidence for {old}")
        native = envo.get(old)
        if not native or native.get("type") != "CLASS" or not obograph_is_deprecated(native):
            raise ValueError(f"PREGO requires the native retired CLASS declaration for {old}")
        replacements, considerations = _targets(row["replaced_by"]), _targets(row["consider"])
        if _annotations(native, _REPLACED_BY) != replacements or _annotations(native, _CONSIDER) != considerations:
            raise ValueError(f"PREGO native retirement annotations changed for {old}")
        if not _DIGEST.fullmatch(row["native_record_sha256"]) or record_digest(native) != row["native_record_sha256"]:
            raise ValueError(f"PREGO native declaration changed for {old}")
        disposition = row["disposition"]
        if disposition == "replace_explicit_unique":
            if not _CURIE.fullmatch(target) or replacements != (target,) or target == old:
                raise ValueError(f"PREGO replacement lacks unique explicit proof for {old}")
            if target.startswith("FOODON:") and (old, target) != ("ENVO:00002002", "FOODON:00001002"):
                raise ValueError(f"Unreviewed PREGO cross-namespace replacement for {old}")
            successor = (foodon if target.startswith("FOODON:") else envo).get(target)
            if not successor or successor.get("type") != "CLASS" or obograph_is_deprecated(successor):
                raise ValueError(f"PREGO replacement target is not a live CLASS: {target}")
            if (
                not _DIGEST.fullmatch(row["target_record_sha256"])
                or record_digest(successor) != row["target_record_sha256"]
            ):
                raise ValueError(f"PREGO replacement declaration changed for {target}")
        elif disposition == "retain_unresolved":
            if target or replacements or row["target_record_sha256"]:
                raise ValueError(f"Invalid PREGO unresolved decision for {old}")
            target, successor = old, native
        else:
            raise ValueError(f"Unknown PREGO identity disposition: {disposition!r}")
        decisions[old] = IdentityDecision(
            old,
            target,
            disposition,
            successor.get("lbl", ""),
            disposition == "retain_unresolved",
            json.dumps({"policy": row, "original": native, "target": successor}, sort_keys=True),
        )
    if set(decisions) != REVIEWED_ENVO_IDS:
        raise ValueError("PREGO identity policy must cover the complete reviewed ten-identifier cohort")
    return MappingProxyType(decisions)
