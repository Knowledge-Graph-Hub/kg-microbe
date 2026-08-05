"""Tests for the PREGO transform."""

import csv
import shutil
import tarfile
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    CAPABLE_OF_PREDICATE,
    PREGO_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.prego.prego import PregoTransform
from kg_microbe.transform_utils.prego.utils import (
    DROP_INVERSE_ENVO_TO_TAXON,
    DROP_INVERSE_TAXON_TO_BTO,
    DROP_INVERSE_TAXON_TO_GO,
    DROP_TAXON_TAXON_HOST,
    KEEP_TAXON_TO_BTO,
    KEEP_TAXON_TO_GO,
    classify_row,
    entity_to_curie,
    load_doid_to_mondo,
)

FIXTURE_DIR = Path(__file__).parent / "resources" / "prego"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def prego_input_dir(tmp_path: Path) -> Path:
    """
    Build the PREGO raw input layout the transform expects.

    Wraps ``tests/resources/prego/database_pairs.tsv`` in a
    ``literature.tar.gz``-shaped tarball under
    ``<tmp>/raw/prego/literature.tar.gz``, matching the real archive
    layout (single-file payload named ``database_pairs.tsv``).
    """
    raw_dir = tmp_path / "raw"
    prego_raw = raw_dir / "prego"
    prego_raw.mkdir(parents=True)
    archive = prego_raw / "literature.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(FIXTURE_DIR / "database_pairs.tsv", arcname="database_pairs.tsv")
    return raw_dir


@pytest.fixture()
def prego_output_dir(tmp_path: Path) -> Path:
    """
    Build the PREGO output layout the transform expects.

    Seeds ``<tmp>/transformed/ontologies/mondo_nodes.tsv`` from the
    fixture so ``load_doid_to_mondo`` finds real DOID→MONDO xrefs.
    """
    out = tmp_path / "transformed"
    ontologies_dir = out / "ontologies"
    ontologies_dir.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "mondo_nodes_fixture.tsv", ontologies_dir / "mondo_nodes.tsv")
    return out


@pytest.fixture()
def prego_transform(prego_input_dir: Path, prego_output_dir: Path) -> PregoTransform:
    """Return a ``PregoTransform`` wired to the fixture input + output dirs."""
    return PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)


def _read_tsv(path: Path) -> list:
    """Read a TSV into a list of dicts (header row → per-row dicts)."""
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ---------------------------------------------------------------------------
# classify_row (pure function)
# ---------------------------------------------------------------------------


def test_classify_row_taxon_to_go_all_namespaces():
    """All 3 GO namespaces (-21 BP, -22 CC, -23 MF) route to KEEP_TAXON_TO_GO."""
    for go_type in (-21, -22, -23):
        assert classify_row(-2, go_type) == KEEP_TAXON_TO_GO


def test_classify_row_inverse_dropped():
    """Inverse directions of the canonical shapes drop to their explicit reason."""
    assert classify_row(-23, -2) == DROP_INVERSE_TAXON_TO_GO
    assert classify_row(-2, -27) == DROP_INVERSE_ENVO_TO_TAXON


def test_classify_row_bto_kept():
    """Taxon→BTO is emitted (as BTO→taxon on emit); BTO→taxon inverse is dropped."""
    assert classify_row(-2, -25) == KEEP_TAXON_TO_BTO
    assert classify_row(-25, -2) == DROP_INVERSE_TAXON_TO_BTO


def test_classify_row_taxon_taxon_dropped():
    """Taxon-taxon host / co-occurrence rows go to their own drop reason."""
    assert classify_row(-2, -2) == DROP_TAXON_TAXON_HOST


# ---------------------------------------------------------------------------
# load_doid_to_mondo
# ---------------------------------------------------------------------------


def test_load_doid_to_mondo_reads_fixture(prego_output_dir: Path):
    """Reading the fixture mondo file yields a valid DOID→MONDO map."""
    mondo_file = prego_output_dir / "ontologies" / "mondo_nodes.tsv"
    lookup = load_doid_to_mondo(mondo_file)
    assert lookup["DOID:8"] == "MONDO:0007256"
    assert lookup["DOID:11111111"] == "MONDO:0000000"
    assert "DOID:99999999" not in lookup


