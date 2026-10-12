"""Exact approved pod/whole-tail categories, with native evidence and preserved neighbors."""

import copy
import csv
import io
import json
import shutil
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import GROSS_ANATOMICAL_STRUCTURE_CATEGORY
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import foodon_anatomical_categories as anatomy
from kg_microbe.utils import foodon_kernel_quarantine as kernel
from kg_microbe.utils import ontology_parent_quarantine as parents
from kg_microbe.utils.foodon_classification import authoritative_foodon_category, foodon_categories
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
from tests.test_ontology_parent_lifecycle import finalized_seed  # noqa: F401 - reuse real public producer fixture

FIXTURE = Path(__file__).parent / "resources/ontology_parent_dispositions"


def document():
    """Read the existing immutable selected native excerpt, not a fabricated biological graph."""
    return json.loads((FIXTURE / "foodon.json").read_text())


def prepare(tmp_path):
    """Construct an imported source with genuine consumed category-authority snapshots."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("foodon.json", "foodon.owl"):
        shutil.copyfile(FIXTURE / name, raw / name)
    transform = Transform("fixture", raw, tmp_path / "transformed")

    @contextmanager
    def opener(path):
        """Use the real producer's consumed-input hook for each test authority."""
        with transform.consume_input("category_" + Path(path).name, path) as stream:
            yield stream

    return transform, SourceCategoryAuthority(raw, opener=opener)


def test_exact24_native_categories_preserve_every_other_category_and_native_value():
    """Both edamame paths stay visible; losing a parent is not the category decision."""
    value = document()
    before = copy.deepcopy(value)
    baseline = foodon_categories(value["graphs"], anatomical_categories={})
    actual = foodon_categories(value["graphs"])
    assert len(anatomy.POD_IDS) == 22 and len(anatomy.TAIL_IDS) == 2
    assert {key for key in actual if actual[key] != baseline[key]} == anatomy.FINITE_IDS
    assert {actual[key] for key in anatomy.FINITE_IDS} == {GROSS_ANATOMICAL_STRUCTURE_CATEGORY}
    with anatomy.POLICY_FILE.open() as stream:
        policy = anatomy.load_policy(stream)
    controls = policy["unchanged_tail_meat_ids"] + policy["unchanged_ambiguous_meat_ids"]
    assert len(controls) == 8
    assert all(actual[key] == baseline[key] for key in controls)
    assert value == before
    for key in anatomy.FINITE_IDS:
        assert authoritative_foodon_category(key, path=FIXTURE / "foodon.json") == actual[key]


@pytest.mark.parametrize(
    "incoming",
    [
        "",
        "biolink:OntologyClass",
        "biolink:Food",
        "biolink:OrganismTaxon",
        "biolink:Food|biolink:OrganismTaxon|biolink:OntologyClass",
        "biolink:AnatomicalEntity",
        "biolink:GrossAnatomicalStructure",
    ],
)
def test_imported_copies_converge_without_category_union(tmp_path, incoming):
    """Every approved ID uses one anatomy projection, irrespective of supplying source."""
    transform, authority = prepare(tmp_path)
    for identifier in sorted(anatomy.FINITE_IDS):
        row = {
            "id": identifier,
            "category": incoming,
            "name": "Retained imported label",
            "provided_by": "infores:prego",
        }
        original = dict(row)
        authority.normalize(row)
        assert row == {**original, "category": GROSS_ANATOMICAL_STRUCTURE_CATEGORY}
    transform.verify_consumed_inputs()
    assert {anatomy.POLICY_FILE, parents.POLICY_FILE, transform.input_base_dir / "foodon.owl"} <= authority.source_paths


def test_separate_kernel22_and_all_eight_controls_are_preserved(tmp_path):
    """Anatomy is finite: neither the existing Food kernels nor tail meat are descendants of its rule."""
    transform, authority = prepare(tmp_path)
    with kernel.POLICY_FILE.open() as stream:
        kernel_policy = kernel.load_policy(stream)
    with (transform.input_base_dir / "foodon.owl").open("rb") as stream:
        view, _ = kernel.reviewed_hierarchy(document()["graphs"], kernel_policy, native_owl=stream)
    baseline = foodon_categories(view, anatomical_categories={})
    assert len(kernel.COHORT_IDS) == 22 and not kernel.COHORT_IDS & anatomy.FINITE_IDS
    with anatomy.POLICY_FILE.open() as stream:
        policy = anatomy.load_policy(stream)
    for identifier in (*kernel.COHORT_IDS, *policy["unchanged_tail_meat_ids"], *policy["unchanged_ambiguous_meat_ids"]):
        row = {"id": identifier, "category": "biolink:OntologyClass"}
        authority.normalize(row)
        assert row["category"] == baseline[identifier]
    assert {baseline[key] for key in kernel.COHORT_IDS} == {"biolink:Food"}


