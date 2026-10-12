"""Preserve exact native class literals with both reviewed lexical envelopes (#1368)."""

import hashlib
import json

import pytest

from kg_microbe.utils import go_imported_restrictions as restrictions
from tests.go_subject_restrictions_fixtures import FULL_POLICY, prepare

pytestmark = pytest.mark.usefixtures("local_source_schema")


def test_all_fifteen_literal_policy_witnesses_prepare_without_editing_evidence(tmp_path, monkeypatch):
    """Accept every exact immutable literal through the real guarded snapshot reader."""
    raw, _, _, _, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    original = (raw / "pato.owl").read_bytes()
    guard = restrictions.ImportedGoRestrictionGuard(authority)
    guard.prepare()
    assert len(guard.policy["records"]) == 15
    assert guard.policy["records"] == FULL_POLICY["records"]
    assert (raw / "pato.owl").read_bytes() == original


@pytest.mark.parametrize(
    "damage",
    ["leading_literal", "trailing_literal", "inner_restriction", "missing", "duplicate", "competing", "digest"],
)
def test_exact_full_literal_and_class_uniqueness_survive_framing_compatibility(tmp_path, monkeypatch, damage):
    """Reach the real witness guard after rebinding only explicit test-owned file hashes."""
    raw, _, _, _, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    path = raw / "pato.owl"
    original = path.read_bytes()
    policy_path = restrictions.POLICY_FILE
    policy = json.loads(policy_path.read_text())
    record = next(row for row in policy["records"] if row["subject"] == "GO:0055108")
    literal = record["native_class_xml"].encode()
    assert original.count(literal) == 1
    if damage == "leading_literal":
        replacement = literal[1:]
    elif damage == "trailing_literal":
        replacement = literal[:-1] + b"\r"
    elif damage == "inner_restriction":
        replacement = literal.replace(b"GO_0005737", b"GO_0005738", 1)
    elif damage == "missing":
        replacement = b""
    elif damage == "duplicate":
        replacement = literal + literal
    elif damage == "competing":
        replacement = literal + literal.replace(b"GO_0005737", b"GO_0005738", 1)
    else:
        replacement = literal
        record["native_class_sha256"] = "0" * 64
    changed = original.replace(literal, replacement, 1)
    assert (changed != original) == (damage != "digest")
    path.write_bytes(changed)
    policy["sources"]["pato.owl"]["sha256"] = hashlib.sha256(changed).hexdigest()
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr(
        restrictions, "REVIEWED_POLICY_SHA256", restrictions._digest(restrictions._json(policy).encode())
    )
    with pytest.raises(ValueError, match="native class restriction witness changed"):
        restrictions.ImportedGoRestrictionGuard(authority).prepare()
    assert path.read_bytes() == changed
