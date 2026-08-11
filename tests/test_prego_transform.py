"""Tests for the PREGO transform."""

import csv
import shutil
import tarfile
from collections import defaultdict
from pathlib import Path

import pytest

from kg_microbe.transform_utils.constants import (
    CAPABLE_OF_PREDICATE,
    PREGO_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.prego.prego import PregoTransform
from kg_microbe.transform_utils.prego.utils import (
    CHANNEL_ENVIRONMENTAL,
    CHANNEL_GENOMES,
    CHANNEL_LITERATURE,
    DROP_INVERSE_ENVO_TO_TAXON,
    DROP_INVERSE_TAXON_TO_BTO,
    DROP_INVERSE_TAXON_TO_GO,
    DROP_TAXON_TAXON_HOST,
    KEEP_TAXON_TO_BTO,
    KEEP_TAXON_TO_GO,
    channel_for_archive,
    classify_evidence,
    classify_row,
    edge_metadata_for,
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

    All three production archives under ``<tmp>/raw/prego/``, each with the
    real layout (single-file payload named ``database_pairs.tsv``):

    * ``literature.tar.gz`` — BioProject/PMID rows at a flat 3.0.
    * ``annotated_genomes_isolates.tar.gz`` — JGI IMG / Isolates rows.
    * ``environmental_samples.tar.gz`` — the continuous-scored rows.

    All three are required, because the channel is derived from the *archive
    name*: an archive can only ever exercise the one channel its filename
    selects. Two earlier versions of this fixture were each blind in a way that
    let real defects through — everything in one ``literature.tar.gz`` made the
    whole histogram → cutoff → filter path dead in every test, and dropping the
    genome archive left ~47% of production edges with no end-to-end coverage
    while mislabelling genome rows as literature (#713).

    The genome payload deliberately carries scores of both 3 and 4, matching
    the real 8.68 GB archive where ~0.1% of rows score 3 (#717). Since
    ``star_for_row`` uses each flat row's own score rather than its channel's
    constant, a uniformly-4.0 fixture could not exercise that.
    """
    raw_dir = tmp_path / "raw"
    prego_raw = raw_dir / "prego"
    prego_raw.mkdir(parents=True)
    for archive_name, payload in (
        ("literature.tar.gz", "database_pairs.tsv"),
        ("annotated_genomes_isolates.tar.gz", "database_pairs_genomes.tsv"),
        ("environmental_samples.tar.gz", "database_pairs_environmental.tsv"),
    ):
        with tarfile.open(prego_raw / archive_name, "w:gz") as tf:
            tf.add(FIXTURE_DIR / payload, arcname="database_pairs.tsv")
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


def test_edges_carry_the_originating_resource(prego_transform: PregoTransform):
    """
    The source/resource column must survive onto emitted edges.

    It used to be read and immediately discarded (``del source``), so edges
    carried ``prego_score`` and ``prego_channel`` but no way to tell which
    resource produced them. Confidence calibration has to be per-resource —
    the Environmental Samples channel aggregates MGnify and MG-RAST, whose
    score marginals differ — so a shared cutoff across them would conflate
    distributions that are not comparable.
    """
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    assert "prego_source" in edges[0], "prego_source missing from the edge header"
    assert all(e["prego_source"] for e in edges), "every emitted edge must carry its resource"
    # Passed through verbatim from the fixture's source column, so the values
    # are real resource names rather than a derived or normalized label.
    assert {e["prego_source"] for e in edges} == {"BioProject", "JGI IMG", "MGnify"}


def test_taxon_to_go_edges_use_capable_of(prego_transform: PregoTransform):
    """NCBITaxon→GO edges use biolink:capable_of, all 3 GO namespaces."""
    prego_transform.run()
    edges = _read_tsv(prego_transform.output_edge_file)
    tax_go = [e for e in edges if e["subject"] == "NCBITaxon:100" and e["object"].startswith("GO:")]
    # 3 genome-channel rows (BP/CC/MF) + 1 habitat-evidenced genome row + the
    # 12 continuous-channel rows that exercise the calibration path.
    assert len(tax_go) == 16, f"expected 16 canonical NCBITaxon:100→GO edges, got {len(tax_go)}"
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


def test_bto_row_with_non_bto_id_drops_to_prefix_mismatch(tmp_path: Path, prego_output_dir: Path):
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


def test_dictionary_cache_saves_and_reuses(prego_input_dir_with_dictionary: Path, prego_output_dir: Path):
    """
    Second run of PregoTransform hits the pickle cache instead of re-parsing.

    Issue #672: the compiled ``_synonym_lookup`` is persisted after the
    first successful load and rehydrated on subsequent runs, cutting the
    ~15 s dictionary parse to ~0.1 s. Test asserts:

    1. First run creates the cache file.
    2. Second run's ``_synonym_lookup`` matches the first (identical output).
    """
    # First run — populates the cache.
    t1 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t1.run()
    cache_path = (
        prego_input_dir_with_dictionary
        / "prego"
        / "prego_dictionary_extracted"
        / "prego_dictionary_synonyms_cache.pickle"
    )
    assert cache_path.exists(), "first run should have persisted the cache"
    first_lookup = dict(t1._synonym_lookup)  # snapshot

    # Second run — must produce the same lookup.
    t2 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t2.run()
    assert t2._synonym_lookup == first_lookup, "cache-hit lookup must match cold-load lookup"


def test_dictionary_cache_invalidates_on_mondo_mtime_change(
    prego_input_dir_with_dictionary: Path, prego_output_dir: Path
):
    """
    Bumping the mondo_nodes.tsv mtime invalidates the cache and forces a rebuild.

    Regression net for the DOID→MONDO cache-key sensitivity — if the
    ontologies transform re-runs and publishes a fresh DOID→MONDO
    mapping, PREGO must rebuild the lookup rather than serve stale
    MONDO enrichments from a previous run's cache.
    """
    # Prime the cache.
    t1 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t1.run()
    cache_path = (
        prego_input_dir_with_dictionary
        / "prego"
        / "prego_dictionary_extracted"
        / "prego_dictionary_synonyms_cache.pickle"
    )
    cache_mtime_before = cache_path.stat().st_mtime

    # Bump the mondo file's mtime forward — cache key changes, so the
    # next run must rebuild.
    mondo_file = prego_output_dir / "ontologies" / "mondo_nodes.tsv"
    import os

    os.utime(mondo_file, (cache_mtime_before + 10, cache_mtime_before + 10))

    t2 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t2.run()
    assert cache_path.stat().st_mtime > cache_mtime_before, "cache should have been rewritten"


def test_dictionary_cache_recovers_from_corrupt_file(prego_input_dir_with_dictionary: Path, prego_output_dir: Path):
    """
    A garbled cache file is logged-and-ignored, not fatal.

    Robustness: an OOM / disk-full / interrupted pickle write could
    leave the cache file half-populated. The transform must fall back
    to a full parse rather than raise UnpicklingError.
    """
    # Prime the cache.
    t1 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t1.run()
    cache_path = (
        prego_input_dir_with_dictionary
        / "prego"
        / "prego_dictionary_extracted"
        / "prego_dictionary_synonyms_cache.pickle"
    )
    # Corrupt the cache.
    cache_path.write_bytes(b"\x00\x01\x02 not a pickle")

    # Next run must not raise, and must rebuild.
    t2 = PregoTransform(input_dir=prego_input_dir_with_dictionary, output_dir=prego_output_dir)
    t2.run()  # would raise on unhandled UnpicklingError
    # The rebuild happened → cache is a valid pickle again.
    import pickle

    with cache_path.open("rb") as fh:
        rebuilt = pickle.load(fh)
    assert "synonym_lookup" in rebuilt


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


# ---------------------------------------------------------------------------
# Confidence thresholding (end-to-end)
# ---------------------------------------------------------------------------


def test_default_threshold_emits_everything(prego_input_dir: Path, prego_output_dir: Path):
    """
    The default must leave the emitted edge set unchanged.

    Note this branch also adds a prego_source column, so the files are not
    byte-identical to a pre-branch run; the invariant is that no edge is
    dropped at the default threshold.

    Filtering is opt-in; a transform that started silently dropping edges on
    upgrade would be far worse than one that needs a flag.
    """
    baseline = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    assert baseline.min_confidence == 0.0
    baseline.run(show_status=False)
    edges = _read_tsv(baseline.output_edge_file)
    assert edges, "fixture must emit edges at the default threshold"
    # No calibration pass runs, so no table is written.
    assert not baseline.calibration_table_file.exists()


def test_threshold_drops_only_rows_below_it(prego_input_dir: Path, prego_output_dir: Path):
    """
    Raising the threshold drops flat-channel rows scoring below it.

    The fixture's flat rows score 3 and 4, so a 3.5 cut must keep the 4s and
    drop the 3s — and must do so on each row's own score, not on the channel's
    documented constant.

    The raw-score assertion applies to FLAT rows only. Continuous rows are
    filtered on the calibrated star axis, where a row at or above its
    resource's cutoff rates STAR_MAX regardless of its raw score — so a
    continuous row scoring 2.0 can legitimately outrank the 3.5 cut. Asserting
    `raw >= 3.5` over every kept edge conflated the two axes and passed only
    because both surviving continuous rows happened to score 4.0; a fixture row
    scoring 2.0 in the top 12.5% of its resource would have failed the test for
    correct behaviour.
    """
    baseline = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    baseline.run(show_status=False)
    all_edges = _read_tsv(baseline.output_edge_file)

    filtered_transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=3.5)
    filtered_transform.run(show_status=False)
    kept = _read_tsv(filtered_transform.output_edge_file)

    assert len(kept) < len(all_edges), "a 3.5 threshold must drop the score-3 rows"
    assert kept, "it must not drop everything"

    flat_kept = [e for e in kept if e["prego_channel"] != CHANNEL_ENVIRONMENTAL]
    assert flat_kept, "the flat-channel arm of this test must not be vacuous"
    assert all(float(e["prego_score"]) >= 3.5 for e in flat_kept)

    # The continuous arm: every kept row must be at or above its resource's
    # calibrated cutoff, which is the quantity the filter actually compares.
    cutoffs = {}
    for line in filtered_transform.calibration_table_file.read_text().splitlines()[1:]:
        if line.strip():
            resource, _n, _tau, cutoff_score, _kept = line.split("\t")
            cutoffs[resource] = float(cutoff_score)
    continuous_kept = [e for e in kept if e["prego_channel"] == CHANNEL_ENVIRONMENTAL]
    assert continuous_kept, "the continuous arm of this test must not be vacuous"
    for e in continuous_kept:
        assert float(e["prego_score"]) >= cutoffs[e["prego_source"]]


def test_threshold_is_read_from_the_environment(prego_input_dir, prego_output_dir, monkeypatch):
    """PREGO_MIN_CONFIDENCE configures the run, matching the repo's env-var idiom."""
    monkeypatch.setenv("PREGO_MIN_CONFIDENCE", "2.5")
    assert PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir).min_confidence == 2.5


def test_out_of_range_threshold_is_refused(prego_input_dir: Path, prego_output_dir: Path):
    """Above the star ceiling every channel drops out; refuse rather than emit nothing."""
    with pytest.raises(ValueError):
        PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=4.5)


def test_running_twice_produces_identical_output(prego_input_dir: Path, prego_output_dir: Path):
    """
    A second run() on the same instance must not emit a truncated nodes.tsv.

    run() rewrites nodes.tsv from scratch, but the node de-dup set used to
    persist across runs, so every ID was suppressed as already-seen. The
    second run left edges whose endpoints had no node row.
    """
    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    transform.run(show_status=False)
    first_nodes = transform.output_node_file.read_text()
    first_edges = transform.output_edge_file.read_text()

    transform.run(show_status=False)
    assert transform.output_node_file.read_text() == first_nodes, "nodes.tsv must be reproducible"
    assert transform.output_edge_file.read_text() == first_edges, "edges.tsv must be reproducible"

    # Every edge endpoint still resolves to a node row emitted by this run.
    nodes = {n["id"] for n in _read_tsv(transform.output_node_file)}
    for edge in _read_tsv(transform.output_edge_file):
        assert edge["subject"] in nodes or edge["object"] in nodes


def test_calibration_table_is_written_and_matches_what_ships(prego_input_dir: Path, prego_output_dir: Path):
    """
    The calibration table must exist and agree with the emitted edge count.

    This covers three defects that all hid behind the same gap. ``atomic_write``
    is a context manager; calling it as a plain function returned an un-entered
    generator, so the table was never written while the run printed that it
    was. Separately, the table measured retention by histogram bin while the
    filter measured it by raw score — not interchangeable, since a bin's lower
    edge can exceed the scores inside it for ~11.5% of representable 4-dp
    values, including 1.71.

    Neither was caught because the fixture had no continuous-channel rows at
    all: pass 1 always returned an empty histogram, so the whole
    histogram → cutoff → filter path was dead in every test.
    """
    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=2.0)
    transform.run(show_status=False)

    assert transform.calibration_table_file.exists(), "the calibration table was not written"
    lines = [ln for ln in transform.calibration_table_file.read_text().splitlines() if ln.strip()]
    assert lines[0].split("\t") == ["resource", "n", "tau", "cutoff_score", "kept_fraction"]
    assert len(lines) > 1, "a resource row is required, not just a header"

    table = {}
    for line in lines[1:]:
        resource, n, _tau, _cut, kept = line.split("\t")
        table[resource] = (int(n), float(kept))

    edges = _read_tsv(transform.output_edge_file)
    for resource, (n_calibrated, kept_fraction) in table.items():
        # Continuous-channel edges are identified by the archive-derived
        # channel, not by the shape of the raw evidence string — that string
        # now lives in `prego_evidence`.
        shipped = sum(1 for e in edges if e["prego_source"] == resource and e["prego_channel"] == CHANNEL_ENVIRONMENTAL)
        expected = round(kept_fraction * n_calibrated)
        assert shipped == expected, (
            f"{resource}: table claims {kept_fraction:.4f} of {n_calibrated} ({expected} edges) but {shipped} shipped"
        )


def test_default_threshold_drops_no_edges(prego_input_dir: Path, prego_output_dir: Path):
    """
    The default must emit exactly what an unfiltered run emits.

    Asserting only that ``min_confidence == 0.0`` is a literal check that would
    still pass if the default silently dropped most edges — the same
    assert-one-spelling weakness found twice before in this PR.
    """
    baseline = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    baseline.run(show_status=False)
    unfiltered = len(_read_tsv(baseline.output_edge_file))

    explicit_zero = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=0.0)
    explicit_zero.run(show_status=False)
    assert len(_read_tsv(explicit_zero.output_edge_file)) == unfiltered

    filtered = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=4.0)
    filtered.run(show_status=False)
    assert len(_read_tsv(filtered.output_edge_file)) < unfiltered, "the knob must actually do something"


