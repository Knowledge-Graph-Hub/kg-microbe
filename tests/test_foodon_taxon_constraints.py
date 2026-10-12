"""Finite native class restrictions remain projections, never inferred identity or hierarchy."""

import copy
import csv
import hashlib
import io
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from defusedxml import ElementTree as ET

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import ontology_parent_quarantine as parent_native
from kg_microbe.utils.foodon_kernel_producer import FoodonKernelQuarantine
from kg_microbe.utils.native_ro_retention import NativeROPredicateRetention
from tests.test_participation_disposition import RDF, curie, parsed_restrictions
from tests.upa_route_fixtures import prepare_empty_upa_route_contract

RESOURCE = Path(__file__).parent / "resources/foodon_taxon_constraints"
ANCESTRY_ANCHORS = {"COB:0000022", "PO:0000003"}
# Independently rejoined to full native JSON, not authorized by a restamped
# fixture manifest. Bind complete declarations/metadata and physical source
# coordinates, so paired JSON/OWL edits cannot invent reviewed definitions.
NATIVE_EVIDENCE_SHA256 = "cfd99f4937b365349877c59d49774e2de457ef1597e0e84ae31a7c35f3c42fa3"


def load(name):
    """Read immutable finite evidence; never read the selected production raw tree."""
    return json.loads((RESOURCE / name).read_text())


