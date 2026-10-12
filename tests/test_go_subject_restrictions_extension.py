"""Exact native evidence and full-row history controls for the ten-claim extension."""

import copy
import hashlib
import json

import pytest
from lxml import etree

from kg_microbe.utils import go_imported_restrictions as restrictions
from kg_microbe.utils.go_authority import normalize_go_bundle
from tests.go_subject_restrictions_fixtures import FIXTURE, FULL_POLICY, prepare, rows, write_rows

CLAIMS = [(row["subject"], row["relation"], row["object"]) for row in FULL_POLICY["records"]]


def iri(identifier):
    """Use one canonical native OBO spelling, not a label or a suffix guess."""
    return "http://purl.obolibrary.org/obo/" + identifier.replace(":", "_")


def independent_projection(row, replacement, authority):
    """Construct the expected existing normalizer projection without guard helper calls."""
    projected = dict(row)
    history = json.loads(row.get("go_reference_context") or "[]")
    for column in ("subject", "object"):
        literal = row[column]
        compact = literal.replace("http://purl.obolibrary.org/obo/GO_", "GO:", 1)
        if not compact.startswith("GO:"):
            continue
        target = replacement if column == "subject" else compact
        if literal == target:
            continue
        projected[column] = target
        projected["original_" + column] = row.get("original_" + column) or literal
        history.append(
            {
                "column": column,
                "original_id": literal,
                "canonical_id": target,
                "replacement_chain": [compact, target] if compact != target else [compact],
                "authority": authority.authority_path,
                "authority_sha256": authority.authority_sha256,
            }
        )
        projected["go_reference_context"] = json.dumps(history, sort_keys=True, separators=(",", ":"))
    return projected


@pytest.mark.parametrize("claim", CLAIMS)
@pytest.mark.parametrize("style", ["compact", "subject_iri", "object_iri", "relation_iri", "all_iris", "historical"])
def test_each_exact_claim_preserves_original_candidate_and_native_context(tmp_path, monkeypatch, claim, style):
    """All fifteen exact claims use the real normalizer, preserving fields and literal evidence."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    original = next(row for row in rows(edges) if (row["subject"], row["relation"], row["object"]) == claim)
    native = next(row for row in FULL_POLICY["records"] if (row["subject"], row["relation"], row["object"]) == claim)
    original["source_record"] = "native-coordinate:7"
    original["review_qualifier"] = "literal evidence must survive"
    for column in ("subject", "object", "relation"):
        if style in ("all_iris", "historical", column + "_iri"):
            original[column] = iri(original[column])
    if style == "historical":
        original = independent_projection(original, native["replacement"], authority)
    expected = independent_projection(original, native["replacement"], authority)
    write_rows(edges, [original])
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert result["quarantined_imported_subject_restrictions"] == 1
    assert rows(edges) == []
    decisions = [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]
    assert len(decisions) == 1
    decision = decisions[0]
    assert json.loads(decision["original_record_json"]) == original
    assert json.loads(decision["candidate_record_json"]) == expected
    evidence = json.loads(decision[restrictions.EVIDENCE_COLUMN])
    assert evidence["native_class_xml"] == native["native_class_xml"]
    assert evidence["input_record_ordinal"] == 1
    restrictions.verify_audit_record(decision, evidence["inputs"])
    before = nodes.read_bytes(), edges.read_bytes(), audit.read_bytes()
    assert normalize_go_bundle([nodes], [edges], authority, audit) == {"already_normalized": 1}
    assert before == (nodes.read_bytes(), edges.read_bytes(), audit.read_bytes())


@pytest.mark.parametrize("claim", CLAIMS)
def test_wrong_predicate_cannot_bypass_a_protected_claim(tmp_path, monkeypatch, claim):
    """An exact supplier/native identity with changed predicate fails before publication."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    row = next(row for row in rows(edges) if (row["subject"], row["relation"], row["object"]) == claim)
    row["predicate"] = "biolink:subclass_of"
    write_rows(edges, [row])
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="predicate"):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()


