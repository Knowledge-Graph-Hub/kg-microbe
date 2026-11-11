"""Actual BacDive output distinguishes safe deposit identity from conflicting claims."""

from kg_microbe.transform_utils.constants import EXACT_MATCH, SAME_AS_PREDICATE
from tests.test_bacdive_taxonomy_evidence import produce, scoped_rows


def test_safe_equivalences_and_unsafe_deposit_suppression(tmp_path, monkeypatch):
    """The producer emits exact identity only for citations surviving the native guard."""
    transform, _, _, _ = produce(tmp_path, monkeypatch)
    rows = scoped_rows(transform)
    citations = [
        row
        for row in rows
        if row["subject"].startswith("kgmicrobe.strain:bacdive_") and row["object"].startswith("kgmicrobe.strain:TEST-")
    ]
    assert {row["object"] for row in citations} == {
        "kgmicrobe.strain:TEST-DIRECT",
        "kgmicrobe.strain:TEST-INFERRED",
        "kgmicrobe.strain:TEST-MIXED",
        "kgmicrobe.strain:TEST-BOTH",
        "kgmicrobe.strain:TEST-REPEAT",
        "kgmicrobe.strain:TEST-LATE",
    }
    assert all(row["predicate"] == SAME_AS_PREDICATE and row["relation"] == EXACT_MATCH for row in citations)
    assert all(row["primary_knowledge_source"] and row["knowledge_level"] and row["agent_type"] for row in citations)
    assert not any(row["object"] == "kgmicrobe.strain:TEST-DISJOINT" for row in rows)
