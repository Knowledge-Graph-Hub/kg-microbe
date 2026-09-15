"""Source finalization owns semantic corrections; merge preserves finalized observation text."""

import csv
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    finalize_source,
    graph_rows,
    validate_graph_bundle,
    verify_finalized_source_files,
)
from kg_microbe.utils.transform_fingerprint import finalization_inputs_current, write_fingerprint

FIXTURES = Path(__file__).parent / "resources"


def _transform(tmp_path, quoting=csv.QUOTE_MINIMAL):
    """Create an explicit producer boundary with isolated raw and transformed roots."""
    raw, output = tmp_path / "raw", tmp_path / "transformed"
    raw.mkdir()
    result = Transform("fixture", raw, output)
    result.TSV_QUOTING = quoting
    return result


def _pair(transform, *, target="fixture:2", value="plain"):
    """Write literal test observations, including quoted scalars that are data, not TSV syntax."""
    transform.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\nfixture:1\tbiolink:NamedThing\tOne\tinfores:test\n"
        f"{target}\tbiolink:NamedThing\tTwo\tinfores:test\n"
    )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tvalue\tvalue_encoding\n"
        f"fixture:1\tbiolink:related_to\t{target}\tskos:related\tinfores:test\t{value}\tbackslash\n"
    )


def test_representation_finalization_is_upstream_and_audited(tmp_path):
    """Known identity aliases and imported categories are resolved before KGX ingestion."""
    transform = _transform(tmp_path)
    (transform.input_base_dir / "foodon.json").write_text('{"graphs": []}')
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / "relation_aware_merge" / f"alpha_{kind}.tsv", transform.output_dir / f"{kind}.tsv")
    report = transform.finalize()
    assert {row["id"] for row in graph_rows(transform.output_node_file)} == {"time:Instant", "FOODON:1"}
    assert {row["subject"] for row in graph_rows(transform.output_edge_file)} == {"time:Instant"}
    audit = list(graph_rows(transform.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    assert len(audit) == 3
    assert "https://www.w3.org/TR/owl-time/" in audit[0]["original_row_json"]
    assert str((transform.input_base_dir / "foodon.json").resolve()) in {row["path"] for row in report["inputs"]}


@pytest.mark.parametrize("quoting", [csv.QUOTE_NONE, csv.QUOTE_MINIMAL])
def test_quote_values_round_trip_through_finalization_and_merge_projection(tmp_path, quoting):
    """Literal quotes remain exact whether the producer uses native KGX or legacy quoted TSV."""
    from kg_microbe.merge_utils.merge_kg import _normalize_edges_tsv

    transform = _transform(tmp_path, quoting)
    _pair(transform, value='"quoted"' if quoting == csv.QUOTE_NONE else '"""quoted"""')
    finalize_source(transform)
    _normalize_edges_tsv(transform.output_edge_file)
    assert list(graph_rows(transform.output_edge_file))[0]["value"] == '"quoted"'


def test_assertion_controls_are_not_silently_flattened(tmp_path):
    """Unknown scalar fields require an explicit producer encoding, not a lossy generic cleanup."""
    transform = _transform(tmp_path)
    _pair(transform, value='"first\nsecond"')
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()
    with pytest.raises(SourceFinalizationRequired, match="value has unencoded control"):
        finalize_source(transform)
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_go_failure_publishes_no_staged_files_or_report(tmp_path, monkeypatch):
    """Authority failure happens before finalized source replacement, not after partial repairs."""
    from kg_microbe.utils import go_authority

    transform = _transform(tmp_path)
    _pair(transform, target="GO:0004096")
    before = transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes()

    def unavailable(raw_dir):
        """Simulate an unavailable selected authority before publication."""
        assert raw_dir == transform.input_base_dir
        raise RuntimeError("authority unavailable")

    monkeypatch.setattr(go_authority, "load_go_authority", unavailable)
    with pytest.raises(RuntimeError, match="authority unavailable"):
        transform.finalize()
    assert before == (transform.output_node_file.read_bytes(), transform.output_edge_file.read_bytes())
    assert not list(transform.output_dir.glob("*resolution.tsv"))


def test_go_authority_corrects_named_nonanonymous_stub_before_merge(tmp_path, monkeypatch):
    """The shared hook consults GO even when an importer supplied an incorrect label/category."""
    from kg_microbe.utils import go_authority

    transform = _transform(tmp_path, csv.QUOTE_NONE)
    _pair(transform, target="GO:0004096", value='"quoted"')
    statements_path = transform.input_base_dir / "go.db"
    shutil.copyfile(FIXTURES / "go_authority" / "statements.tsv", statements_path)
    with statements_path.open() as stream:
        statements = [
            tuple(row[key] or None for key in ("subject", "predicate", "object", "value"))
            for row in csv.DictReader(stream, delimiter="\t")
        ]
    authority = go_authority.GoAuthority.from_statements(statements, authority_path=str(statements_path))
    monkeypatch.setattr(go_authority, "load_go_authority", lambda raw_dir: authority)
    report = transform.finalize()
    nodes = {row["id"]: row for row in graph_rows(transform.output_node_file)}
    assert nodes["GO:0004096"]["category"] == "biolink:MolecularActivity"
    assert nodes["GO:0004096"]["name"] == "catalase activity"
    assert list(graph_rows(transform.output_edge_file))[0]["value"] == '"quoted"'
    assert str(statements_path.resolve()) in {row["path"] for row in report["inputs"]}


def test_dependency_declared_cross_source_target_is_not_an_anonymous_stub(tmp_path):
    """Per-transform incompleteness cannot justify dropping a valid named ontology target."""
    transform = _transform(tmp_path)
    _pair(transform)
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\nfixture:1\tbiolink:related_to\tNCBITaxon:20\tskos:related\n"
    )
    ontology_dir = transform.output_base_dir / "ontologies"
    ontology_dir.mkdir()
    authority = ontology_dir / "foodon_nodes.tsv"
    authority.write_text("id\tname\tcategory\nNCBITaxon:20\tNamed organism\tbiolink:OrganismTaxon\n")
    report = transform.finalize()
    assert list(graph_rows(transform.output_edge_file))[0]["object"] == "NCBITaxon:20"
    assert report["summaries"]["external"] == {}
    assert str(authority.resolve()) in transform.finalization_inputs
    with pytest.raises(SourceFinalizationRequired, match="undeclared endpoint"):
        validate_graph_bundle([transform.output_node_file], [transform.output_edge_file], require_closure=True)
    validate_graph_bundle([transform.output_node_file, authority], [transform.output_edge_file], require_closure=True)


def test_cli_finalizes_before_success_marker_and_invalidates_on_failure(tmp_path, monkeypatch):
    """An older success claim cannot survive a failed producer/finalizer attempt."""
    import kg_microbe.transform as dispatcher

    transform = _transform(tmp_path)
    _pair(transform)
    marker = transform.output_dir / "source_fingerprint.json"
    marker.write_text("previous success")
    events = []
    transform.run = lambda **kwargs: events.append("run")

    def fail(**kwargs):
        """Fail finalization after confirming the old success marker is gone."""
        events.append("finalize")
        assert not marker.exists()
        raise RuntimeError("finalizer failed")

    transform.finalize = fail
    monkeypatch.setitem(dispatcher.DATA_SOURCES, "fixture", lambda *args: transform)
    monkeypatch.setattr(dispatcher, "_record_fingerprint", lambda *args: events.append("fingerprint"))
    with pytest.raises(RuntimeError, match="finalizer failed"):
        dispatcher._run_one("fixture", None, None, False)
    assert events == ["run", "finalize"] and not marker.exists()
    transform.finalize = lambda **kwargs: events.append("finalize")
    dispatcher._run_one("fixture", None, None, False)
    assert events[-3:] == ["run", "finalize", "fingerprint"]


def test_consumed_authority_changes_invalidate_freshness(tmp_path, monkeypatch):
    """Dynamic raw/dependency reads are checked alongside static DATA_INPUTS."""
    code = tmp_path / "kg_microbe" / "transform_utils" / "fixture"
    code.mkdir(parents=True)
    (code / "fixture.py").write_text("X = 1\n")
    output = tmp_path / "data" / "transformed" / "fixture"
    output.mkdir(parents=True)
    authority = tmp_path / "authority.tsv"
    authority.write_text("original")
    marker = write_fingerprint(output, code, tmp_path, (), finalization_inputs=[str(authority)])
    assert finalization_inputs_current(marker, tmp_path)
    script = Path(__file__).parents[1] / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("freshness_finalization_fixture", script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "TRANSFORMED_DIR", output.parent)
    monkeypatch.setattr(module, "_declared_data_inputs", lambda source: ())
    monkeypatch.setattr(module, "_declared_transform_inputs", lambda source: ())
    assert module._fingerprint_verdict("fixture", code)[0] == "FRESH"
    authority.write_text("changed")
    assert not finalization_inputs_current(marker, tmp_path)
    assert module._fingerprint_verdict("fixture", code)[0] == "STALE_VS_DATA"
    authority.unlink()
    assert not finalization_inputs_current(marker, tmp_path)
    assert module._fingerprint_verdict("fixture", code)[0] == "STALE_VS_DATA"


def test_merge_projection_rejects_conflicting_duplicate_fields(tmp_path):
    """Serialization projection cannot choose among conflicting observation values."""
    from kg_microbe.merge_utils.merge_kg import _normalize_edges_tsv

    path = tmp_path / "edges.tsv"
    path.write_text("subject\tpredicate\tobject\tvalue\tvalue\nfixture:1\tbiolink:related_to\tfixture:2\t1\t2\n")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        _normalize_edges_tsv(path)
    assert path.read_bytes() == original


def test_public_merge_gate_requires_exact_prepared_inputs(tmp_path, monkeypatch):
    """An arbitrary external directory is not a silent exemption from source preparation."""
    import yaml

    from kg_microbe.merge_utils import merge_kg

    transform = _transform(tmp_path)
    _pair(transform)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "merged_graph": {
                    "source": {
                        "fixture": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(transform.output_node_file), str(transform.output_edge_file)],
                            }
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setattr(merge_kg, "merge", lambda *args, **kwargs: pytest.fail("must reject before KGX writes"))
    with pytest.raises(SourceFinalizationRequired, match="absent/stale"):
        merge_kg.load_and_merge(str(config))
    transform.finalize()
    merge_kg._assert_sources_finalized(str(config))
    transform.output_edge_file.write_text(transform.output_edge_file.read_text().replace("plain", "changed"))
    with pytest.raises(SourceFinalizationRequired, match="absent/stale"):
        merge_kg.load_and_merge(str(config))


def test_preflight_rejects_changed_authority_even_when_graph_bytes_match(tmp_path):
    """Finalizer input evidence cannot silently drift after the prepared pair was published."""
    transform = _transform(tmp_path)
    _pair(transform, target="PATO:0000001")
    transform.finalize()
    report_path = transform.output_dir / "source_finalization.json"
    report = json.loads(report_path.read_text())
    authority = tmp_path / "authority.tsv"
    authority.write_text("authority")
    import hashlib

    report["inputs"] = [{"path": str(authority), "sha256": hashlib.sha256(authority.read_bytes()).hexdigest()}]
    report_path.write_text(json.dumps(report))
    paths = [transform.output_node_file, transform.output_edge_file]
    verify_finalized_source_files(paths)
    authority.write_text("changed authority")
    with pytest.raises(SourceFinalizationRequired, match="consumed authority changed"):
        verify_finalized_source_files(paths)


def test_diagnostic_opt_out_is_conspicuous_and_written_in_manifest(tmp_path, monkeypatch, capsys):
    """Opt-out is explicit config, never inferred from a fixture path or working directory."""
    import yaml

    from kg_microbe.merge_utils import merge_kg

    transform = _transform(tmp_path)
    _pair(transform)
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"allow_unfinalized_sources": True, "output_directory": str(transform.output_dir)},
                "merged_graph": {
                    "source": {"fixture": {"input": {"filename": [str(transform.output_node_file)]}}},
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        )
    )
    merge_kg._assert_sources_finalized(str(config))
    assert "DIAGNOSTIC OPT-OUT" in capsys.readouterr().out
    shutil.copyfile(transform.output_node_file, transform.output_dir / "fixture_nodes.tsv")
    shutil.copyfile(transform.output_edge_file, transform.output_dir / "fixture_edges.tsv")
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    merge_kg._cleanup_merged_outputs(str(config))
    manifest = json.loads((transform.output_dir / "fixture_manifest.json").read_text())
    assert manifest["provenance"]["source_finalization"] == {"required": False, "diagnostic_opt_out": True}


