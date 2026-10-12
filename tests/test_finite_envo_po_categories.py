"""Three definition-backed ENVO/PO decisions are finite, native-bound and upstream only."""

import copy
import csv
import io
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from lxml import etree

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import finite_envo_po_categories as finite
from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files

FIXTURE = Path(__file__).parent / "resources/finite_envo_po"
ORIGIN = json.loads((FIXTURE / "origin.json").read_text())
POLICY = json.loads(finite.POLICY_FILE.read_text())
COHORT = sorted(POLICY["records"])


def prepare(tmp_path, monkeypatch):
    """Explicitly repin separately identified native excerpts, never claim full-source byte identity."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    policy = copy.deepcopy(POLICY)
    for filename, contract in policy["authorities"].items():
        origin = ORIGIN["native_files"][filename]
        assert contract["sha256"] == origin["full_source_sha256"]
        assert finite.digest((FIXTURE / filename).read_bytes()) == origin["fixture_sha256"]
        assert contract["evidence_sha256"] == origin["evidence_sha256"]
        contract["sha256"] = origin["fixture_sha256"]
        shutil.copyfile(FIXTURE / filename, raw / filename)
    path = tmp_path / "finite_envo_po_category_dispositions.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_FILE", path)
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    return raw, path, policy


@pytest.mark.parametrize("identifier", COHORT)
def test_all_three_decisions_retain_complete_native_witness_and_scientific_limits(tmp_path, monkeypatch, identifier):
    """The reviewed definitions support categories without inventing an asserted process-root path."""
    raw, path, policy = prepare(tmp_path, monkeypatch)
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    evidence = authority.evidence_for(identifier)
    record = policy["records"][identifier]
    assert evidence.category == record["category"]
    assert evidence.disposition == record["disposition"]
    assert json.loads(evidence.decision_json) == record
    assert json.loads(evidence.native_witness_json) == ORIGIN["selected_native_evidence"][evidence.authority_file]
    assert authority.source_paths == {path, raw / record["authority"]}
    if identifier.startswith("ENVO:"):
        parents = json.loads(evidence.native_witness_json)["named_parents"]
        assert parents["ENVO:01001436"] == ["BFO:0000003", "OBI:0000011"]
        assert "OBI:0000011" not in record["named_path"]
        assert "ENVO:02500000" not in parents
    else:
        assert ["RO:0000057", "PO:0000003"] in json.loads(evidence.native_witness_json)["restrictions"][identifier]
    for category in ("", "biolink:NamedThing", "biolink:OntologyClass", evidence.category + "|biolink:OntologyClass"):
        assert finite.apply_finite_category(category, evidence) == evidence.category
    assert finite.apply_finite_category(evidence.category, evidence) == evidence.category


def test_native_files_are_lazy_and_one_envo_read_covers_both_finite_decisions(tmp_path, monkeypatch):
    """No unnecessary PO load, repeated graph parse, or ancestor propagation is introduced."""
    raw, path, _ = prepare(tmp_path, monkeypatch)
    calls = []

    def opener(selected):
        """Record authority reads while returning the actual selected file."""
        calls.append(selected)
        return selected.open()

    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=opener)
    for identifier in ("BFO:0000003", "ENVO:01000906", "ENVO:01001436", "PO:0009012", "PO:0025423", "PO:0009005"):
        assert authority.evidence_for(identifier) is None
    assert not calls
    for identifier in ("ENVO:01001254", "ENVO:01001255", "ENVO:01001254"):
        assert authority.evidence_for(identifier).identifier == identifier
    assert calls == [path, raw / "envo.json"]
    assert authority.evidence_for("http://purl.obolibrary.org/obo/PO_0007033").identifier == "PO:0007033"
    assert calls == [path, raw / "envo.json", raw / "po.owl"]


@pytest.mark.parametrize(
    "category", ["biolink:Activity", "biolink:AnatomicalEntity", "biolink:Food", "biolink:ChemicalEntity"]
)
@pytest.mark.parametrize("identifier", COHORT)
def test_conflicting_substantive_categories_refuse_instead_of_accumulating(tmp_path, monkeypatch, identifier, category):
    """A generic suffix never authorizes replacement of an unexplained substantive category."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    authority = SourceCategoryAuthority(raw, opener=lambda p: p.open())
    row = {"id": identifier, "category": category + "|biolink:OntologyClass", "name": "Keep source label"}
    original = dict(row)
    with pytest.raises(ValueError, match="Unexpected substantive category"):
        authority.normalize(row)
    assert row == original


