"""Preserve historical PREGO habitat statistics while reading current directed edges (#1848)."""

import csv
from collections import Counter

import pytest

from scripts.prego_validation import (
    fold_enrichment_bto,
    fold_enrichment_envo,
    habitat_compat,
    habitat_threshold_check,
    predicate_interaction,
    ubiquity_check,
)


@pytest.mark.parametrize("term", ["ENVO:1", "BTO:1", "FOODON:1"])
@pytest.mark.parametrize("current", [False, True])
def test_exact_reviewed_habitat_directions(term, current):
    """Both native layouts yield the same habitat/taxon pair without renaming its namespace."""
    triple = ("NCBITaxon:1", "biolink:located_in", term) if current else (term, "biolink:location_of", "NCBITaxon:1")
    assert habitat_compat.habitat_pair(*triple) == (term, "NCBITaxon:1")


@pytest.mark.parametrize(
    "triple",
    [
        ("ENVO:1", "biolink:located_in", "NCBITaxon:1"),
        ("NCBITaxon:1", "biolink:location_of", "ENVO:1"),
        ("ENVO:1", "biolink:related_to", "NCBITaxon:1"),
        ("NCBITaxon:1", "biolink:capable_of", "BTO:1"),
        ("NCBITaxon:1", "RO:0001025", "FOODON:1"),
        ("NCBITaxon:1", "biolink:located_in", "GO:1"),
        ("kgmicrobe.strain:1", "biolink:located_in", "ENVO:1"),
        ("NCBITaxon:", "biolink:located_in", "ENVO:1"),
        ("NCBITaxon:1", "biolink:located_in", "ENVO:"),
    ],
)
def test_wrong_predicates_directions_or_domains_are_excluded(triple):
    """Prefix matching alone cannot make an unrelated edge a habitat observation."""
    assert habitat_compat.habitat_pair(*triple) is None


def _habitat_file(path, current, modern_channel=True):
    """Write equivalent old/current PREGO observations with permuted header columns and distractors."""
    header = ["object", "prego_channel", "subject", "predicate", "prego_score", "original_object"]
    if modern_channel:
        header.append("prego_evidence")
    rows = []
    for term, taxon, score, continuous in [
        ("ENVO:1", "NCBITaxon:1", 2.0, True),
        ("ENVO:1", "NCBITaxon:1", 3.0, True),
        ("ENVO:2", "NCBITaxon:2", 4.0, True),
        ("BTO:1", "NCBITaxon:1", 3.5, True),
        ("FOODON:1", "NCBITaxon:1", 3.0, True),
        ("ENVO:3", "NCBITaxon:3", 4.0, False),
    ]:
        subject, predicate, obj = (
            (taxon, "biolink:located_in", term) if current else (term, "biolink:location_of", taxon)
        )
        rows.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "prego_score": score,
                "prego_channel": ("environmental_samples" if modern_channel else "4 of 5 samples")
                if continuous
                else "annotated_genomes_isolates",
                "original_object": "ENVO:1" if term.startswith("FOODON:") else "",
            }
        )
    for subject, predicate, obj in [
        ("ENVO:1", "biolink:located_in", "NCBITaxon:1"),
        ("NCBITaxon:1", "biolink:location_of", "BTO:1"),
        ("ENVO:1", "biolink:related_to", "NCBITaxon:1"),
        ("BTO:1", "biolink:same_as", "NCBITaxon:1"),
        ("NCBITaxon:1", "biolink:capable_of", "GO:1"),
    ]:
        rows.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "prego_score": 1.5,
                "prego_channel": "environmental_samples" if modern_channel else "4 of 5 samples",
            }
        )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("modern_channel", [False, True])
@pytest.mark.parametrize(
    "shape,expected", [("envo", {"ENVO:1": 2, "ENVO:2": 1}), ("bto", {"BTO:1": 1}), ("foodon", {"FOODON:1": 1})]
)
def test_ubiquity_and_threshold_use_term_degree_in_both_directions(tmp_path, modern_channel, shape, expected):
    """Repeated observations retain edge counts, while degree counts distinct taxa in the habitat namespace."""
    outputs = []
    for current in [False, True]:
        path = _habitat_file(tmp_path / f"{current}.tsv", current, modern_channel)
        taxa, edges, total, layout = ubiquity_check.accumulate(path, shape)
        assert dict(edges) == expected
        assert all(len(value) == 1 for value in taxa.values())
        prefix = habitat_threshold_check.PREFIX[shape]
        rows, threshold_layout = habitat_threshold_check.load(path, prefix)
        assert Counter(term for term, _, _ in rows) == Counter(expected)
        assert threshold_layout == layout
        outputs.append((dict(taxa), dict(edges), dict(total), rows))
    assert outputs[0] == outputs[1]


