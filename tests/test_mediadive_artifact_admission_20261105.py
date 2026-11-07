"""Offline archive qualification controls for the bounded MediaDive release gate."""

import copy
import csv
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe.merge_utils import source_freshness
from kg_microbe.merge_utils.artifact_manifest import file_identity, write_graph_archive
from kg_microbe.merge_utils.source_qualifications import package_qualifications
from kg_microbe.transform_utils.mediadive.endpoint_consumer import HEADER
from kg_microbe.transform_utils.mediadive.endpoint_outcomes import BASE_URL, STATES

HELPER_PATH = Path(__file__).parents[1] / "scripts/adhoc/kgm_mediadive_artifact_admission_20261105.py"
SPEC = importlib.util.spec_from_file_location("mediadive_artifact_gate", HELPER_PATH)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def _fixture(tmp_path, monkeypatch, *, dependency=False):
    """Supply explicit synthetic admission while exercising actual archive writing and reading."""
    source = tmp_path / "source"
    source.mkdir()
    selected = tmp_path / "input"
    selected.mkdir()
    output = tmp_path / "published"
    output.mkdir()
    graphs = []
    for name, body in (
        ("nodes", "id\tcategory\nfixture:1\tbiolink:NamedThing\n"),
        ("edges", "subject\tpredicate\tobject\nfixture:1\tbiolink:related_to\tfixture:1\n"),
    ):
        path = selected / f"{name}.tsv"
        path.write_text(body)
        graphs.append(path)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(output)},
                "merged_graph": {
                    "source": {"fixture": {"input": {"format": "tsv", "filename": [str(path) for path in graphs]}}},
                    "destination": {"tsv": {"format": "tsv", "filename": "merged-kg", "compression": "tar.gz"}},
                },
            }
        )
    )
    audit = source / "mediadive_endpoint_outcomes.tsv"
    unknown = []
    with audit.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for number in range(3344):
            for kind in ("medium", "medium-strains"):
                url = BASE_URL + kind + "/" + str(number)
                state = "unknown_unavailable" if kind == "medium-strains" and number < 632 else "nonempty"
                if state == "unknown_unavailable":
                    unknown.append(url)
                writer.writerow(
                    [
                        url,
                        number,
                        state,
                        hashlib.sha256(url.encode()).hexdigest(),
                        "b" * 64,
                        "2026-11-05T00:00:00+00:00",
                    ]
                )
    summary = {
        "schema_version": 1,
        "catalogue_count": 3344,
        "expected_endpoint_count": 6688,
        "association_endpoint_count": 3344,
        "endpoint_accounting_complete": True,
        "recipe_coverage_complete": True,
        "association_coverage_complete": False,
        "policy_applied": True,
        "admissible": True,
        "unknown_endpoints": sorted(unknown),
        "unresolved_endpoints": [],
        "state_counts": {state: {"nonempty": 6056, "unknown_unavailable": 632}.get(state, 0) for state in STATES},
    }
    policy_identity = {"bytes": 100, "sha256": "d" * 64}
    generation = {
        "schema_version": 1,
        "generation_id": "synthetic-fixture",
        "manifest": {"path": "synthetic/manifest.json", "sha256": "e" * 64, "bytes": 300},
        "policy": {"path": "synthetic/unknown-policy.json", **policy_identity},
        "curated_policy": {"path": "synthetic/reviewed-policy.json", **policy_identity},
        "qualification": summary,
    }
    record = {
        "source": "mediadive",
        "graph_paths": [str(source / "nodes.tsv")] if dependency else [str(path) for path in graphs],
        "generation": generation,
        "summary": summary,
        "audit": {
            "name": audit.name,
            "path": str(audit),
            **{key: value for key, value in file_identity(audit).items() if key != "rows"},
        },
    }
    calls = []
    baseline = copy.deepcopy(record)

    def admit(paths, *, admission):
        """Stand in only for prior production source replay, never archive validation."""
        calls.append(list(paths))
        assert list(paths) == graphs
        for path in (*graphs, audit):
            admission.capture(path)
        admission.source_qualifications = {str(source / "source_finalization.json"): copy.deepcopy(baseline)}
        return admission

    monkeypatch.setattr(source_freshness, "verify_source_freshness", admit)
    portable_record = {**record, "participation": "admitted_dependency" if dependency else "graph_input"}
    audit_files, _, qualifications = package_qualifications([portable_record], output, "merged-kg")
    published_graphs = []
    for path in graphs:
        published = output / ("merged-kg_" + path.name)
        published.write_bytes(path.read_bytes())
        published_graphs.append(published)
    provenance = {
        "merge_config": {"name": config.name, "sha256": hashlib.sha256(config.read_bytes()).hexdigest()},
        "source_finalization": {"required": True, "diagnostic_opt_out": False},
        "source_qualifications": qualifications,
    }
    archive = output / "merged-kg.tar.gz"
    files = [*published_graphs, *audit_files]
    write_graph_archive(archive, files, provenance)
    return SimpleNamespace(
        config=config, archive=archive, provenance=provenance, files=files, record=record, audit=audit, calls=calls
    )


