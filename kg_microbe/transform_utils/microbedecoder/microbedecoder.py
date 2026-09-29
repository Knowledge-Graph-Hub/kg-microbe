"""
MicrobeDecoder transform (Hackmann et al., Nucleic Acids Research 2026).

Ingests the wide LPSN-name-record CSV MicrobeDecoder publishes on GitHub —
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
- **FAPROTAX** — taxon-based functional predictions joined to source records

Also emits a `biolink:close_match` crosswalk from every `lpsn:<LPSN_ID>`
row to `NCBITaxon:`, `ncbi.assembly:` (or `GTDB:` taxonomy strings), `gold:`,
and `IMG:`. BacDive crosswalks use `kgmicrobe.strain:bacdive_*` subsumption.
An LPSN name record is not a strain identity, and its reported traits must not
be propagated as universal observations about every member of the taxon.

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

import base64
import csv
import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    ATTRIBUTE_CATEGORY,
    ATTRIBUTE_TYPE_EVIDENCE_COLUMN,
    ATTRIBUTE_TYPE_RATIONALE_COLUMN,
    ATTRIBUTE_TYPE_SOURCE_COLUMN,
    BERGEY_KNOWLEDGE_SOURCE,
    CAPABLE_OF,
    CAPABLE_OF_PREDICATE,
    CATEGORY_COLUMN,
    CHEMICAL_CATEGORY,
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    COMPOUND_PREFIX,
    COMPUTATIONAL_MODEL,
    DESCRIPTION_COLUMN,
    FAPROTAX_KNOWLEDGE_SOURCE,
    GENOME_CATEGORY,
    GOLD_ORGANISM_FOLD_FILE,
    GOLD_ORGANISM_FOLD_HEADER,
    GOLD_PREFIX,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    HAS_OUTPUT_RELATION,
    ID_COLUMN,
    INGREDIENT_PREFIX,
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
    NCBI_ASSEMBLY_PREFIX,
    NCBI_CATEGORY,
    NCBI_TO_SUBSTRATE_EDGE,
    NCBITAXON_PREFIX,
    OBJECT_COLUMN,
    ORIGINAL_OBJECT_COLUMN,
    PATHWAY_PREFIX,
    PREDICATE_COLUMN,
    PREDICTION,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PRODUCES_PREDICATE,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SMALL_MOLECULE_CATEGORY,
    SOURCE_ATTRIBUTE_PREFIX,
    SOURCE_CITATION_BYTES_COLUMN,
    SOURCE_CITATION_COLUMN,
    SOURCE_COLUMN,
    SOURCE_RECORD_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    TROPHICALLY_INTERACTS_WITH,
    VALUE_COLUMN,
    VALUE_ENCODING_COLUMN,
    VPI_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.chemical_curation import RecordChemicalCuration
from kg_microbe.transform_utils.microbedecoder.crosswalk_quarantine import (
    DEFAULT_CROSSWALK_QUARANTINE_POLICY,
    QUARANTINE_REPORT_FIELDS,
    QUARANTINE_REPORT_FILENAME,
    CrosswalkQuarantine,
    QuarantinePolicy,
)
from kg_microbe.transform_utils.microbedecoder.curation import DEFAULT_PROCESS_MAPPINGS, ProcessCuration
from kg_microbe.transform_utils.microbedecoder.phenotype_curation import (
    ATTRIBUTE_TYPE_CURATION_SOURCE,
    DEFAULT_PHENOTYPE_MAPPINGS,
    PhenotypeCuration,
    PhenotypeMapping,
)
from kg_microbe.transform_utils.microbedecoder.process_scopes import (
    DEFAULT_PROCESS_SCOPE_DEFINITIONS,
    ProcessScope,
    ProcessScopeCuration,
)
from kg_microbe.transform_utils.microbedecoder.source_annotations import is_reported_metabolism_annotation
from kg_microbe.transform_utils.microbedecoder.utils import (
    BACDIVE_CROSSWALK_COLUMN,
    BACDIVE_SNAPSHOT_COLUMNS,
    CROSSWALK_COLUMNS,
    LPSN_GENUS_COLUMN,
    LPSN_ID_COLUMN,
    LPSN_SPECIES_COLUMN,
    LPSN_SUBSPECIES_COLUMN,
    METABOLISM_GROUPS,
    crosswalk_curie,
    format_citation,
    is_empty_cell,
    iter_metabolism_columns,
    slugify_label,
    split_multivalue,
    split_multivalue_comma_only,
    split_snapshot_values,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.external_identifiers import ASSEMBLY_ACCESSION, load_assembly_aliases
from kg_microbe.utils.lpsn_utils import resolve_accepted_records
from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer

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
_PHENOTYPE_REPORT_FILENAME = "phenotype_normalizations.tsv"
_PHENOTYPE_REPORT_FIELDS = (
    SUBJECT_COLUMN,
    SOURCE_RECORD_COLUMN,
    SOURCE_COLUMN,
    VALUE_COLUMN,
    VALUE_ENCODING_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    AGENT_TYPE_COLUMN,
    "target_curie",
    "target_label",
    "target_category",
    "evidence_uri",
    "curation_rationale",
    "disposition",
)

# Reviewed unresolved source uses, not a global disposition of Sugar (#1180).
# CSV ordinals 1200/6810 are evidence locators, not stable record identities.
_UNRESOLVED_BERGEY_SUGAR = {
    "773071": "https://doi.org/10.1002/9781118960608.gbm00239",
    "776427": "https://doi.org/10.1002/9781118960608.gbm00020",
}
_UNRESOLVED_SUGAR_DESCRIPTION = (
    "Unresolved MicrobeDecoder Bergey substrate material reported as sugar; "
    "source substrate explanation is literal NA. Historical NCIT:C71939 "
    "grounding is withdrawn for this record/field only (#1180); "
    "no exact chemical identity or sucrose identity is asserted."
)

# Predicate map from metabolism-source group_label to the InforES knowledge
# source used on every emitted edge. Kept as a dict so tests can override
# without patching the constants module.
_GROUP_TO_KS: Dict[str, str] = {
    "bergey": BERGEY_KNOWLEDGE_SOURCE,
    "vpi": VPI_KNOWLEDGE_SOURCE,
    "literature": LITERATURE_KNOWLEDGE_SOURCE,
    "faprotax": FAPROTAX_KNOWLEDGE_SOURCE,
}
_PROCESS_SOURCE_COLUMNS = {
    f"{group['group_label']}:type_of_metabolism": group["columns"]["type_of_metabolism"] for group in METABOLISM_GROUPS
}


class MicrobeDecoderTransform(Transform):
    """Transform the MicrobeDecoder wide CSV into KGX nodes and edges."""

    TSV_QUOTING = csv.QUOTE_NONE

    #: Reads this transform's output; see Transform.TRANSFORM_INPUTS (#845).
    TRANSFORM_INPUTS = ("lpsn", "gold", "gtdb", "ontologies")

    DATA_INPUTS = (
        "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
        "mappings/canonical/microbedecoder_process_mappings.tsv",
        "mappings/canonical/microbedecoder_phenotype_mappings.tsv",
        "mappings/canonical/microbedecoder_process_scope_definitions.tsv",
        "mappings/canonical/microbedecoder_crosswalk_quarantine.json",
        "mappings/canonical/microbedecoder_crosswalk_quarantine.tsv",
        "mappings/canonical/microbedecoder_crosswalk_quarantine_evidence.json.gz",
    )
    REQUIRED_CONSUMED_INPUTS = (
        "process_mappings",
        "process_authority",
        "process_go_authority",
        "phenotype_mappings",
        "process_scope_definitions",
        "chemical_authority",
        "crosswalk_policy",
        "crosswalk_decisions",
        "crosswalk_evidence",
        "crosswalk_raw",
    )
    REQUIRED_AUDIT_FILES = (QUARANTINE_REPORT_FILENAME,)

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        chemical_loader: Any = None,
        process_mappings: Optional[Union[str, Path]] = None,
        phenotype_mappings: Optional[Union[str, Path]] = None,
        process_scopes: Optional[Union[str, Path]] = None,
        crosswalk_quarantine_policy: Optional[Union[str, Path]] = None,
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
        process_mappings:
            Optional exact source-scoped process curation table. Defaults to
            the versioned canonical table; every actual read is fingerprinted.
        phenotype_mappings:
            Optional exact source field/literal attribute-type table. Original
            observations stay intact; reviewed types use a node slot, not an
            organism phenotype assertion. Every use retains a curation report.
        process_scopes:
            Reviewed source-local process meanings, without an external ontology
            identity assertion. Exact field/literal rules are fingerprinted.
        crosswalk_quarantine_policy:
            Exact-snapshot reviewed crosswalk disposition policy. The default
            is mandatory in production; tests may inject a separately pinned
            fixture policy. No missing/changed policy silently disables review.

        """
        super().__init__(MICROBEDECODER, input_dir, output_dir)
        self.node_header = list(
            dict.fromkeys(
                [
                    *self.node_header,
                    HAS_ATTRIBUTE_TYPE_COLUMN,
                    ATTRIBUTE_TYPE_SOURCE_COLUMN,
                    ATTRIBUTE_TYPE_EVIDENCE_COLUMN,
                    ATTRIBUTE_TYPE_RATIONALE_COLUMN,
                ]
            )
        )
        self.edge_header = list(
            dict.fromkeys(
                [
                    *self.edge_header,
                    ORIGINAL_OBJECT_COLUMN,
                    DESCRIPTION_COLUMN,
                    PUBLICATIONS_COLUMN,
                    SOURCE_COLUMN,
                    SOURCE_RECORD_COLUMN,
                    SOURCE_CITATION_COLUMN,
                    SOURCE_CITATION_BYTES_COLUMN,
                    VALUE_COLUMN,
                    VALUE_ENCODING_COLUMN,
                ]
            )
        )
        self.knowledge_source = MICROBEDECODER_KNOWLEDGE_SOURCE
        self.chemical_loader = chemical_loader
        self.process_mappings = Path(process_mappings) if process_mappings is not None else DEFAULT_PROCESS_MAPPINGS
        self._process_curation: Optional[ProcessCuration] = None
        self.phenotype_mappings = (
            Path(phenotype_mappings) if phenotype_mappings is not None else DEFAULT_PHENOTYPE_MAPPINGS
        )
        self._phenotype_curation: Optional[PhenotypeCuration] = None
        self.process_scopes = Path(process_scopes) if process_scopes is not None else DEFAULT_PROCESS_SCOPE_DEFINITIONS
        self._process_scopes: Optional[ProcessScopeCuration] = None
        self._record_chemical_curation: Optional[RecordChemicalCuration] = None
        self._phenotype_report_writer = None
        self.crosswalk_quarantine_policy = (
            Path(crosswalk_quarantine_policy)
            if crosswalk_quarantine_policy is not None
            else DEFAULT_CROSSWALK_QUARANTINE_POLICY
        )
        self._crosswalk_quarantine: Optional[CrosswalkQuarantine] = None
        self._quarantine_report_writer = None
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
            "crosswalk_quarantined": 0,
            "lpsn_repointed": 0,
            "metabolism_edges": 0,
            "bacdive_snapshot_edges": 0,
            "reviewed_phenotype_reports": 0,
            "unmatched_labels": 0,
            "lpsn_stubbed": 0,
            "lpsn_stub_unnamed": 0,
        }
        self._accepted_lpsn: Optional[Dict[str, str]] = None
        self._lpsn_supplied: Optional[set] = None
        self._stubbed_lpsn: set = set()
        self._gold_folds: Dict[str, str] = {}
        self._assembly_declared = set()
        self._assembly_aliases = {}
        self._assembly_references = {}
        self._source_record = ""

    def _reset_run_state(self) -> None:
        """Reset producer caches so repeated runs never inherit old output state."""
        self._seen_nodes.clear()
        self._unmapped.clear()
        self._stats = dict.fromkeys(self._stats, 0)
        self._accepted_lpsn = None
        self._lpsn_supplied = None
        self._stubbed_lpsn.clear()
        self._assembly_references.clear()
        self._source_record = ""
        self._process_curation = None
        self._phenotype_curation = None
        self._process_scopes = None
        self._record_chemical_curation = None
        self._phenotype_report_writer = None
        self._crosswalk_quarantine = None
        self._quarantine_report_writer = None

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

        # Validate the upstream report before opening outputs or loading heavy
        # chemical resources. A bad alias table must not redirect identities.
        self._gold_folds = self._load_gold_organism_folds()
        assembly_nodes = self.output_dir.parent / "gtdb" / "nodes.tsv"
        if not assembly_nodes.is_file():
            raise FileNotFoundError(f"{assembly_nodes} is missing; run the gtdb transform first (#1064).")
        self._assembly_declared, self._assembly_aliases = load_assembly_aliases(assembly_nodes)
        self._reset_run_state()
        self.begin_consumed_inputs()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Parse and emit from one read-only raw snapshot. This prevents a
        # changed raw path from being stamped with an earlier source digest.
        with self.consume_input("crosswalk_raw", csv_path) as raw_snapshot:
            raw_snapshot.reconfigure(errors="surrogateescape")
            with self.consume_input("crosswalk_policy", self.crosswalk_quarantine_policy) as policy_input:
                policy = QuarantinePolicy.load(policy_input)
            with (
                self.consume_input(
                    "crosswalk_decisions", self.crosswalk_quarantine_policy.parent / policy.decisions_file
                ) as decisions,
                self.consume_input(
                    "crosswalk_evidence", self.crosswalk_quarantine_policy.parent / policy.evidence_file
                ) as evidence,
            ):
                self._crosswalk_quarantine = CrosswalkQuarantine(policy, decisions, evidence)
            source_fingerprint = self.consumed_input_snapshots["crosswalk_raw"]["sha256"]
            self._crosswalk_quarantine.preflight(raw_snapshot, source_fingerprint, self._accepted_lpsn_records())
            self._run_snapshot(raw_snapshot, source_fingerprint)
            self.verify_consumed_inputs()
        self._log_summary()

    def _run_snapshot(self, raw_snapshot, source_fingerprint: str) -> None:
        """Emit only after the complete selected source has passed crosswalk preflight."""
        # Resolve only reviewed column/literal pairs, and require their actual
        # ontology-owned declarations before writing any graph output (#650).
        # Consumption guards bind both inputs through finalization/admission.
        with (
            self.consume_input("process_mappings", self.process_mappings) as mappings,
            self.consume_input(
                "process_authority", self.output_dir.parent / "ontologies" / "metpo_nodes.tsv"
            ) as authority,
            self.consume_input(
                "process_go_authority", self.output_dir.parent / "ontologies" / "go_nodes.tsv"
            ) as go_authority,
            self.consume_input("phenotype_mappings", self.phenotype_mappings) as phenotype_mappings,
            self.consume_input("process_scope_definitions", self.process_scopes) as process_scopes,
            self.consume_input(
                "chemical_authority", self.output_dir.parent / "ontologies" / "chebi_nodes.tsv"
            ) as chemical_authority,
        ):
            self._process_curation = ProcessCuration(mappings, authority, go_authority)
            authority.seek(0)
            self._phenotype_curation = PhenotypeCuration(phenotype_mappings, authority)
            self._process_scopes = ProcessScopeCuration(process_scopes)
            process_keys = {column: key for key, column in _PROCESS_SOURCE_COLUMNS.items()}
            for scope in self._process_scopes.rules:
                if self._process_curation.resolve(process_keys[scope.source_column], scope.source_literal) or (
                    self._phenotype_curation.resolve(scope.source_column, scope.source_literal)
                ):
                    raise ValueError(f"Conflicting process scope disposition for {scope.source_literal!r}")
            self._record_chemical_curation = RecordChemicalCuration(chemical_authority)
        # Lazy loader: constructor stays inert with respect to expensive
        # chemical-mapping resources. Matches the round-34 lpsn pattern
        # (get_ontology_adapter is deferred to run()).
        if self.chemical_loader is None:
            from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

            self.chemical_loader = ChemicalMappingLoader()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        with (
            atomic_write(self.output_node_file, "w", newline="", encoding="utf-8") as node_fh,
            atomic_write(self.output_edge_file, "w", newline="", encoding="utf-8") as edge_fh,
            atomic_write(
                self.output_dir / _PHENOTYPE_REPORT_FILENAME, "w", newline="", encoding="utf-8"
            ) as phenotype_fh,
            atomic_write(
                self.output_dir / QUARANTINE_REPORT_FILENAME, "w", newline="", encoding="utf-8"
            ) as quarantine_fh,
        ):
            # KGX reads TSV with QUOTE_NONE. Escape control characters in
            # literal values explicitly; CSV quotation is not a TSV escape.
            node_writer = tsv_writer(node_fh, quoting=csv.QUOTE_NONE, quotechar=None)
            edge_writer = tsv_writer(edge_fh, quoting=csv.QUOTE_NONE, quotechar=None)
            node_writer.writerow(self.node_header)
            edge_writer.writerow(self.edge_header)
            self._phenotype_report_writer = tsv_dict_writer(
                phenotype_fh,
                fieldnames=_PHENOTYPE_REPORT_FIELDS,
                quoting=csv.QUOTE_NONE,
                quotechar=None,
            )
            self._phenotype_report_writer.writeheader()
            self._quarantine_report_writer = tsv_dict_writer(
                quarantine_fh, fieldnames=QUARANTINE_REPORT_FIELDS, quoting=csv.QUOTE_NONE, quotechar=None
            )
            self._quarantine_report_writer.writeheader()

            # CSV strings retain operators, zeros and leading zeros. Record
            # ordinals count CSV records, not physical lines (quoted cells
            # can contain newlines). The digest anchors the original bytes,
            # including the upstream file's rare non-UTF8 label bytes.
            raw_snapshot.seek(0)
            for ordinal, row in enumerate(csv.DictReader(raw_snapshot), start=1):
                self._source_record = f"sha256:{source_fingerprint}#record={ordinal}"
                self._process_row(row, node_writer, edge_writer)
            self._crosswalk_quarantine.require_complete()
        self._phenotype_report_writer = None
        self._quarantine_report_writer = None
        self.record_producer_audit(QUARANTINE_REPORT_FILENAME)

        # Sorted dedup: keeps the output stable across runs and lets the
        # merged KG collapse duplicates cheaply.
        self._deduplicate_literal_tsv(self.output_node_file, ID_COLUMN)
        self._deduplicate_literal_tsv(self.output_edge_file, SUBJECT_COLUMN)
        # Curation queue: per-label placeholder tally sorted by frequency
        # descending. Matches the metatraits `unmapped_traits.tsv` pattern.
        self._write_unmapped_report()
        self._write_assembly_reference_report()

    @staticmethod
    def _deduplicate_literal_tsv(path: Path, sort_column: str) -> None:
        """Deduplicate complete source assertions without numeric/NA coercion."""
        frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, quoting=csv.QUOTE_NONE)
        frame.drop_duplicates(inplace=True)
        columns = [sort_column, *[column for column in frame.columns if column != sort_column]]
        frame.sort_values(columns, kind="stable", inplace=True)
        with atomic_write(path, "w", newline="", encoding="utf-8") as output:
            frame.to_csv(output, sep="\t", index=False, quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n")

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

        Does not emit a node for an ``lpsn:<LPSN_ID>`` subject the ``lpsn``
        transform supplies: those are that transform's product, and stubbing
        them would create a shallow duplicate the merge has to dedup, against
        the add-transform skill's rule on cross-referenced entities.

        It *does* emit one for a subject ``lpsn`` cannot supply. The rule
        assumes the entity exists in KG-Microbe, and for **5,763** of these it
        does not: ``lpsn_gss.csv`` carries only names validly published under the
        **bacteriological** code (every record is ``VP;`` or ``VL;``), while
        MicrobeDecoder's crosswalk also spans the **botanical** code —
        ``Species;`` (4,500) / ``Variety;`` (822) / ``Form;`` (437) /
        ``Subspecies;`` (4). All 5,763 are Cyanobacteriota, which are
        historically named under the ICN rather than the ICNP (#811).

        Note 5,763, not the 5,242 quoted on #811: that figure counted only the
        ids appearing as ``capable_of`` subjects. This gate covers every
        ``LPSN_ID`` the crosswalk references, which is the set that actually
        needs nodes.

        Without the stub they reached the merged graph as untyped
        ``biolink:NamedThing`` endpoints and produced 21,196 ``capable_of``
        domain violations. Dropping the edges instead would have deleted every
        cyanobacterium this source describes.
        """
        lpsn_id = row.get(LPSN_ID_COLUMN)
        if is_empty_cell(lpsn_id):
            return
        lpsn_id = str(lpsn_id).strip()
        # Anchor on the accepted name, not whatever the source snapshot recorded.
        # Everything this transform emits — crosswalk, metabolism, BacDive
        # snapshot — hangs off this one CURIE, so a synonym LPSN_ID drags the
        # whole row onto a deprecated record: 5,263 edges, 1.0% (#746). bacdive
        # got this treatment in #684; the resolver is shared so the two agree.
        accepted = self._accepted_lpsn_records()
        if lpsn_id in accepted:
            self._stats["lpsn_repointed"] += 1
            lpsn_id = accepted[lpsn_id]
        subject_curie = f"{LPSN_PREFIX}{lpsn_id}"
        self._stats["rows_processed"] += 1
        self._emit_lpsn_stub_if_unsupplied(subject_curie, row, node_writer)

        self._emit_crosswalk_edges(subject_curie, row, node_writer, edge_writer)
        self._emit_metabolism_edges(subject_curie, row, node_writer, edge_writer)
        self._emit_bacdive_snapshot_edges(subject_curie, row, node_writer, edge_writer)

    # ------------------------------------------------------------------
    # Crosswalk edges (novel identity mapping MicrobeDecoder pre-joins)
    # ------------------------------------------------------------------
    def _resolve_assembly_reference(self, curie: str, node_writer: "csv._writer") -> str:
        """Use exact GTDB aliases; declare unmatched versioned source accessions honestly."""
        if not ASSEMBLY_ACCESSION.fullmatch(curie):
            # Older releases also carry unversioned references. Keep their
            # original representation; never append an assumed version or
            # treat them as a uniquely resolved physical assembly.
            self._assembly_references[curie] = (curie, "unresolved_unversioned_reference")
            return curie
        canonical = self._assembly_aliases.get(curie, curie)
        status = "gtdb_same_as" if canonical != curie else "gtdb_declared"
        if canonical not in self._assembly_declared:
            # The accession is a source assertion, not an independently
            # validated NCBI record or an inferred GenBank/RefSeq identity.
            status = "source_reported_not_in_gtdb"
            if curie not in self._seen_nodes:
                node = self._make_node_row(curie, GENOME_CATEGORY, curie.removeprefix(NCBI_ASSEMBLY_PREFIX))
                node[self.node_header.index(DESCRIPTION_COLUMN)] = (
                    "Versioned assembly accession reported by MicrobeDecoder; "
                    "not declared in the current GTDB release; no cross-release identity inferred."
                )
                node_writer.writerow(node)
                self._seen_nodes.add(curie)
        self._assembly_references[curie] = (canonical, status)
        return canonical

    def _write_assembly_reference_report(self) -> None:
        """Keep the exact source accession and GTDB resolution disposition for every reference."""
        path = self.output_dir / "assembly_references.tsv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = tsv_writer(handle)
            writer.writerow(["original_id", "canonical_id", "disposition", "evidence_source"])
            for original, (canonical, status) in sorted(self._assembly_references.items()):
                evidence = "gtdb/nodes.tsv:same_as" if status == "gtdb_same_as" else self.knowledge_source
                writer.writerow([original, canonical, status, evidence])

    def _load_gold_organism_folds(self) -> Dict[str, str]:
        """
        Load only GOLD's explicit organism folds; never infer a missing mapping.

        The sibling ``gold/organism_folds.tsv`` records the exact ID replacement
        already applied by GOLD, including retired-taxid resolution. An absent
        report requires a GOLD rerun; a valid empty report means no IDs folded.
        """
        path = self.output_dir.parent / "gold" / GOLD_ORGANISM_FOLD_FILE
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} is missing; run `poetry run kg transform -s gold` first "
                "to resolve folded GOLD organism references (#1051)."
            )
        folds: Dict[str, str] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            if next(reader, None) != list(GOLD_ORGANISM_FOLD_HEADER):
                raise ValueError(f"{path}: expected header {GOLD_ORGANISM_FOLD_HEADER}")
            for line, row in enumerate(reader, start=2):
                if len(row) != 2:
                    raise ValueError(f"{path}:{line}: expected an original and canonical ID")
                original, canonical = row
                if (
                    not original.startswith(GOLD_PREFIX)
                    or len(original) == len(GOLD_PREFIX)
                    or not canonical.startswith(NCBITAXON_PREFIX)
                    or not canonical[len(NCBITAXON_PREFIX) :].isdigit()
                ):
                    raise ValueError(f"{path}:{line}: invalid GOLD organism fold {row!r}")
                if original in folds and folds[original] != canonical:
                    raise ValueError(f"{path}:{line}: conflicting folds for {original}")
                folds[original] = canonical
        return folds

    def _accepted_lpsn_records(self) -> Dict[str, str]:
        """
        Return the LPSN synonym-to-accepted mapping, loading it once.

        The GSS CSV is account-gated and not shipped, so absence is expected and
        non-fatal — exactly as in the bacdive transform. Without it the mapping
        is empty and every row anchors on the ID the source gave, which is the
        behaviour before #746.

        :return: ``record_no`` to accepted ``record_no``.
        """
        if self._accepted_lpsn is not None:
            return self._accepted_lpsn
        gss_csv = Path(self.input_base_dir) / "lpsn_gss.csv"
        if not gss_csv.is_file():
            print(
                f"[microbedecoder] {gss_csv} not found — LPSN IDs are used as given. "
                "Synonym IDs will anchor edges on deprecated records (#746)."
            )
            self._accepted_lpsn = {}
            return self._accepted_lpsn
        with gss_csv.open(newline="") as handle:
            gss_rows = {
                (r.get("record_no") or "").strip(): r
                for r in csv.DictReader(handle)
                if (r.get("record_no") or "").strip()
            }
        self._accepted_lpsn = resolve_accepted_records(gss_rows)
        print(
            f"[microbedecoder] LPSN: {len(self._accepted_lpsn):,} synonym records will be "
            "re-pointed to their accepted name"
        )
        return self._accepted_lpsn

    def _lpsn_supplied_ids(self) -> set:
        """
        CURIEs the ``lpsn`` transform emits, loaded once.

        Absence is non-fatal and deliberate: ``lpsn`` may not have run, and the
        GSS CSV it needs is account-gated. An empty set means every subject is
        treated as supplied, i.e. no stubs — the behaviour before #811, which
        under-reports rather than inventing nodes.

        :return: Set of ``lpsn:<record_no>`` CURIEs, empty when unavailable.
        """
        if self._lpsn_supplied is not None:
            return self._lpsn_supplied
        supplied: set = set()
        nodes_file = self.output_dir.parent / "lpsn" / "nodes.tsv"
        if nodes_file.is_file():
            with nodes_file.open(encoding="utf-8") as handle:
                handle.readline()
                for line in handle:
                    curie = line.split("\t", 1)[0]
                    if curie.startswith(LPSN_PREFIX):
                        supplied.add(curie)
        else:
            logger.warning(
                "%s not found — emitting no LPSN stubs; ids absent from the "
                "lpsn transform will stay untyped in the merged graph (#811)",
                nodes_file,
            )
        self._lpsn_supplied = supplied
        return supplied

    def _emit_lpsn_stub_if_unsupplied(
        self,
        subject_curie: str,
        row: Dict[str, str],
        node_writer: "csv._writer",
    ) -> None:
        """
        Emit a typed node for an LPSN subject the ``lpsn`` transform cannot supply.

        Named from the crosswalk's own genus/species/subspecies columns, which
        are populated for all 5,242 affected records — so these are real labelled
        taxa, not bare placeholders.

        :param subject_curie: The ``lpsn:<record_no>`` subject.
        :param row: The crosswalk row, for naming.
        :param node_writer: Open nodes.tsv writer.
        """
        supplied = self._lpsn_supplied_ids()
        if not supplied or subject_curie in supplied or subject_curie in self._stubbed_lpsn:
            return

        parts = [
            str(row.get(col, "") or "").strip()
            for col in (LPSN_GENUS_COLUMN, LPSN_SPECIES_COLUMN, LPSN_SUBSPECIES_COLUMN)
        ]
        # "NA" is the crosswalk's empty marker, not a name component.
        name = " ".join(p for p in parts if p and p.upper() != "NA")
        if not name:
            self._stats["lpsn_stub_unnamed"] += 1
            return

        self._stubbed_lpsn.add(subject_curie)
        self._stats["lpsn_stubbed"] += 1
        node_writer.writerow(self._make_node_row(subject_curie, NCBI_CATEGORY, name))

    def _emit_crosswalk_edges(
        self,
        subject: str,
        row: Dict[str, Any],
        node_writer: "csv._writer",
        edge_writer: "csv._writer",
    ) -> None:
        """
        Emit one ``biolink:close_match`` edge per crosswalk local-ID token.

        Multi-value cells are split via :func:`split_multivalue_comma_only`
        before CURIE construction. Without a split the source's
        ``IMG_Genome_ID`` column — which packs multiple genome IDs per row
        separated by commas — landed as a single malformed CURIE like
        ``IMG:2547132264,2784746776`` on ~2.6 K edges in the first live
        merge (issue #655).

        Comma-only rather than the metabolism emitter's comma-or-semicolon
        split, because ``GTDB_ID`` uses ``;`` as an internal rank separator
        (``d__Bacteria;g__Bacillus;s__Bacillus subtilis``) — a semicolon
        split would shred a single GTDB CURIE into three orphan fragments.
        The other four crosswalk columns (NCBI, BacDive, GOLD) are
        single-value in practice; comma-only is safe there too.
        """
        for column, prefix, source_prefix in CROSSWALK_COLUMNS:
            raw = row.get(column)
            if is_empty_cell(raw):
                continue
            for local_id in split_multivalue_comma_only(raw):
                object_curie = crosswalk_curie(local_id, prefix, source_prefix)
                original_object = object_curie
                # Match the original column/token/target before GOLD folding
                # or assembly resolution can redirect it or emit a stub.
                decision = (
                    self._crosswalk_quarantine.match(
                        self._source_record, row, subject, column, local_id, original_object
                    )
                    if self._crosswalk_quarantine is not None
                    else None
                )
                if decision is not None:
                    if self._quarantine_report_writer is None:
                        raise ValueError("Crosswalk quarantine audit writer is unavailable")
                    claim = self._make_edge_row(
                        subject, CLOSE_MATCH_PREDICATE, original_object, CLOSE_MATCH_RELATION, self.knowledge_source
                    )
                    original_claim = {
                        key: value if value is not None else ""
                        for key, value in zip(self.edge_header, claim, strict=True)
                    }
                    self._quarantine_report_writer.writerow(
                        self._crosswalk_quarantine.audit_row(decision, row, original_claim)
                    )
                    self._stats["crosswalk_quarantined"] += 1
                    continue
                if object_curie.startswith(NCBI_ASSEMBLY_PREFIX):
                    object_curie = self._resolve_assembly_reference(object_curie, node_writer)
                if prefix == GOLD_PREFIX:
                    object_curie = self._gold_folds.get(object_curie, object_curie)
                if column == BACDIVE_CROSSWALK_COLUMN:
                    # Strain -> name subsumption, matching what the bacdive
                    # transform asserts for the same pair. See the note on
                    # BACDIVE_CROSSWALK_COLUMN: close_match contradicted it.
                    edge_writer.writerow(
                        self._make_edge_row(
                            object_curie,
                            SUBCLASS_PREDICATE,
                            subject,
                            RDFS_SUBCLASS_OF,
                            self.knowledge_source,
                        )
                    )
                else:
                    edge_writer.writerow(
                        self._make_edge_row(
                            subject,
                            CLOSE_MATCH_PREDICATE,
                            object_curie,
                            CLOSE_MATCH_RELATION,
                            self.knowledge_source,
                            original_object=original_object if original_object != object_curie else None,
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
        reviewed_sugar = self._reviewed_sugar_record(row)
        # Review known source identity before splitting/skipping empty fields;
        # missing or changed evidence must not silently bypass this admission.
        reviewed_substrate = (
            self._record_chemical_curation.resolve(
                row, "bergey:substrates", row.get("Bergey_Substrates_for_end_products")
            )
            if self._record_chemical_curation
            else None
        )
        for group_label, fields in iter_metabolism_columns(row):
            provenance = _GROUP_TO_KS[group_label]
            citation_curie = format_citation(fields.get("citation"))
            citation_text = fields.get("citation")
            source_columns = next(
                group["columns"] for group in METABOLISM_GROUPS if group["group_label"] == group_label
            )

            # Normalize reviewed source-specific process assertions to METPO/GO;
            # keep local pathway objects for labels lacking equivalent evidence.
            type_of_metabolism = fields.get("type_of_metabolism")
            if not is_empty_cell(type_of_metabolism):
                for label in split_multivalue(type_of_metabolism):
                    column = source_columns["type_of_metabolism"]
                    mapping = self._phenotype_curation.resolve(column, label) if self._phenotype_curation else None
                    annotation = is_reported_metabolism_annotation(column, label) or mapping is not None
                    obj = (
                        self._resolve_source_attribute_curie(label, column, node_writer)
                        if annotation
                        else self._resolve_metabolism_curie(
                            label, node_writer, source_column=f"{group_label}:type_of_metabolism"
                        )
                    )
                    edge_writer.writerow(
                        self._make_edge_row(
                            subject,
                            HAS_ATTRIBUTE_PREDICATE if annotation else CAPABLE_OF_PREDICATE,
                            obj,
                            HAS_ATTRIBUTE_RELATION if annotation else CAPABLE_OF,
                            provenance,
                            publications=citation_curie,
                            source_citation=citation_text,
                            source_column=column,
                            value=label,
                            original_object=(
                                f"{PATHWAY_PREFIX}{slugify_label(label)}"
                                if not annotation
                                and self._process_scopes
                                and self._process_scopes.resolve(column, label)
                                else None
                            ),
                            # FAPROTAX extrapolates curated taxon-function rules;
                            # its per-organism assignments are predictions (#1209).
                            knowledge_level=PREDICTION if group_label == "faprotax" else KNOWLEDGE_ASSERTION,
                            agent_type=COMPUTATIONAL_MODEL if group_label == "faprotax" else MANUAL_AGENT,
                        )
                    )
                    self._stats["metabolism_edges"] += 1
                    if mapping is not None:
                        self._write_phenotype_normalization(
                            subject,
                            column,
                            label,
                            mapping,
                            provenance,
                            PREDICTION if group_label == "faprotax" else KNOWLEDGE_ASSERTION,
                            COMPUTATIONAL_MODEL if group_label == "faprotax" else MANUAL_AGENT,
                        )

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
                            source_citation=citation_text,
                            source_column=source_columns[role],
                            value=label,
                        )
                    )
                    self._stats["metabolism_edges"] += 1

            # Substrate rows → biolink:consumes + relation trophically_interacts_with.
            # Uses NCBI_TO_SUBSTRATE_EDGE (the standard constant every
            # organism→substrate emitter routes through, incl. madin_etal)
            # so merged-KG queries stay consistent.
            for label in split_multivalue(fields.get("substrates")):
                if group_label == "bergey" and label == "Not reported":
                    # This is missing-report metadata, not a consumed chemical
                    # and not a negative utilization result (#650). Retain the
                    # original observation and citation as a source attribute.
                    column = source_columns["substrates"]
                    obj = self._resolve_source_attribute_curie(label, column, node_writer)
                    edge_writer.writerow(
                        self._make_edge_row(
                            subject,
                            HAS_ATTRIBUTE_PREDICATE,
                            obj,
                            HAS_ATTRIBUTE_RELATION,
                            provenance,
                            publications=citation_curie,
                            source_citation=citation_text,
                            source_column=column,
                            value=label,
                        )
                    )
                    self._stats["metabolism_edges"] += 1
                    continue
                original_object = None
                if group_label == "bergey" and reviewed_substrate is not None:
                    obj = reviewed_substrate
                    original_object = f"{COMPOUND_PREFIX}{slugify_label(label)}"
                else:
                    obj = self._resolve_chemical_curie(label, node_writer, source_column=f"{group_label}:substrates")
                if group_label == "bergey" and reviewed_sugar:
                    original_object = obj
                    obj = self._resolve_reviewed_sugar(row, obj, node_writer)
                edge_writer.writerow(
                    self._make_edge_row(
                        subject,
                        NCBI_TO_SUBSTRATE_EDGE,
                        obj,
                        TROPHICALLY_INTERACTS_WITH,
                        provenance,
                        publications=citation_curie,
                        original_object=original_object,
                        source_citation=citation_text,
                        source_column=source_columns["substrates"],
                        value=label,
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
        Retain source observations, with reviewed attribute types on nodes only.

        Every edge carries ``primary_knowledge_source =
        infores:microbedecoder`` so the paper's exact snapshot stays
        distinguishable from the live bacdive transform's output at
        merge time.
        Units, incubation periods, isolation categories and undecoded source
        codes remain field values, not biological phenotype assertions.
        """
        for column in BACDIVE_SNAPSHOT_COLUMNS:
            raw = row.get(column)
            for label in split_snapshot_values(column, raw):
                obj = self._resolve_source_attribute_curie(label, column, node_writer)
                edge_writer.writerow(
                    self._make_edge_row(
                        subject,
                        HAS_ATTRIBUTE_PREDICATE,
                        obj,
                        HAS_ATTRIBUTE_RELATION,
                        self.knowledge_source,
                        description=column.replace("BacDive_", "").replace("_", " "),
                        source_column=column,
                        value=label,
                    )
                )
                self._stats["bacdive_snapshot_edges"] += 1
                mapping = self._phenotype_curation.resolve(column, label) if self._phenotype_curation else None
                if mapping is not None:
                    self._write_phenotype_normalization(
                        subject, column, label, mapping, self.knowledge_source, KNOWLEDGE_ASSERTION, MANUAL_AGENT
                    )

    def _write_phenotype_normalization(
        self,
        subject: str,
        column: str,
        label: str,
        mapping: PhenotypeMapping,
        provenance: str,
        knowledge_level: str,
        agent_type: str,
    ) -> None:
        """Report each source use without changing evidence tier or asserting a phenotype edge."""
        if self._phenotype_report_writer is None:
            raise RuntimeError("Phenotype normalization report is not open")
        self._phenotype_report_writer.writerow(
            {
                SUBJECT_COLUMN: subject,
                SOURCE_RECORD_COLUMN: self._source_record,
                SOURCE_COLUMN: column,
                VALUE_COLUMN: self._escape_literal(label),
                VALUE_ENCODING_COLUMN: "backslash",
                PRIMARY_KNOWLEDGE_SOURCE_COLUMN: provenance,
                KNOWLEDGE_LEVEL_COLUMN: knowledge_level,
                AGENT_TYPE_COLUMN: agent_type,
                "target_curie": mapping.target_curie,
                "target_label": mapping.target_label,
                "target_category": mapping.target_category,
                "evidence_uri": mapping.evidence_uri,
                "curation_rationale": mapping.curation_rationale,
                "disposition": "reviewed_literal_grounding_not_graph_assertion",
            }
        )
        self._stats["reviewed_phenotype_reports"] += 1

    # ------------------------------------------------------------------
    # CURIE resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _reviewed_sugar_record(source_row: Dict[str, Any]) -> bool:
        """Admit exact finite record/field evidence before any group or token filtering."""
        source_id = str(source_row.get(LPSN_ID_COLUMN, "")).strip()
        citation = _UNRESOLVED_BERGEY_SUGAR.get(source_id)
        if citation is None:
            return False
        if (
            source_row.get(LPSN_ID_COLUMN) != source_id
            or source_row.get("Bergey_Substrates_for_end_products") != "sugar"
            or source_row.get("Bergey_Text_for_substrates") != "NA"
            or source_row.get("Bergey_Article_link") != citation
        ):
            raise ValueError(f"Reviewed unresolved Bergey sugar evidence changed for LPSN_ID {source_id}")
        return True

    def _resolve_reviewed_sugar(
        self,
        source_row: Dict[str, Any],
        historical_target: str,
        node_writer: "csv._writer",
    ) -> str:
        """Preserve two ungrounded Bergey observations without sharing material identity."""
        if not self._reviewed_sugar_record(source_row) or historical_target != "NCIT:C71939":
            raise ValueError("Reviewed unresolved Bergey sugar mapping evidence changed")
        column = "Bergey_Substrates_for_end_products"
        # Full literal record content scopes the material without tying its ID
        # to file order. Repeated identical records share a local material, but
        # their existing CSV digest/ordinal assertion locators remain distinct.
        identity = json.dumps(
            [MICROBEDECODER, source_row, column, "sugar"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(identity.encode("utf-8", errors="surrogateescape")).hexdigest()
        curie = f"{COMPOUND_PREFIX}{MICROBEDECODER}_unresolved_{digest}"
        self._ensure_terminal_node(
            curie, CHEMICAL_CATEGORY, "sugar", node_writer, description=_UNRESOLVED_SUGAR_DESCRIPTION
        )
        self._stats["unmatched_labels"] += 1
        entry = self._unmapped.setdefault(
            (curie, CHEMICAL_CATEGORY),
            {"label": "sugar", "source_columns": {column}, "occurrences": 0},
        )
        entry["occurrences"] = int(entry["occurrences"]) + 1
        return curie

    def _resolve_chemical_curie(
        self,
        label: str,
        node_writer: "csv._writer",
        source_column: str,
    ) -> str:
        """
        Resolve an end-product / substrate label to a CHEBI CURIE or placeholder.

        Successful external ontology resolution → return the CURIE **without**
        emitting a node stub; its ontology owns the authoritative node. The
        unified loader also resolves local compound/ingredient identifiers:
        these require a named declaration here because no ontology supplies
        them (#1073). Preserve their mapped identity and category; do not infer
        an external chemical grounding from their label.
        Miss → mint a ``kgmicrobe.compound:<slug>`` placeholder and emit
        the terminal stub (nothing else will). ``source_column`` is
        recorded in the unmapped-labels report so curators know which
        source axis to prioritise.
        """
        curie: Optional[str] = None
        if self.chemical_loader is not None:
            curie = self.chemical_loader.find_chebi_by_name(label, fuzzy_stereochemistry=True)
        if curie:
            if curie.startswith((COMPOUND_PREFIX, INGREDIENT_PREFIX)):
                name = self.chemical_loader.get_canonical_name(curie) or label
                category = self.chemical_loader.get_category(curie) or SMALL_MOLECULE_CATEGORY
                self._ensure_terminal_node(curie, category, name, node_writer)
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

        Only exact reviewed source-column/literal pairs resolve to validated
        ontology-owned process classes. Other roles, case variants, negative
        assertions and narrower processes keep the existing local fallback.
        The asserting edge retains its source record, literal, citation and
        evidence tier; normalizing its object is not new experimental evidence.
        """
        if self._process_curation is not None:
            mapping = self._process_curation.resolve(source_column, label)
            if mapping is not None:
                return mapping.target_curie
        scope = (
            self._process_scopes.resolve(_PROCESS_SOURCE_COLUMNS.get(source_column, ""), label)
            if self._process_scopes
            else None
        )
        return self._mint_placeholder(
            label,
            node_writer,
            prefix=PATHWAY_PREFIX,
            category=METABOLISM_CATEGORY,
            source_column=source_column,
            process_scope=scope,
        )

    def _resolve_source_attribute_curie(
        self,
        label: str,
        source_column: str,
        node_writer: "csv._writer",
    ) -> str:
        """
        Preserve a reported source field and exact token, without interpreting codes.

        A source value of zero is not evidence for a named negative phenotype
        until its coding scheme is mapped. Column-scoped IDs keep motility,
        spores, temperature and inequalities distinct in the graph itself.
        The generic Attribute type also covers non-phenotypic snapshot fields
        such as isolation categories, incubation periods and salt units.
        """
        return self._mint_placeholder(
            label,
            node_writer,
            prefix=SOURCE_ATTRIBUTE_PREFIX,
            category=ATTRIBUTE_CATEGORY,
            source_column=source_column,
        )

    def _mint_placeholder(
        self,
        label: str,
        node_writer: "csv._writer",
        prefix: str,
        category: str,
        source_column: str,
        process_scope: Optional[ProcessScope] = None,
    ) -> str:
        """
        Return a stable ``<prefix><slug>`` CURIE and emit the terminal stub.

        Placeholder CURIEs land in the caller-supplied ``kgmicrobe.*``
        prefix (``pathway``, ``compound``, or ``source_attribute`` — each already
        registered as a section of ``custom_curies.yaml``). The stub node
        carries the raw source label so the merged KG surfaces something
        human-readable even before the label gets a proper METPO / CHEBI
        mapping. ``source_column`` is tallied into ``self._unmapped`` so
        the end-of-run ``unmapped_labels.tsv`` report knows which source
        column(s) contributed this placeholder.
        """
        curie = f"{prefix}{slugify_label(label)}"
        name = label
        description = None
        if process_scope is not None:
            curie = process_scope.curie
            description = process_scope.description
        attribute_mapping = None
        if prefix == SOURCE_ATTRIBUTE_PREFIX:
            identity = json.dumps([MICROBEDECODER, source_column, label], ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(identity.encode("utf-8", errors="surrogateescape")).hexdigest()
            curie = f"{prefix}{MICROBEDECODER}_{slugify_label(source_column)}_{digest}"
            dimension = source_column.removeprefix("BacDive_").replace("_", " ")
            name = f"reported {dimension}: {label} (source value)"
            description = (
                f"Reported MicrobeDecoder {source_column} field value; not a decoded phenotype "
                "or a claim that every member of the taxon has a trait. "
                "Source record, field and literal token are retained on the asserting edge."
            )
            attribute_mapping = (
                self._phenotype_curation.resolve(source_column, label) if self._phenotype_curation else None
            )
            if attribute_mapping is not None:
                description = (
                    f"Reported MicrobeDecoder {source_column} field value. "
                    "has_attribute_type is KG-Microbe's reviewed classification of this exact source value, "
                    "not an independently observed phenotype or a claim that every member of the taxon has a trait. "
                    "Source record, field, literal token and evidence tier remain on the original asserting edge."
                )
        self._ensure_terminal_node(
            curie, category, name, node_writer, description=description, attribute_mapping=attribute_mapping
        )
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

        - ``placeholder_curie`` — the ``kgmicrobe.{pathway,compound,source_attribute}:<slug>``
          CURIE this run minted for the label
        - ``category`` — the placeholder's biolink category
        - ``label`` — the raw source label
        - ``source_columns`` — pipe-delimited set of source columns this
          label appeared under (``bergey:type_of_metabolism`` /
          ``vpi:major_end_products`` / ``BacDive_Oxygen_tolerance`` / …)
        - ``occurrences`` — how many edges this placeholder anchors this run

        An empty report is still written so a later run with no placeholders
        cannot inherit a stale curation queue from an earlier run.
        """
        target = self.output_dir / _UNMAPPED_REPORT_FILENAME
        rows = [
            {
                "placeholder_curie": curie,
                "category": category,
                "label": self._escape_literal(entry["label"]),
                "source_columns": "|".join(sorted(entry["source_columns"])),  # type: ignore[arg-type]
                "occurrences": entry["occurrences"],
            }
            for (curie, category), entry in self._unmapped.items()
        ]
        # Sort by count desc, then CURIE asc for stable output.
        rows.sort(key=lambda r: (-int(r["occurrences"]), r["placeholder_curie"]))
        with open(target, "w", newline="") as fh:
            writer = tsv_dict_writer(
                fh,
                fieldnames=["placeholder_curie", "category", "label", "source_columns", "occurrences"],
            )
            writer.writeheader()
            writer.writerows(rows)

    def _ensure_terminal_node(
        self,
        curie: str,
        category: str,
        name: str,
        node_writer: "csv._writer",
        description: Optional[str] = None,
        attribute_mapping: Optional[PhenotypeMapping] = None,
    ) -> None:
        """
        Emit a placeholder terminal node once per run (dedup via _seen_nodes).

        Called for locally owned placeholder or mapped compound/ingredient
        CURIEs — never for an external cross-reference target (NCBITaxon, GTDB, CHEBI,
        bacdive, GOLD, IMG) whose authoritative node is provided by
        another transform. See the add-transform skill's Phase 6
        "anti-patterns" for the reasoning.
        """
        if curie in self._seen_nodes:
            return
        self._seen_nodes.add(curie)
        node_writer.writerow(
            self._make_node_row(curie, category, name, description=description, attribute_mapping=attribute_mapping)
        )

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------
    def _make_node_row(
        self,
        node_id: str,
        category: str,
        name: str,
        description: Optional[str] = None,
        attribute_mapping: Optional[PhenotypeMapping] = None,
    ) -> List:
        """Build a node row in canonical Transform.node_header order."""
        row = [None] * len(self.node_header)
        row[self.node_header.index(ID_COLUMN)] = node_id
        row[self.node_header.index(CATEGORY_COLUMN)] = category
        row[self.node_header.index(NAME_COLUMN)] = self._escape_literal(name)
        row[self.node_header.index(DESCRIPTION_COLUMN)] = self._escape_literal(description)
        row[self.node_header.index(PROVIDED_BY_COLUMN)] = self.knowledge_source
        if attribute_mapping is not None:
            if category != ATTRIBUTE_CATEGORY or not node_id.startswith(SOURCE_ATTRIBUTE_PREFIX):
                raise ValueError("Reviewed attribute types belong only on source Attribute nodes")
            row[self.node_header.index(HAS_ATTRIBUTE_TYPE_COLUMN)] = attribute_mapping.target_curie
            row[self.node_header.index(ATTRIBUTE_TYPE_SOURCE_COLUMN)] = ATTRIBUTE_TYPE_CURATION_SOURCE
            row[self.node_header.index(ATTRIBUTE_TYPE_EVIDENCE_COLUMN)] = attribute_mapping.evidence_uri
            row[self.node_header.index(ATTRIBUTE_TYPE_RATIONALE_COLUMN)] = self._escape_literal(
                attribute_mapping.curation_rationale
            )
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
        original_object: Optional[str] = None,
        source_column: Optional[str] = None,
        value: Optional[str] = None,
        source_citation: Optional[str] = None,
        *,
        knowledge_level: str = KNOWLEDGE_ASSERTION,
        agent_type: str = MANUAL_AGENT,
    ) -> List:
        """
        Build an edge row in canonical Transform.edge_header order.

        Context is part of assertion identity, not merely a curation report.
        ``value`` uses reversible backslash escaping for TSV control characters
        and literal backslashes, explicitly declared by ``value_encoding``.
        Numeric operators and source codes remain unchanged.
        """
        row = [None] * len(self.edge_header)
        row[self.edge_header.index(SUBJECT_COLUMN)] = subject
        row[self.edge_header.index(PREDICATE_COLUMN)] = predicate
        row[self.edge_header.index(OBJECT_COLUMN)] = obj
        row[self.edge_header.index(RELATION_COLUMN)] = relation
        row[self.edge_header.index(PRIMARY_KNOWLEDGE_SOURCE_COLUMN)] = primary_knowledge_source
        row[self.edge_header.index(KNOWLEDGE_LEVEL_COLUMN)] = knowledge_level
        row[self.edge_header.index(AGENT_TYPE_COLUMN)] = agent_type
        row[self.edge_header.index(ORIGINAL_OBJECT_COLUMN)] = original_object
        row[self.edge_header.index(DESCRIPTION_COLUMN)] = self._escape_literal(description)
        row[self.edge_header.index(PUBLICATIONS_COLUMN)] = publications
        row[self.edge_header.index(SOURCE_COLUMN)] = source_column
        row[self.edge_header.index(SOURCE_RECORD_COLUMN)] = self._source_record
        row[self.edge_header.index(VALUE_COLUMN)] = self._escape_literal(value)
        row[self.edge_header.index(SOURCE_CITATION_COLUMN)] = self._escape_literal(source_citation)
        row[self.edge_header.index(SOURCE_CITATION_BYTES_COLUMN)] = (
            base64.b64encode(source_citation.encode("utf-8", errors="surrogateescape")).decode("ascii")
            if source_citation is not None
            else None
        )
        row[self.edge_header.index(VALUE_ENCODING_COLUMN)] = "backslash" if value is not None else None
        return row

    @staticmethod
    def _escape_literal(value: Optional[str]) -> Optional[str]:
        """Encode backslashes and TSV control characters without CSV quoting."""
        if value is None:
            return None
        # Display the upstream CSV's rare non-UTF8 citation bytes with the
        # historical replacement policy; source_citation_base64 keeps exact bytes.
        value = value.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
        return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")

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
            "bacdive_snapshot_edges=%d, unmatched_labels=%d, crosswalk_quarantined=%d",
            s["rows_processed"],
            s["crosswalk_edges"],
            s["metabolism_edges"],
            s["bacdive_snapshot_edges"],
            s["unmatched_labels"],
            s["crosswalk_quarantined"],
        )
        print(
            f"[microbedecoder] rows={s['rows_processed']}, "
            f"crosswalk_edges={s['crosswalk_edges']}, "
            f"metabolism_edges={s['metabolism_edges']}, "
            f"bacdive_snapshot_edges={s['bacdive_snapshot_edges']}, "
            f"reviewed_phenotype_reports={s['reviewed_phenotype_reports']}, "
            f"crosswalk_quarantined={s['crosswalk_quarantined']}, "
            f"unmatched_labels={s['unmatched_labels']}"
        )
