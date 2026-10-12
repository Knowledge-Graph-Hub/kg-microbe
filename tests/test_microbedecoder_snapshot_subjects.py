"""Approved finite snapshot relocation, actual writers and read-only admission."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.microbedecoder_join_fixtures import prepare
from tests.test_microbedecoder_bacdive_join_dispositions import _native_report, _rows, _write

FIXTURE = Path(__file__).parent / "resources/microbedecoder/bacdive_snapshot_subjects.json"
SELECTED = {2256, 9713, 10524, 12563, 14251, 21239}
UNCERTAIN = {7603, 12967, 14545, 17767}
CONTROLS = {2395, 3296, 21027, 18842}
PREFIX = "kgmicrobe.source_record:microbedecoder_bacdive_"


def _counter(rows):
    """Compare complete rows, not lossy triples or counts alone."""
    return Counter(json.dumps(row, sort_keys=True) for row in rows)


def _native(tmp_path, monkeypatch, *, selected=True):
    """Run only fourteen saved records, with explicit synthetic authority admission."""
    fixture = json.loads(FIXTURE.read_text())
    positions = tuple(index for index, case in enumerate(fixture["cases"], 1) if case["md_record"] in SELECTED)
    transform, raw, _, _, _ = prepare(
        tmp_path, monkeypatch, selected=positions if selected else (), native_cases=fixture["cases"]
    )
    transform.run(raw)
    source_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    records = {
        case["md_record"]: f"sha256:{source_hash}#record={index}" for index, case in enumerate(fixture["cases"], 1)
    }
    return transform, records, fixture


def test_exact_saved_cohort_has_195_values_and_25_dependent_audits():
    """Pin the saved small cohort and unchanged six native scientific records."""
    assert (
        hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        == "ae4532263d576d5b4968504157fb429b49d2d8dbad52b246b15af6a4249d4856"
    )
    saved = json.loads(FIXTURE.read_text())
    assert set(saved["selected_records"]) == SELECTED
    assert {case["md_record"] for case in saved["cases"]} == SELECTED | UNCERTAIN | CONTROLS
    evidence_path = joins.DEFAULT_POLICY.parent / "microbedecoder_bacdive_join_evidence.json"
    assert hashlib.sha256(joins.DEFAULT_POLICY.read_bytes()).hexdigest() == joins.POLICY_SHA256
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == joins.EVIDENCE_SHA256
    evidence = {case["ordinal"]: case for case in json.loads(evidence_path.read_text())["cases"]}
    selected = [case for case in saved["cases"] if case["md_record"] in SELECTED]
    assert [len(case["snapshot_rows"]) for case in selected] == [37, 34, 34, 31, 0, 59]
    assert sum(len(case["snapshot_rows"]) for case in selected) == 195
    audits = [row for case in selected for row in case["phenotype_audits"]]
    assert sum(row["source_column"].startswith("BacDive_") for row in audits) == 25
    assert sum(row["source_column"] == "FAPROTAX_Type_of_metabolism" for row in audits) == 4
    for case in selected:
        assert case["native_row"] == evidence[case["md_record"]]["native_md_row"]


def test_actual_native_writers_move_only_195_subjects_and_25_audits(tmp_path, monkeypatch):
    """Keep complete same-candidate rows, independent fields, four uncertain joins and four controls."""
    baseline, base_records, _ = _native(tmp_path / "baseline", monkeypatch, selected=False)
    before = _rows(baseline.output_edge_file)
    before_nodes = _rows(baseline.output_node_file)
    before_audits = _rows(baseline.output_dir / "phenotype_normalizations.tsv")
    candidate, records, fixture = _native(tmp_path / "candidate", monkeypatch)
    assert records == base_records
    selected_records = {records[number] for number in SELECTED}
    node_ids = {record: PREFIX + hashlib.sha256(record.encode()).hexdigest() for record in selected_records}
    expected, moved, omitted = [], 0, 0
    for row in before:
        if row["source_record"] in selected_records:
            if row["subject"].startswith("kgmicrobe.strain:bacdive_"):
                omitted += 1
                continue
            if row["source_column"].startswith("BacDive_"):
                row = {**row, "subject": node_ids[row["source_record"]]}
                moved += 1
        expected.append(row)
    assert (moved, omitted) == (195, 6)
    assert _counter(_rows(candidate.output_edge_file)) == _counter(expected)
    after_nodes = _rows(candidate.output_node_file)
    new_nodes = [row for row in after_nodes if row["id"].startswith(PREFIX)]
    assert len(new_nodes) == 5
    assert {row["category"] for row in new_nodes} == {"biolink:InformationContentEntity"}
    assert node_ids[records[14251]] not in {row["id"] for row in new_nodes}
    assert _counter(row for row in after_nodes if not row["id"].startswith(PREFIX)) == _counter(before_nodes)
    expected_audits, dependent, independent = [], 0, 0
    for row in before_audits:
        if row["source_record"] in selected_records:
            if row["source_column"].startswith("BacDive_"):
                row = {**row, "subject": node_ids[row["source_record"]]}
                dependent += 1
            else:
                assert row["source_column"] == "FAPROTAX_Type_of_metabolism"
                independent += 1
        expected_audits.append(row)
    assert (dependent, independent) == (25, 4)
    assert _counter(_rows(candidate.output_dir / "phenotype_normalizations.tsv")) == _counter(expected_audits)
    # Saved historical full snapshot payloads supply an independent writer oracle.
    for case in fixture["cases"]:
        historical = []
        for row in case["snapshot_rows"]:
            record = records[case["md_record"]]
            subject = node_ids[record] if case["md_record"] in SELECTED else "lpsn:" + case["native_row"]["LPSN_ID"]
            assert all(not value for key, value in row.items() if key not in candidate.edge_header)
            historical.append(
                {
                    **{key: row.get(key, "") for key in candidate.edge_header},
                    "source_record": record,
                    "subject": subject,
                }
            )
        actual = [
            row
            for row in expected
            if row["source_record"] == records[case["md_record"]] and row["source_column"].startswith("BacDive_")
        ]
        assert _counter(actual) == _counter(historical)
    contract = candidate.producer_native_inputs[joins.CONTRACT_KEY]
    assert (contract["snapshot_nodes"], contract["snapshot_occurrences"]) == (5, 195)
    candidate.verify_native_inputs()
    joins.verify_recorded_inputs(_native_report(candidate), candidate.output_dir / "source_finalization.json").verify()


@pytest.mark.parametrize(
    "mutation",
    [
        "old_subject",
        "value",
        "missing",
        "duplicate",
        "lost_locator",
        "identity_link",
        "node_category",
        "missing_node",
        "audit_original_subject",
        "audit_faprotax_subject",
        "audit_missing",
    ],
)
def test_complete_snapshot_output_rejoin_refuses_repaired_receipts(tmp_path, monkeypatch, mutation):
    """A refreshed file checksum cannot legitimize wrong subjects or lost original evidence."""
    transform, records, _ = _native(tmp_path, monkeypatch)
    path = transform.output_edge_file
    rows = _rows(path)
    snapshot = next(row for row in rows if row["subject"].startswith(PREFIX))
    if mutation == "old_subject":
        snapshot["subject"] = "lpsn:789848"
    elif mutation == "value":
        snapshot["value"] += " changed"
    elif mutation == "missing":
        rows.remove(snapshot)
    elif mutation == "duplicate":
        rows.append(dict(snapshot))
    elif mutation == "lost_locator":
        snapshot["source_record"] = ""
    elif mutation == "identity_link":
        rows.append({**snapshot, "object": "lpsn:789848", "predicate": "biolink:same_as", "source_column": ""})
    elif mutation.startswith("node_") or mutation == "missing_node":
        path, rows = transform.output_node_file, _rows(transform.output_node_file)
        node = next(row for row in rows if row["id"].startswith(PREFIX))
        if mutation == "missing_node":
            rows.remove(node)
        else:
            node["category"] = "biolink:OrganismTaxon"
    else:
        path = transform.output_dir / "phenotype_normalizations.tsv"
        rows = _rows(path)
        dependent = next(row for row in rows if row["subject"].startswith(PREFIX))
        if mutation == "audit_original_subject":
            dependent["subject"] = "lpsn:789848"
        elif mutation == "audit_missing":
            rows.remove(dependent)
        else:
            independent = next(
                row
                for row in rows
                if row["source_record"] == records[2256] and row["source_column"] == "FAPROTAX_Type_of_metabolism"
            )
            independent["subject"] = dependent["subject"]
    _write(path, rows, list(rows[0]))
    with pytest.raises(SourceFinalizationRequired):
        joins.verify_recorded_inputs(_native_report(transform), transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize("member", ["nodes.tsv", "phenotype_normalizations.tsv"])
def test_retained_admission_binds_snapshot_nodes_and_phenotype_audit(tmp_path, monkeypatch, member):
    """Newly required evidence remains byte-bound after the initial recorded rejoin."""
    transform, _, _ = _native(tmp_path, monkeypatch)
    report = _native_report(transform)
    admission = joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
    path = transform.output_dir / member
    rows = _rows(path)
    if member == "nodes.tsv":
        row = next(row for row in rows if row["id"].startswith(PREFIX))
        row["category"] = "biolink:OrganismTaxon"
    else:
        row = next(row for row in rows if row["subject"].startswith(PREFIX))
        row["subject"] = "lpsn:789848"
    _write(path, rows, list(rows[0]))
    with pytest.raises(SourceFinalizationRequired):
        admission.verify()


@pytest.mark.parametrize(
    ("member", "collection"),
    [("nodes.tsv", "members"), ("phenotype_normalizations.tsv", "producer_audit_members")],
)
def test_recorded_report_cannot_omit_snapshot_member_identity(tmp_path, monkeypatch, member, collection):
    """A semantically valid file still needs its original member/audit receipt."""
    transform, _, _ = _native(tmp_path, monkeypatch)
    report = _native_report(transform)
    report[collection].pop(member)
    with pytest.raises(SourceFinalizationRequired, match="source output/audit identity"):
        joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