@pytest.mark.parametrize(
    "identifier", ["ENVO:01001023", "ENVO:01001247", "ENVO:01001248", "ENVO:02500030", "ENVO:03000091", "ENVO:03000094"]
)
def test_existing_six_envo_ancestry_classifications_are_not_changed(identifier):
    """Existing asserted-root decisions stay distinct from the new definition-backed finite exceptions."""
    authority = OntologyCategoryAuthority(FIXTURE)
    assert authority.category_for(identifier) == "biolink:EnvironmentalProcess"


@pytest.mark.parametrize("damage", ["missing", "extra", "category", "route", "authority", "witness", "definition"])
def test_changed_or_incomplete_policy_is_not_self_authenticating(damage):
    """A revised receipt cannot silently revise a reviewed category or native evidence pin."""
    policy = copy.deepcopy(POLICY)
    record = policy["records"][COHORT[0]]
    if damage == "missing":
        policy["records"].pop(COHORT[0])
    elif damage == "extra":
        policy["records"]["ENVO:99999999"] = record
    elif damage == "category":
        record["category"] = "biolink:Activity"
    elif damage == "route":
        record["authority"] = "po.owl"
    elif damage == "authority":
        policy["authorities"]["envo.json"]["sha256"] = "a" * 64
    elif damage == "witness":
        policy["authorities"]["envo.json"]["evidence_sha256"] = "a" * 64
    else:
        record["native_definition"] = "unsupported replacement"
    with pytest.raises(ValueError, match="Unreviewed"):
        finite.load_policy(io.StringIO(json.dumps(policy)))


def test_duplicate_policy_key_refuses():
    """JSON parser ambiguity must not be resolved by last-key-wins behavior."""
    with pytest.raises(ValueError, match="Duplicate"):
        finite.load_policy(io.StringIO('{"records":{},"records":{}}'))


def repin_native_fixture(path, policy_path, policy, monkeypatch):
    """Permit a deliberate negative excerpt byte change but keep its reviewed semantic witness fixed."""
    policy["authorities"][path.name]["sha256"] = finite.digest(path.read_bytes())
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))


@pytest.mark.parametrize(
    "damage", ["version", "ontology", "missing", "duplicate", "deprecated", "kind", "label", "definition", "parent"]
)
def test_envo_native_identity_and_complete_selected_evidence_refuse_drift(tmp_path, monkeypatch, damage):
    """Even deliberate fixture byte repinning does not authorize scientific evidence drift."""
    raw, policy_path, policy = prepare(tmp_path, monkeypatch)
    path = raw / "envo.json"
    data = json.loads(path.read_text())
    graph = data["graphs"][0]
    node = next(n for n in graph["nodes"] if n["id"].endswith("ENVO_01001254"))
    if damage == "version":
        graph["meta"]["version"] = "foreign-version"
    elif damage == "ontology":
        graph["id"] = "foreign-ontology"
    elif damage == "missing":
        graph["nodes"].remove(node)
    elif damage == "duplicate":
        graph["nodes"].append(copy.deepcopy(node))
    elif damage == "deprecated":
        node["meta"]["deprecated"] = True
    elif damage == "kind":
        node["type"] = "PROPERTY"
    elif damage == "label":
        node["lbl"] = "foreign label"
    elif damage == "definition":
        node["meta"]["definition"]["val"] = "foreign definition"
    else:
        edge = next(e for e in graph["edges"] if e["sub"] == node["id"] and e["pred"] == "is_a")
        edge["obj"] = "http://purl.obolibrary.org/obo/BFO_0000040"
    path.write_text(json.dumps(data))
    repin_native_fixture(path, policy_path, policy, monkeypatch)
    with pytest.raises(ValueError, match="Finite ENVO"):
        finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for(COHORT[0])