def assert_native_claims(claims, native, owl, model):
    """Rejoin every semantic field and logical restriction rather than trusting fixture hashes."""
    assert hashlib.sha256(json.dumps(native, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == (
        NATIVE_EVIDENCE_SHA256
    )
    edges = {tuple(curie(row["edge"][key]) for key in ("sub", "pred", "obj")) for row in native["edges"]}
    nodes = {curie(row["declaration"]["id"]): row["declaration"] for row in native["nodes"]}
    assert len(nodes) == len(native["nodes"])
    parents = defaultdict(set)
    for subject, predicate, obj in edges:
        if predicate == "is_a":
            assert nodes[subject]["type"] == nodes[obj]["type"] == "CLASS"
            parents[subject].add(obj)
    prop = nodes["RO:0002162"]
    assert prop["type"] == "PROPERTY" and prop["propertyType"] == "OBJECT"
    assert len(model["complete_native_property_owl"]) == 1
    property_owl = ET.fromstring(model["complete_native_property_owl"][0])
    assert property_owl.tag == "{http://www.w3.org/2002/07/owl#}ObjectProperty"
    assert curie(property_owl.attrib[RDF + "about"]) == "RO:0002162"
    assert property_owl.findtext("{http://www.w3.org/2000/01/rdf-schema#}label") == prop["lbl"] == "in taxon"
    assert property_owl.findtext("{http://purl.obolibrary.org/obo/}IAO_0000115") == prop["meta"]["definition"]["val"]
    assert "RO:0002162" in model["pinned_model"]["in_taxon"]["exact_mappings"]
    counts, placements = Counter(), Counter()
    for claim in claims:
        subject, relation, obj = claim["triple"]
        assert relation == "RO:0002162" and (subject, relation, obj) in edges
        history = claim["historical_fields"]
        assert (history["subject"], history["relation"], history["object"]) == (subject, relation, obj)
        assert history["predicate"] == "biolink:in_taxon"
        assert history["primary_knowledge_source"] == "infores:foodon"
        assert history["knowledge_level"] == "knowledge_assertion"
        assert history["agent_type"] == "manual_agent"
        assert nodes[subject]["type"] == nodes[obj]["type"] == "CLASS"
        assert set(claim["native_paths"]) == {subject, obj}
        for identifier, evidence in claim["native_paths"].items():
            assert evidence["label"] == nodes[identifier].get("lbl", "")
            pending, ancestors = [identifier], set()
            while pending:
                ancestor = pending.pop()
                if ancestor not in ancestors:
                    ancestors.add(ancestor)
                    pending.extend(parents[ancestor])
            assert set(evidence["native_asserted_paths"]) == ancestors & ANCESTRY_ANCHORS
            assert evidence["native_asserted_paths"]
            for target, path in evidence["native_asserted_paths"].items():
                assert path[0] == identifier and path[-1] == target
                assert len(path) == len(set(path))
                assert all(member in nodes and nodes[member]["type"] == "CLASS" for member in path)
                assert all((left, "is_a", right) in edges for left, right in zip(path, path[1:], strict=False))
        restrictions = []
        for declaration in owl[subject]:
            root, actual = parsed_restrictions(declaration)
            assert curie(root.attrib[RDF + "about"]) == subject
            matching = [row for row in actual if row["property"] == relation and row["filler"] == obj]
            restrictions.extend(matching)
        assert restrictions and restrictions == claim["owl_matching_restrictions"]
        assert all(row["quantifier"] == "someValuesFrom" for row in restrictions)
        assert any("/subClassOf[" in row["path"] and "/equivalentClass[" not in row["path"] for row in restrictions)
        counts.update(row["quantifier"] for row in restrictions)
        placements.update("equivalent" if "/equivalentClass[" in row["path"] else "direct" for row in restrictions)
        assert claim["independent_asserted_subclass_same_target"] == ((subject, "is_a", obj) in edges)
    return counts, placements


def test_native_fixture_identity_and_complete_finite_cohort():
    """Bind exact original identities, then independently check complete finite scientific evidence."""
    manifest = load("manifest.json")
    assert set(manifest["sha256"]) == {"claims.json", "native.json", "owl.json", "model.json"}
    for name, expected in manifest["sha256"].items():
        assert hashlib.sha256((RESOURCE / name).read_bytes()).hexdigest() == expected
    assert manifest["original_inputs"]["model"]["sha256"] == (
        "b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e"
    )
    claims = load("claims.json")
    assert len(claims) == len({tuple(row["triple"]) for row in claims}) == 1679
    assert len({row["triple"][0] for row in claims}) == 1679
    assert Counter(row["triple"][2].split(":")[0] for row in claims) == {"NCBITaxon": 1663, "FOODON": 16}
    counts, placements = assert_native_claims(claims, load("native.json"), load("owl.json"), load("model.json"))
    assert counts == {"someValuesFrom": 1714}
    assert placements == {"direct": 1679, "equivalent": 35}
    assert sum(row["independent_asserted_subclass_same_target"] for row in claims) == 15


def test_pinned_domain_discrepancy_is_explicit_not_waived():
    """An ontology class projection is not a taxon instance, nor an automatic category repair."""
    model = load("model.json")["pinned_model"]
    assert model["version"] == "4.4.2"
    assert model["in_taxon"]["domain"] == "thing with taxon"
    assert model["in_taxon"]["range"] == "organism taxon"
    pending, seen = ["organism taxon"], set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        definition = model["classes"][key]
        pending.extend(definition.get("mixins", []))
        if definition.get("is_a"):
            pending.append(definition["is_a"])
    assert seen == {"organism taxon", "named thing", "entity"}
    assert "thing with taxon" not in seen


@pytest.mark.parametrize(
    "damage",
    [
        "direction",
        "predicate",
        "relation",
        "source",
        "quantifier",
        "annotation",
        "ancestor",
        "subclass",
        "native_property_identity",
        "native_coordinate",
        "missing_ancestor_declaration",
        "erased_ancestry_witness",
        "paired_native_definition_drift",
        "ancestor_type",
        "cycle_in_path",
        "incomplete_reachable_anchors",
    ],
)
def test_restamped_receipts_cannot_authorize_semantic_changes(damage):
    """Reject semantic contradictions independently of any mutable hash manifest."""
    claim = copy.deepcopy(load("claims.json")[0])
    native, owl, model = load("native.json"), load("owl.json"), load("model.json")
    subject = claim["triple"][0]
    if damage == "direction":
        claim["historical_fields"]["subject"], claim["historical_fields"]["object"] = (
            claim["historical_fields"]["object"],
            claim["historical_fields"]["subject"],
        )
    elif damage in {"predicate", "relation", "source"}:
        field = "primary_knowledge_source" if damage == "source" else damage
        claim["historical_fields"][field] = "biolink:same_as"
    elif damage in {"quantifier", "annotation"}:
        for declaration in owl[subject]:
            xml = declaration["declaration_xml"]
            if damage == "quantifier":
                xml = xml.replace("someValuesFrom", "allValuesFrom")
                for row in claim["owl_matching_restrictions"]:
                    row["quantifier"] = "allValuesFrom"
            else:
                # Change the logical axiom wrapper to an annotation without
                # modifying the restriction's inner property or filler.
                xml = re.sub(r"(<\/?[\w]+:)subClassOf(?=[\s>])", r"\1seeAlso", xml)
            declaration["declaration_xml"] = xml
    elif damage == "ancestor":
        path = next(iter(claim["native_paths"][subject]["native_asserted_paths"].values()))
        path.insert(1, "NCBITaxon:999999999")
    elif damage == "native_property_identity":
        model["complete_native_property_owl"][0] = model["complete_native_property_owl"][0].replace(
            "RO_0002162", "RO_9999999"
        )
    elif damage == "native_coordinate":
        native["edges"][0]["pointer"] = "/graphs/0/edges/999999999"
    elif damage == "missing_ancestor_declaration":
        native["nodes"] = [row for row in native["nodes"] if curie(row["declaration"]["id"]) != "COB:0000022"]
    elif damage == "erased_ancestry_witness":
        claim["native_paths"][subject]["native_asserted_paths"] = {}
    elif damage == "paired_native_definition_drift":
        prop = next(row["declaration"] for row in native["nodes"] if curie(row["declaration"]["id"]) == "RO:0002162")
        before = prop["meta"]["definition"]["val"]
        prop["meta"]["definition"]["val"] = "x is not related to organism y"
        model["complete_native_property_owl"][0] = model["complete_native_property_owl"][0].replace(
            escape(before), "x is not related to organism y"
        )
    elif damage == "ancestor_type":
        next(row["declaration"] for row in native["nodes"] if curie(row["declaration"]["id"]) == "COB:0000022")[
            "type"
        ] = "PROPERTY"
    elif damage == "cycle_in_path":
        next(iter(claim["native_paths"][subject]["native_asserted_paths"].values())).insert(1, subject)
    elif damage == "incomplete_reachable_anchors":
        del claim["native_paths"][subject]["native_asserted_paths"]["PO:0000003"]
    else:
        claim["independent_asserted_subclass_same_target"] = not claim["independent_asserted_subclass_same_target"]
    with pytest.raises(AssertionError):
        assert_native_claims([claim], native, owl, model)


def prepare_normalization(tmp_path, *, attach_parent=True):
    """Prepare genuine sibling authorities over the unchanged combined native excerpt."""
    raw = tmp_path / "raw"
    raw.mkdir()
    native = RESOURCE.parent / "ontology_parent_dispositions"
    for filename in ("foodon.json", "foodon.owl"):
        shutil.copyfile(native / filename, raw / filename)
    transform = OntologiesTransform(raw, tmp_path / "transformed")
    NativeROPredicateRetention(transform, io.StringIO())
    kernel_audit, parent_audit = io.StringIO(), io.StringIO()
    kernel = FoodonKernelQuarantine(transform, kernel_audit)
    parent = parent_native.OntologyParentQuarantine(transform, parent_audit)
    prepare_empty_upa_route_contract(transform)
    # Both real guards read the same original source before any normalization.
    kernel.prepare_source(raw / "foodon.json")
    parent.prepare_source("foodon", raw / "foodon.json")
    transform._foodon_kernel_authority = kernel
    if attach_parent:
        transform._ontology_parent_authority = parent
    # These are live normalization audits, not fabricated publication receipts.
    assert parent_native.AUDIT_FILE not in transform.producer_audit_snapshots
    return transform, kernel, parent, kernel_audit, parent_audit


def complete_normalization_rows(kernel, parent):
    """Join only identical complete padded rows, preserving the original1679 in order."""
    claims = [claim["historical_fields"] for claim in load("claims.json")]
    parent_rows = parent.policy["sources"]["foodon"]["source_incidence"]
    kernel_rows = [item["row"] for item in kernel.policy["source_incidence"]]
    assert (len(claims), len(parent_rows), len(kernel_rows)) == (1679, 98, 31)
    header = sorted({key for row in claims + parent_rows + kernel_rows for key in row})
    groups = [
        [{key: row.get(key, "") for key in header} for row in group] for group in (claims, parent_rows, kernel_rows)
    ]
    keys = [Counter(tuple(row[key] for key in header) for row in group) for group in groups]
    assert all(set(group.values()) == {1} for group in keys)
    assert sum((keys[0] & keys[1]).values()) == 11
    assert sum((keys[0] & keys[2]).values()) == 1
    assert not keys[1] & keys[2]
    combined, seen = [], set()
    for group in groups:
        for row in group:
            identity = tuple(row[key] for key in header)
            if identity not in seen:
                combined.append(row)
                seen.add(identity)
    assert len(combined) == 1796
    assert combined[:1679] == groups[0]
    return combined, groups[0], header


def write_normalization_input(transform, rows, header):
    """Write the actual protected FOODON filename consumed by the real normalizer."""
    path = transform.output_dir / "foodon_edges.tsv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    transform.edge_header = header
    return path


def test_actual_source_normalization_preserves_all_claims_without_identity_edges(tmp_path):
    """Use the real source normalizer, not a post-merge repair or a toy graph projection."""
    transform, kernel, parent, kernel_audit, parent_audit = prepare_normalization(tmp_path)
    combined, expected, header = complete_normalization_rows(kernel, parent)
    cohort_keys = {(row["subject"], row["predicate"], row["object"]) for row in expected}
    path = write_normalization_input(transform, combined, header)
    transform._normalize_schema(tmp_path / "no_nodes.tsv", path)
    parent.verify_complete()
    kernel.verify_complete()
    with path.open(newline="") as stream:
        actual = list(csv.DictReader(stream, delimiter="\t"))
    selected = [row for row in actual if (row["subject"], row["predicate"], row["object"]) in cohort_keys]
    assert selected == expected
    assert all(row["predicate"] == "biolink:in_taxon" for row in selected)
    parent_removals = parent_native._read_tsv(parent_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)
    kernel_removals = parent_native._read_tsv(kernel_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)
    assert len(parent_removals) == 13
    assert len(kernel_removals) == 1
    removed = [json.loads(row["canonical_prior_row_json"]) for row in parent_removals + kernel_removals]
    assert Counter(tuple(row[key] for key in header) for row in actual) == (
        Counter(tuple(row[key] for key in header) for row in combined)
        - Counter(tuple(row[key] for key in header) for row in removed)
    )
    assert len(actual) == len(combined) - 14 == 1782
    assert not (transform.output_dir / "source_finalization.json").exists()


def test_normalization_requires_active_parent_authority_for_complete_claims(tmp_path):
    """Refuse the original missing active authority without erasing overlapping claims."""
    transform, kernel, parent, kernel_audit, parent_audit = prepare_normalization(tmp_path, attach_parent=False)
    combined, _, header = complete_normalization_rows(kernel, parent)
    path = write_normalization_input(transform, combined, header)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="^Ontology parent normalization requires a run-owned native authority$"):
        transform._normalize_schema(tmp_path / "no_nodes.tsv", path)
    assert path.read_bytes() == before
    assert not parent_native._read_tsv(parent_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)
    assert not parent_native._read_tsv(kernel_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)


def test_normalization_requires_complete_parent_incidence(tmp_path):
    """Refuse one missing sibling row while every original in_taxon claim remains."""
    transform, kernel, parent, kernel_audit, parent_audit = prepare_normalization(tmp_path)
    combined, expected, header = complete_normalization_rows(kernel, parent)
    original = parent.policy["sources"]["foodon"]["source_incidence"][0]
    missing = {key: original.get(key, "") for key in header}
    assert missing not in expected
    assert combined.count(missing) == 1
    combined.remove(missing)
    assert combined[:1679] == expected
    path = write_normalization_input(transform, combined, header)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="^Ontology parent full emitted finite incidence changed$"):
        transform._normalize_schema(tmp_path / "no_nodes.tsv", path)
    assert path.read_bytes() == before
    assert not parent_native._read_tsv(parent_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)
    assert not parent_native._read_tsv(kernel_audit.getvalue().encode(), quoting=csv.QUOTE_MINIMAL)
