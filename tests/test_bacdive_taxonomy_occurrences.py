"""Preserve native BacDive occurrences without changing source IDs or full-row graph deduplication."""

import copy
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    INFERRED_SUBCLASS_RELATION,
    MANUAL_AGENT,
    OBSERVATION,
    PREDICTION,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.test_bacdive_taxonomy_evidence import produce, scoped_rows

SUBJECT = "kgmicrobe.strain:bacdive_1"
CLASSIFICATION = "Name and taxonomic classification"


def _json(value):
    """Encode full scientific rows with the documented deterministic native projection dialect."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    """Independently bind complete fixture records, not only taxonomy-selected fields."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _record(target=10, *, inferred=False, blank=False, deposit=None, lpsn=None):
    """Construct explicitly synthetic repeated-ID controls on the existing tiny real SQL authority."""
    record = {"General": {"BacDive-ID": 1}}
    if blank:
        return record
    if inferred:
        label = {10: "Fixture ancestor", 20: "Fixture child"}[target]
        record[CLASSIFICATION] = {"species" if target == 20 else "genus": label, "full scientific name": label}
    else:
        record["General"]["NCBI tax id"] = {"NCBI tax id": target, "Matching level": "strain"}
    if lpsn:
        record.setdefault(CLASSIFICATION, {})["LPSN"] = {"species": lpsn}
    if deposit:
        record["External links"] = {"culture collection no.": deposit}
    return record


def _expected(target, *, inferred=False, subject=SUBJECT, original_object=""):
    """Spell out the complete supported row independently of the guard's expected-row builder."""
    return {
        "subject": subject,
        "predicate": SUBCLASS_PREDICATE,
        "object": "NCBITaxon:" + str(target),
        "relation": INFERRED_SUBCLASS_RELATION if inferred else RDFS_SUBCLASS_OF,
        "primary_knowledge_source": "infores:bacdive",
        "knowledge_level": PREDICTION if inferred else OBSERVATION,
        "agent_type": AUTOMATED_AGENT if inferred else MANUAL_AGENT,
        "value": "",
        "unit": "",
        "publications": "https://bacdive.dsmz.de/strain/1" if subject == SUBJECT else "",
        "original_object": original_object,
    }


def _filled(row):
    """Ignore only empty schema-added fields, retaining every nonempty value and its multiplicity."""
    return _json({key: value for key, value in row.items() if value != ""})


def _parents(rows):
    """Select only the repeated record's native-taxonomy parent family."""
    return [
        row
        for row in rows
        if row["subject"] == SUBJECT
        and row["predicate"] == SUBCLASS_PREDICATE
        and row["object"].startswith("NCBITaxon:")
    ]


def _identity(path):
    """Restamp an outer byte receipt without manufacturing an original native read."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, rows, header):
    """Retain the actual finalized quote-none dialect and honest empty audit headers."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _paths(transform):
    """Use the public generic finalized-source entry point with both real graph members."""
    return [transform.output_node_file, transform.output_edge_file]


