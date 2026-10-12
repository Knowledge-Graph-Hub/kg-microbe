"""Native temporal categories remain upstream, finite, audited and model-honest."""

import copy
import csv
import dataclasses
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import uberon_temporal_categories as temporal
from kg_microbe.utils.ontology_resolution import uberon_category
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

FIXTURE = Path(__file__).parent / "resources/uberon_temporal_categories"
ORIGIN = json.loads((FIXTURE / "origin.json").read_text())
COHORT = ORIGIN["cohort_ids"]


def _policy():
    """
    Use real curated decisions with an explicitly bound offline native excerpt.

    The excerpt declares the reviewed release and yields the reviewed decisions, so only
    the release-file binding is substituted: the excerpt stands for its own release (#1420).
    """
    with temporal.TEMPORAL_DISPOSITIONS_FILE.open() as stream:
        policy = temporal.load_temporal_category_policy(stream)
    assert hashlib.sha256((FIXTURE / "uberon.json").read_bytes()).hexdigest() == ORIGIN["fixture_sha256"]
    policy["native_source"] = {"file": "uberon.json", "sha256": ORIGIN["fixture_sha256"]}
    return policy


def _decisions(policy=None, native=None):
    """Load immutable or deliberately corrupted temporary evidence with no network."""
    policy = _policy() if policy is None else policy
    native = (FIXTURE / "uberon.json").read_text() if native is None else native
    policy = temporal.load_temporal_category_policy(io.StringIO(json.dumps(policy)))
    return temporal.load_temporal_category_evidence(policy, io.StringIO(native))


def _native_node(document, identifier):
    """Find an exact native declaration for controlled negative tests."""
    iri = "http://purl.obolibrary.org/obo/" + identifier.replace(":", "_")
    return next(node for node in document["graphs"][0]["nodes"] if node["id"] == iri)


@pytest.mark.parametrize("identifier", COHORT)
def test_each_reviewed_temporal_class_has_exact_native_outcome(identifier):
    """Every reviewed endpoint is independently supported, including unresolved boundaries."""
    decisions = _decisions()
    decision = decisions[identifier]
    assert decision.identifier == identifier
    assert decision.category == _policy()["records"][identifier]["category"]
    assert decision.root_paths
    assert decision.authority_sha256 == ORIGIN["fixture_sha256"]
    if identifier in {"UBERON:0035944", "UBERON:0035945", "UBERON:0035946"}:
        assert decision.category == "biolink:OntologyClass"
        assert decision.disposition == "unresolved_temporal_boundary"
    elif identifier == "UBERON:0000104":
        assert decision.category == "biolink:Activity"
    else:
        assert decision.category == "biolink:LifeStage"


def test_cohort_is_complete_and_prefix_guard_does_not_invent_final_categories():
    """The early ontology helper defers decisions instead of recreating false anatomy."""
    decisions = _decisions()
    assert set(decisions) == set(COHORT)
    assert Counter(value.category for value in decisions.values()) == {
        "biolink:LifeStage": 54,
        "biolink:Activity": 1,
        "biolink:OntologyClass": 3,
    }
    assert len(ORIGIN["historical_cohort_ids"]) == 39
    assert len(ORIGIN["related_life_stage_ids"]) == 19
    for identifier in decisions:
        assert uberon_category(identifier) == "biolink:OntologyClass"
    assert uberon_category("UBERON:0000955") == "biolink:AnatomicalEntity"
    assert "mappings/uberon_temporal_category_dispositions.json" in SHARED_DATA_INPUTS


@pytest.mark.parametrize("identifier", sorted(set(ORIGIN["endpoint_ids"]) - set(COHORT)))
def test_genuine_continuants_and_existing_go_processes_are_conserved(identifier, tmp_path, monkeypatch):
    """All 63 continuants and 11 GO process endpoints remain exactly as supplied."""
    policy_path = tmp_path / "temporal-policy.json"
    policy_path.write_text(json.dumps(_policy()))
    monkeypatch.setattr(temporal, "TEMPORAL_DISPOSITIONS_FILE", policy_path)
    authority = SourceCategoryAuthority(FIXTURE, opener=lambda path: path.open())
    row = {"id": identifier, "category": ORIGIN["native_endpoint_categories"][identifier], "name": "unchanged"}
    before = dict(row)
    authority.normalize(row)
    assert row == before