@pytest.mark.parametrize("incoming", ["biolink:ChemicalEntity", "biolink:Activity", "biolink:Food|biolink:Gene"])
def test_unreviewed_substantive_category_aborts(tmp_path, incoming):
    """The finite override is not authority to erase an unrelated asserted type."""
    _, authority = prepare(tmp_path)
    row = {"id": "FOODON:00002894", "category": incoming}
    with pytest.raises(ValueError, match="substantive category"):
        authority.normalize(row)
    assert row["category"] == incoming


@pytest.mark.parametrize(
    "damage",
    [
        "definition",
        "duplicate",
        "missing",
        "retired",
        "property",
        "alternative_parent",
        "new_descendant",
        "logical_definition",
        "version",
    ],
)
def test_changed_native_json_never_silently_reclassifies_or_expands(damage):
    """Reject changed native evidence rather than infer from a label or lost ancestry."""
    value = document()
    graph = value["graphs"][0]
    node = next(item for item in graph["nodes"] if compact_identifier(item["id"]) == "FOODON:03000155")
    if damage == "definition":
        node.setdefault("meta", {})["definition"] = {"val": "Unreviewed changed meaning"}
    elif damage == "duplicate":
        graph["nodes"].append(copy.deepcopy(node))
    elif damage == "missing":
        graph["nodes"].remove(node)
    elif damage == "retired":
        node.setdefault("meta", {})["deprecated"] = True
    elif damage == "property":
        node["type"] = "PROPERTY"
    elif damage == "alternative_parent":
        graph["edges"].append({"sub": node["id"], "pred": "is_a", "obj": "http://purl.obolibrary.org/obo/NCBITaxon_1"})
    elif damage == "new_descendant":
        graph["nodes"].append({"id": "FOODON:99999999", "type": "CLASS"})
        graph["edges"].append({"sub": "FOODON:99999999", "pred": "is_a", "obj": node["id"]})
    elif damage == "logical_definition":
        axiom = next(item for item in graph["logicalDefinitionAxioms"] if item["definedClassId"] == node["id"])
        axiom["restrictions"] = []
    else:
        graph["meta"]["version"] += "-unreviewed"
    with pytest.raises(ValueError, match="FOODON|native|cohort"):
        foodon_categories(value["graphs"])


@pytest.mark.parametrize("damage", ["missing", "meaning", "alternate_parent"])
def test_native_owl_witness_is_required_in_source_routes(tmp_path, damage):
    """A matching JSON cannot excuse missing or changed original OWL evidence."""
    from lxml import etree

    transform, authority = prepare(tmp_path)
    path = transform.input_base_dir / "foodon.owl"
    if damage == "missing":
        path.unlink()
    else:
        tree = etree.parse(str(path))
        node = next(
            element
            for element in tree.iter(parents._OWL + "Class")
            if compact_identifier(element.get(parents._RDF + "about", "")) == "FOODON:00002894" and len(element)
        )
        if damage == "meaning":
            node.find(parents._RDFS + "label").text += " changed"
        else:
            etree.SubElement(
                node,
                parents._RDFS + "subClassOf",
                {parents._RDF + "resource": "http://purl.obolibrary.org/obo/NCBITaxon_1"},
            )
        path.write_bytes(etree.tostring(tree))
    with pytest.raises((FileNotFoundError, ValueError), match="foodon.owl|native OWL"):
        authority.normalize({"id": "FOODON:00002894", "category": "biolink:OntologyClass"})


@pytest.mark.parametrize("damage", ["category", "scope", "evidence"])
def test_policy_cannot_be_restamped_as_an_unreviewed_decision(damage):
    """The approved scientific choice and exact cohort are pinned independently of input bytes."""
    value = json.loads(anatomy.POLICY_FILE.read_text())
    if damage == "category":
        value["category"] = "biolink:Food"
    elif damage == "scope":
        value["whole_tail_ids"].append("FOODON:03303448")
    else:
        value["native_evidence"]["parent_policy_canonical_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Unreviewed FOODON"):
        anatomy.load_policy(io.StringIO(json.dumps(value)))


def test_missing_native_path_cannot_use_legacy_food_fallback(tmp_path):
    """An exact reviewed anatomical ID must not become Food merely because its authority is absent."""
    with pytest.raises(FileNotFoundError, match="anatomical category authority"):
        authoritative_foodon_category("FOODON:00002894", path=tmp_path / "absent.json")


