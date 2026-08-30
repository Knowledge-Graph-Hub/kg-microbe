"""Culture-collection deposits must not acquire contradictory parent taxa (#892)."""

from __future__ import annotations

from kg_microbe.transform_utils.bacdive.emission import (
    DEPOSIT_CONFLICT_HEADER,
    deposit_conflict_rows,
    resolve_deposit_parents,
)


def test_a_deposit_claimed_by_one_record_keeps_its_parent():
    """The ordinary case — one record cites the deposit — is unchanged."""
    resolved, conflicts = resolve_deposit_parents({"kgmicrobe.strain:DSM-20154": {"NCBITaxon:272240": ["3081"]}})
    assert resolved == [("kgmicrobe.strain:DSM-20154", "NCBITaxon:272240")]
    assert conflicts == []


def test_agreeing_records_still_yield_a_single_edge():
    """Several records citing the same deposit and the same taxon do not conflict."""
    resolved, conflicts = resolve_deposit_parents(
        {"kgmicrobe.strain:DSM-20154": {"NCBITaxon:272240": ["3081", "7476"]}}
    )
    assert resolved == [("kgmicrobe.strain:DSM-20154", "NCBITaxon:272240")]
    assert conflicts == []


def test_disagreeing_records_suppress_the_edge_entirely():
    """
    Picking one of two parents makes the answer depend on file order.

    ``ATCC 13722`` is cited by BacDive 3081 (*Gulosibacter faecalis*) and 7476
    (*Pseudoclavibacter* sp.). Emitting both leaves a consumer that takes "the"
    parent with whichever came first, so neither is asserted.
    """
    claims = {
        "kgmicrobe.strain:ATCC-13722": {
            "NCBITaxon:272240": ["3081"],
            "NCBITaxon:1915061": ["7476"],
        }
    }
    resolved, conflicts = resolve_deposit_parents(claims)
    assert resolved == []
    assert conflicts == [("kgmicrobe.strain:ATCC-13722", claims["kgmicrobe.strain:ATCC-13722"])]


def test_conflicts_do_not_suppress_unrelated_deposits():
    """Suppression is per deposit, not per record."""
    resolved, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-13722": {
                "NCBITaxon:272240": ["3081"],
                "NCBITaxon:1915061": ["7476"],
            },
            "kgmicrobe.strain:NCDO-1718": {"NCBITaxon:272240": ["3081"]},
        }
    )
    assert resolved == [("kgmicrobe.strain:NCDO-1718", "NCBITaxon:272240")]
    assert [curie for curie, _ in conflicts] == ["kgmicrobe.strain:ATCC-13722"]


def test_the_report_records_what_was_suppressed():
    """A suppressed claim is still recoverable from the report."""
    _, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-13722": {
                "NCBITaxon:272240": ["3081"],
                "NCBITaxon:1915061": ["7476"],
            }
        }
    )
    rows = deposit_conflict_rows(conflicts)
    assert len(DEPOSIT_CONFLICT_HEADER) == len(rows[0])
    assert rows == [
        [
            "kgmicrobe.strain:ATCC-13722",
            2,
            "NCBITaxon:1915061|NCBITaxon:272240",
            "3081|7476",
        ]
    ]


# Real NCBITaxon ancestry, trimmed to what these cases need.
_ANCESTRY = {
    # Brevundimonas vesicularis NBRC 12165 sits under Brevundimonas vesicularis.
    "NCBITaxon:1349759": {"NCBITaxon:41276", "NCBITaxon:41275"},
    "NCBITaxon:41276": {"NCBITaxon:41275"},
    # Gulosibacter faecalis and Pseudoclavibacter sp. share nothing below the phylum.
    "NCBITaxon:272240": {"NCBITaxon:201174"},
    "NCBITaxon:1915061": {"NCBITaxon:201174"},
}


def _ancestors(curie):
    return _ANCESTRY.get(curie, set())


def test_claims_differing_only_in_depth_collapse_to_the_shared_ancestor():
    """
    Species and strain-under-that-species are not a contradiction.

    BacDive records one deposit as *Brevundimonas vesicularis* and another as
    *B. vesicularis NBRC 12165*. The species claim holds either way, so it is
    the strongest statement both claimants support — and asserting it privileges
    neither record, which is the whole point of the rule.
    """
    resolved, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-11426": {
                "NCBITaxon:1349759": ["1"],
                "NCBITaxon:41276": ["2"],
            }
        },
        ancestors_of=_ancestors,
    )
    assert resolved == [("kgmicrobe.strain:ATCC-11426", "NCBITaxon:41276")]
    assert conflicts == []


def test_disjoint_lineages_are_still_suppressed_when_ancestry_is_available():
    """Having an ontology must not turn a real contradiction into an answer."""
    resolved, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-13722": {
                "NCBITaxon:272240": ["3081"],
                "NCBITaxon:1915061": ["7476"],
            }
        },
        ancestors_of=_ancestors,
    )
    assert resolved == []
    assert [curie for curie, _ in conflicts] == ["kgmicrobe.strain:ATCC-13722"]


def test_no_unclaimed_taxon_is_ever_asserted():
    """
    The shared phylum is not an acceptable answer.

    Every pair of bacteria has a common ancestor, so falling back to a computed
    one would put ``Bacteria`` on the node and call the conflict resolved.
    """
    _, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-13722": {
                "NCBITaxon:272240": ["3081"],
                "NCBITaxon:1915061": ["7476"],
            }
        },
        ancestors_of=_ancestors,
    )
    assert conflicts, "a shared phylum must not count as agreement"


def test_a_three_way_chain_collapses_to_its_shallowest_member():
    """Chains longer than two claims resolve the same way."""
    resolved, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:X-1": {
                "NCBITaxon:1349759": ["1"],
                "NCBITaxon:41276": ["2"],
                "NCBITaxon:41275": ["3"],
            }
        },
        ancestors_of=_ancestors,
    )
    assert resolved == [("kgmicrobe.strain:X-1", "NCBITaxon:41275")]
    assert conflicts == []


def test_without_ancestry_any_disagreement_is_a_conflict():
    """The helper stays usable, and conservative, with no ontology to consult."""
    resolved, conflicts = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-11426": {
                "NCBITaxon:1349759": ["1"],
                "NCBITaxon:41276": ["2"],
            }
        }
    )
    assert resolved == []
    assert len(conflicts) == 1
