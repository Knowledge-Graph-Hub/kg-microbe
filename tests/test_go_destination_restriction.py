"""Keep the finite destination repair distinct from other relations on its source class."""

import hashlib
import json

from lxml import etree

from kg_microbe.utils import go_imported_restrictions as restrictions
from kg_microbe.utils.go_authority import normalize_go_bundle
from tests.go_subject_restrictions_fixtures import FIXTURE, FULL_POLICY, prepare, rows, write_rows


def test_destination_decision_has_complete_native_role_and_replacement_context():
    """Read genuine supplier declarations rather than infer cargo roles from GO labels."""
    claim = next(record for record in FULL_POLICY["records"] if record["subject"] == "GO:0055108")
    context = claim["scientific_context"]
    assert context["supplier"] == "pato.owl"
    native = (FIXTURE / "pato.owl").read_bytes()
    for field in ("native_replacement_class", "native_property"):
        stanza = context[field + "_xml"].encode()
        assert native.count(stanza) == 1
        assert hashlib.sha256(stanza).hexdigest() == context[field + "_sha256"]
    tree = etree.fromstring(native, etree.XMLParser(no_network=True, resolve_entities=False))
    ns = {
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    }
    prefix = "http://purl.obolibrary.org/obo/"
    old = tree.xpath("owl:Class[@rdf:about=$identifier]", namespaces=ns, identifier=prefix + "GO_0055108")
    current = tree.xpath("owl:Class[@rdf:about=$identifier]", namespaces=ns, identifier=prefix + "GO_0006893")
    prop = tree.xpath("owl:ObjectProperty[@rdf:about=$identifier]", namespaces=ns, identifier=prefix + "RO_0002339")
    assert len(old) == len(current) == len(prop) == 1
    assert prop[0].find("rdfs:label", ns).text == "has target end location"
    old_end = old[0].xpath(
        "rdfs:subClassOf/owl:Restriction[owl:onProperty/@rdf:resource=$property]/owl:someValuesFrom/@rdf:resource",
        namespaces=ns,
        property=prefix + "RO_0002339",
    )
    replacement_end = current[0].xpath(
        "owl:equivalentClass/owl:Class/owl:intersectionOf/owl:Restriction["
        "owl:onProperty/@rdf:resource=$property]/owl:someValuesFrom/@rdf:resource",
        namespaces=ns,
        property=prefix + "RO_0002339",
    )
    assert old_end == [prefix + "GO_0030133"]
    assert replacement_end == [prefix + "GO_0005886"]


def test_destination_quarantine_keeps_supported_start_location_and_its_history(tmp_path, monkeypatch):
    """One destination disposition cannot erase the independent Golgi start-location claim."""
    context = json.loads((FIXTURE / "start_location_go_metadata.json").read_text())
    assert context["source"]["sha256"] == FULL_POLICY["sources"]["go.db"]["sha256"]
    assert len(context["statements"]) == context["row_count"] == 26
    assert {row["subject"] for row in context["statements"]} == {"GO:0005794"}
    _, nodes, edges, audit, authority = prepare(
        tmp_path, monkeypatch, all_claims=True, additional_go_statements=context["statements"]
    )
    original = next(row for row in rows(edges) if row["subject"] == "GO:0055108")
    sibling = {**original, "relation": "RO:0002338", "object": "GO:0005794", "source_record": "native-start"}
    write_rows(edges, [original, sibling])
    result = normalize_go_bundle([nodes], [edges], authority, audit)
    assert result["quarantined_imported_subject_restrictions"] == 1
    decisions = [row for row in rows(audit, quoted=True) if row["record_kind"] == restrictions.AUDIT_KIND]
    assert len(decisions) == 1
    assert json.loads(decisions[0]["original_record_json"]) == original
    evidence = json.loads(decisions[0][restrictions.EVIDENCE_COLUMN])
    assert evidence["inputs"][restrictions.POLICY_ROLE]["path"] == str(restrictions.POLICY_FILE)
    actual = rows(edges)
    assert len(actual) == 1
    retained = actual[0]
    assert retained["subject"] == "GO:0006893"
    assert retained["original_subject"] == "GO:0055108"
    assert all(retained[field] == value for field, value in sibling.items() if field != "subject")
    history = json.loads(retained["go_reference_context"])
    assert len(history) == 1
    assert history[0]["replacement_chain"] == ["GO:0055108", "GO:0006893"]
    assert history[0]["authority_sha256"] == authority.authority_sha256