def test_repeat_finalization_preserves_audit_and_literal_values(tmp_path):
    """A repeat on already prepared bytes is a no-op, not a new lossy producer-dialect parse."""
    transform = _transform(tmp_path)
    _pair(transform, target="PATO:0000001", value='"""quoted"""')
    first = transform.finalize()
    audit = transform.output_dir / "source_canonicalization.tsv"
    prior = audit.read_bytes(), transform.output_edge_file.read_bytes()
    assert list(graph_rows(audit, quoting=csv.QUOTE_MINIMAL))
    assert transform.finalize() == first
    assert prior == (audit.read_bytes(), transform.output_edge_file.read_bytes())
    assert list(graph_rows(transform.output_edge_file))[0]["value"] == '"quoted"'


def test_selected_dataset_finalization_never_discovers_stale_siblings(tmp_path):
    """Explicit dataset output selection supports Bakta without recursively including old runs."""
    transform = _transform(tmp_path)
    selected = transform.output_dir / "selected"
    selected.mkdir()
    stale = transform.output_dir / "stale"
    stale.mkdir()
    view = Transform("selected", transform.input_base_dir, transform.output_dir)
    _pair(view, target="PATO:0000001")
    stale_file = stale / "nodes.tsv"
    stale_file.write_text("old unrelated output")
    transform.finalization_output_dirs = [selected]
    result = transform.finalize(fresh_run=True)
    assert set(result["datasets"]) == {str(selected)}
    assert (selected / "source_finalization.json").is_file()
    assert stale_file.read_text() == "old unrelated output"


def test_all_selected_datasets_validate_before_any_finalizer_publication(tmp_path):
    """A failed selected dataset cannot publish another dataset's staged semantic changes."""
    transform = _transform(tmp_path)
    one = Transform("one", transform.input_base_dir, transform.output_dir)
    two = Transform("two", transform.input_base_dir, transform.output_dir)
    _pair(one, target="PATO:0000001")
    _pair(two, value='"line1\nline2"')
    before = one.output_node_file.read_bytes()
    transform.finalization_output_dirs = [one.output_dir, two.output_dir]
    with pytest.raises(SourceFinalizationRequired, match="unencoded control"):
        transform.finalize(fresh_run=True)
    assert one.output_node_file.read_bytes() == before
    assert not (one.output_dir / "source_finalization.json").exists()


def test_new_source_without_go_replaces_previous_go_report(tmp_path):
    """A fresh producer run cannot leave a misleading prior GO disposition report beside current output."""
    transform = _transform(tmp_path)
    _pair(transform)
    report = transform.output_dir / "go_reference_resolution.tsv"
    report.write_text("stale audit from a different producer run")
    transform.finalize(fresh_run=True)
    assert list(graph_rows(report, quoting=csv.QUOTE_MINIMAL)) == []
