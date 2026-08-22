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


# The wrapper is positional, so the tests derive the column index the way
# production does (`edge_header.index(...)`) rather than hardcoding it. A pin
# that cannot notice the column moving is not pinning much (#741). Rows are
# full width for the same reason: the wrapper's `len(row) > ks_idx` guard means
# a short row passes without exercising the shape production writes.
_EDGE_HEADER = [
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


def _provenance_writer():
    """
    Build a `_StrainProvenanceWriter` over a capturing sink.

    :return: ``(captured_rows, writer, primary_knowledge_source_index)``.
    """
    from kg_microbe.transform_utils.bacdive.bacdive import _StrainProvenanceWriter

    captured = []

    class _Sink:
        """Collect rows instead of writing them."""

        def writerow(self, row):
            """Record one row."""
            captured.append(list(row))

    index = _EDGE_HEADER.index("primary_knowledge_source")
    return captured, _StrainProvenanceWriter(_Sink(), knowledge_source="infores:bacdive", ks_column_index=index), index


def _edge_row(subject, obj, knowledge_source):
    """
    Build a full-width edge row, matching what the transform actually writes.

    :param subject: Edge subject CURIE.
    :param obj: Edge object CURIE.
    :param knowledge_source: Value for the primary_knowledge_source column.
    :return: A row with one cell per column in the real edge header.
    """
    return [
        subject,
        "biolink:subclass_of",
        obj,
        "rdfs:subClassOf",
        knowledge_source,
        "knowledge_assertion",
        "manual_agent",
    ]


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


def _gss_row(record_no, genus, sp, status, link=""):
    """Build one GSS CSV row."""
    return {
        "genus_name": genus,
        "sp_epithet": sp,
        "subsp_epithet": "",
        "status": status,
        "record_no": record_no,
        "record_lnk": link,
    }


_CORRECT = "VP; sp. nov.; validly published under the ICNP; correct name"
_SYNONYM = "VP; sp. nov.; validly published under the ICNP; synonym"


def test_a_synonym_match_is_repointed_to_its_accepted_name(tmp_path):
    """
    A strain reported under an LPSN synonym must land under the accepted name.

    #680 made this edge `subclass_of`, so a synonym target places a living strain
    in the subsumption hierarchy beneath a deprecated class — 992 of 62,096 edges
    (#684). Dropping them would lose real information: the strain genuinely is
    that organism, LPSN has simply renamed it. `record_lnk` is LPSN's own
    crosswalk, so the edge is re-pointed instead.
    """
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            _gss_row("772466", "Abiotrophia", "adiacens", _SYNONYM, link="776611"),
            _gss_row("776611", "Granulicatella", "adiacens", _CORRECT),
        ],
    )
    index = _bare_transform(csv_path)._load_lpsn_name_index()

    assert index["Abiotrophia adiacens"] == ["776611"], "the synonym must resolve to the accepted record"
    assert index["Granulicatella adiacens"] == ["776611"]


def test_a_synonym_chain_is_followed_to_the_accepted_name(tmp_path):
    """Chains occur: 250 synonyms need two hops on the shipped GSS and 2 need three."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            _gss_row("1", "Aaa", "one", _SYNONYM, link="2"),
            _gss_row("2", "Bbb", "two", _SYNONYM, link="3"),
            _gss_row("3", "Ccc", "three", _CORRECT),
        ],
    )
    assert _bare_transform(csv_path)._load_lpsn_name_index()["Aaa one"] == ["3"]


def test_a_dead_end_synonym_keeps_its_own_record(tmp_path):
    """
    192 GSS rows are non-current with no `record_lnk`.

    There is nothing better to point them at, so they are left alone rather than
    dropped — losing the edge would be worse than an imperfect target.
    """
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(csv_path, [_gss_row("9", "Ddd", "four", _SYNONYM)])
    assert _bare_transform(csv_path)._load_lpsn_name_index()["Ddd four"] == ["9"]


def test_a_cyclic_synonym_chain_terminates(tmp_path):
    """No cycles exist in the shipped GSS, but a future release could introduce one."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(
        csv_path,
        [
            _gss_row("1", "Aaa", "one", _SYNONYM, link="2"),
            _gss_row("2", "Bbb", "two", _SYNONYM, link="1"),
        ],
    )
    index = _bare_transform(csv_path)._load_lpsn_name_index()
    assert index["Aaa one"] == ["1"], "a cycle must leave the record untouched, not hang"


def test_correct_names_are_left_alone(tmp_path):
    """The common case must be untouched: 26,866 of 34,301 rows are already current."""
    csv_path = tmp_path / "lpsn_gss.csv"
    _write_gss(csv_path, [_gss_row("100", "Escherichia", "coli", _CORRECT)])
    assert _bare_transform(csv_path)._load_lpsn_name_index()["Escherichia coli"] == ["100"]
