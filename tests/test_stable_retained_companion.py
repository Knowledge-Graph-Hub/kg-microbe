"""#1859: native retained obligations remain complete information, never activation."""

from copy import deepcopy

import pytest

from kg_microbe.utils.stable_ingredient_kgx import project_stable_candidate
from kg_microbe.utils.stable_source_native_bridge import (
    COMPANION_CAPABILITIES,
    RETAINED_CAPABILITY,
    companion_capabilities,
    retained_companion,
)
from tests.test_stable_ingredient_kgx import MANIFEST, digest, envelopes, source_payload


def reconstruct_retained_ledger(edges):
    """Reassemble exact native entry order from scalar graph cells and verify its pin."""
    values = envelopes(edges)
    headers = [entry for entry in values if entry.get("kind") == "retained_obligations"]
    entries = [entry for entry in values if entry.get("kind") == "retained_obligation"]
    assert len(headers) == 1
    header = headers[0]
    assert all(entry["representation"] == "information_assertion" for entry in [header, *entries])
    assert len(entries) == header["payload"]["claim_count"]
    assert all(type(entry["entry_position"]) is int for entry in entries)
    assert sorted(entry["entry_position"] for entry in entries) == list(range(1, len(entries) + 1))
    assert all(entry["ledger_sha256"] == header["ledger_sha256"] for entry in entries)
    result = dict(
        header["payload"], entries=[entry["payload"] for entry in sorted(entries, key=lambda e: e["entry_position"])]
    )
    assert digest(result) == header["ledger_sha256"]
    return result


def retained_payload():
    """Use explicit synthetic decisions, including a supported but retained occurrence."""
    value = source_payload()
    mapping = {
        "subject_id": "MIM:0000001",
        "object_id": "CHEBI:1",
        "predicate_id": "skos:exactMatch",
        "ext_scope_review_status": "SUPPORTED",
        "ext_identity_authorized": "true",
    }
    held = {
        "subject_id": "MIM:0000522",
        "object_id": "NCIT:C85253",
        "predicate_id": "skos:exactMatch",
        "ext_scope_review_status": "WITHHOLD",
        "ext_identity_authorized": "false",
    }
    occurrence = {"ingredient_id": "MIM:0000522", "quantity": "original reported amount", "review_status": "SUPPORTED"}
    entries = []
    for identifier, kind, owner, payload, disposition, partition in [
        ("map-active", "mapping", "data/ingredients/mapped/Active.yaml", mapping, "SUPPORTED", "emitted"),
        ("map-held", "mapping", "data/ingredients/mapped/Bovine_Serum_Albumin.yaml", held, "WITHHOLD", "retained"),
        (
            "occ-held",
            "occurrence",
            "data/ingredients/mapped/Bovine_Serum_Albumin.yaml",
            occurrence,
            "SUPPORTED",
            "retained",
        ),
    ]:
        claim = {"claim_id": identifier, "kind": kind, "owner_record": owner, "payload": payload}
        previous = deepcopy(claim)
        previous["claim_id"] = "previous-" + identifier
        entries.append(
            {
                "previous_claim": previous,
                "claim": claim,
                "decision": {"claim_id": identifier, "disposition": disposition},
                "partition": partition,
                "blocked_by": ["map-held"] if partition == "retained" else [],
            }
        )
    value["companion"] = {
        "mappings": [mapping],
        "identifiers": [],
        "products": [],
        "occurrences": [],
        "retained_obligations": {
            "schema_version": 1,
            "capability": RETAINED_CAPABILITY,
            "historical_review": {"path": "synthetic-history.json", "sha256": "a" * 64},
            "claim_count": 3,
            "owner_count": 2,
            "emitted_claim_count": 1,
            "retained_claim_count": 2,
            "entries": entries,
        },
    }
    return value


def test_explicit_consumer_capability_and_unknown_refusal():
    """Native producer upgrades cannot expand the KG supported set implicitly."""
    assert companion_capabilities({"required_capabilities": sorted(COMPANION_CAPABILITIES)}) == COMPANION_CAPABILITIES
    for required in [["future/v1"], [RETAINED_CAPABILITY, "future/v1"], [RETAINED_CAPABILITY] * 2, [True], None]:
        with pytest.raises(ValueError, match="companion capabilities"):
            companion_capabilities({"required_capabilities": required})


def test_complete_retained_ledger_is_information_only():
    """Retain full prior/current decisions without adding BSA identity or occurrence nodes."""
    value = retained_payload()
    ledger = deepcopy(value["companion"]["retained_obligations"])
    baseline = deepcopy(value)
    del baseline["companion"]["retained_obligations"]
    original_nodes, original_edges = project_stable_candidate(baseline, manifest_sha256=MANIFEST)
    nodes, edges = project_stable_candidate(value, manifest_sha256=MANIFEST)
    assert edges[: len(original_edges)] == original_edges
    assert nodes[: len(original_nodes)] == original_nodes
    assert len(edges) == len(original_edges) + 1 + len(ledger["entries"])
    assert reconstruct_retained_ledger(edges) == ledger
    assert reconstruct_retained_ledger(list(reversed(edges))) == ledger
    assert ledger["entries"][2]["decision"]["disposition"] == "SUPPORTED"
    assert not any(row["id"] in {"MIM.ingredient:0000522", "NCIT:C85253"} for row in nodes)
    assert not any("subclass" in edge["predicate"] for edge in edges)
    assert value["companion"]["retained_obligations"] == ledger


@pytest.mark.parametrize(
    "attack", ["missing", "duplicate", "count", "scope", "partition", "blocker", "leak", "decision"]
)
def test_retained_accounting_and_activation_tampering_refused(attack):
    """Structural rehashing cannot erase obligations, change their partition or activate them."""
    value = retained_payload()
    companion = value["companion"]
    ledger = companion["retained_obligations"]
    if attack == "missing":
        ledger["entries"].pop()
    elif attack == "duplicate":
        ledger["entries"][2] = deepcopy(ledger["entries"][1])
    elif attack == "count":
        ledger["claim_count"] = True
    elif attack == "scope":
        ledger["entries"][1]["claim"]["payload"]["ext_identity_authorized"] = "true"
    elif attack == "partition":
        ledger["entries"][2].update(partition="emitted", blocked_by=[])
    elif attack == "blocker":
        ledger["entries"][2]["blocked_by"] = ["map-active"]
    elif attack == "leak":
        companion["occurrences"].append(ledger["entries"][2]["claim"]["payload"])
    else:
        ledger["entries"][2]["decision"]["claim_id"] = "another"
    with pytest.raises(ValueError):
        project_stable_candidate(value, manifest_sha256=MANIFEST)


def test_old_companion_arrays_have_no_invented_retained_partition():
    """Unchanged old-format payloads remain on their original ordinary route."""
    payload = source_payload()
    assert retained_companion(payload["companion"]) is None
    assert not any(
        entry.get("kind") == "retained_obligations"
        for entry in envelopes(project_stable_candidate(payload, manifest_sha256=MANIFEST)[1])
    )
