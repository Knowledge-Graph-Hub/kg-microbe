"""Lossless audit-only observations and locally declared IMG genomes (#1846/#1827)."""

import csv
import io
import json
from collections import Counter

import pytest

from kg_microbe.transform_utils.microbedecoder import bacdive_join_dispositions as joins
from kg_microbe.transform_utils.microbedecoder import observation_audit as audit
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.microbedecoder_join_fixtures import prepare
from tests.test_microbedecoder_bacdive_join_dispositions import _native_report, _rows, _write
from tests.test_microbedecoder_snapshot_subjects import FIXTURE, SELECTED
from tests.test_microbedecoder_transform import _NoChebi


def _run(tmp_path, monkeypatch, mode):
    """Use immutable actual finite rows and real producer/native verification paths."""
    cases = json.loads(FIXTURE.read_text())["cases"]
    selected = tuple(i for i, case in enumerate(cases, 1) if case["md_record"] in SELECTED)
    transform, raw, _, _, _ = prepare(
        tmp_path,
        monkeypatch,
        selected=selected,
        native_cases=cases,
        include_bacdive_snapshot=mode,
    )
    transform.run(raw)
    return transform


def test_default_snapshot_mode_is_audit_only_and_replays_all_native_occurrences(tmp_path, monkeypatch):
    """The default retains all 195 contradicted observations without snapshot graph claims."""
    monkeypatch.delenv("MICROBEDECODER_INCLUDE_BACDIVE_SNAPSHOT", raising=False)
    transform = _run(tmp_path, monkeypatch, None)
    assert transform.include_bacdive_snapshot is False
    edges = _rows(transform.output_edge_file)
    assert not any(row["source_column"].startswith("BacDive_") for row in edges)
    assert not any(row["id"].startswith("kgmicrobe.source_record:") for row in _rows(transform.output_node_file))
    retained = _rows(transform.output_dir / audit.AUDIT_FILE)
    claims = [json.loads(row["original_claim_json"]) for row in retained]
    contradicted = [row for row in claims if row["subject"].startswith("kgmicrobe.source_record:")]
    assert len(contradicted) == 195
    assert {row["knowledge_level"] for row in contradicted} == {"knowledge_assertion"}
    assert {row["predicate"] for row in contradicted} == {"biolink:has_attribute"}
    contract = transform.producer_native_inputs[joins.CONTRACT_KEY]
    assert contract["include_bacdive_snapshot"] is False
    assert contract["snapshot_nodes"] == 0 and contract["audit_only_snapshot_occurrences"] == 195
    transform.verify_native_inputs()
    joins.verify_recorded_inputs(_native_report(transform), transform.output_dir / "source_finalization.json").verify()


def test_explicit_opt_in_retains_exact_original_snapshot_graph_payload(tmp_path, monkeypatch):
    """An explicit opt-in preserves complete snapshot assertions and native refusal rules."""
    off = _run(tmp_path / "off", monkeypatch, False)
    expected = Counter(
        row["original_claim_json"]
        for row in _rows(off.output_dir / audit.AUDIT_FILE)
        if row["disposition"] == audit.SNAPSHOT_AUDIT_ONLY
    )
    on = _run(tmp_path / "on", monkeypatch, True)
    actual = Counter(
        json.dumps(row, sort_keys=True, separators=(",", ":"))
        for row in _rows(on.output_edge_file)
        if row["source_column"].startswith("BacDive_")
    )
    # Producer graph full-row deduplication remains distinct from occurrence-preserving audit.
    assert set(actual) == set(expected)
    assert all(value == 1 for value in actual.values())
    assert on.producer_native_inputs[joins.CONTRACT_KEY]["snapshot_nodes"] == 5
    on.verify_native_inputs()
    joins.verify_recorded_inputs(_native_report(on), on.output_dir / "source_finalization.json").verify()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "source_cell", "value", "predicate"])
def test_observation_tampering_is_refused_by_actual_native_replay(tmp_path, monkeypatch, mutation):
    """Restamping a changed sidecar cannot replace complete native occurrence comparison."""
    transform = _run(tmp_path, monkeypatch, False)
    path = transform.output_dir / audit.AUDIT_FILE
    rows = _rows(path)
    index = next(i for i, row in enumerate(rows) if row["disposition"] == audit.SNAPSHOT_AUDIT_ONLY)
    if mutation == "missing":
        rows.pop(index)
    elif mutation == "duplicate":
        rows.append(dict(rows[index]))
    elif mutation == "source_cell":
        rows[index]["source_cell_json"] = '"invented"'
    else:
        claim = json.loads(rows[index]["original_claim_json"])
        claim[mutation] = "invented"
        rows[index]["original_claim_json"] = json.dumps(claim, sort_keys=True, separators=(",", ":"))
    _write(path, rows, audit.AUDIT_FIELDS)
    with pytest.raises(SourceFinalizationRequired, match="observation audit"):
        joins.verify_recorded_inputs(_native_report(transform), transform.output_dir / "source_finalization.json")


