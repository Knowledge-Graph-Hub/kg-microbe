"""Actual producer and native/read/audit lifecycle controls for #1363."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.microbedecoder_join_fixtures import prepare
from tests.test_microbedecoder_transform import _NoChebi


def _rows(path):
    """Retain all literal canonical TSV fields for comparisons."""
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def _write(path, rows, fields):
    """Write a deliberate isolated corruption without changing production fixtures."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _native_report(transform):
    """Build a low-level protocol report from actual completed producer inputs/output."""

    def identity(path):
        """Bind a test-owned output's exact byte length and digest."""
        return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    return {
        "producer_native_inputs": transform.producer_native_inputs,
        "consumed_inputs": transform.consumed_input_snapshots,
        "raw_input_directory": str(Path(transform.input_base_dir).resolve()),
        "members": {
            "edges.tsv": identity(transform.output_edge_file),
            "nodes.tsv": identity(transform.output_node_file),
        },
        "producer_audit_members": {
            joins.AUDIT_FILE: identity(transform.output_dir / joins.AUDIT_FILE),
            "phenotype_normalizations.tsv": identity(transform.output_dir / "phenotype_normalizations.tsv"),
        },
    }


def test_actual_emitter_refuses_only_selected_reversed_link_and_preserves_observations(tmp_path, monkeypatch):
    """The same link in a different native record survives, along with independent fields."""
    transform, raw, _, _, rows = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    links = [row for row in _rows(transform.output_edge_file) if row["subject"].startswith("kgmicrobe.strain:")]
    assert len(links) == 1 and links[0]["source_record"].endswith("#record=2")
    assert links[0]["object"] == "lpsn:101" and links[0]["relation"] == "rdfs:subClassOf"
    audit = _rows(transform.output_dir / joins.AUDIT_FILE)
    assert len(audit) == 1
    original = json.loads(audit[0]["original_claim_json"])
    assert original["subject"] == "kgmicrobe.strain:bacdive_42"
    assert original["object"] == "lpsn:101" and original["predicate"] == "biolink:subclass_of"
    assert json.loads(audit[0]["native_record_json"]) == rows[0]
    assert audit[0]["emitted_claim_json"] == "null"
    edges = _rows(transform.output_edge_file)
    snapshots = [row for row in edges if row.get("source_column") == "BacDive_Oxygen_tolerance"]
    record_subject = json.loads(audit[0]["snapshot_node_json"])["id"]
    assert len(snapshots) == 2 and {row["subject"] for row in snapshots} == {"lpsn:101", record_subject}
    predictions = [row for row in edges if row.get("source_column") == "FAPROTAX_Type_of_metabolism"]
    assert predictions and all(row["knowledge_level"] == "prediction" for row in predictions)
    assert joins.CONTRACT_KEY in transform.producer_native_inputs
    assert (
        transform.producer_native_inputs[joins.CONTRACT_KEY]["scope"]
        == "finite_link_refusals_and_record_scoped_snapshot_observations"
    )
    assert "integrated_acceptance_ready" not in transform.producer_native_inputs[joins.CONTRACT_KEY]


def test_bound_gss_replaces_stale_preview_not_the_accepted_name_algorithm(tmp_path, monkeypatch):
    """Public run must not select subjects through an injected old preview dictionary."""
    transform, raw, gss, _, _ = prepare(tmp_path, monkeypatch)
    transform._accepted_lpsn = {"103": "999"}
    transform.run(raw)
    assert transform._accepted_lpsn["103"] == "101"
    snapshot = transform.consumed_input_snapshots[joins.ROLE_GSS]
    assert snapshot == {"path": str(gss.resolve()), "sha256": hashlib.sha256(gss.read_bytes()).hexdigest()}
    assert all("999" not in row["object"] for row in _rows(transform.output_edge_file))


@pytest.mark.parametrize("member", ["raw", "gss", "policy", "evidence"])
def test_preflight_drift_does_not_replace_previous_source_members(tmp_path, monkeypatch, member):
    """Exact source/evidence failures precede this producer's output transaction."""
    transform, raw, gss, policy, _ = prepare(tmp_path, monkeypatch)
    transform.output_dir.mkdir(parents=True, exist_ok=True)
    protected = [transform.output_node_file, transform.output_edge_file, transform.output_dir / joins.AUDIT_FILE]
    for path in protected:
        path.write_text("previous output bytes\n")
    targets = {"raw": raw, "gss": gss, "policy": policy, "evidence": policy.parent / "evidence.json"}
    target = targets[member]
    if member == "gss":
        # GSS bytes alone are no longer bound (#1420); a change to a reviewed accepted row is.
        text = target.read_text(encoding="utf-8")
        assert text.count("101,,correct name") == 1
        target.write_text(text.replace("101,,correct name", "101,,correct name; emended"), encoding="utf-8")
    else:
        target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        transform.run(raw)
    assert all(path.read_text() == "previous output bytes\n" for path in protected)


