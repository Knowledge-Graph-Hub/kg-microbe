"""Complete-payload and owning-record evidence checks shared by reviewed exports."""

from __future__ import annotations

import hashlib
import json


def payload_sha256(payload: dict) -> str:
    """Hash the entire reviewed payload, including structured source qualifiers."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _proof(content: bytes, name: str) -> dict:
    result = json.loads(content, object_pairs_hook=_unique_object)
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object: {name}")
    return result


def validate_review_decision(
    decision: dict,
    payload: dict,
    owner: str,
    owner_sha256: str,
    verified: dict[str, bytes],
    proofs: dict,
    *,
    require_owner_path: bool = False,
) -> None:
    """
    Verify a complete claim against the existing owner/evidence review format.

    Callers independently resolve the owning record and verify every input's
    digest before supplying its bytes. This verifier is shared by mapping and
    companion-claim exports; a checksum or receipt alone confers no approval.
    """
    if decision.get("row_sha256") != payload_sha256(payload) or decision.get("owner_record") != owner:
        raise ValueError("Review row payload or owner does not match source")
    if decision.get("disposition") not in {"SUPPORTED", "WITHHOLD"}:
        raise ValueError("Invalid scientific disposition")
    if not isinstance(decision.get("review_reason"), str) or not decision["review_reason"].strip():
        raise ValueError("Missing scientific review reason")
    evidence, key = decision.get("review_evidence"), decision.get("evidence_key")
    if evidence not in verified or not isinstance(key, str) or not key.strip():
        raise ValueError("Missing hash-bound evidence reference")
    if evidence not in proofs:
        proofs[evidence] = _proof(verified[evidence], evidence)
    entry = proofs[evidence].get("entries", {}).get(key)
    expected = {field: decision[field] for field in ("row_sha256", "disposition", "review_reason")}
    expected["owner_record_sha256"] = owner_sha256
    if require_owner_path:
        expected["owner_record"] = owner
    if not isinstance(entry, dict) or any(entry.get(field) != value for field, value in expected.items()):
        raise ValueError("Scientific decision disagrees with exact evidence entry")
