"""Draft actual producer/public-admission controls; unexecuted until coordinated application."""

import copy
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive import taxonomy_evidence as taxonomy
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform, load_metpo_metabolite_production_mappings
from kg_microbe.transform_utils.bacdive.fallback_evidence import SELECTED_ROLE
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.bacdive_fallback_fixtures import RESOURCE, adapter, close_adapter, native_database, records_by_id, write_rows
from tests.test_bacdive_isolation_categories import _run


def produce(tmp_path, monkeypatch, records):
    """Run the unchanged actual raw reader/emitter with a tiny, real, owned native authority."""
    originals = []

    def context(transform, _policy):
        """Seed actual files before native fallback preparation; never mock a fallback selection."""
        db = native_database(Path(transform.input_base_dir) / "test-native-excerpt.db")
        transform.ncbi_impl = adapter(db)
        originals.append(transform.ncbi_impl)
        selected = tmp_path / "selected_nodes.tsv"
        selected.write_bytes((RESOURCE / "selected_nodes.tsv").read_bytes())
        monkeypatch.setattr(module, "NCBITAXON_NODES_FILE", selected)
        transform.ncbitaxon_fallback_cache = {}
        transform._ncbitaxon_ancestor_cache = {}
        transform.ncbitaxon_labels = {}
        transform.lpsn_name_index = {}
        transform.metpo_metabolite_production_mappings = load_metpo_metabolite_production_mappings()

    try:
        return _run(tmp_path, monkeypatch, records, during_prepare=context)
    finally:
        for original in originals:
            close_adapter(original)