# Channel identification and edge metadata (#694, #695)
# ---------------------------------------------------------------------------


def test_channel_comes_from_the_archive_not_column_six():
    """
    The channel is a property of the archive, not of any column in the data.

    PREGO's column 6 was emitted as ``prego_channel``, but across the real
    archives it holds evidence tallies, resource classes, citations and habitat
    names — ~24k distinct values. That made channel-selection, one of the two
    filters the ingest plan promises, impossible.
    """
    assert channel_for_archive("environmental_samples.tar.gz") == CHANNEL_ENVIRONMENTAL
    assert channel_for_archive("annotated_genomes_isolates.tar.gz") == CHANNEL_GENOMES
    assert channel_for_archive("literature.tar.gz") == CHANNEL_LITERATURE
    # An unrecognised archive keeps its stem rather than being forced into a bucket.
    assert channel_for_archive("something_else.tar.gz") == "something_else"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("402 of 487 samples", "sample_count"),
        ("Isolates", "resource_class"),
        ("Genome annotation", "resource_class"),
        ("Metagenome-Assembled Genome GOLD", "resource_class"),
        ("PMID:24914180", "publication"),
        ("Groundwater", "habitat"),
        ("", "unknown"),
    ],
)
def test_evidence_column_is_classified(value, expected):
    """The grab-bag becomes filterable by classifying what each value actually is."""
    assert classify_evidence(value) == expected


