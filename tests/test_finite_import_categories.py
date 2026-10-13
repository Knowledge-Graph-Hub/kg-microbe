"""Finite native import projections are hermetic, upstream, audited and model-honest."""

import copy
import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import finite_import_categories as finite
from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files
from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

FIXTURE = Path(__file__).parent / "resources/finite_import_categories"
NATIVE = FIXTURE / "native"
ORIGIN = json.loads((FIXTURE / "origin.json").read_text())
POLICY = json.loads(finite.IMPORT_DISPOSITIONS_FILE.read_text())
COHORT = sorted(POLICY["records"])


def _policy():
    """
    Bind faithful small excerpts as their own release files; never pretend they are whole production files.

    The excerpts declare the reviewed release and yield the reviewed decisions, so only the
    release-file binding is substituted (#1420).
    """
    policy = finite.load_import_category_policy(io.StringIO(json.dumps(POLICY)))
    for filename, authority in policy["authorities"].items():
        origin = ORIGIN["native_manifest"][filename]
        assert hashlib.sha256((NATIVE / filename).read_bytes()).hexdigest() == origin["fixture_sha256"]
        authority["source"] = {"file": filename, "sha256": origin["fixture_sha256"]}
    return policy


def _decisions(filename, *, policy=None, native=None):
    """Run both production readers against a genuine or explicitly mutated offline snapshot."""
    policy = _policy() if policy is None else policy
    policy = finite.load_import_category_policy(io.StringIO(json.dumps(policy)))
    native = (NATIVE / filename).read_text() if native is None else native
    return finite.load_import_category_evidence(policy, filename, io.StringIO(native))


@pytest.fixture
def all_decisions():
    """Every selected import module supplies its own asserted evidence only."""
    return {
        identifier: evidence
        for filename in _policy()["authorities"]
        for identifier, evidence in _decisions(filename).items()
    }


@pytest.mark.parametrize("identifier", COHORT)
def test_every_finite_id_has_native_live_path_and_exact_category(identifier, all_decisions):
    """All eighty actual IDs are checked, not a representative namespace sample."""
    record = POLICY["records"][identifier]
    evidence = all_decisions[identifier]
    assert evidence.identifier == identifier
    assert evidence.category == record["category"]
    assert evidence.authority == record["authority_file"]
    assert evidence.authority_sha256 == ORIGIN["native_manifest"][evidence.authority]["fixture_sha256"]
    assert set(evidence.root_paths) == {tuple(path) for path in record["ancestor_paths"].values()}
    native = json.loads((NATIVE / evidence.authority).read_text())["graphs"][0]
    native_edges = {(edge["sub"], edge["pred"], edge["obj"]) for edge in native["edges"]}
    assert set(evidence.supporting_axioms) <= native_edges
    for previous in ("", "biolink:NamedThing", "biolink:OntologyClass", evidence.category + "|biolink:OntologyClass"):
        assert finite.apply_import_category(previous, evidence) == evidence.category
    assert finite.apply_import_category(evidence.category, evidence) == evidence.category


def test_exact_cohort_does_not_claim_model_conformance_or_chemical_equivalence(all_decisions):
    """Category semantics do not invent type slots, ChEBI mappings or graph-ID migrations."""
    assert Counter(e.category for e in all_decisions.values()) == {"biolink:PhysicalEntity": 78, "biolink:Attribute": 2}
    assert hashlib.sha256(("\n".join(COHORT) + "\n").encode()).hexdigest() == ORIGIN["finite_id_set_sha256"]
    assert set(i for i in COHORT if i.startswith("OBO:")) == {"OBO:COB_0000011", "OBO:COB_0000013", "OBO:COB_0000080"}
    schema_path = Path(__file__).parent / "resources/ingredient_bundle/native/biolink-model.yaml"
    assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == ORIGIN["model"]["sha256"]
    schema = yaml.safe_load(schema_path.read_text())
    assert schema["version"] == "4.4.2"
    assert "has attribute type" in schema["classes"]["attribute"]["slots"]
    assert schema["slots"]["has attribute type"]["required"] is True
    assert "mappings/finite_import_category_dispositions.json" in SHARED_DATA_INPUTS


def _authorities(tmp_path, monkeypatch):
    """Use the real upstream integration with an explicitly pinned fixture policy."""
    path = tmp_path / "import-policy.json"
    path.write_text(json.dumps(_policy()))
    monkeypatch.setattr(finite, "IMPORT_DISPOSITIONS_FILE", path)
    return path