@pytest.mark.parametrize("dictionary", [False, True], ids=["list", "dictionary"])
@pytest.mark.parametrize("kind", ["blank", "direct", "fallback", "mixed-same", "mixed-different"])
def test_actual_run_preserves_each_native_occurrence_and_exact_distinct_rows(tmp_path, monkeypatch, dictionary, kind):
    """Equal source IDs retain coordinates and choices while only identical full graph rows coalesce."""
    if kind == "blank":
        records, expected = [_record(blank=True), _record(blank=True)], []
    elif kind == "direct":
        records, expected = [_record(), _record()], [_expected(10)]
    elif kind == "fallback":
        records, expected = [_record(inferred=True), _record(inferred=True)], [_expected(10, inferred=True)]
    else:
        direct_target = 10 if kind == "mixed-same" else 20
        records = [_record(direct_target), _record(inferred=True)]
        expected = [_expected(direct_target), _expected(10, inferred=True)]
    payload = {"original/key-9": records[0], "original/key-2": records[1]} if dictionary else records
    original = copy.deepcopy(payload)
    transform, _, nodes, _ = produce(tmp_path, monkeypatch, payload, gss=False)
    assert payload == original
    guard = transform._taxonomy_evidence_guard
    assert len(guard.records) == guard.contract["native_records"] == 2
    assert set(guard.parent_choices) == {0, 1}
    assert [row["record_id"] for row in guard.records] == ["1", "1"]
    assert [row["source_coordinate"] for row in guard.records] == (
        ["original/key-9", "original/key-2"] if dictionary else [0, 1]
    )
    assert [row["record_sha256"] for row in guard.records] == [_digest(record) for record in records]
    assert [guard.parent_choices[index]["ordinal"] for index in (0, 1)] == [0, 1]
    actual = _parents(scoped_rows(transform))
    assert Counter(map(_filled, actual)) == Counter(map(_filled, expected))
    assert len([row for row in nodes if row["id"] == SUBJECT]) == 1
    child = guard.contract["fallback_native_evidence"]
    eligible = [index for index, record in enumerate(records) if "NCBI tax id" not in record["General"]]
    assert child["eligible_record_count"] == len(eligible)
    assert set(child["plans"]) == {str(index) for index in eligible}
    assert [row["ordinal"] for row in guard.contract["fallback_choices"]] == eligible
    if kind in {"blank", "direct"}:
        assert child["native_queries"] is None and child["selected_input"] is None


@pytest.mark.parametrize("direct_target", [10, 20])
def test_repeated_tokens_join_exact_occurrences_without_id_cartesian_products(tmp_path, monkeypatch, direct_target):
    """The legacy resolver lists stay exact while each audit contributor keeps its own native record."""
    deposit = "TEST OCCURRENCE, TEST OCCURRENCE"
    records = [_record(direct_target, deposit=deposit), _record(inferred=True, deposit=deposit)]
    records.append(copy.deepcopy(records[1]))
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False)
    guard = transform._taxonomy_evidence_guard
    subject = "kgmicrobe.strain:TEST-OCCURRENCE"
    expected_claims = (
        {"NCBITaxon:10": ["1"] * 6} if direct_target == 10 else {"NCBITaxon:20": ["1", "1"], "NCBITaxon:10": ["1"] * 4}
    )
    assert guard.native_deposit_claims() == {subject: expected_claims}
    audits = [row for row in graph_rows(transform.output_dir / taxonomy.AUDIT_FILE) if row["kind"] == "deposit"]
    assert len(audits) == 1
    contributors = json.loads(audits[0]["native_evidence_json"])["claims"]
    assert len(contributors) == 6
    assert Counter(item["selected_parent_choice"]["ordinal"] for item in contributors) == {0: 2, 1: 2, 2: 2}
    for item in contributors:
        ordinal = item["selected_parent_choice"]["ordinal"]
        native = item["native_record"]
        assert native["source_coordinate"] == ordinal
        assert native["record_sha256"] == _digest(records[ordinal])
        assert [token["token_index"] for token in native["deposits"]] == [0, 1]
        assert item["claim_parent"] == (f"NCBITaxon:{direct_target}" if ordinal == 0 else "NCBITaxon:10")
        assert item["selected_parent_choice"]["inferred"] is (ordinal != 0)
    actual = [
        row for row in scoped_rows(transform) if row["subject"] == subject and row["predicate"] == SUBCLASS_PREDICATE
    ]
    expected = _expected(10, inferred=direct_target != 10, subject=subject)
    assert Counter(map(_filled, actual)) == Counter([_filled(expected)])
    assert guard.contract["resolved_deposit_count"] == 1
    if direct_target == 10:
        assert guard.contract["ancestry"]["actual_queries"] is None
    else:
        assert guard.contract["contested"][0][1] == expected_claims
        assert guard.contract["ancestry"]["actual_queries"] is not None


