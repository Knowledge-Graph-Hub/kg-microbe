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
import inspect
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


def test_strain_curie_matches_the_emitted_node_prefix():
    """
    The LPSN edge subject must be the strain CURIE this transform emits as a node.

    The edge previously used ``bacdive:NNN``, which is never written as a
    node row, so all ~62 K of these edges were orphaned and KGX
    synthesized a bare ``biolink:NamedThing`` stub for each one in the
    merged KG.
    """
    assert BacDiveTransform._strain_curie("7249") == "kgmicrobe.strain:bacdive_7249"
    # The bare source prefix is precisely the form that produced the orphans.
    assert not BacDiveTransform._strain_curie("7249").startswith("bacdive:")


def test_lpsn_edge_uses_subclass_of_not_in_taxon():
    """
    Strain → LPSN record is emitted as ``biolink:subclass_of``/``rdfs:subClassOf``.

    Both endpoints are typed ``biolink:OrganismTaxon``, and this transform
    already relates the same strain nodes to their NCBITaxon species with
    ``subclass_of``. ``biolink:in_taxon`` asserts instance-of, which
    contradicts that class-like typing and made this edge the only
    strain→taxon link in the transform using a different predicate.
    """
    source = Path(inspect.getsourcefile(BacDiveTransform)).read_text()
    lpsn_edge_block = source.split("lpsn_record_no = self._lookup_lpsn")[1].split("synonyms =")[0]
    assert "SUBCLASS_PREDICATE" in lpsn_edge_block
    assert "RDFS_SUBCLASS_OF" in lpsn_edge_block
    assert "IN_TAXON_PREDICATE" not in lpsn_edge_block
    # Pin the subject positively on the helper, and ban the raw source prefix
    # outright. Asserting only that one literal spelling of the old
    # concatenation is absent passes for every other spelling of it —
    # including the in-scope `bacdive_key`, which lacks the strain prefix.
    assert "strain_curie = self._strain_curie(key)" in lpsn_edge_block
    assert "strain_curie," in lpsn_edge_block
    assert "BACDIVE_PREFIX" not in lpsn_edge_block
    assert "bacdive_key" not in lpsn_edge_block


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


def test_lpsn_edge_carries_the_list_form_knowledge_source():
    """
    The LPSN cross-ref edge must carry the same list-form provenance as its siblings.

    #680 changed the subject from ``bacdive:NNN`` to
    ``kgmicrobe.strain:bacdive_NNN``, which as a side effect brought all
    62,096 of these edges under ``_StrainProvenanceWriter``. The provenance
    flipped from ``infores:bacdive`` to ``['infores:bacdive', 'bacdive:NNN']``.

    That is the wanted value — mediadive emits a byte-identical literal so KGX
    collapses the two rows by exact-string match at merge — but it was an
    unintended side effect, unmentioned in any commit on #680, and nothing
    pinned it. A refactor could flip it back silently (#688).
    """
    from kg_microbe.transform_utils.bacdive.bacdive import _StrainProvenanceWriter

    captured = []

    class _Sink:

        """Collect rows instead of writing them."""

        def writerow(self, row):
            """Record one row."""
            captured.append(list(row))

    writer = _StrainProvenanceWriter(_Sink(), knowledge_source="infores:bacdive", ks_column_index=4)
    writer.writerow(
        ["kgmicrobe.strain:bacdive_7249", "biolink:subclass_of", "lpsn:12345", "rdfs:subClassOf", "infores:bacdive"]
    )

    assert captured[0][4] == "['infores:bacdive', 'bacdive:7249']", captured[0][4]


def test_non_strain_edges_keep_their_bare_knowledge_source():
    """
    The wrapper must fire only when an endpoint is a BacDive strain.

    METPO ontology axioms and isolation-source edges pass through untouched;
    rewriting those would invent strain provenance for rows that have none.
    """
    from kg_microbe.transform_utils.bacdive.bacdive import _StrainProvenanceWriter

    captured = []

    class _Sink:

        """Collect rows instead of writing them."""

        def writerow(self, row):
            """Record one row."""
            captured.append(list(row))

    writer = _StrainProvenanceWriter(_Sink(), knowledge_source="infores:bacdive", ks_column_index=4)
    writer.writerow(["METPO:1000601", "biolink:subclass_of", "METPO:1000600", "rdfs:subClassOf", "infores:bacdive"])
    writer.writerow(["kgmicrobe.strain:bacdive_7249", "biolink:location_of", "ENVO:00002006", "RO:1", "infores:metpo"])

    assert captured[0][4] == "infores:bacdive", "an ontology axiom must not gain strain provenance"
    assert captured[1][4] == "infores:metpo", "a different knowledge source must pass through"