@pytest.mark.parametrize(
    "control", ORIGIN["negative_controls"], ids=lambda value: value["authority_file"] + ":" + value["graph_id"]
)
def test_native_same_prefix_and_bare_controls_receive_no_finite_override(control, tmp_path, monkeypatch):
    """Thirteen native controls remain outside this policy even when they share a root."""
    policy_path = _authorities(tmp_path, monkeypatch)
    authority = finite.FiniteImportCategoryAuthority(NATIVE, opener=lambda path: path.open())
    assert authority.evidence_for(control["graph_id"]) is None
    assert authority.source_paths <= {policy_path}
    native = json.loads((NATIVE / control["authority_file"]).read_text())["graphs"][0]
    node = next(node for node in native["nodes"] if node["id"] == control["native_iri"])
    assert node.get("lbl", "") == control["native_label"]


def test_selected_pco_uses_pato_but_existing_population_still_uses_envo(tmp_path, monkeypatch):
    """Finite per-ID authority selection precedes, but does not replace, namespace policy."""
    policy_path = _authorities(tmp_path, monkeypatch)
    authority = OntologyCategoryAuthority(NATIVE)
    assert authority.evidence_for("PCO:0000003").category == "biolink:Attribute"
    assert authority.source_paths == {policy_path, NATIVE / "pato.json"}
    assert authority.evidence_for("PCO:0000001").category == "biolink:PopulationOfIndividualOrganisms"
    assert authority.source_paths == {policy_path, NATIVE / "pato.json", NATIVE / "envo.json"}
    assert authority.evidence_for("GAZ:00000462").category is None
    assert authority.evidence_for("OBO:COB_0000021").category is None


@pytest.mark.parametrize(
    "prior",
    [
        "biolink:ChemicalEntity",
        "biolink:ChemicalEntity|biolink:OntologyClass",
        "biolink:PopulationOfIndividualOrganisms",
        "biolink:AnatomicalEntity|biolink:NamedThing",
    ],
)
@pytest.mark.parametrize("identifier", ["PCO:0000003", "OBO:COB_0000011", "GAZ:00000458"])
def test_unexpected_substantive_categories_cannot_bypass_refusal(identifier, prior, tmp_path, monkeypatch):
    """Substantive-only input must not bypass checking merely by omitting OntologyClass."""
    _authorities(tmp_path, monkeypatch)
    authority = SourceCategoryAuthority(NATIVE, opener=lambda path: path.open())
    row = {"id": identifier, "category": prior, "name": "keep native label"}
    before = dict(row)
    with pytest.raises(ValueError, match="Unexpected substantive category"):
        authority.normalize(row)
    assert row == before


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "missing",
        "same_size_id",
        "wrong_file",
        "wrong_category",
        "wrong_iri",
        "wrong_hash",
        "missing_path",
        "duplicate",
        "truncated",
    ],
)
def test_incomplete_or_unreviewed_policy_refuses(change):
    """Neither record count nor a caller-controlled cohort digest authenticates replacements."""
    policy = _policy()
    record = policy["records"][COHORT[0]]
    if change == "empty":
        policy = {}
    elif change == "missing":
        policy["records"].pop(COHORT[0])
    elif change == "same_size_id":
        policy["records"]["GAZ:99999999"] = policy["records"].pop(COHORT[0])
        policy["finite_id_set_sha256"] = hashlib.sha256(
            ("\n".join(sorted(policy["records"])) + "\n").encode()
        ).hexdigest()
    elif change == "wrong_file":
        record["authority_file"] = "../pato.json"
    elif change == "wrong_category":
        record["category"] = "biolink:GeographicLocation"
    elif change == "wrong_iri":
        record["native_iri"] = "http://example.org/foreign"
    elif change == "wrong_hash":
        policy["authorities"]["foodon.json"]["decisions_sha256"] = ""
    elif change == "missing_path":
        record["ancestor_paths"].clear()
    text = json.dumps(policy)
    if change == "duplicate":
        text = text.replace('"version": 2', '"version": 2, "version": 2')
    elif change == "truncated":
        text = text[:-8]
    with pytest.raises(ValueError):
        finite.load_import_category_policy(io.StringIO(text))


