"""Restore native source observations without lexical identity or collapsed context (#1316)."""

import csv
import hashlib
import io
import json
import tarfile
from collections import Counter
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.gold import taxon_dispositions as policy
from kg_microbe.transform_utils.gold.fold_restoration import AUDIT_FILE, AUDIT_HEADER
from kg_microbe.transform_utils.gold.gold import GOLDTransform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from tests.test_gold_taxon_dispositions import _read, _report, _write

FIXTURE = Path(__file__).parent / "resources/gold_taxonomy/fold_native_contexts.json"


@pytest.fixture
def restored(tmp_path, monkeypatch):
    """Read six complete real source contexts, not invented strain or identity evidence."""
    evidence = json.loads(FIXTURE.read_text())
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    _write(
        raw / "gold/GOLD_nodes.tsv",
        evidence["node_header"],
        (item["row"] for item in evidence["native_declarations"].values()),
    )
    _write(
        raw / "gold/GOLD_edges.tsv",
        evidence["edge_header"],
        (
            item["row"]
            for item in evidence["native_incident_assertions"] + evidence["complete_ecosystem_parent_assertions"]
        ),
    )
    _write(
        output / "ontologies/ncbitaxon_nodes.tsv",
        evidence["selected_ncbi_header"],
        (item["row"] for item in evidence["selected_ncbi_declarations"].values()),
    )
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        literal = "".join(item["literal"] for item in evidence["native_taxdump_remaps"]).encode()
        member = tarfile.TarInfo("merged.dmp")
        member.size = len(literal)
        archive.addfile(member, io.BytesIO(literal))
    monkeypatch.setenv("GOLD_APPLY_TAXON_TRIM", "true")
    result = GOLDTransform(raw, output)
    result.run()
    return result


def test_complete_native_incidents_and_literal_source_declarations_are_conserved(restored):
    """All six source records retain literal names/xrefs plus full original claim context."""
    native = json.loads(FIXTURE.read_text())
    nodes = {row["id"]: row for row in _read(restored.output_node_file)}
    audit = {row["id"]: row for row in _read(restored.output_dir / AUDIT_FILE)}
    assert set(audit) == set(native["selected_source_ids"])
    assert all(nodes[identifier]["category"] == "biolink:NamedThing" for identifier in audit)
    for identifier, row in audit.items():
        declaration = native["native_declarations"][identifier]["row"]
        for field in ("name", "xref", "provided_by"):
            assert nodes[identifier][field] == declaration[field]
        assert json.loads(row["native_node_json"])["row"] == declaration
        actual = Counter(policy._json(item["row"]) for item in json.loads(row["native_incident_assertions_json"]))
        expected = Counter(
            policy._json(item["row"])
            for item in native["native_incident_assertions"]
            if identifier in (item["row"]["subject"], item["row"]["object"])
        )
        assert actual == expected
        context = json.loads(row["native_context_declarations_json"])
        assert all(item["row"] == native["native_declarations"][key]["row"] for key, item in context.items())
    contract = restored.producer_native_inputs[policy.CONTRACT_KEY]
    assert contract["historical_fold_count"] == contract["retained_count"] == 6
    assert contract["folded_count"] == 0
    assert (restored.output_dir / "organism_folds.tsv").read_text() == "original_id\tcanonical_id\n"


def test_duplicate_historical_taxon_environments_keep_both_original_source_observations(restored):
    """Two native records at one site no longer collapse to one taxon-level observation."""
    rows = _read(restored.output_edge_file)
    selected = [
        row
        for row in rows
        if row["subject"] in {"gold:Go0460627", "gold:Go0460628"} and row["predicate"] == "biolink:located_in"
    ]
    assert len(selected) == 2
    assert {row["object"] for row in selected} == {"gold.ecosystem:3496"}
    assert {row["original_object"] for row in selected} == {"gold.ecosystem:4212"}
    assert not any(row["subject"] == "NCBITaxon:282217" and row["predicate"] == "biolink:located_in" for row in rows)
    audit = _read(restored.output_dir / AUDIT_FILE)
    historical = [
        claim
        for item in audit
        if item["id"] in {"gold:Go0460627", "gold:Go0460628"}
        for claim in json.loads(item["historical_emitted_claims_json"])
    ]
    assert len(historical) == 2
    assert len({policy._json(row) for row in historical}) == 1


def test_native_taxid_remap_and_unchanged_exclusions_are_audited(restored):
    """Root-only habitat and Study exclusions remain explicit; a retired taxid is not a record alias."""
    audit = {row["id"]: row for row in _read(restored.output_dir / AUDIT_FILE)}
    remapped = audit["gold:Go0568577"]
    assert remapped["historical_fold_target"] == "NCBITaxon:767427"
    assert json.loads(remapped["native_node_json"])["row"]["xref"] == "NCBITaxon:2777964"
    emitted = json.loads(remapped["restored_emitted_claims_json"])
    assert len(emitted) == 1
    assert (emitted[0]["subject"], emitted[0]["predicate"], emitted[0]["object"]) == (
        "gold:Go0568577",
        "biolink:related_to",
        "NCBITaxon:767427",
    )
    reasons = Counter(
        item["disposition"] for row in audit.values() for item in json.loads(row["claim_dispositions_json"])
    )
    assert reasons == {
        "restore_source_taxon_association_without_identity": 6,
        "restore_record_owned_observation": 4,
        "unchanged_root_only_environment_exclusion": 1,
        "unchanged_excluded_sample_study_or_trim_context": 5,
    }
    assert all(not row["id"].startswith("gold:Gs") for row in _read(restored.output_node_file))