@pytest.mark.parametrize(
    "damage",
    [
        "version",
        "ontology",
        "missing",
        "duplicate",
        "deprecated",
        "kind",
        "label",
        "definition",
        "parent",
        "participant",
    ],
)
def test_po_native_declarations_and_whole_plant_participation_refuse_drift(tmp_path, monkeypatch, damage):
    """LifeStage depends on the actual whole-plant restriction, not simply the word stage."""
    raw, policy_path, policy = prepare(tmp_path, monkeypatch)
    path = raw / "po.owl"
    tree = etree.parse(str(path))
    node = next(n for n in tree.iter(finite._OWL + "Class") if n.get(finite._RDF + "about", "").endswith("PO_0007033"))
    ontology = next(tree.iter(finite._OWL + "Ontology"))
    if damage == "version":
        ontology.find(finite._OWL + "versionIRI").set(finite._RDF + "resource", "foreign-version")
    elif damage == "ontology":
        ontology.set(finite._RDF + "about", "foreign-ontology")
    elif damage == "missing":
        node.getparent().remove(node)
    elif damage == "duplicate":
        node.getparent().append(copy.deepcopy(node))
    elif damage == "deprecated":
        etree.SubElement(node, finite._OWL + "deprecated").text = "true"
    elif damage == "kind":
        node.tag = finite._OWL + "ObjectProperty"
    elif damage == "label":
        node.find(finite._RDFS + "label").text = "foreign label"
    elif damage == "definition":
        node.find("{http://purl.obolibrary.org/obo/}IAO_0000115").text = "foreign definition"
    elif damage == "parent":
        next(n for n in node.findall(finite._RDFS + "subClassOf") if n.get(finite._RDF + "resource")).set(
            finite._RDF + "resource", "http://purl.obolibrary.org/obo/PO_0009005"
        )
    else:
        next(node.iter(finite._OWL + "someValuesFrom")).set(
            finite._RDF + "resource", "http://purl.obolibrary.org/obo/PO_0009005"
        )
    path.write_bytes(etree.tostring(tree))
    repin_native_fixture(path, policy_path, policy, monkeypatch)
    with pytest.raises(ValueError, match="Finite (PO|ENVO/PO)"):
        finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for("PO:0007033")