def encode(row):
    """Compare complete serialized rows, not only endpoints or changed metadata cells."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def test_full_native_moorella_preserves_records_deposits_and_other_observations(tmp_path, monkeypatch):
    """Reject only the wasp inference and dependent parents, without inventing a bacterial substitute."""
    native = records_by_id()["175523"]["record"]
    original = copy.deepcopy(native)
    transform, edges, nodes, _ = produce(tmp_path, monkeypatch, [native])
    assert native == original
    subjects = {"kgmicrobe.strain:bacdive_175523", "kgmicrobe.strain:DSM-116161", "kgmicrobe.strain:CCOS-2103"}
    assert subjects <= {row["id"] for row in nodes}
    parents = [
        row
        for row in edges
        if row["subject"] in subjects
        and row["predicate"] == "biolink:subclass_of"
        and row["object"].startswith("NCBITaxon:")
    ]
    assert parents == []
    assert not any(row["id"].startswith(("kgmicrobe.species:", "kgmicrobe.genus:")) for row in nodes)
    audit = [row for row in graph_rows(transform.output_dir / taxonomy.AUDIT_FILE) if row["kind"] == "fallback"]
    assert len(audit) == 1 and audit[0]["status"] == "terminal_rejection"
    evidence = json.loads(audit[0]["native_evidence_json"])
    rejected = evidence["rejected_parent_proposals"]
    assert len(rejected) == 3
    assert {row["edge"]["subject"] for row in rejected} == subjects
    assert {row["edge"]["object"] for row in rejected} == {"NCBITaxon:216400"}
    assert evidence["native_record"]["references"] == native.get("Reference", {})
    assert json.loads(audit[0]["emitted_edge_json"]) == []
    # An explicitly synthetic direct-ID variant exercises trait noninterference;
    # it is not represented as corrected source identity for this native record.
    synthetic = copy.deepcopy(native)
    synthetic["General"]["NCBI tax id"] = {"NCBI tax id": 2}
    other = tmp_path / "synthetic-direct-control"
    other.mkdir()
    monkeypatch.undo()
    _, baseline, _, _ = produce(other, monkeypatch, [synthetic])

    def independent(row):
        """Select unchanged observations outside the reviewed strain-parent claims."""
        return not (
            row["subject"] in subjects
            and row["predicate"] == "biolink:subclass_of"
            and row["object"].startswith("NCBITaxon:")
        )

    assert Counter(encode(row) for row in edges if independent(row)) == Counter(
        encode(row) for row in baseline if independent(row)
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_child",
        "zero_child",
        "drop_audit",
        "changed_audit",
        "native_role",
        "record_parent",
        "deposit_parent",
        "reversed_record",
        "reversed_provisional",
        "filled_qualifier",
    ],
)
def test_public_recorded_admission_rejects_lost_or_coherently_restamped_native_evidence(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """The actual public producer verifier must independently rejoin the native finite scope."""
    identifier = "134696" if damage == "filled_qualifier" else "24851" if damage == "reversed_provisional" else "175523"
    record = records_by_id()[identifier]["record"]
    transform, _, _, _ = produce(tmp_path, monkeypatch, [record])
    report = transform.finalize()
    report_path = transform.output_dir / "source_finalization.json"
    if damage == "missing_child":
        report["producer_native_inputs"]["taxonomy"].pop("fallback_native_evidence")
    elif damage == "zero_child":
        child = report["producer_native_inputs"]["taxonomy"]["fallback_native_evidence"]
        child.update(plans={}, eligible_record_count=0, native_queries=None, selected_input=None)
        report["producer_native_inputs"]["taxonomy"]["fallback_choices"] = []
    elif damage == "native_role":
        report["consumed_inputs"].pop(SELECTED_ROLE)
    elif damage in {"drop_audit", "changed_audit"}:
        path = transform.output_dir / taxonomy.AUDIT_FILE
        rows = list(graph_rows(path))
        if damage == "drop_audit":
            rows = [row for row in rows if row["kind"] != "fallback"]
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=taxonomy.AUDIT_FIELDS,
                    delimiter="\t",
                    quoting=csv.QUOTE_NONE,
                    quotechar=None,
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(rows)
        else:
            selected = next(row for row in rows if row["kind"] == "fallback")
            selected["native_evidence_json"] = "{}"
            write_rows(path, rows)
        # Only the outer receipt is restamped, not an independent input read.
        identity = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        report["producer_audit_members"][taxonomy.AUDIT_FILE] = identity
        report["audit_members"][taxonomy.AUDIT_FILE] = dict(identity)
    else:
        path = transform.output_edge_file
        rows = list(graph_rows(path))
        if damage == "filled_qualifier":
            native_parent = [
                row
                for row in rows
                if row["subject"] == "kgmicrobe.strain:bacdive_134696"
                and row["predicate"] == "biolink:subclass_of"
                and row["object"].startswith("NCBITaxon:")
            ]
            assert len(native_parent) == 1
            native_parent[0]["publications"] = "doi:10.9999/unsupported"
            write_rows(path, rows)
            with pytest.raises(SourceFinalizationRequired):
                BacDiveTransform.verify_recorded_native_inputs(report, report_path, admission=SourceAdmission())
            return
        subject = "kgmicrobe.strain:DSM-116161" if damage == "deposit_parent" else "kgmicrobe.strain:bacdive_175523"
        row = {key: "" for key in rows[0]}
        row.update(
            subject=subject,
            predicate="biolink:subclass_of",
            object="NCBITaxon:216400",
            relation="kgmicrobe:inferred_subClassOf",
            primary_knowledge_source="infores:bacdive",
            knowledge_level="prediction",
            agent_type="automated_agent",
        )
        if damage in {"reversed_record", "reversed_provisional"}:
            row["subject"] = "NCBITaxon:2"
            row["object"] = (
                "kgmicrobe.genus:Proactinomyces"
                if damage == "reversed_provisional"
                else "kgmicrobe.strain:bacdive_175523"
            )
        rows.append(row)
        write_rows(path, rows)
    report_path.write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired):
        BacDiveTransform.verify_recorded_native_inputs(report, report_path, admission=SourceAdmission())


def test_actual_finalize_fresh_repeat_and_late_native_refusal(tmp_path, monkeypatch, local_source_schema):
    """Exercise original and fresh producer routes, retaining the original child after publication."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [records_by_id()["175523"]["record"]])
    report = transform.finalize()
    assert transform.finalize() == report
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, transform.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    locator = Path(
        report["producer_native_inputs"]["taxonomy"]["fallback_native_evidence"]["selected_input"]["locator"]
    )
    locator.write_bytes(locator.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)
    with pytest.raises(SourceFinalizationRequired):
        fresh.verify_native_inputs()


def test_caught_actual_parent_cache_failure_poison_is_retained(tmp_path, monkeypatch):
    """An actual producer guard cannot resume successfully after a caught wrong-cache error."""
    transform, _, _, _ = produce(tmp_path, monkeypatch, [records_by_id()["134696"]["record"]])
    guard = transform._taxonomy_evidence_guard
    plan = guard._fallback.plan(0)
    key = BacDiveTransform._ncbitaxon_fallback_key(plan["native_record"]["classification"])
    cache = {key: "NCBITaxon:2"}
    with pytest.raises(SourceFinalizationRequired):
        guard.fallback_choice(0, cache)
    cache[key] = plan["early_target"]
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_native_inputs()
