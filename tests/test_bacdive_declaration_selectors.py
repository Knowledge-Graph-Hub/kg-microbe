"""Actual producer selectors, not mutable receipts, choose original declaration evidence (#1709)."""

import csv
import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import bacdive as bacdive_module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.bacdive.source_declaration_evidence import (
    ALIASES_ROLE,
    CUSTOM_ROLE,
    METPO_ROLE,
    SELECTED_ROLE,
    producer_input_path,
)
from kg_microbe.utils import mapping_file_utils
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    graph_rows,
    verify_finalized_source_files,
)
from tests.test_bacdive_taxonomy_evidence import _restamp_retirement_authority, produce, retired_producer
from tests.test_external_node_closure import _taxdump


def _select_alternative(monkeypatch, role, substitute):
    """Change the actual configured producer selector without changing any authority bytes."""
    if role == SELECTED_ROLE:
        monkeypatch.setattr(bacdive_module, "NCBITAXON_NODES_FILE", substitute)
    elif role == CUSTOM_ROLE:
        monkeypatch.setattr(bacdive_module, "CUSTOM_CURIES_YAML_FILE", substitute)
    elif role == METPO_ROLE:
        monkeypatch.setenv("KG_MICROBE_METPO_TEMPLATE_DIR", str(substitute.parent))
    else:
        assert role == ALIASES_ROLE
        monkeypatch.setattr(mapping_file_utils, "LOCAL_METPO_ALIAS_OVERRIDES_PATH", substitute)


def _identical_selector_alternative(tmp_path, role):
    """Prepare a distinct lexical selection whose bytes equal the actual selected input."""
    actual = producer_input_path(role)
    if role == METPO_ROLE:
        substitute = tmp_path / "different-template-selection" / actual.name
        substitute.parent.mkdir()
    else:
        substitute = tmp_path / ("different-selection" + actual.suffix)
    substitute.write_bytes(actual.read_bytes())
    return substitute


def _selector_capture_timing(monkeypatch, role, timing, change):
    """Inject only a real configuration change at the first selected resolver capture, retaining verification."""
    original = SourceAdmission.capture_resolution
    observations = {"captures": 0, "changes": 0}

    def capture(admission, resolver, *args):
        """Run the real capture and resolver; never replace their selected value or skip later admission checks."""
        selected = (
            getattr(resolver, "__qualname__", "") == "SourceDeclarationEvidence._bind_selector.<locals>.<lambda>"
            and inspect.getclosurevars(resolver).nonlocals.get("role") == role
        )
        first = selected and observations["captures"] == 0
        if selected:
            observations["captures"] += 1
        if first and timing == "before-capture":
            change()
            observations["changes"] += 1
        result = original(admission, resolver, *args)
        if first and timing == "after-capture":
            change()
            observations["changes"] += 1
        return result

    monkeypatch.setattr(SourceAdmission, "capture_resolution", capture)
    return observations


