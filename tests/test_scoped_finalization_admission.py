"""Current exact source certificates supersede obsolete scoped certificates, never validation."""

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import (
    FINALIZATION_FILE,
    FINALIZATION_VERSION,
    SourceFinalizationRequired,
    verify_finalized_source_files,
)

FIXTURES = Path(__file__).parent / "resources" / "source_finalization_review"


def _prepared(tmp_path):
    """Finalize an actual immutable two-file fixture under isolated raw/output roots."""
    raw = tmp_path / "raw"
    raw.mkdir()
    producer = Transform("fixture", raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"pato_{kind}.tsv", producer.output_dir / f"{kind}.tsv")
    report = producer.finalize(fresh_run=True)
    return producer, report


def _scope(producer, report, *, version=1):
    """Make a structurally valid obsolete scoped record without touching graph/audit bytes."""
    scoped = deepcopy(report)
    scoped["version"] = version
    scoped["members"] = {"nodes.tsv": scoped["members"]["nodes.tsv"]}
    path = producer.output_dir / f"pato_{FINALIZATION_FILE}"
    path.write_text(json.dumps(scoped))
    return path, scoped


@pytest.mark.parametrize("version", [1, FINALIZATION_VERSION])
def test_valid_full_record_supersedes_older_scope_without_rewriting(tmp_path, version):
    """An obsolete contract or stale same-version scope cannot poison an independent full certificate."""
    producer, report = _prepared(tmp_path)
    scoped_path, scoped = _scope(producer, report, version=version)
    scoped["finalizer_code"] = "0" * 64
    scoped_path.write_text(json.dumps(scoped))
    before = {path: path.read_bytes() for path in producer.output_dir.iterdir() if path.is_file()}
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    assert {path: path.read_bytes() for path in before} == before


def test_obsolete_scope_alone_cannot_certify_current_graph(tmp_path):
    """Legacy bytes matching exactly do not substitute for a current finalization contract."""
    producer, report = _prepared(tmp_path)
    _scope(producer, report)
    (producer.output_dir / FINALIZATION_FILE).unlink()
    with pytest.raises(SourceFinalizationRequired, match="absent/stale|Unsupported"):
        verify_finalized_source_files([producer.output_node_file])


def test_full_fresh_rerun_upgrades_certificate_without_deleting_old_scope(tmp_path):
    """Fresh producer completion upgrades even identical graph bytes while retaining obsolete receipts."""
    producer, report = _prepared(tmp_path)
    legacy_path, _ = _scope(producer, report)
    old_receipt = legacy_path.read_bytes()
    report["version"] = 1
    (producer.output_dir / FINALIZATION_FILE).write_text(json.dumps(report))
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    current = producer.finalize(fresh_run=True)
    assert current["version"] == FINALIZATION_VERSION
    assert before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())
    assert legacy_path.read_bytes() == old_receipt
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


@pytest.mark.parametrize("damage", ["member_hash", "finalizer_code", "authority", "audit", "unrelated_member"])
def test_legacy_scope_cannot_bypass_current_certificate_checks(tmp_path, damage):
    """Every accepted file still needs an exact v2 record with valid code, inputs and audit evidence."""
    producer, report = _prepared(tmp_path)
    _scope(producer, report)
    if damage == "member_hash":
        report["members"]["nodes.tsv"]["sha256"] = "0" * 64
    elif damage == "finalizer_code":
        report["finalizer_code"] = "0" * 64
    elif damage == "authority":
        report["inputs"] = [{"path": str(tmp_path / "missing-authority"), "sha256": "0" * 64}]
    elif damage == "audit":
        report["audit_members"]["source_canonicalization.tsv"]["sha256"] = "0" * 64
    else:
        report["members"].pop("nodes.tsv")
    (producer.output_dir / FINALIZATION_FILE).write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([producer.output_node_file])


@pytest.mark.parametrize("version", [1, FINALIZATION_VERSION])
@pytest.mark.parametrize("damage", ["invalid_json", "not_object", "members", "member_identity", "inputs", "audits"])
def test_malformed_scope_is_not_silently_ignored(tmp_path, version, damage):
    """Skipping a known old contract is not permission to suppress unreadable or malformed certificates."""
    producer, report = _prepared(tmp_path)
    path, scoped = _scope(producer, report, version=version)
    if damage == "invalid_json":
        path.write_text("{broken")
    else:
        if damage == "not_object":
            scoped = []
        elif damage == "members":
            scoped["members"] = []
        elif damage == "member_identity":
            scoped["members"]["nodes.tsv"]["bytes"] = "not a byte count"
        elif damage == "inputs":
            scoped["inputs"] = "not an input list"
        else:
            scoped["audit_members"] = []
        path.write_text(json.dumps(scoped))
    with pytest.raises(SourceFinalizationRequired, match="Unreadable|Malformed|Unsupported"):
        verify_finalized_source_files([producer.output_node_file])


def test_unknown_future_contract_cannot_be_ignored(tmp_path):
    """Only the known obsolete v1 format is superseded, not unfamiliar future semantics."""
    producer, report = _prepared(tmp_path)
    _scope(producer, report, version=FINALIZATION_VERSION + 1)
    with pytest.raises(SourceFinalizationRequired, match="Unsupported"):
        verify_finalized_source_files([producer.output_node_file])
