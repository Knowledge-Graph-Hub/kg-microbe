"""Dependency-declared retirements use the actual selected ontology output, not preview labels (#1707)."""

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.merge_kg import _assert_sources_finalized
from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import source_finalization
from kg_microbe.utils.ontology_dependency_declarations import OntologyDependencyDeclarations
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    graph_rows,
    verify_finalized_source_files,
)
from tests.test_bacdive_taxonomy_evidence import retired_producer
from tests.test_declared_taxid_retirement import _published
from tests.test_external_node_closure import _taxdump


def _identity(path):
    """Hash only this bounded native dependency fixture."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _dependency(source, *, receipt=False, name="Named upstream ten", selected=True):
    """Write the actual finalizer dependency; a receipt restricts selection to its member inventory."""
    directory = source.output_base_dir / "ontologies"
    directory.mkdir(exist_ok=True)
    path = directory / "ncbitaxon_nodes.tsv"
    path.write_text(f"id\tname\tcategory\nNCBITaxon:10\t{name}\tbiolink:OrganismTaxon\n")
    if receipt:
        member = path
        if not selected:
            member = directory / "other_nodes.tsv"
            member.write_text("id\tname\tcategory\nNCBITaxon:12\tOther taxon\tbiolink:OrganismTaxon\n")
        # This bounded inventory exercises the existing whole-source selection
        # route; upstream whole-graph/freshness acceptance is a separate gate.
        (directory / "source_finalization.json").write_text(json.dumps({"members": {member.name: _identity(member)}}))
    return path


def _producer(tmp_path, monkeypatch):
    """Keep BacDive's actual supplied ID but no emitted local declaration of that parent."""
    source = retired_producer(tmp_path, monkeypatch, declare_retired=False)
    assert not any(row["id"] == "NCBITaxon:10" for row in graph_rows(source.output_node_file))
    _taxdump(Path(source.input_base_dir), merged="10 | 20 |\n")
    return source


