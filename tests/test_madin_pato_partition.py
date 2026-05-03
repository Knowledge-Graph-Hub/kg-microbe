"""
Tests for the madin_etal substrate/quality CURIE partition.

Madin et al's environments.csv conflates ENVO substrates with PATO qualities
in compositional habitat names like ``rock_deep`` →
``ENVO:00001995, PATO:0001596``. The transform must split the substrate from
the quality so that PATO does not end up as a ``location_of`` subject of an
organism. These tests pin the partition contract; the actual edge emission
is a thin layer on top.
"""

from __future__ import annotations

from kg_microbe.transform_utils.madin_etal.madin_etal import (
    _partition_substrate_quality_curies,
)


def test_partition_separates_pato_from_envo() -> None:
    """A canonical 'rock_deep' row splits into one substrate + one quality."""
    substrates, qualities = _partition_substrate_quality_curies(
        ["ENVO:00001995", "PATO:0001596"],
        ["rock", "increased depth"],
    )
    assert substrates == [("ENVO:00001995", "rock")]
    assert qualities == [("PATO:0001596", "increased depth")]


def test_partition_handles_pure_substrate_row() -> None:
    """Rows without any PATO term emit no qualities."""
    substrates, qualities = _partition_substrate_quality_curies(
        ["ENVO:00002007", "ENVO:01000306"],
        ["sediment", "freshwater environment"],
    )
    assert substrates == [
        ("ENVO:00002007", "sediment"),
        ("ENVO:01000306", "freshwater environment"),
    ]
    assert qualities == []


def test_partition_multi_substrate_with_quality() -> None:
    """
    Keep all substrates and qualities for compositional rows.

    A row like 'sediment_fresh_alkaline' has two ENVO substrates and
    one PATO quality; cross-product attachment is the caller's job.
    """
    substrates, qualities = _partition_substrate_quality_curies(
        ["ENVO:00002007", "ENVO:01000306", "PATO:0001430"],
        ["sediment", "freshwater environment", "alkaline"],
    )
    assert len(substrates) == 2
    assert qualities == [("PATO:0001430", "alkaline")]


def test_partition_pato_only_row_yields_no_substrate() -> None:
    """
    Handle the degenerate PATO-only row safely.

    With no substrate to anchor edges on, the caller emits zero
    ``location_of`` edges and zero ``has_quality`` edges — guaranteeing
    PATO never lands as a ``location_of`` subject even in this edge case.
    """
    substrates, qualities = _partition_substrate_quality_curies(
        ["PATO:0001429"],
        ["acidic"],
    )
    assert substrates == []
    assert qualities == [("PATO:0001429", "acidic")]


def test_partition_unknown_prefix_treated_as_substrate() -> None:
    """
    Be permissive about substrate prefixes.

    Only PATO is recognised as a quality; everything else (UBERON,
    FOODON, mesh, NCIT, novel ontologies) flows into substrates and
    may anchor a ``location_of`` edge.
    """
    substrates, qualities = _partition_substrate_quality_curies(
        ["UBERON:0000178", "FOODON:00002441", "mesh:D000001"],
        ["blood", "yeast extract", "abscess"],
    )
    assert len(substrates) == 3
    assert qualities == []