def test_repeated_ids_each_demand_their_actual_lpsn_lookup(tmp_path, monkeypatch):
    """Identical accepted targets deduplicate edges without erasing the two original lookup occurrences."""
    records = [_record(lpsn="Fixture convergens"), _record(lpsn="Fixture convergens")]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records)
    guard = transform._taxonomy_evidence_guard
    assert guard.lookup_seen == {0, 1}
    rows = [row for row in scoped_rows(transform) if row["subject"] == SUBJECT and row["object"] == "lpsn:2"]
    assert len(rows) == 1
    audit = [row for row in graph_rows(transform.output_dir / taxonomy.AUDIT_FILE) if row["kind"] == "lpsn_lookup"]
    assert len(audit) == 2
    assert [json.loads(row["native_evidence_json"])["source_coordinate"] for row in audit] == [0, 1]


@pytest.mark.parametrize("retired", [False, True])
def test_mixed_same_target_survives_real_finalization_repeat_and_cold_admission(
    tmp_path, monkeypatch, local_source_schema, retired
):
    """Two complete provenance variants remain two through genuine native retirement and publication."""
    records = [_record(), _record(inferred=True)]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False, retired_fixture=retired)
    raw_contract = copy.deepcopy(transform._taxonomy_evidence_guard.contract)
    assert Counter(map(_filled, _parents(scoped_rows(transform)))) == Counter(
        map(_filled, [_expected(10), _expected(10, inferred=True)])
    )
    report = transform.finalize()
    target, original = (12, "NCBITaxon:10") if retired else (10, "")
    expected = [_expected(target, original_object=original), _expected(target, inferred=True, original_object=original)]
    assert Counter(map(_filled, _parents(graph_rows(transform.output_edge_file)))) == Counter(map(_filled, expected))
    assert report["producer_native_inputs"]["taxonomy"] == raw_contract
    if retired:
        with (transform.output_dir / "source_reference_resolution.tsv").open(newline="") as stream:
            resolutions = list(csv.DictReader(stream, delimiter="\t"))
        originals = [
            json.loads(row["original_edge_json"])
            for row in resolutions
            if row["original_edge_json"]
            and json.loads(row["original_edge_json"])["subject"] == SUBJECT
            and row["disposition"] == "retired_id_replaced"
        ]
        assert {_filled(row) for row in originals} == {_filled(_expected(10)), _filled(_expected(10, inferred=True))}
    verify_finalized_source_files(_paths(transform))
    assert transform.finalize() == report
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    verify_finalized_source_files(_paths(transform))
    raw = Path(transform.input_base_dir) / "bacdive_strains.json"
    raw.write_bytes(raw.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_native_inputs()


@pytest.mark.parametrize("blank", [False, True], ids=["direct-only", "no-classification"])
def test_duplicate_occurrence_zero_query_contract_survives_public_repetition(
    tmp_path, monkeypatch, local_source_schema, blank
):
    """Source-derived zero authority demand still accounts for both repeated native occurrences."""
    records = [_record(blank=blank), _record(blank=blank)]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False, forbid_ancestry_selection=True)
    report = transform.finalize()
    contract = report["producer_native_inputs"]["taxonomy"]
    assert contract["native_records"] == 2
    assert contract["ancestry"]["actual_queries"] is None
    assert contract["fallback_native_evidence"]["native_queries"] is None
    assert contract["fallback_native_evidence"]["selected_input"] is None
    assert contract["fallback_native_evidence"]["eligible_record_count"] == (2 if blank else 0)
    assert [item["ordinal"] for item in contract["fallback_choices"]] == ([0, 1] if blank else [])
    assert transform.finalize() == report
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    verify_finalized_source_files(_paths(transform))


