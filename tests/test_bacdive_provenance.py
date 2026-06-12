"""Tests for the bacdive strain-provenance writer wrapper."""

from __future__ import annotations

from kg_microbe.transform_utils.bacdive.bacdive import _StrainProvenanceWriter


class _DummyWriter:

    """Minimal csv.writer stand-in that captures rows in memory for inspection."""

    def __init__(self):
        """Start with an empty list of captured rows."""
        self.rows: list[list] = []

    def writerow(self, row):
        """Capture ``row`` as a plain list for later assertions."""
        self.rows.append(list(row))


def _make_writer() -> tuple[_StrainProvenanceWriter, _DummyWriter]:
    inner = _DummyWriter()
    wrapped = _StrainProvenanceWriter(
        inner,
        knowledge_source="infores:bacdive",
        ks_column_index=4,
    )
    return wrapped, inner


def test_strain_subject_with_infores_rewrites_to_list_form():
    """A bacdive grows-in edge from a strain subject should gain the strain id in its KS."""
    wrapped, inner = _make_writer()
    wrapped.writerow(
        [
            "kgmicrobe.strain:bacdive_160227",
            "METPO:2000517",
            "mediadive.medium:1",
            "rel",
            "infores:bacdive",
            "k",
            "a",
        ]
    )
    assert inner.rows[0][4] == "['infores:bacdive', 'bacdive:160227']"


def test_strain_object_with_infores_rewrites_to_list_form():
    """An isolation-source-style edge with the strain as object also gets the strain id added."""
    wrapped, inner = _make_writer()
    wrapped.writerow(
        [
            "BTO:0003114",
            "biolink:location_of",
            "kgmicrobe.strain:bacdive_999",
            "rel",
            "infores:bacdive",
            "k",
            "a",
        ]
    )
    assert inner.rows[0][4] == "['infores:bacdive', 'bacdive:999']"


def test_non_strain_endpoints_passthrough():
    """A pure ontology edge (no strain endpoint) must keep the singleton infores:bacdive KS."""
    wrapped, inner = _make_writer()
    wrapped.writerow(
        [
            "NCBITaxon:100",
            "biolink:subclass_of",
            "NCBITaxon:200",
            "rel",
            "infores:bacdive",
            "k",
            "a",
        ]
    )
    assert inner.rows[0][4] == "infores:bacdive"


def test_different_knowledge_source_passthrough():
    """Edges with a different KS (e.g. infores:metpo on a METPO axiom) must not be touched."""
    wrapped, inner = _make_writer()
    wrapped.writerow(["X:1", "p", "Y:2", "rel", "infores:metpo", "k", "a"])
    assert inner.rows[0][4] == "infores:metpo"


def test_bare_bacdive_literal_passthrough():
    """The literal ``"bacdive"`` source (isolation-source path) is out of scope; must pass through unchanged."""
    wrapped, inner = _make_writer()
    wrapped.writerow(["BTO:1", "p", "kgmicrobe.strain:bacdive_5", "rel", "bacdive", "k", "a"])
    assert inner.rows[0][4] == "bacdive"


def test_header_row_unaffected():
    """Header rows (no provenance match) pass through unchanged."""
    wrapped, inner = _make_writer()
    header = ["subject", "predicate", "object", "relation", "primary_knowledge_source", "knowledge_level", "agent_type"]
    wrapped.writerow(header)
    assert inner.rows[0] == header


def test_writerows_applies_to_each_row():
    """``writerows`` must funnel each row through the per-row augmentation."""
    wrapped, inner = _make_writer()
    wrapped.writerows(
        [
            ["kgmicrobe.strain:bacdive_1", "p", "X:1", "rel", "infores:bacdive", "k", "a"],
            ["NCBITaxon:9", "p", "X:1", "rel", "infores:bacdive", "k", "a"],
        ]
    )
    assert inner.rows[0][4] == "['infores:bacdive', 'bacdive:1']"
    assert inner.rows[1][4] == "infores:bacdive"
