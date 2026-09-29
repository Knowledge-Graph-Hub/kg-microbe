"""Reviewed literal classes are Attribute node slots, not organism phenotype edges."""

import csv
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    ATTRIBUTE_TYPE_CURATION_SOURCE,
    DEFAULT_PHENOTYPE_MAPPINGS,
)
from tests.microbedecoder_quarantine_fixtures import bind_fixture_quarantine_policy
from tests.test_microbedecoder_context import read_tsv, run_fixture
from tests.test_microbedecoder_curation_integration import _transform, _write_source


def test_native_attribute_type_is_a_single_node_slot_not_an_edge_predicate():
    """Use the actual pinned slot contract without inventing a range-compatible predicate."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from bmt import Toolkit

    fixture = Path(__file__).parent / "resources/microbedecoder/biolink-4.4.2-attributes.yaml"
    toolkit = Toolkit(schema=str(fixture))
    slot = toolkit.get_element("has attribute type")
    assert (slot.domain, slot.range) == ("attribute", "ontology class")
    assert slot.multivalued is False
    assert slot.required is True
    assert "has attribute type" in toolkit.get_element("attribute").slots
    assert toolkit.is_predicate("has attribute type") is False
    assert "biolink:OntologyClass" in toolkit.get_descendants(slot.range, formatted=True, reflexive=True)


def test_typed_values_keep_shared_field_identity_but_separate_record_observations(tmp_path):
    """A shared literal's type is not a new experiment or a universal taxon phenotype."""
    _, nodes, edges = run_fixture(tmp_path, "typed_source_attributes.csv")
    by_id = {node["id"]: node for node in nodes}
    positive = [edge for edge in edges if edge["source_column"] == "BacDive_Gram_stain" and edge["value"] == "positive"]
    assert len(positive) == 2
    assert len({edge["source_record"] for edge in positive}) == 2
    assert len({edge["object"] for edge in positive}) == 1
    assert by_id[positive[0]["object"]]["has_attribute_type"] == "METPO:1000698"
    assert not any(edge["predicate"] in {"biolink:has_attribute_type", "biolink:has_phenotype"} for edge in edges)
    assert not any(node["id"].startswith("METPO:") for node in nodes)
    reviewed = {
        "chemoheterotrophy": "METPO:1000636",
        "photoautotrophy": "METPO:1000656",
        "photoheterotrophy": "METPO:1000657",
        "plant_pathogen": "METPO:1004003",
    }
    for edge in edges:
        node = by_id[edge["object"]]
        if edge["source_column"] == "FAPROTAX_Type_of_metabolism":
            assert (edge["primary_knowledge_source"], edge["knowledge_level"], edge["agent_type"]) == (
                "infores:faprotax",
                "prediction",
                "computational_model",
            )
            if edge["value"] in reviewed:
                assert (edge["predicate"], edge["relation"]) == ("biolink:has_attribute", "SIO:000008")
                assert node["has_attribute_type"] == reviewed[edge["value"]]
            else:
                assert edge["value"] == "phototrophy"
                assert edge["predicate"] == "biolink:has_attribute"
                assert node["has_attribute_type"] == ""
        if node["has_attribute_type"]:
            assert node["category"] == "biolink:Attribute"
            assert "|" not in node["has_attribute_type"]
            assert node["attribute_type_source"] == ATTRIBUTE_TYPE_CURATION_SOURCE
            assert node["attribute_type_evidence"].startswith("https:")
            assert node["attribute_type_rationale"]
        else:
            assert not any(
                node[key] for key in ("attribute_type_source", "attribute_type_evidence", "attribute_type_rationale")
            )


def test_bacdive_original_edge_bytes_are_unchanged_by_node_typing(tmp_path):
    """Only node metadata changes; no new context, tier or assertion replaces the snapshot."""
    transform = _transform(tmp_path)
    source = _write_source(
        tmp_path,
        [
            {"LPSN_ID": "101", "BacDive_Gram_stain": "positive;negative"},
            {"LPSN_ID": "102", "BacDive_Gram_stain": "positive"},
        ],
    )
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    before = transform.output_edge_file.read_bytes()
    nodes = read_tsv(transform.output_node_file)
    ids = {node["id"] for node in nodes}
    assert all(node["has_attribute_type"] for node in nodes)
    with DEFAULT_PHENOTYPE_MAPPINGS.open() as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        header = reader.fieldnames
        unmatched_rule = next(row for row in reader if row["source_literal"] == "coccus-shaped")
    with transform.phenotype_mappings.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerow(unmatched_rule)
    bind_fixture_quarantine_policy(transform, source)
    transform.run(data_file=source)
    assert transform.output_edge_file.read_bytes() == before
    untyped = read_tsv(transform.output_node_file)
    assert {node["id"] for node in untyped} == ids
    assert all(not node["has_attribute_type"] for node in untyped)
    assert read_tsv(transform.output_dir / "phenotype_normalizations.tsv") == []


