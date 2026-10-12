"""Keep contract layers separate and finite diagnostic dispositions fail-closed."""

import csv
import importlib.util
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.utils.kgm_validation_profile import (
    CONTRACT_VERSION,
    CSV_FIELDS,
    DEFAULT_PROFILE,
    DEFAULT_REFERENCE,
    classify_kgxval_report,
    diagnostic_signature,
    file_identity,
    load_profile,
    load_reference_dispositions,
    validation_contract,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, write_merge_validation_report

RESOURCES = Path(__file__).parent / "resources"
DIAGNOSTICS = RESOURCES / "kgxval_diagnostics_v1.csv"


def _rows():
    with DIAGNOSTICS.open(newline="") as stream:
        return list(csv.DictReader(stream))


def _csv(tmp_path, rows):
    path = tmp_path / "diagnostics.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_contract_version_and_separate_layers():
    """Canonical TSV validation is explicitly not native/scientific/strict conformance."""
    contract = validation_contract()
    assert contract["version"] == CONTRACT_VERSION
    assert set(contract["layers"]) == {
        "source_finalization",
        "source_admission",
        "merge_representation",
        "kgm_model",
        "kgxval",
        "strict_kgx",
        "paths",
        "scientific_disposition",
    }
    assert contract["graph_rewrites"] is False and contract["release_authorized"] is False
    contract["layers"].clear()
    assert len(validation_contract()["layers"]) == 8


def test_complete_registered_reference_is_176_not_412_graph_errors():
    """The finite reviewed cohort retains all literal cells and duplicate occurrence counts."""
    profile = load_profile()
    assert len(profile["index"]) == 176
    assert sum(e["reference_occurrences"] for e in profile["index"].values()) == 412
    groups = Counter(e["disposition"] for e in profile["index"].values())
    assert groups == {
        "native_predicate_project_extension": 70,
        "class_subsumption_row_evidence_required": 14,
        "growth_medium_row_evidence_required": 1,
        "taxon_phenotype_row_evidence_required": 2,
        "chemical_role_row_evidence_required": 1,
        "food_taxon_row_evidence_required": 1,
        "ontology_category_source_review_required": 60,
        "domain_range_source_review_required": 27,
    }
    native = [e for e in profile["index"].values() if e["error"] == "BAD BIOLINK"]
    assert Counter(e["predicate"].split(":")[0] for e in native) == {"METPO": 67, "MICRO": 3}
    for signature, entry in profile["index"].items():
        assert diagnostic_signature(entry["original_diagnostic"]) == signature


def test_tiny_original_diagnostics_all_classified_but_not_accepted():
    """A complete classification preserves all cells and keeps category acceptance open."""
    before = DIAGNOSTICS.read_bytes()
    report = classify_kgxval_report(DIAGNOSTICS, expected_report_sha256=file_identity(DIAGNOSTICS)["sha256"])
    assert report["classification_complete"] is True
    assert report["status"] == "CLASSIFIED_REVIEW_REQUIRED"
    assert report["csv_records"] == report["distinct_diagnostics"] == 5
    assert report["review_required_diagnostics"] == 3
    assert report["reference_evidence_applies"] is False
    assert report["reference_assessment_counts"] == {}
    assert all(d["reference_assessment"] is None for d in report["diagnostics"])
    assert report["unregistered_diagnostics"] == 0
    assert {json.dumps(d["original_diagnostic"], sort_keys=True) for d in report["diagnostics"]} == {
        json.dumps(row, sort_keys=True) for row in _rows()
    }
    assert report["inputs_unchanged"] is True and DIAGNOSTICS.read_bytes() == before
    assert report["strict_conformance"] is report["scientific_acceptance"] is report["release_authorized"] is False
    assert all(d["scientific_acceptance"] is False and d["strict_conformance"] is False for d in report["diagnostics"])


def test_reference_join_retains_all_106_category_dispositions():
    """Complete actual row evidence supports 13 conventions and leaves 93 concrete actions."""
    evidence = load_reference_dispositions()
    assert len(evidence["index"]) == 106
    assert evidence["group_counts"]["documented_row_convention_supported"] == 13
    assert sum(evidence["group_counts"].values()) - 13 == 93
    assert evidence["group_counts"]["generic_ontology_endpoint_typing"] == 59
    assert sum(d["matched_endpoint_sides"] for d in evidence["index"].values()) == 9930163
    assert all(d["remaining_action"] for d in evidence["index"].values())
    assert not any(evidence[key] for key in ("strict_conformance", "scientific_acceptance", "release_authorized"))


@pytest.mark.parametrize("defect", ["drop", "counts", "waive", "epoch", "false-pass", "source"])
def test_reference_evidence_corruption_cannot_be_used(tmp_path, defect):
    """The exact joined cohort cannot silently lose a finding, change epochs or invent support."""
    evidence = json.loads(DEFAULT_REFERENCE.read_text())
    if defect == "drop":
        evidence["diagnostics"].pop()
    elif defect == "counts":
        evidence["diagnostics"][0]["matched_endpoint_sides"] += 1
    elif defect == "waive":
        evidence["scientific_acceptance"] = True
    elif defect == "epoch":
        evidence["reference"]["archive_sha256"] = "0" * 64
    elif defect == "false-pass":
        pending = next(
            d for d in evidence["diagnostics"] if d["existing_row_rule_counts"].get("NO_EXISTING_PRECISE_RULE")
        )
        pending["reference_disposition"] = "documented_row_convention_supported"
    else:
        evidence["diagnostics"][0]["witnesses"][0]["assertion"]["primary_knowledge_source"] = "infores:invented"
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError):
        load_reference_dispositions(path)


