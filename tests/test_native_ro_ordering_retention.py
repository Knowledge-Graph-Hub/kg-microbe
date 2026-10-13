"""Finite34 ordering retention preserves exact BFO and unapproved GO restrictions."""

import copy
import csv
import hashlib
import io
import json
import xml.etree.ElementTree as ET
from collections import Counter

import pandas as pd
import pytest

from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_native_ro_input_bindings import _completed
from tests.test_native_ro_retention import FIXTURE, POLICY, audit_rows, frame, legacy_authorities, prepare

NEW = {"RO:0002082": 17, "RO:0002087": 8, "RO:0002223": 4, "RO:0002229": 3, "RO:0002230": 2}
SCIENCE_SHA = "d6a5bf58b80114861739f7f9714836d419d9b9ed96eb50a56ea61c20c9e303bb"
SCIENCE = json.loads((FIXTURE / "temporal62_native.json").read_bytes())
NS = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}
RESOURCE = "{" + NS["rdf"] + "}resource"
NODE_ID = "{" + NS["rdf"] + "}nodeID"
OBO = "http://purl.obolibrary.org/obo/"


def _element(science, supplier, identifier, *, restriction=False):
    """Parse a complete literal native stanza under its original namespace bindings."""
    xml = science["stanzas"][supplier + ":" + identifier]["literal_xml"]
    root = ET.fromstring(  # noqa: S314 - code-pinned complete native fixture, never external input
        science["native_files"][supplier]["rdf_prefix"] + xml + "\n</rdf:RDF>"
    )
    assert len(root) == 1
    element = list(root)[0]
    about = "{" + NS["rdf"] + "}about"
    if restriction:
        assert element.tag == "{" + NS["owl"] + "}Restriction"
        assert element.get(NODE_ID) == identifier and element.get(about) is None
    else:
        assert element.tag == "{" + NS["owl"] + "}Class"
        assert element.get(about) == OBO + identifier.replace(":", "_", 1) and element.get(NODE_ID) is None
    return element


def _restrictions(science, record):
    """Follow native logical class links, never annotation-only blank-node references."""
    row = record["row"]
    supplier = record["witnesses"][0]["supplier"]
    subject = _element(science, supplier, row["subject"])
    result = subject.findall("rdfs:subClassOf/owl:Restriction", NS)
    result += subject.findall("owl:equivalentClass/owl:Class/owl:intersectionOf/owl:Restriction", NS)
    for link in subject.findall("rdfs:subClassOf", NS):
        if link.get(NODE_ID):
            result.append(_element(science, supplier, link.get(NODE_ID), restriction=True))
    found = []
    for restriction in result:
        prop = restriction.find("owl:onProperty", NS)
        if prop is None or prop.get(RESOURCE) != OBO + row["relation"].replace(":", "_", 1):
            continue
        for quantifier in ("someValuesFrom", "allValuesFrom", "hasValue"):
            filler = restriction.find("owl:" + quantifier, NS)
            if filler is not None and filler.get(RESOURCE) == OBO + row["object"].replace(":", "_", 1):
                found.append(quantifier)
    assert found and set(found) == {"someValuesFrom"}
    return found


def test_native_science_is_pinned_and_all62_rejoin_literal_existentials():
    """Independently prove all62 native directions and both explicit logical blank-node links."""
    assert hashlib.sha256((FIXTURE / "temporal62_native.json").read_bytes()).hexdigest() == SCIENCE_SHA
    for stanza in SCIENCE["stanzas"].values():
        assert hashlib.sha256(stanza["literal_xml"].encode()).hexdigest() == stanza["sha256"]
    assert sum(len(_restrictions(SCIENCE, row)) for row in SCIENCE["assertions"]) == 67
    linked = [r for r in SCIENCE["assertions"] if any("blank_node" in x for x in r["literal_owl_restrictions"])]
    assert len(linked) == 2
    assert {r["row"]["subject"] for r in linked} == {"UBERON:0000070", "UBERON:0000109"}
    for record in SCIENCE["assertions"]:
        row = record["row"]
        witness = record["witnesses"][0]["native_assertion"]
        assert [native.compact_identifier(witness[k]) for k in ("sub", "pred", "obj")] == [
            row[k] for k in ("subject", "relation", "object")
        ]
        assert row["relation"] in record["model_slot"][record["projection_kind"]]


