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
        f"{LPSN_PREFIX}707",
    }, "every non-blank LPSN_ID row produces edges keyed on lpsn:<id>"


def test_empty_lpsn_row_is_skipped(microbedecoder_transform):
    """The fixture's trailing empty-LPSN_ID row must not produce any output."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    # Most edges are subject-side lpsn:<non-empty-id>; the BacDive crosswalk is
    # the exception, being strain -subclass_of-> lpsn (#687), so check whichever
    # endpoint carries the LPSN CURIE. The blank row would give `lpsn:` with no
    # local part, which must appear on neither side.
    lpsn_endpoints = {
        endpoint for edge in edges for endpoint in (edge["subject"], edge["object"]) if endpoint.startswith(LPSN_PREFIX)
    }
    assert lpsn_endpoints, "fixture must emit LPSN-anchored edges"
    assert all(len(e) > len(LPSN_PREFIX) for e in lpsn_endpoints)


# ---------------------------------------------------------------------------
# Crosswalk edges (novel identity mapping)
# ---------------------------------------------------------------------------


def test_identifier_crosswalk_edges_use_close_match(microbedecoder_transform):
    """
    The identifier crosswalks stay ``biolink:close_match`` from lpsn:<id>.

    NCBITaxon, GTDB, GOLD and IMG really are other identifiers for the same
    taxon, so near-identity is right. BacDive is excluded — its target is a
    *strain*, not another name, and it is asserted as subsumption instead
    (#687); see :func:`test_bacdive_crosswalk_is_subsumption_not_close_match`.
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)

    # LPSN_ID=101 has all 5 crosswalk cells populated
    e_101 = [e for e in edges if e["subject"] == f"{LPSN_PREFIX}101" and e["predicate"] == CLOSE_MATCH_PREDICATE]
    objects = {e["object"] for e in e_101}
    assert "NCBITaxon:1423" in objects
    assert "GTDB:d__Bacteria;g__Bacillus;s__Bacillus subtilis" in objects
    assert "GOLD:Gs0000101" in objects
    assert "IMG:3300000001" in objects
    assert not any(o.startswith("kgmicrobe.strain:") for o in objects), (
        "the BacDive crosswalk must not be a close_match"
    )


def test_bacdive_crosswalk_is_subsumption_not_close_match(microbedecoder_transform):
    """
    The BacDive crosswalk must not contradict what the bacdive transform asserts.

    `close_match` claimed near-identity between an LPSN *name* and a BacDive
    *strain*, while bacdive asserts `strain -subclass_of-> lpsn` over 18,425 of
    the same pairs (#687). skos:closeMatch and proper subsumption cannot both
    hold over one pair. Emitting the same subsumption makes the two transforms
    agree, so merge collapses the duplicates and keeps both provenances.

    The row means "this BacDive record is the type strain of this LPSN name" —
    MicrobeDecoder's strain designation equals LPSN's own `nomenclatural_type`
    for 98.9% of matched rows — but no predicate expresses that yet (#744).
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)

    strain_edges = [e for e in edges if "kgmicrobe.strain:bacdive_" in (e["subject"] + e["object"])]
    assert strain_edges, "fixture must produce BacDive crosswalk edges"
    for edge in strain_edges:
        assert edge["predicate"] != CLOSE_MATCH_PREDICATE, f"close_match contradicts subsumption: {edge}"
    assert any(
        e["subject"] == "kgmicrobe.strain:bacdive_BAC01"
        and e["predicate"] == "biolink:subclass_of"
        and e["object"] == f"{LPSN_PREFIX}101"
        for e in strain_edges
    ), strain_edges


def test_bacdive_crosswalk_targets_the_strain_curie(microbedecoder_transform):
    """
    BacDive crosswalk objects must be the CURIE the bacdive transform mints.

    This used to emit the bare ``bacdive:<id>`` form, which no transform
    emits as a node row. All ~19 K of these edges dangled and KGX turned
    them into empty ``biolink:NamedThing`` stubs in the merged KG, while
    the real strain nodes sat under ``kgmicrobe.strain:bacdive_<id>``
    (99,392 rows). Every source BacDive ID resolves under that prefix.
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)

    # The BacDive crosswalk is now subject-side subsumption, not a close_match
    # object, so look at subjects (#687).
    bacdive_subjects = {e["subject"] for e in edges if "bacdive" in e["subject"].lower()}
    assert bacdive_subjects, "fixture must produce BacDive crosswalk edges"
    for subject in bacdive_subjects:
        assert subject.startswith("kgmicrobe.strain:bacdive_"), (
            f"BacDive crosswalk endpoint must use the strain CURIE; got {subject!r}"
        )
    # The bare source form must not survive anywhere, on either side.
    assert not any(e["object"].startswith("bacdive:") or e["subject"].startswith("bacdive:") for e in edges)


