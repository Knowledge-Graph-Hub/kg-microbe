"""Keep #1322 contradictory-evidence probes independent of receipt freshness."""

import hashlib
import json

import pytest

from tests import test_participation_disposition as proof


@pytest.mark.parametrize(
    "mutation",
    ["subject", "object", "predicate", "relation", "provenance", "endpoint", "quantifier", "native_path", "annotation"],
)
def test_refreshed_manifest_cannot_accept_contradictory_evidence(tmp_path, monkeypatch, mutation):
    """Every reviewed contradiction is rejected even with a coherent byte manifest."""
    names = ("historical_claims.json", "properties.json", "quantifier_examples.json")
    values = {name: proof.load(name) for name in names}
    row = next(item for item in values["historical_claims.json"] if item["disposition"] == proof.KEEP)
    if mutation == "endpoint":
        row["native_endpoint_declarations"][row["original_native_triple"][0]][0]["declaration"]["id"] = "ENVO:99999999"
    elif mutation == "quantifier":
        example = next(item for item in values["quantifier_examples.json"] if item["form"] == "direct_subclass")
        declaration = example["complete_selected_owl_declarations"][0]
        declaration["declaration_xml"] = declaration["declaration_xml"].replace("someValuesFrom", "allValuesFrom")
    elif mutation == "native_path":
        values["properties.json"]["native_property_paths"]["RO:0004007"]["path"] = [
            {
                "pointer": "/graphs/0/edges/579",
                "edge": {"sub": proof.OBO + "RO_0004007", "pred": "subPropertyOf", "obj": proof.OBO + "RO_0002215"},
            },
            {
                "pointer": "/graphs/0/edges/734",
                "edge": {"sub": proof.OBO + "RO_0002215", "pred": "subPropertyOf", "obj": proof.OBO + "RO_0000057"},
            },
        ]
    elif mutation == "annotation":
        example = next(item for item in values["quantifier_examples.json"] if item["form"] == "blank_node")
        declaration = example["complete_selected_owl_declarations"][0]
        declaration["declaration_xml"] = declaration["declaration_xml"].replace(
            "<ns2:subClassOf rdf:nodeID=", "<ns2:seeAlso rdf:nodeID="
        )
        related = [
            item
            for item in values["historical_claims.json"]
            if item["supplier"] == example["supplier"]
            and item["original_native_triple"] == example["original_native_triple"]
        ]
        for restrictions in (
            declaration["restrictions"],
            example["matching_restrictions"],
            related[0]["owl_matching_restrictions"],
        ):
            for item in restrictions:
                item["path"] = item["path"].replace("/subClassOf/@nodeID", "/seeAlso/@nodeID")
    else:
        column, replacement = {
            "subject": ("subject", "ENVO:99999999"),
            "object": ("object", "CHEBI:99999999"),
            "predicate": ("predicate", "biolink:participates_in"),
            "relation": ("relation", "RO:0002503"),
            "provenance": ("primary_knowledge_source", "infores:wrong_supplier"),
        }[mutation]
        row["historical_nonempty_fields"][column] = replacement
    hashes = {}
    for name, value in values.items():
        target = tmp_path / name
        target.write_text(json.dumps(value))
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({"sha256": hashes}))
    monkeypatch.setattr(proof, "RESOURCE", tmp_path)
    proof.test_fixture_hashes_bind_actual_excerpt_bytes()
    with pytest.raises(AssertionError):
        if mutation in {"quantifier", "annotation"}:
            proof.test_native_quantifier_examples_include_both_blank_nodes_and_no_invented_envo_owl()
        else:
            proof.test_disposition_preserves_all_historical_claims_and_two_distinct_quarantines()
