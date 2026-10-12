"""Unexecuted #1364 scientific compatibility draft; full producer integration remains separate."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive.fallback_selection import assess_candidates

FIXTURE = Path(__file__).parent / "resources/bacdive_fallback/native_compatibility.json"


def _native():
    """Read the honestly extracted full72-record/native-statement fixture, not a fabricated DB epoch."""
    assert (
        hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        == "fcb19469ed9c98719a60eb8670bb449a583dedb63301bf06fbcca01dfde19916"
    )
    payload = json.loads(FIXTURE.read_text())
    assert len(payload["records"]) == 72
    assert payload["origin"]["raw"]["sha256"] == "57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2"
    assert (
        payload["origin"]["native_db"]["sha256"] == "8474ba4f4c341b8578ac10d5661b315be8a3c6f0687b4d2e7e61b55e34faea34"
    )
    for value in payload["records"].values():
        native = value["source_context"]
        encoded = json.dumps(native["record"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert hashlib.sha256(encoded.encode()).hexdigest() == native["canonical_record_sha256"]
        assert native["native_array_index"] == value["original_assertion"]["native_array_index"]
    return payload


def _facts(payload, identifier):
    """Independently assemble native facts from literal SQL statements, without the production reader."""
    declarations, stack = {}, [identifier]
    while stack:
        subject = stack.pop()
        if subject in declarations:
            continue
        statements = payload["literal_native_declarations"][subject]
        assert all(row["subject"] == subject for row in statements)
        declarations[subject] = statements
        stack.extend(row["object"] for row in statements if row["predicate"] == "rdfs:subClassOf")
    own = declarations[identifier]
    return {
        "id": identifier,
        "labels": sorted({row["value"] for row in own if row["predicate"] == "rdfs:label"}),
        "synonyms": sorted(
            {
                row["value"]
                for row in own
                if row["predicate"].startswith("oio:has") and row["predicate"].endswith("Synonym")
            }
        ),
        "ranks": sorted(
            {row["object"].split(":", 1)[1] for row in own if row["predicate"] == "obo:ncbitaxon#has_rank"}
        ),
        "types": sorted({row["object"] for row in own if row["predicate"] == "rdf:type"}),
        "deprecated": any(
            str(row["value"]).lower() in {"true", "1"} for row in own if row["predicate"] == "owl:deprecated"
        ),
        "ancestors": sorted(set(declarations) - {identifier}),
        "complete_native_declarations": declarations,
    }


def test_all59_misnamed_source_fields_keep_actual_native_parents_without_genus_claims():
    """All59 literal inputs support their existing native parent, not a fabricated field rank."""
    payload = _native()
    cases = [row for row in payload["records"].values() if "source_genus_field_native_higher_rank" in row["kinds"]]
    assert len(cases) == 59
    counts = {"order": 0, "family": 0}
    for row in cases:
        source = row["source_context"]["record"]["Name and taxonomic classification"]
        target = row["original_assertion"]["source_row"]["object"]
        candidate = _facts(payload, target)
        assert candidate["ranks"] in [["order"], ["family"]]
        counts[candidate["ranks"][0]] += 1
        decision = assess_candidates(
            source["genus"], "genus", source, [candidate], match_mode="selected_label_casefold"
        )
        assert decision.identifier == target and not decision.terminal
        audit = json.loads(decision.evidence_json)
        assert audit["candidates"][0]["source_field_matches_native_rank"] is False
        assert audit["candidates"][0]["candidate"]["ranks"] == candidate["ranks"]
        # The same native order/family cannot justify constructing a genus's
        # provisional species merely because the source put it in that field.
        construction = assess_candidates(
            source["genus"], "genus", source, [candidate], route="parsed_genus", match_mode="selected_label_casefold"
        )
        assert construction.identifier is None and construction.terminal
        assert construction.status == "native_rank_cannot_support_constructed_hierarchy"
    assert counts == {"order": 46, "family": 13}


def test_native_moorella_wasp_is_terminal_without_bacterial_alternative():
    """The complete175523 source context cannot turn genus homonymy into bacterial identity."""
    payload = _native()
    row = payload["records"]["175523"]
    source = row["source_context"]["record"]["Name and taxonomic classification"]
    candidate = _facts(payload, "NCBITaxon:216400")
    assert candidate["labels"] == ["Moorella"] and candidate["ranks"] == ["genus"]
    assert {"NCBITaxon:7399", "NCBITaxon:50557", "NCBITaxon:2759"} <= set(candidate["ancestors"])
    assert "NCBITaxon:2" not in candidate["ancestors"]
    decision = assess_candidates("Moorella", "genus", source, [candidate])
    assert decision.identifier is None and decision.terminal
    assert decision.status == "outside_or_ambiguous_prokaryote_domain"
    assert json.loads(decision.evidence_json)["automatic_replacement"] is False
    assert json.loads(decision.evidence_json)["source_classification"] == source


@pytest.mark.parametrize("record_id", ["132972", "162619", "168532", "175525"])
def test_all_four_archaeal_records_preserve_native_domain_and_parent(record_id):
    """Do not accidentally make Bacteria the only allowable domain."""
    payload = _native()
    row = payload["records"][record_id]
    attempt = row["uncached_rank_attempts"][-1]
    source = row["source_context"]["record"]["Name and taxonomic classification"]
    candidate = _facts(payload, row["original_assertion"]["source_row"]["object"])
    assert source["domain"] == "Archaea" and "NCBITaxon:2157" in candidate["ancestors"]
    decision = assess_candidates(
        attempt["value"], attempt["field"], source, [candidate], match_mode="selected_label_casefold"
    )
    assert decision.identifier == candidate["id"]
    contradictory = {**source, "domain": "Bacteria"}
    refusal = assess_candidates(
        attempt["value"], attempt["field"], contradictory, [candidate], match_mode="selected_label_casefold"
    )
    assert refusal.identifier is None and refusal.status == "native_domain_conflicts_with_source"


def test_domain_anchor_is_eligible_without_being_its_own_ancestor():
    """The reflexive candidate is included only for domain membership, not forged as a parent edge."""
    payload = _native()
    candidate = _facts(payload, "NCBITaxon:2")
    assert "NCBITaxon:2" not in candidate["ancestors"]
    decision = assess_candidates("Bacteria", "domain", {"domain": "Bacteria"}, [candidate])
    assert decision.identifier == "NCBITaxon:2"
    assert json.loads(decision.evidence_json)["candidates"][0]["native_prokaryote_domains"] == ["NCBITaxon:2"]


def test_selected_fast_casefold_does_not_claim_native_case_insensitive_database_search():
    """Keep the old fast-label route's case behavior and distinguish native exact SQL fallback."""
    payload = _native()
    row = payload["records"]["134696"]
    candidate = _facts(payload, row["native_candidates"][0]["id"])
    original = candidate["labels"][0]
    lower = original.lower()
    assert lower != original
    selected = assess_candidates(lower, "genus", {}, [candidate], match_mode="selected_label_casefold")
    assert selected.identifier == candidate["id"]
    exact = assess_candidates(lower, "genus", {}, [candidate], match_mode="native_exact_label")
    assert exact.identifier is None and exact.status == "native_label_does_not_match_actual_query"


