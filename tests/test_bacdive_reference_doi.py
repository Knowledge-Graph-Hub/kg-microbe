"""Tests for resolving BacDive ``@ref`` ids to publication DOIs."""

from __future__ import annotations

from kg_microbe.transform_utils.bacdive.bacdive import (
    _StrainProvenanceWriter,
    reference_dois,
)


class _DummyWriter:

    """Minimal csv.writer stand-in that captures rows in memory for inspection."""

    def __init__(self):
        """Start with an empty list of captured rows."""
        self.rows: list[list] = []

    def writerow(self, row):
        """Capture ``row`` as a plain list for later assertions."""
        self.rows.append(list(row))


def _writer():
    """A provenance writer over a dummy sink, with knowledge_source at column 4."""
    sink = _DummyWriter()
    return sink, _StrainProvenanceWriter(
        sink, knowledge_source="infores:bacdive", ks_column_index=4
    )


def _row():
    """A strain-derived edge row of the shape the bacdive transform emits."""
    return [
        "kgmicrobe.strain:bacdive_1",
        "METPO:2000002",
        "CHEBI:17234",
        "RO:0000057",
        "infores:bacdive",
        "observation",
        "manual_agent",
    ]


def test_reference_dois_maps_ref_id_to_doi():
    """A Reference entry with a real DOI is keyed by its integer ``@id``."""
    record = {
        "Reference": [
            {"@id": 20215, "doi/url": "10.1099/ijsem.0.004332"},
            {"@id": 12345, "doi/url": "10.1099/ijs.0.02862-0"},
        ]
    }
    assert reference_dois(record) == {
        20215: "10.1099/ijsem.0.004332",
        12345: "10.1099/ijs.0.02862-0",
    }


def test_reference_dois_accepts_a_single_dict():
    """Records with one reference store a dict rather than a list."""
    record = {"Reference": {"@id": 7, "doi/url": "10.1099/ijs.0.63521-0"}}
    assert reference_dois(record) == {7: "10.1099/ijs.0.63521-0"}


def test_reference_dois_skips_non_publications():
    """Catalogue URLs and BacDive's own record DOI are not citations.

    Both would otherwise attach confident-looking provenance that leads back to a catalogue
    entry or to the record already named by ``primary_knowledge_source``, rather than to a
    paper someone can read.
    """
    record = {
        "Reference": [
            {"@id": 1, "doi/url": "https://www.dsmz.de/collection/catalogue/details/culture/DSM-1"},
            {"@id": 2, "doi/url": "10.13145/bacdive1.20221219.7"},
            {"@id": 3, "doi/url": "10.1099/ijs.0.02862-0"},
        ]
    }
    assert reference_dois(record) == {3: "10.1099/ijs.0.02862-0"}


def test_reference_dois_handles_missing_or_malformed():
    """A record with no usable Reference section yields an empty map, not an error."""
    assert reference_dois({}) == {}
    assert reference_dois({"Reference": None}) == {}
    assert reference_dois({"Reference": [{"@id": None, "doi/url": "10.1/x"}]}) == {}
    assert reference_dois({"Reference": [{"@id": "not-an-int", "doi/url": "10.1/x"}]}) == {}


def test_publication_is_appended_to_knowledge_source():
    """A supplied DOI joins the source and strain id in the same list literal."""
    sink, writer = _writer()
    writer.writerow(_row(), publication="doi:10.1099/ijs.0.02862-0")
    assert sink.rows[0][4] == (
        "['infores:bacdive', 'bacdive:1', 'doi:10.1099/ijs.0.02862-0']"
    )


def test_output_is_unchanged_without_a_publication():
    """Sections not yet threaded must emit exactly what they emitted before.

    This is what makes the change safe to land one section at a time: every call site that
    does not pass ``publication`` is byte-for-byte identical to the previous behaviour.
    """
    sink, writer = _writer()
    writer.writerow(_row())
    assert sink.rows[0][4] == "['infores:bacdive', 'bacdive:1']"


def test_non_strain_rows_are_untouched_even_with_a_publication():
    """Ontology-axiom edges have no strain endpoint, so nothing is rewritten."""
    sink, writer = _writer()
    row = ["METPO:1000001", "biolink:subclass_of", "METPO:1000002", "rdfs:subClassOf",
           "infores:bacdive", "observation", "manual_agent"]
    writer.writerow(row, publication="doi:10.1099/ijs.0.02862-0")
    assert sink.rows[0][4] == "infores:bacdive"