def test_edge_metadata_differs_by_channel():
    """
    Channels are generated by different processes, so one constant would lie.

    Environmental associations come from co-occurrence statistics; the genome
    channels from annotation pipelines over curated resources; anything with a
    citation from text mining over the linked abstract.
    """
    assert edge_metadata_for(CHANNEL_ENVIRONMENTAL, "sample_count") == (
        "statistical_association",
        "data_analysis_pipeline",
    )
    assert edge_metadata_for(CHANNEL_GENOMES, "resource_class") == (
        "knowledge_assertion",
        "automated_agent",
    )
    # A citation overrides the channel default — those rows are text-mined.
    assert edge_metadata_for(CHANNEL_GENOMES, "publication") == ("prediction", "text_mining_agent")
    assert edge_metadata_for(CHANNEL_LITERATURE, "resource_class") == ("prediction", "text_mining_agent")


def test_corrupt_archive_fails_before_overwriting_previous_outputs(prego_input_dir: Path, prego_output_dir: Path):
    """
    A tarball with no payload must abort before the outputs are touched.

    ``_ensure_payload`` raises on a missing ``database_pairs.tsv``, but lazily —
    the genome archive sorts first and was only opened inside the emit loop,
    after ``nodes.tsv`` / ``edges.tsv`` had been created and their headers
    written. So a corrupt archive replaced a good previous run's outputs with a
    one-line file before failing (#716).
    """
    good = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    good.run(show_status=False)
    good_edges = good.output_edge_file.read_text()
    good_nodes = good.output_node_file.read_text()
    assert len(good_edges.splitlines()) > 1, "the baseline run must produce real output"

    # Replace one archive with a tarball containing no database_pairs.tsv.
    corrupt = prego_input_dir / "prego" / "annotated_genomes_isolates.tar.gz"
    corrupt.unlink()
    decoy = prego_input_dir / "prego" / "not_the_payload.txt"
    decoy.write_text("nothing useful here\n")
    with tarfile.open(corrupt, "w:gz") as tf:
        tf.add(decoy, arcname="not_the_payload.txt")

    with pytest.raises(SystemExit, match="no database_pairs.tsv"):
        PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir).run(show_status=False)

    assert good.output_edge_file.read_text() == good_edges, "the previous run's edges were clobbered"
    assert good.output_node_file.read_text() == good_nodes, "the previous run's nodes were clobbered"