@pytest.mark.parametrize("receipt", [False, True])
def test_dependency_only_nonprokaryote_retirement_admits_and_freshly_repeats(
    tmp_path, monkeypatch, local_source_schema, receipt
):
    """Actual selected upstream names license exact retirement without inventing a local donor row."""
    source = _producer(tmp_path, monkeypatch)
    path = _dependency(source, receipt=receipt)
    native_contract = source.producer_native_inputs
    report = source.finalize()
    assert report["producer_native_inputs"] == native_contract
    assert report["ontology_dependency_declarations"]["members"][path.name]["sha256"] == _identity(path)["sha256"]
    rewritten = [row for row in graph_rows(source.output_edge_file) if row.get("original_object") == "NCBITaxon:10"]
    assert len(rewritten) == 2
    assert {row["object"] for row in rewritten} == {"NCBITaxon:20"}
    audit = list(graph_rows(source.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    selected = [row for row in audit if row["original_id"] == "NCBITaxon:10"]
    assert selected and all(not row["original_node_json"] for row in selected)
    before = _published(source)
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    fresh = BacDiveTransform.__new__(BacDiveTransform)
    Transform.__init__(fresh, "bacdive", source.input_base_dir, source.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()
    assert _published(source) == before


@pytest.mark.parametrize("evidence", ["preview-only", "unnamed", "outside-inventory"])
def test_unselected_or_unnamed_upstream_rows_cannot_license_nonprokaryote_retirement(
    tmp_path, monkeypatch, local_source_schema, evidence
):
    """Constructor labels and files outside the actual dependency inventory are not declaration proof."""
    source = _producer(tmp_path, monkeypatch)
    if evidence == "unnamed":
        _dependency(source, name="")
    elif evidence == "outside-inventory":
        _dependency(source, receipt=True, selected=False)
    before = _published(source)
    with pytest.raises(SourceFinalizationRequired):
        source.finalize()
    assert _published(source) == before


@pytest.mark.parametrize("timing", ["after-dependency-read", "before-publish"])
def test_dependency_bytes_remain_bound_from_generic_selection_to_publication(
    tmp_path, monkeypatch, local_source_schema, timing
):
    """A changed upstream declaration cannot be restamped after it licenses the generic rewrite."""
    source = _producer(tmp_path, monkeypatch)
    path = _dependency(source)
    before = _published(source)
    function = "_dependency_declarations" if timing == "after-dependency-read" else "_publish_finalization"
    original = getattr(source_finalization, function)
    changed = False

    def change_dependency(*args, **kwargs):
        """Remove the native declaration in the selected publication window."""
        nonlocal changed
        if timing == "after-dependency-read":
            result = original(*args, **kwargs)
            path.write_text(path.read_text().replace("Named upstream ten", ""))
            changed = True
            return result
        path.write_text(path.read_text().replace("Named upstream ten", ""))
        changed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(source_finalization, function, change_dependency)
    with pytest.raises(SourceFinalizationRequired):
        source.finalize()
    assert changed
    assert _published(source) == before


@pytest.mark.parametrize(
    "damage",
    ["bytes", "missing", "new-member", "receipt-appears", "root-retarget", "lost-member-read", "lost-receipt-absence"],
)
def test_public_dependency_admission_retains_original_inventory_and_bindings(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Fresh public proof retains root, membership, native bytes and receipt absence after it returns."""
    source = _producer(tmp_path, monkeypatch)
    path = _dependency(source)
    report = source.finalize()
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, source.output_dir / "source_finalization.json", admission=SourceAdmission()
    )
    before = _published(source)
    if damage == "bytes":
        path.write_text(path.read_text().replace("Named upstream ten", "Different name"))
    elif damage == "missing":
        path.unlink()
    elif damage == "new-member":
        (path.parent / "added_nodes.tsv").write_text("id\tname\nNCBITaxon:99\tAdded\n")
    elif damage == "receipt-appears":
        (path.parent / "source_finalization.json").write_text(json.dumps({"members": {path.name: _identity(path)}}))
    elif damage == "root-retarget":
        original = path.parent.with_name("original-ontologies")
        path.parent.rename(original)
        path.parent.symlink_to(original, target_is_directory=True)
    elif damage == "lost-member-read":
        admission.identities.pop(path.resolve())
    else:
        admission.absent.remove((path.parent / "source_finalization.json").resolve())
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)
    if not damage.startswith("lost-"):
        with pytest.raises(SourceFinalizationRequired):
            verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert _published(source) == before


def test_coherent_dependency_restamp_cannot_replace_original_named_membership(
    tmp_path, monkeypatch, local_source_schema
):
    """Current native named-ID membership, not a self-consistent receipt, licenses the exception."""
    source = _producer(tmp_path, monkeypatch)
    path = _dependency(source)
    report = source.finalize()
    path.write_text("id\tname\tcategory\nNCBITaxon:20\tOnly the canonical taxon\tbiolink:OrganismTaxon\n")
    changed = OntologyDependencyDeclarations(path.parent)
    report["ontology_dependency_declarations"] = changed.contract
    for item in report["inputs"]:
        if item["path"] == str(path.resolve()):
            item["sha256"] = _identity(path)["sha256"]
    (source.output_dir / "source_finalization.json").write_text(json.dumps(report))
    before = _published(source)
    with pytest.raises(SourceFinalizationRequired, match="native authority does not prove"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert _published(source) == before


def _aliased_producer(tmp_path, monkeypatch, *, receipt=False):
    """Run through a selected transformed-root symlink present before the producer starts."""
    actual = tmp_path / "actual-transformed"
    actual.mkdir()
    selected = tmp_path / "transformed"
    selected.symlink_to(actual, target_is_directory=True)
    source = _producer(tmp_path, monkeypatch)
    _dependency(source, receipt=receipt)
    report = source.finalize()
    assert report["ontology_dependency_declarations"]["directory_locator"] == str(selected / "ontologies")
    assert report["ontology_dependency_declarations"]["directory"] == str(actual / "ontologies")
    return source, selected, actual, report


@pytest.mark.parametrize("receipt", [False, True])
def test_unchanged_output_alias_and_canonical_paths_admit_public_and_fresh_repeat(
    tmp_path, monkeypatch, local_source_schema, receipt
):
    """Merge canonicalization preserves an unchanged original dependency locator (#1708)."""
    source, selected, actual, report = _aliased_producer(tmp_path, monkeypatch, receipt=receipt)
    before = _published(source)
    another = tmp_path / "another-transformed-alias"
    another.symlink_to(actual, target_is_directory=True)
    for root in (selected, actual, another):
        files = [root / "bacdive" / name for name in ("nodes.tsv", "edges.tsv")]
        verify_finalized_source_files(files)
        config = tmp_path / "merge.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "merged_graph": {
                        "source": {"bacdive": {"input": {"filename": list(map(str, files)), "format": "tsv"}}}
                    }
                }
            )
        )
        # The real merge gate canonicalizes input paths. This tiny fixture
        # deliberately has no producer/upstream freshness markers: successful
        # dependency admission must reach that separate, unchanged marker gate.
        with pytest.raises(SourceFinalizationRequired, match="missing/unsupported producer fingerprint"):
            _assert_sources_finalized(str(config))
        fresh = BacDiveTransform.__new__(BacDiveTransform)
        Transform.__init__(fresh, "bacdive", source.input_base_dir, root)
        assert fresh.finalize() == report
        fresh.verify_native_inputs()
        assert _published(source) == before


@pytest.mark.parametrize("damage", ["original-alias-retarget", "foreign-copy", "member-retarget"])
def test_canonical_public_admission_still_rejects_changed_alias_or_foreign_identical_output(
    tmp_path, monkeypatch, local_source_schema, damage
):
    """Equivalent spelling never licenses retargeted original selection or another identical root."""
    source, selected, actual, report = _aliased_producer(tmp_path, monkeypatch)
    canonical_files = [actual / "bacdive" / name for name in ("nodes.tsv", "edges.tsv")]
    retained = BacDiveTransform.verify_recorded_native_inputs(
        report, actual / "bacdive/source_finalization.json", admission=SourceAdmission()
    )
    before = _published(source)
    if damage in {"original-alias-retarget", "foreign-copy"}:
        foreign = tmp_path / "foreign-transformed"
        shutil.copytree(actual, foreign)
        assert (foreign / "ontologies/ncbitaxon_nodes.tsv").read_bytes() == (
            actual / "ontologies/ncbitaxon_nodes.tsv"
        ).read_bytes()
        if damage == "original-alias-retarget":
            selected.unlink()
            selected.symlink_to(foreign, target_is_directory=True)
        else:
            canonical_files = [foreign / "bacdive" / name for name in ("nodes.tsv", "edges.tsv")]
    else:
        member = actual / "ontologies/ncbitaxon_nodes.tsv"
        replacement = actual / "ontologies/identical-native.tsv"
        replacement.write_bytes(member.read_bytes())
        member.unlink()
        member.symlink_to(replacement)
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(canonical_files)
    if damage != "foreign-copy":
        with pytest.raises(SourceFinalizationRequired):
            retained.verify(metadata_only=True)
    else:
        # The original target remains admissible; only the unrelated copy fails.
        retained.verify()
        verify_finalized_source_files([actual / "bacdive" / name for name in ("nodes.tsv", "edges.tsv")])
    assert _published(source) == before
    assert {path.name: path.read_bytes() for path in (actual / "bacdive").iterdir() if path.is_file()} == before


@pytest.mark.parametrize("binding", ["original-alias", "canonical-selection"])
def test_public_dependency_replay_retains_both_root_binding_obligations(
    tmp_path, monkeypatch, local_source_schema, binding
):
    """Losing either root cache entry cannot downgrade the original selection to byte-only proof."""
    source, selected, actual, report = _aliased_producer(tmp_path, monkeypatch)
    admission = BacDiveTransform.verify_recorded_native_inputs(
        report, actual / "bacdive/source_finalization.json", admission=SourceAdmission()
    )
    before = _published(source)
    root = selected if binding == "original-alias" else actual
    admission.bindings.pop(root / "ontologies")
    with pytest.raises(SourceFinalizationRequired, match="dependency directory binding was lost"):
        admission.verify(metadata_only=True)
    assert _published(source) == before


@pytest.mark.parametrize("key", ["directory_locator", "directory"])
@pytest.mark.parametrize("damage", ["missing", "relative", "null", "foreign"])
def test_public_dependency_replay_rejects_invalid_original_directory_contract(
    tmp_path, monkeypatch, local_source_schema, key, damage
):
    """Canonical access cannot replace missing original selection or an unrelated identical root."""
    source, _selected, actual, report = _aliased_producer(tmp_path, monkeypatch)
    proof = report["ontology_dependency_declarations"]
    if damage == "missing":
        del proof[key]
    elif damage == "relative":
        proof[key] = "ontologies"
    elif damage == "null":
        proof[key] = None
    else:
        foreign = tmp_path / "unrelated-ontologies"
        shutil.copytree(actual / "ontologies", foreign)
        proof[key] = str(foreign)
    (actual / "bacdive/source_finalization.json").write_text(json.dumps(report))
    before = _published(source)
    with pytest.raises(SourceFinalizationRequired, match="dependency directory"):
        verify_finalized_source_files([actual / "bacdive" / name for name in ("nodes.tsv", "edges.tsv")])
    assert _published(source) == before
