"""The finite ENVO/MONDO supplier extension preserves prior claims and complete native evidence."""

import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_native_ro_retention import FIXTURE, ORIGIN, POLICY, audit_rows, frame, prepare

SUPPLIERS = ("pato", "uberon", "envo", "mondo")


def test_extension_preserves_original326_controls_declarations_and_pins():
    """Check the complete prior contract, not only totals shared by different claims."""
    previous = copy.deepcopy(POLICY)
    previous["records"] = [row for row in previous["records"] if row["ontology"] in {"pato", "uberon"}]
    previous["authorities"] = {
        key: value for key, value in previous["authorities"].items() if key in {"pato.json", "uberon.json", "ro.json"}
    }
    previous["finite_cohort_sha256"] = native._digest(native._json(previous["records"]).encode())
    assert previous["records"] == POLICY["records"][:326]
    assert previous["finite_cohort_sha256"] == "93b0ba1b3859c6a4c00a9e5f54e7dfcb45fd7ed4b1900c5f3fb4f68245a465bf"
    assert (
        native._digest(native._json(previous).encode())
        == "a0ed9d62792f7f2479b1f2a0cb8e3f7f6f91e6f3e38e381945400535916349a3"
    )
    assert len(POLICY["unchanged_records"]) == 8 and len(POLICY["relations"]) == 14
    assert Counter(row["ontology"] for row in POLICY["records"]) == {"pato": 74, "uberon": 252, "envo": 2, "mondo": 188}
    old_keys = {(r["subject"], r["relation"], r["object"]) for r in previous["records"]}
    mondo = native._cohort(POLICY, "mondo")
    assert len(set(mondo) & old_keys) == 126
    assert sum(key[0].startswith("HsapDv:") and key[1] == "RO:0002087" for key in mondo) == 61
    assert len(set(mondo) & set(native._cohort(POLICY, "envo"))) == 1


def test_all516_projection_is_predicate_only_and_audits_remain_supplier_specific(tmp_path, monkeypatch):
    """Preserve every other field, all eight controls and repeated full native witnesses."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=SUPPLIERS)
    for name in SUPPLIERS:
        before = frame(name)
        before["publications"] = "PMID:fixture"
        result = authority.project(name, before, before, name + "_edges.tsv")
        expected = before.copy()
        membership = native._cohort(POLICY, name)
        selected = expected.apply(lambda r, keys=membership: (r["subject"], r["relation"], r["object"]) in keys, axis=1)
        expected.loc[selected, "predicate"] = expected.loc[selected, "relation"]
        pd.testing.assert_frame_equal(result, expected)
        result.to_csv(transform.output_dir / (name + "_edges.tsv"), sep="\t", index=False)
        original_audit = audit.getvalue()
        pd.testing.assert_frame_equal(authority.project(name, result, result, name + "_edges.tsv"), result)
        assert audit.getvalue() == original_audit
    authority.verify_complete()
    rows = audit_rows(audit)
    assert len(rows) == 516
    assert Counter(row["ontology"] for row in rows) == {"pato": 74, "uberon": 252, "envo": 2, "mondo": 188}
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    native.verify_audit_input_bindings(transform.output_dir, transform.consumed_input_snapshots)


@pytest.mark.parametrize("name", ["envo", "mondo"])
@pytest.mark.parametrize("damage", ["added", "deleted", "mutated", "wrong_supplier"])
def test_new_emitted_supplier_scope_refuses_unreviewed_changes(tmp_path, monkeypatch, name, damage):
    """A relation and even a shared triple do not authorize a different source assertion."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=(name,))
    rows = frame(name)
    if damage == "added":
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
        rows.loc[len(rows) - 1, "subject"] = "fixture:unreviewed"
    elif damage == "deleted":
        rows = rows.drop(index=0)
    elif damage == "mutated":
        rows.loc[0, "object"] = "fixture:unreviewed"
    else:
        rows.loc[0, "primary_knowledge_source"] = "infores:uberon"
    with pytest.raises(ValueError):
        authority.project(name, rows, rows, name + "_edges.tsv")
    assert not audit_rows(audit)


@pytest.mark.parametrize("name", ["envo", "mondo"])
@pytest.mark.parametrize(
    "damage", ["missing_role", "authority", "empty_audit", "missing_row", "extra_row", "metadata", "supplier"]
)
def test_new_supplier_recorded_admission_refuses_detached_or_mutated_evidence(tmp_path, monkeypatch, name, damage):
    """Exercise the registered hook after producer state is gone, including source-overlapping claims."""
    transform, authority, audit = prepare(tmp_path, monkeypatch, sources=(name,))
    rows = frame(name)
    retained = authority.project(name, rows, rows, name + "_edges.tsv")
    path = transform.output_dir / (name + "_edges.tsv")
    retained.to_csv(path, sep="\t", index=False)
    audit_path = transform.output_dir / native.AUDIT_FILE
    audit_path.write_text(audit.getvalue())
    authority.verify_complete()
    report = {
        "consumed_inputs": copy.deepcopy(transform.consumed_input_snapshots),
        "producer_native_inputs": transform.producer_native_inputs,
    }
    type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")
    if damage == "missing_role":
        report["consumed_inputs"].pop("ontology_native_relation_" + name)
    elif damage == "authority":
        authority_path = transform.input_base_dir / (name + ".json")
        authority_path.write_bytes(authority_path.read_bytes() + b"\n")
    elif damage == "empty_audit":
        audit_path.write_text(audit.getvalue().splitlines()[0] + "\n")
    else:
        if damage == "missing_row":
            retained = retained.drop(index=0)
        elif damage == "extra_row":
            retained = pd.concat([retained, retained.iloc[[0]]], ignore_index=True)
        elif damage == "metadata":
            retained.loc[0, "knowledge_level"] = "prediction"
        else:
            retained.loc[0, "primary_knowledge_source"] = "infores:uberon"
        retained.to_csv(path, sep="\t", index=False)
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