@pytest.mark.parametrize(
    "damage", ["missing_object_event", "missing_object_id", "wrong_object_id", "reordered", "extra_event"]
)
def test_go_object_history_is_exact_not_ignored(tmp_path, monkeypatch, damage):
    """A GO-object spelling event is independently required and cannot conceal unrelated history."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    row = next(row for row in rows(edges) if row["subject"] == "GO:0006643")
    row["subject"], row["object"] = iri(row["subject"]), iri(row["object"])
    row = independent_projection(row, "GO:0006629", authority)
    history = json.loads(row["go_reference_context"])
    assert [item["column"] for item in history] == ["subject", "object"]
    if damage == "missing_object_event":
        history.pop()
    elif damage == "missing_object_id":
        row["original_object"] = ""
    elif damage == "wrong_object_id":
        row["original_object"] = iri("GO:0005886")
    elif damage == "reordered":
        history.reverse()
    else:
        history.append(copy.deepcopy(history[-1]))
    row["go_reference_context"] = json.dumps(history)
    write_rows(edges, [row])
    before = nodes.read_bytes(), edges.read_bytes()
    with pytest.raises(ValueError, match="history"):
        normalize_go_bundle([nodes], [edges], authority, audit)
    assert before == (nodes.read_bytes(), edges.read_bytes())
    assert not audit.exists()


@pytest.mark.parametrize("record", FULL_POLICY["records"], ids=lambda record: record["subject"])
def test_complete_native_fixture_has_one_exact_direct_existential(record):
    """Check RDF identity and quantifier structure, not merely a dictionary key or stored digest."""
    content = (FIXTURE / "pato.owl").read_bytes()
    assert record["native_class_xml"].encode() in content
    assert hashlib.sha256(record["native_class_xml"].encode()).hexdigest() == record["native_class_sha256"]
    tree = etree.fromstring(content, etree.XMLParser(no_network=True, resolve_entities=False))
    ns = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "owl": "http://www.w3.org/2002/07/owl#",
    }
    classes = tree.xpath("owl:Class[@rdf:about=$subject]", namespaces=ns, subject=iri(record["subject"]))
    assert len(classes) == 1
    witnesses = classes[0].xpath(
        "rdfs:subClassOf/owl:Restriction[owl:onProperty/@rdf:resource=$relation and "
        "owl:someValuesFrom/@rdf:resource=$object]",
        namespaces=ns,
        relation=iri(record["relation"]),
        object=iri(record["object"]),
    )
    assert len(witnesses) == 1
    assert len(witnesses[0].findall("owl:onProperty", ns)) == 1
    assert len(witnesses[0].findall("owl:someValuesFrom", ns)) == 1


def test_sibling_relations_other_suppliers_and_unselected_restrictions_are_not_selected():
    """The selector is finite, not a subject-prefix or relation-wide quarantine."""
    original = FULL_POLICY["records"][2]
    row = {key: original[key] for key in ("subject", "predicate", "object", "relation", "primary_knowledge_source")}
    controls = [
        {**row, "primary_knowledge_source": "infores:upa"},
        {**row, "object": "GO:0005886"},
        {**row, "relation": "RO:0000057"},
        {**row, "subject": "GO:0006903", "relation": "RO:0002162", "object": "NCBITaxon:33208"},
        {**row, "subject": "GO:0048199", "relation": "RO:0004009", "object": "GO:0005794"},
        {**row, "subject": "GO:0055108", "relation": "RO:0002338", "object": "GO:0005794"},
    ]
    before = copy.deepcopy(controls)
    assert all(restrictions.identify(control) is None for control in controls)
    assert controls == before


def test_approved_three_are_conservative_dispositions_not_falsehood_claims():
    """The extension is exactly three relation-specific transfers, not all claims on their subjects."""
    selected = [
        row
        for row in FULL_POLICY["records"]
        if row.get("scientific_context", {}).get("decision") == "user_approved_audit_only_unsupported_transfer"
    ]
    assert {(row["subject"], row["relation"], row["object"]) for row in selected} == {
        ("GO:0006903", "RO:0002162", "NCBITaxon:2759"),
        ("GO:0048199", "RO:0004009", "GO:0005798"),
        ("GO:0055108", "BFO:0000066", "GO:0005737"),
    }
    assert all("does not assert biological falsity" in row["scientific_context"]["interpretation"] for row in selected)
    assert len(FULL_POLICY["records"]) == 15


def test_same_subject_distinct_restrictions_retain_separate_native_occurrences(tmp_path, monkeypatch):
    """The approved spatial transfer does not overwrite the earlier destination audit."""
    _, nodes, edges, audit, authority = prepare(tmp_path, monkeypatch, all_claims=True)
    originals = [row for row in rows(edges) if row["subject"] == "GO:0055108"]
    assert {(row["relation"], row["object"]) for row in originals} == {
        ("RO:0002339", "GO:0030133"),
        ("BFO:0000066", "GO:0005737"),
    }
    write_rows(edges, originals)
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert result["quarantined_imported_subject_restrictions"] == 2
    assert rows(edges) == []
    decisions = [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]
    assert [json.loads(row["original_record_json"]) for row in decisions] == originals
    assert [json.loads(row[restrictions.EVIDENCE_COLUMN])["input_record_ordinal"] for row in decisions] == [1, 2]