def test_new_gss_snapshot_with_reviewed_rows_unchanged_is_accepted(tmp_path, monkeypatch):
    """No GSS byte pin (#1420): a later snapshot passes on its reviewed rows, and its read is recorded."""
    transform, raw, gss, policy, _ = prepare(tmp_path, monkeypatch)
    with gss.open("a", encoding="utf-8", newline="") as stream:
        stream.write("999,,correct name\r\n")
    transform.run(raw)
    snapshot = transform.consumed_input_snapshots[joins.ROLE_GSS]
    assert snapshot["sha256"] == hashlib.sha256(gss.read_bytes()).hexdigest()
    assert json.loads(policy.read_text())["lpsn_gss_reviewed_sha256"] != snapshot["sha256"]
    report = _native_report(transform)
    assert (
        report["producer_native_inputs"][joins.CONTRACT_KEY]["bindings"][joins.ROLE_GSS]["sha256"]
        == (snapshot["sha256"])
    )
    joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize("role", joins.REQUIRED_INPUTS)
def test_live_and_recorded_original_roles_cannot_be_erased(tmp_path, monkeypatch, role):
    """A byte identity under a different role is not original consumption evidence."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    report = _native_report(transform)
    del report["consumed_inputs"][role]
    with pytest.raises(SourceFinalizationRequired):
        joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
    del transform._consumed_input_snapshots[role]
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


@pytest.mark.parametrize(
    "field", ["source_cell_json", "native_record_json", "original_claim_json", "witness_json", "source_record"]
)
def test_audit_payload_cannot_be_replaced_by_a_consistent_new_checksum(tmp_path, monkeypatch, field):
    """Admission independently rebuilds original evidence instead of trusting an audit receipt."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    audit_path = transform.output_dir / joins.AUDIT_FILE
    rows = _rows(audit_path)
    rows[0][field] = "{}" if field.endswith("_json") else "invented"
    _write(audit_path, rows, joins.AUDIT_FIELDS)
    report = _native_report(transform)
    with pytest.raises(SourceFinalizationRequired):
        joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize(
    "mutation", ["restore_selected", "drop_retained", "remove_record", "reverse_orientation", "invent_provenance"]
)
def test_complete_native_link_family_is_conserved(tmp_path, monkeypatch, mutation):
    """Unknown extra, missing and reattributed links fail even with refreshed file receipts."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    rows = _rows(transform.output_edge_file)
    selected = next(row for row in rows if row["subject"].startswith("kgmicrobe.strain:"))
    if mutation == "restore_selected":
        item = dict(selected)
        item["source_record"] = item["source_record"].replace("#record=2", "#record=1")
        rows.append(item)
    elif mutation == "drop_retained":
        rows.remove(selected)
    elif mutation == "remove_record":
        selected["source_record"] = ""
    elif mutation == "reverse_orientation":
        selected["subject"], selected["object"] = selected["object"], selected["subject"]
    else:
        selected["primary_knowledge_source"] = "infores:invented"
    _write(transform.output_edge_file, rows, transform.edge_header)
    with pytest.raises(SourceFinalizationRequired):
        joins.verify_recorded_inputs(_native_report(transform), transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize("boundary", ["live", "public_fresh", "composed_recorded", "public_recorded"])
@pytest.mark.parametrize("source_ordinal", [1, 2])
@pytest.mark.parametrize(
    "predicate,relation",
    [
        ("biolink:close_match", "skos:closeMatch"),
        ("biolink:subclass_of", "rdfs:subClassOf"),
        ("biolink:related_to", "skos:exactMatch"),
        ("biolink:same_as", "biolink:related_to"),
    ],
)
def test_inverse_addition_cannot_hide_behind_intact_family_and_audit(
    tmp_path, monkeypatch, local_source_schema, boundary, source_ordinal, predicate, relation
):
    """Append an inverse claim; do not remove the valid same-pair other-record link."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    recorded = boundary in {"composed_recorded", "public_recorded"}
    report = transform.finalize(fresh_run=True) if recorded else None
    edge_path = transform.output_edge_file
    audit_path = transform.output_dir / joins.AUDIT_FILE
    before_edges, before_audit = edge_path.read_bytes(), audit_path.read_bytes()
    before_rows = _rows(edge_path)
    retained = [row for row in before_rows if row["subject"] == "kgmicrobe.strain:bacdive_42"]
    assert len(retained) == 1 and retained[0]["source_record"].endswith("#record=2")
    # Start from the actual full original omitted assertion, not a synthetic
    # replacement for a required retained row. Record two is also probed:
    # even a real forward claim supplies no native inverse assertion.
    original = json.loads(_rows(audit_path)[0]["original_claim_json"])
    assert original["source_record"].endswith("#record=1")
    with edge_path.open(encoding="utf-8", newline="") as stream:
        fields = next(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    added = {field: original.get(field, "") for field in fields}
    added["subject"], added["object"] = original["object"], original["subject"]
    added["predicate"], added["relation"] = predicate, relation
    added["source_record"] = original["source_record"].rsplit("=", 1)[0] + "=" + str(source_ordinal)
    with edge_path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
        writer.writerow(added)
    assert edge_path.read_bytes().startswith(before_edges)
    assert audit_path.read_bytes() == before_audit
    assert _rows(edge_path) == [*before_rows, added]
    assert retained[0] in _rows(edge_path)
    if recorded:
        # Refresh only the outer edge identity coherently. Native reconstruction
        # must reject the unsupported addition, not merely an old byte receipt.
        report["members"]["edges.tsv"] = {
            "bytes": edge_path.stat().st_size,
            "sha256": hashlib.sha256(edge_path.read_bytes()).hexdigest(),
        }
        report_path = transform.output_dir / "source_finalization.json"
        report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    with pytest.raises(SourceFinalizationRequired, match="retained native BacDive links"):
        if boundary == "live":
            transform.verify_native_inputs()
        elif boundary == "public_fresh":
            transform.finalize(fresh_run=True)
        elif boundary == "composed_recorded":
            MicrobeDecoderTransform.verify_recorded_native_inputs(report, report_path)
        else:
            verify_finalized_source_files([transform.output_node_file, edge_path])


@pytest.mark.parametrize("selector", ["policy", "gss"])
@pytest.mark.parametrize("reset_visible_failure", [False, True])
@pytest.mark.parametrize("fresh_object", [False, True])
def test_selector_catch_restore_retry_requires_a_genuine_new_run(
    tmp_path, monkeypatch, local_source_schema, selector, reset_visible_failure, fresh_object
):
    """Public refusal sticks after restoration; only actual rerun gets fresh evidence."""
    transform, raw, gss, policy, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    if fresh_object:
        report = transform.finalize(fresh_run=True)
        transform = MicrobeDecoderTransform(
            transform.input_base_dir,
            transform.output_base_dir,
            chemical_loader=_NoChebi(),
            crosswalk_quarantine_policy=transform.crosswalk_quarantine_policy,
            bacdive_join_policy=policy,
        )
        assert transform.finalize() == report
    original_guard = transform._bacdive_join_guard
    protected = (transform.output_node_file, transform.output_edge_file, transform.output_dir / joins.AUDIT_FILE)
    before = {path: path.read_bytes() for path in protected}
    original_raw_directory = transform.input_base_dir
    if selector == "policy":
        clone = policy.parent / "same-policy-other-selector.json"
        clone.write_bytes(policy.read_bytes())
        transform.bacdive_join_policy = clone
    else:
        clone = tmp_path / "same-gss-other-raw-directory"
        clone.mkdir()
        (clone / "lpsn_gss.csv").write_bytes(gss.read_bytes())
        transform.input_base_dir = clone
    with pytest.raises(SourceFinalizationRequired, match="configured producer policy/GSS locator"):
        transform.finalize(fresh_run=True)
    assert original_guard._failed
    transform.bacdive_join_policy = policy
    transform.input_base_dir = original_raw_directory
    if reset_visible_failure:
        original_guard._failed = False
    # Catching and restoring a selector does not erase the observed failure;
    # retained admission catches manually resetting the visible flag as well.
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)
    assert {path: path.read_bytes() for path in protected} == before
    transform.run(raw)
    assert transform._bacdive_join_guard is not original_guard
    assert not transform._bacdive_join_guard._failed
    transform.verify_native_inputs()
    report = transform.finalize(fresh_run=True)
    assert report["producer_native_inputs"][joins.CONTRACT_KEY]["quarantined_links"] == 1
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    assert len(_rows(transform.output_dir / joins.AUDIT_FILE)) == 1
    retained = [row for row in _rows(transform.output_edge_file) if row["subject"] == "kgmicrobe.strain:bacdive_42"]
    assert len(retained) == 1 and retained[0]["source_record"].endswith("#record=2")


