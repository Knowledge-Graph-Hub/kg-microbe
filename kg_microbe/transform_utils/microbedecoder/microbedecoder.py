"""
MicrobeDecoder transform (Hackmann & Zhang, Sci Adv 2023).

Ingests the wide per-LPSN-strain CSV MicrobeDecoder publishes on GitHub —
`Shiny/MicrobeDecoder/data/database/database.zip` — into KGX-format nodes
and edges. The database is the actively-maintained successor to
FermentationExplorer and pre-joins four curated fermentation-metabolism
sources KG-Microbe does not otherwise cover:

- **Bergey's Manual of Systematics of Archaea and Bacteria** — expert
  curation of `Type_of_metabolism`, `Major_end_products`,
  `Minor_end_products`, `Substrates_for_end_products`
- **VPI Anaerobe Laboratory Manual** — independent second-opinion
  fermentation profiles for anaerobes
- **Primary literature** — hand-curated end-products with DOI/PMID
  citations
- **FAPROTAX** — functional labels joined at strain granularity

Also emits a `biolink:close_match` crosswalk from every `lpsn:<LPSN_ID>`
row to `NCBITaxon:`, `GTDB:`, `bacdive:`, `GOLD:`, and `IMG:` — a
pre-joined identity mapping worth ~50 K edges in its own right.

Design decisions locked from the plan-mode Q&A:

1. **Node identity**: attach every edge to the *existing* `lpsn:<LPSN_ID>`
   node emitted by the LPSN transform. This transform emits edges only
   (plus terminal nodes for end-products / cross-refs / provisional
   placeholders); it does not re-emit LPSN taxon nodes.
2. **BacDive_* replay**: ingested with `primary_knowledge_source =
   infores:microbedecoder` so the paper's 2024-11-07 BacDive snapshot
   stays reproducible. The fresher `bacdive` transform is authoritative
   in the merged KG; merge-time dedup keeps both edges around,
   distinguishable by provenance.

License: CC BY 4.0 (matches the upstream repo).
"""

from __future__ import annotations

