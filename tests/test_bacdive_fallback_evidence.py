"""Prospective native reader/lifecycle controls for #1364; NOT executed during W freeze."""

import copy
import sqlite3

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive.fallback_evidence import (
    SELECTED_ROLE,
    FallbackEvidence,
    recorded_selected_opener,
)
from kg_microbe.transform_utils.bacdive.taxonomy_evidence import RAW_ROLE
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.bacdive_fallback_fixtures import records_by_id, stage


def test_all93_native_controls_use_actual_owned_query_routes(tmp_path):
    """59 higher-rank fields,4 Archaea,6 special,16 cache-only,5 provisional and3 anchors remain distinct."""
    native = records_by_id()
    ordered = sorted(native.values(), key=lambda entry: entry["native_array_index"])
    records = [entry["record"] for entry in ordered]
    _, guard, _, snapshots, _, _ = stage(tmp_path, records)
    plans = {value["native_record"]["record_id"]: value for value in guard.contract["plans"].values()}
    assert len(plans) == 93
    assert plans["175523"]["status"] == "terminal_rejection"
    assert plans["175523"]["parent_pairs"] == plans["175523"]["provisional_nodes"] == []
    assert [row["decision"]["query"] for row in plans["175523"]["lookups"]] == ["Moorella carbonis", "Moorella"]
    assert {
        value["native_record"]["record_id"]
        for value in plans.values()
        if value["status"] == "unresolved_provisional_genus"
    } == {"24851", "24824", "132750", "132822", "161357"}
    assert sum(value["status"] == "unresolved_unparseable_name" for value in plans.values()) == 16
    assert sum(value["status"] == "accepted_special" for value in plans.values()) == 6
    for key in ("132972", "162619", "168532", "175525"):
        assert plans[key]["early_target"]
        assert plans[key]["lookups"][-1]["decision"]["candidates"][0]["native_prokaryote_domains"] == ["NCBITaxon:2157"]
    higher = [
        plan
        for plan in plans.values()
        if plan["early_target"]
        and plan["lookups"][-1]["decision"]["source_field"] == "genus"
        and not plan["lookups"][-1]["decision"]["candidates"][0]["source_field_matches_native_rank"]
    ]
    assert len(higher) == 59
    assert all(not plan["provisional_nodes"] for plan in higher)
    guard.verify(snapshots)
    query = guard.contract["native_queries"]
    assert query["connection"]["computed_queries"] == []
    physical = [(row["kind"], row["parameter"]) for row in query["physical_queries"]]
    assert len(physical) == len(set(physical))
    assert query["exact_label_batch"]["native_statements_scanned"] > 0
    assert all(kind == "declaration" for kind, _ in physical)


@pytest.mark.parametrize(
    "records",
    [[], [{"General": {"BacDive-ID": 1, "NCBI tax id": {"NCBI tax id": 2}}}], [{"General": {"BacDive-ID": 1}}]],
)
def test_truthful_zero_is_derived_from_actual_native_source(tmp_path, monkeypatch, records):
    """No observed name-query demand needs a fallback DB or selected-label read."""
    from kg_microbe.transform_utils.bacdive.fallback_native_authority import FreshFallbackAuthority

    def forbidden(*args, **kwargs):
        """Refuse any authority construction for the actual empty native cohort."""
        raise AssertionError("zero source selected a fallback native authority")

    monkeypatch.setattr(FreshFallbackAuthority, "from_resolved_adapter", forbidden)
    _, guard, _, snapshots, _, _ = stage(tmp_path, records)
    assert guard.contract["native_queries"] is None
    assert guard.contract["selected_input"] is None
    assert SELECTED_ROLE not in snapshots
    guard.verify(snapshots)
    snapshots[SELECTED_ROLE] = {"path": "forged", "sha256": "0" * 64}
    with pytest.raises(SourceFinalizationRequired):
        guard.verify(snapshots)