def test_changed_snapshot_selector_is_refused(tmp_path, monkeypatch):
    """A producer cannot change graph mode after its original completed run."""
    transform = _run(tmp_path, monkeypatch, False)
    transform.include_bacdive_snapshot = True
    with pytest.raises(SourceFinalizationRequired, match="snapshot graph mode"):
        transform.verify_native_inputs()


@pytest.mark.parametrize("value", ["maybe", "", "yes"])
def test_invalid_snapshot_environment_is_refused(monkeypatch, tmp_path, value):
    """Unknown option spellings must not silently enable or disable source graph assertions."""
    monkeypatch.setenv("MICROBEDECODER_INCLUDE_BACDIVE_SNAPSHOT", value)
    with pytest.raises(ValueError, match="true/false"):
        MicrobeDecoderTransform(tmp_path, tmp_path, chemical_loader=_NoChebi())


def test_img_endpoints_are_genomes_and_membership_is_not_identity(tmp_path):
    """Every admitted repeated IMG endpoint receives one source-backed Genome declaration."""
    transform = MicrobeDecoderTransform(tmp_path, tmp_path, chemical_loader=_NoChebi())
    nodes, edges = io.StringIO(), io.StringIO()
    transform._source_record = "sha256:fixture#record=1"
    transform._emit_crosswalk_edges(
        "lpsn:1", {"IMG_Genome_ID": "123,456,123"}, csv.writer(nodes, delimiter="\t"), csv.writer(edges, delimiter="\t")
    )
    node_rows = [
        dict(zip(transform.node_header, row, strict=True))
        for row in csv.reader(io.StringIO(nodes.getvalue()), delimiter="\t")
    ]
    edge_rows = [
        dict(zip(transform.edge_header, row, strict=True))
        for row in csv.reader(io.StringIO(edges.getvalue()), delimiter="\t")
    ]
    assert {row["id"] for row in node_rows} == {"IMG:123", "IMG:456"}
    assert len(node_rows) == 2
    assert {row["category"] for row in node_rows} == {"biolink:Genome"}
    assert {row["provided_by"] for row in node_rows} == {"infores:microbedecoder"}
    assert all(row["name"] == "IMG genome " + row["id"].split(":")[1] for row in node_rows)
    assert {row["subject"] for row in edge_rows} <= {row["id"] for row in node_rows}
    assert {(row["predicate"], row["relation"], row["object"]) for row in edge_rows} == {
        ("biolink:in_taxon", "RO:0002162", "lpsn:1")
    }


def test_bergey_placeholders_keep_complete_observation_and_citation_only_in_audit(tmp_path):
    """Other/Not reported remain evidence, without inferred phenotype or negative growth."""
    transform = MicrobeDecoderTransform(tmp_path, tmp_path, chemical_loader=_NoChebi())
    transform._source_record = "sha256:fixture#record=1"
    source = {
        "Bergey_Type_of_metabolism": "Other",
        "Bergey_Substrates_for_end_products": "Not reported",
        "Bergey_Article_link": "https://doi.org/10.1234/example\tquoted",
    }
    nodes, edges, observations = io.StringIO(), io.StringIO(), io.StringIO()
    transform._observation_report_writer = csv.DictWriter(
        observations, fieldnames=audit.AUDIT_FIELDS, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None
    )
    transform._observation_report_writer.writeheader()
    transform._emit_metabolism_edges(
        "lpsn:1", source, csv.writer(nodes, delimiter="\t"), csv.writer(edges, delimiter="\t")
    )
    assert not nodes.getvalue() and not edges.getvalue()
    rows = list(csv.DictReader(io.StringIO(observations.getvalue()), delimiter="\t", quoting=csv.QUOTE_NONE))
    assert len(rows) == 2
    claims = [json.loads(row["original_claim_json"]) for row in rows]
    assert {row["value"] for row in claims} == {"Other", "Not reported"}
    assert all(row["source_record"] == transform._source_record for row in claims)
    assert all(row["source_citation"] == transform._escape_literal(source["Bergey_Article_link"]) for row in claims)
    assert all(row["source_citation_base64"] for row in claims)
    assert [json.loads(row["source_cell_json"]) for row in rows] == ["Other", "Not reported"]


