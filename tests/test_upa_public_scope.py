"""Actual publication and generic admission controls for UPA's finite native scope."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import source_finalization as finalizer
from kg_microbe.utils import upa_route_review as upa
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_merge_source_freshness import prepare_source
from tests.upa_route_fixtures import rows, run_upa, write_rows

pytestmark = pytest.mark.usefixtures("local_source_schema")


def identity(path):
    """Restamp only explicit test-owned outer receipts, never native/source inputs."""
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def published_bytes(directory):
    """Capture selected graph/report/audit publication bytes, not temporary-file atomicity."""
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def add_unrelated_upa_files(transform, *, partial=False):
    """Copy genuine finalized fixture rows under explicitly requested, previously unbound names."""
    for kind in ("nodes",) if partial else ("nodes", "edges"):
        shutil.copyfile(transform.output_dir / f"chebi_{kind}.tsv", transform.output_dir / f"upa_{kind}.tsv")


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("restored", [False, True])
def test_inactive_contract_cannot_publish_requested_complete_or_partial_upa_members(tmp_path, partial, restored):
    """Real public finalization refuses before replacing existing selected rows/reports."""
    transform = prepare_source(tmp_path, "ontologies", prefix="chebi_", marker=False)
    if restored:
        transform = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
        transform.finalize(file_prefix="chebi_")
    add_unrelated_upa_files(transform, partial=partial)
    shutil.copyfile(
        transform.output_dir / "chebi_source_finalization.json",
        transform.output_dir / "upa_source_finalization.json",
    )
    before = published_bytes(transform.output_dir)
    prefix = "" if partial else "upa_"
    with pytest.raises(SourceFinalizationRequired, match="UPA.*(staged member scope|exact node/edge member pair)"):
        transform.finalize(file_prefix=prefix, fresh_run=True)
    assert published_bytes(transform.output_dir) == before
    assert set(upa._owned(transform.consumed_input_snapshots)) == {upa.POLICY_ROLE}
    with pytest.raises(
        SourceFinalizationRequired,
        match="UPA (route review previously failed|restored original roles changed)",
    ):
        transform.verify_native_inputs()


def test_true_scoped_zero_ignores_upa_files_outside_the_selected_stage(tmp_path):
    """Fresh and repeat chebi_-only publication need no UPA/GO native files beside stale UPA rows."""
    transform = prepare_source(tmp_path, "ontologies", prefix="chebi_", marker=False)
    add_unrelated_upa_files(transform)
    upa_before = {name: (transform.output_dir / name).read_bytes() for name in upa.MEMBERS}
    report = transform.finalize(file_prefix="chebi_", fresh_run=True)
    assert report["producer_native_inputs"]["upa_route_review"]["members"] == []
    assert set(upa._owned(report["consumed_inputs"])) == {upa.POLICY_ROLE}
    for name in ("upa.json", "upa.owl", "go.db"):
        assert not (transform.input_base_dir / name).exists()
    paths = [transform.output_dir / name for name in report["members"]]
    verify_finalized_source_files(paths)
    repeat = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
    assert repeat.finalize(file_prefix="chebi_")["producer_native_inputs"] == report["producer_native_inputs"]
    assert upa_before == {name: (transform.output_dir / name).read_bytes() for name in upa.MEMBERS}


@pytest.mark.parametrize("restored", [False, True])
def test_second_staging_checkpoint_rejects_late_upa_addition_before_any_publication(tmp_path, monkeypatch, restored):
    """Both existing finalizer checkpoints enforce the bound zero scope, not just stage creation."""
    transform = prepare_source(tmp_path, "ontologies", prefix="chebi_", marker=False)
    if restored:
        transform = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
        transform.finalize(file_prefix="chebi_")
    before = published_bytes(transform.output_dir)
    original_publish = finalizer._publish_finalization

    def add_pair_then_publish(producer, prepared):
        """Inject new explicitly staged names after validation but before the real late guard."""
        stage = prepared[0]
        for kind in ("nodes", "edges"):
            shutil.copyfile(stage / f"chebi_{kind}.tsv", stage / f"upa_{kind}.tsv")
        return original_publish(producer, prepared)

    monkeypatch.setattr(finalizer, "_publish_finalization", add_pair_then_publish)
    with pytest.raises(SourceFinalizationRequired, match="UPA explicitly staged member scope"):
        transform.finalize(file_prefix="chebi_", fresh_run=True)
    assert published_bytes(transform.output_dir) == before


def test_active_run_cannot_be_weakened_to_a_different_selected_prefix(tmp_path, monkeypatch):
    """An active source's bound UPA pair cannot be hidden by requesting an unrelated output scope."""
    transform, _, _, _ = run_upa(tmp_path, monkeypatch, finalize=True)
    for kind in ("nodes", "edges"):
        shutil.copyfile(transform.output_dir / f"upa_{kind}.tsv", transform.output_dir / f"other_{kind}.tsv")
    before = published_bytes(transform.output_dir)
    with pytest.raises(SourceFinalizationRequired, match="UPA explicitly staged member scope"):
        transform.finalize(file_prefix="other_", fresh_run=True)
    assert published_bytes(transform.output_dir) == before


