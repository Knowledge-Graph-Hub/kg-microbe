"""Bind FOODON proof to actual selected members through live and public recorded lifecycles."""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import foodon_kernel_quarantine as native
from kg_microbe.utils.foodon_kernel_producer import MEMBERS, verify_kernel_audit_bindings
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from tests.test_foodon_kernel_quarantine import prepare, publish
from tests.test_merge_source_freshness import prepare_source

FIXTURE = Path(__file__).parent / "resources/ontology_parent_dispositions"
pytestmark = pytest.mark.usefixtures("local_source_schema")


def identity(path):
    """Restamp only explicit disposable output bytes, not any native authority."""
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def write_rows(path, rows, fields, *, quoting=csv.QUOTE_NONE):
    """Preserve canonical field order and the actual source TSV dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("damage", ["all_declarations", "one_declaration", "node_file", "one_retained_edge"])
def test_active_kernel_requires_all22_declarations_and30_retained_claims(tmp_path, damage):
    """Expose the old empty-declaration bypass independently of the shared-directory scope defect."""
    transform, guard, audit = prepare(tmp_path)
    publish(transform, guard, audit)
    nodes = transform.output_dir / MEMBERS[0]
    edges = transform.output_dir / MEMBERS[1]
    if damage == "node_file":
        nodes.unlink()
    else:
        path = edges if damage == "one_retained_edge" else nodes
        rows = list(graph_rows(path))
        kept = [] if damage == "all_declarations" else rows[1:]
        write_rows(path, kept, list(rows[0]))
    with pytest.raises((SourceFinalizationRequired, ValueError), match="FOODON kernel|Missing|missing|No such"):
        verify_kernel_audit_bindings(transform.output_dir, transform.consumed_input_snapshots, members=MEMBERS)


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_zero_cannot_publish_selected_foodon_and_failure_is_sticky(tmp_path, restored, partial):
    """Use a genuine zero producer; only change public file selection, never private guard state."""
    transform = prepare_source(tmp_path, "ontologies", prefix="chebi_", marker=False)
    if restored:
        transform = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
        transform.finalize(file_prefix="chebi_")
    for kind in ("nodes",) if partial else ("nodes", "edges"):
        shutil.copyfile(transform.output_dir / f"chebi_{kind}.tsv", transform.output_dir / f"foodon_{kind}.tsv")
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    with pytest.raises(SourceFinalizationRequired, match="FOODON kernel.*(staged scope|selected node/edge pair)"):
        transform.finalize(file_prefix="" if partial else "foodon_", fresh_run=True)
    assert before == {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    with pytest.raises(SourceFinalizationRequired, match="FOODON kernel.*(previously failed|original binding changed)"):
        transform.verify_native_inputs()


@pytest.fixture(scope="module")
def shared_directory_seed(tmp_path_factory):
    """Run the actual dispatcher twice with pinned full native excerpts and the local model."""
    root = tmp_path_factory.mktemp("foodon-envo-selected-scope")
    raw = root / "raw"
    raw.mkdir()
    for name in ("foodon.json", "envo.json", "po.owl"):
        shutil.copyfile(FIXTURE / "lifecycle" / name, raw / name)
    shutil.copyfile(FIXTURE / "foodon.owl", raw / "foodon.owl")
    script = r"""
import importlib, json, shutil, socket, sys
from pathlib import Path
def offline(*args, **kwargs):
    raise AssertionError("Kernel selected-source control must stay offline")
socket.getaddrinfo = offline
socket.socket.connect = offline
dispatcher = importlib.import_module("kg_microbe.transform")
from kg_microbe.transform_utils.ontologies import ontologies_transform as module
from kg_microbe.utils.source_finalization import verify_finalized_source_files, SourceFinalizationRequired
raw, output, snapshot = map(Path, sys.argv[1:4])
module.ONTOLOGIES_MAP = {"foodon": "foodon.json", "envo": "envo.json"}
dispatcher._run_one("foodon", raw, output, False)
directory = output / "ontologies"
foodon_path = directory / "foodon_source_finalization.json"
first = json.loads(foodon_path.read_text())
assert set(first["members"]) == {"foodon_nodes.tsv", "foodon_edges.tsv"}
verify_finalized_source_files([directory / name for name in first["members"]])
fresh = module.OntologiesTransform(raw, output)
assert fresh.finalize(file_prefix="foodon_") == first
fresh.verify_consumed_inputs()
shutil.copytree(directory, snapshot)
before = {name: (directory / name).read_bytes() for name in (*first["members"], foodon_path.name)}
dispatcher._run_one("envo", raw, output, False)
assert before == {name: (directory / name).read_bytes() for name in before}
report_path = directory / "envo_source_finalization.json"
report = json.loads(report_path.read_text())
assert set(report["members"]) == {"envo_nodes.tsv", "envo_edges.tsv"}
assert "ontology_foodon_kernel_json" not in report["consumed_inputs"]
assert "ontology_foodon_kernel_owl" not in report["consumed_inputs"]
fresh = module.OntologiesTransform(raw, output)
assert fresh.finalize(file_prefix="envo_") == report
fresh.verify_consumed_inputs()
verify_finalized_source_files([directory / name for name in report["members"]])
assert not (directory / "source_fingerprint.json").exists()
# Separate old unprefixed-audit limitation: graph/report preservation is not
# continued admission of the old FOODON report after its audit was overwritten.
try:
    verify_finalized_source_files([directory / name for name in first["members"]])
