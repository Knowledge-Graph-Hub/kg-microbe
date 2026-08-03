"""Tests for the MicrobeDecoder transform."""

import csv
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    BERGEY_KNOWLEDGE_SOURCE,
    CLOSE_MATCH_PREDICATE,
    COMPOUND_PREFIX,
    FAPROTAX_KNOWLEDGE_SOURCE,
    HAS_PHENOTYPE_PREDICATE,
    LITERATURE_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    PRODUCES_PREDICATE,
    TRAIT_PREFIX,
    VPI_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

FIXTURE_DIR = Path(__file__).parent / "resources" / "microbedecoder"


class _NoChebi:

    """
    ChemicalMappingLoader stub returning None for every lookup.

    Keeps tests self-contained (no ChEBI mapping file dependency) and
    exercises the ``kgmicrobe.compound:<slug>`` placeholder fallback
    path deterministically.
    """

    def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
        """Return None for every lookup."""
        del label, fuzzy_stereochemistry
        return None


@pytest.fixture()
def microbedecoder_transform(tmp_path):
    """
    Return a ``MicrobeDecoderTransform`` configured to read the fixture CSV.

    Points ``input_base_dir`` at ``tests/resources/microbedecoder`` so
    ``database.csv`` is picked up by the transform's default resolve chain,
    and ``output_dir`` at a per-test temp dir so nodes.tsv / edges.tsv
    land in isolation. ``_NoChebi`` is injected so the tests never depend
    on the unified chemical mapping file being present.
    """
    return MicrobeDecoderTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        chemical_loader=_NoChebi(),
    )


def _read_tsv(path: Path) -> list:
    """Read a TSV into a list of dicts (header row → per-row dicts)."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ---------------------------------------------------------------------------
# Node emission
# ---------------------------------------------------------------------------


def test_lpsn_subject_nodes_are_not_stubbed(microbedecoder_transform):
    """
    LPSN taxa are the ``lpsn`` transform's product; MicrobeDecoder must not stub.

    Per the add-transform skill's Phase 6 anti-patterns: "Do NOT emit
    stub nodes for cross-referenced entities that already exist in
    KG-Microbe — emit the edge, and rely on merge-time reconciliation."
    Every ``lpsn:<LPSN_ID>`` appears as an edge subject, but never as a
    node in this transform's own output.
    """
    microbedecoder_transform.run()
    nodes = _read_tsv(microbedecoder_transform.output_node_file)
    lpsn_node_ids = {n["id"] for n in nodes if n["id"].startswith(LPSN_PREFIX)}
    assert lpsn_node_ids == set(), (
        f"MicrobeDecoder must not emit lpsn:* nodes (lpsn transform owns them); found: {sorted(lpsn_node_ids)}"
    )
    # But every subject on emitted edges IS an lpsn:<id>, so downstream
    # merge glues them to the lpsn transform's authoritative rows.
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    edge_subject_lpsn_ids = {e["subject"] for e in edges if e["subject"].startswith(LPSN_PREFIX)}
    assert edge_subject_lpsn_ids == {
        f"{LPSN_PREFIX}101",
        f"{LPSN_PREFIX}202",
        f"{LPSN_PREFIX}303",
        f"{LPSN_PREFIX}404",
        f"{LPSN_PREFIX}505",
        f"{LPSN_PREFIX}606",
    }, "every non-blank LPSN_ID row produces edges keyed on lpsn:<id>"


def test_empty_lpsn_row_is_skipped(microbedecoder_transform):
    """The fixture's trailing empty-LPSN_ID row must not produce any output."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    subjects = {e["subject"] for e in edges}
    # Every edge subject is a lpsn:<non-empty-id>; the blank row's would be
    # `lpsn:` (no local) or empty, neither of which should appear.
    assert all(s.startswith(LPSN_PREFIX) and len(s) > len(LPSN_PREFIX) for s in subjects)


# ---------------------------------------------------------------------------
# Crosswalk edges (novel identity mapping)
# ---------------------------------------------------------------------------