@pytest.mark.parametrize("dependency", [False, True])
def test_actual_archive_preserves_exact_admitted_coverage(tmp_path, monkeypatch, dependency):
    """Both participation types keep the exact finite unknown cohort and false completeness."""
    fixture = _fixture(tmp_path, monkeypatch, dependency=dependency)
    result = GATE.verify(fixture.config, fixture.archive)
    assert len(fixture.calls) == 1
    assert result["qualification"]["endpoint_count"] == 6688
    assert result["qualification"]["state_counts"]["unknown_unavailable"] == 632
    assert result["qualification"]["summary"]["association_coverage_complete"] is False
    assert result["qualification"]["participation"] == ("admitted_dependency" if dependency else "graph_input")


@pytest.mark.parametrize(
    "mutation",
    ["generation", "policy", "summary_type", "complete", "counts", "participation", "audit_identity", "diagnostic"],
)
def test_outer_manifest_restamp_cannot_relabel_admitted_evidence(tmp_path, monkeypatch, mutation):
    """A self-consistent archive manifest cannot replace production source admission."""
    fixture = _fixture(tmp_path, monkeypatch)
    item = fixture.provenance["source_qualifications"][0]
    if mutation == "generation":
        item["generation"]["generation_id"] = "other-generation"
    elif mutation == "policy":
        item["generation"]["curated_policy"]["sha256"] = "f" * 64
    elif mutation == "summary_type":
        item["summary"]["endpoint_accounting_complete"] = 1
    elif mutation == "complete":
        item["summary"]["association_coverage_complete"] = True
    elif mutation == "counts":
        item["endpoint_state_counts"]["unknown_unavailable"] = 631
    elif mutation == "participation":
        item["participation"] = "admitted_dependency"
    elif mutation == "audit_identity":
        item["audit"]["sha256"] = "f" * 64
    else:
        fixture.provenance["source_finalization"]["diagnostic_opt_out"] = True
    write_graph_archive(fixture.archive, fixture.files, fixture.provenance)
    with pytest.raises(ValueError):
        GATE.verify(fixture.config, fixture.archive)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "transport", "wrong_id"])
def test_endpoint_inventory_defects_survive_outer_rehash_rejection(tmp_path, monkeypatch, mutation):
    """The verifier reads actual endpoint rows even when the archive is internally rehashed."""
    fixture = _fixture(tmp_path, monkeypatch)
    path = fixture.files[-1]
    lines = path.read_text().splitlines()
    if mutation == "duplicate":
        lines[2] = lines[1]
    elif mutation == "missing":
        lines.pop()
    elif mutation == "transport":
        lines[1] = lines[1].replace("\tnonempty\t", "\ttransport_error\t")
    else:
        columns = lines[1].split("\t")
        columns[1] = "different-id"
        lines[1] = "\t".join(columns)
    path.write_text("\n".join(lines) + "\n")
    fixture.provenance["source_qualifications"][0]["audit"] = {"name": path.name, **file_identity(path)}
    write_graph_archive(fixture.archive, fixture.files, fixture.provenance)
    with pytest.raises(ValueError):
        GATE.verify(fixture.config, fixture.archive)


def test_source_drift_during_archive_scan_is_rejected(tmp_path, monkeypatch):
    """The retained production admission remains live through the complete artifact read."""
    fixture = _fixture(tmp_path, monkeypatch)
    original = GATE.archive_metadata

    def change(*args):
        """Model a source audit changing after successful artifact reads."""
        result = original(*args)
        fixture.audit.write_bytes(fixture.audit.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(GATE, "archive_metadata", change)
    with pytest.raises(ValueError, match="changed"):
        GATE.verify(fixture.config, fixture.archive)