@pytest.mark.parametrize("ordinal", [True, False, -1, 2, "0"])
@pytest.mark.parametrize("route", ["entry", "choice", "lookup"])
def test_live_occurrence_ingress_requires_exact_original_integer(tmp_path, monkeypatch, ordinal, route):
    """Booleans cannot alias a valid original ordinal, and invalid indices cannot enter the ledger."""
    records = [_record(lpsn="Fixture convergens"), _record(lpsn="Fixture convergens")]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records)
    guard = transform._taxonomy_evidence_guard
    with pytest.raises(SourceFinalizationRequired, match="native record ordinal"):
        if route == "entry":
            guard._entry(ordinal)
        elif route == "choice":
            guard.observe_parent_choice(ordinal, records[0], "NCBITaxon:10", False)
        else:
            guard.lookup(ordinal, records[0][CLASSIFICATION]["LPSN"])


@pytest.mark.parametrize("route", ["choice", "lookup"])
def test_second_observation_of_one_ordinal_still_refuses(tmp_path, monkeypatch, route):
    """Allowing another equal-ID occurrence must not allow double-accounting one occurrence."""
    records = [_record(lpsn="Fixture convergens"), _record(lpsn="Fixture convergens")]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records)
    guard = transform._taxonomy_evidence_guard
    with pytest.raises(SourceFinalizationRequired, match="(twice|repeated)"):
        if route == "choice":
            guard.observe_parent_choice(1, records[1], "NCBITaxon:10", False)
        else:
            guard.lookup(1, records[1][CLASSIFICATION]["LPSN"])


@pytest.mark.parametrize("route", ["choice", "lookup"])
def test_actual_run_cannot_omit_one_equal_id_occurrence(tmp_path, monkeypatch, route):
    """A missing second call does not disappear into an ID-set equality check at completion."""
    records = [_record(lpsn="Fixture convergens"), _record(lpsn="Fixture convergens")]
    output = tmp_path / "transformed/bacdive"
    output.mkdir(parents=True)
    (output / "nodes.tsv").write_bytes(b"previous nodes\n")
    (output / "edges.tsv").write_bytes(b"previous edges\n")
    if route == "choice":
        actual = taxonomy.TaxonomyEvidence.observe_parent_choice

        def omit_choice(self, ordinal, record, target, inferred):
            """Simulate a lost observer call without changing source data or emitter choices."""
            if ordinal != 1:
                return actual(self, ordinal, record, target, inferred)
            return None

        monkeypatch.setattr(taxonomy.TaxonomyEvidence, "observe_parent_choice", omit_choice)
    else:
        actual = taxonomy.TaxonomyEvidence.lookup

        def omit_lookup(self, ordinal, block):
            """Retain the real accepted-name answer but omit one demanded observation."""
            return actual(self, ordinal, block) if ordinal != 1 else self.gss.lookup(block)["target"]

        monkeypatch.setattr(taxonomy.TaxonomyEvidence, "lookup", omit_lookup)
    with pytest.raises(SourceFinalizationRequired, match="BacDive taxonomy evidence:"):
        produce(tmp_path, monkeypatch, records)
    assert (output / "nodes.tsv").read_bytes() == b"previous nodes\n"
    assert (output / "edges.tsv").read_bytes() == b"previous edges\n"


