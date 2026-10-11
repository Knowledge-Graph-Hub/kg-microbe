"""Approved finite BacDive category and same-priority taxid dispositions, offline."""

import copy
import csv
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import isolation_categories as categories
from kg_microbe.transform_utils.bacdive import supplied_taxid_policy as supplied
from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_bacdive_isolation_categories import CATEGORIES, SECTION, _counter
from tests.test_bacdive_taxonomy_evidence import produce, scoped_rows

RESOURCE = Path(__file__).parent / "resources"


def fixture(name):
    """Load saved native excerpts with explicit omitted-section provenance."""
    return json.loads((RESOURCE / name).read_text())["records"]


def policy():
    """Read the exact policy used by production rather than duplicating its decision table."""
    with supplied.POLICY_PATH.open() as stream:
        return supplied.load_policy(stream)


def tax_record(record_id=4427):
    """Retain actual ordered source claims, deposits, classification and citations."""
    return next(
        row["record"] for row in fixture("bacdive_supplied_taxid_approved.json") if row["bacdive_id"] == record_id
    )


def tax_audit(transform):
    """Read the emitted evidence table, not a reconstructed in-memory substitute."""
    with (Path(transform.output_dir) / taxonomy.AUDIT_FILE).open() as stream:
        return [
            row
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if row["kind"] == "supplied_taxid_ambiguity"
        ]


def test_reviewed_policy_is_exactly_97_ambiguities_not_97_proven_errors():
    """Keep the approved finite denominator and separate stronger record-specific evidence."""
    selected = policy()
    assert len(selected["records"]) == 97
    assert len({row["record_id"] for row in selected["records"]}) == 97
    assert Counter(row["priority"] for row in selected["records"]) == {"species": 89, "strain": 8}
    assert all(len(set(row["normalized_priority_ids"])) > 1 for row in selected["records"])
    assert supplied.disposition(tax_record(12996), selected)["biological_contradiction_proven"] is False
    assert supplied.ROLE in BacDiveTransform.REQUIRED_CONSUMED_INPUTS
    assert supplied.POLICY_RELATIVE in BacDiveTransform.DATA_INPUTS


@pytest.mark.parametrize("record_id", [4427, 12996])
@pytest.mark.parametrize("reverse", [False, True])
def test_actual_ordered_and_reversed_claims_withhold_parent_without_erasing_claims(
    tmp_path, monkeypatch, record_id, reverse
):
    """The genuine producer must not promote the first of multiple live priority candidates."""
    record = tax_record(record_id)
    if reverse:
        record["General"]["NCBI tax id"].reverse()
    original = copy.deepcopy(record)
    transform, _, nodes, _ = produce(tmp_path, monkeypatch, [record], gss=False)
    rows = scoped_rows(transform)
    subject = f"kgmicrobe.strain:bacdive_{record_id}"
    assert not [
        row for row in rows if row["predicate"] == "biolink:subclass_of" and row["object"].startswith("NCBITaxon:")
    ]
    assert any(node["id"] == subject for node in nodes)
    assert any(row["subject"] == subject and row["predicate"] == "biolink:close_match" for row in rows)
    [audit] = tax_audit(transform)
    decision = json.loads(audit["lookup_evidence_json"])
    witness = json.loads(audit["native_evidence_json"])
    assert decision["all_supplied_claims"] == original["General"]["NCBI tax id"]
    assert decision["biological_contradiction_proven"] is False
    assert witness["native_record"]["general"] == original["General"]
    assert witness["native_record"]["references"] == original["Reference"]
    assert witness["selected_parent_choice"]["target"] is None
    assert witness["selected_parent_choice"]["inferred"] is False
    assert len(witness["withheld_deposit_contributions"]) == len(witness["native_record"]["deposits"])
    assert audit["emitted_edge_json"] == "null"
    assert json.loads(audit["original_edge_json"])["object"] == decision["original_first_selection"]
    assert record == original


def test_normalized_duplicates_do_not_create_an_ambiguity():
    """Repeated spellings of one canonical identifier do not form distinct candidates."""
    record = tax_record()
    record["General"]["NCBI tax id"] = [
        {"Matching level": "strain", "NCBI tax id": 1322345},
        {"Matching level": "strain", "NCBI tax id": "01322345"},
        {"Matching level": "species", "NCBI tax id": 562},
    ]
    assert supplied.disposition(record, policy()) is None