def test_load_doid_to_mondo_missing_file_returns_empty(tmp_path: Path):
    """A missing mondo file returns an empty dict rather than raising."""
    assert load_doid_to_mondo(tmp_path / "does_not_exist.tsv") == {}


# ---------------------------------------------------------------------------
# End-to-end transform run
# ---------------------------------------------------------------------------


def test_run_emits_nodes_and_edges(prego_transform: PregoTransform):
    """A fixture-driven run produces well-formed nodes.tsv + edges.tsv."""
    prego_transform.run()
    assert prego_transform.output_node_file.exists()
    assert prego_transform.output_edge_file.exists()
    nodes = _read_tsv(prego_transform.output_node_file)
    edges = _read_tsv(prego_transform.output_edge_file)
    assert len(nodes) >= 5, "expected ≥5 unique nodes from the fixture"
    assert len(edges) >= 5, "expected ≥5 emitted edges from the fixture"


def test_taxon_to_go_edges_use_capable_of(prego_transform: PregoTransform):
    """NCBITaxon→GO edges use biolink:capable_of, all 3 GO namespaces."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    tax_go = [e for e in edges if e["subject"] == "NCBITaxon:100" and e["object"].startswith("GO:")]
    assert len(tax_go) == 3, f"expected 3 canonical NCBITaxon:100→GO edges (BP/CC/MF), got {len(tax_go)}"
    assert all(e["predicate"] == CAPABLE_OF_PREDICATE for e in tax_go)


def test_envo_to_taxon_edges_use_location_of_matching_bacdive(
    prego_transform: PregoTransform,
):
    """ENVO→NCBITaxon edges use biolink:location_of, matching bacdive convention."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    envo_edges = [e for e in edges if e["subject"].startswith("ENVO:")]
    assert len(envo_edges) == 1, f"expected 1 canonical ENVO→NCBITaxon edge, got {len(envo_edges)}"
    assert envo_edges[0]["predicate"] == "biolink:location_of"
    assert envo_edges[0]["object"] == "NCBITaxon:693444"


def test_doid_with_mondo_xref_emits_mondo_edge(prego_transform: PregoTransform):
    """A DOID row with a valid MONDO xref emits NCBITaxon → MONDO associated_with."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    disease = [e for e in edges if e["object"].startswith("MONDO:")]
    assert len(disease) == 1
    assert disease[0] == {
        **disease[0],
        "subject": "NCBITaxon:562",
        "predicate": "biolink:associated_with",
        "object": "MONDO:0007256",  # from fixture DOID:8 xref
    } | {"subject": "NCBITaxon:562", "predicate": "biolink:associated_with", "object": "MONDO:0007256"}


def test_doid_without_mondo_xref_lands_in_unmapped_report(prego_transform: PregoTransform):
    """A DOID row with no MONDO xref is dropped and recorded in the report."""
    prego_transform.run()
    report = _read_tsv(prego_transform.unmapped_report_file)
    doid_drops = [r for r in report if r["reason"] == "doid_no_mondo_xref"]
    assert len(doid_drops) == 1, f"expected 1 no-xref drop, got {len(doid_drops)}: {report}"
    assert "DOID:99999999" in doid_drops[0]["exemplar_row"]


def test_inverse_direction_rows_are_dropped(prego_transform: PregoTransform):
    """GO→NCBITaxon and NCBITaxon→ENVO inverse rows are dropped, not re-emitted."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    # No edges should have GO as subject (only as object in taxon→GO).
    assert not any(e["subject"].startswith("GO:") for e in edges)
    # No edges should have ENVO as object (only as subject in ENVO→taxon).
    assert not any(e["object"].startswith("ENVO:") for e in edges)


