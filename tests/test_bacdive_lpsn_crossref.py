"""
Tests for BacDive → LPSN cross-ref helpers.

We exercise the ``_load_lpsn_name_index`` and ``_lookup_lpsn`` helpers in
isolation because the full ``BacDiveTransform.__init__`` pulls in the
NCBITaxon SQLite adapter (~13 GB) plus every METPO / GO / ChEBI adapter,
which makes a live end-to-end unit test impractical. Skipping the heavy
constructor via ``__new__`` and populating only the fields the helpers
touch is the standard pattern for isolating a single method in a
class that owns a heavy constructor.
"""

import csv
from pathlib import Path

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform


def _bare_transform(lpsn_csv: Path | None) -> BacDiveTransform:
    """
    Return a ``BacDiveTransform`` instance with only the fields the LPSN helpers need.

    ``__init__`` isn't called (that would pull the NCBI/GO/ChEBI adapters
    and the METPO mapping loaders). Instead we allocate via ``__new__``
    and hand-set the two attributes ``_load_lpsn_name_index`` and
    ``_lookup_lpsn`` use.
    """
    x = BacDiveTransform.__new__(BacDiveTransform)
    x.input_base_dir = lpsn_csv.parent if lpsn_csv else Path("/nonexistent")
    x._lpsn_stats = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    x.lpsn_name_index = x._load_lpsn_name_index()
    return x


def _write_gss(path: Path, rows):
    """Write a minimal LPSN GSS CSV that ``_load_lpsn_name_index`` can parse."""
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "genus_name",
                "sp_epithet",
                "subsp_epithet",
                "reference",
                "status",
                "authors",
                "address",
                "risk_grp",
                "nomenclatural_type",
                "record_no",
                "record_lnk",
            ],
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)


def test_missing_csv_returns_empty_index(tmp_path):
    """No lpsn_gss.csv on disk → empty index, no exceptions."""
    x = _bare_transform(tmp_path / "no_such.csv")
    assert x.lpsn_name_index == {}
    # Lookup on an empty index must silently return None.
    assert x._lookup_lpsn({"species": "Escherichia coli"}) is None
    assert x._lpsn_stats == {"matched": 0, "unmatched": 0, "ambiguous": 0}


def test_species_lookup_via_species_field(tmp_path):
    """The ``species`` field on the LPSN block maps to a single record_no."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            {
                "genus_name": "Escherichia",
                "sp_epithet": "coli",
                "record_no": "1002",
                "address": "https://lpsn.dsmz.de/species/escherichia-coli",
                "status": "correct name",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            }
        ],
    )
    x = _bare_transform(csv_path)
    result = x._lookup_lpsn({"species": "Escherichia coli"})
    assert result == "1002"
    assert x._lpsn_stats["matched"] == 1
    assert x._lpsn_stats["unmatched"] == 0


def test_full_scientific_name_fallback_strips_html(tmp_path):
    """When ``species`` is absent, parse the first two tokens of ``full scientific name``."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            {
                "genus_name": "Moraxella",
                "sp_epithet": "canis",
                "record_no": "555",
                "address": "https://lpsn.dsmz.de/species/moraxella-canis",
                "status": "correct name",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            }
        ],
    )
    x = _bare_transform(csv_path)
    # BacDive's raw full-scientific-name string wraps genus/species in <I> tags
    # and appends the authority + year.
    lpsn_block = {
        "full scientific name": "<I>Moraxella</I> <I>canis</I> Jannes et al. 1993",
    }
    assert x._lookup_lpsn(lpsn_block) == "555"


def test_unknown_species_counts_as_unmatched(tmp_path):
    """A species name not in the LPSN index → None, unmatched counter incremented."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            {
                "genus_name": "Escherichia",
                "sp_epithet": "coli",
                "record_no": "1002",
                "address": "",
                "status": "",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            }
        ],
    )
    x = _bare_transform(csv_path)
    assert x._lookup_lpsn({"species": "Notgenus notspecies"}) is None
    assert x._lpsn_stats["unmatched"] == 1
    assert x._lpsn_stats["matched"] == 0


def test_ambiguous_species_emits_no_edge(tmp_path):
    """Same species name mapping to two LPSN record_no's → None, ambiguous counter incremented."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            {
                "genus_name": "Escherichia",
                "sp_epithet": "coli",
                "record_no": "1002",
                "address": "",
                "status": "correct name",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            },
            {
                "genus_name": "Escherichia",
                "sp_epithet": "coli",
                "record_no": "9999",
                "address": "",
                "status": "later heterotypic synonym",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            },
        ],
    )
    x = _bare_transform(csv_path)
    assert x._lookup_lpsn({"species": "Escherichia coli"}) is None
    assert x._lpsn_stats["ambiguous"] == 1


def test_blank_lpsn_block_returns_none(tmp_path):
    """An empty LPSN block → None, no stat increment."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            {
                "genus_name": "Escherichia",
                "sp_epithet": "coli",
                "record_no": "1002",
                "address": "",
                "status": "correct name",
                "authors": "",
                "reference": "",
                "subsp_epithet": "",
                "risk_grp": "",
                "nomenclatural_type": "",
                "record_lnk": "",
            }
        ],
    )
    x = _bare_transform(csv_path)
    assert x._lookup_lpsn({}) is None
    assert x._lookup_lpsn(None) is None
    # None + empty are treated as no-op; unmatched not incremented.
    assert x._lpsn_stats["unmatched"] == 0
