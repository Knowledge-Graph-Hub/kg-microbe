"""Reviewer calibration must remove false positives without hiding routing bugs (#1072)."""

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_skill(name):
    """Load one standalone reviewer without invoking its CLI or writing artifacts."""
    filename = name.replace("-", "_")
    path = REPO_ROOT / ".claude" / "skills" / name / f"{filename}.py"
    module_name = f"test_reviewer_{filename}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def model_reviewer():
    """Use the pinned hermetic Biolink fixture from conftest."""
    return _load_skill("kg-model-review")


def test_prefixes_union_local_registries_and_keep_unknown_visible(model_reviewer, monkeypatch, tmp_path):
    """A map-only prefix is valid; accepting it must not accept arbitrary prefixes."""
    custom = tmp_path / "custom.yaml"
    custom.write_text("custom: {}\ngold: {}\n", encoding="utf-8")
    prefixmap = tmp_path / "prefixmap.json"
    prefixmap.write_text(json.dumps({"time": "http://www.w3.org/2006/time#"}), encoding="utf-8")
    monkeypatch.setattr(model_reviewer, "CUSTOM_CURIES_FILE", custom)
    monkeypatch.setattr(model_reviewer, "PREFIXMAP_FILE", prefixmap, raising=False)
    prefixes = model_reviewer.load_registered_prefixes()
    assert {"custom", "gold", "time", "NCBITaxon"} <= prefixes
    assert "NOT_REGISTERED" not in prefixes
    rows = [
        {"id": "time:Instant", "category": "biolink:NamedThing", "name": "instant"},
        {"id": "NOT_REGISTERED:1", "category": "biolink:NamedThing", "name": "unknown"},
    ]
    findings = model_reviewer.check_nodes_rows(rows, len(rows), prefixes, set(), True)
    warnings = [finding for finding in findings if finding.check == "Prefix" and finding.severity == "WARNING"]
    assert len(warnings) == 1
    assert "NOT_REGISTERED" in str(warnings[0])
    assert "time" not in str(warnings[0])


def test_real_registry_accepts_time_and_gold_but_not_legacy_gold(model_reviewer):
    """The checked-in registrations track the unified namespace, not its obsolete alias (#1065)."""
    prefixes = model_reviewer.load_registered_prefixes()
    assert {"time", "gold", "gold.ecosystem"} <= prefixes
    assert "GOLD" not in prefixes
    rows = [{"id": "GOLD:Gp000001", "category": "biolink:NamedThing", "name": "legacy"}]
    findings = model_reviewer.check_nodes_rows(rows, 1, prefixes, set(), True)
    assert any(finding.check == "Prefix" and finding.severity == "WARNING" for finding in findings)


@pytest.fixture
def path_reviewer():
    """Load the path reviewer with no graph data or network dependencies."""
    return _load_skill("kg-path-review")


def _family_report(module, monkeypatch, rows, predicates=None):
    """Exercise the actual archetype using tiny in-memory edge streams."""
    monkeypatch.setattr(module, "iter_edges", lambda transform: iter(rows))
    args = argparse.Namespace(transform=["archive-fixture"], predicate=predicates)
    return module.archetype_family_mismatch(args)


def test_pato_quality_decomposition_is_explicit_info(path_reviewer, monkeypatch):
    """Nine exact archived upstream axioms are not established substrate-routing defects."""
    with (REPO_ROOT / "tests/resources/reviewer_pato_partonomy.tsv").open(encoding="utf-8") as stream:
        reader = csv.reader(stream, delimiter="\t")
        next(reader)
        rows = list(reader)
    report = _family_report(path_reviewer, monkeypatch, rows)
    assert report.stats["edges_scanned"] == 9
    assert report.stats["flagged"] == 0
    assert report.stats["quality_partonomy_candidates"] == 9
    assert len(report.findings) == 9
    assert all(finding.severity == "INFO" for finding in report.findings)
    assert all("candidate" in finding.detail and "BFO:0000051" in finding.evidence for finding in report.findings)


@pytest.mark.parametrize(
    "subject,predicate,obj,relation",
    [
        ("PATO:0000383", "biolink:location_of", "NCBITaxon:562", "RO:0001015"),
        ("PATO:0001596", "biolink:location_of", "PATO:0000133", "RO:0001015"),
        ("PATO:0001652", "biolink:has_part", "NCBITaxon:562", "BFO:0000051"),
        ("PATO:0001652", "biolink:has_part", "CHEBI:15377", "BFO:0000051"),
        ("UO:0000001", "biolink:has_part", "UO:0000002", "BFO:0000051"),
        ("METPO:1000001", "biolink:has_part", "METPO:1000002", "BFO:0000051"),
        ("PATO:0001652", "biolink:has_part", "PATO:0000133", "RO:0001015"),
        ("PATO:0001652", "biolink:has_part", "PATO:0000133", ""),
        ("PATO:0001652", "biolink:has_part", "PATO:0001652", "BFO:0000051"),
    ],
)
def test_family_misroutes_and_self_loops_remain_critical(path_reviewer, monkeypatch, subject, predicate, obj, relation):
    """Neither a whole-ontology exemption nor blanket has_part suppression is allowed."""
    report = _family_report(path_reviewer, monkeypatch, [[subject, predicate, obj, relation]])
    assert report.stats["flagged"] == 1
    assert len(report.findings) == 1
    assert report.findings[0].severity == "CRITICAL"


def test_quality_candidate_does_not_hide_neighboring_routing_error(path_reviewer, monkeypatch):
    """Separate counters and evidence preserve the actual critical edge in mixed input."""
    rows = [
        ["PATO:0001652", "biolink:has_part", "PATO:0000133", "BFO:0000051"],
        ["PATO:0000383", "biolink:location_of", "NCBITaxon:562", "RO:0001015"],
    ]
    report = _family_report(path_reviewer, monkeypatch, rows)
    assert report.stats["flagged"] == 1
    assert report.stats["quality_partonomy_candidates"] == 1
    assert sorted(finding.severity for finding in report.findings) == ["CRITICAL", "INFO"]
    filtered = _family_report(path_reviewer, monkeypatch, rows, ["biolink:location_of"])
    assert filtered.stats["flagged"] == 1
    assert filtered.stats["quality_partonomy_candidates"] == 0
