"""Coverage unknowns remain explicit in loose and archived graph artifacts."""

import hashlib
import json
import tarfile

import pytest

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.merge_utils.source_qualifications import package_qualifications, selected_qualifications
from tests.test_merge_canonical_serialization import _configuration, offline_kgx  # noqa: F401


def _admitted(tmp_path, config, *, dependency=False):
    """Supply a source-admitted audit with one scientifically unknown endpoint."""
    audit = tmp_path / "mediadive_endpoint_outcomes.tsv"
    payload = (
        "endpoint\trequested_id\tstate\tobservation_id\tbody_sha256\tobserved_at\n"
        "https://mediadive.dsmz.de/rest/medium-strains/1\t1\tunknown_unavailable\tobservation\tbody\tdate\n"
        "https://mediadive.dsmz.de/rest/medium-strains/2\t2\texplicit_empty\tobservation2\tbody2\tdate\n"
    ).encode()
    audit.write_bytes(payload)
    admission = SourceAdmission()
    admission.capture(config)
    admission.capture(audit)
    admission.source_qualifications = {
        str(tmp_path / "source_finalization.json"): {
            "source": "mediadive",
            "graph_paths": [str(tmp_path / ("dependency/nodes.tsv" if dependency else "input/nodes.tsv"))],
            "summary": {"endpoint_accounting_complete": True, "association_coverage_complete": False},
            "generation": {"version": 1, "manifest_sha256": "immutable-sealed-generation"},
            "audit": {
                "name": audit.name,
                "path": str(audit),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        }
    }
    return admission, audit, payload


@pytest.mark.parametrize("compression", [None, "tar.gz"])
@pytest.mark.parametrize("dependency", [False, True])
def test_public_merge_preserves_unknown_and_empty(tmp_path, monkeypatch, compression, dependency):
    """Selected-source and inherited qualifications survive actual KGX serialization."""
    config, output = _configuration(tmp_path, compression)
    admission, _audit, payload = _admitted(tmp_path, config, dependency=dependency)
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", lambda *_args: admission)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    merge_kg.load_and_merge(str(config))
    name = "merged-kg_mediadive_endpoint_outcomes.tsv"
    if compression:
        with tarfile.open(output / "merged-kg.tar.gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            assert archive.extractfile(name).read() == payload
    else:
        manifest = json.loads((output / "merged-kg_manifest.json").read_text())
        assert (output / name).read_bytes() == payload
    (qualification,) = manifest["provenance"]["source_qualifications"]
    assert qualification["summary"]["association_coverage_complete"] is False
    assert qualification["participation"] == ("admitted_dependency" if dependency else "graph_input")
    assert qualification["endpoint_state_counts"] == {"nonempty": 0, "explicit_empty": 1, "unknown_unavailable": 1}
    assert qualification["audit"]["sha256"] == manifest["members"][name]["sha256"]


def test_changed_audit_cannot_replace_previous_graph(tmp_path, monkeypatch):
    """A mandatory qualification failure preserves the previous published archive."""
    config, output = _configuration(tmp_path, "tar.gz")
    admission, audit, _payload = _admitted(tmp_path, config)
    marker = output / "merged-kg.tar.gz"
    marker.write_bytes(b"previous graph")
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", lambda *_args: admission)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    real = merge_kg.check_merged_invariants

    def change(*args, **kwargs):
        """Model a report mutating an admitted source after its original validation."""
        real(*args, **kwargs)
        audit.write_bytes(audit.read_bytes().replace(b"unknown_unavailable", b"explicit_empty"))

    monkeypatch.setattr(merge_kg, "check_merged_invariants", change)
    with pytest.raises(ValueError, match="audit changed"):
        merge_kg.load_and_merge(str(config))
    assert marker.read_bytes() == b"previous graph"
    assert sorted(path.name for path in output.iterdir()) == [marker.name]


def test_unknown_cannot_be_described_as_complete_associations(tmp_path):
    """Even unchanged endpoint bytes cannot be packaged under a contradictory summary."""
    config, output = _configuration(tmp_path, None)
    admission, _audit, _payload = _admitted(tmp_path, config)
    records = selected_qualifications(admission, [tmp_path / "input/nodes.tsv"])
    records[0]["summary"]["association_coverage_complete"] = True
    with pytest.raises(ValueError, match="disagrees"):
        package_qualifications(records, output, "merged-kg")
    assert not list(output.iterdir())


def test_admission_qualification_is_detached_before_kgx(tmp_path):
    """Mutable producer objects cannot silently relabel the admitted limitation."""
    config, _output = _configuration(tmp_path, None)
    admission, _audit, _payload = _admitted(tmp_path, config)
    records = selected_qualifications(admission, [])
    next(iter(admission.source_qualifications.values()))["summary"]["association_coverage_complete"] = True
    assert records[0]["summary"]["association_coverage_complete"] is False