def test_go_ubiquity_shape_remains_taxon_to_term(tmp_path):
    """The habitat compatibility view does not reverse or discard the independent GO shape."""
    path = _habitat_file(tmp_path / "current.tsv", True)
    taxa, edges, total, _ = ubiquity_check.accumulate(path, "go")
    assert dict(taxa) == {"GO:1": {"NCBITaxon:1"}}
    assert dict(edges) == {"GO:1": 1}
    assert dict(total) == {"GO:1": 1.5}


@pytest.mark.parametrize("channel", ["any", "continuous", "genome"])
def test_envo_fold_collection_preserves_gold_space_and_channels(tmp_path, channel):
    """FOODON original_object provenance cannot masquerade as an ENVO benchmark assertion."""
    gold = {("ENVO:1", "NCBITaxon:1"), ("ENVO:2", "NCBITaxon:2"), ("ENVO:3", "NCBITaxon:3")}
    results = [
        fold_enrichment_envo.collect_prego(_habitat_file(tmp_path / f"{current}.tsv", current), gold, channel)
        for current in [False, True]
    ]
    assert results[0] == results[1]
    labelled, all_scores, per_term, _, _ = results[1]
    assert len(labelled) == {"any": 4, "continuous": 3, "genome": 1}[channel]
    assert len(all_scores) == len(labelled)
    assert all(hit for _, hit in labelled)
    assert all(term.startswith("ENVO:") for term in per_term)


def test_bto_fold_collection_keeps_exact_bto_taxon_pairs(tmp_path):
    """The BTO reader accepts both source orientations and excludes ENVO/FOODON/unrelated predicates."""
    gold = {("BTO:1", "NCBITaxon:1")}
    results = [
        fold_enrichment_bto.collect_prego(_habitat_file(tmp_path / f"{current}.tsv", current), gold)
        for current in [False, True]
    ]
    assert results[0] == results[1]
    per_term, agg, shared_bto, shared_tax, n = results[1]
    assert per_term == {"BTO:1": [(3.5, True)]}
    assert agg == {3.5: [1, 1]}
    assert shared_bto == {"BTO:1"} and shared_tax == {"NCBITaxon:1"} and n == 1


@pytest.mark.parametrize("positive_only", [False, True])
def test_interaction_keeps_habitat_and_function_observations_distinct(tmp_path, monkeypatch, positive_only):
    """Keep the historical location_of report bucket while normalizing only the PREGO habitat view."""
    gold = {("ENVO:1", "NCBITaxon:1"), ("ENVO:2", "NCBITaxon:2"), ("BTO:1", "NCBITaxon:1")}
    terms = {term for term, _ in gold}
    taxa = {"NCBITaxon:1", "NCBITaxon:2"}
    fn = {("NCBITaxon:1", "GO:1"): True}
    results = []
    for current in [False, True]:
        monkeypatch.setattr(predicate_interaction, "PREGO", _habitat_file(tmp_path / f"{current}.tsv", current))
        results.append(predicate_interaction.collect(gold, terms, taxa, fn, {"GO:1"}, taxa, taxa, positive_only))
    assert results[0] == results[1]
    assert set(results[1]["location_of"]) == terms
    assert sum(map(len, results[1]["location_of"].values())) == 4
    assert results[1]["capable_of"] == {"GO:1": [(1.5, True, "NCBITaxon:1")]}


def test_bacdive_and_madin_gold_readers_keep_their_own_native_orientation(tmp_path):
    """PREGO normalization never changes source-specific benchmark interpretation."""
    path = tmp_path / "gold.tsv"
    path.write_text(
        "subject\tpredicate\tobject\n"
        "kgmicrobe.strain:1\tbiolink:subclass_of\tNCBITaxon:1\n"
        "ENVO:1\tbiolink:location_of\tkgmicrobe.strain:1\n"
        "ENVO:2\tbiolink:location_of\tNCBITaxon:2\n"
        "NCBITaxon:3\tbiolink:located_in\tENVO:3\n"
    )
    assert fold_enrichment_envo.load_gold_bacdive(path) == {("ENVO:1", "NCBITaxon:1")}
    assert fold_enrichment_envo.load_gold_madin(path) == {("ENVO:2", "NCBITaxon:2")}