def test_habitat_evidence_is_an_observation_not_an_assertion():
    """
    A habitat-evidenced genome row must not claim the highest provenance tier.

    ``Marginal Sea`` / ``Hydrothermal vents`` / ``Birds`` rows come from
    sample/isolation metadata rather than the annotation pipeline the genome
    channel is named for, yet they inherited that channel's
    ``knowledge_assertion`` (#716).

    This is not a confidence demotion, and the two signals are orthogonal:
    measured over the first 3M rows of the real archive, all 1,693 habitat rows
    carry score 4 — PREGO's *highest* tier, none at 3 — including the three
    named above (16, 17 and 18 rows respectively, all at 4). Biolink's
    ``knowledge_level`` describes how knowledge was produced, not how confident
    it is, so a high-confidence observation is coherent.
    """
    assert edge_metadata_for(CHANNEL_GENOMES, "habitat") == ("observation", "automated_agent")
    # The resource-class rows the channel IS named for keep the higher tier.
    assert edge_metadata_for(CHANNEL_GENOMES, "resource_class") == ("knowledge_assertion", "automated_agent")
    # A citation still outranks the habitat rule — those rows are text-mined.
    assert edge_metadata_for(CHANNEL_GENOMES, "publication") == ("prediction", "text_mining_agent")


