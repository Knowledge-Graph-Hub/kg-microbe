"""Native ancestry evidence and refusal controls for generic category correction."""

import json
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority

FIXTURES = Path(__file__).parent / "resources" / "ontology_category_authority"


@pytest.mark.parametrize(
    "identifier,category",
    [
        ("ENVO:00002030", "biolink:EnvironmentalFeature"),
        ("ENVO:00001998", "biolink:PhysicalEntity"),
        ("ENVO:02500000", "biolink:EnvironmentalProcess"),
        ("ENVO:01000206", "biolink:Attribute"),
        ("MICRO:0000175", "biolink:ChemicalMixture"),
        ("MICRO:0000082", "biolink:GrowthMedium"),
    ],
)
def test_native_ancestry_categories(identifier, category):
    """Complete fixture ancestry distinguishes systems, materials, quality and processes."""
    authority = OntologyCategoryAuthority(FIXTURES)
    evidence = authority.evidence_for(identifier)
    assert evidence.category == category
    assert evidence.disposition == "asserted_ancestry"
    assert evidence.root_paths
    assert all(path[0] == identifier for path in evidence.root_paths)
    assert authority.category_for(identifier) == category
    with pytest.raises(FrozenInstanceError):
        evidence.category = "biolink:NamedThing"


@pytest.mark.parametrize(
    "identifier", ["ENVO:01001307", "ENVO:01001862", "ENVO:99999999", "BFO:0000038", "PRIDE:0000685", "FOODON:00000001"]
)
def test_unknown_property_individual_and_unsupported_classes_stay_unresolved(identifier):
    """Neither namespace nor occurrence as an endpoint supplies missing type evidence."""
    authority = OntologyCategoryAuthority(FIXTURES)
    assert authority.category_for(identifier) is None


def test_restriction_fillers_are_not_ancestors():
    """A medium ingredient is not a medium because a restriction mentions a medium."""
    evidence = OntologyCategoryAuthority(FIXTURES).evidence_for("MICRO:0000175")
    assert evidence.category == "biolink:ChemicalMixture"
    assert all("MICRO:0000067" not in path for path in evidence.root_paths)
    assert any("named_genus" in predicate for _, predicate, _ in evidence.supporting_axioms)


def _modified_authority(tmp_path, mutate):
    """Apply deliberately synthetic refusal controls to a native immutable excerpt."""
    document = json.loads((FIXTURES / "envo.json").read_text())
    mutate(document["graphs"][0])
    (tmp_path / "envo.json").write_text(json.dumps(document))
    return OntologyCategoryAuthority(tmp_path)


@pytest.mark.parametrize("value", [0, 1, "false", "unknown"])
def test_json_obsolete_flag_requires_a_boolean(tmp_path, value):
    """Numeric and textual lookalikes cannot establish a live class declaration."""

    def mutate(graph):
        """Supply an invalid JSON type for the explicit obsolete marker."""
        graph["nodes"][0].setdefault("meta", {})["deprecated"] = value

    with pytest.raises(ValueError, match="Malformed obsolete flag"):
        _modified_authority(tmp_path, mutate).category_for("ENVO:00001998")


@pytest.mark.parametrize("value", ["unknown", "", "2"])
def test_xml_invalid_obsolete_flag_is_not_treated_as_live(tmp_path, value):
    """A malformed explicit OWL annotation must not silently become false."""
    (tmp_path / "po.owl").write_text(
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#">'
        '<owl:Class rdf:about="http://purl.obolibrary.org/obo/PO_0025131">'
        f"<owl:deprecated>{value}</owl:deprecated></owl:Class></rdf:RDF>"
    )
    with pytest.raises(ValueError, match="Malformed obsolete flag"):
        OntologyCategoryAuthority(tmp_path).category_for("PO:0025131")


@pytest.mark.parametrize("route", ["generic", "foodon"])
@pytest.mark.parametrize("conflict", [False, True])
def test_obsolete_annotation_is_honored_and_conflicting_encodings_abort(tmp_path, route, conflict):
    """Both category routes honor the alternative explicit OWL retirement encoding."""
    from kg_microbe.utils.foodon_classification import authoritative_foodon_category, foodon_categories

    identifier = "BFO:0000040" if route == "generic" else "FOODON:invalid"
    meta = {"basicPropertyValues": [{"pred": "http://www.w3.org/2002/07/owl#deprecated", "val": "true"}]}
    if conflict:
        meta["deprecated"] = False
    graphs = [{"nodes": [{"id": identifier, "type": "CLASS", "meta": meta}], "edges": []}]

    def classify():
        """Exercise the selected source category policy over the identical native declaration."""
        if route == "foodon":
            return foodon_categories(graphs, dispositions={})
        (tmp_path / "envo.json").write_text(json.dumps({"graphs": graphs}))
        return OntologyCategoryAuthority(tmp_path).category_for(identifier)

    if conflict:
        with pytest.raises(ValueError, match="Conflicting obsolete flags"):
            classify()
    elif route == "generic":
        assert classify() is None
    else:
        with pytest.raises(ValueError, match="No live FOODON CLASS"):
            authoritative_foodon_category(identifier, categories=classify())


