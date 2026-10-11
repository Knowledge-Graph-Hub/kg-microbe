"""Bind the finite FOODON kernel correction to complete native evidence, not label heuristics."""

import copy
import csv
import io
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import foodon_kernel_quarantine as native
from kg_microbe.utils.foodon_classification import foodon_categories
from kg_microbe.utils.foodon_kernel_producer import MEMBERS, FoodonKernelQuarantine, verify_kernel_audit_bindings
from kg_microbe.utils.native_ro_retention import NativeROPredicateRetention
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files

FIXTURE = Path(__file__).parent / "resources/foodon_kernel"
POLICY = json.loads(native.POLICY_FILE.read_text())


def graphs():
    """Read the immutable native excerpt without modifying shared fixture bytes."""
    return json.loads((FIXTURE / "foodon.json").read_text())["graphs"]


def reviewed(document=None):
    """Use the actual native OWL witness alongside the original JSON declarations."""
    with (FIXTURE / "foodon.owl").open("rb") as stream:
        return native.reviewed_hierarchy(document if document is not None else graphs(), POLICY, native_owl=stream)


def prepare(tmp_path):
    """Use actual consumed snapshots and a genuine producer contract, not fabricated identities."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for filename in ("foodon.json", "foodon.owl"):
        shutil.copyfile(FIXTURE / filename, raw / filename)
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    NativeROPredicateRetention(transform, io.StringIO())
    audit = io.StringIO()
    scope = FoodonKernelQuarantine(transform, audit)
    from tests.ontology_parent_fixtures import prepare_empty_parent_contract

    prepare_empty_parent_contract(transform)
    from tests.upa_route_fixtures import prepare_empty_upa_route_contract

    prepare_empty_upa_route_contract(transform)
    return transform, scope, audit


def frame():
    """Read every actual historical incident assertion from the independently pinned policy."""
    return pd.DataFrame([item["row"] for item in POLICY["source_incidence"]])


def publish(transform, scope, audit):
    """Exercise producer projection and admission with real retained graph bytes."""
    scope.prepare_source(transform.input_base_dir / "foodon.json")
    before = frame()
    original = before.copy()
    original["id"] = [f"converter:{i}" for i in before.index]
    after = scope.project(before, original, "foodon_edges.tsv")
    scope.verify_complete()
    after.to_csv(transform.output_dir / "foodon_edges.tsv", sep="\t", index=False)
    declarations = {native.compact(node["id"]): node for graph in graphs() for node in graph["nodes"]}
    with (transform.output_dir / "foodon_nodes.tsv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "category", "name", "provided_by"], delimiter="\t")
        writer.writeheader()
        for identifier in sorted(native.COHORT_IDS):
            writer.writerow(
                {
                    "id": identifier,
                    "category": "biolink:Food",
                    "name": declarations[identifier]["lbl"],
                    "provided_by": "infores:foodon",
                }
            )
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    transform.record_producer_audit(native.AUDIT_FILE)
    verify_kernel_audit_bindings(transform.output_dir, transform.consumed_input_snapshots, members=scope.member_names())
    return before, after


def test_exact22_categories_and_one_parent_no_native_mutation():
    """Keep valid ancestry, restrictions, definitions, labels and whole-plant negative controls."""
    original = graphs()
    snapshot = copy.deepcopy(original)
    view, evidence = reviewed(original)
    before, after = foodon_categories(original), foodon_categories(view)
    changed = {identifier for identifier in before if before[identifier] != after[identifier]}
    assert changed == set(POLICY["cohort"]) == evidence.cohort
    assert len(changed) == 22
    assert {after[identifier] for identifier in changed} == {"biolink:Food"}
    assert all(
        after[identifier] == "biolink:OrganismTaxon" for identifier in (native.REJECTED_PARENT, "FOODON:00005105")
    )
    assert before["FOODON:00003424"] == after["FOODON:00003424"] == "biolink:Food"
    assert original == snapshot
    assert sum(len(graph["edges"]) for graph in original) - sum(len(graph["edges"]) for graph in view) == 1
    assert all(
        new["logicalDefinitionAxioms"] == old["logicalDefinitionAxioms"]
        for new, old in zip(view, original, strict=True)
    )


@pytest.mark.parametrize(
    "damage", ["label", "definition", "duplicate", "missing", "new_descendant", "wrong_parent", "restriction"]
)
def test_native_json_change_requires_new_independent_review(damage):
    """Never widen the finite cohort or silently accept changed selected native meanings."""
    document = graphs()
    graph = document[0]
    root = next(node for node in graph["nodes"] if native.compact(node["id"]) == native.ROOT_ID)
    if damage == "label":
        root["lbl"] += " modified"
    elif damage == "definition":
        root["meta"]["definition"]["val"] += " modified"
    elif damage == "duplicate":
        graph["nodes"].append(copy.deepcopy(root))
    elif damage == "missing":
        graph["nodes"].remove(root)
    elif damage == "new_descendant":
        graph["edges"].append({"sub": "FOODON:99999999", "pred": "is_a", "obj": root["id"]})
    elif damage == "wrong_parent":
        edge = next(edge for edge in graph["edges"] if native._triple(edge) == native.REJECTED_TRIPLE)
        edge["obj"] = "FOODON:00000001"
    else:
        graph["logicalDefinitionAxioms"][0]["restrictions"] = []
    with pytest.raises(ValueError):
        reviewed(document)


@pytest.mark.parametrize("damage", ["label", "duplicate", "missing", "new_descendant", "alternate_organism_path"])
def test_native_owl_change_requires_new_independent_review(tmp_path, damage):
    """Validate native OWL independently instead of trusting a JSON conversion alone."""
    from lxml import etree

    tree = etree.parse(str(FIXTURE / "foodon.owl"))
    ns = {"owl": native._OWL[1:-1], "rdf": native._RDF[1:-1], "rdfs": native._RDFS[1:-1]}
    root = next(
        element
        for element in tree.iter(native._OWL + "Class")
        if native.compact(element.get(native._RDF + "about", "")) == native.ROOT_ID and len(element)
    )
    if damage == "label":
        root.find("rdfs:label", ns).text += " modified"
    elif damage == "duplicate":
        tree.getroot().append(copy.deepcopy(root))
    elif damage == "missing":
        root.getparent().remove(root)
    elif damage == "new_descendant":
        child = etree.SubElement(
            tree.getroot(),
            native._OWL + "Class",
            {native._RDF + "about": "http://purl.obolibrary.org/obo/FOODON_99999999"},
        )
        etree.SubElement(
            child, native._RDFS + "subClassOf", {native._RDF + "resource": root.get(native._RDF + "about")}
        )
    else:
        parent = next(
            element
            for element in tree.iter(native._OWL + "Class")
            if native.compact(element.get(native._RDF + "about", "")) == "FOODON:00005092" and len(element)
        )
        etree.SubElement(
            parent,
            native._RDFS + "subClassOf",
            {native._RDF + "resource": "http://purl.obolibrary.org/obo/NCBITaxon_1"},
        )
    with pytest.raises(ValueError):
        native.reviewed_hierarchy(graphs(), POLICY, native_owl=io.BytesIO(etree.tostring(tree)))


@pytest.mark.parametrize(
    "incoming", ["", "biolink:OntologyClass", "biolink:OrganismTaxon", "biolink:Food|biolink:OrganismTaxon"]
)
def test_imported_and_native_categories_converge(tmp_path, incoming):
    """Use the actual shared source authority, including exact-byte consumed snapshots."""
    transform, _, _ = prepare(tmp_path)

    @contextmanager
    def opener(path):
        """Parse selected authorities through the real immutable input lifecycle."""
        with transform.consume_input("test_category_" + Path(path).name, path) as stream:
            yield stream

    authority = SourceCategoryAuthority(transform.input_base_dir, opener=opener)
    for identifier in POLICY["cohort"]:
        row = {"id": identifier, "category": incoming}
        authority.normalize(row)
        assert row["category"] == "biolink:Food"
    transform.verify_consumed_inputs()
    assert transform.input_base_dir / "foodon.owl" in authority.source_paths


def test_substantive_category_conflict_not_silently_discarded():
    """A future unrelated interpretation needs evidence rather than widening this finite override."""
    _, evidence = reviewed()
    with pytest.raises(ValueError, match="substantive category"):
        native.apply_kernel_category(native.ROOT_ID, "biolink:ChemicalEntity", evidence)
    assert native.apply_kernel_category("FOODON:00005088", "biolink:OrganismTaxon", evidence) == "biolink:OrganismTaxon"


def test_all31_assertions_one_quarantine_full_original_audit(tmp_path):
    """Conserve all30 retained assertions and every field; never change native authority bytes."""
    transform, scope, audit = prepare(tmp_path)
    raw = (transform.input_base_dir / "foodon.json").read_bytes()
    before, after = publish(transform, scope, audit)
    expected = before.loc[~((before.subject == native.ROOT_ID) & (before.object == native.REJECTED_PARENT))]
    pd.testing.assert_frame_equal(after, expected)
    rows = list(csv.DictReader(io.StringIO(audit.getvalue()), delimiter="\t"))
    assert len(rows) == 1
    assert json.loads(rows[0]["normalization_input_row_json"])["id"].startswith("converter:")
    assert native.digest(json.loads(rows[0]["native_json_evidence_json"])) == native.JSON_EVIDENCE_SHA256
    assert native.digest(json.loads(rows[0]["native_owl_evidence_json"])) == native.OWL_EVIDENCE_SHA256
    assert (transform.input_base_dir / "foodon.json").read_bytes() == raw


@pytest.mark.parametrize("damage", ["missing", "duplicate", "predicate", "relation", "provenance"])
def test_changed_projection_refuses_without_audit(tmp_path, damage):
    """Demand the entire native incident cohort, not just the rejected parent appearing once."""
    transform, scope, audit = prepare(tmp_path)
    scope.prepare_source(transform.input_base_dir / "foodon.json")
    rows = frame()
    if damage == "missing":
        rows = rows.iloc[1:]
    elif damage == "duplicate":
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    else:
        column = "primary_knowledge_source" if damage == "provenance" else damage
        rows.loc[0, column] = "unreviewed:value"
    with pytest.raises(ValueError, match="incident cohort"):
        scope.project(rows, rows, "foodon_edges.tsv")
    assert not list(csv.DictReader(io.StringIO(audit.getvalue()), delimiter="\t"))


@pytest.mark.parametrize("role", [native.POLICY_ROLE, native.JSON_ROLE, native.OWL_ROLE])
def test_removed_or_rebound_live_native_role_refuses(tmp_path, role):
    """The mandatory producer check keeps original read-time bindings independently."""
    transform, scope, _ = prepare(tmp_path)
    scope.prepare_source(transform.input_base_dir / "foodon.json")
    transform._consumed_input_snapshots.pop(role)
    expected = (
        "FOODON kernel original role bindings changed"
        if role == native.OWL_ROLE
        else "FOODON kernel selected members/native role scope differ"
    )
    with pytest.raises(SourceFinalizationRequired, match=f"^{expected}$"):
        scope.verify_complete()


@pytest.mark.parametrize(
    "damage",
    [
        "erase_audit",
        "erase_native_role",
        "reintroduce_parent",
        "lose_retained_edge",
        "native_change",
        "evidence_change",
    ],
)
def test_recorded_admission_detects_graph_native_and_audit_damage(tmp_path, damage):
    """Admission validates, never repairs or restamps altered graph/evidence bytes."""
    transform, scope, audit = prepare(tmp_path)
    publish(transform, scope, audit)
    snapshots = transform.consumed_input_snapshots
    path = transform.output_dir / native.AUDIT_FILE
    if damage == "erase_audit":
        path.write_text(path.read_text().splitlines()[0] + "\n")
    elif damage == "erase_native_role":
        snapshots.pop(native.OWL_ROLE)
    elif damage in {"reintroduce_parent", "lose_retained_edge"}:
        rows = frame() if damage == "reintroduce_parent" else frame().iloc[2:]
        rows.to_csv(transform.output_dir / "foodon_edges.tsv", sep="\t", index=False)
    elif damage == "native_change":
        with (transform.input_base_dir / "foodon.owl").open("a") as stream:
            stream.write("\n")
    else:
        path.write_text(path.read_text().replace("caryopsis", "invented"))
    with pytest.raises((ValueError, SourceFinalizationRequired)):
        verify_kernel_audit_bindings(transform.output_dir, snapshots, members=MEMBERS)


def test_empty_unselected_source_is_honest_header_only(tmp_path):
    """Do not require full FOODON authority when an invocation never selects FOODON."""
    transform, scope, audit = prepare(tmp_path)
    scope.verify_complete()
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    verify_kernel_audit_bindings(transform.output_dir, transform.consumed_input_snapshots, members=())
    assert native.JSON_ROLE not in transform.consumed_input_snapshots


def test_actual_ontology_normalizer_quarantines_before_finalization(tmp_path):
    """Exercise the production normalization hook, retaining original converter-only fields."""
    transform, scope, audit = prepare(tmp_path)
    scope.prepare_source(transform.input_base_dir / "foodon.json")
    transform._foodon_kernel_authority = scope
    rows = frame()
    rows["id"] = "original-converter-id"
    edges = transform.output_dir / "foodon_edges.tsv"
    rows.to_csv(edges, sep="\t", index=False)
    transform._normalize_schema(transform.output_dir / "absent_nodes.tsv", edges)
    scope.verify_complete()
    emitted = pd.read_csv(edges, sep="\t", dtype=str, keep_default_na=False)
    assert len(emitted) == 30
    assert (
        json.loads(
            list(csv.DictReader(io.StringIO(audit.getvalue()), delimiter="\t"))[0]["normalization_input_row_json"]
        )["id"]
        == "original-converter-id"
    )


def test_restamping_policy_cannot_replace_reviewed_native_evidence():
    """Do not trust policy-supplied hashes without the independent code review pin."""
    policy = copy.deepcopy(POLICY)
    policy["json_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="policy changed"):
        native.load_policy(io.StringIO(json.dumps(policy)))


def test_actual_source_finalization_binds_both_native_formats_and_all22_original_rows(tmp_path):
    """Keep independent JSON/OWL roles and audit every corrected native or imported source row."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for filename in ("foodon.json", "foodon.owl"):
        shutil.copyfile(FIXTURE / filename, raw / filename)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    nodes = {native.compact(node["id"]): node for graph in graphs() for node in graph["nodes"]}
    with transform.output_node_file.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "category", "name", "provided_by"], delimiter="\t")
        writer.writeheader()
        for identifier in POLICY["cohort"]:
            writer.writerow(
                {
                    "id": identifier,
                    "category": "biolink:OrganismTaxon",
                    "name": nodes[identifier]["lbl"],
                    "provided_by": "infores:foodon",
                }
            )
    transform.output_edge_file.write_text("subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n")
    report = transform.finalize()
    actual = list(graph_rows(transform.output_node_file))
    assert len(actual) == 22
    assert {row["category"] for row in actual} == {"biolink:Food"}
    inputs = report["consumed_inputs"]
    assert inputs["category_authority_foodon"]["path"] == str((raw / "foodon.json").resolve())
    assert inputs["category_authority_foodon_owl"]["path"] == str((raw / "foodon.owl").resolve())
    audit = list(graph_rows(transform.output_dir / "source_canonicalization.tsv", quoting=csv.QUOTE_MINIMAL))
    changes = [row for row in audit if json.loads(row["original_row_json"]).get("id") in native.COHORT_IDS]
    assert len(changes) == 22
    assert {json.loads(row["original_row_json"])["category"] for row in changes} == {"biolink:OrganismTaxon"}
    assert {json.loads(row["normalized_row_json"])["category"] for row in changes} == {"biolink:Food"}
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    with (raw / "foodon.owl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(SourceFinalizationRequired, match="changed|missing"):
        verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_no_owl_and_no_partial_or_erased_cohort_acceptance(tmp_path):
    """Absence is allowed only for truly unrelated sources, not for native kernels."""
    with pytest.raises(ValueError, match="OWL evidence is required"):
        native.reviewed_hierarchy(graphs(), POLICY)
    unrelated = [{"nodes": [{"id": "FOODON:00001301", "type": "PROPERTY"}], "edges": []}]
    assert native.reviewed_hierarchy(unrelated, POLICY) == (unrelated, None)
    transform, scope, audit = prepare(tmp_path)
    scope.verify_complete()
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    (transform.output_dir / "foodon_nodes.tsv").write_text("id\tcategory\nFOODON:00005106\tbiolink:Food\n")
    with pytest.raises(SourceFinalizationRequired, match="selected members/native role scope differ"):
        verify_kernel_audit_bindings(transform.output_dir, transform.consumed_input_snapshots, members=MEMBERS)


@pytest.mark.parametrize("field", ["policy", "json_records", "owl_records"])
def test_cached_native_interpretations_cannot_change_before_first_projection(tmp_path, field):
    """Consumed file checks also bind the parsed policy/native payload actually used."""
    transform, scope, audit = prepare(tmp_path)
    scope.prepare_source(transform.input_base_dir / "foodon.json")
    if field == "policy":
        scope.policy["rationale"] += " altered"
    else:
        getattr(scope.evidence, field).clear()
    with pytest.raises(SourceFinalizationRequired, match="cached"):
        scope.project(frame(), frame(), "foodon_edges.tsv")
    assert not list(csv.DictReader(io.StringIO(audit.getvalue()), delimiter="\t"))