@pytest.mark.parametrize("field", CSV_FIELDS)
def test_changing_any_literal_diagnostic_cell_cannot_inherit_disposition(tmp_path, field):
    """IDs, scope and complete valid-category cells all participate in the exact signature."""
    row = _rows()[0]
    row[field] = "BAD SUBJECT" if field == "ERROR" else row[field] + "_new"
    result = classify_kgxval_report(_csv(tmp_path, [row]))
    assert result["status"] == "UNREGISTERED_DIAGNOSTICS"
    assert result["classification_complete"] is False
    assert result["unregistered_diagnostics"] == 1


@pytest.mark.parametrize("predicate", ["METPO:2999999", "MICRO:9999999", "METPO:2000064"])
def test_new_predicate_even_registered_elsewhere_needs_finite_review(tmp_path, predicate):
    """A namespace and even a production mapping are insufficient for this frozen cohort."""
    row = _rows()[0]
    row["PREDICATE"] = predicate
    report = classify_kgxval_report(_csv(tmp_path, [row]))
    assert report["unregistered_diagnostics"] == 1


def test_duplicate_csv_records_are_reported_not_counted_as_graph_edges(tmp_path):
    """All original physical CSV occurrence locators survive grouping."""
    report = classify_kgxval_report(_csv(tmp_path, [_rows()[0]] * 3))
    assert report["csv_records"] == 3 and report["distinct_diagnostics"] == 1
    assert report["diagnostics"][0]["csv_physical_end_lines"] == [2, 3, 4]
    assert report["diagnostics"][0]["csv_records"] == 3
    assert report["status"] == "CLASSIFIED_NATIVE_EXTENSIONS_ONLY"
    assert report["strict_conformance"] is False


def test_exact_reference_cohort_rejects_partial_and_wrong_digest(tmp_path):
    """A subset cannot pose as all 176 reference diagnostics or their original CSV bytes."""
    with pytest.raises(ValueError, match="cohort"):
        classify_kgxval_report(DIAGNOSTICS, require_reference_cohort=True)
    with pytest.raises(ValueError, match="SHA-256"):
        classify_kgxval_report(DIAGNOSTICS, expected_report_sha256="0" * 64)
    complete = []
    for entry in load_profile()["index"].values():
        complete.extend([entry["original_diagnostic"]] * entry["reference_occurrences"])
    with pytest.raises(ValueError, match="CSV bytes"):
        classify_kgxval_report(_csv(tmp_path, complete), require_reference_cohort=True)