@pytest.mark.parametrize("defect", ["duplicate_label", "deprecated", "wrong_type", "two_ranks", "no_rank"])
def test_synthetic_corrupt_or_ambiguous_candidate_is_not_first_hit_identity(defect):
    """Negative variants are explicit synthetic mutations, never relabelled as native witnesses."""
    payload = _native()
    row = payload["records"]["134696"]
    candidate = copy.deepcopy(_facts(payload, row["native_candidates"][0]["id"]))
    query = candidate["labels"][0]
    candidates = [candidate]
    if defect == "duplicate_label":
        second = copy.deepcopy(candidate)
        second["id"] = "NCBITaxon:999999999"
        candidates.append(second)
    elif defect == "deprecated":
        candidate["deprecated"] = True
    elif defect == "wrong_type":
        candidate["types"] = ["owl:ObjectProperty"]
    elif defect == "two_ranks":
        candidate["ranks"] = ["genus", "family"]
    else:
        candidate["ranks"] = []
    decision = assess_candidates(query, "genus", {}, candidates)
    assert decision.identifier is None and decision.terminal


def test_existing_six_special_routes_keep_native_higher_rank_without_becoming_genus():
    """Rhizobiales, Planctomycetia and the three actinobacteria retain separate reviewed routes."""
    payload = _native()
    cases = [row for row in payload["records"].values() if "existing_special_higher_rank" in row["kinds"]]
    assert len(cases) == 6
    for row in cases:
        target = row["original_assertion"]["source_row"]["object"]
        candidate = _facts(payload, target)
        query = {
            "NCBITaxon:356": "Rhizobiales",
            "NCBITaxon:203683": "Planctomycetia",
            "NCBITaxon:201174": "Actinobacteria",
        }[target]
        source = row["source_context"]["record"]["Name and taxonomic classification"]
        decision = assess_candidates(
            query,
            "genus",
            source,
            [candidate],
            route="special_higher_rank",
            match_mode="special_selected_name_casefold",
        )
        assert decision.identifier == target
        assert candidate["ranks"][0] in {"order", "class", "phylum"}
        assert decision.identifier not in {"kgmicrobe.genus:Rhizobiales", "kgmicrobe.genus:Planctomycetia"}