def test_crosswalk_edges_use_close_match(microbedecoder_transform):
    """Every crosswalk edge is a ``biolink:close_match`` from lpsn:<id> to the target."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)

    # LPSN_ID=101 has all 5 crosswalk cells populated
    e_101 = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}101" and e["predicate"] == CLOSE_MATCH_PREDICATE]
    objects = {e["object"] for e in e_101}
    assert "NCBITaxon:1423" in objects
    assert "GTDB:d__Bacteria;g__Bacillus;s__Bacillus subtilis" in objects
    assert "bacdive:BAC01" in objects
    assert "GOLD:Gs0000101" in objects
    assert "IMG:3300000001" in objects


def test_crosswalk_edges_carry_microbedecoder_provenance(microbedecoder_transform):
    """Crosswalk edges are provenanced to microbedecoder (source of the mapping)."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    close_matches = [e for e in edges if e["predicate"] == CLOSE_MATCH_PREDICATE]
    assert close_matches, "some crosswalk edges must exist"
    for e in close_matches:
        assert e["primary_knowledge_source"] == MICROBEDECODER_KNOWLEDGE_SOURCE


def test_missing_crosswalk_cells_are_skipped(microbedecoder_transform):
    """LPSN_ID=606 has no GTDB_ID cell; no GTDB edge should be emitted for it."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    e_606 = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}606" and e["predicate"] == CLOSE_MATCH_PREDICATE]
    assert not any(e["object"].startswith("GTDB:") for e in e_606)


def test_crosswalk_targets_are_not_stubbed(microbedecoder_transform):
    """
    No stub node for any cross-ref target the KG's own transforms own.

    Add-transform skill rule (Phase 6 anti-pattern): NCBITaxon, GTDB,
    bacdive, GOLD, IMG all have their authoritative nodes elsewhere.
    MicrobeDecoder emits the edges to them but never a stub.
    """
    microbedecoder_transform.run()
    nodes = _read_tsv(microbedecoder_transform.output_node_file)
    for prefix in ("NCBITaxon:", "GTDB:", "bacdive:", "GOLD:", "IMG:", "CHEBI:"):
        stubs = [n["id"] for n in nodes if n["id"].startswith(prefix)]
        assert stubs == [], (
            f"MicrobeDecoder must not emit stub nodes for cross-ref target "
            f"prefix {prefix!r} (owner transform provides them); found: {stubs[:3]}"
        )


def test_crosswalk_normalizes_prefixed_source_ids(microbedecoder_transform):
    """A pre-CURIE'd source cell (``NCBITaxon:1423``) must not double-prefix."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    objects = {
        e["object"] for e in edges if e["predicate"] == CLOSE_MATCH_PREDICATE and e["object"].startswith("NCBITaxon:")
    }
    # None should be "NCBITaxon:NCBITaxon:1423".
    for o in objects:
        assert o.count("NCBITaxon:") == 1, f"double-prefixed: {o}"


# ---------------------------------------------------------------------------
# Metabolism edges (Bergey / VPI / Literature / FAPROTAX)
# ---------------------------------------------------------------------------


def test_bergey_edges_carry_bergey_provenance(microbedecoder_transform):
    """Every Bergey-source edge lists infores:bergey-manual as its primary_knowledge_source."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    bergey_edges = [e for e in edges if e["primary_knowledge_source"] == BERGEY_KNOWLEDGE_SOURCE]
    assert bergey_edges, "Bergey rows in fixture must produce at least one edge"
    # LPSN_ID=101 has Bergey_Major_end_products='acetate, lactate' — expect 2 produces edges
    e_101_produces = [
        e for e in bergey_edges if e["subject"] == f"{LPSN_PREFIX}101" and e["predicate"] == PRODUCES_PREDICATE
    ]
    objects = {e["object"] for e in e_101_produces}
    # Both fall through to placeholders because _NoChebi never resolves
    assert f"{COMPOUND_PREFIX}acetate" in objects
    assert f"{COMPOUND_PREFIX}lactate" in objects


def test_vpi_edges_carry_vpi_provenance(microbedecoder_transform):
    """LPSN_ID=303 has VPI-only fermentation (ABE); each VPI edge is provenanced accordingly."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    vpi_edges = [e for e in edges if e["primary_knowledge_source"] == VPI_KNOWLEDGE_SOURCE]
    assert vpi_edges, "VPI columns in fixture must produce edges"
    # ABE = acetone, butanol, ethanol — 3 produces edges for LPSN_ID=303
    e_303 = [e for e in vpi_edges if e["subject"] == f"{LPSN_PREFIX}303" and e["predicate"] == PRODUCES_PREDICATE]
    objects = {e["object"] for e in e_303}
    for product in ("acetone", "butanol", "ethanol"):
        assert f"{COMPOUND_PREFIX}{product}" in objects, f"missing produces edge for {product}"