@pytest.mark.parametrize(
    "field", ["category", "disposition", "authority_file", "authority_sha256", "native_witness_json", "decision_json"]
)
def test_cached_witness_or_decision_cannot_drift_after_native_read(tmp_path, monkeypatch, field):
    """Seal complete parsed payloads, not only an unchanged archive or policy receipt."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    evidence = authority.evidence_for(COHORT[0])
    authority._decisions[COHORT[0]] = replace(evidence, **{field: "altered"})
    with pytest.raises(ValueError, match="cached decision"):
        authority.evidence_for(COHORT[0])


def source(tmp_path, monkeypatch, provider):
    """Import all three IDs through real finalization, without relying on namespace defaults."""
    raw, path, _ = prepare(tmp_path, monkeypatch)
    producer = Transform("fixture", raw, tmp_path / "transformed")
    producer.output_node_file.write_text(
        "id\tcategory\tname\tdescription\tprovided_by\n"
        + "".join(f"{i}\tbiolink:OntologyClass\tKept label\tKept description\t{provider}\n" for i in COHORT)
        + f"fixture:1\tbiolink:NamedThing\tControl\tKept\t{provider}\n"
    )
    producer.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\tpublications\n"
        + "".join(
            f"{i}\tbiolink:related_to\tfixture:1\tskos:related\t{provider}\tknowledge_assertion\tmanual_agent\t\n"
            for i in COHORT
        )
    )
    return producer, path


@pytest.mark.parametrize("provider", ["infores:envo", "infores:foodon", "infores:other-importer"])
def test_actual_finalization_importers_converge_without_edge_or_other_node_edits(tmp_path, monkeypatch, provider):
    """Consumed inputs, full old/new audits and repeat/admission guards are exercised together."""
    producer, path = source(tmp_path, monkeypatch, provider)
    previous_nodes = list(graph_rows(producer.output_node_file))
    previous_edges = list(graph_rows(producer.output_edge_file))
    report = producer.finalize()
    nodes = list(graph_rows(producer.output_node_file))
    assert list(graph_rows(producer.output_edge_file)) == previous_edges
    for previous, row in zip(previous_nodes, nodes, strict=True):
        assert {k: row[k] for k in previous if k != "category"} == {
            k: v for k, v in previous.items() if k != "category"
        }
        assert row["category"] == POLICY["records"].get(row["id"], {}).get("category", previous["category"])
    assert set(report["consumed_inputs"]) == {
        "category_authority_finite_envo_po_category_dispositions",
        "category_authority_envo",
        "category_authority_po_owl",
    }
    audit = list(graph_rows(producer.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    changes = [r for r in audit if json.loads(r["original_row_json"]).get("id") in COHORT]
    assert len(changes) == 3
    assert all(json.loads(r["original_row_json"])["category"] == "biolink:OntologyClass" for r in changes)
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    producer.finalize()
    assert before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())
    path.write_text(path.read_text() + " ")
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


@pytest.mark.parametrize("filename", ["envo.json", "po.owl"])
def test_native_byte_change_before_first_use_preserves_unfinalized_outputs(tmp_path, monkeypatch, filename):
    """No category publication is possible after the native authority becomes unreviewed."""
    producer, _ = source(tmp_path, monkeypatch, "infores:envo")
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    path = producer.input_base_dir / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="native bytes changed"):
        producer.finalize()
    assert before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())
    assert not (producer.output_dir / "source_finalization.json").exists()


def test_changed_original_after_snapshot_read_refuses_with_restored_size_and_mtime(tmp_path, monkeypatch):
    """Immutable parsed evidence is not confused with a subsequently changed selected raw file."""
    producer, _ = source(tmp_path, monkeypatch, "infores:envo")
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    original = finite._json_evidence

    def mutate_after_read(content, contract):
        """Alter the original authority after parsing to exercise late-drift refusal."""
        witness = original(content, contract)
        path = producer.input_base_dir / "envo.json"
        stat = path.stat()
        payload = path.read_bytes().replace(b"animal aquaculture", b"xxxxxx aquaculture", 1)
        assert len(payload) == stat.st_size
        path.write_bytes(payload)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return witness

    monkeypatch.setattr(finite, "_json_evidence", mutate_after_read)
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        producer.finalize()
    assert before == (producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes())


def test_cached_policy_cannot_be_replaced(tmp_path, monkeypatch):
    """Policy payload mutation between two uses is not hidden by previously valid input pins."""
    raw, _, _ = prepare(tmp_path, monkeypatch)
    authority = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open())
    authority.evidence_for(COHORT[0])
    authority._policy_json = "{}"
    with pytest.raises(ValueError, match="cached policy"):
        authority.evidence_for(COHORT[1])


def test_native_owl_comments_and_anonymous_structures_do_not_become_declarations(tmp_path, monkeypatch):
    """Accept production-style XML comments without dropping any selected class witness."""
    raw, path, policy = prepare(tmp_path, monkeypatch)
    native = raw / "po.owl"
    tree = etree.parse(str(native))
    root = tree.getroot()
    root.insert(0, etree.Comment(" http://purl.obolibrary.org/obo/PO_0007033 "))
    root.insert(1, etree.ProcessingInstruction("native-processing", "not-a-class"))
    root.append(etree.Comment(" Generated by the OWL API (version 4.5.29) "))
    etree.SubElement(root, finite._OWL + "Axiom")
    etree.SubElement(
        root,
        finite._RDF + "Description",
        {finite._RDF + "about": "http://purl.obolibrary.org/obo/PO_0009011"},
    )
    native.write_bytes(etree.tostring(tree))
    repin_native_fixture(native, path, policy, monkeypatch)
    evidence = finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for("PO:0007033")
    assert evidence.category == "biolink:LifeStage"
    assert json.loads(evidence.native_witness_json) == ORIGIN["selected_native_evidence"]["po.owl"]


def test_nonempty_rdf_description_cannot_hide_additional_selected_class_triples(tmp_path, monkeypatch):
    """Only triple-free named references may be ignored; added selected assertions must fail."""
    raw, path, policy = prepare(tmp_path, monkeypatch)
    native = raw / "po.owl"
    tree = etree.parse(str(native))
    description = etree.SubElement(
        tree.getroot(),
        finite._RDF + "Description",
        {finite._RDF + "about": "http://purl.obolibrary.org/obo/PO_0009011"},
    )
    etree.SubElement(
        description, finite._RDF + "type", {finite._RDF + "resource": finite._OWL[1:-1] + "ObjectProperty"}
    )
    native.write_bytes(etree.tostring(tree))
    repin_native_fixture(native, path, policy, monkeypatch)
    with pytest.raises(ValueError, match="nonclass declaration"):
        finite.FiniteEnvoPoCategoryAuthority(raw, opener=lambda p: p.open()).evidence_for("PO:0007033")


ROLES = [finite.POLICY_ROLE, "category_authority_envo", "category_authority_po_owl"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("damage", ["delete", "rebind"])
def test_live_original_named_roles_cannot_disappear_or_change(tmp_path, monkeypatch, role, damage):
    """Current-path hashes alone do not prove that the intended authority reader consumed them."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    producer.finalize()
    if damage == "delete":
        producer._consumed_input_snapshots.pop(role)
    else:
        alternate = next(value for key, value in producer._consumed_input_snapshots.items() if key != role)
        producer._consumed_input_snapshots[role] = dict(alternate)
    with pytest.raises(ValueError, match="consumed-input binding"):
        producer.verify_consumed_inputs()


