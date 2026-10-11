"""Finite native evidence and actual converter/projection conservation (#1355/#1356)."""

import copy
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import ontology_parent_quarantine as native
from kg_microbe.utils.source_finalization import graph_rows

FIXTURE = Path(__file__).parent / "resources/ontology_parent_dispositions"
POLICY = json.loads(native.POLICY_FILE.read_text())


def document(name):
    """Read a genuine native fixture without mutating shared bytes."""
    return json.loads((FIXTURE / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["foodon", "envo"])
def test_native_full_context_and_all_source_rows_rejoin(name):
    """All 103 incident assertions have native witnesses; fourteen alone are quarantined."""
    spec = POLICY["sources"][name]
    assert native.json_context(document(name), spec) == spec["json_context"]
    assert len(spec["quarantines"]) == {"foodon": 13, "envo": 1}[name]
    assert len(spec["source_incidence"]) == {"foodon": 98, "envo": 5}[name]
    if name == "foodon":
        with (FIXTURE / "foodon.owl").open("rb") as stream:
            assert native.owl_context(stream, spec) == spec["owl_context"]


@pytest.mark.parametrize(
    "damage", ["definition", "named_parent", "duplicate_edge", "missing_node", "logical_definition"]
)
def test_native_changes_require_new_review(damage):
    """A self-restamped source cannot silently redefine the finite scientific scope."""
    value = document("foodon")
    graph = value["graphs"][0]
    subject = "http://purl.obolibrary.org/obo/FOODON_03411479"
    selected = next(node for node in graph["nodes"] if node["id"] == subject)
    edge = next(edge for edge in graph["edges"] if edge["sub"] == subject and edge["pred"] == "is_a")
    if damage == "definition":
        selected.setdefault("meta", {})["definition"] = {"val": "Unreviewed replacement"}
    elif damage == "named_parent":
        edge["obj"] = "http://purl.obolibrary.org/obo/FOODON_00002576"
    elif damage == "duplicate_edge":
        graph["edges"].append(copy.deepcopy(edge))
    elif damage == "missing_node":
        graph["nodes"].remove(selected)
    else:
        axiom = next(
            item
            for item in graph["logicalDefinitionAxioms"]
            if item["definedClassId"] == "http://purl.obolibrary.org/obo/FOODON_03308553"
        )
        assert subject in axiom["genusIds"]
        axiom["genusIds"] = []
    with pytest.raises(ValueError, match="native|cohort"):
        native.json_context(value, POLICY["sources"]["foodon"])


def test_ambiguous_cases_and_unsolved_expressions_are_preserved():
    """A part-or-carcass annotation is not a selection rule; expressions stay explicit."""
    spec = POLICY["sources"]["foodon"]
    ambiguous = {
        f"FOODON:{value}" for value in ("03301771", "03317630", "03308428", "03308431", "03308442", "03309238")
    }
    assert ambiguous <= set(spec["incident_ids"])
    assert not ambiguous & {row["subject"] for row in spec["quarantines"]}
    retained, prior = native._expected_rows(spec, retained=True), spec["source_incidence"]
    for identifier in ambiguous:
        assert [row for row in retained if row["subject"] == identifier] == [
            row for row in prior if row["subject"] == identifier
        ]
    assert {
        "definedClassId": "http://purl.obolibrary.org/obo/FOODON_03308553",
        "genusIds": [
            "http://purl.obolibrary.org/obo/FOODON_03301193",
            "http://purl.obolibrary.org/obo/FOODON_03411479",
        ],
    } in spec["json_context"]["logical_definitions"]
    assert all("not repaired upstream OWL" in row["remaining_native_expression_caveat"] for row in spec["quarantines"])


def test_policy_receipt_cannot_redefine_scientific_cohort():
    """The independently code-pinned policy rejects a coherently restamped new rule."""
    policy = copy.deepcopy(POLICY)
    policy["sources"]["foodon"]["quarantines"].pop()
    with pytest.raises(ValueError, match="Unreviewed"):
        native.load_policy(io.StringIO(json.dumps(policy)))


@pytest.fixture(scope="module")
def producer_seed(tmp_path_factory):
    """Run actual KGX once; copies retain this immutable native/trace authority."""
    tmp_path = tmp_path_factory.mktemp("parent14-native")
    raw = tmp_path / "raw"
    raw.mkdir()
    for filename in ("foodon.json", "foodon.owl", "envo.json"):
        shutil.copyfile(FIXTURE / filename, raw / filename)
    script = r"""
import csv, json, socket, sys
from collections import Counter
from pathlib import Path
def offline(*args, **kwargs):
    raise AssertionError("Network prohibited in parent-disposition regression")
socket.getaddrinfo = offline
socket.socket.connect = offline
from kg_microbe.transform_utils.ontologies import ontologies_transform as module
from kg_microbe.utils import ontology_parent_quarantine as native
from kg_microbe.utils.source_finalization import graph_rows
module.ONTOLOGIES_MAP = {"foodon": "foodon.json", "envo": "envo.json"}
real_project = native.OntologyParentQuarantine.project
checks = {}
def measured(self, name, frame, originals):
    before = Counter(native._payload(row) for row in frame.to_dict("records"))
    nodes_path = self.transform.output_dir / f"{name}_nodes.tsv"
    nodes_before = nodes_path.read_bytes()
    result = real_project(self, name, frame, originals)
    removed = [row for row in frame.to_dict("records") if native._key(row) in {
        native._reject_key(item) for item in self.policy["sources"][name]["quarantines"]
    }]
    remaining = Counter(native._payload(row) for row in result.to_dict("records"))
    assert remaining == before - Counter(map(native._payload, removed))
    assert nodes_path.read_bytes() == nodes_before
    checks[name] = {
        "removed": len(removed), "nodes_unchanged_at_projection": True,
        "all_other_full_rows_unchanged": True,
    }
    return result
native.OntologyParentQuarantine.project = measured
transform = module.OntologiesTransform(Path(sys.argv[1]), Path(sys.argv[2]))
transform.run()
transform.verify_consumed_inputs()
assert checks["foodon"]["removed"] == 13 and checks["envo"]["removed"] == 1
assert len(list(graph_rows(transform.output_dir / "foodon_kernel_quarantine.tsv", quoting=csv.QUOTE_MINIMAL))) == 1
assert len(native._read_tsv((transform.output_dir / native.AUDIT_FILE).read_bytes(), quoting=csv.QUOTE_MINIMAL)) == 14
report = {
    "producer_native_inputs": transform.producer_native_inputs,
    "consumed_inputs": transform.consumed_input_snapshots,
    "producer_audit_members": transform.producer_audit_snapshots,
    "members": {name: {} for name in ("foodon_nodes.tsv", "foodon_edges.tsv", "envo_nodes.tsv", "envo_edges.tsv")},
    "scope": "Real producer/native-audit verification only; not a fabricated source-finalization marker",
    "same_stage_checks": checks,
}
path = transform.output_dir / "producer-test-evidence.json"
path.write_text(json.dumps(report, sort_keys=True))
native.verify_audit_bindings(
    transform.output_dir, report["consumed_inputs"],
    members=report["members"], graph_quoting=csv.QUOTE_MINIMAL,
)
print(path)
"""
    model = FIXTURE.parent / "ingredient_bundle/native"
    result = subprocess.run(  # noqa: S603 - fixed offline script and immutable local fixtures
        [sys.executable, "-c", script, str(raw), str(tmp_path / "transformed")],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str(model / "biolink-model.yaml"),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(model / "predicate_mapping.yaml"),
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / "transformed/ontologies"


@pytest.fixture
def genuine_producer(producer_seed, tmp_path):
    """Copy disposable outputs, leaving immutable original read receipts untouched."""
    directory = tmp_path / "candidate"
    shutil.copytree(producer_seed, directory)
    return directory, json.loads((directory / "producer-test-evidence.json").read_text())


def write_rows(path, rows, *, fields=None, quoting=csv.QUOTE_NONE):
    """Change one disposable artifact with explicit header and dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields or tuple(rows[0]),
            delimiter="\t",
            lineterminator="\n",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
        )
        writer.writeheader()
        writer.writerows(rows)


def verify(directory, report):
    """Rejoin real pre-finalization producer bytes; public lifecycle has a separate full test module."""
    native.verify_audit_bindings(
        directory, report["consumed_inputs"], members=report["members"], graph_quoting=csv.QUOTE_MINIMAL
    )


def test_actual_converter_exact_fourteen_and_separate_kernel(genuine_producer):
    """Both suppliers leave nodes and all unrelated full edges unchanged at projection."""
    directory, report = genuine_producer
    assert report["same_stage_checks"]["foodon"]["removed"] == 13
    assert report["same_stage_checks"]["envo"]["removed"] == 1
    verify(directory, report)


@pytest.mark.parametrize(
    "field",
    [
        "rationale",
        "native_context_json",
        "native_assertion_json",
        "canonical_prior_row_json",
        "normalization_input_row_json",
        "remaining_native_expression_caveat",
        "consumed_inputs_json",
    ],
)
def test_every_mandatory_audit_cell_is_rejoined(genuine_producer, field):
    """An outer restamped receipt cannot replace original full scientific evidence."""
    directory, report = genuine_producer
    path = directory / native.AUDIT_FILE
    rows = native._read_tsv(path.read_bytes(), quoting=csv.QUOTE_MINIMAL)
    rows[0][field] = ""
    write_rows(path, rows, fields=native.AUDIT_FIELDS, quoting=csv.QUOTE_MINIMAL)
    report["producer_audit_members"][native.AUDIT_FILE] = {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    with pytest.raises(ValueError, match="audit"):
        verify(directory, report)


@pytest.mark.parametrize(
    "damage", ["reinsert", "remove_neighbor", "publications", "knowledge_level", "same_count_swap"]
)
def test_actual_retained_full_rows_not_just_counts(genuine_producer, damage):
    """Keep finite environment/restriction claims and reject invented provenance."""
    directory, report = genuine_producer
    path = directory / "foodon_edges.tsv"
    rows = list(graph_rows(path))
    index = next(i for i, row in enumerate(rows) if row["subject"] == "FOODON:00002765")
    if damage == "reinsert":
        prior = next(
            row
            for row in POLICY["sources"]["foodon"]["source_incidence"]
            if row["subject"] == "FOODON:00002765" and row["object"] == "FOODON:00002576"
        )
        rows.append({column: prior.get(column, "") for column in rows[0]})
    elif damage == "remove_neighbor":
        rows.pop(index)
    elif damage == "same_count_swap":
        rows[index]["object"] = "FOODON:00002576"
    elif damage == "knowledge_level":
        rows[index][damage] = "observation"
    else:
        rows = [{**row, "publications": "PMID:99999999" if i == index else ""} for i, row in enumerate(rows)]
    write_rows(path, rows)
    report["members"][path.name] = {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    with pytest.raises(ValueError, match="retained graph"):
        verify(directory, report)


@pytest.mark.parametrize(
    "role", ["ontology_parent_foodon_json", "ontology_parent_foodon_owl", "ontology_parent_foodon_converter_rows"]
)
def test_original_roles_are_mandatory(genuine_producer, role):
    """Removing one authority/trace role cannot turn an active source into empty scope."""
    directory, report = genuine_producer
    report["consumed_inputs"].pop(role)
    with pytest.raises(ValueError, match="role|scope"):
        verify(directory, report)


def test_blank_added_columns_allowed_nonblank_unknowns_rejected(genuine_producer):
    """Preserve the finalizer's additive blank-schema contract without evidence loss."""
    directory, report = genuine_producer
    path = directory / "envo_edges.tsv"
    rows = [{**row, "publications": "", "subject_aspect_qualifier": ""} for row in graph_rows(path)]
    write_rows(path, rows)
    verify(directory, report)
    next(row for row in rows if row["subject"] == "PCO:0000001")["subject_aspect_qualifier"] = "invented"
    write_rows(path, rows)
    with pytest.raises(ValueError, match="retained graph"):
        verify(directory, report)


def test_fresh_binding_keeps_exact_scope_and_late_roles(genuine_producer, tmp_path):
    """A fresh object retains dynamic roles instead of accepting cached-empty state."""
    _, report = genuine_producer
    fresh = OntologiesTransform(tmp_path / "raw", tmp_path / "transformed")
    fresh._consumed_input_snapshots = copy.deepcopy(report["consumed_inputs"])
    fresh.producer_native_inputs = report["producer_native_inputs"]
    guard = fresh._ontology_parent_input_contract
    assert guard.member_names() == ("envo_edges.tsv", "envo_nodes.tsv", "foodon_edges.tsv", "foodon_nodes.tsv")
    fresh._consumed_input_snapshots.pop("ontology_parent_foodon_owl")
    with pytest.raises(ValueError, match="restored"):
        guard.verify_bindings()


def test_restored_binding_refuses_equal_byte_locator_replacement(genuine_producer, tmp_path):
    """Keep original input inode/locator evidence in addition to its role SHA."""
    _, report = genuine_producer
    fresh = OntologiesTransform(tmp_path / "raw", tmp_path / "transformed")
    snapshots = copy.deepcopy(report["consumed_inputs"])
    identity = snapshots["ontology_parent_foodon_owl"]
    target = tmp_path / "bound-foodon.owl"
    shutil.copyfile(identity["path"], target)
    identity["path"] = str(target)
    fresh._consumed_input_snapshots = snapshots
    fresh.producer_native_inputs = report["producer_native_inputs"]
    guard = fresh._ontology_parent_input_contract
    guard.verify_bindings()
    path = Path(snapshots["ontology_parent_foodon_owl"]["path"])
    replacement = path.with_suffix(".replacement")
    shutil.copyfile(path, replacement)
    replacement.replace(path)
    with pytest.raises(ValueError, match="admitted file changed"):
        guard.verify_bindings()
    with pytest.raises(ValueError, match="restored"):
        guard.verify_bindings()


def test_unrelated_empty_finalization_same_and_fresh_repeat(tmp_path):
    """Use real existing finalizer/marker fixtures; never invent a finalized receipt."""
    from tests.test_merge_source_freshness import prepare_source

    transform = prepare_source(tmp_path, "ontologies")
    transform.verify_consumed_inputs()
    first = transform.finalize()
    assert first["producer_native_inputs"]["ontology_parent_dispositions"]["members"] == []
    assert transform.finalize() == first
    fresh = OntologiesTransform(transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == first
    fresh.verify_consumed_inputs()