def test_literature_edges_carry_literature_provenance(microbedecoder_transform):
    """Literature-sourced edges are provenanced to infores:microbedecoder-literature."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    lit_edges = [e for e in edges if e["primary_knowledge_source"] == LITERATURE_KNOWLEDGE_SOURCE]
    assert lit_edges, "Literature columns in fixture must produce edges"
    # LPSN_ID=404 (Methanocaldococcus): Literature_Major_end_products=methane
    e_404 = [e for e in lit_edges if e["subject"] == f"{LPSN_PREFIX}404" and e["predicate"] == PRODUCES_PREDICATE]
    assert any(e["object"] == f"{COMPOUND_PREFIX}methane" for e in e_404)


def test_faprotax_edges_carry_faprotax_provenance(microbedecoder_transform):
    """FAPROTAX Type_of_metabolism labels are provenanced to infores:faprotax."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    fap = [e for e in edges if e["primary_knowledge_source"] == FAPROTAX_KNOWLEDGE_SOURCE]
    assert fap, "FAPROTAX column in fixture must produce edges"


def test_substrates_use_consumes_predicate(microbedecoder_transform):
    """LPSN_ID=101 Bergey_Substrates_for_end_products=glucose, fructose — 2 consumes edges."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    consumes = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}101"
        and e["predicate"] == "biolink:consumes"
        and e["primary_knowledge_source"] == BERGEY_KNOWLEDGE_SOURCE
    ]
    assert {e["object"] for e in consumes} == {
        f"{COMPOUND_PREFIX}glucose",
        f"{COMPOUND_PREFIX}fructose",
    }


def test_multivalue_split_produces_one_edge_per_token(microbedecoder_transform):
    """
    LPSN_ID=101 Literature_Major_end_products='acetate, lactate, 2,3-butanediol'.

    Documented v1 behavior: the splitter splits on every ``,`` or ``;``,
    so a chemical name containing a literal comma (``2,3-butanediol``)
    over-splits into ``2`` and ``3-butanediol``. This is the same
    limitation madin_etal ships with; both transforms produce accurate
    edges for the common case of simple names (``acetate``, ``lactate``,
    ``butanol``) and can be tightened in a follow-up once a curated
    exceptions list exists.
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    lit_produces = {
        e["object"]
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}101"
        and e["primary_knowledge_source"] == LITERATURE_KNOWLEDGE_SOURCE
        and e["predicate"] == PRODUCES_PREDICATE
    }
    # Simple names must land as expected
    assert f"{COMPOUND_PREFIX}acetate" in lit_produces
    assert f"{COMPOUND_PREFIX}lactate" in lit_produces
    # And the known over-split fragments prove the fixture actually
    # exercised the multi-value path (fixture carries the corner case
    # deliberately as a regression anchor for the future smart-splitter).
    assert f"{COMPOUND_PREFIX}2" in lit_produces
    assert f"{COMPOUND_PREFIX}3_butanediol" in lit_produces


# ---------------------------------------------------------------------------
# BacDive_* snapshot replay
# ---------------------------------------------------------------------------


