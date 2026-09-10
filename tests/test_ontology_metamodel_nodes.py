"""An ontology's annotation vocabulary is not one of its classes (#1023)."""

import pandas as pd
import pytest

from kg_microbe.transform_utils.ontologies.ontologies_transform import (
    METAMODEL_NODE_PREFIXES,
    OntologiesTransform,
)


@pytest.fixture()
def transform():
    """Build a transform instance; the dropper is a pure DataFrame method needing no I/O."""
    return OntologiesTransform.__new__(OntologiesTransform)


def _nodes(*ids):
    return pd.DataFrame({"id": list(ids), "category": ["biolink:OntologyClass"] * len(ids)})


def test_annotation_properties_are_dropped(transform):
    """
    rdfs:label was a node in the knowledge graph, asserted to be an ontology class.

    55 distinct such ids, 172 rows across ten ontologies, 0 edges touching any
    of them, 36 in the shipped graph.
    """
    df, dropped = transform._drop_metamodel_nodes(
        _nodes("rdfs:label", "owl:deprecated", "dcterms:license", "dc:title", "skos:closeMatch", "CHEBI:1")
    )
    assert dropped == 5
    assert df["id"].tolist() == ["CHEBI:1"]


def test_real_ontology_terms_are_kept(transform):
    """The filter must key on the prefix, not on anything fuzzier."""
    keep = _nodes("CHEBI:15377", "GO:0008150", "UPA:UCR00014", "NCBITaxon:562", "FOODON:03301710", "PATO:0001421")
    df, dropped = transform._drop_metamodel_nodes(keep)
    assert dropped == 0
    assert len(df) == 6


def test_both_dcterms_spellings_go(transform):
    """
    The same IRI arrived as `dcterms:license` or `dct:license` depending on the run.

    Dropping the row removes the nondeterminism without having to pick a winner
    between two prefixes for one namespace.
    """
    df, dropped = transform._drop_metamodel_nodes(_nodes("dcterms:license", "dct:license", "EC:1.1.1.1"))
    assert dropped == 2
    assert df["id"].tolist() == ["EC:1.1.1.1"]


def test_a_frame_without_an_id_column_is_returned_unchanged(transform):
    """Mirrors _drop_metamodel_edges: no column, no opinion."""
    df = pd.DataFrame({"category": ["biolink:OntologyClass"]})
    out, dropped = transform._drop_metamodel_nodes(df)
    assert dropped == 0
    assert out.equals(df)


def test_a_bare_id_without_a_prefix_is_kept(transform):
    """`split(":")[0]` on an id with no colon yields the whole id; it must not match by accident."""
    df, dropped = transform._drop_metamodel_nodes(_nodes("owl", "rdfs", "CHEBI:1"))
    # "owl" and "rdfs" have no colon, so they are not prefixed CURIEs -- but they
    # would collide with the prefix set. Documenting the behaviour deliberately.
    assert dropped == 2, "a bare token equal to a metamodel prefix is treated as one"
    assert df["id"].tolist() == ["CHEBI:1"]


def test_the_prefix_set_covers_what_was_measured():
    """The ten prefixes actually seen in the 2026-09-10 ontology outputs."""
    for prefix in ("dc", "dct", "dcterms", "oio", "owl", "rdfs", "skos"):
        assert prefix in METAMODEL_NODE_PREFIXES