def mutate_saved_contract(transform, report, policy, damage):
    """Persist coherent outer mutations while keeping every actual immutable input object unchanged."""
    audit_path = transform.output_dir / upa.AUDIT_FILE
    audit = rows(audit_path, quoted=True)
    changed_audit = False
    expected_error = "UPA complete audit differs from actual native/writer evidence"
    if damage == "missing_contract":
        del report["producer_native_inputs"]["upa_route_review"]
        expected_error = "Native ontology recorded input contract missing or changed"
    elif damage == "whole_cohort_zero":
        report["producer_native_inputs"]["upa_route_review"] = upa.contract(())
        report["consumed_inputs"] = {
            key: value
            for key, value in report["consumed_inputs"].items()
            if key not in upa.ROLES or key == upa.POLICY_ROLE
        }
        audit = [
            {
                "record_kind": "checkpoint",
                "evidence_json": upa.canonical(
                    {
                        "contract": upa.contract(()),
                        "inputs": {upa.POLICY_ROLE: report["consumed_inputs"][upa.POLICY_ROLE]},
                        "candidate_count": 0,
                        "generated_count": 0,
                    }
                ),
            }
        ]
        changed_audit = True
        expected_error = "Native ontology recorded input contract missing or changed"
    elif damage == "missing_selected_role":
        del report["consumed_inputs"][upa.OWL_ROLE]
        checkpoint = json.loads(audit[-1]["evidence_json"])
        del checkpoint["inputs"][upa.OWL_ROLE]
        audit[-1]["evidence_json"] = upa.canonical(checkpoint)
        changed_audit = True
        expected_error = "UPA recorded consumed-role cohort is missing or enlarged"
    elif damage == "changed_witness":
        row = next(item for item in audit if item["record_kind"] == "candidate")
        witness = json.loads(row["evidence_json"])
        witness["witnesses"][0]["native_nodes"][0]["record"]["lbl"] = "invented native evidence"
        row["evidence_json"] = upa.canonical(witness)
        changed_audit = True
    elif damage == "erased_evidence":
        checkpoint = json.loads(audit[-1]["evidence_json"])
        checkpoint["candidate_count"] = checkpoint["generated_count"] = 0
        audit = [{"record_kind": "checkpoint", "evidence_json": upa.canonical(checkpoint)}]
        changed_audit = True
    else:
        assert damage == "reintroduced_current_id"
        edges_path = transform.output_dir / "upa_edges.tsv"
        graph = rows(edges_path)
        original_rows = copy.deepcopy(graph)
        rule = next(item for item in policy["rules"] if item["canonical_go"] == "GO:0004420")
        addition = {column: "" for column in graph[0]}
        addition.update(
            subject=rule["canonical_go"],
            predicate="biolink:part_of",
            object=rule["pathway"],
            relation="BFO:0000050",
            primary_knowledge_source="infores:upa",
            knowledge_level="knowledge_assertion",
            agent_type="manual_agent",
        )
        graph.append(addition)
        write_rows(edges_path, graph)
        assert rows(edges_path)[:-1] == original_rows
        report["members"][edges_path.name] = identity(edges_path)
        expected_error = "UPA current graph differs from its original/identity-only projected rows"
    if changed_audit:
        write_rows(audit_path, audit, fields=upa.AUDIT_FIELDS, quoted=True)
        report["audit_members"][upa.AUDIT_FILE] = identity(audit_path)
        report["producer_audit_members"][upa.AUDIT_FILE] = identity(audit_path)
    (transform.output_dir / "upa_source_finalization.json").write_text(json.dumps(report, sort_keys=True))
    return expected_error


@pytest.mark.parametrize("route", ["generic_public", "fresh_repeat"])
@pytest.mark.parametrize(
    "damage",
    [
        "missing_contract",
        "whole_cohort_zero",
        "missing_selected_role",
        "changed_witness",
        "erased_evidence",
        "reintroduced_current_id",
    ],
)
def test_generic_public_routes_reject_coherent_outer_restamps_with_native_specific_error(
    tmp_path, monkeypatch, route, damage
):
    """Coherent saved receipts cannot override original native observations or admit an excluded edge."""
    transform, policy, _, original = run_upa(tmp_path, monkeypatch, finalize=True)
    paths = [transform.output_dir / name for name in upa.MEMBERS]
    verify_finalized_source_files(paths)
    report = copy.deepcopy(original)
    inputs_before = {
        value["path"]: hashlib.sha256(Path(value["path"]).read_bytes()).hexdigest()
        for value in original["consumed_inputs"].values()
    }
    expected_error = mutate_saved_contract(transform, report, policy, damage)
    assert inputs_before == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in inputs_before}
    before = published_bytes(transform.output_dir)
    with pytest.raises(SourceFinalizationRequired, match=expected_error):
        if route == "generic_public":
            verify_finalized_source_files(paths)
        else:
            OntologiesTransform(transform.input_base_dir, transform.output_base_dir).finalize(file_prefix="upa_")
    assert published_bytes(transform.output_dir) == before
