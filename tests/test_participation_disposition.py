"""Finite native participation evidence; no runtime/schema validation waiver."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

RESOURCE = Path(__file__).parent / "resources/participation_disposition"
OBO = "http://purl.obolibrary.org/obo/"
OWL = "{http://www.w3.org/2002/07/owl#}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
KEEP = "retain_native_ontology_projection"


def load(name):
    """Read a checked-in finite fixture, never the selected production raw tree."""
    return json.loads((RESOURCE / name).read_text())


def curie(value):
    """Compact only the exact OBO IRI convention used in the native excerpts."""
    return value.removeprefix(OBO).replace("_", ":", 1) if value.startswith(OBO) else value


def path_reaches(subject, target, witnesses):
    """Check this ordered native witness, not an arbitrary category-based inference."""
    for witness in witnesses:
        edge = witness["edge"]
        if curie(edge["sub"]) != subject or edge["pred"] != "subPropertyOf":
            return False
        subject = curie(edge["obj"])
    return subject == target


def assert_property_path(relation, properties):
    """Require the ordered path and declarations to belong to their native supplier excerpt."""
    evidence = properties["native_property_paths"][relation]
    native = properties["native_property_excerpt"][evidence["supplier"]]
    assert evidence["declarations"]
    for declaration in evidence["declarations"]:
        assert declaration in native["nodes"]
        assert curie(declaration["declaration"]["id"]) == relation
        assert declaration["declaration"]["type"] == "PROPERTY"
    assert all(witness in native["edges"] for witness in evidence["path"])
    assert path_reaches(relation, evidence["target"], evidence["path"])


def assert_claim_joins(claims, properties):
    """Join original evidence to each historical projection, never just its receipt."""
    paths = properties["native_property_paths"]
    slots = properties["pinned_model"]["slots"]
    for row in claims:
        subject, relation, obj = row["original_native_triple"]
        historical = row["historical_nonempty_fields"]
        evidence = paths[relation]
        assert_property_path(relation, properties)
        slot_name = "participates in" if evidence["target"] == "RO:0000056" else "has participant"
        slot = slots[slot_name]
        assert evidence["target"] in slot["exact_mappings"]
        strength = "exact" if relation == evidence["target"] else "generalization"
        assert row["mapping_strength"] == evidence["mapping_strength"] == strength
        assert relation in slot["exact_mappings" if strength == "exact" else "narrow_mappings"]
        predicate = "biolink:" + slot_name.replace(" ", "_")
        assert row["projected_predicate"] == historical["predicate"] == predicate
        assert historical["object"] == obj
        assert historical["relation"] == relation
        assert historical["primary_knowledge_source"] == "infores:" + row["supplier"]
        if row["disposition"] == KEEP:
            assert historical["subject"] == subject
        else:
            assert row["disposition"] == "separate_GO_subject_quarantine_1302"
            assert (subject, relation, obj) in {
                ("GO:0006082", "RO:0004007", "CHEBI:64709"),
                ("GO:0043603", "RO:0004007", "CHEBI:32988"),
            }
            assert row["supplier"] == "pato"
            assert historical["original_subject"] == subject
            assert historical["subject"] == "GO:0008152"
            context = json.loads(historical["go_reference_context"])
            assert len(context) == 1
            assert context[0]["column"] == "subject"
            assert context[0]["original_id"] == subject
            assert context[0]["canonical_id"] == historical["subject"]
            assert context[0]["replacement_chain"] == [subject, historical["subject"]]
        assert set(row["native_endpoint_declarations"]) == {subject, obj}
        for identifier, declarations in row["native_endpoint_declarations"].items():
            assert declarations
            assert all(curie(item["declaration"]["id"]) == identifier for item in declarations)


def parsed_restrictions(declaration):
    """Reparse finite complete XML and linked blank nodes independently of cached metadata."""
    root = ET.fromstring(declaration["declaration_xml"])
    assert root.tag == OWL + "Class"
    blanks = declaration.get("referenced_blank_node_declarations", {})
    result, used = [], set()
    logical_children = {
        OWL + "Class": {RDFS + "subClassOf", OWL + "equivalentClass", OWL + "intersectionOf"},
        RDFS + "subClassOf": {OWL + "Class", OWL + "Restriction", RDF + "Description"},
        OWL + "equivalentClass": {OWL + "Class", OWL + "Restriction", RDF + "Description"},
        OWL + "intersectionOf": {OWL + "Class", OWL + "Restriction", RDF + "Description"},
    }

    def walk(element, path, visiting):
        """Traverse native restriction structures while retaining their property paths."""
        if element.tag == OWL + "Restriction":
            properties = element.findall(OWL + "onProperty")
            assert len(properties) == 1
            prop = curie(properties[0].attrib[RDF + "resource"])
            for quantifier in ("someValuesFrom", "allValuesFrom"):
                for filler in element.findall(OWL + quantifier):
                    if RDF + "resource" in filler.attrib:
                        result.append(
                            {
                                "property": prop,
                                "filler": curie(filler.attrib[RDF + "resource"]),
                                "quantifier": quantifier,
                                "path": path,
                            }
                        )
        for index, child in enumerate(element):
            if child.tag not in logical_children.get(element.tag, set()):
                continue
            local = child.tag.rsplit("}", 1)[-1]
            node_id = child.get(RDF + "nodeID")
            if node_id:
                key = "_:" + node_id
                assert key not in visiting and key in blanks
                used.add(key)
                for item in blanks[key]:
                    linked = ET.fromstring(item["declaration_xml"])
                    assert linked.get(RDF + "nodeID") == node_id
                    walk(
                        linked,
                        path + "/" + local + "/@nodeID(" + key + ")/" + linked.tag.rsplit("}", 1)[-1],
                        visiting | {key},
                    )
            else:
                walk(child, path + "/" + local + "[" + str(index) + "]", visiting)

    walk(root, root.tag.rsplit("}", 1)[-1], set())
    assert used == set(blanks)
    return root, result


def test_fixture_hashes_bind_actual_excerpt_bytes():
    """Bind fixture contents separately from original complete native-file identities."""
    manifest = load("manifest.json")
    assert set(manifest["sha256"]) == {"properties.json", "historical_claims.json", "quantifier_examples.json"}
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((RESOURCE / name).read_bytes()).hexdigest() == digest
    assert load("properties.json")["original_file_sha256"]["biolink-model.yaml"] == (
        "b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e"
    )


@pytest.mark.parametrize("relation", ["RO:0000056", "RO:0000057", "RO:0004007", "RO:0002565", "OBI:0000293"])
def test_exact_or_broader_native_witness_preserves_direction(relation):
    """Require complete directed subproperty paths for every nonexact projection."""
    properties = load("properties.json")
    evidence = properties["native_property_paths"][relation]
    assert_property_path(relation, properties)
    assert path_reaches(relation, evidence["target"], evidence["path"])
    assert evidence["mapping_strength"] == ("exact" if relation == evidence["target"] else "generalization")
    if evidence["path"]:
        assert not path_reaches(evidence["target"], relation, evidence["path"])
        assert not path_reaches(relation, evidence["target"], evidence["path"][:-1])


def test_exact_inverse_does_not_fabricate_an_obi_inverse_axiom():
    """Preserve the distinction between a formal axiom and an English definition."""
    props = load("properties.json")
    ro_edges = [item["edge"] for item in props["native_property_excerpt"]["ro"]["edges"]]
    assert any(
        (curie(row["sub"]), row["pred"], curie(row["obj"])) == ("RO:0000056", "inverseOf", "RO:0000057")
        for row in ro_edges
    )
    obi = props["native_property_owl_declarations"]["foodon"]
    assert set(obi) == {"OBI:0000293", "OBI:0000295"}
    for declarations in obi.values():
        for item in declarations:
            assert not list(ET.fromstring(item["declaration_xml"]).iter(OWL + "inverseOf"))


def test_disposition_preserves_all_historical_claims_and_two_distinct_quarantines():
    """Keep every supplier occurrence and the two original GO subjects in the evidence ledger."""
    claims = load("historical_claims.json")
    kept = [row for row in claims if row["disposition"] == KEEP]
    excluded = [row for row in claims if row["disposition"] != KEEP]
    assert len(claims) == 323
    assert len({tuple(row["original_native_triple"]) for row in claims}) == 242
    assert len(kept) == 321
    assert len({tuple(row["original_native_triple"]) for row in kept}) == 240
    assert {tuple(row["original_native_triple"]) for row in excluded} == {
        ("GO:0006082", "RO:0004007", "CHEBI:64709"),
        ("GO:0043603", "RO:0004007", "CHEBI:32988"),
    }
    assert Counter(row["mapping_strength"] for row in kept) == {"exact": 61, "generalization": 260}
    assert Counter(row["supplier"] for row in claims) == {"envo": 9, "foodon": 9, "pato": 92, "uberon": 213}
    for row in claims:
        assert len(row["native_edge_matches"]) == 1
        native = row["native_edge_matches"][0]["edge"]
        assert [curie(native[key]) for key in ("sub", "pred", "obj")] == row["original_native_triple"]
        for identifier in (row["original_native_triple"][0], row["original_native_triple"][2]):
            declarations = row["native_endpoint_declarations"][identifier]
            assert declarations and all(item["declaration"]["type"] == "CLASS" for item in declarations)
    assert_claim_joins(claims, load("properties.json"))


def test_pinned_model_discrepancy_is_recorded_not_repaired():
    """Retain the actual domain/range conflict and LifeStage's non-Occurrent ancestry."""
    model = load("properties.json")["pinned_model"]
    assert model["version"] == "4.4.2"
    participates = model["slots"]["participates in"]
    participant = model["slots"]["has participant"]
    assert "continuant and a process" in participates["description"]
    assert participates["domain"] == "occurrent"
    assert "process and a continuant" in participant["description"]
    assert participant["range"] == "occurrent"
    assert participates["is_a"] == participant["is_a"] == "related to at instance level"
    pending, seen = ["life stage"], set()
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        row = model["classes"][identifier]
        pending.extend(row.get("mixins", []))
        if row.get("is_a"):
            pending.append(row["is_a"])
    assert "organismal entity" in seen
    assert "occurrent" not in seen


