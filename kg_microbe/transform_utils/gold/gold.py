"""
Transform the GOLD (Genomes OnLine Database, JGI) pre-transformed KGX TSVs.

GOLD is unusual among our sources: it arrives **already in KGX shape**, so there
is nothing to parse. That makes a blind copy tempting and wrong. The modeling
review of the shipped payload (``docs/GOLD_TRANSFORM_REVIEW.md``) found nine
issues that a copy would carry straight into a merge — including 279,618
``MaterialSample`` nodes with no incident edge, and 4,220 ``subclass_of`` edges
that violate Biolink's domain/range.

So this is a *validating* passthrough. It conforms the schema to the KG-Microbe
standard, repairs what can be repaired mechanically, and reports the rest rather
than silently propagating it.

What it changes, and why each is safe:

* **Adds the standard columns.** Upstream nodes lack ``description``,
  ``synonym``, ``deprecated`` and ``same_as``; edges lack ``knowledge_level`` and
  ``agent_type``. Every other transform emits them, and they are how a consumer
  tells an assertion from a prediction. GOLD entries are curated submissions, so
  they are filled as ``knowledge_assertion`` / ``manual_agent``.
* **Drops the upstream edge ``id``.** The post-merge cleanup drops it anyway; not
  emitting it keeps the header standard.
* **Adds ``biolink:OntologyClass`` to ecosystem nodes.** ``subclass_of`` requires
  ``OntologyClass`` on both ends, and the GOLD ecosystem hierarchy is exactly
  that — a class hierarchy. Pipe-adding the category is the same device METPO
  nodes already use (``METPO:1001000|biolink:Procedure``). Without it those 4,220
  edges are a Biolink violation.

* **Applies the NCBITaxon trim.** KG-Microbe deliberately restricts NCBITaxon to
  microbes (``exclusion_branches.tsv`` removes Viruses, Viridiplantae, Metazoa
  and others). GOLD is a genome database covering all of life, so ingesting it
  unfiltered reintroduces 23,695 excluded taxa — phages, marine viruses,
  ``Picea glauca``, a starling — and the 76,034 organisms typed to them, undoing
  the trim the ontologies transform performs. Those, and the study nodes left
  holding nothing but them, are dropped.

* **Drops samples and studies.** KG-Microbe wants neither. ``MaterialSample``
  was 279,670 nodes with 242 incident edges, and ``Study`` was reachable only
  via ``IndividualOrganism -related_to-> Study``, a predicate asserting nothing
  usable (27.5% of the export). What the ingest is *for* — the organism to
  environment link, ``occurs_in`` — is kept. Measured: nodes 975,839 -> 637,286,
  edges 1,110,984 -> 823,250, and the pre-existing orphan warning falls from
  279,618 to 5. ``occurs_in`` ends at 287,706 rather than its upstream 286,725 —
  it *rises*, because organisms the taxid remap rescues keep their environment
  edges.
* **Remaps retired NCBI taxids** from ``merged.dmp`` in the taxonomy dump.
  GOLD's export carries taxa NCBI has since merged, and judging them by the
  retired id makes the trim drop them along with the organisms typed to them.
  Measured against the real payload: 611 taxa and 1,473 organisms retained that
  would otherwise have been discarded, with 561 nodes collapsing onto an
  existing id. Applied before the trim, since that is the point.

* **Resolves uninformative ecosystems upward, and drops what resolves to
  nothing.** 63.5% of ``occurs_in`` edges pointed at a node labelled
  "Unclassified", across 1,663 distinct such nodes — not a bucket you can
  filter, but 1,663 empty ids. The meaning is in the hierarchy: the single
  largest target, carrying 39,446 organisms, sits three "Unclassified" hops
  below ``Mammals: Human``. Each edge now names the nearest informative
  ancestor and keeps the original target in Biolink's ``original_object``, so
  the collapse is auditable and reversible. Edges resolving only to the
  hierarchy root — 58,340 of them, asserting an organism lives somewhere — are
  dropped. Measured: 229,366 ``occurs_in`` edges remain, **none** pointing at an
  "Unclassified", with ``Mammals: Human`` (39,472), ``Fecal``, ``Soil``,
  ``Plants``, ``Blood`` and ``Marine`` the largest targets.

What it deliberately does **not** change, because each needs a modelling decision
rather than a patch, and is reported instead:

* the 23,695 GOLD-only taxa absent from the NCBITaxon output;
* the 78 taxon ``name`` disagreements with the ontologies output.

* **Corrects the environment predicate and bridges the vocabulary.** Upstream
  ships ``occurs_in``, which Biolink defines as holding "between a **process**
  and a material entity or site" — the subject here is an organism, a material
  entity, so ``located_in`` is the right one. Neither constrains domain/range
  beyond ``named thing``, which is why KGXVal never flagged it. All 229,366
  environment edges are re-predicated.

  The ecosystem vocabulary is then bridged two ways: the GOLD ontology's
  curated ``skos:exactMatch`` links (531 nodes), then a label join against
  ontologies KG-Microbe already loads (537 more, overwhelmingly UBERON host
  anatomy — ``Rumen``, ``Blood``, ``Nasopharynx``, ``Urine``). Together
  **45.7%** of environment edges reach an ontology term in two hops, against
  26.9% from the curated mapping alone. Label normalisation was measured and
  contributes one edge, so the uncovered remainder is genuinely absent rather
  than spelled differently.

  The label join is restricted to site-shaped prefixes. Unrestricted it
  produced ``Alkaline -> PATO:0001430``, ``Benzene -> CHEBI:16716`` and
  ``Sperm -> CL:0000019``; an organism is not ``located_in`` a quality, a
  molecule or a cell type. 18 further labels name a host *taxon* rather than a
  site and are left alone — ``in_taxon`` would assert the microbe *is* a plant,
  and the correct shape is bacdive's inverse ``taxon location_of organism``.

Still open: better coverage of the ``gold.ecosystem:`` vocabulary. Without it these
edges remain an island — KG-Microbe models environments in ENVO everywhere else
(BacDive isolation sources, Madin habitats, PREGO), so a GOLD environment and a
BacDive environment for the same organism never meet. Resolution shrinks the
target vocabulary from 4,226 nodes to the named ones, which is what makes a
crosswalk tractable.

Still open upstream, unaffected by this transform: versioned filenames or a
published checksum, and the six ``Saccharomyces`` rows that lose their hybrid
``x`` marker.
"""

