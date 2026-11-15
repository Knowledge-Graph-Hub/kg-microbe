"""Exercise the shared deposit contract with real offline source producers (#1852)."""

import pytest

from kg_microbe.transform_utils.bacdive.emission import RESOLUTION_SUPPRESSED
from kg_microbe.transform_utils.constants import (
    BACDIVE_DEPOSIT_CLAIMS_FILE,
    EXACT_MATCH,
    NCBI_CATEGORY,
    RDFS_SUBCLASS_OF,
    SAME_AS_PREDICATE,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.lpsn.lpsn import LPSNTransform
from kg_microbe.utils.source_finalization import graph_rows
from tests.test_bacdive_taxonomy_evidence import controls, produce, scoped_rows
from tests.test_lpsn_transform import FIXTURE_DIR, _NoGTDB, _NoNCBI, _read_tsv

DEPOSIT = "kgmicrobe.strain:ATCC-11775"


def _reachable_taxa(edges, start):
    """Follow identity in either direction and taxonomic hierarchy toward parents."""
    adjacent = {}
    for edge in edges:
        if edge["predicate"] not in {SAME_AS_PREDICATE, SUBCLASS_PREDICATE}:
            continue
        adjacent.setdefault(edge["subject"], set()).add(edge["object"])
        if edge["predicate"] == SAME_AS_PREDICATE:
            adjacent.setdefault(edge["object"], set()).add(edge["subject"])
    seen, pending = set(), {start}
    while pending:
        node = pending.pop()
        seen.add(node)
        pending.update(adjacent.get(node, set()) - seen)
    return seen


@pytest.mark.parametrize("conflicting", [False, True], ids=["shared-deposit", "disjoint-bacdive-claims"])
def test_shared_deposit_taxon_contract_preserves_conflict_guard(tmp_path, monkeypatch, conflicting):
    """Joining LPSN preserves BacDive's safe traversal and cannot restore suppressed identities."""
    # These are synthetic behavior controls, not claims that the fixture taxa
    # are ATCC 11775. Reuse that identifier solely to exercise the source join.
    records = controls()["records"][6 : 8 if conflicting else 7]
    for record in records:
        record["External links"]["culture collection no."] = "ATCC 11775"
    bacdive, _, _, _ = produce(tmp_path, monkeypatch, records=records)
    lpsn = LPSNTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path / "lpsn-output",
        ncbi_impl=_NoNCBI(),
        gtdb_index=_NoGTDB(),
    )
    lpsn.run()
    bacdive_edges = scoped_rows(bacdive)
    lpsn_edges = _read_tsv(lpsn.output_edge_file)
    combined = bacdive_edges + lpsn_edges

    for source, nodes in (
        ("infores:bacdive", list(graph_rows(bacdive.output_node_file))),
        ("infores:lpsn", _read_tsv(lpsn.output_node_file)),
    ):
        deposit_nodes = [node for node in nodes if node["id"] == DEPOSIT]
        assert len(deposit_nodes) == 1
        assert deposit_nodes[0]["category"] == NCBI_CATEGORY
        assert deposit_nodes[0]["provided_by"] == source

    lpsn_parents = [edge for edge in lpsn_edges if edge["subject"] == DEPOSIT]
    assert len(lpsn_parents) == 1
    assert lpsn_parents[0] == {
        "subject": DEPOSIT,
        "predicate": SUBCLASS_PREDICATE,
        "object": "lpsn:1002",
        "relation": RDFS_SUBCLASS_OF,
        "primary_knowledge_source": "infores:lpsn",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
    }
    assert {"lpsn:1001", "lpsn:1002"} <= _reachable_taxa(combined, DEPOSIT)
    assert not any(edge["predicate"] == "biolink:in_taxon" for edge in combined if edge["subject"] == DEPOSIT)

    reached = _reachable_taxa(combined, "kgmicrobe.strain:bacdive_7")
    claims = list(graph_rows(bacdive.output_dir / BACDIVE_DEPOSIT_CLAIMS_FILE))
    if conflicting:
        assert not any(DEPOSIT in (edge["subject"], edge["object"]) for edge in bacdive_edges)
        assert {DEPOSIT, "lpsn:1001", "lpsn:1002", "kgmicrobe.strain:bacdive_8"}.isdisjoint(reached)
        assert "NCBITaxon:20" in reached and "NCBITaxon:30" not in reached
        assert len(claims) == 1
        assert claims[0]["strain_id"] == DEPOSIT
        assert claims[0]["resolution"] == RESOLUTION_SUPPRESSED
        assert set(claims[0]["parents"].split("|")) == {"NCBITaxon:20", "NCBITaxon:30"}
        assert claims[0]["asserted_parent"] == ""
    else:
        assert {DEPOSIT, "lpsn:1001", "lpsn:1002", "NCBITaxon:20"} <= reached
        citations = [edge for edge in bacdive_edges if edge["object"] == DEPOSIT]
        assert len(citations) == 1
        assert citations[0]["predicate"] == SAME_AS_PREDICATE
        assert citations[0]["relation"] == EXACT_MATCH
        assert citations[0]["primary_knowledge_source"] == "infores:bacdive"
        assert not claims