def test_a_redundant_native_axiom_changes_the_reviewed_decisions():
    """With no byte pin left, the decisions digest alone catches an added axiom between reviewed classes (#1517)."""
    filename = "foodon.json"
    policy = _policy()
    native = json.loads((NATIVE / filename).read_text())
    graph = native["graphs"][0]
    identifier = sorted(key for key, record in policy["records"].items() if record["authority_file"] == filename)[0]
    iri = policy["records"][identifier]["native_iri"]
    direct = {edge["obj"] for edge in graph["edges"] if edge["sub"] == iri and edge["pred"] == "is_a"}
    target = next(
        ancestor
        for ancestor in sorted(policy["records"][identifier]["ancestor_paths"])
        if ancestor != iri and ancestor not in direct
    )
    graph["edges"].append({"sub": iri, "pred": "is_a", "obj": target})
    with pytest.raises(ValueError, match="Finite import decisions differ"):
        _decisions(filename, policy=policy, native=json.dumps(native))


@pytest.mark.parametrize(
    "change",
    [
        "label",
        "metadata",
        "missing",
        "property",
        "obsolete",
        "bad_obsolete",
        "conflicting_obsolete",
        "duplicate_node",
        "broken_path",
        "missing_ancestor",
        "obsolete_ancestor",
        "extra_parent",
        "wrong_graph",
    ],
)
def test_bad_native_snapshot_is_refused(change):
    """Live declared native identity, complete ancestry and the reviewed decisions are checked."""
    filename = "foodon.json"
    policy = _policy()
    native = json.loads((NATIVE / filename).read_text())
    graph = native["graphs"][0]
    record = policy["records"][COHORT[0]]
    node = next(node for node in graph["nodes"] if node["id"] == record["native_iri"])
    ancestor = next(node for node in graph["nodes"] if node["id"].endswith("BFO_0000040"))
    if change == "label":
        node["lbl"] = "different meaning"
    elif change == "metadata":
        node.setdefault("meta", {})["comment"] = "invented"
    elif change == "missing":
        graph["nodes"].remove(node)
    elif change == "property":
        node["type"] = "PROPERTY"
    elif change == "obsolete":
        node.setdefault("meta", {})["deprecated"] = True
    elif change == "bad_obsolete":
        node.setdefault("meta", {})["deprecated"] = "false"
    elif change == "conflicting_obsolete":
        node.setdefault("meta", {})["deprecated"] = False
        node["meta"].setdefault("basicPropertyValues", []).append({"pred": "owl:deprecated", "val": "true"})
    elif change == "duplicate_node":
        graph["nodes"].append(copy.deepcopy(node))
    elif change == "broken_path":
        graph["edges"] = [edge for edge in graph["edges"] if edge["sub"] != node["id"]]
    elif change == "missing_ancestor":
        graph["nodes"].remove(ancestor)
    elif change == "obsolete_ancestor":
        ancestor.setdefault("meta", {})["deprecated"] = True
    elif change == "extra_parent":
        graph["edges"].append({"sub": node["id"], "pred": "is_a", "obj": "http://purl.obolibrary.org/obo/BFO_0000003"})
        graph["nodes"].append({"id": "http://purl.obolibrary.org/obo/BFO_0000003", "type": "CLASS"})
    elif change == "wrong_graph":
        graph["id"] = "http://example.org/other.owl"
    with pytest.raises(ValueError):
        _decisions(filename, policy=policy, native=json.dumps(native))


def test_reserialized_converted_json_keeps_the_reviewed_decisions():
    """A different serialization of the same reviewed content is accepted; a whole-file pin refused it (#1420)."""
    filename = "foodon.json"
    original = _decisions(filename)
    reserialized = json.dumps(json.loads((NATIVE / filename).read_text()), indent=4, sort_keys=True)
    assert reserialized != (NATIVE / filename).read_text()
    assert _decisions(filename, native=reserialized) == original