@pytest.mark.parametrize(
    "column,literal",
    [
        ("BacDive_Motility", "2"),
        ("BacDive_Spore_formation", "1"),
        ("BacDive_Indole_test", "0"),
        ("BacDive_Voges_proskauer", "+/-"),
        ("BacDive_Pathogenicity_plant", "0"),
    ],
)
def test_undecoded_codes_and_spore_scope_do_not_gain_an_attribute_type(tmp_path, column, literal):
    """Numeric meaning and generic-spore versus endospore scope need their own evidence."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", column: literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    node = read_tsv(transform.output_node_file)[0]
    assert node["category"] == "biolink:Attribute"
    assert node["has_attribute_type"] == ""
    assert read_tsv(transform.output_edge_file)[0]["value"] == literal


def test_faprotax_type_reports_keep_prediction_not_manual_assertion(tmp_path):
    """Term normalization provenance cannot upgrade a taxonomically extrapolated prediction."""
    transform, _, edges = run_fixture(tmp_path, "typed_source_attributes.csv")
    reports = read_tsv(transform.output_dir / "phenotype_normalizations.tsv")
    predicted = [row for row in reports if row["source_column"] == "FAPROTAX_Type_of_metabolism"]
    assert len(predicted) == 4
    for row in predicted:
        original = next(
            edge
            for edge in edges
            if all(edge[key] == row[key] for key in ("subject", "source_record", "source_column", "value"))
        )
        assert (
            (row["primary_knowledge_source"], row["knowledge_level"], row["agent_type"])
            == (original["primary_knowledge_source"], original["knowledge_level"], original["agent_type"])
            == ("infores:faprotax", "prediction", "computational_model")
        )


@pytest.mark.parametrize(
    "column,literal,target,meaning",
    [
        ("BacDive_Motility", "0", "METPO:1000703", "negative"),
        ("BacDive_Motility", "1", "METPO:1000702", "positive"),
        ("BacDive_Pathogenicity_animal", "1", "METPO:1004002", "positive"),
        ("BacDive_Pathogenicity_human", "1", "METPO:1004004", "positive"),
        ("BacDive_Pathogenicity_plant", "1", "METPO:1004003", "positive"),
        ("BacDive_Indole_test", "+", "METPO:1005011", "positive"),
        ("BacDive_Indole_test", "-", "METPO:1005012", "negative"),
        ("BacDive_Voges_proskauer", "+", "METPO:1005017", "positive"),
        ("BacDive_Voges_proskauer", "-", "METPO:1005018", "negative"),
    ],
)
def test_snapshot_supported_codes_type_only_original_field_scoped_attribute(tmp_path, column, literal, target, meaning):
    """Immutable codebook and matching native scopes support exactly these nine pairs."""
    fixture = Path(__file__).parent / "resources/microbedecoder/phenotype_codebook.json"
    codebook = json.loads(fixture.read_text())
    callsite = codebook["callsite"]
    assert len(callsite["data_vars"]) == callsite["data_vars_count"] == 29
    assert len(callsite["is_numeric_vars"]) == callsite["is_numeric_vars_count"] == 29
    assert dict(zip(callsite["data_vars"], callsite["is_numeric_vars"], strict=True))[column] is False
    assert codebook["callsite"]["selected_field_flags"][column] is False
    assert codebook["decoder"]["standalone_token_replacements"][literal] == meaning
    compatibility = codebook["selected_snapshot_compatibility"]
    assert sum(compatibility["compared_fields"].values()) == compatibility["nonempty_field_cells_compared"] == 16317
    assert compatibility["different_field_cells_or_bacdive_ids"] == 0
    assert compatibility["upstream_csv_sha256"] != compatibility["selected_local_csv_sha256"]
    transform = _transform(tmp_path)
    quarantine_source = _write_source(tmp_path, [{"LPSN_ID": "101", "BacDive_ID": "123", column: literal}])
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    edges = read_tsv(transform.output_edge_file)
    observed = [edge for edge in edges if edge["source_column"] == column]
    assert len(observed) == 1
    edge = observed[0]
    assert (edge["predicate"], edge["relation"], edge["value"]) == ("biolink:has_attribute", "SIO:000008", literal)
    assert (edge["primary_knowledge_source"], edge["knowledge_level"], edge["agent_type"]) == (
        "infores:microbedecoder",
        "knowledge_assertion",
        "manual_agent",
    )
    assert edge["source_record"].startswith("sha256:")
    nodes = read_tsv(transform.output_node_file)
    node = next(row for row in nodes if row["id"] == edge["object"])
    assert node["category"] == "biolink:Attribute"
    assert node["has_attribute_type"] == target
    assert codebook["immutable_commit"] in node["attribute_type_evidence"]
    assert not any(row["id"].startswith("METPO:") for row in nodes)
    assert not any(row["predicate"] in {"biolink:has_attribute_type", "biolink:has_phenotype"} for row in edges)


def test_contradictory_codes_and_ambiguous_assay_results_remain_separate_observations(tmp_path):
    """Neither conflicting signs nor generic spores authorize a new aggregate identity."""
    transform = _transform(tmp_path)
    quarantine_source = _write_source(
        tmp_path,
        [
            {
                "LPSN_ID": "101",
                "BacDive_Motility": "0;1",
                "BacDive_Spore_formation": "0;1",
                "BacDive_Voges_proskauer": "+;-;+/-",
                "BacDive_Indole_test": "0;1",
            }
        ],
    )
    bind_fixture_quarantine_policy(transform, quarantine_source)
    transform.run(data_file=quarantine_source)
    edges = read_tsv(transform.output_edge_file)
    nodes = {node["id"]: node for node in read_tsv(transform.output_node_file)}
    assert len(edges) == 9
    expected = {
        ("BacDive_Motility", "0"): "METPO:1000703",
        ("BacDive_Motility", "1"): "METPO:1000702",
        ("BacDive_Voges_proskauer", "+"): "METPO:1005017",
        ("BacDive_Voges_proskauer", "-"): "METPO:1005018",
    }
    for edge in edges:
        assert edge["predicate"] == "biolink:has_attribute"
        pair = (edge["source_column"], edge["value"])
        assert nodes[edge["object"]]["has_attribute_type"] == expected.get(pair, "")
    assert {edge["value"] for edge in edges} == {"0", "1", "+", "-", "+/-"}
    assert len(read_tsv(transform.output_dir / "phenotype_normalizations.tsv")) == 4