def test_genuine_zero_source_requires_all_native_reads_and_header_only_audit(tmp_path, monkeypatch):
    """Tiny empty fixture inputs exercise the protocol, not a runtime zero bypass."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch, selected=(), empty=True)
    transform.run(raw)
    assert _rows(transform.output_dir / joins.AUDIT_FILE) == []
    assert set(joins.REQUIRED_INPUTS) <= transform.consumed_input_snapshots.keys()
    admission = joins.verify_recorded_inputs(
        _native_report(transform), transform.output_dir / "source_finalization.json"
    )
    admission.verify()


@pytest.mark.parametrize("change", ["synonym_of_md_side", "row_edited"])
def test_the_bacdive_side_accepted_row_is_bound_too(tmp_path, monkeypatch, change):
    """A refusal rests on two distinct correct names, so the BacDive side's row is compared as well (#1525)."""
    transform, raw, gss, _, _ = prepare(tmp_path, monkeypatch)
    text = gss.read_text(encoding="utf-8")
    assert text.count("9000001,,correct name") == 1
    replacement = "9000001,101,synonym" if change == "synonym_of_md_side" else "9000001,,correct name; emended"
    gss.write_text(text.replace("9000001,,correct name", replacement), encoding="utf-8")
    with pytest.raises(SourceFinalizationRequired, match="accepted-name witness drift"):
        transform.run(raw)