def _release_bound(tmp_path, release):
    """Stage the FOODON excerpt with an OWL release file beside it, bound the production way."""
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copyfile(NATIVE / "foodon.json", raw / "foodon.json")
    policy = _policy()
    owl = b'<?xml version="1.0"?>\n<!-- stand-in for the pinned foodon.owl release -->\n'
    policy["authorities"]["foodon.json"]["source"] = {"file": "foodon.owl", "sha256": hashlib.sha256(owl).hexdigest()}
    if release is not None:
        (raw / "foodon.owl").write_bytes(owl if release == "pinned" else owl + b"<!-- another release -->\n")
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    opened = []

    def opener(target):
        """Serve the rebound fixture policy and record every consumed input."""
        opened.append(Path(target).name)
        return (path if Path(target) == finite.IMPORT_DISPOSITIONS_FILE else Path(target)).open(encoding="utf-8")

    return finite.FiniteImportCategoryAuthority(raw, opener=opener), opened


def test_the_owl_release_file_is_read_and_bound(tmp_path):
    """The release file the JSON was converted from is read as a consumed input and must match."""
    authority, opened = _release_bound(tmp_path, "pinned")
    assert authority.evidence_for(COHORT[0]).category == finite.PHYSICAL_ENTITY_CATEGORY
    assert opened[-2:] == ["foodon.json", "foodon.owl"]


@pytest.mark.parametrize("release", ["changed", None], ids=["changed", "missing"])
def test_a_different_or_missing_owl_release_is_refused(tmp_path, release):
    """Reviewed decisions in the JSON cannot stand in for an unreviewed release file."""
    authority, _ = _release_bound(tmp_path, release)
    with pytest.raises((ValueError, FileNotFoundError)):
        authority.evidence_for(COHORT[0])


def test_rewritten_policy_paths_cannot_authenticate_material_quality_conflict():
    """Even mutually restamped test evidence cannot make a material also a quality."""
    policy = _policy()
    filename = "uberon.json"
    native = json.loads((NATIVE / filename).read_text())
    graph = native["graphs"][0]
    root = "http://purl.obolibrary.org/obo/PATO_0000001"
    graph["nodes"].append({"id": root, "type": "CLASS"})
    for record in policy["records"].values():
        if record["authority_file"] == filename:
            graph["edges"].append({"sub": record["native_iri"], "pred": "is_a", "obj": root})
            record["ancestor_paths"][root] = [record["native_iri"], root]
    with pytest.raises(ValueError, match="Contradictory"):
        _decisions(filename, policy=policy, native=json.dumps(native))


def _source(tmp_path, monkeypatch, provider):
    """Build a real producer using all eighty selected imports and one unrelated node."""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    for filename in POLICY["authorities"]:
        (raw / filename).write_bytes((NATIVE / filename).read_bytes())
    policy_path = _authorities(tmp_path, monkeypatch)
    producer = Transform("fixture", raw, tmp_path / "transformed")
    with producer.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["id", "category", "name", "description", "provided_by"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for identifier, record in POLICY["records"].items():
            writer.writerow(
                {
                    "id": identifier,
                    "category": "biolink:OntologyClass",
                    "name": record["native_label"],
                    "description": "Keep source description",
                    "provided_by": provider,
                }
            )
        writer.writerow(
            {"id": "fixture:1", "category": "biolink:NamedThing", "name": "unrelated", "provided_by": provider}
        )
    producer.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        + "".join(f"{identifier}\tbiolink:related_to\tfixture:1\tskos:related\t{provider}\n" for identifier in COHORT)
    )
    return producer, policy_path


@pytest.mark.parametrize("provider", ["infores:foodon", "infores:uberon", "infores:pato"])
def test_all_importer_copies_converge_with_bound_evidence_and_unchanged_assertions(tmp_path, monkeypatch, provider):
    """Every category edit is upstream and audited, and no noncategory meaning is rewritten."""
    producer, policy_path = _source(tmp_path, monkeypatch, provider)
    before_nodes = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    before_edges = list(graph_rows(producer.output_edge_file))
    report = producer.finalize()
    after_nodes = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    after_edges = list(graph_rows(producer.output_edge_file))
    assert before_nodes.keys() == after_nodes.keys()
    for identifier, row in before_nodes.items():
        assert {key: after_nodes[identifier][key] for key in row if key != "category"} == {
            key: value for key, value in row.items() if key != "category"
        }
        assert after_nodes[identifier]["category"] == (
            POLICY["records"][identifier]["category"] if identifier in COHORT else row["category"]
        )
    assert [{key: row[key] for key in before_edges[0]} for row in after_edges] == before_edges
    audits = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    category_audits = [row for row in audits if json.loads(row["original_row_json"]).get("id") in COHORT]
    assert len(category_audits) == 80
    for row in category_audits:
        assert json.loads(row["original_row_json"])["category"] == "biolink:OntologyClass"
        updated = json.loads(row["normalized_row_json"])
        assert updated["category"] == POLICY["records"][updated["id"]]["category"]
    assert {Path(record["path"]).name for record in report["consumed_inputs"].values()} == {
        policy_path.name,
        *POLICY["authorities"],
    }
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    policy_path.write_text(policy_path.read_text() + " ")
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