import csv
import io
import json
import os
import re
import tarfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.constants import (
    EXACT_MATCH,
    EXACT_MATCH_PREDICATE,
    GOLD,
    GOLD_ORGANISM_FOLD_FILE,
    GOLD_ORGANISM_FOLD_HEADER,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    NAMED_THING_CATEGORY,
    RELATED_TO_PREDICATE,
)
from kg_microbe.transform_utils.gold import selected_taxon_aliases
from kg_microbe.transform_utils.gold.crosswalk_quarantine import (
    AUDIT_FILE,
    REQUIRED_INPUTS,
    CrosswalkQuarantine,
    verify_recorded_inputs,
)
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    AUDIT_FILE as TAXON_AUDIT_FILE,
)
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    CONTRACT_KEY as TAXON_CONTRACT_KEY,
)
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    REQUIRED_INPUTS as TAXON_REQUIRED_INPUTS,
)
from kg_microbe.transform_utils.gold.taxon_dispositions import (
    TaxonDispositions,
    verify_recorded_taxon_inputs,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.source_finalization import FINALIZATION_FILE, SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer

#: Upstream filenames inside ``data/raw/gold/``.
GOLD_NODES_FILE = "GOLD_nodes.tsv"
GOLD_EDGES_FILE = "GOLD_edges.tsv"

#: Ecosystem nodes form a class hierarchy, so `subclass_of` needs them to be
#: ontology classes. Biolink requires OntologyClass on both ends of that
#: predicate; without this the edges are a domain/range violation.
_ECOSYSTEM_PREFIX = "gold.ecosystem:"
_ONTOLOGY_CLASS = "biolink:OntologyClass"

#: Categories dropped outright. GOLD ships 279,670 ``MaterialSample`` nodes with
#: 242 incident edges — 279,428 disconnected — and 60,433 ``Study`` nodes whose
#: only tie to anything is ``IndividualOrganism -related_to-> Study``, a
#: predicate that asserts nothing usable (289,946 edges, 27.5% of the export).
#: KG-Microbe wants neither samples nor studies; it wants the organism to
#: environment link, which is ``occurs_in`` and is unaffected.
_DROP_CATEGORIES = ("biolink:MaterialSample", "biolink:Study")

#: NCBI's retired-to-current taxid map lives in this member of the taxdump.
_TAXDUMP_ARCHIVE = "taxdump.tar.gz"
_MERGED_DMP = "merged.dmp"

#: The trimmed NCBITaxon set, produced by the ontologies transform. GOLD must run
#: after it. Same shape of dependency as PREGO's on ``mondo_nodes.tsv``.
_NCBITAXON_NODES = "ncbitaxon_nodes.tsv"

#: Set false to ingest GOLD unfiltered, for debugging what the trim removes.
_APPLY_TRIM_ENV = "GOLD_APPLY_TAXON_TRIM"

#: The predicate the *upstream export* uses for organism to taxon. It is not
#: what we emit — see ``_SUBCLASS_OF`` below. Kept as an input constant for the
#: same reason ``_OCCURS_IN`` is: the trim has to recognise the source rows
#: before the re-predication happens.
_IN_TAXON = "biolink:in_taxon"
_OCCURS_IN = "biolink:occurs_in"

#: What GOLD's environment edges are rewritten to. Biolink defines ``occurs in``
#: as holding "between a **process** and a material entity or site within which
#: the process occurs"; our subject is a ``biolink:IndividualOrganism``, which
#: is a material entity, not a process. ``located in`` is the one defined for a
#: material entity in a site. Neither constrains domain/range beyond
#: ``named thing``, so nothing mechanical rejects the wrong one — the definition
#: is what disqualifies it, which is why KGXVal did not flag the original.
_LOCATED_IN_PREDICATE = "biolink:located_in"
_LOCATED_IN_RELATION = "RO:0001025"

#: NOT YET EMITTED — recorded here as the shape host-taxon labels should take
#: when #790 is picked up, matching what bacdive already emits for
#: isolation-source hosts (``NCBITaxon:40674 location_of kgmicrobe.strain:...``).
#: The transform currently counts and skips those labels rather than guessing.
#: ``in_taxon`` would be wrong: its range is ``organism taxon`` and it asserts
#: the subject *is* that taxon, so a microbe found in a plant would be
#: classified as a plant.
_HOST_TAXON_EDGE_SHAPE = ("biolink:location_of", "RO:0001015")

#: GOLD's ecosystem hierarchy remains a hierarchy. Its organism_v2 rows are
#: not all strains: native records also denote metagenomes, binned genomes,
#: and unnamed referents. A different label is not proof for #834's named-
#: strain convention. Unverified native referents retain their own identifier
#: and audited taxon association, without taxonomic inheritance (#1316).
_SUBCLASS_OF = "biolink:subclass_of"

#: This is the unresolved original source referent, not a newly reified record.
_ORGANISM_CATEGORY = NAMED_THING_CATEGORY

#: Upstream category for a GOLD organism, used to recognise the rows to retype.
_INDIVIDUAL_ORGANISM = "biolink:IndividualOrganism"

#: Ecosystem labels that carry no information, so an edge pointing at one says
#: nothing. ``root`` is the hierarchy root — note it is NOT a plant root, the
#: same trap that put physicochemical bands on ``NCBITaxon:1`` in #796.
_UNINFORMATIVE_ECOSYSTEM_LABELS = frozenset({"", "unclassified", "unknown", "other", "root"})

#: Biolink's slot for "what the source said before we transformed it". Appended
#: to the standard edge header for this transform so an upward resolution stays
#: auditable and reversible.
_ORIGINAL_OBJECT = "original_object"

#: The GOLD ecosystem classification as OWL, carrying curated ENVO mappings.
#: Joined on **label**, because the ontology uses label-derived IRIs
#: (``GOLDVOCAB:Paddy-field/soil``) while the export uses numeric ids.
_GOLD_ONTOLOGY_FILE = "gold_ontology.owl"
_ENVO_PREFIX = "ENVO:"

#: Prefixes whose terms are host *taxa* rather than sites. These take the
#: inverse edge — ``taxon location_of organism`` — because saying an organism is
#: ``located_in`` a taxon reads as taxonomic classification, and ``in_taxon``
#: would assert the microbe *is* that taxon.
_HOST_TAXON_PREFIXES = ("NCBITaxon:",)

#: Prefixes a *site* may come from. An allow-list, not a deny-list, because the
#: failure is open-ended: a lexical join finds whatever shares a label. Left
#: unrestricted it produced `Alkaline -> PATO:0001430` (a quality),
#: `Benzene -> CHEBI:16716` (a molecule) and `Sperm -> CL:0000019` (a cell
#: type) — an organism is not `located_in` any of those. This is the same
#: family-mismatch class as `DISALLOWED_OBJECT_SOURCES` in
#: `isolation_source_mapping_utils.py` and the substrate/quality partition in
#: `madin_etal.py`, arrived at independently for a third time.
#:
#: ``mesh:`` is deliberately absent. MeSH is a general-purpose thesaurus
#: spanning anatomy, disease, chemicals and organisms, so a *prefix* cannot
#: express "is a site" for it: the join produced ``Invertebrates ->
#: mesh:D007448`` (a taxon group — the host-taxon case already excluded for
#: NCBITaxon, readmitted through another door) and ``Polycyclic aromatic
#: hydrocarbons -> mesh:D011084`` (a chemical class). Both label-match exactly,
#: so nothing lexical catches them. Excluding the whole prefix costs 410 of
#: 229,366 environment edges (0.18%) and removes a class of wrong assertion
#: that cannot otherwise be bounded by a rule.
_SITE_PREFIXES = ("ENVO:", "UBERON:", "FOODON:", "PO:", "FAO:")

#: Per-term MeSH decisions, because a prefix rule cannot express "is a site"
#: for a thesaurus spanning anatomy, disease, chemicals and organisms (#823).
#: Every reachable MeSH term is listed and decided; anything unlisted is not
#: bridged, so unknown means no and a new upstream label cannot readmit the
#: class of error the file exists to prevent.
_MESH_SITE_FILE = "gold_ecosystem_mesh_sites.tsv"
_MESH_PREFIX = "mesh:"


def _normalise_label(text: str) -> str:
    """
    Fold a label for lexical joining.

    :param text: Raw label.
    :return: Lowercased, punctuation- and separator-normalised form.
    """
    folded = re.sub(r"[\s_/-]+", " ", text.strip().lower())
    folded = re.sub(r"[^\w\s]", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


_TAXON_PREFIX = "NCBITaxon:"


class GOLDTransform(Transform):
    """Conform the pre-transformed GOLD KGX TSVs to the KG-Microbe standard."""

    #: Reads this transform's output; see Transform.TRANSFORM_INPUTS (#845).
    TRANSFORM_INPUTS = ("ontologies", "ontologies_stubs")

    #: The MeSH site curation this transform reads. Declared so the freshness
    #: check notices an edit to it — a transform that reads a curation file
    #: without declaring it is reported fresh while its output is stale, which
    #: is #812, then #839, and would have been this transform next (#876).
    DATA_INPUTS = (
        f"mappings/{_MESH_SITE_FILE}",
        "mappings/gold_abscess_crosswalk_policy.json",
        "mappings/gold_taxon_dispositions.json",
        "mappings/gold_selected_taxon_aliases.json",
    )
    REQUIRED_CONSUMED_INPUTS = (*REQUIRED_INPUTS, *TAXON_REQUIRED_INPUTS, *selected_taxon_aliases.REQUIRED_INPUTS)
    REQUIRED_AUDIT_FILES = (
        AUDIT_FILE,
        TAXON_AUDIT_FILE,
        "gold_lexical_fold_restorations.tsv",
        selected_taxon_aliases.AUDIT_FILE,
    )

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """
        Instantiate the transform.

        :param input_dir: Directory holding ``gold/``.
        :param output_dir: Transform output directory.
        """
        super().__init__(GOLD, input_dir, output_dir)
        self._merges: Optional[dict] = None
        self._envo_map: Optional[dict] = None
        self._envo_nodes_cache: Optional[set] = None
        self._label_index: Optional[dict] = None
        self._mesh_sites: Optional[set] = None
        self._crosswalk_quarantine = None
        self._recorded_crosswalk_inputs = None
        self._recorded_native_guard = None
        self._recorded_native_admission = None
        self._native_publication_failed = False
        self._taxon_dispositions = None

    @property
    def producer_native_inputs(self):
        """Retain the reviewed selection contract independently of mutable receipts."""
        if self._crosswalk_quarantine is not None:
            return {
                **self._crosswalk_quarantine.contract(),
                TAXON_CONTRACT_KEY: self._taxon_dispositions.contract(),
                selected_taxon_aliases.CONTRACT_KEY: self._taxon_dispositions.aliases.contract(),
            }
        return self._recorded_crosswalk_inputs

    @producer_native_inputs.setter
    def producer_native_inputs(self, recorded):
        """Allow repeated admission only against the original consumed native inputs."""
        if self._native_publication_failed:
            raise SourceFinalizationRequired("GOLD native publication previously failed; rerun the producer")
        if self._crosswalk_quarantine is not None and recorded != self.producer_native_inputs:
            raise SourceFinalizationRequired("GOLD crosswalk cohort differs from finalized run")
        if self._recorded_native_guard is not None:
            self._recorded_native_guard()
            if recorded != self._recorded_crosswalk_inputs:
                raise SourceFinalizationRequired("GOLD recorded native contract was replaced")
            return
        if self._crosswalk_quarantine is None:
            self._restore_native_guard(recorded)
            return
        verify_recorded_inputs(
            {
                "consumed_inputs": self.consumed_input_snapshots,
                "producer_native_inputs": recorded,
                "raw_input_directory": str(self.input_base_dir.resolve()),
            }
        )
        self._recorded_crosswalk_inputs = recorded

    def _restore_native_guard(self, recorded, *, report_path=None):
        """Rejoin the complete saved producer once and retain exact live state bindings (#1339)."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        report_path = Path(report_path) if report_path is not None else self.output_dir / FINALIZATION_FILE
        admission = SourceAdmission()
        report = json.loads(admission.capture(report_path, retain=True))
        if recorded != report.get("producer_native_inputs"):
            raise SourceFinalizationRequired("GOLD supplied native contract differs from published report")
        self.verify_recorded_native_inputs(report, report_path, admission=admission)
        encode = selected_taxon_aliases._json
        original_contract = encode(recorded)
        original_roles = encode(report.get("consumed_inputs"))
        original_audits = encode(report.get("producer_audit_members"))
        original_raw = report.get("raw_input_directory")
        original_output = self.output_dir.absolute()
        self._recorded_crosswalk_inputs = json.loads(original_contract)
        failed = False

        def verify_state():
            """Retain the complete restored state contract independently of the public guard binding."""
            nonlocal failed
            try:
                if (
                    failed
                    or self._recorded_native_guard is not verify
                    or self._recorded_native_admission is not admission
                    or encode(self._recorded_crosswalk_inputs) != original_contract
                    or encode(self.consumed_input_snapshots) != original_roles
                    or encode(self.producer_audit_snapshots) != original_audits
                    or str(self.input_base_dir.resolve()) != original_raw
                    or self.output_dir.absolute() != original_output
                ):
                    raise SourceFinalizationRequired("GOLD restored native contract or input bindings changed")
            except Exception:
                failed = True
                raise
            return True

        def verify(*, metadata_only=True, output_dir=None):
            """Refuse changed restored contracts, roles, artifacts or guard bindings without repair."""
            nonlocal failed
            verify_state()
            if output_dir is not None and Path(output_dir).absolute() != original_output:
                failed = True
                raise SourceFinalizationRequired("GOLD restored native output directory changed")
            admission.verify(metadata_only=metadata_only)

        self._recorded_native_guard = verify
        self._recorded_native_admission = admission
        admission.capture_resolution(verify_state)
        verify(metadata_only=False)

    def verify_native_inputs(self, *, byte_verified=False, output_dir=None):
        """Verify lexical paths as well as the immutable parser snapshots."""
        if self._native_publication_failed:
            raise SourceFinalizationRequired("GOLD native publication previously failed; rerun the producer")
        if self._recorded_native_admission is not None:
            self._recorded_native_admission.verify(metadata_only=byte_verified)
        if self._crosswalk_quarantine is not None:
            self._crosswalk_quarantine.verify_bindings(byte_verified=byte_verified)
            if self._taxon_dispositions is not None:
                self._taxon_dispositions.verify(output_dir=output_dir, metadata_only=byte_verified)
        elif self._recorded_native_guard is not None:
            self._recorded_native_guard(metadata_only=byte_verified, output_dir=output_dir)
        else:
            raise SourceFinalizationRequired("GOLD native producer guard is missing; rerun or restore finalization")

    @classmethod
    def verify_recorded_native_inputs(cls, report, report_path, *, admission=None):
        """Validate persisted cohort/authority bindings; never edit a graph during admission."""
        verify_recorded_inputs(report, report_path)
        return verify_recorded_taxon_inputs(report, report_path, admission=admission)

    def finalize(self, *, file_prefix="", fresh_run=False):
        """Transition legitimate published output replacements without rebasing native inputs (#1342)."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission
        from kg_microbe.transform_utils.gold.taxon_dispositions import restore_gold_declarations

        if self._native_publication_failed:
            raise SourceFinalizationRequired("GOLD native publication previously failed; rerun the producer")
        if self._crosswalk_quarantine is None:
            return super().finalize(file_prefix=file_prefix, fresh_run=fresh_run)
        self.verify_consumed_inputs()
        original_contract = selected_taxon_aliases._json(self.producer_native_inputs)
        boundary = SourceAdmission()
        for snapshot in self.consumed_input_snapshots.values():
            boundary.capture(snapshot["path"])
        # Retain selected lexical aliases as well as resolved consumed paths.
        for role, path in selected_taxon_aliases._locators(self.input_base_dir, self.output_base_dir).items():
            if role in self.consumed_input_snapshots:
                boundary.capture(path)
        for optional in self._taxon_dispositions.optional:
            boundary.capture(optional["path"], optional=True)
        original_guards = (boundary, self._crosswalk_quarantine.guard, self._taxon_dispositions.admission)
        original_directory = self.output_dir.absolute()
        try:
            # Base publication still verifies every original live guard before
            # replacing outputs. The boundary guard was captured before that
            # check and must remain unchanged afterward, including equal bytes.
            report = super().finalize(file_prefix=file_prefix, fresh_run=fresh_run)
            if (
                self.output_dir.absolute() != original_directory
                or selected_taxon_aliases._json(report.get("producer_native_inputs")) != original_contract
            ):
                raise SourceFinalizationRequired("GOLD published native contract differs from its producer")
            for guard in original_guards:
                guard.verify(metadata_only=True)
            report_path = self.output_dir / f"{file_prefix}{FINALIZATION_FILE}"
            self._restore_native_guard(json.loads(original_contract), report_path=report_path)
            admission = self._recorded_native_admission
            for guard in original_guards:
                admission.capture_resolution(lambda original=guard: original.verify(metadata_only=True))
            # Own-GOLD nameless declarations also retained the former producer
            # output guard. Rejoin their exact published scope using the same
            # completed admission cache, not a second graph-scale native scan.
            restore_gold_declarations(self, report, report_path, admission=admission)
            admission.verify(metadata_only=True)
            self._crosswalk_quarantine = None
            self.verify_consumed_inputs()
            return report
        except Exception:
            self._native_publication_failed = True
            raise

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True) -> None:
        """
        Conform the upstream TSVs and write standard nodes/edges.

        :param data_file: Unused; the filenames are fixed by the download entry.
        :param show_status: Unused; retained for the base-class signature.
        :raises FileNotFoundError: If either upstream file is missing.
        """
        raw = self.input_base_dir / GOLD
        nodes_in, edges_in = raw / GOLD_NODES_FILE, raw / GOLD_EDGES_FILE
        for path in (nodes_in, edges_in):
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing; run `poetry run kg download -t gold` first.")

        self.begin_consumed_inputs()
        self._merges = self._envo_map = self._envo_nodes_cache = self._label_index = self._mesh_sites = None
        self._crosswalk_quarantine = self._recorded_crosswalk_inputs = None
        self._recorded_native_guard = None
        self._recorded_native_admission = None
        self._native_publication_failed = False
        self._taxon_dispositions = None
        with ExitStack() as stack:
            scope = CrosswalkQuarantine(self, stack, nodes_in, edges_in)
            self._crosswalk_quarantine = scope
            self._taxon_dispositions = TaxonDispositions(self, stack, scope)
            self._run_snapshot(scope.nodes_path, scope.edges_path)
            scope.finish()
            self._taxon_dispositions.finish()

    def _run_snapshot(self, nodes_in, edges_in):
        """Use the same captured native records for every existing GOLD pass."""
        # Order matters: remap retired taxids first, so a taxon NCBI has merged
        # into a current one is judged by the trim on the id it actually means.
        # Judging it on the retired id drops ~950 taxa, many of them bacteria.
        self._taxid_merges()
        dropped = self._category_drop_set(nodes_in)
        taxon_dropped, seen_before = self._taxon_drop_set(nodes_in, edges_in)
        dropped |= taxon_dropped
        resolution, ecosystem_labels = self._ecosystem_resolution(nodes_in, edges_in)
        # Label equality does not establish record identity. Retain source IDs
        # and source-owned observations; the complete historical counterfactual
        # is independently reconstructed in the mandatory restoration audit.
        incident = self._write_edges(edges_in, dropped, resolution, ecosystem_labels)
        self._write_nodes(nodes_in, dropped, seen_before, incident)
        # Retire the old identity table explicitly, including repeated runs.
        # Historical decisions belong only in the complete restoration audit.
        with atomic_write(self.output_dir / GOLD_ORGANISM_FOLD_FILE, encoding="utf-8", newline="") as handle:
            writer = tsv_writer(handle)
            writer.writerow(GOLD_ORGANISM_FOLD_HEADER)

    def _trimmed_taxa(self) -> Optional[set]:
        """
        Load the taxon IDs that survived the NCBITaxon trim.

        :return: The permitted ``NCBITaxon:`` IDs, or None when filtering is off.
        :raises FileNotFoundError: If the ontologies output is absent while
            filtering is on — silently skipping the trim would reintroduce every
            excluded branch with nothing to show it had happened.
        :raises ValueError: If the ontologies output carries no ``NCBITaxon:``
            rows. An empty permitted set is never a legitimate trim: it makes
            every GOLD taxon "excluded", drops every organism typed to one, and
            cascades to an empty graph reported as a successful run. A
            header-only or truncated derived file is a known failure mode in this
            repo — ``atomic_io`` exists for it — and the ontologies output
            predates that work, so it carries no completion marker to check.
        """
        if os.environ.get(_APPLY_TRIM_ENV, "true").strip().lower() in ("false", "0", "no"):
            print(f"[gold] {_APPLY_TRIM_ENV} is off — emitting excluded-branch taxa unfiltered")
            return None
        path = self.output_base_dir / "ontologies" / _NCBITAXON_NODES
        if self._taxon_dispositions is not None and self._taxon_dispositions.ncbi is not None:
            path = self._taxon_dispositions.ncbi
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing, so the NCBITaxon trim cannot be applied. Run "
                f"`poetry run kg transform -s ontologies` first, or set {_APPLY_TRIM_ENV}=false "
                "to ingest GOLD unfiltered (which reintroduces viruses, plants and metazoa)."
            )
        with path.open(newline="") as handle:
            permitted = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
        taxa = {node_id for node_id in permitted if node_id.startswith(_TAXON_PREFIX)}
        if not taxa:
            raise ValueError(
                f"{path} has no {_TAXON_PREFIX} rows ({len(permitted):,} rows total), so the trim "
                "would exclude every GOLD taxon and emit an empty graph. Re-run "
                f"`poetry run kg transform -s ontologies`, or set {_APPLY_TRIM_ENV}=false to "
                "ingest GOLD unfiltered."
            )
        return taxa

    def _mesh_site_terms(self) -> set:
        """
        MeSH CURIEs curated as sites.

        :return: The ``SITE`` CURIEs; empty when the curation file is absent,
            which keeps the #821 behaviour of bridging no MeSH at all.
        """
        if self._crosswalk_quarantine is not None:
            return self._crosswalk_quarantine.allowed_mesh
        if self._mesh_sites is not None:
            return self._mesh_sites
        path = Path(__file__).resolve().parents[3] / "mappings" / _MESH_SITE_FILE
        allowed: set = set()
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as handle:
                rows = (line for line in handle if not line.startswith("#"))
                for row in csv.DictReader(rows, delimiter="\t"):
                    if (row.get("decision") or "").strip().upper() == "SITE":
                        allowed.add((row.get("mesh_id") or "").strip())
        self._mesh_sites = {curie for curie in allowed if curie}
        return self._mesh_sites

    def _ontology_label_index(self) -> dict:
        """
        Label to CURIE across the ontologies already in the graph.

        The GOLD ontology's ``skos:exactMatch`` links cover only 26.9% of
        environment edges, and label normalisation recovers exactly one more —
        the uncovered labels are absent from it rather than spelled differently.
        But 42.9% of the remainder match an ontology KG-Microbe already loads,
        overwhelmingly host anatomy: ``Rumen`` -> ``UBERON:0007365``, ``Blood``
        -> ``UBERON:0000178``, ``Nasopharynx`` -> ``UBERON:0001728`` (the same
        term #816 used for the Madin nasopharyngeal row).

        Only the *primary label* is indexed, not synonyms: a synonym match is a
        weaker claim and this join is already lexical.

        :return: ``{normalised label: CURIE}``.
        """
        if self._label_index is not None:
            return self._label_index
        index: dict = {}
        sources = [
            self.output_base_dir / "ontologies" / name
            for name in ("uberon_nodes.tsv", "envo_nodes.tsv", "foodon_nodes.tsv")
        ]
        # PO is a MIREOT stub, not a full ontology load, so it lands in a
        # different directory. Reading it from `ontologies/` failed
        # `is_file()` silently, so PO never contributed despite the log line
        # claiming it did.
        sources.append(self.output_base_dir / "ontologies_stubs" / "po_nodes.tsv")
        # MeSH is indexed so the curated SITE terms are reachable. Everything
        # else it contributes is refused by the per-term gate below, which is
        # why indexing the whole file here is safe.
        mesh = self.output_base_dir / "ontologies_stubs" / "mesh_nodes.tsv"
        if self._crosswalk_quarantine is not None and self._crosswalk_quarantine.mesh_path is not None:
            mesh = self._crosswalk_quarantine.mesh_path
        sources.append(mesh)
        for path in sources:
            if not path.is_file():
                continue
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                for row in reader:
                    label = (row.get("name") or "").strip()
                    curie = (row.get("id") or "").strip()
                    if label and curie:
                        index.setdefault(_normalise_label(label), curie)
        self._label_index = index
        return index

    def _envo_nodes(self) -> set:
        """
        ENVO ids the ontologies transform emits.

        Used to refuse a crosswalk edge whose target has no node, rather than
        creating an untyped endpoint the merge would materialise as
        ``biolink:NamedThing``.

        :return: Set of ENVO CURIEs, empty when the extract is absent.
        """
        if self._envo_nodes_cache is not None:
            return self._envo_nodes_cache
        available: set = set()
        path = self.output_base_dir / "ontologies" / "envo_nodes.tsv"
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                handle.readline()
                for line in handle:
                    curie = line.split("\t", 1)[0]
                    if curie.startswith(_ENVO_PREFIX):
                        available.add(curie)
        self._envo_nodes_cache = available
        return available

    def _envo_crosswalk(self) -> dict:
        """
        Map lowercased GOLD ecosystem label to an ENVO CURIE.

        Read from the GOLD ontology (``cmungall/gold-ontology``), which carries
        curated ``skos:exactMatch`` links to ENVO. Only exactMatch is used: the
        MIxS ``env_broad`` / ``env_local`` / ``env_medium`` triad is contextual
        scale annotation rather than equivalence, and measured against our
        targets it adds essentially nothing beyond exactMatch (26.9% edge
        coverage either way).

        Absence is non-fatal — no crosswalk edges are emitted and the ecosystem
        vocabulary stays an island, which is the behaviour before this existed.

        :return: ``{label: ENVO CURIE}``, empty when the ontology is unavailable.
        """
        if self._envo_map is not None:
            return self._envo_map

        mapping: dict = {}
        path = self.input_base_dir / _GOLD_ONTOLOGY_FILE
        if self._crosswalk_quarantine is not None and self._crosswalk_quarantine.ontology_path is not None:
            path = self._crosswalk_quarantine.ontology_path
        if not path.is_file():
            print(f"[gold] {path} not found — no ENVO crosswalk emitted; run `poetry run kg download -t gold`")
            self._envo_map = mapping
            return mapping

        try:
            import rdflib
        except ImportError:  # pragma: no cover - rdflib is a hard dependency
            print("[gold] rdflib unavailable; no ENVO crosswalk emitted")
            self._envo_map = mapping
            return mapping

        graph = rdflib.Graph()
        graph.parse(str(path), format="xml")
        skos_exact = rdflib.URIRef("http://www.w3.org/2004/02/skos/core#exactMatch")
        labels = {s: str(o) for s, o in graph.subject_objects(rdflib.RDFS.label)}
        for subject, obj in graph.subject_objects(skos_exact):
            match = re.search(r"ENVO_(\d+)$", str(obj))
            if match and subject in labels:
                mapping.setdefault(labels[subject].strip().lower(), f"{_ENVO_PREFIX}{match.group(1)}")
        print(f"[gold] ENVO crosswalk: {len(mapping):,} GOLD labels carry a skos:exactMatch")
        self._envo_map = mapping
        return mapping

    def _ecosystem_resolution(self, nodes_in: Path, edges_in: Path) -> dict:
        """
        Map each uninformative ecosystem node to its nearest informative ancestor.

        63.5% of GOLD's ``occurs_in`` edges point at a node labelled
        "Unclassified", and there are 1,663 distinct such nodes — so the label
        is not even a bucket you can filter, it is 1,663 semantically empty ids.
        The meaning is in the hierarchy: ``Unclassified <- Unclassified <-
        Unclassified <- Mammals: Human`` says the organism came from a human
        host, but only if you walk up.

        Resolving here rather than leaving it to consumers means a one-hop query
        gets the fact GOLD actually holds. Measured: 228,634 of 286,725 edges
        (79.7%) resolve to something informative.

        A node resolving only to the hierarchy root is mapped to ``None`` and its
        edges are dropped — 58,340 asserting an organism lives somewhere. (An
        earlier 58,091 was measured before the retired-taxid remap, which
        rescues organisms and so raises every downstream count.)

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :return: ``({ecosystem id: resolved id or None}, {ecosystem id: label})``.
        """
        labels: dict = {}
        with nodes_in.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["id"].startswith(_ECOSYSTEM_PREFIX):
                    labels[row["id"]] = (row.get("name") or "").strip()

        parent: dict = {}
        with edges_in.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["predicate"] == _SUBCLASS_OF and row["subject"].startswith(_ECOSYSTEM_PREFIX):
                    parent[row["subject"]] = row["object"]

        def informative(node: str) -> bool:
            """Report whether a node's label says anything."""
            return labels.get(node, "").lower() not in _UNINFORMATIVE_ECOSYSTEM_LABELS

        resolution: dict = {}
        for node in labels:
            if informative(node):
                continue
            seen = {node}
            cur = parent.get(node)
            while cur is not None and not informative(cur):
                if cur in seen:  # defensive: a cycle would otherwise hang
                    cur = None
                    break
                seen.add(cur)
                cur = parent.get(cur)
            resolution[node] = cur

        resolvable = sum(1 for v in resolution.values() if v is not None)
        print(
            f"[gold] ecosystem resolution: {resolvable:,} of {len(resolution):,} uninformative "
            f"nodes resolve to a named ancestor; {len(resolution) - resolvable:,} resolve to nothing"
        )
        return resolution, labels

    def _taxid_merges(self) -> dict:
        """
        NCBI's retired-taxid to current-taxid map, from ``merged.dmp``.

        GOLD's export carries roughly 950 taxa NCBI has since merged. Left
        alone they point at ids no longer in NCBITaxon, so the trim drops them
        along with the organisms typed to them — losing bacteria we would
        otherwise keep, which is the opposite of what the trim is for.

        Read straight out of the tarball; NCBI publishes no standalone
        ``merged.dmp``. Absence is non-fatal: without it the remap is a no-op
        and the affected taxa are dropped as before, which is the pre-existing
        behaviour rather than a new failure.

        :return: ``{"NCBITaxon:<old>": "NCBITaxon:<new>"}``, empty if unavailable.
        """
        if self._merges is not None:
            return self._merges

        merges: dict = {}
        archive = self.input_base_dir / _TAXDUMP_ARCHIVE
        if self._taxon_dispositions is not None and self._taxon_dispositions.taxdump is not None:
            archive = self._taxon_dispositions.taxdump
        if not archive.is_file():
            print(
                f"[gold] {archive} not found — retired NCBI taxids will not be remapped; "
                "run `poetry run kg download -t gold`"
            )
            self._merges = merges
            return merges

        with tarfile.open(archive, "r:gz") as tar:
            member = tar.extractfile(_MERGED_DMP)
            if member is None:
                print(f"[gold] {_MERGED_DMP} missing from {archive.name}; no remap applied")
                self._merges = merges
                return merges
            for raw in io.TextIOWrapper(member, encoding="utf-8"):
                # merged.dmp rows look like:  old_id\t|\tnew_id\t|
                parts = [f.strip() for f in raw.split("|")]
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    merges[f"{_TAXON_PREFIX}{parts[0]}"] = f"{_TAXON_PREFIX}{parts[1]}"
        print(f"[gold] loaded {len(merges):,} NCBI taxid merges from {_MERGED_DMP}")
        self._merges = merges
        return merges

    def _remap(self, node_id: str) -> str:
        """
        Rewrite a retired NCBI taxid to its current one.

        :param node_id: Any node id; non-taxon ids pass through untouched.
        :return: The current id, or the input when there is no merge record.
        """
        if self._taxon_dispositions is not None:
            return self._taxon_dispositions.aliases.resolve(node_id)
        return self._taxid_merges().get(node_id, node_id)

    def _category_drop_set(self, nodes_in: Path) -> set:
        """
        Ids whose category KG-Microbe does not ingest.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :return: Ids of sample and study nodes.
        """
        with nodes_in.open(newline="") as handle:
            drop = {
                row["id"]
                for row in csv.DictReader(handle, delimiter="\t")
                if any(c in (row.get("category") or "") for c in _DROP_CATEGORIES)
            }
        print(f"[gold] dropping {len(drop):,} sample/study nodes and every edge touching them")
        return drop

    def _taxon_drop_set(self, nodes_in: Path, edges_in: Path) -> tuple:
        """
        Decide what the trim removes, before anything is written.

        Three things go: taxa outside the trimmed set, the organisms typed to
        them — an organism whose taxon is a spruce or a starling does not belong
        in a microbial graph — and the studies left holding nothing else. The
        last is a condition we create, so we clean it up; the orphans already in
        the upstream payload are a separate modelling question and are left alone.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :return: ``(ids_to_drop, ids_that_had_an_edge_upstream)``.
        """
        permitted = self._trimmed_taxa()
        seen_before: set = set()
        if permitted is None:
            with edges_in.open(newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    # Remap here too. The writers remap unconditionally, so
                    # recording raw ids would desync the orphan bookkeeping and
                    # drop nodes that do still have a surviving edge.
                    seen_before.add(self._remap(row["subject"]))
                    seen_before.add(self._remap(row["object"]))
            return set(), seen_before

        with nodes_in.open(newline="") as handle:
            excluded = {
                row["id"]
                for row in csv.DictReader(handle, delimiter="\t")
                if row["id"].startswith(_TAXON_PREFIX) and self._remap(row["id"]) not in permitted
            }
        organisms: set = set()
        with edges_in.open(newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                seen_before.add(self._remap(row["subject"]))
                seen_before.add(self._remap(row["object"]))
                if row["predicate"] == _IN_TAXON and row["object"] in excluded:
                    organisms.add(row["subject"])
        print(
            f"[gold] NCBITaxon trim: dropping {len(excluded):,} taxa outside the trimmed set "
            f"and {len(organisms):,} organisms typed to them"
        )
        return excluded | organisms, seen_before

    def _write_edges(
        self,
        edges_in: Path,
        dropped: set,
        resolution: dict,
        ecosystem_labels: dict,
    ) -> set:
        """
        Write surviving edges, resolving uninformative ecosystem targets upward.

        :param edges_in: Upstream ``GOLD_edges.tsv``.
        :param dropped: IDs removed by the trim.
        :param resolution: Ecosystem id to nearest informative ancestor, or None.
        :param ecosystem_labels: Ecosystem id to its label, for the ENVO crosswalk.
        :return: IDs incident to at least one surviving edge.
        """
        incident: set = set()
        kept = removed = resolved = uninformative = relabelled = 0
        retyped = deduped = 0
        # Preserve record ownership. Only duplicate triples within a record,
        # e.g. resolved environment aliases, can now be deduplicated here.
        seen_triples: set = set()
        with (
            edges_in.open(newline="") as handle,
            self.output_edge_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = tsv_writer(out)
            # `original_object` is Biolink's slot for what the source said before
            # transformation, so an upward resolution stays auditable and
            # reversible rather than silently rewriting the target.
            writer.writerow(list(self.edge_header) + [_ORIGINAL_OBJECT])
            for row in reader:
                subject, obj = self._remap(row["subject"]), self._remap(row["object"])
                if row["subject"] in dropped or row["object"] in dropped or subject in dropped or obj in dropped:
                    removed += 1
                    continue

                original_object = ""
                predicate = row["predicate"]
                relation = row.get("relation", "")

                if predicate == _IN_TAXON:
                    # A taxonomy field is source evidence for an association,
                    # not proof that this heterogeneous referent is a strain.
                    # Preserve the literal native relation in the graph/audit.
                    predicate = RELATED_TO_PREDICATE
                    retyped += 1

                if predicate == _OCCURS_IN:
                    if obj in resolution:
                        target = resolution[obj]
                        if target is None:
                            # Resolves only to the hierarchy root: "lives somewhere".
                            uninformative += 1
                            continue
                        original_object = obj
                        obj = target
                        resolved += 1
                    # Correct the predicate while we are rewriting the target.
                    # Upstream ships `occurs_in`, which Biolink defines for a
                    # *process*; the subject here is an organism.
                    predicate = _LOCATED_IN_PREDICATE
                    relation = _LOCATED_IN_RELATION
                    relabelled += 1

                # After the upward resolution, not before: two isolates on
                # different uninformative ecosystems can resolve to the same
                # ancestor, and checking the pre-resolution target would miss it.
                if (subject, predicate, obj) in seen_triples:
                    deduped += 1
                    continue
                seen_triples.add((subject, predicate, obj))

                incident.add(subject)
                incident.add(obj)
                kept += 1
                emitted = [
                    subject,
                    predicate,
                    obj,
                    relation,
                    row.get("primary_knowledge_source", "") or f"infores:{GOLD}",
                    KNOWLEDGE_ASSERTION,
                    MANUAL_AGENT,
                    original_object,
                ]
                writer.writerow(emitted)
                if self._crosswalk_quarantine is not None:
                    self._crosswalk_quarantine.observe_location(
                        row, dict(zip([*self.edge_header, _ORIGINAL_OBJECT], emitted, strict=True))
                    )
            # Bridge the ecosystem vocabulary to ENVO. Emitted as edges rather
            # than by rewriting `occurs_in` targets, so GOLD's own hierarchy
            # survives intact and the crosswalk is inspectable on its own. A
            # consumer reaches ENVO in two hops:
            #   organism -occurs_in-> gold.ecosystem: -exact_match-> ENVO:
            crosswalk = self._envo_crosswalk()
            bridged = unresolvable = 0
            if crosswalk:
                # Only bridge to ENVO terms the ontologies transform actually
                # carries. 7 of the 210 targets are absent from our extract, and
                # emitting those would mint untyped `biolink:NamedThing`
                # phantoms — the defect fixed for NCBITaxon in #815, for LPSN in
                # #817 and for the taxid remap in #819. Not repeating it here.
                available = self._envo_nodes()
                for eco_id, label in sorted(ecosystem_labels.items()):
                    if eco_id not in incident:
                        continue  # nothing points at it after resolution
                    envo = crosswalk.get(label.strip().lower())
                    if not envo:
                        continue
                    if available and envo not in available:
                        unresolvable += 1
                        continue
                    kept += 1
                    writer.writerow(
                        [
                            eco_id,
                            EXACT_MATCH_PREDICATE,
                            envo,
                            EXACT_MATCH,
                            f"infores:{GOLD}",
                            KNOWLEDGE_ASSERTION,
                            MANUAL_AGENT,
                            "",
                        ]
                    )
                    bridged += 1
                print(f"[gold]   ENVO crosswalk: {bridged:,} ecosystem nodes bridged to ENVO")

            # Second pass: labels the GOLD ontology does not map, but which name
            # a term KG-Microbe already carries — overwhelmingly host anatomy.
            index = self._ontology_label_index()
            anatomy = host_taxa = non_site = 0
            bridged_prefixes: Counter = Counter()
            for eco_id, label in sorted(ecosystem_labels.items()):
                if eco_id not in incident:
                    continue
                if crosswalk.get(label.strip().lower()):
                    continue  # already bridged by the curated GOLD mapping
                curie = index.get(_normalise_label(label))
                if self._crosswalk_quarantine is not None and eco_id in self._crosswalk_quarantine.ecosystem_ids:
                    proposed = dict(
                        zip(
                            [*self.edge_header, _ORIGINAL_OBJECT],
                            [
                                eco_id,
                                EXACT_MATCH_PREDICATE,
                                curie,
                                EXACT_MATCH,
                                f"infores:{GOLD}",
                                KNOWLEDGE_ASSERTION,
                                MANUAL_AGENT,
                                "",
                            ],
                            strict=True,
                        )
                    )
                    self._crosswalk_quarantine.intercept(eco_id, label, curie, proposed)
                    continue
                if not curie or curie.startswith(_ECOSYSTEM_PREFIX):
                    continue
                if curie.startswith(_MESH_PREFIX):
                    # Per-term, not per-prefix: `Invertebrates`, `Bacteria` and
                    # `Cnidaria` are taxon groups and `Polycyclic aromatic
                    # hydrocarbons` is a chemical class, all label-matching
                    # exactly. Unlisted MeSH terms are refused.
                    if curie not in self._mesh_site_terms():
                        non_site += 1
                        continue
                    kept += 1
                    anatomy += 1
                    bridged_prefixes[_MESH_PREFIX.rstrip(":")] += 1
                    writer.writerow(
                        [
                            eco_id,
                            EXACT_MATCH_PREDICATE,
                            curie,
                            EXACT_MATCH,
                            f"infores:{GOLD}",
                            KNOWLEDGE_ASSERTION,
                            MANUAL_AGENT,
                            "",
                        ]
                    )
                    continue
                if not curie.startswith(_SITE_PREFIXES + _HOST_TAXON_PREFIXES):
                    non_site += 1
                    continue
                if curie.startswith(_HOST_TAXON_PREFIXES):
                    # Inverse direction, matching what bacdive emits for
                    # isolation-source host taxa.
                    host_taxa += 1
                    continue
                kept += 1
                anatomy += 1
                bridged_prefixes[curie.split(":", 1)[0]] += 1
                writer.writerow(
                    [
                        eco_id,
                        EXACT_MATCH_PREDICATE,
                        curie,
                        EXACT_MATCH,
                        f"infores:{GOLD}",
                        KNOWLEDGE_ASSERTION,
                        MANUAL_AGENT,
                        "",
                    ]
                )
            if anatomy:
                # Report what actually contributed, not the list of sources
                # consulted: PO is read but currently matches nothing, and the
                # old message named it anyway.
                breakdown = ", ".join(f"{p}={n}" for p, n in sorted(bridged_prefixes.items()))
                print(f"[gold]   label crosswalk: {anatomy:,} further ecosystem nodes bridged ({breakdown})")
            if non_site:
                print(f"[gold]   {non_site:,} label match(es) rejected as not a site (quality / molecule / cell type)")
            if host_taxa:
                print(
                    f"[gold]   {host_taxa:,} ecosystem node(s) name a host TAXON, not a site — "
                    "not bridged; these need `taxon location_of organism`, see #790"
                )
            # Top-level, not nested under host_taxa: these count unrelated
            # things, and nesting meant a run with zero host-taxon matches would
            # swallow this warning entirely.
            if unresolvable:
                print(
                    f"[gold]   {unresolvable:,} skipped — their ENVO term is not in "
                    "data/transformed/ontologies/envo_nodes.tsv"
                )

        # "dropped" spans both reasons — the taxon trim and the sample/study
        # categories — so do not attribute it to the trim alone.
        print(f"[gold] edges emitted: {kept:,}" + (f" (dropped {removed:,})" if removed else ""))
        if resolved or uninformative:
            print(
                f"[gold]   environment edges: {resolved:,} resolved up to a named ancestor, "
                f"{uninformative:,} dropped as resolving only to the hierarchy root"
            )
        if relabelled:
            print(
                f"[gold]   {relabelled:,} re-predicated occurs_in -> located_in "
                "(Biolink defines occurs_in for a process, not an organism)"
            )
        if retyped:
            print(
                f"[gold]   {retyped:,} retained in_taxon claims as audited related_to associations "
                "(native referent identity unresolved; no taxonomic inheritance)"
            )
        if deduped:
            print(f"[gold]   {deduped:,} duplicate triples removed after environment resolution")
        return incident

    def _write_nodes(self, nodes_in: Path, dropped: set, seen_before: set, incident: set) -> None:
        """
        Write surviving nodes in the standard column order, adding missing columns.

        A node goes if the trim removed it, or if it had an edge upstream and has
        none left — that second case is orphaning *we* caused, so we clean it up.
        Nodes that were already edgeless upstream are kept and reported, because
        whether to drop those is a modelling decision for GOLD, not ours.

        :param nodes_in: Upstream ``GOLD_nodes.tsv``.
        :param dropped: IDs removed by the trim.
        :param seen_before: IDs incident to an edge in the upstream payload.
        :param incident: IDs incident to a surviving edge.
        """
        emitted = removed = newly_orphaned = remapped_collisions = 0
        pre_existing_orphans: set = set()
        # Which ids the upstream file carries verbatim, so a retired row can
        # defer to its replacement's own row rather than donating a stale name.
        with nodes_in.open(newline="") as handle:
            verbatim_ids = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
        with (
            nodes_in.open(newline="") as handle,
            self.output_node_file.open("w", newline="") as out,
        ):
            reader = csv.DictReader(handle, delimiter="\t")
            writer = tsv_writer(out)
            writer.writerow(self.node_header)
            written: set = set()
            for row in reader:
                original_id = row["id"]
                node_id = self._remap(original_id)
                if original_id != node_id and node_id in verbatim_ids:
                    # Both the retired id and its replacement are present
                    # upstream. Skip the retired row and let the replacement's
                    # own row supply the node, so the surviving node does not
                    # carry the merged-away taxon's name: 232 of 420 collisions
                    # would otherwise label NCBITaxon:296995 "Exiguobacterium
                    # enclense" instead of "Exiguobacterium indicum", because
                    # the retired row happens to come first in the file.
                    remapped_collisions += 1
                    continue
                if node_id in written:
                    # Several retired ids can merge into one target that is not
                    # itself present upstream; the first is as good as any.
                    remapped_collisions += 1
                    continue
                if original_id in dropped or node_id in dropped:
                    removed += 1
                    continue
                if node_id in seen_before and node_id not in incident:
                    newly_orphaned += 1
                    removed += 1
                    continue
                if node_id not in seen_before:
                    pre_existing_orphans.add(node_id)
                category = row.get("category", "")
                if node_id.startswith(_ECOSYSTEM_PREFIX) and _ONTOLOGY_CLASS not in category:
                    category = f"{category}|{_ONTOLOGY_CLASS}" if category else _ONTOLOGY_CLASS
                elif category == _INDIVIDUAL_ORGANISM:
                    # No native structured strain evidence is supplied here;
                    # retain the unresolved referent and its literal name.
                    category = _ORGANISM_CATEGORY
                emitted += 1
                written.add(node_id)
                if (
                    self._taxon_dispositions is not None
                    and original_id != node_id
                    and (alias := self._taxon_dispositions.aliases.evidence_for(original_id)) is not None
                ):
                    # The finite selected authority supplies a real target
                    # declaration when GOLD has none; the old taxon's literal
                    # declaration stays in the alias audit, not on the new ID.
                    selected = json.loads(alias["selected_declaration_json"])["row"]
                    writer.writerow([selected.get(column, "") for column in self.node_header])
                    continue
                writer.writerow(
                    [
                        node_id,
                        category,
                        row.get("name", ""),
                        "",  # description — not supplied upstream
                        row.get("xref", ""),
                        row.get("provided_by", "") or f"infores:{GOLD}",
                        "",  # synonym
                        "",  # deprecated
                        "",  # same_as
                    ]
                )
        print(f"[gold] nodes emitted: {emitted:,}" + (f" (dropped {removed:,})" if removed else ""))
        if newly_orphaned:
            print(f"[gold]   {newly_orphaned:,} nodes were left edgeless by the trim and cleaned up")
        if remapped_collisions:
            print(
                f"[gold]   {remapped_collisions:,} node(s) collapsed onto an existing id after the retired-taxid remap"
            )
        self._report_orphans(pre_existing_orphans, emitted)

    @staticmethod
    def _report_orphans(orphans: set, emitted: int) -> None:
        """
        Report nodes that were already edgeless upstream.

        The upstream payload is 26.5% orphans, essentially all ``MaterialSample``.
        Whether to drop them is a modelling decision for GOLD, so this surfaces
        the number rather than taking it — unlike the orphaning the trim causes,
        which is ours and is cleaned up.

        :param orphans: IDs that had no edge in the upstream payload.
        :param emitted: Total nodes written.
        """
        if not orphans:
            return
        by_prefix: dict = {}
        for node_id in orphans:
            prefix = node_id.split(":")[0]
            by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        top = ", ".join(f"{k}={v:,}" for k, v in sorted(by_prefix.items(), key=lambda kv: -kv[1])[:4])
        print(
            f"[gold] WARNING: {len(orphans):,} of {emitted:,} emitted nodes ({100 * len(orphans) / emitted:.1f}%) "
            f"had no incident edge upstream — {top}. See docs/GOLD_TRANSFORM_REVIEW.md; dropping them is a "
            "modelling decision for GOLD, not taken here."
        )