except SourceFinalizationRequired:
    pass
else:
    raise AssertionError("The old FOODON report must not be certified by ENVO's new shared audits")
"""
    model = FIXTURE.parent / "ingredient_bundle/native"
    result = subprocess.run(  # noqa: S603 - fixed offline actual dispatcher control
        [sys.executable, "-c", script, str(raw), str(root / "transformed"), str(root / "foodon_snapshot")],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str(model / "biolink-model.yaml"),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(model / "predicate_mapping.yaml"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return root


def test_actual_shared_directory_scoped_run_repeat_and_public_admission(shared_directory_seed):
    """Admit the ENVO selection without reading or claiming the unrelated FOODON source."""
    directory = shared_directory_seed / "transformed/ontologies"
    verify_finalized_source_files([directory / "envo_nodes.tsv", directory / "envo_edges.tsv"])


def test_envo_late_native_admission_excludes_unselected_foodon_members(shared_directory_seed):
    """Check retained actual read identities, not just a successful return code."""
    directory = shared_directory_seed / "transformed/ontologies"
    report_path = directory / "envo_source_finalization.json"
    report = json.loads(report_path.read_text())
    admission = SourceAdmission()
    OntologiesTransform.verify_recorded_native_inputs(report, report_path, admission=admission)
    assert not {directory / name for name in MEMBERS} & set(admission.identities)
    assert native.JSON_ROLE not in report["consumed_inputs"]
    assert native.OWL_ROLE not in report["consumed_inputs"]
    admission.verify()


@pytest.mark.parametrize("role", [native.JSON_ROLE, native.OWL_ROLE])
def test_restored_zero_refuses_late_role_addition_and_caught_restore(tmp_path, role):
    """A completed zero invocation cannot silently acquire a native supplier after restoration."""
    original = prepare_source(tmp_path, "ontologies", prefix="chebi_", marker=False)
    transform = OntologiesTransform(original.input_base_dir, original.output_base_dir)
    transform.finalize(file_prefix="chebi_")
    transform._consumed_input_snapshots[role] = dict(transform.consumed_input_snapshots[native.POLICY_ROLE])
    with pytest.raises(SourceFinalizationRequired, match="FOODON kernel restored original binding changed"):
        transform.verify_native_inputs()
    transform._consumed_input_snapshots.pop(role)
    with pytest.raises(SourceFinalizationRequired, match="FOODON kernel restored original binding changed"):
        transform.verify_native_inputs()


@pytest.mark.parametrize("route", ["admission", "fresh_repeat"])
@pytest.mark.parametrize(
    "damage", ["erase_all_declarations", "erase_one_declaration", "missing_json", "missing_owl", "erase_audit"]
)
def test_public_active_kernel_rejects_coherent_outer_restamps(shared_directory_seed, tmp_path, route, damage):
    """Rejoin genuine retained native inputs after output/report mutation, not an outer-hash failure."""
    directory = tmp_path / "transformed/ontologies"
    shutil.copytree(shared_directory_seed / "foodon_snapshot", directory)
    report_path = directory / "foodon_source_finalization.json"
    report = json.loads(report_path.read_text())
    verify_finalized_source_files([directory / name for name in report["members"]])
    original_inputs = {
        item["path"]: hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
        for item in report["consumed_inputs"].values()
    }
    if damage.startswith("erase_") and damage != "erase_audit":
        path = directory / "foodon_nodes.tsv"
        rows = list(graph_rows(path))
        identifiers = (
            native.COHORT_IDS if damage == "erase_all_declarations" else {next(iter(sorted(native.COHORT_IDS)))}
        )
        write_rows(path, [row for row in rows if row["id"] not in identifiers], list(rows[0]))
        report["members"][path.name] = identity(path)
        expected = "FOODON kernel graph declarations lack complete native evidence"
    elif damage == "erase_audit":
        from kg_microbe.utils.foodon_kernel_producer import AUDIT_FIELDS

        path = directory / native.AUDIT_FILE
        write_rows(path, [], AUDIT_FIELDS, quoting=csv.QUOTE_MINIMAL)
        for key in ("audit_members", "producer_audit_members"):
            report[key][path.name] = identity(path)
        expected = "FOODON kernel audit/native cohort mismatch"
    else:
        del report["consumed_inputs"][native.JSON_ROLE if damage == "missing_json" else native.OWL_ROLE]
        expected = (
            "FOODON kernel selected members/native role scope differ"
            if damage == "missing_json"
            else "Missing FOODON kernel input role"
        )
    report_path.write_text(json.dumps(report, sort_keys=True))
    assert original_inputs == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in original_inputs}
    before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    with pytest.raises(SourceFinalizationRequired, match=expected):
        if route == "admission":
            verify_finalized_source_files([directory / name for name in report["members"]])
        else:
            OntologiesTransform(Path(report["raw_input_directory"]), directory.parent).finalize(file_prefix="foodon_")
    assert before == {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
