"""Culture-collection deposits must not acquire contradictory parent taxa (#892)."""

from __future__ import annotations

from kg_microbe.transform_utils.bacdive.emission import (
    DEPOSIT_CONFLICT_HEADER,
    RESOLUTION_COLLAPSED,
    RESOLUTION_SUPPRESSED,
    RESOLUTION_SUPPRESSED_NO_ANCESTRY,
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
    assert conflicts == [
        ("kgmicrobe.strain:ATCC-13722", claims["kgmicrobe.strain:ATCC-13722"], RESOLUTION_SUPPRESSED, "")
    ]


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
    assert [entry[0] for entry in conflicts] == ["kgmicrobe.strain:ATCC-13722"]


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
            RESOLUTION_SUPPRESSED,
            "",
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
    assert [entry[2] for entry in conflicts] == [RESOLUTION_COLLAPSED]


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
    assert [entry[0] for entry in conflicts] == ["kgmicrobe.strain:ATCC-13722"]


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
    assert [entry[2] for entry in conflicts] == [RESOLUTION_COLLAPSED]


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


def test_the_record_is_linked_to_every_deposit_it_cites():
    """
    A deposit node must reach back to whoever asserted it (#894).

    Without this edge a `kgmicrobe.strain:<deposit>` node has one outgoing
    `subclass_of` and nothing else, so a deposit whose claimants disagree —
    which gets no `subclass_of` at all — would reach no taxon by any path.

    Inspected rather than run: `BacDiveTransform.run` needs the NCBITaxon
    adapter, which makes an end-to-end unit test impractical (see the module
    docstring of `test_bacdive_lpsn_crossref.py`).
    """
    import inspect
    from pathlib import Path

    from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform

    source = Path(inspect.getsourcefile(BacDiveTransform)).read_text()
    block = source.split("if culture_number_from_external_links:")[1].split("if phys_and_metabolism_enzymes:")[0]
    assert "CLOSE_MATCH_RELATION" in block
    # Subject is the record node and object the deposit node, not the reverse —
    # the record is the thing making the assertion.
    row = block.split("edge_writer.writerow(")[1].split("]")[0]
    assert [line.strip().rstrip(",") for line in row.splitlines() if line.strip() and "[" not in line][:3] == [
        "organism_id",
        "CLOSE_MATCH_PREDICATE",
        "strain_curie",
    ]


def test_bacdive_and_lpsn_land_on_the_same_deposit_curie():
    """
    Both transforms must mint one CURIE per deposit, or the link does not meet.

    LPSN emits `lpsn:<record> close_match kgmicrobe.strain:<code>` and BacDive
    now emits `kgmicrobe.strain:bacdive_<id> close_match kgmicrobe.strain:<code>`.
    They reconcile at merge only while both normalise a deposit string the same
    way, so pin that rather than trusting two copies of the rule to stay equal.
    """
    from kg_microbe.transform_utils.lpsn.lpsn import COL_NOMENCLATURAL_TYPE, LPSNTransform

    lpsn = LPSNTransform.__new__(LPSNTransform)
    for raw in ("ATCC 11775", "DSM 30083", "JCM 1649", "NCTC 9001"):
        bacdive_curie = "kgmicrobe.strain:" + raw.strip().replace(" ", "-").replace(":", "-")
        lpsn_curies = lpsn._extract_strain_curies({COL_NOMENCLATURAL_TYPE: raw})
        assert lpsn_curies == [bacdive_curie], f"{raw}: {lpsn_curies} != [{bacdive_curie}]"


def test_a_collapsed_deposit_is_reported_not_just_counted():
    """
    Coarsening a deposit's taxonomy must leave a trace (#898).

    A collapsed deposit still gets an edge, so it is tempting to treat it as
    resolved and say nothing. But the discarded claim then exists in no artifact
    at all, and nobody can tell that `ATCC 11426` was ever claimed as anything
    more specific than the species now asserted on it.
    """
    resolved, contested = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-11426": {
                "NCBITaxon:1349759": ["1"],
                "NCBITaxon:41276": ["2"],
            }
        },
        ancestors_of=_ancestors,
    )
    assert resolved == [("kgmicrobe.strain:ATCC-11426", "NCBITaxon:41276")]
    rows = deposit_conflict_rows(contested)
    assert rows == [
        [
            "kgmicrobe.strain:ATCC-11426",
            2,
            "NCBITaxon:1349759|NCBITaxon:41276",
            "1|2",
            RESOLUTION_COLLAPSED,
            "NCBITaxon:41276",
        ]
    ]
    # The claim that was dropped is still readable from the row.
    assert "NCBITaxon:1349759" in rows[0][2]


def test_a_deposit_with_one_claim_is_not_in_the_report():
    """The report is about contested deposits; 150k uncontested ones are noise."""
    _, contested = resolve_deposit_parents(
        {"kgmicrobe.strain:DSM-20154": {"NCBITaxon:272240": ["3081"]}},
        ancestors_of=_ancestors,
    )
    assert contested == []


def test_a_suppression_caused_by_unreadable_ancestry_says_so():
    """
    A degraded adapter must not read as a data problem in BacDive (#897).

    With no ancestry, two claims on one lineage look disjoint and the edge is
    suppressed. That is the right precaution, but reporting it as a plain
    conflict blames the source for the ontology's failure.
    """
    _, contested = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-11426": {
                "NCBITaxon:1349759": ["1"],
                "NCBITaxon:41276": ["2"],
            }
        },
        ancestors_of=lambda curie: frozenset(),
        ancestry_failed={"NCBITaxon:1349759"}.__contains__,
    )
    assert [entry[2] for entry in contested] == [RESOLUTION_SUPPRESSED_NO_ANCESTRY]


def test_a_real_conflict_is_not_blamed_on_the_ontology():
    """A working lookup that finds genuine disagreement stays a plain suppression."""
    _, contested = resolve_deposit_parents(
        {
            "kgmicrobe.strain:ATCC-13722": {
                "NCBITaxon:272240": ["3081"],
                "NCBITaxon:1915061": ["7476"],
            }
        },
        ancestors_of=_ancestors,
        ancestry_failed=set().__contains__,
    )
    assert [entry[2] for entry in contested] == [RESOLUTION_SUPPRESSED]