def test_taxon_taxon_dropped_but_bto_now_kept(prego_transform: PregoTransform):
    """
    Taxon-taxon host rows still drop; BTO rows now emit (as of PR #TBD).

    Regression net for the v1→v2 scope change: BTO used to be deferred
    and land in ``bto_deferred_v2``. It now emits as an edge with
    ``biolink:location_of`` direction matching bacdive.
    """
    prego_transform.run()
    report = _read_tsv(prego_transform.unmapped_report_file)
    reasons = {r["reason"] for r in report}
    assert DROP_TAXON_TAXON_HOST in reasons
    assert "bto_deferred_v2" not in reasons, "BTO should now emit, not drop"
    # BTO edge should be present.
    edges = _read_tsv(prego_transform.output_edge_file)
    bto_edges = [e for e in edges if e["subject"].startswith("BTO:")]
    assert len(bto_edges) == 1, f"expected 1 BTO→NCBITaxon edge; got {len(bto_edges)}"
    assert bto_edges[0]["predicate"] == "biolink:location_of"
    assert bto_edges[0]["object"] == "NCBITaxon:562"


def test_edges_carry_prego_metadata(prego_transform: PregoTransform):
    """Every emitted edge has score, channel, direct_flag, primary_knowledge_source populated."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    for e in edges:
        assert e["primary_knowledge_source"] == PREGO_KNOWLEDGE_SOURCE
        assert e["prego_score"], f"score missing on edge {e}"
        assert e["prego_channel"], f"channel missing on edge {e}"
        assert e["prego_direct_flag"], f"direct_flag missing on edge {e}"


def test_nodes_are_deduplicated(prego_transform: PregoTransform):
    """A CURIE that appears on multiple edges emits only one node row."""
    prego_transform.run()
    nodes = _read_tsv(prego_transform.output_node_file)
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), f"duplicate node ids: {ids}"
    # NCBITaxon:100 appears on 3 canonical GO edges — should still be one node.
    assert ids.count("NCBITaxon:100") == 1


def test_malformed_rows_are_counted_not_raised(prego_transform: PregoTransform):
    """The fixture's 3-column garbage line is counted, not fatal."""
    prego_transform.run()  # must not raise
    assert prego_transform._stats["rows_malformed"] >= 1


def test_empty_entity_id_row_is_dropped(tmp_path: Path, prego_output_dir: Path):
    """
    A row with an empty entity_id lands in the unmapped report as `empty_id`.

    Regression net for the CURIE-shape defense added in the review-fix
    commit (issue #668 finding 2) — an empty local part would otherwise
    emit a malformed CURIE like `NCBITaxon:`.
    """
    raw_dir = tmp_path / "raw"
    prego_raw = raw_dir / "prego"
    prego_raw.mkdir(parents=True)
    tsv_path = prego_raw / "one_row.tsv"
    # Well-formed 9 cols but entity1_id is empty.
    tsv_path.write_text("-2\t\t-23\tGO:0000034\tJGI IMG\tIsolates\t4\tTRUE\t\n")
    archive = prego_raw / "onerow.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(tsv_path, arcname="database_pairs.tsv")
    tsv_path.unlink()

    transform = PregoTransform(input_dir=raw_dir, output_dir=prego_output_dir)
    transform.run()

    edges = _read_tsv(transform.output_edge_file)
    assert edges == [], f"empty-id row should NOT emit an edge; got {edges}"
    report = _read_tsv(transform.unmapped_report_file)
    empty_id_rows = [r for r in report if r["reason"] == "empty_id"]
    assert len(empty_id_rows) == 1, f"expected 1 empty_id drop, got {report}"


def test_missing_raw_dir_raises(tmp_path: Path):
    """If input_base_dir/prego/ doesn't exist, run() raises SystemExit with a clear message."""
    out = tmp_path / "out"
    (out / "ontologies").mkdir(parents=True)
    transform = PregoTransform(input_dir=tmp_path / "raw", output_dir=out)
    with pytest.raises(SystemExit, match="not found"):
        transform.run()


# ---------------------------------------------------------------------------
# Phase 6b — dictionary synonym enrichment
# ---------------------------------------------------------------------------


def test_entity_to_curie_type_dispatch():
    """entity_to_curie routes each JensenLab type integer to the correct CURIE (or None)."""
    assert entity_to_curie(-2, "100") == "NCBITaxon:100"
    assert entity_to_curie(-21, "GO:0006355") == "GO:0006355"
    assert entity_to_curie(-22, "GO:0005634") == "GO:0005634"
    assert entity_to_curie(-23, "GO:0000034") == "GO:0000034"
    assert entity_to_curie(-27, "ENVO:00000011") == "ENVO:00000011"
    assert entity_to_curie(-25, "BTO:9999") == "BTO:9999"  # tissues now enriched
    # DOID still not handled here — routed via doid_to_mondo in _load_dictionary.
    assert entity_to_curie(-26, "DOID:8") is None
    assert entity_to_curie(-2, "") is None  # defensive against empty source_id