def test_unknown_supplier_is_not_admitted(tmp_path, monkeypatch):
    """Protected predicates are finite supplier evidence, not prefix-based permission."""
    transform, authority, _ = prepare(tmp_path, monkeypatch, sources=())
    with pytest.raises(ValueError, match="supplier"):
        authority.prepare_source("hp", transform.input_base_dir / "mondo.json")


def execute_parse_fixture(raw, output, policy, policy_digest, name):
    """Run real parsing/finalization with truthful finite native and GO authority fixtures."""
    from kg_microbe.utils import go_authority

    raw, output = Path(raw), Path(output)
    native.POLICY_FILE = Path(policy)
    native.REVIEWED_POLICY_SHA256 = policy_digest
    metadata_path = FIXTURE / "mondo_go_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    evidence = ORIGIN["go_metadata_fixture"]
    assert hashlib.sha256(metadata_path.read_bytes()).hexdigest() == evidence["fixture_sha256"]
    assert metadata["full_source_sha256"] == evidence["full_source_sha256"]
    assert metadata["full_source_bytes"] == evidence["full_source_bytes"]
    assert len(metadata["identifiers"]) == evidence["identifiers"] == 45
    assert len(metadata["statements"]) == evidence["statements"] == 142
    go = go_authority.GoAuthority.from_statements(
        metadata["statements"],
        authority_path=str(metadata_path),
        authority_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        structural_edges=frozenset(),
    )

    def load_fixture_go(selected):
        """Resolve only the chosen fixture raw root, using independently captured exact GO metadata."""
        assert Path(selected) == raw
        return go

    go_authority.load_go_authority = load_fixture_go
    if name == "mondo":
        # Imported temporal classes use the existing verbatim native ancestry
        # fixture and its explicit fixture-only policy pin, not a fake category.
        from kg_microbe.utils import uberon_temporal_categories as temporal
        from tests.test_uberon_temporal_categories import FIXTURE as TEMPORAL_FIXTURE
        from tests.test_uberon_temporal_categories import _policy as temporal_policy

        (raw / "uberon.json").write_bytes((TEMPORAL_FIXTURE / "uberon.json").read_bytes())
        temporal_path = raw.parent / "temporal-policy.json"
        temporal_path.write_text(json.dumps(temporal_policy()))
        temporal.TEMPORAL_DISPOSITIONS_FILE = temporal_path
    transform = OntologiesTransform(raw, output)
    # Run all real authority lifecycles. ENVO has no quarantined parent rows,
    # but its native parent, converter and selected-member receipts are real.
    transform.run(data_file=name + ".json")
    expected = {
        "path": str((raw / (name + ".json")).resolve()),
        "sha256": ORIGIN["native_files"][name + ".json"]["fixture_sha256"],
    }
    assert transform.consumed_input_snapshots["ontology_native_relation_" + name] == expected
    if name == "envo":
        assert transform.consumed_input_snapshots["ontology_native_envo"] == expected
        assert transform.consumed_input_snapshots["ontology_parent_envo_json"] == expected
        sanitized = transform.consumed_input_snapshots["ontology_metadata_envo"]
        assert sanitized["path"] != expected["path"] and sanitized["sha256"] != expected["sha256"]
    report = transform.finalize(fresh_run=True)
    paths = [transform.output_dir / (name + suffix) for suffix in ("_nodes.tsv", "_edges.tsv")]
    verify_finalized_source_files(paths)
    type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")
    with paths[1].open() as stream:
        retained = list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))
    selected = [row for row in retained if row["relation"] in POLICY["relations"]]
    assert len(selected) == {"envo": 2, "mondo": 188}[name]
    assert all(row["predicate"] == row["relation"] for row in selected)
    assert all(row["primary_knowledge_source"] == "infores:" + name for row in selected)
    # The read-only native file and the original read role survive finalization.
    assert hashlib.sha256((raw / (name + ".json")).read_bytes()).hexdigest() == expected["sha256"]
    assert report["consumed_inputs"]["ontology_native_relation_" + name] == expected
    if name == "envo":
        assert set(report["producer_native_inputs"]["ontology_parent_dispositions"]["members"]) == {
            "envo_nodes.tsv",
            "envo_edges.tsv",
        }
    print(json.dumps({"supplier": name, "retained": len(selected), "finalized_admission": "passed"}))


@pytest.mark.parametrize("name", ["envo", "mondo"])
def test_real_parse_finalize_and_admission_preserve_new_native_supplier(tmp_path, monkeypatch, name):
    """Use a fresh actual KGX reader, with network denied and private sanitation visible."""
    transform, _, _ = prepare(tmp_path, monkeypatch, sources=())
    script = """
import socket, sys
def offline(*args, **kwargs):
    raise AssertionError('Network prohibited in native RO supplier regression')
socket.getaddrinfo = offline
socket.socket.connect = offline
from tests.test_native_ro_supplier_retention import execute_parse_fixture
execute_parse_fixture(*sys.argv[1:])
"""
    model = FIXTURE.parent / "ingredient_bundle/native"
    result = subprocess.run(  # noqa: S603 - fixed offline script and immutable local fixtures
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(transform.input_base_dir),
            str(tmp_path / "actual"),
            str(native.POLICY_FILE),
            native.REVIEWED_POLICY_SHA256,
            name,
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=90,
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str(model / "biolink-model.yaml"),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(model / "predicate_mapping.yaml"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"finalized_admission": "passed"' in result.stdout