def test_bacdive_snapshot_edges_carry_microbedecoder_provenance(microbedecoder_transform):
    """Round-plan Q&A decision: BacDive_* replay uses microbedecoder provenance."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    bacdive_snapshot = [
        e
        for e in edges
        if e["predicate"] == HAS_PHENOTYPE_PREDICATE
        and e["primary_knowledge_source"] == MICROBEDECODER_KNOWLEDGE_SOURCE
    ]
    assert bacdive_snapshot, "BacDive_* columns must produce has_phenotype edges"
    # LPSN_ID=101 has BacDive_Oxygen_tolerance='facultative anaerobe'
    e_101 = [e for e in bacdive_snapshot if e["subject"] == f"{LPSN_PREFIX}101"]
    assert any(e["object"] == f"{TRAIT_PREFIX}facultative_anaerobe" for e in e_101)


def test_bacdive_only_row_still_emits_snapshot(microbedecoder_transform):
    """LPSN_ID=505 has synonym status and BacDive-only content — must not crash."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    e_505 = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}505"]
    # At minimum an oxygen tolerance edge + bacdive crosswalk
    predicates = {e["predicate"] for e in e_505}
    assert HAS_PHENOTYPE_PREDICATE in predicates
    assert CLOSE_MATCH_PREDICATE in predicates  # bacdive:BAC05


# ---------------------------------------------------------------------------
# File resolution + failure modes
# ---------------------------------------------------------------------------


def test_missing_csv_raises_file_not_found(tmp_path):
    """A missing input CSV must raise FileNotFoundError with actionable text."""
    xform = MicrobeDecoderTransform(input_dir=tmp_path, output_dir=tmp_path, chemical_loader=_NoChebi())
    with pytest.raises(FileNotFoundError, match="MicrobeDecoder database not found"):
        xform.run()


def test_constructor_is_inert_wrt_chemical_loader(tmp_path, monkeypatch):
    """
    __init__ must not eagerly instantiate ChemicalMappingLoader.

    Mirrors the round-34 lpsn regression check: constructor stays cheap so
    a missing input CSV fails fast without triggering the heavy resource.
    """
    from kg_microbe.transform_utils.microbedecoder import microbedecoder as mod

    calls: list = []

    class _Tripwire:

        """Explode if the transform tries to instantiate the loader eagerly."""

        def __init__(self, *a, **kw):
            """Record the ctor call for the test to assert against."""
            calls.append(("ChemicalMappingLoader", a, kw))

    monkeypatch.setattr("kg_microbe.utils.chemical_mapping_utils.ChemicalMappingLoader", _Tripwire)

    xform = MicrobeDecoderTransform(input_dir=tmp_path, output_dir=tmp_path)
    assert xform.chemical_loader is None
    assert calls == [], "the constructor must not auto-load ChemicalMappingLoader"
    del mod  # silence unused-import


def test_dedup_sorts_output(microbedecoder_transform):
    """Node file must be sorted by id after drop_duplicates."""
    microbedecoder_transform.run()
    nodes = _read_tsv(microbedecoder_transform.output_node_file)
    ids = [n["id"] for n in nodes]
    assert ids == sorted(ids), "nodes must be sorted by id"


def test_mixed_encoding_csv_is_read_with_replacement(tmp_path):
    """
    The real MicrobeDecoder CSV is mixed UTF-8 + sporadic Latin-1 bytes.

    R's ``write.csv`` emits mostly UTF-8 (``°C``, ``©``, fraction glyphs)
    but leaves a handful of raw Latin-1 bytes (e.g. ``0xe9`` = ``é``)
    unescaped. Strict UTF-8 decode raises; we read with
    ``encoding_errors='replace'`` so the transform can consume the file
    unchanged. Valid UTF-8 multi-byte sequences are preserved; bad bytes
    become U+FFFD.

    Fixture is a hand-crafted 8-row CSV extended with two rows: one
    carrying a valid UTF-8 ``°C`` sequence and one carrying a raw
    Latin-1 ``é`` byte injected post-write. Both must land in the
    output; nothing about the malformed byte should abort the run.
    """
    xform = MicrobeDecoderTransform(
        input_dir=FIXTURE_DIR,
        output_dir=tmp_path,
        chemical_loader=_NoChebi(),
    )
    xform.run(data_file="database_mixed_encoding.csv")
    edges = _read_tsv(xform.output_edge_file)
    subjects = {e["subject"] for e in edges}
    assert f"{LPSN_PREFIX}777" in subjects, "the valid-UTF-8 row must be processed"
    assert f"{LPSN_PREFIX}888" in subjects, "the mixed-encoding row must be processed too"