@pytest.fixture()
def prego_input_dir_with_dictionary(prego_input_dir: Path) -> Path:
    """
    Extend the base input fixture with the dictionary tarball.

    Builds ``prego_dictionary.tar.gz`` on-the-fly from the tracked
    ``prego_entities_fixture.tsv`` + ``prego_names_fixture.tsv`` so the
    tarball itself doesn't need to sit in git (blocked by the repo-wide
    ``*.tar.gz`` gitignore).
    """
    archive = prego_input_dir / "prego" / "prego_dictionary.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(FIXTURE_DIR / "prego_entities_fixture.tsv", arcname="prego_entities.tsv")
        tf.add(FIXTURE_DIR / "prego_names_fixture.tsv", arcname="prego_names.tsv")
    return prego_input_dir


@pytest.fixture()
def prego_transform_with_dictionary(prego_input_dir_with_dictionary: Path, prego_output_dir: Path) -> PregoTransform:
    """PregoTransform wired to input that includes the dictionary tarball."""
    return PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)


def test_phase_6b_populates_synonym_column(prego_transform_with_dictionary: PregoTransform):
    """With the dictionary present, NCBITaxon:100 gets its dictionary synonyms."""
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    ncbi100 = next(n for n in nodes if n["id"] == "NCBITaxon:100")
    synonyms = set(ncbi100["synonym"].split("|"))
    # Case-insensitive dedup: "Ancylobacter aquaticus" and
    # "ancylobacter aquaticus" collapse to one entry; alternate
    # "A. aquaticus" survives.
    assert synonyms == {"Ancylobacter aquaticus", "A. aquaticus"} or synonyms == {
        "ancylobacter aquaticus",
        "A. aquaticus",
    }, f"expected one of the two case-collapsed sets; got {synonyms}"


def test_phase_6b_go_node_gets_synonyms(prego_transform_with_dictionary: PregoTransform):
    """GO:0000034 node should carry its dictionary synonym."""
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    go = next(n for n in nodes if n["id"] == "GO:0000034")
    assert "aminoacyl-tRNA hydrolase activity" in go["synonym"]


def test_phase_6b_only_enriches_emitted_nodes(prego_transform_with_dictionary: PregoTransform):
    """
    Dictionary entries whose CURIE isn't emitted by Phase 6a don't produce standalone nodes.

    Regression against the plan's explicit anti-pattern: ingesting the full
    2.5 M dictionary as standalone stubs would balloon the transform's node
    count and duplicate the NCBITaxon transform's output.
    """
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    # Serial 7777's "orphan name" is in prego_names but has no entities row —
    # even if entities-only enrichment were bugged, it couldn't produce a node.
    # The transform must not have invented a node for the orphan serial.
    assert not any("orphan" in n.get("name", "") for n in nodes)
    # BTO:9999 IS in the dictionary but NOT referenced by any association row
    # in database_pairs.tsv fixture — the association fixture references
    # BTO:0000763 only. So BTO:9999 should NOT be emitted as a standalone
    # node (dictionary-only entries don't stub).
    ids = {n["id"] for n in nodes}
    assert "BTO:9999" not in ids


def test_phase_6b_skipped_gracefully_when_dictionary_missing(prego_transform: PregoTransform):
    """
    Without a dictionary in the raw dir, Phase 6a still runs; synonym columns empty.

    Regression net for the optional-dictionary contract — the fixture
    ``prego_transform`` (no dictionary) must run end-to-end and produce
    edges + nodes, just with empty synonym cells.
    """
    prego_transform.run()
    nodes = _read_tsv(prego_transform.output_node_file)
    assert all(n["synonym"] == "" for n in nodes), "no dictionary → all synonyms should be empty"