@pytest.mark.parametrize(
    "change", ["obsolete", "property", "missing", "broken_path", "continuant", "new_stage_boundary"]
)
def test_invalid_or_contradictory_native_evidence_aborts(change):
    """A re-pinned hypothetical authority still cannot bypass live declared ancestry checks."""
    policy = _policy()
    native = json.loads((FIXTURE / "uberon.json").read_text())
    graph = native["graphs"][0]
    target = _native_node(native, "UBERON:0000068")
    if change == "obsolete":
        target.setdefault("meta", {})["deprecated"] = True
    elif change == "property":
        target["type"] = "PROPERTY"
    elif change == "missing":
        graph["nodes"].remove(target)
    elif change == "broken_path":
        graph["edges"] = [edge for edge in graph["edges"] if edge["sub"] != target["id"]]
    elif change == "continuant":
        graph["edges"].append(
            {"sub": target["id"], "pred": "is_a", "obj": "http://purl.obolibrary.org/obo/BFO_0000002"}
        )
    else:
        graph["edges"].append(
            {
                "sub": "http://purl.obolibrary.org/obo/UBERON_0035944",
                "pred": "is_a",
                "obj": "http://purl.obolibrary.org/obo/UBERON_0000105",
            }
        )
    with pytest.raises(ValueError, match="ancestry|class|witness"):
        _decisions(policy, json.dumps(native))


def _bound(tmp_path, native, source):
    """Load through the release-file binding from a temporary raw directory."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "uberon.json").write_text(native)
    policy = _policy()
    if source is not None:
        (raw / source[0]).write_bytes(source[1])
        policy["native_source"] = {"file": source[0], "sha256": hashlib.sha256(source[1]).hexdigest()}
    paths = set()
    decisions = temporal.load_bound_temporal_evidence(
        policy, raw, lambda target: Path(target).open(encoding="utf-8"), paths
    )
    return decisions, sorted(item.name for item in paths)


def test_reserialized_converted_json_keeps_the_reviewed_decisions():
    """A different serialization of the same reviewed content is accepted; a whole-file pin refused it (#1420)."""
    native = (FIXTURE / "uberon.json").read_text()
    reserialized = json.dumps(json.loads(native), indent=4)
    assert reserialized != native
    assert _decisions(native=reserialized) == _decisions()


def test_the_owl_release_file_is_read_and_bound(tmp_path):
    """The release file the JSON was converted from is read as a consumed input and must match."""
    owl = b'<?xml version="1.0"?>\n<!-- stand-in for the pinned uberon.owl release -->\n'
    decisions, read = _bound(tmp_path, (FIXTURE / "uberon.json").read_text(), ("uberon.owl", owl))
    assert read == ["uberon.json", "uberon.owl"]
    assert {item.authority_sha256 for item in decisions.values()} == {hashlib.sha256(owl).hexdigest()}
    assert {key: dataclasses.replace(item, authority_sha256="") for key, item in decisions.items()} == {
        key: dataclasses.replace(item, authority_sha256="") for key, item in _decisions().items()
    }


def test_authority_byte_drift_and_unreviewed_substantive_types_abort(tmp_path):
    """Release-file drift cannot be repaired by restamping; unexpected existing types require review."""
    with pytest.raises(ValueError, match="Unreviewed release file"):
        _bound(tmp_path, (FIXTURE / "uberon.json").read_text() + " ", None)
    decision = _decisions()["UBERON:0000068"]
    assert (
        temporal.apply_temporal_category("biolink:AnatomicalEntity|biolink:OntologyClass", decision)
        == decision.category
    )
    assert temporal.apply_temporal_category(decision.category, decision) == decision.category
    with pytest.raises(ValueError, match="Unexpected substantive category"):
        temporal.apply_temporal_category("biolink:Cell|biolink:AnatomicalEntity", decision)


@pytest.mark.parametrize("change", ["missing_record", "wrong_category", "wrong_boundary", "wrong_file", "duplicate"])
def test_policy_drift_requires_explicit_finite_review(change):
    """Wrong category semantics and ambiguous policy keys cannot silently override a rule."""
    policy = _policy()
    if change == "missing_record":
        policy["records"].pop("UBERON:0000068")
    elif change == "wrong_category":
        policy["records"]["UBERON:0000104"]["category"] = "biolink:BiologicalProcess"
    elif change == "wrong_boundary":
        policy["records"]["UBERON:0035944"]["category"] = "biolink:LifeStage"
    elif change == "wrong_file":
        policy["native_file"] = "pato.json"
    text = json.dumps(policy)
    if change == "duplicate":
        text = text.replace('"version": 2', '"version": 2, "version": 2')
    with pytest.raises(ValueError):
        temporal.load_temporal_category_policy(io.StringIO(text))


def _source(tmp_path, monkeypatch, provider):
    """Build a real producer-finalization fixture with all finite UBERON decisions."""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    (raw / "uberon.json").write_bytes((FIXTURE / "uberon.json").read_bytes())
    policy_path = tmp_path / "temporal-policy.json"
    policy_path.write_text(json.dumps(_policy()))
    monkeypatch.setattr(temporal, "TEMPORAL_DISPOSITIONS_FILE", policy_path)
    producer = Transform("fixture", raw, tmp_path / "transformed")
    with producer.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["id", "category", "name", "provided_by"], delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(
            {
                "id": identifier,
                "category": "biolink:AnatomicalEntity",
                "name": _policy_record["native_label"],
                "provided_by": provider,
            }
            for identifier, _policy_record in json.loads(policy_path.read_text())["records"].items()
        )
        writer.writerow(
            {"id": "UBERON:0000955", "category": "biolink:AnatomicalEntity", "name": "brain", "provided_by": provider}
        )
    with producer.output_edge_file.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["subject", "predicate", "object", "relation", "primary_knowledge_source"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "subject": "UBERON:0000955",
                "predicate": "biolink:precedes",
                "object": "UBERON:0000068",
                "relation": "RO:0002488",
                "primary_knowledge_source": provider,
            }
        )
    return producer, policy_path