def test_bacdive_crosswalk_normalizes_a_precuried_cell(microbedecoder_transform):
    """
    A cell already CURIE'd as ``bacdive:<id>`` must not be double-prefixed.

    The prefix-stripping step keys off the *emitted* prefix, which for
    BacDive no longer matches the prefix the source uses. Without also
    stripping the source prefix, fixture row 505 (``bacdive:BAC05``) would
    emit ``kgmicrobe.strain:bacdive_bacdive:BAC05``.
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    # Subject-side since #687: the BacDive crosswalk is strain -subclass_of-> lpsn.
    strains = {
        e["subject"] for e in edges if e["object"] == f"{LPSN_PREFIX}505" and e["subject"].startswith("kgmicrobe.")
    }
    assert "kgmicrobe.strain:bacdive_BAC05" in strains, f"pre-CURIE'd cell was not normalized; got {strains}"
    for strain in strains:
        assert strain.count(":") == 1, f"double-prefixed CURIE: {strain!r}"


def test_crosswalk_edges_carry_microbedecoder_provenance(microbedecoder_transform):
    """Crosswalk edges are provenanced to microbedecoder (source of the mapping)."""
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    close_matches = [e for e in edges if e["predicate"] == CLOSE_MATCH_PREDICATE]
    assert close_matches, "some crosswalk edges must exist"
    for e in close_matches:
        assert e["primary_knowledge_source"] == MICROBEDECODER_KNOWLEDGE_SOURCE


def test_crosswalk_splits_multi_value_cells(microbedecoder_transform):
    """
    Multi-value crosswalk cells (comma-separated) must emit one edge per token.

    Regression for issue #655: the source's ``IMG_Genome_ID`` column packs
    multiple IMG genome IDs per row (e.g. ``3300000001,3300000002``).
    Before the fix the raw cell was emitted as a single malformed CURIE
    (``IMG:3300000001,3300000002``); ~2.6 K such edges landed in the
    first live merge. The fix runs every crosswalk cell through
    :func:`split_multivalue` so each token becomes its own
    ``biolink:close_match`` edge.

    Fixture row LPSN_ID=707 carries a two-value IMG cell that must split
    into two edges pointing at ``IMG:3300000001`` and ``IMG:3300000002``.
    """
    microbedecoder_transform.run()
    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    img_edges_for_707 = [
        e
        for e in edges
        if e["subject"] == f"{LPSN_PREFIX}707"
        and e["predicate"] == CLOSE_MATCH_PREDICATE
        and e["object"].startswith("IMG:")
    ]
    objects = {e["object"] for e in img_edges_for_707}
    assert objects == {"IMG:3300000001", "IMG:3300000002"}, (
        f"multi-value IMG cell must split into two edges; got {objects}"
    )
    # Nothing malformed: no CURIE should contain an embedded comma.
    for obj in objects:
        assert "," not in obj, f"multi-value cell escaped the split: {obj!r}"


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
    # "bacdive:" stays in the list even though nothing emits it now — it is the
    # prefix this transform used to target, and stubbing it would be a silent
    # return of the dangling-edge bug.
    for prefix in ("NCBITaxon:", "GTDB:", "kgmicrobe.strain:", "bacdive:", "GOLD:", "IMG:", "CHEBI:"):
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
    e_505 = [e for e in edges if f"{LPSN_PREFIX}505" in (e["subject"], e["object"])]
    # At minimum an oxygen tolerance edge + the BacDive crosswalk, which is now
    # subsumption from the strain rather than a close_match to it (#687).
    predicates = {e["predicate"] for e in e_505}
    assert HAS_PHENOTYPE_PREDICATE in predicates
    assert "biolink:subclass_of" in predicates, predicates


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


def test_unmapped_labels_report_is_written(microbedecoder_transform):
    """
    `unmapped_labels.tsv` lands next to nodes/edges with per-label tallies.

    The report is the curation priority queue that feeds issue #650 —
    sorted by occurrence count descending. Follows the metatraits
    ``unmapped_traits.tsv`` convention. Each row names the placeholder
    CURIE, its category, the raw source label, the pipe-set of source
    columns it appeared in, and the occurrence count for this run.
    """
    microbedecoder_transform.run()
    report = microbedecoder_transform.output_dir / "unmapped_labels.tsv"
    assert report.is_file(), "run must emit unmapped_labels.tsv when placeholders were minted"
    with open(report, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert rows, "report has at least one row for the fixture's unmapped labels"
    # Header shape
    assert set(rows[0].keys()) == {
        "placeholder_curie",
        "category",
        "label",
        "source_columns",
        "occurrences",
    }
    # Sorted by occurrences descending
    counts = [int(r["occurrences"]) for r in rows]
    assert counts == sorted(counts, reverse=True), "rows must be sorted by occurrences desc"
    # `acetate` shows up in multiple Bergey/VPI/Literature columns for
    # LPSN_ID=101 — its source_columns cell should carry the pipe-set.
    acetate_rows = [r for r in rows if r["label"] == "acetate"]
    assert acetate_rows, "acetate appeared in the fixture; must be in the report"
    src_cols = acetate_rows[0]["source_columns"].split("|")
    assert len(src_cols) >= 2, (
        f"acetate appeared under multiple source columns in the fixture "
        f"(bergey, vpi, literature); got source_columns={acetate_rows[0]['source_columns']}"
    )


def test_unmapped_labels_report_omitted_when_no_placeholders(tmp_path):
    """
    No report is written when every label maps cleanly (aspirational state).

    Injects a chemical loader that resolves every label to a stub CHEBI
    CURIE. The transform's fixture also carries BacDive_* and
    Type_of_metabolism cells that route through the placeholder path
    regardless of ChEBI, so the report file WILL still be written for
    those. This test therefore uses a fixture-minimal transform whose
    only unmapped-eligible content is the chemical labels the fake
    loader resolves.
    """

    class _AlwaysResolves:
        """ChemicalMappingLoader stub that resolves every label to CHEBI:0."""

        def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
            """Return a stub CHEBI CURIE for every lookup (so no placeholders)."""
            del label, fuzzy_stereochemistry
            return "CHEBI:15377"

    # Write a minimal 1-row CSV with ONLY chemical fields populated (no
    # Type_of_metabolism, no BacDive_* cells) so the placeholder path
    # is only reachable for chemical labels.
    fixture_dir = tmp_path
    csv_path = fixture_dir / "database.csv"
    header = [
        "LPSN_ID",
        "Bergey_Major_end_products",
        "Bergey_Substrates_for_end_products",
    ]
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerow(["999", "acetate, lactate", "glucose"])

    xform = MicrobeDecoderTransform(
        input_dir=fixture_dir,
        output_dir=tmp_path,
        chemical_loader=_AlwaysResolves(),
    )
    xform.run(data_file="database.csv")
    report = xform.output_dir / "unmapped_labels.tsv"
    assert not report.exists(), (
        "no report should be written when every label mapped cleanly; found unmapped_labels.tsv anyway"
    )


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


def test_lpsn_anchor_is_repointed_to_the_accepted_name(tmp_path, microbedecoder_transform):
    """
    A synonym LPSN_ID must not drag the whole row onto a deprecated record.

    Everything this transform emits — crosswalk, metabolism, BacDive snapshot —
    hangs off one `lpsn:<LPSN_ID>` anchor, so a synonym ID puts all of a row's
    edges under a deprecated class: 5,263 edges, 1.0% of the output (#746).
    bacdive got this in #684; the resolver is shared so the two agree.
    """
    import shutil

    # The transform resolves database.csv from input_base_dir, so the fixture has
    # to move with the GSS file rather than the base dir being repointed alone.
    staged = tmp_path / "input"
    staged.mkdir()
    shutil.copy(FIXTURE_DIR / "database.csv", staged / "database.csv")
    (staged / "lpsn_gss.csv").write_text(
        "record_no,status,record_lnk\n"
        "101,VP; sp. nov.; validly published under the ICNP; synonym,999\n"
        "999,VP; sp. nov.; validly published under the ICNP; correct name,\n",
        encoding="utf-8",
    )
    microbedecoder_transform.input_base_dir = staged
    microbedecoder_transform._accepted_lpsn = None
    microbedecoder_transform.run()

    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    anchors = {e["object"] for e in edges if e["object"].startswith(LPSN_PREFIX)}
    anchors |= {e["subject"] for e in edges if e["subject"].startswith(LPSN_PREFIX)}

    assert f"{LPSN_PREFIX}999" in anchors, "the synonym anchor must be re-pointed to the accepted record"
    assert f"{LPSN_PREFIX}101" not in anchors, "the synonym record must not survive as an anchor"


def test_a_missing_gss_file_is_non_fatal(tmp_path, microbedecoder_transform):
    """
    The GSS CSV is account-gated and not shipped.

    Absence must leave IDs as given rather than abort — the same contract the
    bacdive transform honours.
    """
    import shutil

    staged = tmp_path / "input_no_gss"
    staged.mkdir()
    shutil.copy(FIXTURE_DIR / "database.csv", staged / "database.csv")  # but no lpsn_gss.csv
    microbedecoder_transform.input_base_dir = staged
    microbedecoder_transform._accepted_lpsn = None
    microbedecoder_transform.run()

    edges = _read_tsv(microbedecoder_transform.output_edge_file)
    assert edges, "the transform must still emit without the GSS file"