def test_emitted_provenance_snapshot(prego_transform: PregoTransform):
    """
    Pin the provenance of EVERY fixture edge, so any flip is caught.

    ``test_edge_metadata_matrix_is_pinned`` covers the pure function; this
    covers the wiring — that each real row reaches it with the channel and
    evidence class it should. A bug in `channel_for_archive`, in
    `classify_evidence`, or in which archive a row lives in would leave the
    matrix test green while changing what ships.

    This is the before/after coverage #720 asked for. Point assertions could
    not catch a provenance flip on a pre-existing edge, which is exactly how
    two defects reached master: the habitat rule silently answering for
    unrecognised channels, and genome rows emitting as ``literature`` because
    they sat in the wrong archive. Both show up here as a changed value rather
    than as an absent test.

    The expected values were cross-checked against the fixture *source* rather
    than copied from the transform's output — generating a snapshot from
    current behaviour is how a bug gets enshrined as the expectation. Each is
    derivable from the archive a row lives in plus its column-6 value:
    ``literature`` + ``PMID:*`` -> publication -> text-mined;
    ``annotated_genomes_isolates`` + ``Isolates`` -> resource_class ->
    knowledge_assertion; the same archive + ``Aquatic`` -> habitat ->
    observation; ``environmental_samples`` + a tally -> sample_count ->
    statistical_association.
    """
    prego_transform.run(show_status=False)
    edges = _read_tsv(prego_transform.output_edge_file)

    actual = {
        (e["subject"], e["object"]): (
            e["prego_channel"],
            e["prego_evidence_class"],
            e["knowledge_level"],
            e["agent_type"],
        )
        for e in edges
    }
    genome_assertion = ("annotated_genomes_isolates", "resource_class", "knowledge_assertion", "automated_agent")
    text_mined = ("literature", "publication", "prediction", "text_mining_agent")
    env = ("environmental_samples", "sample_count", "statistical_association", "data_analysis_pipeline")

    expected = {
        ("BTO:0000763", "NCBITaxon:562"): text_mined,
        ("NCBITaxon:562", "MONDO:0007256"): text_mined,
        # Genome-annotation rows. These emitted as `literature`/`prediction`
        # before #713 moved them into the archive they belong to.
        ("ENVO:00000011", "NCBITaxon:693444"): genome_assertion,
        ("NCBITaxon:100", "GO:0000034"): genome_assertion,
        ("NCBITaxon:100", "GO:0005634"): genome_assertion,
        ("NCBITaxon:100", "GO:0006355"): genome_assertion,
        # The habitat exception: sample metadata, not genome annotation.
        ("NCBITaxon:100", "GO:0008150"): ("annotated_genomes_isolates", "habitat", "observation", "automated_agent"),
    }
    expected.update({("NCBITaxon:100", f"GO:000{5000 + i}"): env for i in range(12)})

    # Count first. `actual` is keyed on (subject, object), so two edges sharing
    # that pair collapse into one entry — and the transform does NOT dedupe.
    # Without this line a refactor that processes an archive twice would double
    # all 44.7M edges and every prego test would still pass, including this one,
    # which exists to be the tripwire.
    assert len(edges) == len(expected), f"expected {len(expected)} edges, got {len(edges)} (duplicates?)"
    assert actual == expected


def test_edge_metadata_matrix_is_pinned():
    """
    Pin the whole (channel x evidence_class) matrix, not sampled cells.

    ``edge_metadata_for`` is the single point where 44.7M edges acquire their
    provenance, and its branches interact: the publication rule overrides every
    channel, the habitat rule applies only inside the genome channel, and an
    unrecognised channel must decline to assert. Point assertions missed that —
    hoisting the habitat rule silently changed six cells while the test probing
    that exact invariant still passed, because it sampled one of the other
    twenty-four.

    Diffed against master when this landed: exactly ONE cell changes, the
    genome+habitat one. Everything else must stay put.
    """
    na = ("not_provided", "not_provided")
    text_mined = ("prediction", "text_mining_agent")
    stats = ("statistical_association", "data_analysis_pipeline")
    genome = ("knowledge_assertion", "automated_agent")

    expected = {}
    for evidence_class in ("sample_count", "resource_class", "habitat", "unknown", ""):
        expected[(CHANNEL_ENVIRONMENTAL, evidence_class)] = stats
        expected[(CHANNEL_LITERATURE, evidence_class)] = text_mined
        expected[(CHANNEL_GENOMES, evidence_class)] = genome
        # Unrecognised and empty channels decline to assert.
        expected[("metagenomes", evidence_class)] = na
        expected[("", evidence_class)] = na
    # Habitat is the one genome-channel exception.
    expected[(CHANNEL_GENOMES, "habitat")] = ("observation", "automated_agent")
    # A citation is evidence in its own right and overrides every channel,
    # including ones the code does not recognise.
    for channel in (CHANNEL_ENVIRONMENTAL, CHANNEL_GENOMES, CHANNEL_LITERATURE, "metagenomes", ""):
        expected[(channel, "publication")] = text_mined

    actual = {key: edge_metadata_for(*key) for key in expected}
    assert actual == expected


def test_emitted_knowledge_levels_are_real_biolink_enum_values(prego_transform: PregoTransform):
    """
    Every emitted knowledge_level / agent_type must exist in the Biolink model.

    Checked against the imported enums, not a hand-maintained set. A docstring
    claiming a value was "verified against the model" while the test hardcodes
    the string verifies nothing: a typo like ``observations`` would pass the
    whole suite and ship ~25k edges carrying an invalid enum value.
    """
    from biolink_model.datamodel.pydanticmodel_v2 import AgentTypeEnum, KnowledgeLevelEnum

    knowledge_levels = {e.value for e in KnowledgeLevelEnum}
    agent_types = {e.value for e in AgentTypeEnum}
    # Guard against the enums themselves coming back empty, which would make
    # the subset assertions below pass vacuously.
    assert "observation" in knowledge_levels and "automated_agent" in agent_types

    prego_transform.run(show_status=False)
    edges = _read_tsv(prego_transform.output_edge_file)
    assert edges
    assert {e["knowledge_level"] for e in edges} <= knowledge_levels
    assert {e["agent_type"] for e in edges} <= agent_types


def test_unknown_channel_declines_to_assert_metadata():
    """
    An unrecognised channel must not be given a confident provenance label.

    Probed across EVERY evidence class, not just ``unknown``. The habitat rule
    was briefly hoisted above the channel checks, which made
    ``edge_metadata_for("metagenomes", "habitat")`` answer a confident
    ``("observation", "automated_agent")`` about a pipeline the code knows
    nothing about. That is reachable: ``channel_for_archive`` returns the raw
    stem for an unrecognised archive, and such archives ARE processed.
    """
    for evidence_class in ("unknown", "habitat", "resource_class", "sample_count"):
        assert edge_metadata_for("metagenomes", evidence_class) == ("not_provided", "not_provided"), (
            f"unrecognised channel must decline to assert, but evidence_class={evidence_class!r} did not"
        )
    # A citation is evidence in its own right and stays an exception.
    assert edge_metadata_for("metagenomes", "publication") == ("prediction", "text_mining_agent")