def test_direct_cache_invalidates_when_finite_policy_changes(tmp_path, monkeypatch):
    """Process-local cache keys include this new policy; source routes separately bind full bytes."""
    path = tmp_path / anatomy.POLICY_FILE.name
    shutil.copyfile(anatomy.POLICY_FILE, path)
    monkeypatch.setattr(anatomy, "POLICY_FILE", path)
    assert (
        authoritative_foodon_category("FOODON:00002894", path=FIXTURE / "foodon.json")
        == GROSS_ANATOMICAL_STRUCTURE_CATEGORY
    )
    value = json.loads(path.read_text())
    value["category"] = "biolink:Food"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Unreviewed FOODON"):
        authoritative_foodon_category("FOODON:00002894", path=FIXTURE / "foodon.json")


def test_actual_import_finalization_binds_policy_and_lossless_category_audit(tmp_path):
    """No merge rewrite: source outputs, evidence and original rows are finalized upstream."""
    transform, _ = prepare(tmp_path)
    with transform.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "category", "name", "provided_by"], delimiter="\t")
        writer.writeheader()
        for identifier in sorted(anatomy.FINITE_IDS):
            writer.writerow(
                {
                    "id": identifier,
                    "category": "biolink:Food|biolink:OrganismTaxon",
                    "name": "Literal imported name",
                    "provided_by": "infores:fixture",
                }
            )
        writer.writerow(
            {"id": "fixture:1", "category": "biolink:NamedThing", "name": "Unrelated", "provided_by": "infores:fixture"}
        )
    transform.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\n"
        "FOODON:00002894\tbiolink:related_to\tfixture:1\tskos:related\tinfores:fixture\tknowledge_assertion\tmanual_agent\n"
    )
    original_edges = list(graph_rows(transform.output_edge_file))
    report = transform.finalize()
    nodes = list(graph_rows(transform.output_node_file))
    assert len(nodes) == 25
    assert all(
        row["category"] == GROSS_ANATOMICAL_STRUCTURE_CATEGORY and row["name"] == "Literal imported name"
        for row in nodes
        if row["id"] in anatomy.FINITE_IDS
    )
    edges = list(graph_rows(transform.output_edge_file))
    assert [{key: row[key] for key in original_edges[0]} for row in edges] == original_edges
    roles = report["consumed_inputs"]
    assert {
        "category_authority_foodon_anatomical_category_dispositions",
        "category_authority_ontology_parent_dispositions",
        "category_authority_foodon",
        "category_authority_foodon_owl",
    } <= roles.keys()
    audit = list(graph_rows(transform.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    selected = [row for row in audit if json.loads(row["original_row_json"]).get("id") in anatomy.FINITE_IDS]
    assert len(selected) == 24
    assert all(
        json.loads(row["original_row_json"])["category"] == "biolink:Food|biolink:OrganismTaxon" for row in selected
    )
    assert all(
        json.loads(row["normalized_row_json"])["category"] == GROSS_ANATOMICAL_STRUCTURE_CATEGORY for row in selected
    )
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_actual_native_dispatcher_category_and_sound_hierarchy(finalized_seed):  # noqa: F811 - shared pytest fixture
    """The real native producer finalizes all 24 categories without changing sound parent assertions."""
    directory, prefix, scope = finalized_seed
    report = json.loads((directory / (prefix + "source_finalization.json")).read_text())
    if scope == "envo":
        # ENVO imports the shared organism root, so its classification may use
        # FOODON evidence without certifying FOODON's unselected graph members.
        assert set(report["members"]) == {"envo_nodes.tsv", "envo_edges.tsv"}
        return
    nodes = {row["id"]: row for row in graph_rows(directory / "foodon_nodes.tsv")}
    assert {nodes[key]["category"] for key in anatomy.FINITE_IDS} == {GROSS_ANATOMICAL_STRUCTURE_CATEGORY}
    assert "category_authority_foodon_anatomical_category_dispositions" in report["consumed_inputs"]
    selected = anatomy.FINITE_IDS | {"FOODON:03303448", "FOODON:03308350"}
    with parents.POLICY_FILE.open() as stream:
        parent_policy = parents.load_policy(stream)
    refused = {(row["subject"], row["parent"]) for row in parent_policy["sources"]["foodon"]["quarantines"]}
    expected = Counter(
        (compact_identifier(edge["sub"]), compact_identifier(edge["obj"]))
        for graph in document()["graphs"]
        for edge in graph["edges"]
        if edge["pred"] == "is_a"
        and compact_identifier(edge["sub"]) in selected
        and (compact_identifier(edge["sub"]), compact_identifier(edge["obj"])) not in refused
    )
    actual = Counter(
        (row["subject"], row["object"])
        for row in graph_rows(directory / "foodon_edges.tsv")
        if row["subject"] in selected and row["relation"] == "rdfs:subClassOf"
    )
    assert actual == expected
    assert actual["FOODON:03000156", "FOODON:03000155"] == 1
    for tail in ("FOODON:03303448", "FOODON:03308350", "FOODON:03308354"):
        assert actual[tail, "FOODON:00002894"] == 1
