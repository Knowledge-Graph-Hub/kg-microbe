"""
PREGO transform — ingest taxon↔environment/process associations.

Reads the three ``database_pairs.tsv`` archives from
https://prego.hcmr.gr/download/ (documented in the paper's Appendix D — see
`docs/PREGO_INGEST_PLAN.md` for the full acquisition trail and schema
discovery) and emits KGX-format node + edge TSVs plus an
``unmapped_associations.tsv`` curation report for rows that were
intentionally skipped.

Phase 6a scope (this module): the associations themselves. Phase 6b
(dictionary synonym enrichment from ``prego_dictionary.tar.gz``) is a
follow-up per the plan's own ship-6a-first guidance.

Emitted edge shapes (canonical directions matching KGM convention — see
`utils.classify_row`):

- ``NCBITaxon:X → biolink:capable_of → GO:Y``  (all 3 GO namespaces)
- ``ENVO:Y → biolink:location_of → NCBITaxon:X``  (matches bacdive)
- ``NCBITaxon:X → biolink:associated_with → MONDO:Y``  (DOID routed via xref)

Each edge carries per-row PREGO metadata (``score``, ``channel``,
``direct_flag``, ``evidence_url``) as extra columns beyond the KGX
minimum, so downstream consumers can filter by evidence type or
threshold on confidence.
"""

from __future__ import annotations

import csv
import pickle
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union

from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    CAPABLE_OF_PREDICATE,
    CATEGORY_COLUMN,
    ID_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PREGO,
    PREGO_CHANNEL_COLUMN,
    PREGO_DIRECT_FLAG_COLUMN,
    PREGO_EVIDENCE_URL_COLUMN,
    PREGO_KNOWLEDGE_SOURCE,
    PREGO_SCORE_COLUMN,
    PREGO_SOURCE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
)
from kg_microbe.transform_utils.prego.utils import (
    KEEP_ENVO_TO_TAXON,
    KEEP_TAXON_TO_BTO,
    KEEP_TAXON_TO_DOID,
    KEEP_TAXON_TO_GO,
    PREGO_TYPE_DOID,
    classify_row,
    entity_to_curie,
    go_category_for_type,
    iter_database_pairs,
    iter_dictionary_entities,
    iter_dictionary_names,
    load_doid_to_mondo,
)
from kg_microbe.transform_utils.transform import Transform

# ---------------------------------------------------------------------------
# Edge predicates and relations. PREGO uses only biolink predicates; the
# RELATION_COLUMN carries an RO term where an obvious one applies, else empty.
# ---------------------------------------------------------------------------
_LOCATION_OF_PREDICATE = "biolink:location_of"
_ASSOCIATED_WITH_PREDICATE = "biolink:associated_with"
_RELATION_LOCATION_OF = "RO:0001015"  # source → location_of → organism
_RELATION_CAPABLE_OF = "RO:0002215"  # organism → capable_of → process
_RELATION_ASSOCIATED_WITH = "RO:0002610"  # correlated with

# ---------------------------------------------------------------------------
# Node categories for stub emission. The `ontologies` transform is
# authoritative for these CURIEs; PREGO's stubs let its own edges resolve
# in its own nodes.tsv, and merge-time dedup upgrades the category if a
# richer row exists.
# ---------------------------------------------------------------------------
_NCBITAXON_CATEGORY = "biolink:OrganismTaxon"
_ENVO_CATEGORY = "biolink:OntologyClass"  # heterogeneous in ENVO; safe default
_MONDO_CATEGORY = "biolink:Disease"
_BTO_CATEGORY = "biolink:GrossAnatomicalStructure"  # BTO = Brenda Tissue Ontology

# ---------------------------------------------------------------------------
# Extra edge columns beyond the KGX minimum. Kept as a small tuple so the
# header is single-sourced.
# ---------------------------------------------------------------------------
_PREGO_EDGE_EXTRA_COLUMNS = (
    PREGO_SCORE_COLUMN,
    PREGO_CHANNEL_COLUMN,
    PREGO_SOURCE_COLUMN,
    PREGO_DIRECT_FLAG_COLUMN,
    PREGO_EVIDENCE_URL_COLUMN,
)