def test_a_gss_that_is_not_utf8_is_refused_cleanly(tmp_path, monkeypatch):
    """Undecodable bytes are a refusal through the guard, not a bare UnicodeDecodeError (#1532)."""
    transform, raw, gss, _, _ = prepare(tmp_path, monkeypatch)
    gss.write_bytes(gss.read_bytes() + b"9000002,,caf\xe9\r\n")
    with pytest.raises(SourceFinalizationRequired, match="not valid UTF-8"):
        transform.run(raw)


def test_contract_deletion_and_late_gss_drift_cannot_pass(tmp_path, monkeypatch):
    """Required contract membership and original authority locators survive admission."""
    transform, raw, gss, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    report = _native_report(transform)
    admission = joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
    gss.write_bytes(gss.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        admission.verify()
    report["producer_native_inputs"] = {}
    with pytest.raises(SourceFinalizationRequired):
        joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize(
    "mutation", ["erase_audit", "erase_contract", "clear_parsed_rules", "rebound_role", "rebound_selector"]
)
def test_mandatory_obligations_cannot_be_downgraded_to_zero(tmp_path, monkeypatch, mutation):
    """Input/output/cache loss is not evidence of a genuinely inactive native cohort."""
    transform, raw, _, policy, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    if mutation == "erase_audit":
        (transform.output_dir / joins.AUDIT_FILE).unlink()
    elif mutation == "erase_contract":
        transform.producer_native_inputs.clear()
    elif mutation == "clear_parsed_rules":
        transform._bacdive_join_guard.selected.clear()
        transform._bacdive_join_guard._dispatches.clear()
    elif mutation == "rebound_role":
        clone = policy.parent / "same-bytes-other-file.json"
        clone.write_bytes(policy.read_bytes())
        transform._consumed_input_snapshots[joins.ROLE_POLICY]["path"] = str(clone)
    else:
        clone = policy.parent / "same-bytes-other-selector.json"
        clone.write_bytes(policy.read_bytes())
        transform.bacdive_join_policy = clone
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


def test_caught_failure_and_reset_visible_completion_are_not_success(tmp_path, monkeypatch):
    """A reset of a mutable phase flag cannot discard retained completion evidence."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    guard = transform._bacdive_join_guard
    old = guard._sealed
    guard._sealed = None
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()
    guard._sealed = old
    guard._failed = False
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()


def test_public_finalization_repeat_and_composed_gold_admission(tmp_path, monkeypatch, local_source_schema):
    """Exercise real registered producer finalization and both independent native verifiers."""
    transform, raw, _, policy, _ = prepare(tmp_path, monkeypatch)
    transform.run(raw)
    before = Counter(json.dumps(row, sort_keys=True) for row in _rows(transform.output_edge_file))
    report = transform.finalize(fresh_run=True)
    assert report["producer_native_inputs"][joins.CONTRACT_KEY]["quarantined_links"] == 1
    assert "gold_reference_declarations" in report
    after = Counter(json.dumps(row, sort_keys=True) for row in _rows(transform.output_edge_file))
    assert before == after
    fresh = MicrobeDecoderTransform(
        transform.input_base_dir, transform.output_base_dir, chemical_loader=_NoChebi(), bacdive_join_policy=policy
    )
    repeated = fresh.finalize()
    assert repeated == report
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh.verify_native_inputs()


def test_original_ten_thousand_decision_policy_is_unchanged():
    """The finite deposit policy cannot silently weaken the earlier cross-phylum witnesses."""
    root = Path(__file__).resolve().parents[1]
    directory = root / "mappings/canonical"
    expected = {
        "microbedecoder_crosswalk_quarantine.tsv": "7d35ebf9d56cefb473d60462426ccfcd0f7a202d1547aa8c47b8ebf3ea132718",
        "microbedecoder_crosswalk_quarantine_evidence.json.gz": (
            "57e2af2e05988bb0d2c73aee28507f7e4254a0b0ce687c7a2eaa38d035060202"
        ),
    }
    for name, sha in expected.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == sha