def _keyword_source(tmp_path, monkeypatch, *, matched=False):
    """Run a real producer with an actual native keyword, matched only when its real custom input permits it."""
    record = {
        "General": {
            "BacDive-ID": 31,
            "NCBI tax id": {"NCBI tax id": 10},
            "keywords": ["fixture_keyword" if matched else "unmapped_native_tag"],
        },
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    source, _, _, _ = produce(
        tmp_path, monkeypatch, [record], gss=False, retired_fixture=True, forbid_ancestry_selection=True
    )
    assert any(row["id"] == "NCBITaxon:10" for row in graph_rows(source.output_node_file)) == matched
    return source


def _unchanged_native_and_graph(source, *, include_audit=False):
    """Retain original native input and graph bytes, excluding the deliberately restamped retirement authority."""
    paths = [
        Path(source.input_base_dir) / "bacdive_strains.json",
        source.output_node_file,
        source.output_edge_file,
        *(producer_input_path(role) for role in (SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE)),
    ]
    if include_audit:
        paths.append(source.output_dir / "source_reference_resolution.tsv")
    return {Path(path): Path(path).read_bytes() for path in paths if Path(path).is_file()}


def _forged_nonprok_original(source):
    """Change only the synthetic retirement authority and mutable original-node audit claim."""
    _taxdump(Path(source.input_base_dir), nodes="1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 1 | species |\n")
    rows = list(graph_rows(source.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    for row in rows:
        if row["original_id"] == "NCBITaxon:10":
            assert not row["original_node_json"]
            row["original_node_json"] = json.dumps({"id": "NCBITaxon:10", "category": "biolink:OrganismTaxon"})
    return rows


def _substitute_receipt_input(report, role, substitute):
    """Coherently restamp the untrusted proof, consumed role and outer input identity for a different locator."""
    proof = report["producer_native_inputs"]["taxonomy"]["source_declarations"]
    if substitute.exists():
        identity = {"bytes": substitute.stat().st_size, "sha256": hashlib.sha256(substitute.read_bytes()).hexdigest()}
        consumed = {"path": str(substitute.resolve()), "sha256": identity["sha256"]}
        report["consumed_inputs"][role] = consumed
        report["inputs"].append(consumed)
    else:
        identity, consumed = None, None
        report["consumed_inputs"].pop(role, None)
    entry = {"locator": str(substitute.absolute()), "identity": identity, "role": consumed}
    if role == SELECTED_ROLE:
        proof["selected_input"] = entry
    else:
        proof["keyword_inputs"][role] = entry


@pytest.mark.parametrize("replacement", ["missing", "header-only", "same-bytes", "same-target-alias"])
def test_public_rejects_never_selected_taxonomy_locator(tmp_path, monkeypatch, local_source_schema, replacement):
    """A false absence or another lexical locator cannot invent the producer's mandatory stub."""
    identical = replacement in {"same-bytes", "same-target-alias"}
    source = (
        _keyword_source(tmp_path, monkeypatch, matched=True)
        if identical
        else retired_producer(tmp_path, monkeypatch, declare_retired=False)
    )
    report = source.finalize()
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    unchanged = _unchanged_native_and_graph(source, include_audit=identical)
    actual = producer_input_path(SELECTED_ROLE)
    substitute = tmp_path / "never-selected.tsv"
    if replacement == "header-only":
        substitute.write_text("id\tcategory\tname\n")
    elif replacement == "same-bytes":
        substitute.write_bytes(actual.read_bytes())
    elif replacement == "same-target-alias":
        substitute.symlink_to(actual)
    proof = report["producer_native_inputs"]["taxonomy"]["source_declarations"]
    if replacement in {"missing", "header-only"}:
        proof["selected_rows"] = []
    _substitute_receipt_input(report, SELECTED_ROLE, substitute)
    if identical:
        (source.output_dir / "source_finalization.json").write_text(json.dumps(report))
    else:
        _restamp_retirement_authority(source, report, audit_rows=_forged_nonprok_original(source))
    with pytest.raises(SourceFinalizationRequired, match="locator differs from actual producer selector"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert {path: path.read_bytes() for path in unchanged} == unchanged


@pytest.mark.parametrize("role", [CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE])
@pytest.mark.parametrize("replacement", ["invented-key", "same-bytes", "same-target-alias"])
def test_public_rejects_never_selected_keyword_locator(tmp_path, monkeypatch, local_source_schema, role, replacement):
    """New keyword emission cannot be proved by replacing any actual custom/class/alias input selector."""
    identical = replacement in {"same-bytes", "same-target-alias"}
    source = _keyword_source(tmp_path, monkeypatch, matched=identical)
    report = source.finalize()
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    proof = report["producer_native_inputs"]["taxonomy"]["source_declarations"]
    assert bool(proof["native_emissions"]) == identical
    unchanged = _unchanged_native_and_graph(source, include_audit=identical)
    actual = producer_input_path(role)
    substitute = tmp_path / ("never-selected.yaml" if role == CUSTOM_ROLE else "never-selected.tsv")
    if replacement == "same-target-alias":
        substitute.symlink_to(actual)
    elif replacement == "same-bytes":
        substitute.write_bytes(actual.read_bytes())
    elif role == CUSTOM_ROLE:
        custom = yaml.safe_load(actual.read_text())
        custom["injected"] = {
            "unmapped_native_tag": {
                "curie": "METPO:1000698",
                "category": "biolink:PhenotypicQuality",
                "predicate": "biolink:has_phenotype",
                "name": "Invented mapping",
            }
        }
        substitute.write_text(yaml.safe_dump(custom))
    else:
        with actual.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields, rows = reader.fieldnames, list(reader)
        if role == METPO_ROLE:
            next(row for row in rows if row["ID"] == "METPO:1000698")["bacdive keyword synonym"] = "unmapped_native_tag"
        else:
            rows.append(
                {
                    "subject_label": "unmapped_native_tag",
                    "subject_label_normalized": "unmapped_native_tag",
                    "object_id": "METPO:1000698",
                    "object_label": "Invented mapping",
                    "confidence": "high",
                    "mapping_justification": "semapv:ManualMappingCuration",
                }
            )
        with substitute.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    if replacement == "invented-key":
        proof["native_emissions"] = [
            {"ordinal": 0, "target": "NCBITaxon:10", "medium": False, "keywords": ["unmapped_native_tag"]}
        ]
    _substitute_receipt_input(report, role, substitute)
    if identical:
        (source.output_dir / "source_finalization.json").write_text(json.dumps(report))
    else:
        _restamp_retirement_authority(source, report, audit_rows=_forged_nonprok_original(source))
    with pytest.raises(SourceFinalizationRequired, match="locator differs from actual producer selector"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert {path: path.read_bytes() for path in unchanged} == unchanged


@pytest.mark.parametrize("role", [SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE])
@pytest.mark.parametrize("checkpoint", ["before-finalization", "before-public-admission", "after-public-admission"])
def test_actual_input_selector_stays_bound(tmp_path, monkeypatch, local_source_schema, role, checkpoint):
    """Identical bytes at another configured selector do not satisfy the original live or public admission."""
    source = _keyword_source(tmp_path, monkeypatch)
    if checkpoint != "before-finalization":
        report = source.finalize()
    if checkpoint == "after-public-admission":
        guard = BacDiveTransform.verify_recorded_native_inputs(
            report, source.output_dir / "source_finalization.json", admission=SourceAdmission()
        )
    substitute = _identical_selector_alternative(tmp_path, role)
    _select_alternative(monkeypatch, role, substitute)
    error = (
        "locator differs from actual producer selector"
        if checkpoint == "before-public-admission"
        else "input resolution changed"
    )
    with pytest.raises(SourceFinalizationRequired, match=error):
        if checkpoint == "before-public-admission":
            verify_finalized_source_files([source.output_node_file, source.output_edge_file])
        elif checkpoint == "after-public-admission":
            guard.verify()
        else:
            source.finalize()


@pytest.mark.parametrize("role", [SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE])
@pytest.mark.parametrize("timing", ["unchanged", "before-call", "before-capture", "after-capture"])
def test_public_admission_binds_initial_selector_observation(tmp_path, monkeypatch, local_source_schema, role, timing):
    """A selector change cannot become a new capture baseline while public admission reads its old selection."""
    source = _keyword_source(tmp_path, monkeypatch, matched=True)
    source.finalize()
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    actual = producer_input_path(role)
    substitute = _identical_selector_alternative(tmp_path, role)
    unchanged = _unchanged_native_and_graph(source, include_audit=True)
    for path in (
        Path(source.input_base_dir) / "taxdump.tar.gz",
        source.output_dir / "source_finalization.json",
        substitute,
    ):
        unchanged[path] = path.read_bytes()

    def change():
        """Change only the genuine selector; graph, receipt, native inputs and alternative bytes stay fixed."""
        _select_alternative(monkeypatch, role, substitute)

    observations = _selector_capture_timing(monkeypatch, role, timing, change)
    if timing == "before-call":
        change()
    if timing == "unchanged":
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    else:
        with pytest.raises(SourceFinalizationRequired):
            verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert observations["captures"] >= 1
    assert observations["changes"] == int(timing in {"before-capture", "after-capture"})
    assert producer_input_path(role) == (actual if timing == "unchanged" else substitute)
    assert {path: path.read_bytes() for path in unchanged} == unchanged


@pytest.mark.parametrize("role", [SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE])
def test_live_source_rejects_selector_change_at_initial_capture(tmp_path, monkeypatch, role):
    """The real producer fails its initial declaration proof before a finalized receipt can be published."""
    unchanged = {}

    def change():
        """Wait for native fixture selection, then change only one actual selector at initial proof capture."""
        for selected_role in (SELECTED_ROLE, CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE):
            path = producer_input_path(selected_role)
            unchanged[path] = path.read_bytes()
        raw = tmp_path / "raw" / "bacdive_strains.json"
        unchanged[raw] = raw.read_bytes()
        substitute = _identical_selector_alternative(tmp_path, role)
        unchanged[substitute] = substitute.read_bytes()
        _select_alternative(monkeypatch, role, substitute)

    observations = _selector_capture_timing(monkeypatch, role, "before-capture", change)
    with pytest.raises(SourceFinalizationRequired):
        _keyword_source(tmp_path, monkeypatch, matched=True)
    assert observations == {"captures": 1, "changes": 1}
    assert {path: path.read_bytes() for path in unchanged} == unchanged
    assert not list(tmp_path.rglob("source_finalization.json"))


def test_original_keyword_selectors_reject_forged_declaration(tmp_path, monkeypatch, local_source_schema):
    """An unmatched native keyword with the genuine original selectors does not prove a declaration."""
    source = _keyword_source(tmp_path, monkeypatch)
    report = source.finalize()
    assert report["producer_native_inputs"]["taxonomy"]["source_declarations"]["native_emissions"] == []
    _restamp_retirement_authority(source, report, audit_rows=_forged_nonprok_original(source))
    with pytest.raises(SourceFinalizationRequired, match="does not prove the finalized taxonomy replacement"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])


@pytest.mark.parametrize("absent_role", [SELECTED_ROLE, ALIASES_ROLE])
def test_actual_configured_absence_remains_valid(tmp_path, monkeypatch, local_source_schema, absent_role):
    """An actual absent selector is supported; it is different from inventing absence in a receipt."""
    record = {
        "General": {"BacDive-ID": 31, "NCBI tax id": {"NCBI tax id": 10}, "keywords": ["fixture_keyword"]},
        "External links": {"culture collection no.": "TEST RETIRED"},
    }
    absent = tmp_path / "actual-configured-absent.tsv"

    def context(source):
        """Bind the same genuine configured absence in real producer input selection and evidence."""
        if absent_role == SELECTED_ROLE:
            monkeypatch.setattr(bacdive_module, "NCBITAXON_NODES_FILE", absent)
            source.ncbitaxon_labels = {}
        else:
            monkeypatch.setattr(mapping_file_utils, "LOCAL_METPO_ALIAS_OVERRIDES_PATH", absent)

    source, _, _, _ = produce(
        tmp_path, monkeypatch, [record], gss=False, retired_fixture=True, declaration_context=context
    )
    _taxdump(Path(source.input_base_dir), merged="10 | 20 |\n")
    report = source.finalize()
    proof = report["producer_native_inputs"]["taxonomy"]["source_declarations"]
    selected = proof["selected_input"] if absent_role == SELECTED_ROLE else proof["keyword_inputs"][ALIASES_ROLE]
    assert selected == {"locator": str(absent), "identity": None, "role": None}
    assert absent_role not in report["consumed_inputs"]
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert source.finalize() == report