@pytest.mark.parametrize("mutation", ["native", "foreign_column", "changed_target", "inverse", "node_only"])
def test_unselected_snapshot_reinjection_is_refused_with_complete_audit(tmp_path, monkeypatch, mutation):
    """An ordinary native record cannot regain a disabled snapshot through either replay path (#1854)."""
    transform, raw, _, _, _ = prepare(tmp_path, monkeypatch, include_bacdive_snapshot=False)
    transform.run(raw)
    claim = next(
        json.loads(row["original_claim_json"])
        for row in _rows(transform.output_dir / audit.AUDIT_FILE)
        if row["disposition"] == audit.SNAPSHOT_AUDIT_ONLY and row["source_record"].endswith("#record=2")
    )
    assert claim["source_record"] not in transform._bacdive_join_guard.selected
    _assert_additive_audit_only_refusal(transform, claim, mutation)


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("column", tuple(audit.BERGEY_PLACEHOLDERS))
@pytest.mark.parametrize("mutation", ["native", "foreign_column", "changed_target", "node_only"])
def test_bergey_placeholder_reinjection_is_refused_in_either_mode(tmp_path, monkeypatch, mode, column, mutation):
    """Exact missing-report values remain audit-only even with snapshot opt-in and an intact audit."""
    native = {
        "LPSN_ID": "101",
        "BacDive_ID": "",
        "BacDive_Oxygen_tolerance": "aerobic",
        "FAPROTAX_Type_of_metabolism": "chemoheterotrophy",
        "Bergey_Type_of_metabolism": "Other",
        "Bergey_Substrates_for_end_products": "Not reported",
        "Bergey_Article_link": "https://doi.org/10.1234/synthetic",
    }
    transform, raw, _, _, _ = prepare(
        tmp_path, monkeypatch, selected=(), native_cases=[{"native_row": native}], include_bacdive_snapshot=mode
    )
    transform.run(raw)
    claim = next(
        json.loads(row["original_claim_json"])
        for row in _rows(transform.output_dir / audit.AUDIT_FILE)
        if row["source_column"] == column
    )
    _assert_additive_audit_only_refusal(transform, claim, mutation)


def _assert_additive_audit_only_refusal(transform, claim, mutation):
    """Keep every valid edge/audit byte, then test native and detached refusal of one added claim."""
    transform.verify_native_inputs()
    joins.verify_recorded_inputs(_native_report(transform), transform.output_dir / "source_finalization.json").verify()
    before_edges = _rows(transform.output_edge_file)
    before_nodes = transform.output_node_file.read_bytes()
    before_audit = (transform.output_dir / audit.AUDIT_FILE).read_bytes()
    forged = dict(claim)
    target = forged["object"]
    if mutation == "foreign_column":
        forged.update(source_column="foreign_column", value="foreign_value")
    elif mutation == "changed_target":
        forged["object"] = "fixture:foreign_attribute"
    elif mutation == "inverse":
        forged["subject"], forged["object"] = forged["object"], forged["subject"]
        forged.update(source_column="foreign_column", value="foreign_value")
    if mutation != "node_only":
        _write(transform.output_edge_file, [*before_edges, forged], transform.edge_header)
    else:
        # Test declarations separately: a forbidden node must not mask a missing edge guard.
        node = dict.fromkeys(transform.node_header, "")
        node.update(id=target, category="biolink:Attribute", name=claim["value"], provided_by="infores:microbedecoder")
        _write(transform.output_node_file, [*_rows(transform.output_node_file), node], transform.node_header)
    if mutation != "node_only":
        assert transform.output_node_file.read_bytes() == before_nodes
    else:
        assert _rows(transform.output_edge_file) == before_edges
    assert _rows(transform.output_edge_file)[: len(before_edges)] == before_edges
    assert (transform.output_dir / audit.AUDIT_FILE).read_bytes() == before_audit
    # Bind the mutated file bytes in the detached report: refusal must be scientific, not a stale output hash.
    report = _native_report(transform)
    with pytest.raises(SourceFinalizationRequired, match="audit-only observation reintroduced"):
        transform.verify_native_inputs()
    with pytest.raises(SourceFinalizationRequired, match="audit-only observation reintroduced"):
        joins.verify_recorded_inputs(report, transform.output_dir / "source_finalization.json")