def test_priority_preserves_unique_strain_over_reviewed_species_candidates():
    """Lower-priority supplied entries neither override nor create strain ambiguity."""
    record = tax_record(12996)
    record["General"]["NCBI tax id"].append({"Matching level": "strain", "NCBI tax id": 20})
    assert supplied.disposition(record, policy()) is None
    record = tax_record()
    record["General"]["NCBI tax id"].append({"Matching level": "species", "NCBI tax id": 30})
    decision = supplied.disposition(record, policy())
    assert decision["priority"] == "strain"
    assert len(decision["normalized_priority_ids"]) == 2
    assert len(decision["all_supplied_claims"]) == 4


def test_policy_near_misses_do_not_expand_reviewed_cohort():
    """Reject changed reviewed candidates and do not broaden the finite record cohort."""
    record = tax_record()
    record["General"]["BacDive-ID"] = 999999
    assert supplied.disposition(record, policy()) is None
    record = tax_record()
    record["General"]["NCBI tax id"][0]["NCBI tax id"] = 20
    with pytest.raises(ValueError, match="candidates changed"):
        supplied.disposition(record, policy())
    with pytest.raises(ValueError, match="policy changed"):
        supplied.load_policy(io.StringIO(supplied.POLICY_PATH.read_text() + "\n"))


def test_actual_deposit_parent_keeps_only_independent_contributor(tmp_path, monkeypatch):
    """Withheld record claims are audited separately from independent deposit support."""
    ambiguous = tax_record()
    ambiguous["External links"] = {"culture collection no.": "TEST SHARED, TEST ONLY, TEST SHARED"}
    other = {
        "General": {"BacDive-ID": 999999, "NCBI tax id": {"NCBI tax id": 20, "Matching level": "strain"}},
        "Name and taxonomic classification": {"species": "Fixture child"},
        "External links": {"culture collection no.": "TEST SHARED"},
    }
    transform, _, _, _ = produce(tmp_path, monkeypatch, [ambiguous, other], gss=False)
    rows = scoped_rows(transform)
    parents = {row["subject"]: row for row in rows if row["predicate"] == "biolink:subclass_of"}
    assert parents["kgmicrobe.strain:TEST-SHARED"]["object"] == "NCBITaxon:20"
    assert parents["kgmicrobe.strain:TEST-SHARED"]["knowledge_level"] == "observation"
    assert "kgmicrobe.strain:TEST-ONLY" not in parents
    assert "kgmicrobe.strain:bacdive_4427" not in parents
    assert transform._taxonomy_evidence_guard.deposit_rows["kgmicrobe.strain:TEST-SHARED"]["claims"] == {
        "NCBITaxon:20": ["999999"]
    }
    [audit] = tax_audit(transform)
    withheld = json.loads(audit["native_evidence_json"])["withheld_deposit_contributions"]
    assert len(withheld) == 3
    assert sum(row["native_token"]["deposit"] == "kgmicrobe.strain:TEST-SHARED" for row in withheld) == 2