def test_capability_and_towards_do_not_enter_the_finite_participation_proof():
    """Native property labels or category signatures cannot expand the reviewed projection set."""
    props = load("properties.json")
    negatives = {curie(row["declaration"]["id"]): row["declaration"] for row in props["negative_property_declarations"]}
    assert negatives["RO:0002215"]["lbl"] == "capable of"
    assert negatives["RO:0002503"]["lbl"] == "towards"
    assert not set(negatives) & set(props["native_property_paths"])


def test_native_quantifier_examples_include_both_blank_nodes_and_no_invented_envo_owl():
    """Represent native serialization limits without inventing missing existential witnesses."""
    examples = load("quantifier_examples.json")
    claims = load("historical_claims.json")
    for example in examples:
        subject, relation, obj = example["original_native_triple"]
        matches = [
            row
            for row in claims
            if row["original_native_triple"] == example["original_native_triple"]
            and row["supplier"] == example["supplier"]
        ]
        assert len(matches) == 1 and matches[0]["disposition"] == example["disposition"]
        observed = []
        for declaration in example["complete_selected_owl_declarations"]:
            root, restrictions = parsed_restrictions(declaration)
            assert curie(root.attrib[RDF + "about"]) == subject
            assert restrictions == declaration["restrictions"]
            observed.extend(item for item in restrictions if item["property"] == relation and item["filler"] == obj)
        assert observed == example["matching_restrictions"] == matches[0]["owl_matching_restrictions"]
        assert all(item["quantifier"] == "someValuesFrom" for item in observed)
        assert bool(observed) == (example["form"] != "json_only")
    blanks = [row for row in examples if row["form"] == "blank_node"]
    assert len(blanks) == 2
    for row in blanks:
        declarations = row["complete_selected_owl_declarations"]
        assert len(declarations) == 1
        assert declarations[0]["referenced_blank_node_declarations"]
        assert all(item["quantifier"] == "someValuesFrom" for item in row["matching_restrictions"])
        assert any("@nodeID" in item["path"] for item in row["matching_restrictions"])
    json_only = [row for row in examples if row["form"] == "json_only"]
    assert len(json_only) == 1 and json_only[0]["supplier"] == "envo"
    assert json_only[0]["complete_selected_owl_declarations"] == []
    assert json_only[0]["matching_restrictions"] == []
    all_claims = load("historical_claims.json")
    without_owl = [row for row in all_claims if not row["owl_matching_restrictions"]]
    assert len(without_owl) == 9 and {row["supplier"] for row in without_owl} == {"envo"}


