"""Finite approved withholding of 97 same-priority, normalized-multivalent records."""

import hashlib
import json
from pathlib import Path

from kg_microbe.transform_utils.constants import NCBITAXON_PREFIX

POLICY_RELATIVE = "mappings/bacdive_supplied_taxid_dispositions.json"
POLICY_PATH = Path(__file__).resolve().parents[3] / POLICY_RELATIVE
ROLE = "bacdive_supplied_taxid_dispositions"
POLICY_SHA256 = "3b82f2acd786b6033cdaac04deb9db5e1437963f395ee282392f2c932cf57739"


def load_policy(stream):
    """Admit only the reviewed finite policy; no output-derived or global ambiguity rule."""
    content = stream.read()
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != POLICY_SHA256:
        raise ValueError("Reviewed BacDive supplied-taxid policy changed")
    return json.loads(content)


def disposition(record, policy):
    """Retain source claims/order, withholding only reviewed distinct normalized candidates."""
    general = record.get("General", {})
    record_id = str(general.get("BacDive-ID", ""))
    rule = next((row for row in policy["records"] if row["record_id"] == record_id), None)
    supplied = general.get("NCBI tax id")
    if rule is None or not isinstance(supplied, list):
        return None
    preferred = [item for item in supplied if item.get("Matching level") == "strain"]
    priority = "strain" if preferred else "species"
    preferred = preferred or [item for item in supplied if item.get("Matching level") == "species"]
    if not preferred or priority != rule["priority"]:
        return None
    original = []
    normalized = []
    for claim in preferred:
        value = claim.get("NCBI tax id")
        if (
            isinstance(value, bool)
            or not isinstance(value, (str, int))
            or not str(value).isascii()
            or not str(value).isdigit()
        ):
            raise ValueError("Invalid reviewed supplied taxid")
        identifier = NCBITAXON_PREFIX + str(int(value))
        original.append(identifier)
        normalized.append(policy["normalizations"].get(identifier, identifier))
    if len(set(normalized)) <= 1:
        return None
    if set(normalized) != set(rule["normalized_priority_ids"]):
        raise ValueError("Reviewed BacDive supplied-taxid candidates changed; review required")
    return {
        "status": "same_priority_distinct_normalized_taxids_parent_withheld",
        "priority": priority,
        "original_priority_ids": original,
        "normalized_priority_ids": normalized,
        "original_first_selection": original[0],
        "all_supplied_claims": supplied,
        "policy_evidence_sha256": policy["evidence_sha256"],
        "biological_contradiction_proven": False,
    }