@pytest.mark.parametrize("damage", ["omit", "duplicate", "boolean", "moved", "swapped", "record-id", "directness"])
def test_generic_admission_rejoins_every_recorded_fallback_occurrence(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Equal IDs do not let forged or incomplete choices evade actual raw/native reconstruction."""
    records = [_record(inferred=True), _record(20, inferred=True)]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False)
    report = transform.finalize()
    verify_finalized_source_files(_paths(transform))
    choices = report["producer_native_inputs"]["taxonomy"]["fallback_choices"]
    assert choices == [
        {"record_id": "1", "target": "NCBITaxon:10", "inferred": True, "ordinal": 0},
        {"record_id": "1", "target": "NCBITaxon:20", "inferred": True, "ordinal": 1},
    ]
    if damage == "omit":
        choices.pop()
    elif damage == "duplicate":
        choices.append(copy.deepcopy(choices[0]))
    elif damage == "boolean":
        choices[1]["ordinal"] = True
    elif damage == "moved":
        choices[1]["ordinal"] = 2
    elif damage == "swapped":
        choices[0]["target"], choices[1]["target"] = choices[1]["target"], choices[0]["target"]
    elif damage == "record-id":
        choices[1]["record_id"] = "2"
    else:
        choices[1]["inferred"] = False
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="BacDive (taxonomy|fallback) evidence:"):
        verify_finalized_source_files(_paths(transform))


@pytest.mark.parametrize("damage", ["omit", "duplicate", "substitute", "record-hash"])
def test_generic_admission_rejects_coherently_restamped_occurrence_audit(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Audit byte/count receipts cannot replace the original complete per-occurrence witnesses."""
    records = [_record(inferred=True), _record(20, inferred=True)]
    transform, _, _, _ = produce(tmp_path, monkeypatch, records, gss=False)
    report = transform.finalize()
    verify_finalized_source_files(_paths(transform))
    original_inputs = copy.deepcopy((report["inputs"], report["consumed_inputs"]))
    path = transform.output_dir / taxonomy.AUDIT_FILE
    rows = list(graph_rows(path))
    assert len(rows) == 2 and all(row["kind"] == "fallback" for row in rows)
    if damage == "omit":
        rows.pop()
    elif damage == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    else:
        payload = json.loads(rows[1]["native_evidence_json"])
        if damage == "substitute":
            payload["native_record"] = json.loads(rows[0]["native_evidence_json"])["native_record"]
        else:
            payload["native_record"]["record_sha256"] = "0" * 64
        rows[1]["native_evidence_json"] = _json(payload)
    _write(path, rows, taxonomy.AUDIT_FIELDS)
    report["producer_audit_members"][path.name] = _identity(path)
    report["audit_members"][path.name] = _identity(path)
    report["producer_native_inputs"]["taxonomy"]["audit_rows"] = len(rows)
    report["producer_native_inputs"]["taxonomy"]["audit_projection_sha256"] = _digest(rows)
    assert (report["inputs"], report["consumed_inputs"]) == original_inputs
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="BacDive (taxonomy|fallback) evidence:"):
        verify_finalized_source_files(_paths(transform))


@pytest.mark.parametrize("damage", ["omit-direct", "omit-inferred", "duplicate", "qualifier", "reverse"])
def test_generic_admission_requires_exact_full_rows_after_outer_graph_restamp(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """A shared endpoint pair licenses only its two native-supported complete provenance variants."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [_record(), _record(inferred=True)], gss=False)
    report = transform.finalize()
    verify_finalized_source_files(_paths(transform))
    rows = list(graph_rows(transform.output_edge_file))
    selected = _parents(rows)
    assert len(selected) == 2
    original_rows = Counter(map(_json, rows))
    native_before = copy.deepcopy(report["producer_native_inputs"])
    audit = transform.output_dir / taxonomy.AUDIT_FILE
    audit_before = audit.read_bytes()
    if damage.startswith("omit-"):
        relation = RDFS_SUBCLASS_OF if damage == "omit-direct" else INFERRED_SUBCLASS_RELATION
        rows.remove(next(row for row in selected if row["relation"] == relation))
    elif damage == "duplicate":
        rows.append(copy.deepcopy(selected[0]))
    elif damage == "qualifier":
        selected[0]["publications"] += "|doi:10.9999/unsupported"
    else:
        reversed_row = copy.deepcopy(selected[0])
        reversed_row["subject"], reversed_row["object"] = reversed_row["object"], reversed_row["subject"]
        rows.append(reversed_row)
    if damage in {"duplicate", "reverse"}:
        assert original_rows <= Counter(map(_json, rows)) and len(rows) == sum(original_rows.values()) + 1
    _write(transform.output_edge_file, rows, list(rows[0]))
    report["members"][transform.output_edge_file.name] = _identity(transform.output_edge_file)
    assert report["producer_native_inputs"] == native_before
    assert audit.read_bytes() == audit_before
    assert all(report["members"][path.name] == _identity(path) for path in _paths(transform))
    (transform.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="BacDive taxonomy evidence:"):
        verify_finalized_source_files(_paths(transform))