def test_inverse_instance_relation_does_not_reverse_an_existential_class_restriction():
    """An explicit countermodel rejects universal class-edge reversal."""
    # A countermodel: every A has some B; a second B need not relate to any A.
    class_a, class_b, relation = {"a1"}, {"b1", "b2"}, {("a1", "b1")}
    assert all(any((a, b) in relation for b in class_b) for a in class_a)
    inverse = {(b, a) for a, b in relation}
    assert not all(any((b, a) in inverse for a in class_a) for b in class_b)


def test_common_ontology_normalization_preserves_all_321_retained_claims(tmp_path):
    """Bounded actual-stage replay, not full producer/GO admission acceptance."""
    claims = [row for row in load("historical_claims.json") if row["disposition"] == KEEP]
    assert_claim_joins(claims, load("properties.json"))
    rows = [row["historical_nonempty_fields"] for row in claims]
    header = sorted({key for row in rows for key in row})
    normalized = [{key: row.get(key, "") for key in header} for row in rows]
    edges = tmp_path / "participation_edges.tsv"
    with edges.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerows(normalized)
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.edge_header = header
    transform._normalize_schema(tmp_path / "no_nodes.tsv", edges)
    with edges.open(newline="") as stream:
        assert list(csv.DictReader(stream, delimiter="\t")) == normalized
