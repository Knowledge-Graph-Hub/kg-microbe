"""Tests for the LPSN transform."""

import csv
from pathlib import Path

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import (
    DEPRECATED_STATUSES,
    LPSN_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    LPSNTransform,
)

FIXTURE_DIR = Path(__file__).parent / "resources"


class _NoNCBI:

    """OAK-adapter stub used when a test wants NCBITaxon enrichment disabled."""

    def curies_by_label(self, label):
        """Return an empty list — every LPSN name is treated as unmatched."""
        return []


class _NoGTDB:

    """GTDB-index stub used when a test wants GTDB enrichment disabled."""

    def curies_by_rank_name(self, rank, name):
        """Return an empty list — every LPSN name is treated as unmatched."""
        return []


class _FakeGTDB:

    """Simple GTDB-index fake keyed on ``(rank, name)`` tuples."""

    def __init__(self, mapping):
        """Store the mapping and answer ``curies_by_rank_name`` from it."""
        self._map = mapping

    def curies_by_rank_name(self, rank, name):
        """Return the CURIE list for ``(rank, name)`` (empty if unknown)."""
        return list(self._map.get((rank, name), []))


@pytest.fixture()
def lpsn_transform(tmp_path):
    """
    Return an ``LPSNTransform`` configured to read the fixture CSV.

    The transform's ``input_base_dir`` is set to ``tests/resources`` so
    ``lpsn_gss.csv`` resolves via the base ``Transform`` class, and
    ``output_dir`` is set to a per-test temp dir so nodes.tsv /
    edges.tsv land in isolation.

    A no-op NCBITaxon adapter is injected so the default fixture never
    depends on the local ``data/raw/ncbitaxon.owl`` (~13 GB) being on
    disk. Tests that specifically exercise the NCBI cross-ref path use
    ``lpsn_transform_with_ncbi`` instead.
    """
    return LPSNTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        ncbi_impl=_NoNCBI(),
        gtdb_index=_NoGTDB(),
    )