class PregoTransform(Transform):

    """Ingest PREGO taxon↔environment/process associations."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """Instantiate; register the source name + extend the edge header with PREGO metadata."""
        super().__init__(PREGO, input_dir, output_dir)
        # Extend edge header with PREGO's per-row metadata columns. Node
        # header is unchanged (id / category / name / description / xref /
        # provided_by / synonym / deprecated / same_as).
        self.edge_header = list(self.edge_header) + list(_PREGO_EDGE_EXTRA_COLUMNS)
        # Where mondo xrefs live in the ontologies output.
        self._mondo_nodes_file = self.output_base_dir / "ontologies" / "mondo_nodes.tsv"
        # Curation report path — one row per (drop_reason, source_id) pair
        # with an occurrence count, so a curator can prioritise fix targets.
        self.unmapped_report_file = self.output_dir / "unmapped_associations.tsv"
        # Per-run counters.
        self._stats = {
            "rows_read": 0,
            "rows_malformed": 0,
            "edges_emitted": 0,
            "edges_by_shape": defaultdict(int),
            "rows_dropped": 0,
            "rows_dropped_by_reason": defaultdict(int),
            "doid_no_mondo_xref": 0,
            "unique_nodes_emitted": 0,
            "nodes_enriched_with_synonyms": 0,
            "dictionary_curies_indexed": 0,
            "dictionary_synonyms_indexed": 0,
            "dictionary_doid_routed_to_mondo": 0,
        }
        # Node de-dup set — a CURIE seen twice only emits one node row.
        self._emitted_nodes: set = set()
        # Detailed drop report keyed by (reason, exemplar_id) so the report
        # can point curators at the specific IDs that got dropped, capped
        # per-reason to avoid unbounded memory on 10^8-row runs.
        self._drop_examples: dict = defaultdict(lambda: defaultdict(int))
        # Phase 6b: CURIE → set of case-insensitively-unique synonyms from
        # the tagger dictionary. Populated by _load_dictionary() when the
        # optional prego_dictionary.tar.gz is present; empty when it isn't
        # (Phase 6a still runs standalone).
        self._synonym_lookup: dict = {}

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """
        Read every PREGO archive and emit nodes + edges + unmapped-associations report.

        ``data_file`` is accepted for base-class compatibility but ignored.
        PREGO ingests every ``*.tar.gz`` in its raw directory — the full
        three-channel set (literature / environmental_samples /
        annotated_genomes_isolates) is the intended production input, but any
        subset works (e.g. the isolates-only canary). ``show_status`` toggles
        the tqdm progress bar; false is used by the pytest suite to keep
        captured output clean.
        """
        del data_file  # multi-archive ingest; scanned from raw dir

        prego_raw_dir = self.input_base_dir / PREGO
        if not prego_raw_dir.is_dir():
            raise SystemExit(f"[prego] {prego_raw_dir} not found. Run `poetry run kg download -t prego` first.")

        # Association archives are every *.tar.gz EXCEPT the tagger dictionary,
        # which Phase 6b loads through a separate code path.
        archives = sorted(p for p in prego_raw_dir.glob("*.tar.gz") if p.name != self._DICTIONARY_ARCHIVE_NAME)
        if not archives:
            raise SystemExit(
                f"[prego] no *.tar.gz archives in {prego_raw_dir}. Run `poetry run kg download -t prego` first."
            )

        doid_to_mondo = load_doid_to_mondo(self._mondo_nodes_file)
        if not doid_to_mondo:
            print(
                f"[prego] WARNING: no DOID→MONDO xrefs loaded from {self._mondo_nodes_file}; "
                "every DOID row will drop to the unmapped report. Re-run the ontologies "
                "transform if you want disease edges."
            )

        # Phase 6b — dictionary synonym enrichment. Optional: if the
        # tagger dictionary isn't downloaded, skip and log; 6a still
        # produces useful output on its own. The DOID→MONDO xref map is
        # threaded through so DOID dictionary synonyms enrich the
        # corresponding MONDO nodes (reverse-lookup, per the plan).
        self._load_dictionary(prego_raw_dir, doid_to_mondo)

        Path.mkdir(self.output_dir, exist_ok=True, parents=True)
        with (
            self.output_node_file.open("w", newline="") as node_fh,
            self.output_edge_file.open("w", newline="") as edge_fh,
        ):
            node_writer = csv.writer(node_fh, delimiter="\t")
            edge_writer = csv.writer(edge_fh, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            for archive_path in archives:
                self._process_archive(archive_path, doid_to_mondo, node_writer, edge_writer, show_status=show_status)

        self._write_unmapped_report()
        self._print_summary()

    # ------------------------------------------------------------------ #
    # Phase 6b: dictionary synonym enrichment.
    # ------------------------------------------------------------------ #

    _DICTIONARY_ARCHIVE_NAME = "prego_dictionary.tar.gz"
    _DICTIONARY_FILES = ("prego_entities.tsv", "prego_names.tsv")
    # Pickle cache of the compiled `_synonym_lookup` (issue #672). Invalidated
    # on any mtime change of the dictionary tarball OR the mondo_nodes.tsv
    # file (which drives the DOID→MONDO xref routing). Sits alongside the
    # extracted payload so it lives with what it's derived from.
    _DICTIONARY_CACHE_NAME = "prego_dictionary_synonyms_cache.pickle"
    _DICTIONARY_CACHE_VERSION = 1  # bump if the cache payload shape changes

    def _load_dictionary(self, prego_raw_dir: Path, doid_to_mondo: dict) -> None:
        """
        Populate :attr:`_synonym_lookup` from the tagger dictionary if available.

        Optional. If ``prego_dictionary.tar.gz`` isn't in the raw dir, log a
        one-line note and continue — Phase 6a still produces useful output
        with empty synonym columns.

        Two-step join in memory (per the plan's §Phase 6b):

        1. ``prego_entities.tsv`` → ``{serial: CURIE}`` for the 6 emitted
           entity types (NCBITaxon, all 3 GO namespaces, ENVO, BTO), PLUS
           DOID entries reverse-mapped to their MONDO CURIE via
           ``doid_to_mondo`` — so DOID synonyms enrich the MONDO nodes
           that Phase 6a routes DOID rows to. Non-target types are dropped
           so we don't waste memory on entries whose synonyms would never
           enrich anything.
        2. ``prego_names.tsv`` → for each ``(serial, name)`` where the serial
           is in the type-filtered map, accumulate ``{CURIE: {names...}}``.
           Case-insensitive dedup keeps only distinct spellings.

        Memory profile per canary-scale estimates: ~200 MB peak for the
        serial→CURIE map (~500 K useful entries out of 2.5 M) plus ~150 MB
        for the accumulated synonym sets. Fine on any machine that can
        already extract the 8.1 GB isolates payload.
        """
        archive = prego_raw_dir / self._DICTIONARY_ARCHIVE_NAME
        if not archive.is_file():
            print(
                f"[prego] no {self._DICTIONARY_ARCHIVE_NAME} in {prego_raw_dir}; "
                "skipping Phase 6b synonym enrichment. Node `synonym` columns "
                "will be empty. Add the archive to download.yaml and re-run "
                "if you want enrichment."
            )
            return

        payload_dir = prego_raw_dir / "prego_dictionary_extracted"
        payload_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Cache fast path: skip the ~15 s dictionary parse if the compiled
        # lookup is still fresh vs both the dictionary tarball AND the
        # mondo_nodes.tsv that drives DOID→MONDO routing. Keeps developer
        # iteration cheap; production runs pay the cost once, then hit the
        # cache on every subsequent kg-release build.
        # ------------------------------------------------------------------
        cache_path = payload_dir / self._DICTIONARY_CACHE_NAME
        cache_key = self._dictionary_cache_key(archive)
        if self._load_synonym_lookup_from_cache(cache_path, cache_key):
            return
        # Same size-check-then-reuse pattern as _process_archive.
        with tarfile.open(archive, mode="r:gz") as tf:
            for member in tf.getmembers():
                target_name = Path(member.name).name
                if target_name not in self._DICTIONARY_FILES:
                    continue
                dest = payload_dir / target_name
                if not dest.exists() or dest.stat().st_size != member.size:
                    print(f"[prego] extracting dictionary member {target_name}...")
                    with tf.extractfile(member) as src, dest.open("wb") as out:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)

        entities_file = payload_dir / "prego_entities.tsv"
        names_file = payload_dir / "prego_names.tsv"
        if not (entities_file.is_file() and names_file.is_file()):
            print(
                f"[prego] WARNING: dictionary archive found but expected members missing "
                f"({self._DICTIONARY_FILES}); skipping Phase 6b."
            )
            return

        print(f"[prego] loading dictionary entities from {entities_file.name}...")
        serial_to_curie: dict = {}
        n_doid_via_mondo = 0
        for serial, entity_type, source_id in iter_dictionary_entities(entities_file):
            curie = entity_to_curie(entity_type, source_id)
            if curie is not None:
                serial_to_curie[serial] = curie
                continue
            # DOID reverse-lookup: PREGO's dictionary keys synonyms by DOID
            # serial, but the emitted edge/node CURIE is the MONDO xref. So
            # we route DOID serials to their MONDO CURIEs at index time and
            # every DOID's synonyms accumulate under the MONDO node.
            if entity_type == PREGO_TYPE_DOID and source_id.startswith("DOID:"):
                mondo = doid_to_mondo.get(source_id)
                if mondo is not None:
                    serial_to_curie[serial] = mondo
                    n_doid_via_mondo += 1
        self._stats["dictionary_curies_indexed"] = len(serial_to_curie)
        self._stats["dictionary_doid_routed_to_mondo"] = n_doid_via_mondo
        print(f"[prego] indexed {len(serial_to_curie):,} target CURIEs from dictionary")

        print(f"[prego] loading dictionary names from {names_file.name}...")
        n_kept = 0
        for serial, name in iter_dictionary_names(names_file):
            curie = serial_to_curie.get(serial)
            if curie is None:
                continue
            name_stripped = name.strip()
            if not name_stripped:
                continue
            # Case-insensitive dedup: keep the first-seen casing of each
            # distinct spelling so downstream match strategies work with
            # what curators wrote in the literature.
            bucket = self._synonym_lookup.setdefault(curie, {})
            key = name_stripped.casefold()
            bucket.setdefault(key, name_stripped)
            n_kept += 1
        # Persist the compiled lookup for the next run's fast path (issue #672).
        # Wait to write until AFTER the flatten below so what's persisted is
        # what `_emit_node` consumes at runtime.
        # Flatten the {casefold_key: original_case} inner dicts to sets of the
        # preserved-case names — that's what _emit_node consumes.
        self._synonym_lookup = {curie: set(inner.values()) for curie, inner in self._synonym_lookup.items()}
        self._stats["dictionary_synonyms_indexed"] = n_kept
        print(f"[prego] dictionary loaded: {n_kept:,} synonym rows kept across {len(self._synonym_lookup):,} CURIEs")

        # Persist the compiled lookup so the next run skips the ~15 s parse.
        self._save_synonym_lookup_cache(cache_path, cache_key)

    # ------------------------------------------------------------------ #
    # Cache helpers for the compiled synonym lookup (issue #672).
    # ------------------------------------------------------------------ #

    def _dictionary_cache_key(self, archive: Path) -> tuple:
        """
        Return a cache key sensitive to changes in either source-of-truth file.

        The compiled ``_synonym_lookup`` is a function of the dictionary
        tarball AND the mondo_nodes.tsv (which drives DOID→MONDO routing).
        Cache invalidation triggers on any mtime change of either.
        Version tag lets a schema change force a rebuild across the board.
        """
        dict_mtime = archive.stat().st_mtime
        mondo_mtime = self._mondo_nodes_file.stat().st_mtime if self._mondo_nodes_file.is_file() else 0
        return (self._DICTIONARY_CACHE_VERSION, dict_mtime, mondo_mtime)

    def _load_synonym_lookup_from_cache(self, cache_path: Path, expected_key: tuple) -> bool:
        """
        Try to hydrate :attr:`_synonym_lookup` from the pickle cache.

        Returns True on a cache hit (caller then skips the dictionary parse).
        Returns False if the cache is missing, stale, corrupt, or version-
        mismatched — the transform then does a full parse and re-writes
        the cache at the end.
        """
        if not cache_path.exists():
            return False
        try:
            with cache_path.open("rb") as fh:
                cached = pickle.load(fh)  # noqa: S301 (trusted local-only cache)
        except (pickle.UnpicklingError, EOFError, ValueError, AttributeError) as exc:
            print(f"[prego] cache {cache_path.name} unreadable ({type(exc).__name__}); rebuilding")
            return False
        if cached.get("cache_key") != expected_key:
            print(f"[prego] cache {cache_path.name} stale (source files changed); rebuilding")
            return False
        self._synonym_lookup = cached["synonym_lookup"]
        for stat_key in (
            "dictionary_curies_indexed",
            "dictionary_synonyms_indexed",
            "dictionary_doid_routed_to_mondo",
        ):
            self._stats[stat_key] = cached.get(stat_key, 0)
        print(
            f"[prego] loaded {len(self._synonym_lookup):,} CURIE synonyms from cache "
            f"{cache_path.name} (skipped ~15 s parse)"
        )
        return True

    def _save_synonym_lookup_cache(self, cache_path: Path, cache_key: tuple) -> None:
        """
        Persist the compiled synonym lookup atomically.

        Writes to a ``.tmp`` sibling first, then ``rename()`` — that way a
        crashed write doesn't leave a truncated cache the next run trusts.
        """
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        payload = {
            "cache_key": cache_key,
            "synonym_lookup": self._synonym_lookup,
            "dictionary_curies_indexed": self._stats["dictionary_curies_indexed"],
            "dictionary_synonyms_indexed": self._stats["dictionary_synonyms_indexed"],
            "dictionary_doid_routed_to_mondo": self._stats["dictionary_doid_routed_to_mondo"],
        }
        try:
            with tmp_path.open("wb") as fh:
                pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
            tmp_path.replace(cache_path)
            print(f"[prego] persisted synonym lookup to {cache_path.name}")
        except OSError as exc:
            print(f"[prego] WARNING: could not persist cache {cache_path.name}: {exc}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Per-archive processing.
    # ------------------------------------------------------------------ #

    def _process_archive(self, archive_path, doid_to_mondo, node_writer, edge_writer, show_status: bool = True):
        """
        Extract ``database_pairs.tsv`` from one archive and stream it row-by-row.

        Cache-then-reuse: extract once into a sibling ``_extracted`` dir so
        re-runs don't pay the ~30 s decompression cost twice. Guard against
        interrupted-extraction: if the cached payload's size doesn't match the
        tar member's declared size, re-extract rather than trusting a possibly
        truncated file (the alternative would silently emit fewer edges on a
        retry after Ctrl-C / disk-full / OOM).
        """
        payload_dir = archive_path.parent / archive_path.stem.replace(".tar", "_extracted")
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_file = payload_dir / "database_pairs.tsv"

        # Read the member's declared size up front so we can compare against
        # any cached file and decide whether re-extraction is needed.
        with tarfile.open(archive_path, mode="r:gz") as tf:
            member = next(
                (m for m in tf.getmembers() if m.name.endswith("database_pairs.tsv")),
                None,
            )
            if member is None:
                raise SystemExit(f"[prego] {archive_path.name}: no database_pairs.tsv member found in tarball.")
            expected_size = member.size
            need_extract = not payload_file.exists() or payload_file.stat().st_size != expected_size
            if need_extract:
                if payload_file.exists():
                    print(
                        f"[prego] cached {payload_file.name} size "
                        f"({payload_file.stat().st_size:,}) != tar member "
                        f"({expected_size:,}); re-extracting"
                    )
                else:
                    print(f"[prego] extracting {archive_path.name} → {payload_file.name}...")
                with tf.extractfile(member) as src, payload_file.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)

        print(f"[prego] processing {payload_file.name} ({payload_file.stat().st_size / 1024**3:.1f} GB)")
        row_iter = iter_database_pairs(payload_file)
        if show_status:
            row_iter = tqdm(row_iter, desc=archive_path.name, unit="rows")
        for row, err in row_iter:
            self._stats["rows_read"] += 1
            if err is not None:
                self._stats["rows_malformed"] += 1
                continue
            self._process_row(row, doid_to_mondo, node_writer, edge_writer)

    # ------------------------------------------------------------------ #
    # Per-row processing.
    # ------------------------------------------------------------------ #

    def _process_row(self, row, doid_to_mondo, node_writer, edge_writer):
        """Route one raw row through the canonical-direction filter + edge emission."""
        try:
            entity1_type = int(row[0])
            entity1_id = row[1]
            entity2_type = int(row[2])
            entity2_id = row[3]
            source = row[4]
            channel = row[5]
            # Defensive: an empty entity_id would produce a malformed
            # CURIE like `NCBITaxon:` on emit. Not seen in the canary,
            # but a two-line check is cheap insurance.
            if not entity1_id or not entity2_id:
                self._record_drop("empty_id", entity1_type, entity1_id, entity2_type, entity2_id)
                return
            score = row[6]
            direct_flag = row[7]
            evidence_url = row[8]
        except (ValueError, IndexError):
            self._stats["rows_malformed"] += 1
            return

        outcome = classify_row(entity1_type, entity2_type)
        if outcome not in (KEEP_TAXON_TO_GO, KEEP_ENVO_TO_TAXON, KEEP_TAXON_TO_DOID, KEEP_TAXON_TO_BTO):
            self._record_drop(outcome, entity1_type, entity1_id, entity2_type, entity2_id)
            return

        if outcome == KEEP_TAXON_TO_GO:
            # Defensive: some source rows type-tag GO (-21/-22/-23) but
            # carry a non-GO identifier (rare data-quality edge case).
            if not entity2_id.startswith("GO:"):
                self._record_drop("go_id_prefix_mismatch", entity1_type, entity1_id, entity2_type, entity2_id)
                return
            subject = f"NCBITaxon:{entity1_id}"
            obj = entity2_id
            predicate = CAPABLE_OF_PREDICATE
            relation = _RELATION_CAPABLE_OF
            self._emit_node(node_writer, subject, _NCBITAXON_CATEGORY)
            self._emit_node(node_writer, obj, go_category_for_type(entity2_type))

        elif outcome == KEEP_ENVO_TO_TAXON:
            if not entity1_id.startswith("ENVO:"):
                self._record_drop("envo_id_prefix_mismatch", entity1_type, entity1_id, entity2_type, entity2_id)
                return
            subject = entity1_id
            obj = f"NCBITaxon:{entity2_id}"
            predicate = _LOCATION_OF_PREDICATE
            relation = _RELATION_LOCATION_OF
            self._emit_node(node_writer, subject, _ENVO_CATEGORY)
            self._emit_node(node_writer, obj, _NCBITAXON_CATEGORY)

        elif outcome == KEEP_TAXON_TO_DOID:
            mondo = doid_to_mondo.get(entity2_id)
            if mondo is None:
                self._stats["doid_no_mondo_xref"] += 1
                self._record_drop("doid_no_mondo_xref", entity1_type, entity1_id, entity2_type, entity2_id)
                return
            subject = f"NCBITaxon:{entity1_id}"
            obj = mondo
            predicate = _ASSOCIATED_WITH_PREDICATE
            relation = _RELATION_ASSOCIATED_WITH
            self._emit_node(node_writer, subject, _NCBITAXON_CATEGORY)
            self._emit_node(node_writer, obj, _MONDO_CATEGORY)

        else:  # KEEP_TAXON_TO_BTO
            # Some source rows type-tag BTO (-25) but carry a non-BTO
            # identifier (e.g. CLDB — Cell Line Data Base — observed in the
            # 2026-08-04 isolates canary on rows tagged -25 but with a
            # `CLDB:` entity ID). Drop to a curator-visible bucket rather
            # than emit a malformed BTO node.
            if not entity2_id.startswith("BTO:"):
                self._record_drop("bto_id_prefix_mismatch", entity1_type, entity1_id, entity2_type, entity2_id)
                return
            # Flip direction to match bacdive convention: BTO tissue is the
            # subject on `location_of` edges, taxon is the object.
            subject = entity2_id
            obj = f"NCBITaxon:{entity1_id}"
            predicate = _LOCATION_OF_PREDICATE
            relation = _RELATION_LOCATION_OF
            self._emit_node(node_writer, subject, _BTO_CATEGORY)
            self._emit_node(node_writer, obj, _NCBITAXON_CATEGORY)

        edge_writer.writerow(
            self._make_edge_row(
                subject=subject,
                predicate=predicate,
                obj=obj,
                relation=relation,
                score=score,
                channel=channel,
                source=source,
                direct_flag=direct_flag,
                evidence_url=evidence_url,
            )
        )
        self._stats["edges_emitted"] += 1
        self._stats["edges_by_shape"][outcome] += 1

    # ------------------------------------------------------------------ #
    # Writers.
    # ------------------------------------------------------------------ #

    def _emit_node(self, node_writer, node_id: str, category: str) -> None:
        """
        Emit a stub node row if not already emitted (dedup by id).

        When Phase 6b is active (:attr:`_synonym_lookup` populated), the
        dictionary's alternate names for ``node_id`` land as pipe-delimited
        values in the ``synonym`` column. The ``name`` column stays empty —
        merge-time dedup upgrades the name from the ontologies transform's
        richer row, so PREGO doesn't need to compete for that source of
        truth.
        """
        if node_id in self._emitted_nodes:
            return
        self._emitted_nodes.add(node_id)
        self._stats["unique_nodes_emitted"] += 1
        row = {col: "" for col in self.node_header}
        row[ID_COLUMN] = node_id
        row[CATEGORY_COLUMN] = category
        row[PROVIDED_BY_COLUMN] = PREGO_KNOWLEDGE_SOURCE
        synonyms = self._synonym_lookup.get(node_id)
        if synonyms:
            # Case-insensitively deduplicated at load time; sort for stable
            # output (deterministic diff on re-runs).
            row[SYNONYM_COLUMN] = "|".join(sorted(synonyms))
            self._stats["nodes_enriched_with_synonyms"] += 1
        node_writer.writerow([row[c] for c in self.node_header])

    def _make_edge_row(
        self,
        subject: str,
        predicate: str,
        obj: str,
        relation: str,
        score: str,
        channel: str,
        source: str,
        direct_flag: str,
        evidence_url: str,
    ) -> list:
        """Produce one edge row matching ``self.edge_header``."""
        row = {col: "" for col in self.edge_header}
        row[SUBJECT_COLUMN] = subject
        row[PREDICATE_COLUMN] = predicate
        row[OBJECT_COLUMN] = obj
        row[RELATION_COLUMN] = relation
        row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = PREGO_KNOWLEDGE_SOURCE
        row[PREGO_SCORE_COLUMN] = score
        row[PREGO_CHANNEL_COLUMN] = channel
        row[PREGO_SOURCE_COLUMN] = source
        row[PREGO_DIRECT_FLAG_COLUMN] = direct_flag
        row[PREGO_EVIDENCE_URL_COLUMN] = evidence_url
        return [row[c] for c in self.edge_header]

    # ------------------------------------------------------------------ #
    # Drop tracking + report.
    # ------------------------------------------------------------------ #

    _MAX_EXAMPLES_PER_REASON = 500

    def _record_drop(self, reason, e1_type, e1_id, e2_type, e2_id) -> None:
        """
        Increment drop counters and record an exemplar row per (reason, key).

        Key is `(entity1_type, entity1_id, entity2_type, entity2_id)` compressed
        to a short string. Per-reason exemplar count is capped so a
        10^8-row run doesn't accumulate an unbounded dict.
        """
        self._stats["rows_dropped"] += 1
        self._stats["rows_dropped_by_reason"][reason] += 1
        bucket = self._drop_examples[reason]
        if len(bucket) >= self._MAX_EXAMPLES_PER_REASON:
            return
        key = f"{e1_type}:{e1_id}->{e2_type}:{e2_id}"
        bucket[key] += 1

    def _write_unmapped_report(self) -> None:
        """
        Emit ``unmapped_associations.tsv`` — the per-run curation report.

        One row per (reason, exemplar_key) with an occurrence count, sorted
        by (reason, -count) so curators can scan the largest drop buckets
        first.
        """
        with self.unmapped_report_file.open("w", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(["reason", "exemplar_row", "occurrences", "reason_total"])
            for reason in sorted(self._drop_examples):
                total = self._stats["rows_dropped_by_reason"][reason]
                sorted_examples = sorted(self._drop_examples[reason].items(), key=lambda kv: (-kv[1], kv[0]))
                for key, count in sorted_examples:
                    writer.writerow([reason, key, count, total])

    # ------------------------------------------------------------------ #
    # Summary.
    # ------------------------------------------------------------------ #

    def _print_summary(self) -> None:
        """One-line summary a run script or CI log can grep for."""
        by_shape = dict(self._stats["edges_by_shape"])
        by_reason = dict(self._stats["rows_dropped_by_reason"])
        print(
            f"[prego] rows_read={self._stats['rows_read']:,} "
            f"malformed={self._stats['rows_malformed']:,} "
            f"edges_emitted={self._stats['edges_emitted']:,} "
            f"nodes_emitted={self._stats['unique_nodes_emitted']:,} "
            f"dropped={self._stats['rows_dropped']:,} "
            f"doid_no_mondo={self._stats['doid_no_mondo_xref']:,}"
        )
        if by_shape:
            print(f"[prego] edges_by_shape={by_shape}")
        if by_reason:
            print(f"[prego] rows_dropped_by_reason={by_reason}")