@pytest.mark.parametrize(
    "damage", ["role", "native_bytes", "selected_bytes", "reader", "plans", "parser_binding", "absence_guard"]
)
def test_original_live_native_contract_cannot_be_erased_or_rebased(tmp_path, damage):
    """Reject changed original native/query/role obligations rather than accepting current cache state."""
    record = records_by_id()["175523"]["record"]
    _, guard, _, snapshots, nodes, database = stage(tmp_path, [record], selected=damage != "absence_guard")
    if damage == "role":
        snapshots.pop(SELECTED_ROLE)
    elif damage == "native_bytes":
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE statements SET value='different' WHERE subject='NCBITaxon:216400' AND predicate='rdfs:label'"
            )
    elif damage == "selected_bytes":
        nodes.write_bytes(nodes.read_bytes() + b"\n")
    elif damage == "reader":
        guard._owner = None
    elif damage == "plans":
        guard._plans = "{}"
    elif damage == "parser_binding":
        from pathlib import Path

        path = Path(guard.contract["parser_implementation"]["path"]).resolve()
        del guard.admission.identities[path]
    else:
        guard.admission.absent.remove(nodes.resolve())
    with pytest.raises(SourceFinalizationRequired):
        guard.verify(snapshots)


@pytest.mark.parametrize("damage", [None, "zero", "partial", "candidate", "qualifier", "selected_role"])
def test_recorded_child_rejoins_original_source_not_restamped_choices(tmp_path, damage):
    """Recompute actual selected decisions independently of a mutually restamped finite report."""
    native = records_by_id()
    _, guard, entries, snapshots, _, _ = stage(tmp_path, [native["175523"]["record"], native["134696"]["record"]])
    recorded = copy.deepcopy(guard.contract)
    if damage == "zero":
        recorded["plans"] = {}
        recorded["eligible_record_count"] = 0
        recorded["native_queries"] = None
    elif damage == "partial":
        recorded["plans"].pop("0")
        recorded["eligible_record_count"] -= 1
    elif damage == "candidate":
        recorded["plans"]["0"]["early_target"] = "NCBITaxon:44260"
    elif damage == "qualifier":
        recorded["plans"]["0"]["native_record"]["references"] = {}
    elif damage == "selected_role":
        snapshots.pop(SELECTED_ROLE)
    admission = SourceAdmission()

    def rejoin():
        """Reconstruct the child from its original native records and consumed inputs."""
        return FallbackEvidence(
            entries,
            snapshots,
            raw_role=RAW_ROLE,
            selected_path=recorded["selected_input"]["locator"],
            opener=lambda role, path: recorded_selected_opener(snapshots, admission, role, path),
            recorded=recorded,
            admission=admission,
        )

    if damage is None:
        fresh = rejoin()
        assert fresh.contract == guard.contract
        fresh.verify(snapshots)
    else:
        with pytest.raises(SourceFinalizationRequired):
            rejoin()


@pytest.mark.parametrize("later", [7, ["malformed", "unused"], {"ignored": True}])
def test_unvisited_malformed_later_field_does_not_drop_a_valid_parent(tmp_path, later):
    """Preserve a valid earlier choice without eagerly validating an unused lower-rank field."""
    record = {
        "General": {"BacDive-ID": 99},
        "Name and taxonomic classification": {"species": "Bacteria", "genus": later, "full scientific name": None},
    }
    _, guard, _, _, _, _ = stage(tmp_path, [record])
    assert guard.plan(0)["early_target"] == "NCBITaxon:2"
    assert len(guard.plan(0)["lookups"]) == 1


def test_cache_cannot_hide_a_different_source_native_choice(tmp_path):
    """Retain distinct selector contexts and reject a later cache substitution."""
    native = records_by_id()
    _, guard, _, _, _, _ = stage(tmp_path, [native["18491"]["record"], native["134696"]["record"]])
    cache = {}
    first = guard.select_ordinary(0, cache)
    second = guard.select_ordinary(1, cache)
    assert first[0] == "NCBITaxon:2"
    assert second[0] not in {None, "NCBITaxon:2"}
    assert guard.select_ordinary(1, cache) == second
    key = next(key for key, value in cache.items() if value == second[0])
    cache[key] = "NCBITaxon:2"
    with pytest.raises(SourceFinalizationRequired):
        guard.select_ordinary(1, cache)