def test_phase_6b_counts_enrichment_stats(prego_transform_with_dictionary: PregoTransform):
    """Per-run stats expose Phase 6b metrics for the CI log."""
    prego_transform_with_dictionary.run()
    stats = prego_transform_with_dictionary._stats
    # Fixture has 8 valid CURIEs indexed after MONDO reverse-lookup:
    #   NCBI:100/562, GO:0000034, ENVO:00000011, BTO:0000763, BTO:9999,
    #   plus DOID:8 → MONDO:0007256 and DOID:11111111 → MONDO:0000000
    # DOID:99999999 has no MONDO xref so isn't indexed.
    assert stats["dictionary_curies_indexed"] == 8
    assert stats["dictionary_doid_routed_to_mondo"] == 2
    # ≥1 emitted node got at least one synonym.
    assert stats["nodes_enriched_with_synonyms"] >= 1


def test_bto_node_emitted_with_gross_anatomical_category(
    prego_transform_with_dictionary: PregoTransform,
):
    """A taxon→BTO row emits BTO stub node with biolink:GrossAnatomicalStructure."""
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    bto = [n for n in nodes if n["id"].startswith("BTO:")]
    assert len(bto) == 1, f"expected 1 BTO node from fixture; got {[n['id'] for n in bto]}"
    assert bto[0]["id"] == "BTO:0000763"
    assert bto[0]["category"] == "biolink:GrossAnatomicalStructure"


def test_bto_node_gets_dictionary_synonym(prego_transform_with_dictionary: PregoTransform):
    """BTO:0000763 node emitted by Phase 6a gets its dictionary synonym via Phase 6b."""
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    bto = next(n for n in nodes if n["id"] == "BTO:0000763")
    assert "bacterial gut microbiome" in bto["synonym"]


def test_bto_row_with_non_bto_id_drops_to_prefix_mismatch(
    tmp_path: Path, prego_output_dir: Path
):
    """
    A `-2 → -25` row whose entity2_id doesn't start with `BTO:` drops explicitly.

    Regression net for the CLDB defense added during PR #674's live canary:
    some source rows type-tag `-25` (BTO) but carry a CLDB or other prefix.
    The transform must NOT emit those as malformed BTO nodes.
    """
    raw_dir = tmp_path / "raw"
    prego_raw = raw_dir / "prego"
    prego_raw.mkdir(parents=True)
    tsv_path = prego_raw / "one_row.tsv"
    # Well-formed 9 cols, entity2_type=-25 but entity2_id is CLDB, not BTO.
    tsv_path.write_text("-2\t104623\t-25\tCLDB:0001165\tBioProject\tPMID:24336377\t3\tTRUE\t\n")
    archive = prego_raw / "onerow.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(tsv_path, arcname="database_pairs.tsv")
    tsv_path.unlink()

    transform = PregoTransform(input_dir=raw_dir, output_dir=prego_output_dir)
    transform.run()

    # No edge should emit.
    edges = _read_tsv(transform.output_edge_file)
    assert edges == [], f"CLDB-prefixed row should not emit; got {edges}"
    # And no node with a CLDB: prefix should appear.
    nodes = _read_tsv(transform.output_node_file)
    assert not any(n["id"].startswith("CLDB:") for n in nodes)
    # Drop lands in the dedicated bucket.
    report = _read_tsv(transform.unmapped_report_file)
    reasons = {r["reason"] for r in report}
    assert "bto_id_prefix_mismatch" in reasons


def test_mondo_node_enriched_via_doid_reverse_lookup(
    prego_transform_with_dictionary: PregoTransform,
):
    """
    MONDO node emitted from a DOID association row gets synonyms via reverse-lookup.

    The DOID synonyms in ``prego_names.tsv`` are keyed on the DOID serial;
    the transform routes those serials to MONDO CURIEs during dictionary
    load so the synonyms land on the MONDO nodes Phase 6a actually emits.
    """
    prego_transform_with_dictionary.run()
    nodes = _read_tsv(prego_transform_with_dictionary.output_node_file)
    mondo = next(n for n in nodes if n["id"] == "MONDO:0007256")
    synonyms = set(mondo["synonym"].split("|"))
    # DOID:8 has two names in the dictionary fixture: "AIDS" and "HIV/AIDS"
    assert "AIDS" in synonyms
    assert "HIV/AIDS" in synonyms