@pytest.mark.parametrize("change", ["native", "policy", "callback_failure"])
def test_native_or_policy_change_during_finalization_never_publishes_partial_categories(tmp_path, monkeypatch, change):
    """Every source snapshot is rechecked at publication, even after a successful classification."""
    producer, policy_path = _source(tmp_path, monkeypatch, "infores:foodon")
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    original = finite.load_import_category_evidence

    def mutate_after_read(policy, filename, stream):
        """Change a backing file only after the classifier consumes its immutable snapshot."""
        decisions = original(policy, filename, stream)
        if change == "callback_failure":
            raise ValueError("deliberate evidence callback failure")
        path = policy_path if change == "policy" else producer.input_base_dir / filename
        path.write_text(path.read_text() + " ")
        return decisions

    monkeypatch.setattr(finite, "load_import_category_evidence", mutate_after_read)
    with pytest.raises((SourceFinalizationRequired, ValueError)):
        producer.finalize()
    assert (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()) == before
    assert not (producer.output_dir / "source_finalization.json").exists()


def test_unrelated_ids_consult_no_new_authorities(tmp_path):
    """Lazy finite routing cannot add missing-file dependencies to unrelated producers."""
    calls = []

    def refuse(path):
        """Refuse any new policy or native file dependency for an unrelated ID."""
        calls.append(path)
        raise AssertionError(path)

    authority = SourceCategoryAuthority(tmp_path, opener=refuse)
    for identifier in ("fixture:1", "mesh:D999999", "CLM:1000041", "OBO:COB_0000021"):
        row = {"id": identifier, "category": "biolink:OntologyClass", "name": "unchanged"}
        before = dict(row)
        authority.normalize(row)
        assert row == before
    assert calls == []


def test_category_normalization_also_covers_declarations_added_during_closure(tmp_path, monkeypatch):
    """A controlled closure-added copy passes the same final upstream policy and audit."""
    from kg_microbe.merge_utils import external_node_closure

    producer, _ = _source(tmp_path, monkeypatch, "infores:pato")
    missing = "PCO:0000003"
    nodes = list(graph_rows(producer.output_node_file))
    declaration = next(row for row in nodes if row["id"] == missing)
    with producer.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(declaration), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(row for row in nodes if row["id"] != missing)
    original = external_node_closure.resolve_external_reference_bundle

    def closure_with_import(node_paths, *args, **kwargs):
        """Simulate an additional generic imported declaration, not a new resolver authority."""
        result = original(node_paths, *args, **kwargs)
        with node_paths[0].open() as stream:
            header = next(csv.reader(stream, delimiter="\t"))
        with node_paths[0].open("a", newline="") as stream:
            csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n").writerow(declaration)
        return result

    monkeypatch.setattr(external_node_closure, "resolve_external_reference_bundle", closure_with_import)
    producer.finalize()
    final = {row["id"]: row for row in graph_rows(producer.output_node_file)}
    assert final[missing]["category"] == "biolink:Attribute"
    assert len(final) == 81
    audits = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    corrected = [row for row in audits if json.loads(row["original_row_json"]).get("id") == missing]
    assert len(corrected) == 1
    assert json.loads(corrected[0]["normalized_row_json"])["category"] == "biolink:Attribute"


def test_repeated_finalization_is_stable_and_new_run_rechecks_evidence(tmp_path, monkeypatch):
    """No process-global category cache can certify a later run with changed source bytes."""
    producer, _ = _source(tmp_path, monkeypatch, "infores:foodon")
    producer.finalize()
    expected = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    producer.finalize()
    assert (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()) == expected
    path = producer.input_base_dir / "foodon.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="Unreviewed release file"):
        SourceCategoryAuthority(producer.input_base_dir, opener=lambda path: path.open()).normalize(
            {"id": COHORT[0], "category": "biolink:OntologyClass"}
        )