import csv
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    BERGEY_KNOWLEDGE_SOURCE,
    CAPABLE_OF,
    CAPABLE_OF_PREDICATE,
    CATEGORY_COLUMN,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    COMPOUND_PREFIX,
    DESCRIPTION_COLUMN,
    FAPROTAX_KNOWLEDGE_SOURCE,
    HAS_OUTPUT_RELATION,
    HAS_PHENOTYPE,
    HAS_PHENOTYPE_PREDICATE,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    LITERATURE_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    MANUAL_AGENT,
    METABOLISM_CATEGORY,
    MICROBEDECODER,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    MICROBEDECODER_RAW_DIR,
    NAME_COLUMN,
    NCBI_TO_SUBSTRATE_EDGE,
    OBJECT_COLUMN,
    PATHWAY_PREFIX,
    PHENOTYPIC_CATEGORY,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PRODUCES_PREDICATE,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SMALL_MOLECULE_CATEGORY,
    SUBJECT_COLUMN,
    TRAIT_PREFIX,
    TROPHICALLY_INTERACTS_WITH,
    VPI_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.utils import (
    BACDIVE_SNAPSHOT_COLUMNS,
    CROSSWALK_COLUMNS,
    LPSN_ID_COLUMN,
    format_citation,
    is_empty_cell,
    iter_metabolism_columns,
    slugify_label,
    split_multivalue,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.pandas_utils import drop_duplicates

logger = logging.getLogger(__name__)

# Default local zip name (matches the `download.yaml` local_name entry).
_DEFAULT_ZIP_NAME = "microbedecoder_database.zip"
# Filename inside the zip. MicrobeDecoder ships one CSV: `database.csv`.
_CSV_INSIDE_ZIP = "database.csv"
# Per-run curation report of labels that fell through the mapping chain
# and landed as ``kgmicrobe.*`` placeholders. Follows the metatraits
# ``unmapped_traits.tsv`` convention (per-source, in the transform's
# output dir, TSV with a stable header).
_UNMAPPED_REPORT_FILENAME = "unmapped_labels.tsv"

# Predicate map from metabolism-source group_label to the InforES knowledge
# source used on every emitted edge. Kept as a dict so tests can override
# without patching the constants module.
_GROUP_TO_KS: Dict[str, str] = {
    "bergey": BERGEY_KNOWLEDGE_SOURCE,
    "vpi": VPI_KNOWLEDGE_SOURCE,
    "literature": LITERATURE_KNOWLEDGE_SOURCE,
    "faprotax": FAPROTAX_KNOWLEDGE_SOURCE,
}


class MicrobeDecoderTransform(Transform):

    """Transform the MicrobeDecoder wide CSV into KGX nodes and edges."""

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        chemical_loader: Any = None,
    ) -> None:
        """
        Instantiate.

        Parameters
        ----------
        input_dir:
            Directory holding the downloaded MicrobeDecoder zip (or an
            already-unzipped ``database.csv``). Defaults to
            :data:`kg_microbe.transform_utils.constants.RAW_DATA_DIR` via
            the base :class:`Transform`.
        output_dir:
            Where to write ``nodes.tsv`` / ``edges.tsv``. Defaults to
            ``data/transformed/microbedecoder``.
        chemical_loader:
            Injectable ChEBI resolver. When ``None`` (production default),
            :meth:`run` lazily loads a :class:`ChemicalMappingLoader` — same
            deferral pattern as ``lpsn._load_ncbi_adapter`` so a missing
            input CSV fails fast without triggering the full mapping-load
            path. Tests inject a fake to keep fixtures self-contained.

        """
        super().__init__(MICROBEDECODER, input_dir, output_dir)
        self.knowledge_source = MICROBEDECODER_KNOWLEDGE_SOURCE
        self.chemical_loader = chemical_loader
        # Track dedup state so unmatched-label placeholders are emitted
        # once per run. Cross-ref targets (NCBITaxon/GTDB/bacdive/GOLD/IMG)
        # and successfully-resolved CHEBI CURIEs are never stubbed here —
        # their authoritative nodes come from other transforms.
        self._seen_nodes: set = set()
        # Per-label tally of placeholder mintings so the end-of-run
        # ``unmapped_labels.tsv`` can prioritise curation by frequency.
        # Keyed by ``(placeholder_curie, category)``; value tracks the raw
        # label, the pipe-set of source columns it appeared in, and the
        # occurrence count. See ``_write_unmapped_report``.
        self._unmapped: Dict[tuple, Dict[str, object]] = {}
        # End-of-run summary counters.
        self._stats: Dict[str, int] = {
            "rows_processed": 0,
            "crosswalk_edges": 0,
            "metabolism_edges": 0,
            "bacdive_snapshot_edges": 0,
            "unmatched_labels": 0,
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Emit nodes.tsv and edges.tsv from ``database.csv``.

        Parameters
        ----------
        data_file:
            Optional override for the input path. Accepts either a zip
            (extracted here) or an already-unzipped CSV. Default resolves
            to ``<input_base_dir>/microbedecoder_database.zip`` when the
            zip is present, else ``<input_base_dir>/database.csv``.
        show_status:
            Accepted for CLI compatibility; unused because the parse pass
            is fast enough (~8 K rows) that a progress bar isn't worth
            pulling ``tqdm`` in for.

        """
        _ = show_status
        csv_path = self._resolve_input(data_file)
        if not csv_path.is_file():
            raise FileNotFoundError(
                f"MicrobeDecoder database not found at {csv_path}. "
                "Run `poetry run kg download -t microbedecoder` to fetch it "
                "(fetches https://github.com/thackmann/MicrobeDecoder/raw/main/"
                "Shiny/MicrobeDecoder/data/database/database.zip; CC BY 4.0)."
            )

        # Lazy loader: constructor stays inert with respect to expensive
        # chemical-mapping resources. Matches the round-34 lpsn pattern
        # (get_ontology_adapter is deferred to run()).
        if self.chemical_loader is None:
            from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

            try:
                self.chemical_loader = ChemicalMappingLoader()
            except FileNotFoundError:
                logger.warning(
                    "[microbedecoder] Unified chemical mappings not present; "
                    "end-product CHEBI resolution disabled — every metabolism "
                    "label falls through to a kgmicrobe.compound:* placeholder."
                )
                self.chemical_loader = None

        self.output_dir.mkdir(parents=True, exist_ok=True)

        with (
            open(self.output_node_file, "w", newline="") as node_fh,
            open(self.output_edge_file, "w", newline="") as edge_fh,
        ):
            node_writer = csv.writer(node_fh, delimiter="\t")
            edge_writer = csv.writer(edge_fh, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)

            # ``dtype=str`` on the whole CSV so numeric-looking columns
            # (LPSN_ID, NCBI_Taxonomy_ID, IMG_Genome_ID) don't get coerced
            # to floats with a ``.0`` suffix that then leaks into CURIEs.
            # NaN cells arrive as the string ``"nan"``; :func:`is_empty_cell`
            # recognises that already.
            #
            # ``encoding_errors="replace"`` because the real MicrobeDecoder
            # CSV (R-produced) is mixed encoding: mostly UTF-8 (0xc3 lead
            # bytes for ``°``, ``©``, fraction glyphs) with a handful of
            # sporadic raw Latin-1 bytes (e.g. ``0xe9`` = ``é``) that break
            # strict UTF-8 decode. Replace on error rather than fall back
            # to Latin-1: latin-1 would misread every legitimate UTF-8
            # multi-byte sequence (``°`` becomes ``°``, etc). U+FFFD
            # affects ~2 bytes out of 57 MB — acceptable aesthetic loss
            # on the name field, no impact on any CURIE.
            df = pd.read_csv(
                csv_path,
                dtype=str,
                keep_default_na=False,
                low_memory=False,
                encoding="utf-8",
                encoding_errors="replace",
            )
            for _, row_series in df.iterrows():
                row = row_series.to_dict()
                self._process_row(row, node_writer, edge_writer)

        # Sorted dedup: keeps the output stable across runs and lets the
        # merged KG collapse duplicates cheaply.
        drop_duplicates(self.output_node_file, sort_by_column=ID_COLUMN)
        drop_duplicates(self.output_edge_file, sort_by_column=SUBJECT_COLUMN)
        # Curation queue: per-label placeholder tally sorted by frequency
        # descending. Matches the metatraits `unmapped_traits.tsv` pattern.
        self._write_unmapped_report()
        self._log_summary()

    # ------------------------------------------------------------------
    # Row processing
    # ------------------------------------------------------------------
    def _process_row(
        self,
        row: Dict[str, Any],
        node_writer: "csv._writer",
        edge_writer: "csv._writer",
    ) -> None:
        """
        Emit all crosswalk + metabolism + BacDive-snapshot edges for one row.

        Deliberately does NOT emit a node for the ``lpsn:<LPSN_ID>``
        subject: LPSN taxon nodes are the ``lpsn`` transform's product.
        Emitting a stub here would create a shallow duplicate the merge
        step has to dedup, and violates the add-transform skill's rule
        against stubbing cross-referenced entities that already exist
        in KG-Microbe. ``lpsn`` is documented as a hard dependency in
        CLAUDE.md.
        """
        lpsn_id = row.get(LPSN_ID_COLUMN)
        if is_empty_cell(lpsn_id):
            return
        subject_curie = f"{LPSN_PREFIX}{str(lpsn_id).strip()}"
        self._stats["rows_processed"] += 1

        self._emit_crosswalk_edges(subject_curie, row, node_writer, edge_writer)
        self._emit_metabolism_edges(subject_curie, row, node_writer, edge_writer)
        self._emit_bacdive_snapshot_edges(subject_curie, row, node_writer, edge_writer)

    # ------------------------------------------------------------------
    # Crosswalk edges (novel identity mapping MicrobeDecoder pre-joins)
    # ------------------------------------------------------------------
    def _emit_crosswalk_edges(
        self,
        subject: str,
        row: Dict[str, Any],
        node_writer: "csv._writer",
        edge_writer: "csv._writer",
    ) -> None:
        """One `biolink:close_match` edge per non-empty crosswalk cell."""
        for column, prefix, _formatter in CROSSWALK_COLUMNS:
            raw = row.get(column)
            if is_empty_cell(raw):
                continue
            local_id = str(raw).strip()
            # Strip a stray leading prefix if the source already CURIE'd it
            # (`NCBI_Taxonomy_ID` occasionally arrives as ``"NCBITaxon:562"``
            # rather than a bare integer — normalise so downstream nodes
            # merge cleanly).
            if local_id.upper().startswith(prefix.upper()):
                local_id = local_id.split(":", 1)[1]
            object_curie = f"{prefix}{local_id}"
            edge_writer.writerow(
                self._make_edge_row(
                    subject,
                    CLOSE_MATCH_PREDICATE,
                    object_curie,
                    CLOSE_MATCH_RELATION,
                    self.knowledge_source,
                )
            )
            self._stats["crosswalk_edges"] += 1

    # ------------------------------------------------------------------
    # Metabolism edges (Bergey / VPI / Literature / FAPROTAX)
    # ------------------------------------------------------------------
    def _emit_metabolism_edges(
        self,
        subject: str,
        row: Dict[str, Any],
        node_writer: "csv._writer",
        edge_writer: "csv._writer",
    ) -> None:
        """Emit capable_of / produces / consumes edges per metabolism source."""
        for group_label, fields in iter_metabolism_columns(row):
            provenance = _GROUP_TO_KS[group_label]
            citation_curie = format_citation(fields.get("citation"))

            # `Type_of_metabolism` label → capable_of a metabolism-class
            # object. Uses a kgmicrobe.pathway: placeholder for now;
            # curated METPO mappings (via load_metpo_mappings) can promote
            # these to METPO: CURIEs in a follow-up curation pass.
            type_of_metabolism = fields.get("type_of_metabolism")
            if not is_empty_cell(type_of_metabolism):
                for label in split_multivalue(type_of_metabolism):
                    obj = self._resolve_metabolism_curie(
                        label, node_writer, source_column=f"{group_label}:type_of_metabolism"
                    )
                    edge_writer.writerow(
                        self._make_edge_row(
                            subject,
                            CAPABLE_OF_PREDICATE,
                            obj,
                            CAPABLE_OF,
                            provenance,
                            publications=citation_curie,
                        )
                    )
                    self._stats["metabolism_edges"] += 1

            # End-product rows → biolink:produces + relation has_output.
            # `qualifier` (major / minor) is carried in the edge description
            # so downstream queries can filter without a schema change.
            for role, qualifier in (
                ("major_end_products", "major"),
                ("minor_end_products", "minor"),
            ):
                for label in split_multivalue(fields.get(role)):
                    obj = self._resolve_chemical_curie(label, node_writer, source_column=f"{group_label}:{role}")
                    edge_writer.writerow(
                        self._make_edge_row(
                            subject,
                            PRODUCES_PREDICATE,
                            obj,
                            HAS_OUTPUT_RELATION,
                            provenance,
                            description=qualifier,
                            publications=citation_curie,
                        )
                    )
                    self._stats["metabolism_edges"] += 1

            # Substrate rows → biolink:consumes + relation trophically_interacts_with.
            # Uses NCBI_TO_SUBSTRATE_EDGE (the standard constant every
            # organism→substrate emitter routes through, incl. madin_etal)
            # so merged-KG queries stay consistent.
            for label in split_multivalue(fields.get("substrates")):
                obj = self._resolve_chemical_curie(label, node_writer, source_column=f"{group_label}:substrates")
                edge_writer.writerow(
                    self._make_edge_row(
                        subject,
                        NCBI_TO_SUBSTRATE_EDGE,
                        obj,
                        TROPHICALLY_INTERACTS_WITH,
                        provenance,
                        publications=citation_curie,
                    )
                )
                self._stats["metabolism_edges"] += 1

    # ------------------------------------------------------------------
    # BacDive_* snapshot replay (per user decision: keep the paper's exact
    # 2024-11-07 snapshot alongside the fresher `bacdive` transform)
    # ------------------------------------------------------------------
    def _emit_bacdive_snapshot_edges(
        self,
        subject: str,
        row: Dict[str, Any],
        node_writer: "csv._writer",
        edge_writer: "csv._writer",
    ) -> None:
        """
        Emit one has_phenotype edge per non-empty BacDive_* cell.

        Every edge carries ``primary_knowledge_source =
        infores:microbedecoder`` so the paper's exact snapshot stays
        distinguishable from the live bacdive transform's output at
        merge time.
        """
        for column in BACDIVE_SNAPSHOT_COLUMNS:
            raw = row.get(column)
            if is_empty_cell(raw):
                continue
            for label in split_multivalue(raw):
                obj = self._resolve_phenotype_curie(label, column, node_writer)
                edge_writer.writerow(
                    self._make_edge_row(
                        subject,
                        HAS_PHENOTYPE_PREDICATE,
                        obj,
                        HAS_PHENOTYPE,
                        self.knowledge_source,
                        description=column.replace("BacDive_", "").replace("_", " "),
                    )
                )
                self._stats["bacdive_snapshot_edges"] += 1

    # ------------------------------------------------------------------
    # CURIE resolution
    # ------------------------------------------------------------------
    def _resolve_chemical_curie(
        self,
        label: str,
        node_writer: "csv._writer",
        source_column: str,
    ) -> str:
        """
        Resolve an end-product / substrate label to a CHEBI CURIE or placeholder.

        Successful CHEBI resolution → return the CURIE **without** emitting
        a node stub; the ontologies transform owns the authoritative CHEBI
        node (per the add-transform skill's "don't stub cross-refs" rule).
        Miss → mint a ``kgmicrobe.compound:<slug>`` placeholder and emit
        the terminal stub (nothing else will). ``source_column`` is
        recorded in the unmapped-labels report so curators know which
        source axis to prioritise.
        """
        curie: Optional[str] = None
        if self.chemical_loader is not None:
            try:
                curie = self.chemical_loader.find_chebi_by_name(label, fuzzy_stereochemistry=True)
            except Exception as exc:  # noqa: BLE001 — chemical loader has broad failure modes
                logger.debug("[microbedecoder] chebi lookup failed for %r: %s", label, exc)
        if curie:
            return curie
        return self._mint_placeholder(
            label,
            node_writer,
            prefix=COMPOUND_PREFIX,
            category=SMALL_MOLECULE_CATEGORY,
            source_column=source_column,
        )

    def _resolve_metabolism_curie(
        self,
        label: str,
        node_writer: "csv._writer",
        source_column: str,
    ) -> str:
        """
        Resolve a type_of_metabolism label to a pathway CURIE or placeholder.

        v1: no METPO integration yet — always mints a
        ``kgmicrobe.pathway:<slug>`` placeholder (same prefix ``madin_etal``
        uses for its unmatched pathway labels). A follow-up can promote
        recognised labels (Fermentation, Homofermentative, Methanogenesis, …)
        to METPO CURIEs via ``load_metpo_mappings("microbedecoder synonym")``
        once the upstream METPO ROBOT template gains that synonym column.
        """
        return self._mint_placeholder(
            label,
            node_writer,
            prefix=PATHWAY_PREFIX,
            category=METABOLISM_CATEGORY,
            source_column=source_column,
        )

    def _resolve_phenotype_curie(
        self,
        label: str,
        source_column: str,
        node_writer: "csv._writer",
    ) -> str:
        """
        Resolve a BacDive_* value. v1: placeholder in the trait prefix.

        Category is left generic (:data:`PHENOTYPIC_CATEGORY`); the fresher
        ``bacdive`` transform provides the semantically-correct edge
        (MicrobeDecoder ingests the 2024-11-07 snapshot per the plan-mode
        Q&A). ``source_column`` is recorded in the unmapped-labels report
        so curators can distinguish the same short string (``yes``, ``0``)
        appearing under different BacDive columns.
        """
        return self._mint_placeholder(
            label,
            node_writer,
            prefix=TRAIT_PREFIX,
            category=PHENOTYPIC_CATEGORY,
            source_column=source_column,
        )

    def _mint_placeholder(
        self,
        label: str,
        node_writer: "csv._writer",
        prefix: str,
        category: str,
        source_column: str,
    ) -> str:
        """
        Return a stable ``<prefix><slug>`` CURIE and emit the terminal stub.

        Placeholder CURIEs land in the caller-supplied ``kgmicrobe.*``
        prefix (``pathway``, ``compound``, or ``trait`` — each already
        registered as a section of ``custom_curies.yaml``). The stub node
        carries the raw source label so the merged KG surfaces something
        human-readable even before the label gets a proper METPO / CHEBI
        mapping. ``source_column`` is tallied into ``self._unmapped`` so
        the end-of-run ``unmapped_labels.tsv`` report knows which source
        column(s) contributed this placeholder.
        """
        curie = f"{prefix}{slugify_label(label)}"
        self._ensure_terminal_node(curie, category, label, node_writer)
        self._stats["unmatched_labels"] += 1
        # Aggregate per placeholder CURIE. Same CURIE from multiple
        # columns keeps them all in the ``source_columns`` set so the
        # curation report shows the union.
        key = (curie, category)
        entry = self._unmapped.setdefault(
            key,
            {"label": label, "source_columns": set(), "occurrences": 0},
        )
        entry["source_columns"].add(source_column)  # type: ignore[union-attr]
        entry["occurrences"] = int(entry["occurrences"]) + 1
        return curie

    def _write_unmapped_report(self) -> None:
        """
        Emit a per-label curation queue as ``unmapped_labels.tsv``.

        Sorted by occurrence count descending so the top rows are the
        highest-leverage curation targets. Feeds the "which MicrobeDecoder
        labels most need a canonical mapping" question the paper's
        readers and downstream curators care about (issue #650).

        Columns:

        - ``placeholder_curie`` — the ``kgmicrobe.{pathway,compound,trait}:<slug>``
          CURIE this run minted for the label
        - ``category`` — the placeholder's biolink category
        - ``label`` — the raw source label
        - ``source_columns`` — pipe-delimited set of source columns this
          label appeared under (``bergey:type_of_metabolism`` /
          ``vpi:major_end_products`` / ``BacDive_Oxygen_tolerance`` / …)
        - ``occurrences`` — how many edges this placeholder anchors this run

        No file is written when the run produced zero placeholders (all
        labels mapped — the aspirational state).
        """
        if not self._unmapped:
            return
        target = self.output_dir / _UNMAPPED_REPORT_FILENAME
        rows = [
            {
                "placeholder_curie": curie,
                "category": category,
                "label": entry["label"],
                "source_columns": "|".join(sorted(entry["source_columns"])),  # type: ignore[arg-type]
                "occurrences": entry["occurrences"],
            }
            for (curie, category), entry in self._unmapped.items()
        ]
        # Sort by count desc, then CURIE asc for stable output.
        rows.sort(key=lambda r: (-int(r["occurrences"]), r["placeholder_curie"]))
        with open(target, "w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["placeholder_curie", "category", "label", "source_columns", "occurrences"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows(rows)

    def _ensure_terminal_node(
        self,
        curie: str,
        category: str,
        name: str,
        node_writer: "csv._writer",
    ) -> None:
        """
        Emit a placeholder terminal node once per run (dedup via _seen_nodes).

        Only ever called for placeholder / unmatched-label CURIEs — never
        for a resolved cross-reference target (NCBITaxon, GTDB, CHEBI,
        bacdive, GOLD, IMG) whose authoritative node is provided by
        another transform. See the add-transform skill's Phase 6
        "anti-patterns" for the reasoning.
        """
        if curie in self._seen_nodes:
            return
        self._seen_nodes.add(curie)
        node_writer.writerow(self._make_node_row(curie, category, name))

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------
    def _make_node_row(
        self,
        node_id: str,
        category: str,
        name: str,
        description: Optional[str] = None,
    ) -> List:
        """Build a node row in canonical Transform.node_header order."""
        row = [None] * len(self.node_header)
        row[self.node_header.index(ID_COLUMN)] = node_id
        row[self.node_header.index(CATEGORY_COLUMN)] = category
        row[self.node_header.index(NAME_COLUMN)] = name
        row[self.node_header.index(DESCRIPTION_COLUMN)] = description
        row[self.node_header.index(PROVIDED_BY_COLUMN)] = self.knowledge_source
        return row

    def _make_edge_row(
        self,
        subject: str,
        predicate: str,
        obj: str,
        relation: str,
        primary_knowledge_source: str,
        description: Optional[str] = None,
        publications: Optional[str] = None,
    ) -> List:
        """
        Build an edge row in canonical Transform.edge_header order.

        ``description`` (currently used for the major/minor qualifier) and
        ``publications`` (PMID/DOI CURIE) are accepted for forward-compat but
        currently unused: the canonical edge header has no slot for them,
        and no other transform ships per-edge citation columns today. A
        follow-up (issue #TBD) can promote them to their own columns without
        touching call sites.
        """
        del description  # v1: dropped; canonical header has no description column
        del publications  # v1: dropped; canonical header has no publications column
        row = [None] * len(self.edge_header)
        row[self.edge_header.index(SUBJECT_COLUMN)] = subject
        row[self.edge_header.index(PREDICATE_COLUMN)] = predicate
        row[self.edge_header.index(OBJECT_COLUMN)] = obj
        row[self.edge_header.index(RELATION_COLUMN)] = relation
        row[self.edge_header.index(PRIMARY_KNOWLEDGE_SOURCE_COLUMN)] = primary_knowledge_source
        row[self.edge_header.index(KNOWLEDGE_LEVEL_COLUMN)] = KNOWLEDGE_ASSERTION
        row[self.edge_header.index(AGENT_TYPE_COLUMN)] = MANUAL_AGENT
        return row

    # ------------------------------------------------------------------
    # Input resolution + summary
    # ------------------------------------------------------------------
    def _resolve_input(self, data_file: Union[Optional[Path], Optional[str]]) -> Path:
        """Return a Path to the CSV, unzipping first if only the zip is present."""
        # Explicit override wins.
        if data_file is not None:
            candidate = Path(data_file)
            if not candidate.is_absolute():
                candidate = self.input_base_dir / candidate
            if candidate.suffix.lower() == ".zip":
                return self._unzip(candidate)
            return candidate

        # Search order: extracted CSV under the transform's raw dir → zip
        # under the raw dir → CSV under the caller's input_base_dir → zip
        # under input_base_dir. The first three cover regular downloads;
        # the last is the developer/test convenience path.
        for candidate in (
            MICROBEDECODER_RAW_DIR / _CSV_INSIDE_ZIP,
            MICROBEDECODER_RAW_DIR / _DEFAULT_ZIP_NAME,
            self.input_base_dir / _CSV_INSIDE_ZIP,
            self.input_base_dir / _DEFAULT_ZIP_NAME,
        ):
            if not candidate.is_file():
                continue
            return self._unzip(candidate) if candidate.suffix.lower() == ".zip" else candidate
        # Fall through — return the first-choice path so run()'s
        # FileNotFoundError message points at a canonical location.
        return MICROBEDECODER_RAW_DIR / _CSV_INSIDE_ZIP

    def _unzip(self, zip_path: Path) -> Path:
        """Extract ``database.csv`` from the zip to a sibling location and cache it."""
        target_dir = zip_path.parent
        csv_target = target_dir / _CSV_INSIDE_ZIP
        if csv_target.is_file():
            return csv_target
        with zipfile.ZipFile(zip_path) as zf:
            # Robust: the archive nests the CSV under a directory when
            # GitHub delivers it as a source download. Find the first entry
            # matching the target filename, regardless of nesting.
            members = [n for n in zf.namelist() if Path(n).name == _CSV_INSIDE_ZIP]
            if not members:
                raise FileNotFoundError(
                    f"{zip_path} does not contain {_CSV_INSIDE_ZIP}; members were {zf.namelist()!r}"
                )
            member = members[0]
            with zf.open(member) as src, open(csv_target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return csv_target

    def _log_summary(self) -> None:
        """Print a one-line summary of what got emitted."""
        s = self._stats
        logger.info(
            "[microbedecoder] rows=%d, crosswalk_edges=%d, metabolism_edges=%d, "
            "bacdive_snapshot_edges=%d, unmatched_labels=%d",
            s["rows_processed"],
            s["crosswalk_edges"],
            s["metabolism_edges"],
            s["bacdive_snapshot_edges"],
            s["unmatched_labels"],
        )
        print(
            f"[microbedecoder] rows={s['rows_processed']}, "
            f"crosswalk_edges={s['crosswalk_edges']}, "
            f"metabolism_edges={s['metabolism_edges']}, "
            f"bacdive_snapshot_edges={s['bacdive_snapshot_edges']}, "
            f"unmatched_labels={s['unmatched_labels']}"
        )