def _read_tsv(path: Path) -> list[dict]:
    """Read a TSV into a list of dicts (header row → per-row dicts)."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_nodes_emitted_for_every_valid_row(lpsn_transform):
    """One node per LPSN record (fixture has 6 rows, all with record_no)."""
    lpsn_transform.run()
    nodes = _read_tsv(lpsn_transform.output_node_file)
    assert len(nodes) == 6
    ids = {n["id"] for n in nodes}
    assert ids == {
        f"{LPSN_PREFIX}1001",
        f"{LPSN_PREFIX}1002",
        f"{LPSN_PREFIX}1003",
        f"{LPSN_PREFIX}1010",
        f"{LPSN_PREFIX}1011",
        f"{LPSN_PREFIX}1099",
    }


def test_node_fields_are_shaped_correctly(lpsn_transform):
    """A species row emits id/category/name/description/xref/provided_by."""
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    ecoli = nodes[f"{LPSN_PREFIX}1002"]
    assert ecoli["category"] == "biolink:OrganismTaxon"
    assert ecoli["name"] == "Escherichia coli"
    assert "Migula" in ecoli["description"]
    assert ecoli["xref"].startswith("https://lpsn.dsmz.de/species/")
    assert ecoli["provided_by"] == LPSN_KNOWLEDGE_SOURCE


def test_illegitimate_row_is_marked_deprecated(lpsn_transform):
    """`status = "illegitimate name"` sets deprecated=True."""
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    subsp = nodes[f"{LPSN_PREFIX}1003"]
    assert subsp["deprecated"] == "True"
    # Sanity: correct-name rows are NOT deprecated.
    assert nodes[f"{LPSN_PREFIX}1002"]["deprecated"] == ""


def test_synonym_status_is_deprecated(lpsn_transform):
    """`status = "synonym"` also flags deprecated (per DEPRECATED_STATUSES)."""
    assert "synonym" in DEPRECATED_STATUSES
    lpsn_transform.run()
    nodes = {n["id"]: n for n in _read_tsv(lpsn_transform.output_node_file)}
    assert nodes[f"{LPSN_PREFIX}1099"]["deprecated"] == "True"


def test_species_gets_subclass_edge_to_genus(lpsn_transform):
    """Escherichia coli (1002) → Escherichia (1001)."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["object"] == f"{LPSN_PREFIX}1001"]
    assert len(hits) == 1
    assert hits[0]["predicate"] == "biolink:subclass_of"
    assert hits[0]["relation"] == "rdfs:subClassOf"
    assert hits[0]["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_subspecies_gets_subclass_edge_to_species(lpsn_transform):
    """Escherichia coli inactive (1003) → Escherichia coli (1002) subclass edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1003"
        and e["object"] == f"{LPSN_PREFIX}1002"
        and e["predicate"] == "biolink:subclass_of"
    ]
    assert len(hits) == 1


def test_synonym_row_emits_same_as_edge_to_correct_name(lpsn_transform):
    """Row 1003 has ``record_lnk = 1002`` → biolink:same_as edge 1003 → 1002."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1003"
        and e["object"] == f"{LPSN_PREFIX}1002"
        and e["predicate"] == "biolink:same_as"
    ]
    assert len(hits) == 1
    assert hits[0]["relation"] == "skos:exactMatch"
    assert hits[0]["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_row_without_record_lnk_emits_no_same_as_edge(lpsn_transform):
    """The current-name species row 1002 has blank record_lnk → no same_as edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["predicate"] == "biolink:same_as"]
    assert hits == []


def test_orphan_species_produces_no_edge(lpsn_transform):
    """Notgenus orphan (1099) has no matching genus row → no subclass edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    orphan_edges = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1099"]
    assert orphan_edges == []


def test_missing_csv_raises_file_not_found(tmp_path):
    """Instantiating with an empty input dir and calling run() raises FNFE."""
    xform = LPSNTransform(input_dir=tmp_path, output_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="LPSN GSS CSV not found"):
        xform.run()


def test_missing_csv_does_not_trigger_ncbitaxon_build(tmp_path, monkeypatch):
    """
    Round 34: __init__ must not eagerly resolve NCBITaxon.

    ``kg transform -s lpsn`` on a fresh checkout used to call
    ``get_ontology_adapter("ncbitaxon")`` from ``__init__``, which starts
    a multi-hour ~13 GB build — only to have ``run()`` immediately fail
    because the manually-downloaded ``lpsn_gss.csv`` is absent. The
    constructor must be inert with respect to the ontologies, so an
    absent CSV fails fast without triggering any build.
    """
    from kg_microbe.transform_utils.lpsn import lpsn as lpsn_module

    calls = []

    def _tripwire(*args, **kwargs):
        """Record any attempt to auto-load ontology resources."""
        calls.append(("_load_ncbi_adapter", args, kwargs))
        return None

    def _gtdb_tripwire(*args, **kwargs):
        """Record any attempt to auto-load the GTDB index."""
        calls.append(("_load_gtdb_index", args, kwargs))
        return None

    monkeypatch.setattr(lpsn_module.LPSNTransform, "_load_ncbi_adapter", staticmethod(_tripwire))
    monkeypatch.setattr(lpsn_module.LPSNTransform, "_load_gtdb_index", staticmethod(_gtdb_tripwire))

    xform = LPSNTransform(input_dir=tmp_path, output_dir=tmp_path)
    assert calls == [], "the constructor must not auto-load ontologies"

    with pytest.raises(FileNotFoundError, match="LPSN GSS CSV not found"):
        xform.run()
    assert calls == [], "an absent CSV must fail before any ontology load starts"


def test_species_gets_close_match_edges_for_each_type_strain_deposit(lpsn_transform):
    """
    Emit one close_match edge per culture-collection deposit for a species row.

    E. coli (1002) has ``ATCC 11775 = DSM 30083 = JCM 1649`` and should emit
    one edge per deposit to the shared strain CURIE that BacDive
    also uses (``kgmicrobe.strain:<code>``).
    """
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1002" and e["predicate"] == "biolink:close_match"
    ]
    objects = {e["object"] for e in close_matches}
    assert objects == {
        "kgmicrobe.strain:ATCC-11775",
        "kgmicrobe.strain:DSM-30083",
        "kgmicrobe.strain:JCM-1649",
    }
    for e in close_matches:
        assert e["relation"] == "skos:closeMatch"
        assert e["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_subspecies_gets_close_match_edge(lpsn_transform):
    """Subspecies row (1003) with ``DSM 30083`` emits one close_match edge."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1003" and e["predicate"] == "biolink:close_match"
    ]
    assert len(close_matches) == 1
    assert close_matches[0]["object"] == "kgmicrobe.strain:DSM-30083"


def test_genus_row_does_not_emit_close_match(lpsn_transform):
    """
    Genus rows must not emit close_match edges.

    Their ``nomenclatural_type`` carries the type species name, not a
    culture-collection deposit.
    """
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1001" and e["predicate"] == "biolink:close_match"
    ]
    assert close_matches == []


def test_row_with_no_nomenclatural_type_emits_no_close_match(lpsn_transform):
    """The synonym row (1099) has blank ``nomenclatural_type`` → no edges."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    close_matches = [
        e for e in edges if e["subject"] == f"{LPSN_PREFIX}1099" and e["predicate"] == "biolink:close_match"
    ]
    assert close_matches == []