def test_habitat_bucket_is_reported_as_a_residual(prego_input_dir: Path, prego_output_dir: Path, capsys):
    """
    The habitat catch-all must report its distinct values, not hide them.

    ``classify_evidence`` returns ``habitat`` for anything that is not a tally,
    a PMID or a known resource-class prefix — a residual bucket, not a positive
    match. Measured over 3M real genome rows that is 1,693 rows across just 42
    distinct values, all genuine habitat names, so reclassifying them as
    ``unknown`` would destroy a real signal. But the bucket silently absorbs
    anything new: a fifth PREGO resource class would be asserted to be a
    habitat, and a consumer filtering on ``prego_evidence_class='habitat'``
    would get it mixed in (#714).

    Printing the distinct values makes that visible — the real value space is
    small and stable, so an unfamiliar entry stands out.
    """
    extra = prego_input_dir / "prego" / "annotated_genomes_isolates.tar.gz"
    assert extra.exists(), "the genome archive carries the habitat-valued rows"

    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    transform.run(show_status=False)
    out = capsys.readouterr().out

    tracked = transform._stats["evidence_habitat_values"]
    assert "residual bucket" in out, f"the habitat summary must be printed; got:\n{out}"

    # Drift detection must cover DROPPED rows too (#719). The fixture has two
    # habitat values: `Aquatic` on a taxon→GO row that emits, and `Human` on a
    # taxon-taxon row that drops as taxon_taxon_host. Tracking only the emit
    # path saw one of them, which would make a new PREGO resource class landing
    # on a dropped shape invisible to the check built to catch it.
    assert set(tracked) == {"Aquatic", "Human"}, (
        f"habitat tracking must cover dropped rows, not just emitted ones; got {dict(tracked)}"
    )
    assert transform._stats["evidence_habitat_emitted"] == 1, "only Aquatic ships"

    # Seen and emitted are reported separately, since a divergence is a signal.
    assert "2 rows seen" in out and "1 emitted" in out, f"summary must separate seen from emitted; got:\n{out}"
    # The values must be named, so a new resource class would be legible.
    assert "Aquatic" in out and "Human" in out


def test_habitat_drift_covers_every_drop_reason(prego_input_dir: Path, prego_output_dir: Path):
    """
    A habitat value must be tracked no matter why its row is dropped.

    #719 moved tracking off the emit path, but the empty-id guard returns from
    inside the same try block, so tracking placed below it would have excluded
    `empty_id` rows — the identical blind spot, one drop reason further along.

    This asserts coverage across three distinct fates: emitted, dropped by
    shape, and dropped by the empty-id guard.
    """
    extra = FIXTURE_DIR / "database_pairs_genomes.tsv"
    rows = extra.read_text().rstrip("\n").split("\n")
    # A habitat-valued row with an empty entity2_id -> dropped as empty_id.
    rows.append("-2\t100\t-21\t\tJGI IMG\tSubglacial Lake\t4\tTRUE\thttps://example/x")
    payload = prego_input_dir / "prego" / "genomes_with_empty_id.tsv"
    payload.write_text("\n".join(rows) + "\n")
    archive = prego_input_dir / "prego" / "annotated_genomes_isolates.tar.gz"
    archive.unlink()
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(payload, arcname="database_pairs.tsv")

    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    transform.run(show_status=False)
    tracked = transform._stats["evidence_habitat_values"]

    assert "Subglacial Lake" in tracked, (
        f"a habitat value on an empty-id row must still be tracked; got {dict(tracked)}"
    )
    # All three fates represented: emitted, dropped-by-shape, dropped-by-empty-id.
    assert {"Aquatic", "Human", "Subglacial Lake"} <= set(tracked)
    assert transform._stats["evidence_habitat_emitted"] == 1, "only Aquatic ships"


def test_habitat_value_tracking_is_bounded(prego_transform: PregoTransform):
    """
    Distinct-habitat tracking must not grow without bound across 44.7M rows.

    A dict keyed on a free-text column is an O(N) memory risk if the upstream
    shape changes; the cap keeps it O(1) while still counting occurrences, so
    the drift stays visible without the run dying of it.
    """
    prego_transform.run(show_status=False)

    # NB: no `len(counts) <= CAP` assertion here. The fixture yields one habitat
    # value against a cap of 1000, so it would pass with the cap deleted
    # entirely — decoration, not a check. The real check is the overflow path.
    # A defaultdict, not dict.fromkeys: run()'s reset loop type-sniffs and would
    # replace a plain dict with 0, making a second run() raise on `in 0`.
    prego_transform._stats["evidence_habitat_values"] = defaultdict(
        int, {f"habitat_{i}": 1 for i in range(PregoTransform._HABITAT_VALUE_CAP)}
    )
    prego_transform._stats["evidence_habitat_values_uncounted"] = 0
    prego_transform._record_habitat_value("a_brand_new_resource_class")
    assert len(prego_transform._stats["evidence_habitat_values"]) == PregoTransform._HABITAT_VALUE_CAP
    assert prego_transform._stats["evidence_habitat_values_uncounted"] == 1


