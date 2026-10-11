"""Require explicit graph bytes before attaching historical diagnostic coverage."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.utils import kgm_validation_profile as mod


@pytest.fixture
def cohort(tmp_path):
    """Build a tiny byte-identity fixture, not a real graph-validity claim."""
    profile = json.loads(mod.DEFAULT_PROFILE.read_text())
    reference = json.loads(mod.DEFAULT_REFERENCE.read_text())
    archive = tmp_path / "identity-only.bin"
    archive.write_bytes(b"archive identity test, not TSV validation")
    report = tmp_path / "report.csv"
    with report.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=mod.CSV_FIELDS)
        writer.writeheader()
        for entry in mod.load_profile()["index"].values():
            writer.writerows([entry["original_diagnostic"]] * entry["reference_occurrences"])
    profile["reference"]["csv_sha256"] = mod.file_identity(report)["sha256"]
    profile["reference"]["archive_sha256"] = mod.file_identity(archive)["sha256"]
    reference["reference"] = profile["reference"]
    profile_path, reference_path = tmp_path / "profile.json", tmp_path / "reference.json"
    profile_path.write_text(json.dumps(profile))
    reference_path.write_text(json.dumps(reference))
    return report, archive, {"profile_path": profile_path, "reference_path": reference_path}


def test_exact_csv_without_graph_cannot_inherit_row_coverage(cohort):
    """Byte-identical reports alone do not establish their originating graph."""
    report, _, kwargs = cohort
    result = mod.classify_kgxval_report(report, require_reference_cohort=True, **kwargs)
    assert result["reference_cohort_matches"] is True
    assert result["reference_evidence_applies"] is False
    assert result["reference_assessment_counts"] == {}
    assert all(item["reference_assessment"] is None for item in result["diagnostics"])
    assert result["supplied_graph_archive"] is None
    assert result["reference_epoch"]["archive_sha256"]


def test_matching_csv_and_archive_bind_historical_assessments(cohort):
    """Explicit binding is still not validator execution or release approval."""
    report, archive, kwargs = cohort
    result = mod.classify_kgxval_report(report, graph_archive_path=archive, require_reference_cohort=True, **kwargs)
    assert result["reference_evidence_applies"] is True
    assert result["reference_assessment_counts"]["documented_row_convention_supported"] == 13
    assert result["supplied_graph_archive"] == {"path": str(archive.resolve()), **mod.file_identity(archive)}
    assert result["inputs"][str(archive.resolve())] == mod.file_identity(archive)
    assert result["inputs_unchanged"] is True
    assert result["scientific_acceptance"] is result["strict_conformance"] is result["release_authorized"] is False


def test_changed_archive_cannot_inherit_identical_csv_coverage(cohort, tmp_path):
    """A different graph either lacks historical coverage or fails explicit requirements."""
    report, _, kwargs = cohort
    other = tmp_path / "different.bin"
    other.write_bytes(b"different graph")
    result = mod.classify_kgxval_report(report, graph_archive_path=other, **kwargs)
    assert result["reference_cohort_matches"] is True
    assert result["reference_evidence_applies"] is False
    with pytest.raises(ValueError, match="graph archive differs"):
        mod.classify_kgxval_report(report, graph_archive_path=other, require_reference_cohort=True, **kwargs)


def test_archive_identity_has_before_after_guards(cohort, monkeypatch):
    """The explicit archive is part of the unchanged-input contract."""
    report, archive, kwargs = cohort
    original = mod.file_identity
    calls = 0

    def identity(path):
        """Simulate a changed second digest without modifying any real input."""
        nonlocal calls
        actual = original(path)
        if Path(path) == archive:
            calls += 1
            if calls > 1:
                return {**actual, "sha256": "0" * 64}
        return actual

    monkeypatch.setattr(mod, "file_identity", identity)
    with pytest.raises(ValueError, match="input bytes changed"):
        mod.classify_kgxval_report(report, graph_archive_path=archive, **kwargs)
    assert calls == 2


def test_matching_archive_with_changed_csv_does_not_attach(cohort):
    """Familiar counts and graph identity still require original CSV bytes."""
    report, archive, kwargs = cohort
    report.write_bytes(report.read_bytes().replace(b"\r\n", b"\n"))
    result = mod.classify_kgxval_report(report, graph_archive_path=archive, **kwargs)
    assert result["reference_cohort_matches"] is True
    assert result["reference_evidence_applies"] is False


@pytest.mark.parametrize(
    "defect",
    [
        "join_locator",
        "join_hash",
        "join_hash_shape",
        "join_size",
        "witness_hash",
        "witness_hash_shape",
        "endpoints",
        "endpoint_id",
        "endpoint_category",
        "endpoint_provider",
    ],
)
def test_mandatory_reference_evidence_shapes(tmp_path, defect):
    """Local shape guards do not authenticate the external saved join file."""
    catalog = json.loads(mod.DEFAULT_REFERENCE.read_text())
    witness = catalog["diagnostics"][0]["witnesses"][0]
    if defect == "join_locator":
        catalog["evidence_join"].pop("path")
    elif defect == "join_hash":
        catalog["evidence_join"].pop("sha256")
    elif defect == "join_hash_shape":
        catalog["evidence_join"]["sha256"] = "not-a-digest"
    elif defect == "join_size":
        catalog["evidence_join"]["bytes"] = True
    elif defect == "witness_hash":
        witness.pop("original_full_row_sha256")
    elif defect == "witness_hash_shape":
        witness["original_full_row_sha256"] = "a" * 63
    elif defect == "endpoints":
        witness["endpoint_declarations"] = []
    elif defect == "endpoint_id":
        witness["endpoint_declarations"][0]["id"] = "different:1"
    elif defect == "endpoint_category":
        witness["endpoint_declarations"][0]["category"] = "biolink:NamedThing"
    else:
        witness["endpoint_declarations"][0].pop("provided_by")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):
        mod.load_reference_dispositions(path)