@pytest.mark.parametrize("text", ["", ",".join(CSV_FIELDS) + "\n", "ERROR,ERROR\nBAD BIOLINK,BAD BIOLINK\n"])
def test_empty_or_malformed_reports_cannot_claim_completed_review(tmp_path, text):
    """Header-only and duplicated headers are not validator-completion evidence."""
    path = tmp_path / "bad.csv"
    path.write_text(text)
    with pytest.raises(ValueError):
        classify_kgxval_report(path)


@pytest.mark.parametrize("mutation", ["version", "bool_version", "duplicate", "count", "waiver", "cells", "rule"])
def test_profile_drift_and_acceptance_waivers_fail_closed(tmp_path, mutation):
    """Curated entries cannot silently change version, literal cells or acceptance scope."""
    profile = json.loads(DEFAULT_PROFILE.read_text())
    if mutation == "version":
        profile["version"] = 2
    elif mutation == "bool_version":
        profile["version"] = True
    elif mutation == "duplicate":
        profile["diagnostics"].append(profile["diagnostics"][0])
    elif mutation == "count":
        profile["diagnostics"][0]["reference_occurrences"] = -1
    elif mutation == "waiver":
        profile["dispositions"]["class_subsumption_row_evidence_required"]["scientific_acceptance"] = True
    elif mutation == "cells":
        profile["diagnostics"][0]["actual_categories"] = "ontology class"
    else:
        profile["diagnostics"][0]["disposition"] = "native_predicate_project_extension"
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        load_profile(path)


def test_contract_report_is_one_validation_sentinel_and_never_rewrites_tsvs(tmp_path):
    """A native METPO predicate can pass canonical representation, not strict Biolink."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "reference_resolution.tsv"))
    shutil.copyfile(RESOURCES / "validation_contract_nodes.tsv", nodes)
    shutil.copyfile(RESOURCES / "validation_contract_edges.tsv", edges)
    before = nodes.read_bytes(), edges.read_bytes()
    assert write_merge_validation_report(nodes, edges, report) == {"nodes": 2, "edges": 1}
    with report.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert rows == [
        {
            "check": "canonical_representation_and_endpoint_closure_no_semantic_rewrites",
            "status": "pass",
            "nodes": "2",
            "edges": "1",
            "audited_native_nameless_nodes": "0",
        }
    ]
    assert (nodes.read_bytes(), edges.read_bytes()) == before


@pytest.mark.parametrize("mutation", ["endpoint", "relation", "crlf", "legacy_column"])
def test_merge_contract_failure_never_repairs_graph_or_creates_pass(tmp_path, mutation):
    """Canonical closure/schema defects abort without a misleading summary receipt."""
    nodes, edges, report = (tmp_path / name for name in ("nodes.tsv", "edges.tsv", "reference_resolution.tsv"))
    shutil.copyfile(RESOURCES / "validation_contract_nodes.tsv", nodes)
    text = (RESOURCES / "validation_contract_edges.tsv").read_text()
    if mutation == "endpoint":
        text = text.replace("CHEBI:1", "CHEBI:2")
    elif mutation == "relation":
        text = text.replace("RO:0002215", "RO:0002215|RO:0002200")
    elif mutation == "crlf":
        text = text.replace("\n", "\r\n")
    else:
        text = text.replace("agent_type\n", "agent_type\tid\n").replace("manual_agent\n", "manual_agent\tedge:1\n")
    edges.write_bytes(text.encode())
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(SourceFinalizationRequired):
        write_merge_validation_report(nodes, edges, report)
    assert not report.exists()
    assert (nodes.read_bytes(), edges.read_bytes()) == before


def test_cli_writes_only_a_new_report_and_retains_review_required_exit(tmp_path):
    """The standalone tool never replaces its input or reports unresolved cases as green."""
    script = Path(__file__).parents[1] / "scripts" / "classify_kgxval_report.py"
    spec = importlib.util.spec_from_file_location("classification_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "review.json"
    argv = ["--report", str(DIAGNOSTICS), "--output", str(output)]
    assert module.main(argv) == 2
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        module.main(argv)
    assert output.read_bytes() == before