# --------------------------------------------------------------------------
# NCBITaxon cross-refs
# --------------------------------------------------------------------------


class _FakeNCBI:

    """Minimal stub of the subset of OAK's adapter API that LPSN uses."""

    def __init__(self, mapping):
        """Store the ``{scientific_name: [CURIE, ...]}`` lookup table."""
        self._map = mapping

    def curies_by_label(self, label):
        """Return the CURIE list for ``label`` (empty list if unknown)."""
        return list(self._map.get(label, []))


@pytest.fixture()
def lpsn_transform_with_ncbi(tmp_path):
    """
    LPSNTransform wired to a fake NCBI adapter with three canned answers.

    - ``Escherichia coli`` → single hit ``NCBITaxon:562`` (should emit an edge)
    - ``Escherichia coli inactive`` → **two** hits (ambiguous — no edge)
    - ``Bacillus subtilis`` → zero hits (unmatched — no edge)
    """
    fake = _FakeNCBI(
        {
            "Escherichia coli": ["NCBITaxon:562"],
            "Escherichia coli inactive": ["NCBITaxon:99999", "NCBITaxon:99998"],
            # Bacillus subtilis intentionally absent.
        }
    )
    return LPSNTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        ncbi_impl=fake,
        gtdb_index=_NoGTDB(),
    )


def test_single_hit_emits_ncbitaxon_close_match(lpsn_transform_with_ncbi):
    """E. coli (1002) → NCBITaxon:562 close_match edge."""
    lpsn_transform_with_ncbi.run()
    edges = _read_tsv(lpsn_transform_with_ncbi.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1002"
        and e["object"] == "NCBITaxon:562"
        and e["predicate"] == "biolink:close_match"
    ]
    assert len(hits) == 1
    assert hits[0]["relation"] == "skos:closeMatch"
    assert hits[0]["primary_knowledge_source"] == LPSN_KNOWLEDGE_SOURCE


