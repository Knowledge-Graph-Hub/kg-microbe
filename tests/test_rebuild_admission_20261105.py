"""Offline acceptance boundaries of the dated rebuild helper."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.artifact_manifest import file_identity, write_graph_archive
from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rebuild_admission", REPO / "scripts/adhoc/kgm_rebuild_admission_20261105.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def _config(tmp_path):
    """Relocate only the canonical paths into a hermetic test checkout."""
    canonical = yaml.safe_load((REPO / "merge.yaml").read_text())
    (tmp_path / "merge.yaml").write_text(yaml.safe_dump(canonical))
    runtime = json.loads(json.dumps(canonical))
    runtime["configuration"]["output_directory"] = str(tmp_path / "data/merged")
    for source in runtime["merged_graph"]["source"].values():
        source["input"]["filename"] = [str(tmp_path / value) for value in source["input"]["filename"]]
    runtime["merged_graph"]["operations"][0]["args"]["filename"] = str(tmp_path / "data/stats.yaml")
    path = tmp_path / "runtime.yaml"
    path.write_text(yaml.safe_dump(runtime))
    return path, runtime


def test_current_planner_preserves_standard_scope(tmp_path, monkeypatch):
    """Use registered dependencies and the canonical config without activating optional graph scope."""
    for name in ("PREGO_SHAPES", "PREGO_MIN_CONFIDENCE", "PREGO_HABITAT_MIN_SCORE", "GOLD_APPLY_TAXON_TRIM"):
        monkeypatch.delenv(name, raising=False)
    config_path, _ = _config(tmp_path)
    plan = helper.build_plan(
        tmp_path, tmp_path / "data/raw", tmp_path / "data/transformed", config_path, tmp_path / "data/merged"
    )
    assert plan["phases"][0] == ["ontologies"]
    assert set(plan["sources"]) == {
        "ontologies",
        "ontologies_stubs",
        "bacdive",
        "gtdb",
        "madin_etal",
        "metatraits",
        "rhea_mappings",
        "prego",
        "lpsn",
        "mediadive",
        "metatraits_gtdb",
        "bactotraits",
        "gold",
        "lpsn_api",
        "microbedecoder",
    }
    assert len(plan["sources"]["ontologies"]) == 28
    assert all("prego_habitat" in name for name in plan["sources"]["prego"])
    phase_of = {source: number for number, phase in enumerate(plan["phases"]) for source in phase}
    assert phase_of["gold"] < phase_of["microbedecoder"]
    assert phase_of["bacdive"] < phase_of["mediadive"]


@pytest.mark.parametrize("damage", ["bypass", "removed_source", "external_input", "prego"])
def test_planner_refuses_scope_and_path_changes(tmp_path, monkeypatch, damage):
    """Path relocation cannot conceal semantic scope changes or original-checkout input reuse."""
    path, config = _config(tmp_path)
    if damage == "bypass":
        config["configuration"]["allow_unfinalized_sources"] = True
    elif damage == "removed_source":
        del config["merged_graph"]["source"]["prego"]
    elif damage == "external_input":
        config["merged_graph"]["source"]["bacdive"]["input"]["filename"][0] = str(
            REPO / "data/transformed/bacdive/nodes.tsv"
        )
    else:
        monkeypatch.setenv("PREGO_SHAPES", "all")
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        helper.build_plan(
            tmp_path, tmp_path / "data/raw", tmp_path / "data/transformed", path, tmp_path / "data/merged"
        )


@pytest.fixture
def ontology_bundle(tmp_path, monkeypatch):
    """Isolate the wrapper's extra whole-source checks from the production gate's own tests."""
    import kg_microbe.merge_utils.source_freshness as freshness

    directory = tmp_path / "transformed/ontologies"
    directory.mkdir(parents=True)
    raw = tmp_path / "raw"
    raw.mkdir()
    paths = []
    for name in helper.ONTOLOGIES:
        for kind in ("nodes", "edges"):
            path = directory / f"{name}_{kind}.tsv"
            path.write_text("id\nfixture:1\n")
            paths.append(path)
    report = {
        "raw_input_directory": str(raw),
        "members": {path.name: file_identity(path) for path in paths},
        "consumed_inputs": {"ncbi_taxonomy_authority": {"path": str(raw / "taxdump.tar.gz"), "sha256": "fixture"}},
        "audit_members": {},
    }
    (directory / "source_finalization.json").write_text(json.dumps(report))
    (directory / "source_fingerprint.json").write_text("{}")
    calls = []

    def gate(selected):
        """Capture exact selected bytes so post-gate mutation remains observable."""
        calls.append(selected)
        admission = SourceAdmission()
        for path in selected:
            admission.capture(path)
        return admission

    monkeypatch.setattr(freshness, "verify_source_freshness", gate)
    plan = {"sources": {"ontologies": [str(path) for path in paths]}, "raw_directory": str(raw)}
    return plan, directory, report, calls


def test_whole_ontology_inventory_passes_through_production_gate(ontology_bundle):
    """The wrapper calls the public gate with every ontology member and rechecks its admission."""
    plan, _, _, calls = ontology_bundle
    result, admission = helper.verify_sources(plan, ["ontologies"])
    assert len(calls) == 1 and len(calls[0]) == 28
    assert len(result["sources"]["ontologies"]["graphs"]) == 28
    assert len(admission.identities) == 30


@pytest.mark.parametrize("damage", ["empty_graph", "missing_authority", "wrong_raw", "missing_member"])
def test_ontology_gate_requires_persisted_complete_current_evidence(ontology_bundle, damage):
    """A successful public admission cannot replace the rebuild's explicit whole-canary inventory."""
    plan, directory, report, _ = ontology_bundle
    if damage == "empty_graph":
        Path(plan["sources"]["ontologies"][0]).write_text("id\n")
    elif damage == "missing_authority":
        report["consumed_inputs"] = {}
    elif damage == "wrong_raw":
        report["raw_input_directory"] = str(directory)
    else:
        report["members"].pop(Path(plan["sources"]["ontologies"][0]).name)
    (directory / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        helper.verify_sources(plan, ["ontologies"])


def test_production_gate_failure_is_not_repaired_or_bypassed(ontology_bundle, monkeypatch):
    """No alternate marker or restamping path can turn production rejection into a pass."""
    import kg_microbe.merge_utils.source_freshness as freshness

    plan, directory, _, _ = ontology_bundle
    before = {path: path.read_bytes() for path in directory.iterdir()}

    def reject(paths):
        """Represent a stale production authority receipt."""
        raise SourceFinalizationRequired("consumed authority changed")

    monkeypatch.setattr(freshness, "verify_source_freshness", reject)
    with pytest.raises(SourceFinalizationRequired, match="consumed authority changed"):
        helper.verify_sources(plan, ["ontologies"])
    assert before == {path: path.read_bytes() for path in directory.iterdir()}


@pytest.fixture
def merged_bundle(tmp_path, monkeypatch):
    """Build a tiny manifest-backed archive using the production packager."""
    import kg_microbe.merge_utils.stats_provenance as provenance
    import kg_microbe.utils.transform_fingerprint as fingerprint

    config_path, config = _config(tmp_path)
    directory = tmp_path / "data/merged"
    directory.mkdir(parents=True)
    nodes, edges, validation = [
        directory / f"merged-kg_{suffix}.tsv" for suffix in ("nodes", "edges", "reference_resolution")
    ]
    nodes.write_text("id\tcategory\nfixture:1\tbiolink:NamedThing\n")
    edges.write_text("subject\tpredicate\tobject\nfixture:1\tbiolink:related_to\tfixture:1\n")
    validation.write_text(
        "check\tstatus\tnodes\tedges\taudited_native_nameless_nodes\ncanonical_representation_and_endpoint_closure_no_semantic_rewrites\tpass\t1\t1\t0\n"
    )
    archive = directory / "merged-kg.tar.gz"
    info = {
        "merge_config": {"name": config_path.name, "sha256": file_identity(config_path)["sha256"]},
        "source_finalization": {"required": True, "diagnostic_opt_out": False},
        "repository_schema": {"version": "fixture"},
        "commit": "fixture",
        "configured_source_markers": {},
    }
    write_graph_archive(archive, [nodes, edges, validation], provenance=info)
    stats_path = Path(config["merged_graph"]["operations"][0]["args"]["filename"])
    stats = {
        "node_stats": {"total_nodes": 1},
        "edge_stats": {"total_edges": 1, "count_by_raw_predicate": {"biolink:related_to": 1}},
        "provenance": {
            "sources": {},
            "commit": "fixture",
            "merge_config": str(config_path),
            "edges_archive": str(archive),
            "edges_archive_member": edges.name,
        },
    }
    stats_path.write_text(yaml.safe_dump(stats))
    (directory / "merged_strain_parent_violations.tsv").write_text(
        "strain_id\tparent_count\tparents\tknowledge_sources\n"
    )
    (directory / "merged_stub_nodes.tsv").write_text("prefix\tcount\texpected\tnote\texamples\n")
    (directory / "merged_stub_node_details.tsv").write_text(
        "id\texpected\tnote\tincident_edges\tpredicates\tknowledge_sources\tdeclared_outside_merge\n"
    )
    monkeypatch.setattr(helper, "verify_sources", lambda *args: ({"sources": {}}, SourceAdmission()))
    monkeypatch.setattr(provenance, "git_commit", lambda *args, **kwargs: "fixture")
    monkeypatch.setattr(provenance, "source_markers", lambda *args: {})
    monkeypatch.setattr(fingerprint, "schema_fingerprint", lambda *args: {"version": "fixture"})
    plan = {"phases": [["ontologies"]], "merged_directory": str(directory)}
    return plan, config_path, directory, stats_path


def test_merge_archive_and_persisted_reports_are_verified(merged_bundle, tmp_path):
    """A complete archive is accepted only alongside current provenance and successful reports."""
    plan, config_path, _, _ = merged_bundle
    result = helper.verify_merge(plan, config_path, tmp_path)
    assert result["archive"]["members"]["merged-kg_edges.tsv"]["rows"] == 1


@pytest.mark.parametrize("damage", ["archive", "stats", "missing_report", "empty_report", "unexpected_stub"])
def test_merge_gate_rejects_false_success_evidence(merged_bundle, tmp_path, damage):
    """Archive corruption and optional production bookkeeping failures are acceptance failures."""
    plan, config_path, directory, stats_path = merged_bundle
    if damage == "archive":
        archive = directory / "merged-kg.tar.gz"
        archive.write_bytes(archive.read_bytes()[:-8])
    elif damage == "stats":
        stats = yaml.safe_load(stats_path.read_text())
        stats["node_stats"]["total_nodes"] = 2
        stats_path.write_text(yaml.safe_dump(stats))
    elif damage == "missing_report":
        (directory / "merged_stub_nodes.tsv").unlink()
    elif damage == "empty_report":
        (directory / "merged_stub_nodes.tsv").write_text("")
    else:
        with (directory / "merged_stub_nodes.tsv").open("a") as stream:
            stream.write("BAD\t1\tno\tunexpected\tBAD:1\n")
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        helper.verify_merge(plan, config_path, tmp_path)


def test_evidence_receipts_never_overwrite_prior_results_or_inputs(tmp_path):
    """Receipt paths are task-scoped and each observation remains immutable."""
    path = tmp_path / helper.EVIDENCE / "gate.json"
    helper.write_receipt(path, tmp_path, {"status": "pass"})
    with pytest.raises(FileExistsError):
        helper.write_receipt(path, tmp_path, {"status": "fail"})
    assert json.loads(path.read_text()) == {"status": "pass"}
    with pytest.raises(ValueError, match="Receipt must be under"):
        helper.write_receipt(tmp_path / "data/raw/marker.json", tmp_path, {})
