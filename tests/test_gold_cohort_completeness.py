"""Independently reconstructed GOLD cohorts cannot admit extra own-source claims (#1328)."""

import csv

import pytest

from kg_microbe.transform_utils.gold.taxon_dispositions import _verify_graph
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_gold_organism_folds import transformed_gold as transformed_gold


def test_emitter_cannot_restore_excluded_native_cohort(transformed_gold, monkeypatch):
    """A synthetic emitter defect cannot override the independently witnessed native policy."""
    original = transformed_gold._write_nodes

    def append_excluded(*args, **kwargs):
        """Append an excluded native declaration after ordinary emission."""
        original(*args, **kwargs)
        with transformed_gold.output_node_file.open("a", newline="") as stream:
            csv.writer(stream, delimiter="\t").writerow(
                [
                    "gold:Go3",
                    "biolink:NamedThing",
                    "excluded synthetic routing record",
                    "",
                    "",
                    "infores:gold",
                    "",
                    "",
                    "",
                ]
            )

    monkeypatch.setattr(transformed_gold, "_write_nodes", append_excluded)
    with pytest.raises(SourceFinalizationRequired, match="outside the audited native cohort"):
        transformed_gold.run()


def test_assertion_cannot_reference_excluded_native_cohort(transformed_gold):
    """A declaration-free reference to a trimmed native record remains outside producer scope."""
    with transformed_gold.output_edge_file.open("a", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            [
                "gold:Go3",
                "biolink:related_to",
                "NCBITaxon:10",
                "gold:organism_v2.ncbi_taxonomy_id",
                "infores:gold",
                "knowledge_assertion",
                "manual_agent",
                "",
            ]
        )
    with pytest.raises(SourceFinalizationRequired, match="excluded native referent"):
        _verify_graph(
            transformed_gold._taxon_dispositions.index,
            transformed_gold.output_node_file,
            transformed_gold.output_edge_file,
        )


@pytest.mark.parametrize(
    "predicate", ["biolink:same_as", "biolink:exact_match", "biolink:close_match", "biolink:subclass_of"]
)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("relation_only", [False, True])
def test_identity_strength_cannot_escape_through_other_namespaces(transformed_gold, predicate, reverse, relation_only):
    """Neither edge direction nor an unaudited relation field grants unresolved referents identity."""
    subject, target = ("FOODON:00001002", "gold:Go2") if reverse else ("gold:Go2", "gold:Go5")
    with transformed_gold.output_edge_file.open("a", newline="") as stream:
        csv.writer(stream, delimiter="\t").writerow(
            [
                subject,
                "biolink:related_to" if relation_only else predicate,
                target,
                predicate,
                "infores:gold",
                "knowledge_assertion",
                "manual_agent",
                "",
            ]
        )
    with pytest.raises(SourceFinalizationRequired, match="Unsupported identity or class assertion"):
        _verify_graph(
            transformed_gold._taxon_dispositions.index,
            transformed_gold.output_node_file,
            transformed_gold.output_edge_file,
        )


def test_environment_context_and_external_ecosystem_crosswalk_remain_valid(transformed_gold):
    """The finite referent contract is not a general ban on native environment or external identity edges."""
    with transformed_gold.output_edge_file.open("a", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(
            [
                "gold:Go2",
                "biolink:located_in",
                "FOODON:00001002",
                "gold:ecosystem",
                "infores:gold",
                "knowledge_assertion",
                "manual_agent",
                "",
            ]
        )
        writer.writerow(
            [
                "gold.ecosystem:unselected_fixture",
                "biolink:exact_match",
                "ENVO:00000001",
                "skos:exactMatch",
                "infores:gold",
                "knowledge_assertion",
                "manual_agent",
                "",
            ]
        )
    _verify_graph(
        transformed_gold._taxon_dispositions.index, transformed_gold.output_node_file, transformed_gold.output_edge_file
    )