def _mutate_native_cache(index, mutation):
    """Change only a parsed cache, leaving all original native fixture bytes intact."""
    scope = index.restorations
    if mutation == "clear":
        index.historical_folds.clear()
    elif mutation == "partial":
        index.historical_folds.pop(next(iter(index.historical_folds)))
    elif mutation == "rebind":
        index.historical_folds = dict(index.historical_folds)
    elif mutation == "swap_targets":
        left, right = next(
            (left, right)
            for left in index.historical_folds
            for right in index.historical_folds
            if index.historical_folds[left] != index.historical_folds[right]
        )
        index.historical_folds[left], index.historical_folds[right] = (
            index.historical_folds[right],
            index.historical_folds[left],
        )
    elif mutation == "context":
        scope.hierarchy.clear()
    else:
        scope.db.execute("DELETE FROM fold_incidents WHERE rowid=(SELECT min(rowid) FROM fold_incidents)")


@pytest.mark.parametrize("mutation", ["clear", "partial", "rebind", "swap_targets", "context", "native_table"])
@pytest.mark.parametrize("phase", ["before_completion", "late_publication"])
def test_parsed_native_restoration_cache_cannot_erase_or_change_evidence(restored, monkeypatch, mutation, phase):
    """Original linkage, full targets and complete native contexts remain required at both boundaries (#1337)."""
    if phase == "before_completion":
        original = restored._write_nodes

        def mutate_after_emission(*args):
            """Corrupt the parsed restoration evidence after ordinary emission."""
            original(*args)
            _mutate_native_cache(restored._taxon_dispositions.index, mutation)

        monkeypatch.setattr(restored, "_write_nodes", mutate_after_emission)
        with pytest.raises(SourceFinalizationRequired, match="restoration native"):
            restored.run()
    else:
        _mutate_native_cache(restored._taxon_dispositions.index, mutation)
        with pytest.raises(SourceFinalizationRequired, match="restoration native"):
            restored.verify_consumed_inputs()


def test_detected_native_restoration_drift_remains_failed_after_cache_repair(restored):
    """A caller cannot clear a detected refusal by restoring the same mutable mapping."""
    index = restored._taxon_dispositions.index
    original = dict(index.historical_folds)
    index.historical_folds.clear()
    with pytest.raises(SourceFinalizationRequired):
        restored.verify_consumed_inputs()
    index.historical_folds.update(original)
    with pytest.raises(SourceFinalizationRequired, match="previously changed"):
        restored.verify_consumed_inputs()


@pytest.mark.parametrize(
    "change", ["remove_observation", "repoint_taxon", "extra_observation", "duplicate_observation"]
)
def test_emitter_cannot_drop_redirect_or_invent_restored_observations(restored, change):
    """Native reconstruction checks actual rows, not only aggregate counts or self-stamped receipts."""
    rows = _read(restored.output_edge_file)
    selected = next(
        row for row in rows if row["subject"] == "gold:Go0460627" and row["predicate"] == "biolink:located_in"
    )
    if change == "remove_observation":
        rows.remove(selected)
    elif change == "repoint_taxon":
        selected["subject"] = "NCBITaxon:282217"
    elif change == "extra_observation":
        rows.append({**selected, "object": "gold.ecosystem:1"})
    else:
        rows.append(dict(selected))
    _write(restored.output_edge_file, list(rows[0]), rows)
    with pytest.raises(SourceFinalizationRequired):
        restored._taxon_dispositions.index.restorations.verify_graph(restored.output_edge_file, quoting=csv.QUOTE_NONE)


@pytest.mark.parametrize("change", ["missing", "omission_restamped", "claim_restamped", "contract_removed"])
def test_restoration_audit_is_mandatory_and_independently_rejoined(restored, change):
    """A new digest cannot bless omitted or changed native context, even when the graph is unchanged."""
    report = _report(restored)
    path = restored.output_dir / AUDIT_FILE
    if change == "missing":
        path.unlink()
    elif change == "contract_removed":
        report["producer_native_inputs"][policy.CONTRACT_KEY].pop("lexical_fold_restorations")
    else:
        rows = _read(path)
        if change == "omission_restamped":
            rows.pop()
        else:
            rows[0]["native_incident_assertions_json"] = "[]"
        _write(path, AUDIT_HEADER, rows)
        identity = SourceAdmission().capture(path)
        report["audit_members"][AUDIT_FILE] = report["producer_audit_members"][AUDIT_FILE] = identity
        contract = report["producer_native_inputs"][policy.CONTRACT_KEY]["lexical_fold_restorations"]
        contract.update(
            audit=identity,
            count=len(rows),
            cohort_sha256=hashlib.sha256("".join(policy._json(row) + "\n" for row in rows).encode()).hexdigest(),
        )
    with pytest.raises((SourceFinalizationRequired, FileNotFoundError)):
        policy.verify_recorded_taxon_inputs(report, restored.output_dir / "source_finalization.json")


def test_actual_finalization_repeat_and_recorded_admission_preserve_record_level_observations(restored):
    """Canonicalization/admission verify the native restoration, without post-merge rewriting."""
    restored.finalize(fresh_run=True)
    before = {
        name: hashlib.sha256((restored.output_dir / name).read_bytes()).hexdigest()
        for name in ("nodes.tsv", "edges.tsv", AUDIT_FILE)
    }
    GOLDTransform(restored.input_base_dir, restored.output_base_dir).finalize()
    verify_finalized_source_files([restored.output_node_file, restored.output_edge_file])
    assert before == {name: hashlib.sha256((restored.output_dir / name).read_bytes()).hexdigest() for name in before}