@pytest.mark.parametrize("damage", [*ROLES, "rebind", "whole_contract", "zero_contract", "identifiers", "counts"])
def test_recorded_admission_rejoins_roles_and_actual_output_cohort(tmp_path, monkeypatch, damage):
    """Deleting a complete contract cannot hide finite target nodes still present in actual graph members."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    producer.finalize()
    path = producer.output_dir / "source_finalization.json"
    report = json.loads(path.read_text())
    if damage in ROLES:
        report["consumed_inputs"].pop(damage)
    elif damage == "rebind":
        report["consumed_inputs"][finite.POLICY_ROLE] = report["consumed_inputs"]["category_authority_envo"]
    elif damage == "whole_contract":
        report.pop(finite.CONTRACT_KEY)
        for role in ROLES:
            report["consumed_inputs"].pop(role)
    elif damage == "zero_contract":
        report[finite.CONTRACT_KEY] = {
            "version": 1,
            "identifiers": [],
            "node_members": ["nodes.tsv"],
            "occurrences": {},
            "bindings": {},
        }
        for role in ROLES:
            report["consumed_inputs"].pop(role)
    elif damage == "identifiers":
        report[finite.CONTRACT_KEY]["identifiers"].pop()
    else:
        report[finite.CONTRACT_KEY]["occurrences"][COHORT[0]] += 1
    path.write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="finite ENVO/PO"):
        verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


def test_actual_non_target_bundle_has_explicit_zero_contract_without_authority_reads(tmp_path, monkeypatch):
    """A genuine no-eligible-cohort source needs no ENVO/PO bytes, while still sealing its zero inventory."""
    raw = tmp_path / "raw"
    raw.mkdir()
    producer = Transform("fixture", raw, tmp_path / "transformed")
    producer.output_node_file.write_text(
        "id\tcategory\tname\tprovided_by\nfixture:1\tbiolink:NamedThing\tControl\tinfores:fixture\n"
    )
    producer.output_edge_file.write_text("subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n")
    report = producer.finalize()
    assert report[finite.CONTRACT_KEY] == {
        "version": 1,
        "identifiers": [],
        "node_members": ["nodes.tsv"],
        "occurrences": {},
        "bindings": {},
    }
    assert not (set(ROLES) & report["consumed_inputs"].keys())
    verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])


def test_fresh_instance_repeat_restores_live_bindings_instead_of_only_receipt_hashes(tmp_path, monkeypatch):
    """Exact repeat remains byte-idempotent and retains original role checks on the new producer object."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    producer.finalize()
    before = producer.output_node_file.read_bytes(), producer.output_edge_file.read_bytes()
    fresh = Transform("fixture", producer.input_base_dir, producer.output_base_dir)
    fresh.finalize()
    assert before == (fresh.output_node_file.read_bytes(), fresh.output_edge_file.read_bytes())
    fresh._consumed_input_snapshots.pop(finite.POLICY_ROLE)
    with pytest.raises(ValueError, match="consumed-input binding"):
        fresh.verify_consumed_inputs()