def test_all_three_channels_are_exercised_end_to_end(prego_transform: PregoTransform):
    """
    Every production channel must appear in the emitted edges.

    A fixture that omits a channel cannot fail for anything specific to it, and
    this suite has been blind twice already: once with every row in
    ``literature.tar.gz`` (which killed the whole calibration path), and once
    without the genome archive at all — ~47% of production edges, whose rows
    were additionally mislabelled as ``literature`` because the channel comes
    from the filename (#713).

    Asserting the full expected sets rather than "more than one" means adding a
    fourth channel upstream, or dropping an archive from the fixture, fails
    here rather than silently narrowing coverage.
    """
    prego_transform.run(show_status=False)
    edges = _read_tsv(prego_transform.output_edge_file)

    assert {e["prego_channel"] for e in edges} == {
        CHANNEL_ENVIRONMENTAL,
        CHANNEL_GENOMES,
        CHANNEL_LITERATURE,
    }
    # Each channel routes to a distinct provenance pair, so full channel
    # coverage must also mean full metadata coverage.
    assert {e["knowledge_level"] for e in edges} == {
        "statistical_association",
        "knowledge_assertion",
        "prediction",
        # Habitat-evidenced genome rows are observations, not assertions (#716).
        "observation",
    }
    assert {e["agent_type"] for e in edges} == {
        "data_analysis_pipeline",
        "automated_agent",
        "text_mining_agent",
    }
    # `habitat` is the residual bucket (#714) and is deliberately present, so
    # the class that silently absorbs upstream drift is covered too.
    assert {e["prego_evidence_class"] for e in edges} == {
        "sample_count",
        "resource_class",
        "publication",
        "habitat",
    }


def test_genome_channel_rows_keep_their_own_score_not_the_channel_constant(
    prego_input_dir: Path, prego_output_dir: Path
):
    """
    A genome row scoring 3 must be dropped at tau=3.5, not promoted to 4.0.

    ``FLAT_CHANNEL_STARS`` documents the genome channel as 4.0, but the real
    8.68 GB archive has ~0.1% of rows at 3 — including ``Isolates`` and
    ``Single Amplified Genome``, not just PMID-evidenced ones (#717).
    ``star_for_row`` deliberately returns the row's own score for a recognised
    flat channel so such a row is preserved as a data-quality signal rather
    than silently promoted to its channel's documented tier.

    The fixture's genome payload carries both 3 and 4 for exactly this reason.
    """
    baseline = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    baseline.run(show_status=False)
    genome_scores = {
        float(e["prego_score"]) for e in _read_tsv(baseline.output_edge_file) if e["prego_channel"] == CHANNEL_GENOMES
    }
    assert genome_scores == {3.0, 4.0}, (
        f"the genome fixture must carry both tiers or this test proves nothing; got {genome_scores}"
    )

    filtered = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=3.5)
    filtered.run(show_status=False)
    kept = [e for e in _read_tsv(filtered.output_edge_file) if e["prego_channel"] == CHANNEL_GENOMES]
    assert kept, "the score-4 genome rows must survive"
    assert all(float(e["prego_score"]) >= 3.5 for e in kept), (
        "a score-3 genome row must be dropped at tau=3.5, not promoted to its channel constant"
    )


def test_unrecognised_archive_warns_that_it_bypasses_the_threshold(
    prego_input_dir: Path, prego_output_dir: Path, capsys
):
    """
    An archive whose channel is unrecognised must announce that it fails open.

    This is the upstream-rename scenario. `channel_for_archive` returns the bare
    stem, `flat_channel_star` returns None, `star_for_row` returns None and
    `keep_row` returns True — so every row bypasses the threshold no matter how
    high it is set. That is deliberate (never drop data for a reason unrelated
    to confidence), but it must be loud.

    The log previously called every skipped archive a "flat channel", which is
    the one thing an unrecognised channel is NOT: a flat channel is rated and
    thresholded on its own score, an unrecognised one is not rated at all. A
    rename of `annotated_genomes_isolates.tar.gz` would silently exempt ~47% of
    production edges while the log looked routine.
    """
    renamed = prego_input_dir / "prego" / "environmental_sampl3s.tar.gz"
    with tarfile.open(renamed, "w:gz") as tf:
        tf.add(FIXTURE_DIR / "database_pairs_environmental.tsv", arcname="database_pairs.tsv")

    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=4.0)
    transform.run(show_status=False)
    out = capsys.readouterr().out

    assert "WARNING" in out and "unrecognised channel" in out, f"an unrecognised archive must warn; got:\n{out}"
    assert "environmental_sampl3s" in out
    assert "flat channel 'environmental_sampl3s'" not in out, "must not be mislabelled as flat"

    # And the warning must be true: those rows really do survive the maximum
    # threshold, on channel rather than on score.
    edges = _read_tsv(transform.output_edge_file)
    bypassed = [e for e in edges if e["prego_channel"] == "environmental_sampl3s"]
    assert bypassed, "the unrecognised-channel rows should have bypassed min_confidence=4.0"
    assert all(e["knowledge_level"] == "not_provided" for e in bypassed)


