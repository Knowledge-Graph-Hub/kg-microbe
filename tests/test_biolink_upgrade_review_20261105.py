"""Offline evidence boundaries for the dated Biolink comparison helper."""

import copy
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.source_admission import SourceAdmission

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "biolink_upgrade_review", REPO / "scripts/adhoc/kgm_biolink_upgrade_review_20261105.py"
)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


@pytest.fixture
def bundle_pair(tmp_path):
    """Use explicit synthetic epochs to test inheritance, never to claim a real model review."""
    model = {
        "version": "fixture-old",
        "imports": ["linkml:types", "attributes"],
        "classes": {
            "entity": {},
            "ontology class": {"is_a": "entity"},
            "parent": {"is_a": "entity", "slots": ["attribute type"]},
            "selected": {"is_a": "parent"},
        },
        "slots": {
            "attribute type": {"range": "ontology class", "required": True},
            "related to": {"exact_mappings": ["RO:0000001"]},
        },
    }
    for name, version in (("old", "fixture-old"), ("new", "fixture-new")):
        directory = tmp_path / name
        directory.mkdir()
        value = copy.deepcopy(model)
        value["version"] = version
        (directory / "biolink-model.yaml").write_text(yaml.safe_dump(value))
        (directory / "attributes.yaml").write_text("imports: [linkml:types]\nslots: {}\n")
        (directory / "predicate_mapping.yaml").write_text("predicate mappings: []\n")
    return tmp_path / "old", tmp_path / "new"


def _load_pair(paths):
    """Bind both fixture epochs to one mutation-detecting production reader."""
    admission = SourceAdmission()
    old = review.load_bundle(paths[0], "fixture-old", admission)
    new = review.load_bundle(paths[1], "fixture-new", admission)
    return old, new, admission


@pytest.mark.parametrize("field", ["is_a", "mixins", "slot_requirement"])
def test_selected_class_detects_changed_inherited_semantics(bundle_pair, field):
    """An unchanged selected class cannot conceal a changed parent, mixin or inherited slot."""
    path = bundle_pair[1] / "biolink-model.yaml"
    model = yaml.safe_load(path.read_text())
    if field == "is_a":
        model["classes"]["parent"]["is_a"] = "ontology class"
    elif field == "mixins":
        model["classes"]["parent"]["mixins"] = ["ontology class"]
    else:
        model["slots"]["attribute type"]["required"] = False
    path.write_text(yaml.safe_dump(model))
    old, new, _ = _load_pair(bundle_pair)
    result = review.term_comparison(old, new, "classes", "selected")
    assert result["old"]["declaration"] == result["new"]["declaration"]
    assert result["changed"] and result["changes"]


def test_duplicate_yaml_keys_are_not_silently_discarded():
    """Every source statement must have an unambiguous parsed representation."""
    with pytest.raises(ValueError, match="Duplicate YAML key"):
        review.read_yaml("version: one\nversion: two\n")


@pytest.mark.parametrize("fault", ["missing_import", "remote_import", "wrong_epoch"])
def test_incomplete_or_misattributed_bundles_fail(bundle_pair, fault):
    """Complete local imports and actual version identity are prerequisites for comparison."""
    directory = bundle_pair[0]
    if fault == "missing_import":
        (directory / "attributes.yaml").unlink()
    elif fault == "remote_import":
        path = directory / "attributes.yaml"
        path.write_text("imports: [https://example.org/schema]\n")
    with pytest.raises((ValueError, RuntimeError)):
        review.load_bundle(directory, "wrong" if fault == "wrong_epoch" else "fixture-old", SourceAdmission())


def test_native_mapping_strength_change_is_visible(bundle_pair):
    """A native relation must not silently acquire broader or stronger Biolink meaning."""
    path = bundle_pair[1] / "biolink-model.yaml"
    model = yaml.safe_load(path.read_text())
    model["slots"]["related to"] = {"narrow_mappings": ["RO:0000001"]}
    path.write_text(yaml.safe_dump(model))
    old, new, _ = _load_pair(bundle_pair)
    result = review.native_relation_comparison(old, new, {"RO:0000001"})
    assert result["changes"]
    assert result["old"]["RO:0000001"]["slot_mappings"][0]["mapping_field"] == "exact_mappings"
    assert result["new"]["RO:0000001"]["slot_mappings"][0]["mapping_field"] == "narrow_mappings"