@pytest.mark.parametrize("damage", ["quantifier", "annotation_only", "wrong_filler", "reverse"])
def test_linked_native_restriction_proof_refuses_semantic_drift(damage):
    """Even re-stamped local metadata cannot make a different OWL restriction prove this assertion."""
    evidence = copy.deepcopy(SCIENCE)
    record = next(r for r in evidence["assertions"] if r["row"]["subject"] == "UBERON:0000070")
    linked = next(r for r in record["literal_owl_restrictions"] if "blank_node" in r)
    stanza = evidence["stanzas"]["uberon:" + linked["blank_node"]]
    if damage == "quantifier":
        stanza["literal_xml"] = stanza["literal_xml"].replace("someValuesFrom", "allValuesFrom")
    elif damage == "wrong_filler":
        stanza["literal_xml"] = stanza["literal_xml"].replace("GO_0035209", "GO_0008150")
    elif damage == "annotation_only":
        subject = evidence["stanzas"]["uberon:UBERON:0000070"]
        subject["literal_xml"] = subject["literal_xml"].replace(
            '<rdfs:subClassOf rdf:nodeID="' + linked["blank_node"] + '"/>',
            '<rdfs:seeAlso rdf:nodeID="' + linked["blank_node"] + '"/>',
        )
    else:
        record["row"]["subject"], record["row"]["object"] = record["row"]["object"], record["row"]["subject"]
    stanza["sha256"] = hashlib.sha256(stanza["literal_xml"].encode()).hexdigest()
    with pytest.raises(AssertionError):
        _restrictions(evidence, record)


def test_exact_extension_preserves_prior292_and_declares_only_reviewed34():
    """No prior record, direction, native authority, or unrelated predicate gains new approval."""
    original_suppliers = [r for r in POLICY["records"] if r["ontology"] in {"pato", "uberon"}]
    previous = [r for r in original_suppliers if r["relation"] not in NEW]
    assert len(previous) == 292
    assert (
        native._digest(native._json(previous).encode())
        == "eb4722a3a35388fd5dc4d5308004e59a1210d7d9e834f0d0398df53d87196d8d"
    )
    old_policy = copy.deepcopy(POLICY)
    old_policy["version"] = 1
    old_policy["records"] = previous
    old_policy["authorities"] = legacy_authorities({"pato.json", "uberon.json", "ro.json"})
    old_policy["relations"] = {key: row for key, row in old_policy["relations"].items() if key not in NEW}
    old_policy["finite_cohort_sha256"] = native._digest(native._json(previous).encode())
    old_policy.pop("unchanged_records")
    assert (
        native._digest(native._json(old_policy).encode())
        == "b140b39a0e4d8c4fec34f67c894e4b0f5addfed29b86064cc015a251621827b7"
    )
    added = [r for r in original_suppliers if r["relation"] in NEW]
    assert Counter(r["relation"] for r in added) == NEW
    assert Counter(r["ontology"] for r in added) == {"pato": 10, "uberon": 24}
    assert len(POLICY["unchanged_records"]) == 8
    assert all(r["subject"].startswith("GO:") and r["object"].startswith("GO:") for r in POLICY["unchanged_records"])
    assert native.native_input_contract()["version"] == 2


@pytest.mark.parametrize(
    "damage",
    ["detached_blank_id", "wrong_subject", "wrong_class_type", "not_restriction", "extra_root", "competing_identifier"],
)
def test_scientific_witness_identity_is_parsed_not_inferred_from_dictionary_key(damage):
    """Reject structurally detached or mis-typed XML even with a re-stamped stanza receipt."""
    evidence = copy.deepcopy(SCIENCE)
    record = next(row for row in evidence["assertions"] if row["row"]["subject"] == "UBERON:0000070")
    link = next(row for row in record["literal_owl_restrictions"] if "blank_node" in row)
    stanza = evidence["stanzas"]["uberon:" + link["blank_node"]]
    if damage == "detached_blank_id":
        stanza["literal_xml"] = stanza["literal_xml"].replace(
            'rdf:nodeID="' + link["blank_node"] + '"', 'rdf:nodeID="unrelated_restriction"'
        )
    elif damage in {"wrong_subject", "wrong_class_type"}:
        stanza = evidence["stanzas"]["uberon:UBERON:0000070"]
        if damage == "wrong_subject":
            stanza["literal_xml"] = stanza["literal_xml"].replace(
                'rdf:about="' + OBO + 'UBERON_0000070"', 'rdf:about="' + OBO + 'UBERON_9999999"'
            )
        else:
            stanza["literal_xml"] = stanza["literal_xml"].replace("owl:Class", "owl:ObjectProperty")
    elif damage == "not_restriction":
        stanza["literal_xml"] = stanza["literal_xml"].replace("owl:Restriction", "owl:Class")
    elif damage == "extra_root":
        stanza["literal_xml"] += '\n<owl:Restriction rdf:nodeID="' + link["blank_node"] + '"/>'
    else:
        stanza["literal_xml"] = stanza["literal_xml"].replace(
            "<owl:Restriction ", '<owl:Restriction rdf:about="' + OBO + 'UBERON_0000070" '
        )
    stanza["sha256"] = hashlib.sha256(stanza["literal_xml"].encode()).hexdigest()
    with pytest.raises(AssertionError):
        _restrictions(evidence, record)