@pytest.fixture()
def prego_input_dir_multi_archive(prego_input_dir: Path) -> Path:
    """
    Extend the base input fixture with a second association tarball.

    The base fixture provides ``literature.tar.gz`` with the primary
    ``database_pairs.tsv`` (10 valid rows). This overlays a second
    ``environmental.tar.gz`` built from ``database_pairs_second.tsv`` (3
    rows) so we can verify multi-archive integrity (issue #668 finding 4):

    1. Archive 1's edges + archive 2's edges both land in the same
       edges.tsv without corruption.
    2. A CURIE that appears in BOTH archives (NCBITaxon:100) is emitted
       as one node (not two).
    3. Header rows aren't accidentally re-emitted.
    """
    second_archive = prego_input_dir / "prego" / "environmental.tar.gz"
    with tarfile.open(second_archive, "w:gz") as tf:
        tf.add(FIXTURE_DIR / "database_pairs_second.tsv", arcname="database_pairs.tsv")
    return prego_input_dir


@pytest.fixture()
def prego_transform_multi_archive(prego_input_dir_multi_archive: Path, prego_output_dir: Path) -> PregoTransform:
    """PregoTransform wired to input that has two association tarballs."""
    return PregoTransform(input_dir=prego_input_dir_multi_archive, output_dir=prego_output_dir)


def test_multi_archive_edges_from_both_land_in_output(
    prego_transform_multi_archive: PregoTransform,
):
    """
    Both archives' unique rows appear in the final edges.tsv.

    Regression net for issue #668 finding 4: the transform is designed to
    loop over multiple tarballs, but the earlier fixture only exercised the
    one-tarball path. This test proves both archives' contributions
    survive to the merged output.
    """
    prego_transform_multi_archive.run()
    edges = _read_tsv(prego_transform_multi_archive.output_edge_file)
    edge_pairs = {(e["subject"], e["object"]) for e in edges}
    # From archive 1 (literature.tar.gz):
    assert ("NCBITaxon:100", "GO:0000034") in edge_pairs, "archive 1 taxon→GO_MF edge missing"
    # From archive 2 (environmental.tar.gz):
    assert ("ENVO:00003064", "NCBITaxon:1224") in edge_pairs, "archive 2 ENVO→taxon edge missing"
    assert ("NCBITaxon:100", "GO:0000049") in edge_pairs, "archive 2 taxon→GO edge missing"
    assert ("NCBITaxon:1224", "GO:0016020") in edge_pairs, "archive 2 second taxon→GO edge missing"


def test_multi_archive_nodes_deduplicated_across_archives(
    prego_transform_multi_archive: PregoTransform,
):
    """NCBITaxon:100 appears in both archives; should still emit one node row."""
    prego_transform_multi_archive.run()
    nodes = _read_tsv(prego_transform_multi_archive.output_node_file)
    ids = [n["id"] for n in nodes]
    assert ids.count("NCBITaxon:100") == 1, (
        f"NCBITaxon:100 appears in both archives; expected 1 node row, got {ids.count('NCBITaxon:100')}"
    )


def test_multi_archive_no_stray_headers(prego_transform_multi_archive: PregoTransform):
    """
    Every emitted edge row carries CURIE-shaped subject and object.

    Regression net for the possibility that row iteration accidentally
    re-emits tarball headers or produces row-1 quirks — a raw
    ``entity1_type`` integer string leaking through as a subject would
    fail the ``":" in e["subject"]`` assertion.
    """
    prego_transform_multi_archive.run()
    edges = _read_tsv(prego_transform_multi_archive.output_edge_file)
    for e in edges:
        assert ":" in e["subject"], f"non-CURIE subject: {e['subject']}"
        assert ":" in e["object"], f"non-CURIE object: {e['object']}"


def test_missing_archives_raises(tmp_path: Path):
    """If prego/ exists but has no *.tar.gz, run() raises SystemExit."""
    raw = tmp_path / "raw" / "prego"
    raw.mkdir(parents=True)
    out = tmp_path / "out"
    (out / "ontologies").mkdir(parents=True)
    transform = PregoTransform(input_dir=tmp_path / "raw", output_dir=out)
    with pytest.raises(SystemExit, match="no .* archives"):
        transform.run()