@pytest.mark.parametrize("provider", ["infores:uberon", "infores:pato"])
def test_primary_and_imported_copies_converge_before_merge_with_lossless_audit(tmp_path, monkeypatch, provider):
    """Finite corrections apply independently of supplier, preserving IDs, labels and every edge."""
    producer, policy_path = _source(tmp_path, monkeypatch, provider)
    before_nodes = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    before_edges = list(graph_rows(producer.output_edge_file))
    report = producer.finalize()
    nodes = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    assert nodes.keys() == before_nodes.keys()
    for identifier, before in before_nodes.items():
        assert {key: nodes[identifier][key] for key in before if key != "category"} == {
            key: value for key, value in before.items() if key != "category"
        }
    assert nodes["UBERON:0000955"]["category"] == "biolink:AnatomicalEntity"
    assert Counter(nodes[identifier]["category"] for identifier in COHORT) == ORIGIN["category_counts"]
    after_edges = list(graph_rows(producer.output_edge_file))
    assert [{key: row[key] for key in before_edges[0]} for row in after_edges] == before_edges
    audit = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    category_audits = [row for row in audit if json.loads(row["original_row_json"]).get("id") in COHORT]
    assert len(category_audits) == len(COHORT)
    for row in category_audits:
        original = json.loads(row["original_row_json"])
        normalized = json.loads(row["normalized_row_json"])
        assert original["category"] == "biolink:AnatomicalEntity"
        assert normalized["category"] == nodes[original["id"]]["category"]
    assert {Path(record["path"]).name for record in report["consumed_inputs"].values()} == {
        "uberon.json",
        policy_path.name,
    }
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    policy_path.write_text(policy_path.read_text() + " ")
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


def test_native_change_during_finalization_does_not_publish_staged_categories(tmp_path, monkeypatch):
    """The immutable bytes used by the classifier must still match at publication."""
    producer, _ = _source(tmp_path, monkeypatch, "infores:uberon")
    original = temporal.load_temporal_category_evidence
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()

    def mutate_after_read(policy, stream):
        """Edit the backing file after reading a genuine immutable input snapshot."""
        decisions = original(policy, stream)
        path = producer.input_base_dir / "uberon.json"
        path.write_text(path.read_text() + " ")
        return decisions

    monkeypatch.setattr(temporal, "load_temporal_category_evidence", mutate_after_read)
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        producer.finalize()
    assert (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()) == before
    assert not (producer.output_dir / "source_finalization.json").exists()


def test_pinned_biolink_constraint_defect_remains_visible_after_category_repair():
    """LifeStage lacks Occurrent in the exact pinned model; no false strict-pass claim."""
    schema_path = Path(__file__).parent / "resources/ingredient_bundle/native/biolink-model.yaml"
    assert (
        hashlib.sha256(schema_path.read_bytes()).hexdigest()
        == "b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e"
    )
    schema = yaml.safe_load(schema_path.read_text())
    assert schema["version"] == "4.4.2"
    assert "UBERON:0000105" in schema["classes"]["life stage"]["exact_mappings"]
    assert schema["classes"]["occurrent"]["mixin"] is True

    def ancestors(name):
        """Traverse only the pinned class is_a and mixins, without a local schema patch."""
        parents = copy.deepcopy(schema["classes"][name].get("mixins", []))
        if schema["classes"][name].get("is_a"):
            parents.append(schema["classes"][name]["is_a"])
        return {name}.union(*(ancestors(parent) for parent in parents))

    assert "occurrent" not in ancestors("life stage")
    assert "occurrent" in ancestors("activity")
    assert "occurrent" not in ancestors("anatomical entity")
    assert schema["slots"]["temporally related to"]["domain"] == "occurrent"
    assert schema["slots"]["temporally related to"]["range"] == "occurrent"