def test_ambiguous_hit_emits_no_edge(lpsn_transform_with_ncbi):
    """Subspecies 1003's fake mapping returns 2 hits → no edge."""
    lpsn_transform_with_ncbi.run()
    edges = _read_tsv(lpsn_transform_with_ncbi.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1003" and e["object"].startswith("NCBITaxon:")]
    assert hits == []
    assert lpsn_transform_with_ncbi._ncbi_stats["ambiguous"] == 1


def test_unmatched_row_emits_no_edge(lpsn_transform_with_ncbi):
    """B. subtilis (1011) has no fake mapping → no edge, counted as unmatched."""
    lpsn_transform_with_ncbi.run()
    edges = _read_tsv(lpsn_transform_with_ncbi.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1011" and e["object"].startswith("NCBITaxon:")]
    assert hits == []
    # unmatched count includes 1011 + 1099 (both species-rank rows with no fake
    # mapping): the orphan Notgenus (1099) is also species-rank so it counts.
    assert lpsn_transform_with_ncbi._ncbi_stats["unmatched"] >= 1


def test_ncbi_disabled_when_adapter_absent(lpsn_transform):
    """The default fixture (no ncbi_impl) emits no NCBITaxon edges at all."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    ncbi_edges = [e for e in edges if e["object"].startswith("NCBITaxon:")]
    assert ncbi_edges == []


def test_genus_row_now_gets_ncbi_edge_when_synonym_matches(tmp_path):
    """
    Genus rows match via bacterial-subtree-filtered exact-synonym lookup.

    NCBI stores each disambiguated genus's bare form as an
    ``oio:hasExactSynonym`` on the disambiguated CURIE (``Bacillus
    <firmicutes>`` has ``hasExactSynonym Bacillus``), and the subtree
    filter guarantees only the bacterial candidate is returned. The
    injected fake stands in for that pre-resolved behavior.
    """
    fake = _FakeNCBI({"Escherichia": ["NCBITaxon:561"]})
    xform = LPSNTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        ncbi_impl=fake,
        gtdb_index=_NoGTDB(),
    )
    xform.run()
    edges = _read_tsv(xform.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1001"
        and e["object"] == "NCBITaxon:561"
        and e["predicate"] == "biolink:close_match"
    ]
    assert len(hits) == 1


# --------------------------------------------------------------------------
# GTDB cross-refs
# --------------------------------------------------------------------------


@pytest.fixture()
def lpsn_transform_with_gtdb(tmp_path):
    """
    LPSNTransform wired to a fake GTDB index with canned answers.

    Fixture rows and their fake GTDB answers:
    - genus ``Escherichia`` (1001) → ``GTDB:g__Escherichia``
    - species ``Escherichia coli`` (1002) → ``GTDB:s__Escherichia_coli``
    - subspecies ``Escherichia coli inactive`` (1003) → SKIPPED (no rank)
    - genus ``Bacillus`` (1010) → 2 hits (ambiguous, no edge)
    - species ``Bacillus subtilis`` (1011) → 0 hits (unmatched)
    - synonym ``Notgenus orphan`` (1099) → not in map (unmatched)
    """
    fake = _FakeGTDB(
        {
            ("g__", "Escherichia"): ["GTDB:g__Escherichia"],
            ("s__", "Escherichia coli"): ["GTDB:s__Escherichia_coli"],
            ("g__", "Bacillus"): ["GTDB:g__Bacillus", "GTDB:g__Bacillus_A"],
            # Bacillus subtilis and Notgenus orphan intentionally absent.
        }
    )
    return LPSNTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        ncbi_impl=_NoNCBI(),
        gtdb_index=fake,
    )


def test_species_gets_gtdb_close_match(lpsn_transform_with_gtdb):
    """Species row → single-hit GTDB match emitted as biolink:close_match."""
    lpsn_transform_with_gtdb.run()
    edges = _read_tsv(lpsn_transform_with_gtdb.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1002"
        and e["object"] == "GTDB:s__Escherichia_coli"
        and e["predicate"] == "biolink:close_match"
    ]
    assert len(hits) == 1
    assert hits[0]["relation"] == "skos:closeMatch"


def test_genus_gets_gtdb_close_match(lpsn_transform_with_gtdb):
    """Genus row → GTDB g__ match emitted."""
    lpsn_transform_with_gtdb.run()
    edges = _read_tsv(lpsn_transform_with_gtdb.output_edge_file)
    hits = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}1001"
        and e["object"] == "GTDB:g__Escherichia"
        and e["predicate"] == "biolink:close_match"
    ]
    assert len(hits) == 1


def test_subspecies_row_skips_gtdb(lpsn_transform_with_gtdb):
    """LPSN subspecies rows never get GTDB edges (no subspecies rank in GTDB)."""
    lpsn_transform_with_gtdb.run()
    edges = _read_tsv(lpsn_transform_with_gtdb.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1003" and e["object"].startswith("GTDB:")]
    assert hits == []


def test_ambiguous_gtdb_hit_emits_no_edge(lpsn_transform_with_gtdb):
    """Multi-hit GTDB lookup → no edge, ambiguous counter incremented."""
    lpsn_transform_with_gtdb.run()
    edges = _read_tsv(lpsn_transform_with_gtdb.output_edge_file)
    hits = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}1010" and e["object"].startswith("GTDB:")]
    assert hits == []
    assert lpsn_transform_with_gtdb._gtdb_stats["ambiguous"] >= 1


def test_gtdb_disabled_when_index_absent(lpsn_transform):
    """The default fixture (no gtdb_index) emits no GTDB edges."""
    lpsn_transform.run()
    edges = _read_tsv(lpsn_transform.output_edge_file)
    gtdb_edges = [e for e in edges if e["object"].startswith("GTDB:")]
    assert gtdb_edges == []