def test_original_locator_rebinding_refuses_even_with_same_pinned_bytes(tmp_path, monkeypatch):
    """The old resolved file remaining intact does not authorize silently changing the selected raw locator."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    original = producer.input_base_dir / "envo.json"
    target = producer.input_base_dir / "native-a.json"
    original.rename(target)
    original.symlink_to(target)
    producer.finalize()
    alternate = producer.input_base_dir / "native-b.json"
    shutil.copyfile(target, alternate)
    original.unlink()
    original.symlink_to(alternate)
    with pytest.raises(ValueError, match="locator changed"):
        producer.verify_consumed_inputs()


def test_admission_retains_late_native_change_guard(tmp_path, monkeypatch):
    """A returned admission guard remains sensitive to native changes after finite verification."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    report = producer.finalize()
    guard = finite.verify_recorded_inputs(report, producer.output_dir / "source_finalization.json")
    path = producer.input_base_dir / "po.owl"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        guard.verify()


def test_source_counts_and_categories_remain_bound_until_publication(tmp_path, monkeypatch):
    """The live checkpoint checks multiplicity as well as unique IDs after staged output is sealed."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    producer.finalize()
    guard = producer._finite_envo_po_category_guard
    lines = producer.output_node_file.read_text().splitlines(keepends=True)
    producer.output_node_file.write_text("".join([*lines, lines[1]]))
    with pytest.raises(ValueError, match="occurrence counts"):
        guard.verify(producer.consumed_input_snapshots, output_dir=producer.output_dir)


def test_scoped_repeat_and_late_checks_ignore_other_members_without_ignoring_selected_drift(tmp_path, monkeypatch):
    """Unrelated side-by-side supplier files are not part of a selected-prefix completion contract."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    node = producer.output_dir / "selected_nodes.tsv"
    edge = producer.output_dir / "selected_edges.tsv"
    producer.output_node_file.rename(node)
    producer.output_edge_file.rename(edge)
    report = producer.finalize(file_prefix="selected_")
    assert report[finite.CONTRACT_KEY]["node_members"] == [node.name]
    before = node.read_bytes(), edge.read_bytes()
    shutil.copyfile(node, producer.output_dir / "other_nodes.tsv")
    shutil.copyfile(edge, producer.output_dir / "other_edges.tsv")
    fresh = Transform("fixture", producer.input_base_dir, producer.output_base_dir)
    repeated = fresh.finalize(file_prefix="selected_")
    assert repeated[finite.CONTRACT_KEY] == report[finite.CONTRACT_KEY]
    assert before == (node.read_bytes(), edge.read_bytes())
    guard = fresh._finite_envo_po_category_guard
    guard.verify(fresh.consumed_input_snapshots, output_dir=fresh.output_dir)
    lines = node.read_text().splitlines(keepends=True)
    node.write_text("".join([*lines, lines[1]]))
    with pytest.raises(ValueError, match="occurrence counts"):
        guard.verify(fresh.consumed_input_snapshots, output_dir=fresh.output_dir)


@pytest.mark.parametrize("damage", ["delete_member", "replace_member", "extra_member"])
def test_recorded_node_member_scope_cannot_be_redefined(tmp_path, monkeypatch, damage):
    """Exact admitted members are mandatory even when copied files contain identical finite identifiers."""
    producer, _ = source(tmp_path, monkeypatch, "infores:fixture")
    report = producer.finalize()
    path = producer.output_dir / "source_finalization.json"
    shutil.copyfile(producer.output_node_file, producer.output_dir / "other_nodes.tsv")
    if damage == "delete_member":
        report[finite.CONTRACT_KEY]["node_members"] = []
    elif damage == "replace_member":
        report[finite.CONTRACT_KEY]["node_members"] = ["other_nodes.tsv"]
    else:
        report[finite.CONTRACT_KEY]["node_members"].append("other_nodes.tsv")
    with pytest.raises(SourceFinalizationRequired, match="finite ENVO/PO"):
        finite.verify_recorded_inputs(report, path)