def test_labels_and_non_subclass_edges_do_not_classify(tmp_path):
    """An attractive environmental label and part_of link cannot create membership."""

    def mutate(graph):
        """Add a tempting label and non-hierarchical relation only."""
        graph["nodes"].append({"id": "ENVO:99999999", "type": "CLASS", "lbl": "environmental system"})
        graph["edges"].append({"sub": "ENVO:99999999", "pred": "BFO:0000050", "obj": "ENVO:01000254"})

    assert _modified_authority(tmp_path, mutate).category_for("ENVO:99999999") is None


def test_contradictory_process_and_material_roots_abort(tmp_path):
    """Asserted contradictions are infrastructure failures, not per-row fallbacks."""

    def mutate(graph):
        """Give a material an incompatible process parent."""
        graph["edges"].append({"sub": "ENVO:00001998", "pred": "is_a", "obj": "ENVO:02500000"})

    authority = _modified_authority(tmp_path, mutate)
    with pytest.raises(ValueError, match="Contradictory material/process"):
        authority.category_for("ENVO:00001998")


@pytest.mark.parametrize("root", ["PATO:0000001", "IAO:0000030"])
@pytest.mark.parametrize("identifier", ["ENVO:00001998", "ENVO:02500000"])
def test_material_or_process_cannot_be_quality_or_information(tmp_path, identifier, root):
    """Disjoint foundational categories cannot become convenient union categories."""

    def mutate(graph):
        """Add a disjoint quality or information ancestor."""
        if root == "IAO:0000030":
            graph["nodes"].append({"id": root, "type": "CLASS"})
        graph["edges"].append({"sub": identifier, "pred": "is_a", "obj": root})

    with pytest.raises(ValueError, match="Contradictory"):
        _modified_authority(tmp_path, mutate).category_for(identifier)


def test_biological_environmental_process_multityping_is_preserved(tmp_path):
    """Independent process specializations are compatible asserted memberships."""

    def mutate(graph):
        """Supply an additional compatible biological-process ancestry path."""
        graph["nodes"].append({"id": "GO:0008150", "type": "CLASS"})
        graph["edges"].append({"sub": "ENVO:02500000", "pred": "is_a", "obj": "GO:0008150"})

    authority = _modified_authority(tmp_path, mutate)
    assert authority.category_for("ENVO:02500000") == "biolink:BiologicalProcess|biolink:EnvironmentalProcess"


def test_obsolete_declarations_and_missing_intermediates_do_not_classify(tmp_path):
    """No traversal through a retired or missing authority node is permitted."""

    def mutate(graph):
        """Retire an intermediate node in the otherwise supported ancestry."""
        next(node for node in graph["nodes"] if node["id"] == "ENVO:00010483")["meta"] = {"deprecated": True}

    authority = _modified_authority(tmp_path, mutate)
    assert authority.category_for("ENVO:00001998") is None
    assert authority.category_for("ENVO:00010483") is None


def test_authorities_are_lazy_and_use_snapshot_opener(tmp_path):
    """Selected missing authority fails, unrelated missing files are never opened."""
    reads = []

    @contextmanager
    def opener(path):
        """Record accesses while supplying immutable native fixture bytes."""
        reads.append(path)
        with (FIXTURES / path.name).open() as stream:
            yield stream

    authority = OntologyCategoryAuthority(tmp_path, opener=opener)
    assert authority.category_for("PRIDE:0000685") is None
    assert not reads
    assert authority.category_for("ENVO:00001998") == "biolink:PhysicalEntity"
    assert authority.category_for("ENVO:99999999") is None
    assert reads == [tmp_path / "envo.json"]
    assert authority.source_paths == set(reads)
    with pytest.raises(FileNotFoundError):
        OntologyCategoryAuthority(tmp_path).category_for("ENVO:00001998")


@pytest.mark.parametrize("content", ["not json", '{"graphs": []}', '{"graphs": [{"nodes": []}]}'])
def test_malformed_and_empty_authority_abort(tmp_path, content):
    """Malformed pinned input cannot be converted to a successful unknown decision."""
    (tmp_path / "envo.json").write_text(content)
    with pytest.raises(ValueError):
        OntologyCategoryAuthority(tmp_path).category_for("ENVO:00001998")


def test_imported_edges_cannot_override_selected_native_authority(tmp_path):
    """A disconnected native ENVO record does not borrow ancestry from FOODON."""
    native = {"graphs": [{"nodes": [{"id": "ENVO:00001998", "type": "CLASS"}], "edges": []}]}
    (tmp_path / "envo.json").write_text(json.dumps(native))
    (tmp_path / "foodon.json").write_text((FIXTURES / "envo.json").read_text())
    authority = OntologyCategoryAuthority(tmp_path)
    assert authority.category_for("ENVO:00001998") is None
    assert authority.source_paths == {tmp_path / "envo.json"}
