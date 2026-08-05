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
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.prego.utils import (
    KEEP_ENVO_TO_TAXON,
    KEEP_TAXON_TO_DOID,
    KEEP_TAXON_TO_GO,
    classify_row,
    go_category_for_type,
    iter_database_pairs,
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

# ---------------------------------------------------------------------------
# Extra edge columns beyond the KGX minimum. Kept as a small tuple so the
# header is single-sourced.
# ---------------------------------------------------------------------------
_PREGO_EDGE_EXTRA_COLUMNS = (
    PREGO_SCORE_COLUMN,
    PREGO_CHANNEL_COLUMN,
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
        }
        # Node de-dup set — a CURIE seen twice only emits one node row.
        self._emitted_nodes: set = set()
        # Detailed drop report keyed by (reason, exemplar_id) so the report
        # can point curators at the specific IDs that got dropped, capped
        # per-reason to avoid unbounded memory on 10^8-row runs.
        self._drop_examples: dict = defaultdict(lambda: defaultdict(int))

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """
        Read every PREGO archive and emit nodes + edges + unmapped-associations report.

        ``data_file`` is accepted for base-class compatibility but ignored —
        PREGO ingests every ``*.tar.gz`` in its raw directory (typically the
        three channels: literature / environmental_samples /
        annotated_genomes_isolates). ``show_status`` toggles the tqdm progress
        bar; false is used by the pytest suite to keep captured output clean.
        """
        del data_file  # multi-archive ingest; scanned from raw dir

        prego_raw_dir = self.input_base_dir / PREGO
        if not prego_raw_dir.is_dir():
            raise SystemExit(f"[prego] {prego_raw_dir} not found. Run `poetry run kg download -t prego` first.")

        archives = sorted(prego_raw_dir.glob("*.tar.gz"))
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
    # Per-archive processing.
    # ------------------------------------------------------------------ #

    def _process_archive(self, archive_path, doid_to_mondo, node_writer, edge_writer, show_status: bool = True):
        """Extract ``database_pairs.tsv`` from one archive and stream it row-by-row."""
        # PREGO archives are single-file tar.gz payloads (verified 2026-08-04 canary).
        # Extract the payload into the archive's own directory next to the tarball
        # so the same file can be reused across re-runs without paying decompression
        # cost twice.
        payload_dir = archive_path.parent / archive_path.stem.replace(".tar", "_extracted")
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_file = payload_dir / "database_pairs.tsv"
        if not payload_file.exists():
            print(f"[prego] extracting {archive_path.name} → {payload_file.name}...")
            with tarfile.open(archive_path, mode="r:gz") as tf:
                for member in tf.getmembers():
                    if not member.name.endswith("database_pairs.tsv"):
                        continue
                    with tf.extractfile(member) as src, payload_file.open("wb") as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
                    break

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
            score = row[6]
            direct_flag = row[7]
            evidence_url = row[8]
        except (ValueError, IndexError):
            self._stats["rows_malformed"] += 1
            return

        del source  # column carried in edge_attribute space for now; unused

        outcome = classify_row(entity1_type, entity2_type)
        if outcome not in (KEEP_TAXON_TO_GO, KEEP_ENVO_TO_TAXON, KEEP_TAXON_TO_DOID):
            self._record_drop(outcome, entity1_type, entity1_id, entity2_type, entity2_id)
            return

        if outcome == KEEP_TAXON_TO_GO:
            subject = f"NCBITaxon:{entity1_id}"
            obj = entity2_id  # already "GO:xxxxxxx"
            predicate = CAPABLE_OF_PREDICATE
            relation = _RELATION_CAPABLE_OF
            self._emit_node(node_writer, subject, _NCBITAXON_CATEGORY)
            self._emit_node(node_writer, obj, go_category_for_type(entity2_type))

        elif outcome == KEEP_ENVO_TO_TAXON:
            subject = entity1_id  # already "ENVO:xxxxxxx"
            obj = f"NCBITaxon:{entity2_id}"
            predicate = _LOCATION_OF_PREDICATE
            relation = _RELATION_LOCATION_OF
            self._emit_node(node_writer, subject, _ENVO_CATEGORY)
            self._emit_node(node_writer, obj, _NCBITAXON_CATEGORY)

        else:  # KEEP_TAXON_TO_DOID
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

        edge_writer.writerow(
            self._make_edge_row(
                subject=subject,
                predicate=predicate,
                obj=obj,
                relation=relation,
                score=score,
                channel=channel,
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
        """Emit a stub node row if not already emitted (dedup by id)."""
        if node_id in self._emitted_nodes:
            return
        self._emitted_nodes.add(node_id)
        self._stats["unique_nodes_emitted"] += 1
        row = {col: "" for col in self.node_header}
        row[ID_COLUMN] = node_id
        row[CATEGORY_COLUMN] = category
        row[PROVIDED_BY_COLUMN] = PREGO_KNOWLEDGE_SOURCE
        node_writer.writerow([row[c] for c in self.node_header])

    def _make_edge_row(
        self,
        subject: str,
        predicate: str,
        obj: str,
        relation: str,
        score: str,
        channel: str,
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