def test_ancestry_cycles_fail_instead_of_truncating_evidence(bundle_pair):
    """A cycle cannot produce a plausible partial ancestry receipt."""
    old, _, _ = _load_pair(bundle_pair)
    old["definitions"]["classes"]["entity"]["is_a"] = "selected"
    with pytest.raises(ValueError, match="Cyclic"):
        review.term_evidence(old, "classes", "selected")


def _archive(path, duplicate=False):
    """Write a tiny graph archive with literal category and predicate values."""
    members = [
        ("test_nodes.tsv", b"id\tcategory\nA:1\tbiolink:Selected|biolink:Selected\nA:2\tbiolink:Parent\n"),
        ("test_edges.tsv", b"subject\tpredicate\tobject\trelation\nA:1\tbiolink:related_to\tA:2\tRO:0000001\n"),
    ]
    if duplicate:
        members.append(members[0])
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_graph_inventory_streams_exact_incidence_and_predicate_counts(tmp_path):
    """Repeated category tokens on one node count once; raw relation evidence survives."""
    path = tmp_path / "graph.tar.gz"
    _archive(path)
    admission = SourceAdmission()
    result = review.graph_inventory(path, None, None, admission)
    assert result["nodes"]["rows"] == 2
    assert result["nodes"]["counts"] == {"biolink:Parent": 1, "biolink:Selected": 1}
    assert result["edges"]["relations"] == {"RO:0000001": 1}
    assert result["edges"]["counts"] == {"biolink:related_to": 1}
    assert not result["scientific_acceptance"]
    assert list(tmp_path.iterdir()) == [path]


def test_graph_inventory_rejects_duplicate_archive_members(tmp_path):
    """An ambiguous archive cannot establish a reference graph inventory."""
    path = tmp_path / "graph.tar.gz"
    _archive(path, duplicate=True)
    with pytest.raises(ValueError, match="duplicate"):
        review.graph_inventory(path, None, None, SourceAdmission())


def test_profile_plan_does_not_clone_historical_diagnostics(bundle_pair):
    """A target model's profile starts with required evidence, never inherited acceptance."""
    _, new, _ = _load_pair(bundle_pair)
    history = {
        "legacy.json": {"reference": {"biolink_version": "fixture-old"}, "diagnostics": [{"signature": "historical"}]}
    }
    result = review.diagnostic_profile_plan(new, {"historical_profiles": history})
    assert result["diagnostics"] == []
    assert result["historical_profiles_preserved"] == history
    assert result["status"] == "plan_only_not_a_profile"
    assert not result["scientific_acceptance"] and not result["release_authorized"]


def test_runtime_policy_requires_exact_supplied_old_schema(bundle_pair, tmp_path):
    """A policy cannot be compared as if it came from a different source model epoch."""
    old, new, admission = _load_pair(bundle_pair)
    mappings = tmp_path / "mappings"
    mappings.mkdir()
    value = {"model_version": "fixture-old", "model_sha256": "wrong", "model_classes": {}, "records": {}}
    (mappings / review.RUNTIME_POLICIES[0]).write_text(json.dumps(value))
    with pytest.raises(ValueError, match="not bound to supplied old model"):
        review.policy_comparison(old, new, tmp_path, admission)


def test_null_schema_sections_are_valid_empty_imports(bundle_pair):
    """Official attributes.yaml may declare empty sections as YAML null."""
    (bundle_pair[0] / "attributes.yaml").write_text("imports: [linkml:types]\nclasses:\nslots:\n")
    old, _, _ = _load_pair(bundle_pair)
    assert set(old["definitions"]["classes"]) == {"entity", "ontology class", "parent", "selected"}


def test_ambiguous_name_spelling_is_reported_without_discarding_either_definition(bundle_pair):
    """Unused overlapping schema names must not hide evidence for graph-referenced terms."""
    old, new, _ = _load_pair(bundle_pair)
    new["definitions"]["classes"]["Selected"] = {"is_a": "ontology class"}
    comparison = review.compare_identifiers(old, new, {"biolink:Selected"})["biolink:Selected"]
    assert comparison[0]["normalized_name_ambiguity"] == ["Selected", "selected"]
    assert {entry["term"] for entry in comparison if "term" in entry} == {"Selected", "selected"}