@pytest.mark.parametrize("name", ["pato", "uberon"])
def test_all28_exact_bfo_and_eight_go_control_rows_remain_completely_unchanged(tmp_path, monkeypatch, name):
    """Preserve every field of actual source evidence, not just predicate counts."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=(name,))
    records = [
        r["current_production_source_rows"][0]["row"]
        for r in SCIENCE["assertions"]
        if r["witnesses"][0]["supplier"] == name and r["row"]["relation"].startswith("BFO:")
    ]
    rows = pd.concat([frame(name), pd.DataFrame(records)], ignore_index=True).fillna("")
    before = rows.copy(deep=True)
    retained = authority.project(name, rows, rows, name + "_edges.tsv")
    membership = native._cohort(POLICY, name)
    outside = before.apply(lambda row: (row["subject"], row["relation"], row["object"]) not in membership, axis=1)
    pd.testing.assert_frame_equal(retained.loc[outside], before.loc[outside])
    assert len(audit_rows(audit)) == {"pato": 74, "uberon": 252}[name]
    assert len(records) == {"pato": 8, "uberon": 20}[name]


@pytest.mark.parametrize("damage", ["extra", "missing_control", "native_control", "supplier_control", "reversed"])
def test_relation_overlap_is_not_blanket_approval(tmp_path, monkeypatch, damage):
    """Refuse unknown/changed finite relation assertions before writing any audit."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    index = rows.index[rows["subject"].str.startswith("GO:") & (rows["relation"] == "RO:0002230")][0]
    if damage == "extra":
        rows.loc[len(rows)] = rows.loc[index]
        rows.loc[len(rows) - 1, "subject"] = "GO:9999999"
    elif damage == "missing_control":
        rows = rows.drop(index)
    elif damage == "native_control":
        rows.loc[index, "predicate"] = "RO:0002230"
    elif damage == "supplier_control":
        rows.loc[index, "primary_knowledge_source"] = "infores:uberon"
    else:
        index = rows.index[rows["relation"] == "RO:0002082"][0]
        rows.loc[index, ["subject", "object"]] = rows.loc[index, ["object", "subject"]].to_numpy()
    with pytest.raises(ValueError):
        authority.project("pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


@pytest.mark.parametrize(
    "damage", ["extra", "missing_control", "native_control", "all_selected_and_audit_lost", "partial_audit"]
)
def test_public_recorded_admission_enforces_new_scope_and_control_semantics(tmp_path, monkeypatch, damage):
    """Restamping outer receipts cannot admit broadened scope or erased selected assertions."""
    transform, _, _ = _completed(tmp_path, monkeypatch)
    path = transform.output_dir / "pato_edges.tsv"
    rows = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    index = rows.index[rows["subject"].str.startswith("GO:") & (rows["relation"] == "RO:0002230")][0]
    if damage == "extra":
        rows.loc[len(rows)] = rows.loc[index]
        rows.loc[len(rows) - 1, "subject"] = "GO:9999999"
    elif damage == "missing_control":
        rows = rows.drop(index)
    elif damage == "native_control":
        rows.loc[index, "predicate"] = "RO:0002230"
    elif damage == "all_selected_and_audit_lost":
        rows = rows[rows["predicate"] != rows["relation"]]
        (transform.output_dir / native.AUDIT_FILE).write_text("\t".join(native.AUDIT_FIELDS) + "\n")
    else:
        audit_path = transform.output_dir / native.AUDIT_FILE
        audits = list(csv.DictReader(io.StringIO(audit_path.read_text()), delimiter="\t"))
        removed = next(row for row in audits if json.loads(row["retained_row_json"])["relation"] in NEW)
        audits.remove(removed)
        with audit_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=native.AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(audits)
    rows.to_csv(path, sep="\t", index=False)
    report = {
        "consumed_inputs": transform.consumed_input_snapshots,
        "producer_native_inputs": transform.producer_native_inputs,
    }
    with pytest.raises(SourceFinalizationRequired):
        type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")


def test_truthful_inactive_supplier_prefix_has_no_control_requirement(tmp_path):
    """A file prefix alone does not claim that full native PATO was consumed."""
    from tests.test_merge_source_freshness import prepare_source

    transform = prepare_source(tmp_path, "ontologies", prefix="pato_", marker=False)
    assert "ontology_native_relation_pato" not in transform.consumed_input_snapshots
    transform.verify_consumed_inputs()
    report = {
        "consumed_inputs": transform.consumed_input_snapshots,
        "producer_native_inputs": transform.producer_native_inputs,
    }
    type(transform).verify_recorded_native_inputs(report, transform.output_dir / "source_finalization.json")