def test_emitted_edges_carry_populated_metadata(prego_input_dir: Path, prego_output_dir: Path):
    """
    Every edge must carry knowledge_level and agent_type.

    They shipped empty, so 44.7M text-mined and statistically-derived
    associations were indistinguishable from curated assertions anywhere in the
    merged KG — and PREGO is the single largest edge block in it.

    Asserts membership in the documented value sets rather than truthiness.
    ``not_provided`` is truthy, so a truthiness check passes even when EVERY
    edge has unrecognised provenance — which is exactly the state an upstream
    archive rename would produce, and exactly what this test exists to catch.
    """
    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    transform.run(show_status=False)
    edges = _read_tsv(transform.output_edge_file)
    assert edges

    known_levels = {"statistical_association", "knowledge_assertion", "prediction", "observation"}
    known_agents = {"data_analysis_pipeline", "automated_agent", "text_mining_agent"}
    assert {e["knowledge_level"] for e in edges} <= known_levels, (
        f"unrecognised knowledge_level(s): {{e['knowledge_level'] for e in edges}} - {known_levels}"
    )
    assert {e["agent_type"] for e in edges} <= known_agents
    assert {e["prego_channel"] for e in edges} <= {
        CHANNEL_ENVIRONMENTAL,
        CHANNEL_GENOMES,
        CHANNEL_LITERATURE,
    }

    # The raw column is preserved verbatim. Checking `"prego_evidence" in e`
    # would only test the HEADER — `e` is a DictReader dict — and would pass
    # with every cell empty, which is the failure this is meant to exclude.
    assert all(e["prego_evidence"] for e in edges), "prego_evidence values must be populated"


# ---------------------------------------------------------------------------
# Shape selection: habitat-only emission (PREGO_SHAPES)
# ---------------------------------------------------------------------------


def test_habitat_shapes_emit_only_location_of(prego_input_dir: Path, prego_output_dir: Path):
    """
    PREGO is ~99% taxon->GO by volume, and that part has no positive evidence.

    Filtering in the transform rather than downstream is the difference between
    a 12.2 GB edges.tsv and a ~65 MB one, and between a three-hour merge and a
    routine one. Filtering downstream also cannot fix nodes.tsv.
    """
    transform = PregoTransform(
        input_dir=prego_input_dir, output_dir=prego_output_dir, shapes="habitat", habitat_min_score=0
    )
    transform.run()
    edges = _read_tsv(transform.output_edge_file)

    assert edges, "habitat mode must still emit something"
    predicates = {e["predicate"] for e in edges}
    assert predicates == {"biolink:location_of"}, predicates
    assert not any(e["predicate"] == CAPABLE_OF_PREDICATE for e in edges)


def test_habitat_mode_leaves_no_orphan_nodes(prego_input_dir: Path, prego_output_dir: Path):
    """
    Every emitted node must be incident to an emitted edge.

    Node emission used to happen inside the shape branches, before the filters
    below could reject the row, so a dropped edge still wrote its nodes. In
    habitat mode that would have written a GO node for all ~44M taxon->GO rows.
    """
    transform = PregoTransform(
        input_dir=prego_input_dir, output_dir=prego_output_dir, shapes="habitat", habitat_min_score=0
    )
    transform.run()
    nodes = {n["id"] for n in _read_tsv(transform.output_node_file)}
    incident = set()
    for edge in _read_tsv(transform.output_edge_file):
        incident.add(edge["subject"])
        incident.add(edge["object"])

    assert nodes, "habitat mode must still emit nodes"
    assert not (nodes - incident), f"orphan nodes emitted: {sorted(nodes - incident)[:5]}"
    assert not any(n.startswith("GO:") for n in nodes), "no GO nodes belong in a habitat-only build"


def test_min_confidence_no_longer_leaves_orphan_nodes(prego_input_dir: Path, prego_output_dir: Path):
    """
    The same ordering bug affected the pre-existing star threshold.

    `_emit_node` ran before `keep_row`, so every edge PREGO_MIN_CONFIDENCE
    dropped still contributed its nodes to nodes.tsv, and merge carried those
    orphans into the graph.
    """
    transform = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, min_confidence=4)
    transform.run()
    nodes = {n["id"] for n in _read_tsv(transform.output_node_file)}
    incident = set()
    for edge in _read_tsv(transform.output_edge_file):
        incident.add(edge["subject"])
        incident.add(edge["object"])

    assert not (nodes - incident), f"orphan nodes emitted: {sorted(nodes - incident)[:5]}"


def test_habitat_min_score_thresholds_only_the_continuous_channel(prego_input_dir: Path, prego_output_dir: Path):
    """
    Genome-channel habitat scores are only ever 3 or 4.

    A threshold that applied to them would delete 4% of habitat outright on
    provenance rather than quality, so the floor is continuous-channel only.
    """
    transform = PregoTransform(
        input_dir=prego_input_dir, output_dir=prego_output_dir, shapes="habitat", habitat_min_score=99
    )
    transform.run()
    edges = _read_tsv(transform.output_edge_file)
    channels = {e["prego_channel"] for e in edges}

    assert CHANNEL_ENVIRONMENTAL not in channels, "an unreachable floor must empty the continuous channel"
    assert channels, "the genome channel must survive any continuous-channel floor"
    assert channels <= {CHANNEL_GENOMES, CHANNEL_LITERATURE}, channels


def test_shapes_defaults_to_all_and_rejects_nonsense(prego_input_dir: Path, prego_output_dir: Path):
    """Unfiltered stays the default, and a typo must fail loudly rather than silently emit everything."""
    default = PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir)
    assert default.shapes == "all"
    assert default.habitat_min_score == 0.0, "the habitat floor must not apply to an unfiltered run"

    with pytest.raises(ValueError, match="PREGO_SHAPES"):
        PregoTransform(input_dir=prego_input_dir, output_dir=prego_output_dir, shapes="habitats")