def test_withheld_parent_reintroduction_and_lost_policy_role_are_rejected(tmp_path, monkeypatch):
    """Require both output conservation and the exact actual-read policy binding."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [tax_record()], gss=False)
    row = taxonomy._edge("kgmicrobe.strain:bacdive_4427", "NCBITaxon:1322345")
    with Path(transform.output_edge_file).open("a") as stream:
        csv.writer(stream, delimiter="\t").writerow([row.get(column, "") for column in transform.edge_header])
    with pytest.raises(SourceFinalizationRequired, match="scoped taxonomy row"):
        transform._taxonomy_evidence_guard.verify_output(transform.output_dir, quoting=csv.QUOTE_MINIMAL)
    snapshots = copy.deepcopy(transform.consumed_input_snapshots)
    snapshots.pop(supplied.ROLE)
    with pytest.raises(SourceFinalizationRequired, match="consumed input role"):
        transform._taxonomy_evidence_guard.verify_native(snapshots)


def test_withholding_replays_through_fresh_finalization(tmp_path, monkeypatch, local_source_schema):
    """A new producer instance must reconstruct the withheld source claims exactly."""
    record = tax_record()
    # This fixture avoids unrelated external taxon closure; scientific native claims remain literal.
    record["External links"] = {"culture collection no.": "TEST ONLY"}
    transform, _, _, _ = produce(tmp_path, monkeypatch, [record], gss=False)
    report = transform.finalize()
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()


def test_actual_agriculture_all_ten_combinations_preserve_other_assertions(tmp_path, monkeypatch):
    """Actual writers preserve all nonselected rows and both repeated native positions."""
    records = [row["record"] for row in fixture("bacdive_agriculture_approved.json")]
    original = copy.deepcopy(records)
    baseline = copy.deepcopy(records)
    positions = []
    for record in baseline:
        blocks = record[SECTION][CATEGORIES]
        blocks = blocks if isinstance(blocks, list) else [blocks]
        for index, block in enumerate(blocks):
            if block.get("Cat2") == "#Agriculture":
                positions.append((record["General"]["BacDive-ID"], index, block.get("Cat3")))
                block.pop("Cat2")
    assert len({row[2] for row in positions}) == 10
    assert sum(row[0] == 158499 for row in positions) == 2
    candidate_dir, baseline_dir = tmp_path / "candidate", tmp_path / "baseline"
    candidate_dir.mkdir()
    baseline_dir.mkdir()
    _, before_edges, before_nodes, _ = produce(baseline_dir, monkeypatch, baseline, gss=False)
    monkeypatch.undo()
    transform, edges, nodes, audit = produce(candidate_dir, monkeypatch, records, gss=False)
    selected = [row for row in audit if row["raw_value"] == "#Agriculture"]
    assert len(selected) == len(positions)
    ids = {row["attribute_id"] for row in selected}
    assert len(ids) == len(positions)
    assert not any("ENVO:01001442" in (row["subject"], row["object"]) for row in edges)
    assert not any("agriculture" in row["id"].lower() for row in nodes)
    assert _counter(row for row in edges if row["object"] not in ids) == _counter(before_edges)
    # Attribute type can already be emitted by another retained category in either arm.
    assert _counter(row for row in nodes if row["id"] not in ids | {categories.ATTRIBUTE_TYPE}) == _counter(
        row for row in before_nodes if row["id"] != categories.ATTRIBUTE_TYPE
    )
    source = {str(record["General"]["BacDive-ID"]): record for record in records}
    for row in selected:
        native = source[row["organism_id"].rsplit("_", 1)[1]]
        assert json.loads(row["source_record_json"]) == native
        assert json.loads(row["source_isolation_json"]) == native[SECTION]
        assert json.loads(row["source_category_json"])["Cat1"] == "#Engineered"
        assert row["native_authority_sha256"] == "c3c288b9d95cf1e62b0146bcb2a365bdbd294b0072bbf2efab8819e5db8fff2b"
        assert json.loads(row["original_edge_json"])["subject"] == "ENVO:01001442"
        assert json.loads(row["emitted_edge_json"])["predicate"] == "biolink:has_attribute"
        assert json.loads(row["emitted_edge_json"])["knowledge_level"] == "observation"
    assert records == original
    transform.verify_native_inputs()


@pytest.mark.parametrize("damage", ["case", "space", "field", "context"])
def test_agriculture_near_matches_refuse_instead_of_minting_location(tmp_path, monkeypatch, damage):
    """Exact source field, literal and Engineered context are part of the approved scope."""
    record = next(row["record"] for row in fixture("bacdive_agriculture_approved.json") if row["bacdive_id"] == 158499)
    block = {"Cat1": "#Engineered", "Cat2": "#Agriculture"}
    if damage == "case":
        block["Cat2"] = "#agriculture"
    elif damage == "space":
        block["Cat2"] += " "
    elif damage == "field":
        block["Cat3"] = block.pop("Cat2")
    else:
        block["Cat1"] = "#Natural"
    record[SECTION][CATEGORIES] = [block]
    with pytest.raises(ValueError, match="(?i:scope|category)"):
        produce(tmp_path, monkeypatch, [record], gss=False)
