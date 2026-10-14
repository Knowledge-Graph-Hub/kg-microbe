"""
Ontologies-stubs transform.

KG-Microbe deliberately does NOT load the full NCIT, MESH, BTO, PO, or MICRO
ontologies — those would each add thousands of unrelated nodes for what is in
practice a small per-mapping reference footprint. But the chemical-mapping
consolidator and the BacDive isolation-source mapper reference ~73 distinct
NCIT IDs, ~95 distinct mesh IDs, a handful of distinct BTO/PO IDs, and
~34 distinct MICRO IDs (across ~150 total reference rows) as canonical
xrefs for ingredients, growth media, plant-anatomy isolation sources, and
microbial conditions (e.g. ``NCIT:C29298 'Oatmeal'``, ``mesh:D011136 'Tween'``,
``PO:0009046 'flower'``, ``MICRO:0000082 'nutrient broth'``). Without this
transform those CURIEs would appear as dangling node ids in the merged KG:
edges point at them but no node row carries the label.

This transform:

1. Calls :func:`~kg_microbe.utils.stub_curie_collection.collect_stub_curies` to
   discover every NCIT / mesh / BTO / PO / MICRO CURIE referenced anywhere
   under ``mappings/``.
2. For each prefix, dispatches on
   ``STUB_ONTOLOGY_SOURCES[prefix]["source_type"]``:

   * ``"semsql"`` — NCIT, mesh, BTO. Queries the local SemSQL DB
     (``data/raw/{ncit,mesh,bto}.db``) via OAK and emits one labelled
     stub node per referenced CURIE; no edges. The mesh entry sets
     ``db_prefix = "MESH"`` to bridge the casing gap between our
     lowercase ``mesh:`` mapping ids and the DB's uppercase ``MESH:``
     subject form.
   * ``"owl_mireot"`` — PO, MICRO. Runs ``robot extract --method MIREOT``
     against the source OWL (``data/raw/{po,micro}.owl`` from
     ``download.yaml``) under a curated upper term and parses the
     resulting OBO Graph JSON. Emits both nodes (stubs + ancestors up
     to the upper term, with label/synonyms/xrefs) and ``biolink:subclass_of``
     edges (one per is_a axiom in the module). MICRO's two IRI shapes
     — standard ``obo/MICRO_xxxx`` and legacy ``obo/MicrO.owl/MICRO_xxxx``
     — are handled by passing both forms to ROBOT for every lower term.
     Both OWLs are pinned together with the modules they import, which
     resolve through a local catalog while ROBOT runs with network access
     refused.

3. Writes per-ontology TSVs to
   ``data/transformed/ontologies_stubs/{ncit,mesh,bto,po,micro}_nodes.tsv``
   carrying the canonical KGX node columns. For PO and MICRO,
   ``{po,micro}_edges.tsv`` is also written with the canonical KGX edge
   columns.

Note for downstream consumers: if a KG built with this transform is ever
merged with a kg-microbe-biomedical KG that loads any of these ontologies
fully, biolink merge semantics will union nodes — the stub node here is a
strict subset of what the full ontology would emit (label/synonym/xref +
optional rdfs:subClassOf ancestors), so the union will simply pick the
fuller record.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from xml.sax.saxutils import quoteattr

from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    KNOWLEDGE_ASSERTION,
    MICRO_IMPORT_MODULES,
    MICRO_IMPORTS_DIR,
    PO_IMPORT_MODULES,
    PO_IMPORTS_DIR,
    PO_VERSION_IRI,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.ontologies_stubs.ncit_category_projection import (
    REVIEWED_CATEGORIES,
    native_contract,
    project_category,
    read_dispositions,
    validate_native_contract,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.atomic_io import gunzip_beside
from kg_microbe.utils.isolation_source_mapping_utils import STUB_ONTOLOGY_CATEGORY
from kg_microbe.utils.robot_utils import initialize_robot, missing_robot, offline_robot_env
from kg_microbe.utils.stub_curie_collection import (
    DEFAULT_MAPPING_PATHS,
    collect_stub_curies,
)
from kg_microbe.utils.stub_curie_collection import (
    REPO_ROOT as _STUB_REPO_ROOT,
)
from kg_microbe.utils.tsv_io import tsv_writer

# Stub ontologies handled by this transform. Each entry maps the canonical
# CURIE prefix (case-sensitive — must match how the prefix appears in
# existing mapping rows) to the per-source configuration.
#
# source_type controls how the stub nodes (and optional subclass-of edges)
# are produced:
#
#   * "semsql"         — OAK `sqlite:` adapter against a bbop-sqlite SemSQL DB
#                        (decompressed from a sibling .db.gz on demand). Emits
#                        ``{prefix}_nodes.tsv`` only — no hierarchy.
#   * "semsql_mireot"  — same SemSQL DB, but the transform walks
#                        ``rdfs:subClassOf`` ancestors of every stub via OAK,
#                        stopping (inclusively) at any of the curated
#                        ``upper_terms``. Emits both ``{prefix}_nodes.tsv``
#                        (stubs + ancestors) AND ``{prefix}_edges.tsv``
#                        (one ``biolink:subclass_of`` edge per walked parent).
#                        No ROBOT/OWL needed. Used for NCIT, which has the
#                        SemSQL DB already and a heterogeneous stub set that
#                        a single MIREOT upper_term cannot cover.
#   * "owl_mireot"     — ROBOT `extract --method MIREOT` against the source OWL
#                        under a curated ``upper_term``. Emits both
#                        ``{prefix}_nodes.tsv`` (stubs + ancestors up to the
#                        upper term, with labels/synonyms/xrefs from the module)
#                        AND ``{prefix}_edges.tsv`` (one ``biolink:subclass_of``
#                        edge per is_a axiom in the module). Used for PO and
#                        MICRO — the two ontologies whose mapped CURIEs sit in
#                        coherent rdfs:subClassOf subtrees and gain real
#                        downstream value from carrying their ancestor chain.
#   * "mesh_nt_rdf"    — streaming walk of the NLM MeSH N-Triples RDF
#                        (``mesh2026.nt.gz``). Captures ``rdfs:label`` and
#                        the mesh-specific parent predicates
#                        ``meshv:broaderDescriptor`` (D→D),
#                        ``meshv:preferredMappedTo`` (C→D main), and
#                        ``meshv:mappedTo`` (C→D fallback). DescriptorQualifierPair
#                        IRIs like ``D012694Q000031`` are collapsed to their D
#                        component on edge targets but excluded from labels
#                        (so ``"Serine/agonists"`` never shadows ``"Serine"``).
#                        Used only for mesh because the bbop-sqlite distribution
#                        strips C-record relationships entirely.
#
# Optional fields per entry:
#
#   * ``db_prefix`` — CURIE prefix to use when querying the source DB if it
#     differs from the canonical/output prefix (e.g. mesh.db stores rows as
#     ``MESH:Cxxxx`` but our mappings emit ``mesh:Cxxxx``). Defaults to the
#     canonical prefix when absent.
#   * ``upper_term`` (owl_mireot only) — CURIE of the upper term passed to
#     ROBOT MIREOT. Bounds how far the ancestor chain is walked; pick the
#     tightest concept that still covers all referenced stubs.
#   * ``upper_terms`` (semsql_mireot only) — list of CURIEs at which the
#     ancestor walk stops. Necessary when no single upper_term covers all
#     stubs (NCIT's stub set spans drugs/foods/organisms/specimens/etc).
#   * ``owl_filename`` (owl_mireot only) — local filename of the OWL under
#     ``input_base_dir``. Must be declared in ``download.yaml``.
#   * ``nt_filename`` (mesh_nt_rdf only) — local filename of the gzipped
#     N-Triples RDF under ``input_base_dir``. Must be declared in
#     ``download.yaml``.
#   * ``imports_dir`` / ``import_modules`` (owl_mireot only) — directory under
#     ``input_base_dir`` holding a pinned local copy of every ``owl:imports``
#     module the OWL declares, and the file names the pin downloads there (all
#     in ``download.yaml`` at the OWL's own pin). ROBOT resolves the imports
#     through a catalog mapping each to its copy and runs with network access
#     refused, so an unmapped import fails instead of being fetched. Preflight
#     fails if a module is missing or the OWL's imports differ from the list.
#     Without these ROBOT would fetch imports live, so every owl_mireot source
#     sets them (a test checks).
#   * ``version_iri`` (owl_mireot only, optional) — the ``owl:versionIRI`` the
#     pinned OWL must declare. Preflight fails on any other, so a file left
#     from an earlier release is not used just because it is on disk.
STUB_ONTOLOGY_SOURCES: Dict[str, Dict[str, Any]] = {
    "NCIT": {
        # NCI Thesaurus. ~73 stubs spanning drugs/antibiotics, foods,
        # body-fluid specimens, organisms, procedures, devices, qualifiers,
        # and findings — too heterogeneous for a single MIREOT upper term.
        # A greedy set-cover over the stubs' rdfs:subClassOf ancestors
        # yields 9 upper-terms that collectively partition the set into
        # disjoint subtrees; the walk under those upper_terms produces a
        # ~207-node / ~213-edge module that connects every stub to one of
        # the 9 mid-level NCIT concepts. We use semsql_mireot (not
        # owl_mireot) because ncit.db is already downloaded as part of the
        # stub-import set, while ncit.owl is ~250 MB and we don't need any
        # of its non-subClassOf axioms.
        "source_type": "semsql_mireot",
        "db_filename": "ncit.db",
        "upper_terms": [
            "NCIT:C1908",  # Drug, Food, Chemical or Biomedical Material  (48 stubs)
            "NCIT:C20181",  # Conceptual Entity                              (9)
            "NCIT:C14250",  # Organism                                       (5)
            "NCIT:C20189",  # Property or Attribute                          (5)
            "NCIT:C12219",  # Anatomic Structure, System, or Substance       (2)
            "NCIT:C3367",  # Finding                                        (1, Lesion)
            "NCIT:C26548",  # Gene Product                                   (1, Calprotectin)
            "NCIT:C43431",  # Activity                                       (1, Biopsy Procedure)
            "NCIT:C97325",  # Manufactured Object                            (1, Catheter Device)
        ],
        "knowledge_source": "infores:ncit",
    },
    "mesh": {
        # MeSH RDF — NLM's authoritative N-Triples distribution. We need
        # this (not the bbop-sqlite mesh.db) because the bbop-sqlite build
        # strips every relationship for C* supplementary concept records,
        # which make up 79 of our 95 mesh stubs. The .nt.gz carries the
        # full hierarchy via three predicates:
        #   * meshv:broaderDescriptor  — D → D (descriptor taxonomy)
        #   * meshv:preferredMappedTo  — C → D (SCR "main parent")
        #   * meshv:mappedTo           — C → D / D-Q pair (fallback)
        # All 95 stubs reach an asserted root via this walk; the resulting
        # module is ~384 nodes / ~460 edges. DescriptorQualifierPair
        # targets like ``D012694Q000031`` collapse to ``D012694`` for the
        # edge target so the merged KG lands on a real Descriptor that
        # carries its own broader chain.
        "source_type": "mesh_nt_rdf",
        "nt_filename": "mesh2026.nt.gz",
        "knowledge_source": "infores:mesh",
    },
    "BTO": {
        # BRENDA Tissue Ontology. Only ~2 CURIEs in current kg-microbe
        # mappings (wound fluid from BacDive isolation_source; cell lysate
        # added by the MIM 2026-05-18 republish). Both attach to BTO via
        # partonomic relations (RO:0004030, BFO:0000050) not rdfs:subClassOf,
        # so MIREOT would yield empty modules — semsql label-only path is
        # the right fit here.
        "source_type": "semsql",
        "db_filename": "bto.db",
        "knowledge_source": "infores:bto",
    },
    "PO": {
        # Plant Ontology. ~6 CURIEs in current kg-microbe mappings
        # (bark, rhizome, flower, stem, plant sap, leaf epidermis) all
        # under PO:0025131 (plant anatomical entity). MIREOT extracts
        # ~21 nodes (the 6 stubs + 15 ancestors) into a coherent local
        # subtree rooted at the upper term.
        #
        # po.owl imports two modules by unversioned IRI; they are pinned with
        # it to one release (PO_RELEASE) and resolved offline, and preflight
        # checks po.owl is that release.
        "source_type": "owl_mireot",
        "owl_filename": "po.owl",
        "imports_dir": PO_IMPORTS_DIR,
        "import_modules": PO_IMPORT_MODULES,
        "version_iri": PO_VERSION_IRI,
        "upper_term": "PO:0025131",
        "knowledge_source": "infores:po",
    },
    "MICRO": {
        # Microbial Conditions Ontology (Carrine Blank's MicrO). ~34
        # distinct CURIEs (~150 total references from chemical/ingredient
        # mappings) — nutrient broth, tryptic soy agar, peptone, etc.
        # All sit under MICRO:0000031 (fermentation product), which also
        # encompasses culture media and medium ingredients. MIREOT
        # extracts ~55 nodes / ~54 subClassOf edges rooted there.
        #
        # MicrO uses two IRI shapes for the same CURIE:
        #   http://purl.obolibrary.org/obo/MICRO_xxxx        (standard)
        #   http://purl.obolibrary.org/obo/MicrO.owl/MICRO_xxxx  (legacy)
        # `_run_mireot_extract` passes both forms to ROBOT for every lower
        # term so neither shape is silently dropped.
        #
        # MicrO.owl imports 20 modules from MicrO's master branch by IRI; they
        # are pinned with it (MICRO_COMMIT) and resolved offline.
        "source_type": "owl_mireot",
        "owl_filename": "micro.owl",
        "imports_dir": MICRO_IMPORTS_DIR,
        "import_modules": MICRO_IMPORT_MODULES,
        "upper_term": "MICRO:0000031",
        "knowledge_source": "infores:micro",
    },
}

# Cap any single cell value (label, synonym, xref) at this many characters
# before pipe-joining. MICRO occasionally carries multi-kilobyte marketing
# datasheets as synonyms (see MICRO:0001365 'lactalbumin hydrolysate') which
# otherwise produce TSV rows with embedded newlines that downstream parsers
# (awk, naive KGX readers) misinterpret as record separators.
_MAX_CELL_LEN = 500

ONTOLOGIES_STUBS_SOURCE_NAME = "ontologies_stubs"
NCIT_CATEGORY_DISPOSITIONS = _STUB_REPO_ROOT / "mappings/ncit_category_dispositions.tsv"


class OntologiesStubsTransform(Transform):
    """Emit one labelled stub node per referenced NCIT / mesh / BTO / PO / MICRO CURIE."""

    #: Derived from the collector's own list rather than restated, so the two
    #: cannot drift (#839). Hand-maintaining it declared 1 of the 11 files this
    #: transform reads, which made `kgm-freshness-check` — which consults
    #: nothing but `DATA_INPUTS` — report the output fresh after a change to any
    #: of the other ten. That is the #812 blind spot, and this was the last
    #: transform still carrying it.
    #:
    #: Note this makes the SSSOM dependency visible: `DEFAULT_MAPPING_PATHS[0]`
    #: is the unified mapping set, so `ontologies_stubs` is *not* independent of
    #: an incoming MIM release, which the one-file declaration implied it was.
    #: Paths outside the repo are skipped rather than raising. This runs at
    #: class-definition time, so `relative_to` raising would surface as an
    #: ImportError from a tuple comprehension — breaking every importer, and
    #: pointing nowhere near the entry that caused it (#841). An out-of-repo
    #: path is not git-checkable anyway, so dropping it loses no signal.
    DATA_INPUTS = ("mappings/ncit_category_dispositions.tsv",) + tuple(
        sorted(
            path.relative_to(_STUB_REPO_ROOT).as_posix()
            for path in DEFAULT_MAPPING_PATHS
            if path.is_relative_to(_STUB_REPO_ROOT)
        )
    )
    #: Finalization reads the ontologies output's declarations, so CHEBI terms
    #: MicrO's edges reference are not declared again here (#1511).
    TRANSFORM_INPUTS = ("ontologies",)

    @classmethod
    def missing_prerequisites(cls, input_dir: Optional[Path] = None) -> List[str]:
        """
        Report a missing pinned ROBOT, java, pinned import module or pinned release, or an unusable ncit.db.

        ROBOT builds the PO and MICRO hierarchies, and their imports must be
        on disk because they are no longer fetched; any of these missing used
        to fail only after the hours-long ontologies source. ``ncit.db`` gets the
        ontologies source's check: this source reads an existing copy as it is, so
        one left beside a newer ``ncit.db.gz`` would be read silently (#1536).
        """
        from kg_microbe.utils.release_preflight import ncit_authority_problems

        raw_dir = Path(input_dir) if input_dir else cls.DEFAULT_INPUT_DIR
        problems = missing_robot(raw_dir)
        for prefix, cfg in STUB_ONTOLOGY_SOURCES.items():
            if "imports_dir" in cfg:
                problems += _pinned_import_problems(prefix, cfg, raw_dir)
        return problems + ncit_authority_problems(raw_dir)

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Instantiate transform.

        :param input_dir: Where the SemSQL DBs live (defaults to ``data/raw/``).
        :param output_dir: Where ``ontologies_stubs/{ncit,mesh}_nodes.tsv`` are
            written (defaults to ``data/transformed/``).
        """
        super().__init__(ONTOLOGIES_STUBS_SOURCE_NAME, input_dir, output_dir)

    def begin_consumed_inputs(self):
        """Start the native authority guard afresh only when a new producer run begins."""
        super().begin_consumed_inputs()
        self._ncit_category_authority_admission = None
        self.producer_native_inputs = {"version": 1, "authority": None}

    def run(self, data_file=None, **kwargs) -> None:  # noqa: D401 — base class signature
        """
        Collect stub CURIEs and emit per-ontology node (and, where configured, edge) TSVs.

        Dispatches per :data:`STUB_ONTOLOGY_SOURCES` ``source_type``:

        * ``semsql`` — :meth:`_write_stub_nodes_from_semsql` writes
          ``{prefix}_nodes.tsv`` only.
        * ``semsql_mireot`` — :meth:`_write_stub_module_from_semsql_walk`
          writes ``{prefix}_nodes.tsv`` AND ``{prefix}_edges.tsv`` after
          walking ``rdfs:subClassOf`` ancestors via OAK to the curated
          ``upper_terms``.
        * ``owl_mireot`` — :meth:`_write_stub_module_from_mireot` writes
          ``{prefix}_nodes.tsv`` AND ``{prefix}_edges.tsv`` after running
          ``robot extract --method MIREOT`` against the source OWL.

        :param data_file: Unused (kept for the base-class signature). The
            transform discovers its inputs from the mapping TSVs and the
            input files in ``input_base_dir``.
        :param kwargs: Absorbs forward-compatible kwargs (e.g. ``show_status``)
            that the transform dispatcher in ``kg_microbe.transform.transform``
            passes to non-ontologies transforms. The stub transform has no
            progress bar to toggle, so the flag is intentionally ignored.
        """
        prefixes = list(STUB_ONTOLOGY_SOURCES.keys())
        curies_by_prefix = collect_stub_curies(prefixes)

        for prefix, curies in curies_by_prefix.items():
            cfg = STUB_ONTOLOGY_SOURCES[prefix]
            source_type = cfg.get("source_type", "semsql")
            sorted_curies = sorted(curies)
            if source_type == "owl_mireot":
                self._write_stub_module_from_mireot(
                    prefix=prefix,
                    curies=sorted_curies,
                    owl_path=self.input_base_dir / cfg["owl_filename"],
                    upper_term=cfg["upper_term"],
                    knowledge_source=cfg["knowledge_source"],
                    imports_dir=self.input_base_dir / cfg["imports_dir"] if "imports_dir" in cfg else None,
                )
            elif source_type == "semsql_mireot":
                self._write_stub_module_from_semsql_walk(
                    prefix=prefix,
                    curies=sorted_curies,
                    db_path=self.input_base_dir / cfg["db_filename"],
                    upper_terms=cfg["upper_terms"],
                    knowledge_source=cfg["knowledge_source"],
                )
            elif source_type == "mesh_nt_rdf":
                self._write_stub_module_from_mesh_nt(
                    prefix=prefix,
                    curies=sorted_curies,
                    nt_path=self.input_base_dir / cfg["nt_filename"],
                    knowledge_source=cfg["knowledge_source"],
                )
            else:
                self._write_stub_nodes_from_semsql(
                    prefix=prefix,
                    curies=sorted_curies,
                    db_path=self.input_base_dir / cfg["db_filename"],
                    knowledge_source=cfg["knowledge_source"],
                    output_file=self.output_dir / f"{prefix.lower()}_nodes.tsv",
                )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _write_stub_nodes_from_semsql(
        self,
        prefix: str,
        curies: List[str],
        db_path: Path,
        knowledge_source: str,
        output_file: Path,
    ) -> None:
        """Fetch label/synonyms/xrefs per CURIE via OAK SemSQL and write the node TSV."""
        if not curies:
            print(f"  [{prefix}] no CURIEs to import; skipping {output_file.name}")
            # Write an empty file with header so the merge step doesn't fail
            # on a missing file declared in merge.yaml.
            self._write_node_file(output_file, [])
            return

        adapter = self._open_adapter(prefix, db_path)
        if adapter is None:
            detail = (
                f"expected SemSQL DB at {db_path} (or sibling {db_path.name}.gz "
                f"to auto-decompress). Run `poetry run kg download` to fetch it."
            )
            raise FileNotFoundError(
                f"OAK adapter for {prefix} could not be opened: {detail} The stub "
                f"transform refuses to silently emit unlabelled nodes — that would "
                f"reintroduce the dangling-xref hazard this transform exists to fix."
            )

        db_prefix = STUB_ONTOLOGY_SOURCES.get(prefix, {}).get("db_prefix", prefix)
        rows: List[List[Optional[str]]] = []
        missing: List[str] = []
        for curie in curies:
            # mesh.db keys subjects under MESH: even though our mappings use
            # lowercase mesh:. Query under db_prefix; emit under canonical prefix.
            db_curie = _retag_curie(curie, prefix, db_prefix)
            label, synonyms, xrefs = self._fetch_metadata(adapter, db_curie)
            if not label:
                # Last-resort fallback: use the CURIE as the name. Log it so
                # curators can chase down obsolete or missing entries upstream.
                missing.append(curie)
                label = curie
            row = [
                curie,  # id (canonical prefix)
                self._reviewed_ncit_category(adapter, db_curie, label),  # category
                label,  # name
                None,  # description
                _join_pipe(xrefs),  # xref
                ONTOLOGIES_STUBS_SOURCE_NAME,  # provided_by
                _join_pipe(synonyms),  # synonym
                None,  # deprecated
                None,  # same_as
            ]
            rows.append(row)

        if self._ncit_category_authority_admission is not None:
            self.verify_consumed_inputs()
        self._write_node_file(output_file, rows)
        print(
            f"  [{prefix}] wrote {len(rows)} stub nodes to {output_file.name} "
            f"(knowledge_source={knowledge_source}, missing labels: {len(missing)})"
        )
        if missing:
            print(f"  [{prefix}] CURIEs with no SemSQL label (used CURIE as name): {missing}")

    def _write_stub_module_from_mireot(
        self,
        prefix: str,
        curies: List[str],
        owl_path: Path,
        upper_term: str,
        knowledge_source: str,
        imports_dir: Optional[Path],
    ) -> None:
        """
        Build a MIREOT module under ``upper_term`` and emit its nodes + subClassOf edges.

        Uses ROBOT ``extract --method MIREOT`` against ``owl_path`` to get a
        small ontology module containing the stub CURIEs plus their ancestor
        chain up to ``upper_term``. The resulting OBO Graph JSON is parsed
        for:

        * **Nodes**: every class whose CURIE prefix matches ``prefix`` (i.e.
          the target ontology — cross-ontology classes MIREOT pulls in for
          structural reasons are left for their own ontology transform to
          define). Label/synonyms/xrefs come straight from the module
          annotations (no second adapter call).
        * **Edges**: every is_a axiom whose subject is in ``prefix`` and
          whose object is *not* in BFO or owl: (those upper-ontology
          targets are not loaded in the merged KG and would dangle).
          Cross-ontology objects (e.g. ``UBERON:0001062``) are kept — the
          merged KG has them.
        """
        nodes_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
        edges_file = self.output_dir / f"{prefix.lower()}_edges.tsv"

        if not curies:
            print(f"  [{prefix}] no CURIEs to import; writing empty {nodes_file.name} / {edges_file.name}")
            self._write_node_file(nodes_file, [])
            self._write_edge_file(edges_file, [])
            return

        if not owl_path.is_file():
            raise FileNotFoundError(
                f"MIREOT extraction for {prefix} needs {owl_path} on disk. Run `poetry run kg download` to fetch it."
            )

        module_json = self._run_mireot_extract(
            prefix=prefix,
            lower_curies=curies,
            upper_curie=upper_term,
            owl_path=owl_path,
            imports_dir=imports_dir,
        )

        node_rows, edge_rows, foreign_targets, dropped_lower = self._parse_mireot_module(
            prefix=prefix,
            module_json=module_json,
            knowledge_source=knowledge_source,
            requested_curies=curies,
        )

        self._write_node_file(nodes_file, node_rows)
        self._write_edge_file(edges_file, edge_rows)

        print(
            f"  [{prefix}] wrote {len(node_rows)} nodes / {len(edge_rows)} edges "
            f"to {nodes_file.name} / {edges_file.name} "
            f"(knowledge_source={knowledge_source}, upper_term={upper_term}, "
            f"edges to other ontologies: {len(foreign_targets)})"
        )
        if dropped_lower:
            print(
                f"  [{prefix}] CURIEs requested but missing from module "
                f"(no path to upper_term {upper_term} or unknown to ROBOT): {dropped_lower}"
            )

    def _run_mireot_extract(
        self,
        prefix: str,
        lower_curies: List[str],
        upper_curie: str,
        owl_path: Path,
        imports_dir: Optional[Path],
    ) -> Path:
        """
        Run ``robot extract --method MIREOT`` and convert the result to OBO Graph JSON.

        Writes intermediate ``.owl`` (RDF/XML) and ``.json`` files into ``self.output_dir``
        so they're available for inspection if the module needs auditing. With
        ``imports_dir`` the OWL's imports resolve through a local catalog
        (:func:`_write_import_catalog`), and ROBOT runs with network access
        refused, so an import the catalog misses fails instead of being fetched.
        ``imports_dir`` has no default: leaving it out must not quietly bring the
        network back.
        """
        # The pinned ROBOT from the raw directory, as the ontologies transform
        # runs it; a PATH `robot` may be another version (#986 was 1.9.6).
        problems = missing_robot(self.input_base_dir)
        if problems:
            raise FileNotFoundError(f"Required to build the {prefix} stub hierarchy via MIREOT: {' '.join(problems)}")
        robot_file, env = initialize_robot(str(self.input_base_dir))

        lower_iris: List[str] = []
        for c in lower_curies:
            lower_iris.extend(_curie_to_iris(c))
        upper_iris = _curie_to_iris(upper_curie)

        lower_terms_file = self.output_dir / f"{prefix.lower()}_mireot_lower.txt"
        lower_terms_file.write_text("\n".join(lower_iris) + "\n", encoding="utf-8")
        # RDF/XML, not functional syntax. ROBOT 1.9.6 writes an `.ofn` it then
        # cannot parse back once the module carries MICRO literals with
        # embedded newlines and a `™` -- every OWLAPI parser rejects it and the
        # convert step fails with INVALID ONTOLOGY FILE ERROR. RDF/XML round-
        # trips the same content (#986).
        module_owl = self.output_dir / f"{prefix.lower()}_mireot_module.owl"
        module_json = self.output_dir / f"{prefix.lower()}_mireot_module.json"
        # The superseded intermediate: leaving the unparsable file beside the
        # parseable one says nothing about which is current (#988).
        module_owl.with_suffix(".ofn").unlink(missing_ok=True)

        extract_cmd: List[str] = [
            "bash",
            robot_file,
            "extract",
            "--method",
            "MIREOT",
            "--input",
            str(owl_path),
            "--lower-terms",
            str(lower_terms_file),
        ]
        for iri in upper_iris:
            extract_cmd += ["--upper-term", iri]
        extract_cmd += ["--output", str(module_owl)]
        if imports_dir is not None:
            env = offline_robot_env(env)
        # The catalog holds absolute paths on this machine: keep it out of the
        # published output directory.
        with tempfile.TemporaryDirectory() as catalog_dir:
            if imports_dir is not None:
                catalog = _write_import_catalog(owl_path, imports_dir, Path(catalog_dir) / "catalog-v001.xml")
                extract_cmd += ["--catalog", str(catalog)]
            subprocess.run(extract_cmd, check=True, env=env)  # noqa: S603

        convert_cmd: List[str] = [
            "bash",
            robot_file,
            "convert",
            "--input",
            str(module_owl),
            "--output",
            str(module_json),
            "-f",
            "json",
        ]
        subprocess.run(convert_cmd, check=True, env=env)  # noqa: S603
        return module_json

    def _parse_mireot_module(
        self,
        prefix: str,
        module_json: Path,
        knowledge_source: str,
        requested_curies: List[str],
    ) -> Tuple[List[List[Optional[str]]], List[List[Optional[str]]], Set[str], List[str]]:
        """Return ``(node_rows, edge_rows, foreign_edge_targets, dropped_requested)``."""
        data = json.loads(module_json.read_text(encoding="utf-8"))

        node_rows: List[List[Optional[str]]] = []
        module_prefix_curies: Set[str] = set()
        for graph in data.get("graphs", []) or []:
            for node in graph.get("nodes", []) or []:
                curie = _iri_to_curie(node.get("id", ""))
                if not curie or curie.split(":", 1)[0] != prefix:
                    continue
                module_prefix_curies.add(curie)
                meta = node.get("meta") or {}
                synonyms = sorted(
                    {_sanitize(_val_or_str(s)) for s in (meta.get("synonyms") or []) if _val_or_str(s)} - {""}
                )
                xrefs = sorted({_sanitize(_val_or_str(x)) for x in (meta.get("xrefs") or []) if _val_or_str(x)} - {""})
                label = _sanitize(node.get("lbl") or "") or curie
                node_rows.append(
                    [
                        curie,
                        STUB_ONTOLOGY_CATEGORY,
                        label,
                        None,
                        _join_pipe(xrefs),
                        ONTOLOGIES_STUBS_SOURCE_NAME,
                        _join_pipe(synonyms),
                        None,
                        None,
                    ]
                )
        node_rows.sort(key=lambda r: r[0] or "")

        edge_rows: List[List[Optional[str]]] = []
        foreign_targets: Set[str] = set()
        for graph in data.get("graphs", []) or []:
            for edge in graph.get("edges", []) or []:
                if edge.get("pred") != "is_a":
                    continue
                sub = _iri_to_curie(edge.get("sub", ""))
                obj = _iri_to_curie(edge.get("obj", ""))
                if not sub or not obj:
                    continue
                if sub.split(":", 1)[0] != prefix:
                    continue
                # BFO and bare owl: targets are upper-ontology classes not
                # loaded in the merged KG. Dropping these edges avoids
                # dangling-object node ids without losing any modeling we'd
                # actually query against.
                obj_prefix = obj.split(":", 1)[0]
                if obj_prefix in ("BFO", "owl"):
                    continue
                if obj_prefix != prefix:
                    foreign_targets.add(obj)
                edge_rows.append(
                    [
                        sub,
                        SUBCLASS_PREDICATE,
                        obj,
                        RDFS_SUBCLASS_OF,
                        knowledge_source,
                        KNOWLEDGE_ASSERTION,
                        AUTOMATED_AGENT,
                    ]
                )
        edge_rows.sort(key=lambda r: ((r[0] or ""), (r[2] or "")))

        dropped = sorted(set(requested_curies) - module_prefix_curies)
        return node_rows, edge_rows, foreign_targets, dropped

    def _write_stub_module_from_semsql_walk(
        self,
        prefix: str,
        curies: List[str],
        db_path: Path,
        upper_terms: List[str],
        knowledge_source: str,
    ) -> None:
        """
        Build a stub hierarchy by walking ``rdfs:subClassOf`` via OAK SemSQL.

        Equivalent to ROBOT MIREOT for the subClassOf-only case: starting
        from each stub CURIE, follow direct parents until any of
        ``upper_terms`` is reached (inclusive — the upper-term itself is in
        the module). Emits ``{prefix}_nodes.tsv`` for stubs + walked ancestors
        (label/synonyms/xrefs fetched via the same adapter) and
        ``{prefix}_edges.tsv`` for the parent edges as ``biolink:subclass_of``.

        Used when (a) the SemSQL DB is already downloaded for this prefix,
        (b) the stub set is too heterogeneous for a single MIREOT
        upper_term, and (c) we don't need any non-subClassOf axioms that
        ROBOT MIREOT would otherwise preserve.
        """
        nodes_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
        edges_file = self.output_dir / f"{prefix.lower()}_edges.tsv"

        if not curies:
            print(f"  [{prefix}] no CURIEs to import; writing empty {nodes_file.name} / {edges_file.name}")
            self._write_node_file(nodes_file, [])
            self._write_edge_file(edges_file, [])
            return

        adapter = self._open_adapter(prefix, db_path)
        if adapter is None:
            raise FileNotFoundError(
                f"OAK adapter for {prefix} could not be opened: expected SemSQL DB at "
                f"{db_path} (or sibling {db_path.name}.gz to auto-decompress). Run "
                f"`poetry run kg download` to fetch it. The stub transform refuses to "
                f"silently emit unlabelled nodes — that would reintroduce the "
                f"dangling-xref hazard this transform exists to fix."
            )

        db_prefix = STUB_ONTOLOGY_SOURCES.get(prefix, {}).get("db_prefix", prefix)

        # BFS up rdfs:subClassOf, stopping inclusively at any upper term.
        upper_set = {_retag_curie(u, prefix, db_prefix) for u in upper_terms}
        visited: Set[str] = set()
        edges: List[Tuple[str, str]] = []
        frontier: List[str] = [_retag_curie(c, prefix, db_prefix) for c in curies]
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in upper_set:
                continue
            try:
                rels = list(adapter.outgoing_relationships(current, predicates=[RDFS_SUBCLASS_OF]))
            except Exception as error:
                self._refuse_database_failure(current, error)
                if current in REVIEWED_CATEGORIES:
                    self._consumed_input_error = str(error)
                    raise
                rels = []
            for _, parent in rels:
                edges.append((current, parent))
                if parent not in visited:
                    frontier.append(parent)

        # Emit nodes (translating back to canonical/output prefix).
        node_rows: List[List[Optional[str]]] = []
        missing_labels: List[str] = []
        for db_curie in sorted(visited):
            out_curie = _retag_curie(db_curie, db_prefix, prefix)
            label, synonyms, xrefs = self._fetch_metadata(adapter, db_curie)
            if not label:
                missing_labels.append(out_curie)
                label = out_curie
            node_rows.append(
                [
                    out_curie,
                    self._reviewed_ncit_category(adapter, db_curie, label),
                    label,
                    None,
                    _join_pipe(xrefs),
                    ONTOLOGIES_STUBS_SOURCE_NAME,
                    _join_pipe(synonyms),
                    None,
                    None,
                ]
            )

        # Emit edges (drop BFO / owl: upper-ontology targets).
        edge_rows: List[List[Optional[str]]] = []
        foreign_targets: Set[str] = set()
        for sub_db, obj_db in sorted(set(edges)):
            out_sub = _retag_curie(sub_db, db_prefix, prefix)
            out_obj = _retag_curie(obj_db, db_prefix, prefix)
            obj_prefix = out_obj.split(":", 1)[0] if ":" in out_obj else ""
            if obj_prefix in ("BFO", "owl"):
                continue
            if obj_prefix != prefix:
                foreign_targets.add(out_obj)
            edge_rows.append(
                [
                    out_sub,
                    SUBCLASS_PREDICATE,
                    out_obj,
                    RDFS_SUBCLASS_OF,
                    knowledge_source,
                    KNOWLEDGE_ASSERTION,
                    AUTOMATED_AGENT,
                ]
            )

        if self._ncit_category_authority_admission is not None:
            self.verify_consumed_inputs()
        self._write_node_file(nodes_file, node_rows)
        self._write_edge_file(edges_file, edge_rows)

        print(
            f"  [{prefix}] wrote {len(node_rows)} nodes / {len(edge_rows)} edges "
            f"to {nodes_file.name} / {edges_file.name} "
            f"(knowledge_source={knowledge_source}, upper_terms={len(upper_terms)}, "
            f"edges to other ontologies: {len(foreign_targets)}, missing labels: {len(missing_labels)})"
        )
        if missing_labels:
            print(f"  [{prefix}] CURIEs with no SemSQL label (used CURIE as name): {missing_labels[:10]}")

    def _write_stub_module_from_mesh_nt(
        self,
        prefix: str,
        curies: List[str],
        nt_path: Path,
        knowledge_source: str,
    ) -> None:
        """
        Build a mesh stub module by streaming the NLM N-Triples RDF.

        One pass over ``mesh2026.nt.gz`` (~15 M lines, ~17 s) captures every
        ``rdfs:label`` plus every mesh parent edge (``meshv:broaderDescriptor``,
        ``meshv:preferredMappedTo``, ``meshv:mappedTo``). BFS from each stub
        walks upward until the chain naturally terminates at a top-level
        Descriptor (mesh has no single owl:Thing equivalent; chains hit roots
        at depth ~8–10).

        DescriptorQualifierPair IRIs (``DxxxQyyy``) are excluded from labels
        (``"Serine/agonists"`` must not shadow ``"Serine"``) but collapsed
        to their D component on edge *targets* so the edge lands on a
        descriptor that has its own broader chain.
        """
        nodes_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
        edges_file = self.output_dir / f"{prefix.lower()}_edges.tsv"

        if not curies:
            print(f"  [{prefix}] no CURIEs to import; writing empty {nodes_file.name} / {edges_file.name}")
            self._write_node_file(nodes_file, [])
            self._write_edge_file(edges_file, [])
            return

        if not nt_path.is_file():
            raise FileNotFoundError(
                f"mesh N-Triples walk for {prefix} needs {nt_path} on disk. Run `poetry run kg download` to fetch it."
            )

        labels, parents = _stream_mesh_nt(nt_path)
        print(
            f"  [{prefix}] streamed {nt_path.name}: {len(labels):,} labels, {len(parents):,} records with parent edges"
        )

        # BFS from stubs upward (no explicit upper_terms — mesh chains
        # terminate at their asserted roots within ~10 hops).
        visited: Set[str] = set()
        edges: List[Tuple[str, str, str]] = []
        frontier = list(curies)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for parent_c, relation in parents.get(current, []):
                edges.append((current, parent_c, relation))
                if parent_c not in visited:
                    frontier.append(parent_c)

        # Emit nodes.
        missing_labels: List[str] = []
        node_rows: List[List[Optional[str]]] = []
        for c in sorted(visited):
            label = labels.get(c)
            if not label:
                missing_labels.append(c)
                label = c
            node_rows.append(
                [
                    c,
                    STUB_ONTOLOGY_CATEGORY,
                    _sanitize(label),
                    None,
                    "",
                    ONTOLOGIES_STUBS_SOURCE_NAME,
                    "",
                    None,
                    None,
                ]
            )

        # Emit edges (mesh is self-contained — no foreign-prefix targets to worry about).
        edge_rows: List[List[Optional[str]]] = []
        for sub, obj, relation in sorted(set(edges)):
            edge_rows.append(
                [
                    sub,
                    SUBCLASS_PREDICATE,
                    obj,
                    relation,
                    knowledge_source,
                    KNOWLEDGE_ASSERTION,
                    AUTOMATED_AGENT,
                ]
            )

        self._write_node_file(nodes_file, node_rows)
        self._write_edge_file(edges_file, edge_rows)

        dropped = sorted(set(curies) - visited)
        print(
            f"  [{prefix}] wrote {len(node_rows)} nodes / {len(edge_rows)} edges "
            f"to {nodes_file.name} / {edges_file.name} "
            f"(knowledge_source={knowledge_source}, "
            f"missing labels: {len(missing_labels)}, stubs without parents: {len(dropped)})"
        )
        if dropped:
            print(f"  [{prefix}] CURIEs with no parent edges in mesh RDF: {dropped[:10]}")

    def _open_adapter(self, prefix: str, db_path: Path):
        """
        Open an OAK SemSQL adapter for ``prefix``; return None if the DB is missing.

        OBO Foundry distributes SemSQL DBs as ``.db.gz`` and ``download.yaml``
        stores the gzipped form, so if the unzipped ``.db`` is missing but a
        sibling ``.db.gz`` is present, it is unpacked atomically and used. An
        existing ``.db`` is used as it is, whatever archive is beside it.
        """
        if prefix == "NCIT" and not db_path.resolve().is_relative_to(self.input_base_dir.resolve()):
            self._consumed_input_error = "NCIT category authority is outside the selected input directory"
            raise ValueError(self._consumed_input_error)
        if not db_path.is_file():
            gz_path = db_path.with_suffix(db_path.suffix + ".gz")
            if gz_path.is_file():
                if prefix == "NCIT" and not gz_path.resolve().is_relative_to(self.input_base_dir.resolve()):
                    self._consumed_input_error = "NCIT compressed authority is outside the selected input directory"
                    raise ValueError(self._consumed_input_error)
                print(f"  [{prefix}] decompressing {gz_path.name} → {db_path.name}")
                # Atomic and shared with the NCIT category authority, which can unpack
                # ncit.db first while the ontologies source finalizes (#1526).
                gunzip_beside(db_path)
            else:
                if prefix == "NCIT":
                    self._consumed_input_error = f"Selected NCIT native authority is missing: {db_path}"
                return None
        if prefix == "NCIT":
            self._bind_ncit_category_authority(db_path)
        try:
            from oaklib import get_adapter
        except ImportError as exc:  # pragma: no cover — oaklib is a dep
            raise RuntimeError(f"oaklib import failed while opening SemSQL adapter for {prefix}: {exc}") from exc
        try:
            return get_adapter(f"sqlite:{db_path}")
        except Exception as error:
            if prefix == "NCIT":
                self._consumed_input_error = str(error)
            raise

    def _bind_ncit_category_authority(self, db_path):
        """Bind the selected native DB after decompression, without copying binary authority."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        try:
            lexical = Path(db_path).absolute()
            path = lexical.resolve()
            if not path.is_relative_to(self.input_base_dir.resolve()):
                raise ValueError("NCIT category authority must stay inside the selected input directory")
            admission = getattr(self, "_ncit_category_authority_admission", None)
            freshly_captured = admission is None
            if admission is None:
                admission = SourceAdmission()
                identity = admission.capture(lexical)
                snapshot = {"path": str(path), "sha256": identity["sha256"]}
                previous = self._consumed_input_snapshots.setdefault("ncit_category_authority", snapshot)
                if previous != snapshot:
                    raise ValueError("NCIT category authority changed within one producer run")
                self.producer_native_inputs = native_contract(lexical, path, identity["sha256"])
                self._ncit_category_authority_admission = admission
            elif lexical not in admission.bindings or path not in admission.identities:
                raise ValueError("NCIT category authority selection changed within one producer run")
            self.verify_native_inputs(byte_verified=freshly_captured)
        except BaseException as error:
            self._consumed_input_error = str(error)
            raise

    def verify_native_inputs(self, *, byte_verified=False, output_dir=None):
        """Check native guards; only the byte-verifying consumed-input checkpoint may skip rehashing."""
        try:
            admission = validate_native_contract(
                self.producer_native_inputs,
                self.input_base_dir,
                self.consumed_input_snapshots,
                Path(self.output_dir if output_dir is None else output_dir) / "ncit_nodes.tsv",
                admission=self._ncit_category_authority_admission,
            )
            if self.producer_native_inputs["authority"] is not None:
                self._ncit_category_authority_admission = admission
            admission.verify(metadata_only=byte_verified)
        except BaseException as error:
            self._consumed_input_error = str(error)
            raise

    @classmethod
    def verify_recorded_native_inputs(cls, report, report_path, *, admission=None):
        """Verify saved NCIT provenance and retain locator/absence checks for public merge admission."""
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        if report_path is None:
            raise SourceFinalizationRequired("NCIT native authority validation requires its completion-record path")
        members = report.get("members", {})
        ncit_member = members.get("ncit_nodes.tsv")
        contract = report.get("producer_native_inputs")
        if isinstance(contract, dict) and contract.get("authority") is None and ncit_member is None:
            raise SourceFinalizationRequired("Null NCIT authority requires its canonical recorded output")
        return validate_native_contract(
            contract,
            report.get("raw_input_directory"),
            report.get("consumed_inputs", {}),
            Path(report_path).parent / "ncit_nodes.tsv",
            admission=admission,
            expected_member=ncit_member,
        )

    def _reviewed_ncit_category(self, adapter, curie, label):
        """Keep unknown concepts unchanged and fail closed on the two reviewed native projections."""
        if curie not in REVIEWED_CATEGORIES:
            return STUB_ONTOLOGY_CATEGORY
        try:
            if getattr(self, "_ncit_category_authority_admission", None) is None:
                raise ValueError("NCIT category projection requires a bound native authority")
            with self.consume_input("ncit_category_dispositions", NCIT_CATEGORY_DISPOSITIONS) as stream:
                disposition = read_dispositions(stream)[curie]
            if label != disposition["label"]:
                raise ValueError(f"NCIT emitted label differs from reviewed native evidence: {curie}")
            return project_category(adapter, curie, disposition)
        except BaseException as error:
            self._refuse_database_failure(curie, error)
            self._consumed_input_error = str(error)
            raise

    def _refuse_database_failure(self, curie: str, error: BaseException) -> None:
        """
        Fail this source when a lookup failed because the SemSQL database could not be read.

        A term the database lacks comes back with no label; looking it up raises nothing. A
        database error, or SQLite running out of memory, is not a missing term. Absorbed per
        term, it named the affected stubs by their identifiers, and the run exited 0 (#1604):
        every stub when another run's unpack replaced the file under this adapter (#1537,
        #1580), or when the file was damaged. ``SourceFinalizationRequired`` fails this source
        only, as ``bacdive``'s ancestry authority does for the same errors, and ``kg
        transform`` then skips the sources that depend on it.
        """
        from sqlalchemy.exc import SQLAlchemyError

        if isinstance(error, (sqlite3.Error, SQLAlchemyError, MemoryError)):
            from kg_microbe.utils.source_finalization import SourceFinalizationRequired

            self._consumed_input_error = str(error)
            raise SourceFinalizationRequired(
                f"ontologies_stubs cannot read the SemSQL database to look up {curie}: {error}"
            ) from error

    def _fetch_metadata(self, adapter, curie: str):
        """Return (label, synonyms_list, xrefs_list) for ``curie`` via the OAK adapter."""
        label = ""
        synonyms: Set[str] = set()
        xrefs: Set[str] = set()
        try:
            label = adapter.label(curie) or ""
        except Exception as error:  # noqa: S110 — obsolete CURIEs are expected to miss
            self._refuse_database_failure(curie, error)
            if curie in REVIEWED_CATEGORIES:
                self._consumed_input_error = str(error)
                raise
            pass
        try:
            synonyms = {s for s in adapter.entity_aliases(curie) if s}
        except Exception as error:  # noqa: S110
            self._refuse_database_failure(curie, error)
            if curie in REVIEWED_CATEGORIES:
                self._consumed_input_error = str(error)
                raise
            pass
        # Drop the canonical label out of the synonym set to keep them disjoint.
        synonyms.discard(label)
        try:
            metadata = adapter.entity_metadata_map(curie) or {}
        except Exception as error:  # noqa: S110
            self._refuse_database_failure(curie, error)
            if curie in REVIEWED_CATEGORIES:
                self._consumed_input_error = str(error)
                raise
            metadata = {}
        # OAK returns metadata keyed by short-form predicate. dbxref entries
        # land under "oio:hasDbXref" (or "oboInOwl:hasDbXref" on older
        # adapters). Accept both.
        for predicate_key in ("oio:hasDbXref", "oboInOwl:hasDbXref"):
            for value in metadata.get(predicate_key, []) or []:
                if value:
                    xrefs.add(str(value))
        # NCIT records CAS Registry Numbers in P210 rather than hasDbXref.
        # Preserve these direct source annotations in the output xref column;
        # they do not assert same_as or upgrade any MIM broadMatch relationship.
        for predicate_key in (
            "NCIT:P210",
            "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#P210",
        ):
            for value in metadata.get(predicate_key, []) or []:
                cas_xref = _cas_xref(value)
                if cas_xref:
                    xrefs.add(cas_xref)
        return (
            _sanitize(label),
            sorted({_sanitize(s) for s in synonyms} - {""}),
            sorted({_sanitize(x) for x in xrefs} - {""}),
        )

    def _write_node_file(self, path: Path, rows: Iterable[Iterable[Optional[str]]]) -> None:
        """Write ``rows`` to ``path`` using the canonical Transform node header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = tsv_writer(fh)
            writer.writerow(self.node_header)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])

    def _write_edge_file(self, path: Path, rows: Iterable[Iterable[Optional[str]]]) -> None:
        """Write ``rows`` to ``path`` using the canonical Transform edge header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = tsv_writer(fh)
            writer.writerow(self.edge_header)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])


def _cas_xref(value: Any) -> Optional[str]:
    """Convert a CAS annotation with valid syntax and check digit to a CURIE."""
    if not isinstance(value, str):
        return None
    registry_number = value.strip()
    if not re.fullmatch(r"[1-9][0-9]{1,6}-[0-9]{2}-[0-9]", registry_number):
        return None
    body, check_digit = registry_number.rsplit("-", 1)
    checksum = sum(position * int(digit) for position, digit in enumerate(reversed(body.replace("-", "")), 1))
    if checksum % 10 != int(check_digit):
        return None
    return f"cas:{registry_number}"


def _sanitize(value: Optional[str]) -> str:
    """Collapse internal whitespace and cap length so a single cell stays safe in TSV."""
    if not value:
        return ""
    # Replace any run of whitespace (incl. newlines, tabs) with a single space.
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if len(cleaned) > _MAX_CELL_LEN:
        cleaned = cleaned[: _MAX_CELL_LEN - 1].rstrip() + "…"
    return cleaned


def _join_pipe(values: Iterable[str]) -> str:
    """Pipe-join a sequence; return ``""`` when empty (matches existing TSV convention)."""
    items = [v for v in values if v]
    return "|".join(items) if items else ""


def _val_or_str(item: Any) -> str:
    """Pull a string out of either ``{'val': '…'}`` or a bare string; ``""`` otherwise."""
    if isinstance(item, dict):
        return str(item.get("val") or "")
    return str(item) if item else ""


def _retag_curie(curie: str, from_prefix: str, to_prefix: str) -> str:
    """Translate ``mesh:Cxxx`` → ``MESH:Cxxx`` (or no-op if prefixes match)."""
    if from_prefix == to_prefix:
        return curie
    if curie.startswith(from_prefix + ":"):
        return to_prefix + curie[len(from_prefix) :]
    return curie


# Match the local ID at the tail of an OBO Foundry IRI. Handles both the
# standard ``http://purl.obolibrary.org/obo/MICRO_0000082`` shape and MicrO's
# quirky ``http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0003152`` variant
# (both fall out of the trailing ``..._<local>`` match).
_OBO_LOCAL_ID_RE = re.compile(r"/([A-Za-z][A-Za-z0-9]*)_([A-Za-z0-9]+)$")


_OWL_IMPORT = re.compile(r"<owl:imports\s+rdf:resource=\"([^\"]*)\"")
_OWL_VERSION_IRI = re.compile(r"<owl:versionIRI\s+rdf:resource=\"([^\"]*)\"")
# Any `imports` element, whatever prefix it is written with (none = default namespace).
_ANY_IMPORT = re.compile(r"<([A-Za-z_][\w.-]*:)?imports[\s/>]")
_ABSOLUTE_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def _declared_imports(owl_path: Path) -> List[str]:
    """
    Return the ``owl:imports`` IRIs of an RDF/XML ontology, refusing spellings this cannot read.

    A text scan, not an RDF parse, so it refuses what it might misread: a file
    that is not RDF/XML, an import not written as ``owl:imports rdf:resource``
    (another prefix bound to OWL, OWL as the default namespace, a nested
    form), an IRI spelled with an XML entity or with no scheme (relative to an
    ``xml:base``); a catalog keyed on any of these would not match what OWLAPI
    requests. It gives early, specific errors; the guarantee that nothing is
    fetched comes from running ROBOT offline.

    :param owl_path: RDF/XML ontology.
    :return: Sorted distinct import IRIs.
    """
    text = owl_path.read_text(encoding="utf-8")
    if "<rdf:RDF" not in text:
        raise ValueError(f"{owl_path} is not RDF/XML, so its imports cannot be resolved offline")
    declared = _OWL_IMPORT.findall(text)
    other_prefixes = sorted({prefix for prefix in _ANY_IMPORT.findall(text) if prefix != "owl:"})
    if other_prefixes or text.count("<owl:imports") != len(declared):
        raise ValueError(
            f"{owl_path} declares imports in a form other than owl:imports rdf:resource "
            f"(prefixes seen: {other_prefixes or ['owl:']}); cannot resolve offline"
        )
    iris = sorted(set(declared))
    entity_iris = [iri for iri in iris if "&" in iri]
    if entity_iris:
        raise ValueError(f"{owl_path} spells imports with XML entities, which the catalog cannot match: {entity_iris}")
    relative = [iri for iri in iris if not _ABSOLUTE_IRI.match(iri)]
    if relative:
        raise ValueError(f"{owl_path} has relative import IRIs, which the catalog cannot match: {relative}")
    return iris


def _declared_version_iris(owl_path: Path) -> List[str]:
    """Return every ``owl:versionIRI`` an RDF/XML ontology declares (one, for a released ontology)."""
    return _OWL_VERSION_IRI.findall(owl_path.read_text(encoding="utf-8"))


def _import_file_name(iri: str) -> str:
    """Name the local copy of an import: the last path segment of its IRI, as ``download.yaml`` saves it."""
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _pinned_import_problems(prefix: str, cfg: Dict[str, Any], raw_dir: Path) -> List[str]:
    """
    Check one source's pinned imports before the batch: the OWL, its release, every module, and the import list.

    The run maps whatever the OWL declares; preflight checks the pinned list.
    If they drift, an import added by a new pin would pass preflight and fail
    only after the hours-long ontologies source. An OWL from another release
    can import the same modules, so where the pin names a release
    (``version_iri``) the OWL must declare it: `kg download` leaves a file it
    has no record of in place.
    """
    owl_path = raw_dir / cfg["owl_filename"]
    imports_dir = raw_dir / cfg["imports_dir"]
    fetch = "Run `poetry run kg download -t ontologies` to fetch them."
    if not owl_path.is_file():
        return [f"{prefix} ontology missing: {owl_path}. {fetch}"]
    problems = []
    absent = [name for name in cfg["import_modules"] if not (imports_dir / name).is_file()]
    if absent:
        problems.append(f"{prefix} import modules missing from {imports_dir}: {', '.join(absent)}. {fetch}")
    try:
        declared = {_import_file_name(iri) for iri in _declared_imports(owl_path)}
        versions = _declared_version_iris(owl_path) if "version_iri" in cfg else None
    except ValueError as exc:
        return problems + [f"{prefix}: {exc}"]
    if versions is not None and versions != [cfg["version_iri"]]:
        problems.append(
            f"{prefix} ontology is not the pinned release: {owl_path} declares versionIRI "
            f"{', '.join(versions) or 'none'}, not {cfg['version_iri']}. "
            "Delete it and run `poetry run kg download -t ontologies`."
        )
    pinned = set(cfg["import_modules"])
    if declared != pinned:
        problems.append(
            f"{prefix} imports and pin disagree: {owl_path.name} imports {sorted(declared - pinned)} "
            f"that the pin does not download, and the pin downloads {sorted(pinned - declared)} it does not import"
        )
    return problems


def _write_import_catalog(owl_path: Path, imports_dir: Path, catalog_path: Path) -> Path:
    """
    Write a ROBOT catalog mapping every ``owl:imports`` IRI in ``owl_path`` to its local copy.

    Without one, OWLAPI fetches each import from its IRI on every run, so an
    unpinned upstream branch decides what the module contains. Each IRI maps to
    the file named by its last path segment under ``imports_dir``; an import
    with no local copy, or one :func:`_declared_imports` cannot read, raises.

    :param owl_path: RDF/XML ontology whose imports are resolved.
    :param imports_dir: Directory holding the pinned import modules.
    :param catalog_path: Where to write the catalog.
    :return: ``catalog_path``.
    """
    local = {iri: imports_dir / _import_file_name(iri) for iri in _declared_imports(owl_path)}
    absent = [f"{iri} -> {path}" for iri, path in local.items() if not path.is_file()]
    if absent:
        raise FileNotFoundError(
            f"{owl_path.name} imports modules with no local copy (ROBOT would fetch them): {absent}. "
            "Pin and download them, or run `poetry run kg download -t ontologies`."
        )
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        '<catalog prefer="public" xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
        *(f"  <uri name={quoteattr(iri)} uri={quoteattr(path.resolve().as_uri())}/>" for iri, path in local.items()),
        "</catalog>",
    ]
    catalog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return catalog_path


def _curie_to_iris(curie: str) -> List[str]:
    """Return every known IRI shape for ``curie`` (handles MICRO's two-shape quirk)."""
    prefix, local = curie.split(":", 1)
    iris = [f"http://purl.obolibrary.org/obo/{prefix}_{local}"]
    if prefix == "MICRO":
        iris.append(f"http://purl.obolibrary.org/obo/MicrO.owl/{prefix}_{local}")
    return iris


def _iri_to_curie(iri: str) -> Optional[str]:
    """OBO IRI → ``PREFIX:local`` (or None if not OBO-shaped)."""
    m = _OBO_LOCAL_ID_RE.search(iri)
    return f"{m.group(1)}:{m.group(2)}" if m else None


# ---------------------------------------------------------------------------
# mesh N-Triples streaming
# ---------------------------------------------------------------------------

# Records: <http://id.nlm.nih.gov/mesh/[2026/]Cxxxxxx[Qyyyyyy]>
# Group 1: ``CD|M`` head + digits (the record local id).
# Group 2: optional ``Qyyyyyy`` qualifier suffix (DescriptorQualifierPair).
_MESH_IRI_RE = re.compile(r"http://id\.nlm\.nih\.gov/mesh/(?:\d{4}/)?([CDM]\d+)(Q\d+)?")

_MESH_PRED_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
_MESH_PRED_BROADER_DESCRIPTOR = "<http://id.nlm.nih.gov/mesh/vocab#broaderDescriptor>"
_MESH_PRED_PREFERRED_MAPPED_TO = "<http://id.nlm.nih.gov/mesh/vocab#preferredMappedTo>"
_MESH_PRED_MAPPED_TO = "<http://id.nlm.nih.gov/mesh/vocab#mappedTo>"
_MESH_HIERARCHY_PREDS: Dict[str, str] = {
    _MESH_PRED_BROADER_DESCRIPTOR: "meshv:broaderDescriptor",
    _MESH_PRED_PREFERRED_MAPPED_TO: "meshv:preferredMappedTo",
    _MESH_PRED_MAPPED_TO: "meshv:mappedTo",
}


def _mesh_iri_to_curie(iri: str, *, strict: bool) -> Optional[str]:
    """
    Return ``mesh:Cxxxxx`` / ``mesh:Dxxxxx`` for a NLM mesh IRI.

    ``strict=True`` refuses DescriptorQualifierPair IRIs (returns ``None``) —
    use this when capturing labels so ``"Serine/agonists"`` doesn't shadow
    ``"Serine"``. ``strict=False`` collapses DQ-pair IRIs to their D component
    — use this for edge targets so the edge lands on a real Descriptor that
    has its own ``broaderDescriptor`` chain.
    """
    m = _MESH_IRI_RE.search(iri)
    if not m:
        return None
    if strict and m.group(2):
        return None
    return f"mesh:{m.group(1)}"


def _parse_nt_line(line: str) -> Optional[Tuple[str, str, str]]:
    """
    Best-effort N-Triples splitter.

    Returns ``(subject_iri, predicate_token, object_token)`` on success or
    ``None`` on malformed input. The predicate token includes its surrounding
    ``<>`` so it can be compared by exact string match.
    """
    line = line.rstrip()
    if not line.endswith(" ."):
        return None
    line = line[:-2]
    if not line.startswith("<"):
        return None
    try:
        end_s = line.index("> ", 1)
    except ValueError:
        return None
    subject = line[1:end_s]
    rest = line[end_s + 2 :]
    if not rest.startswith("<"):
        return None
    try:
        end_p = rest.index("> ", 1)
    except ValueError:
        return None
    predicate = rest[: end_p + 1]
    obj = rest[end_p + 2 :].strip()
    return subject, predicate, obj


def _stream_mesh_nt(nt_gz_path: Path) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, str]]]]:
    """
    One-pass scan of the gzipped mesh N-Triples file.

    Returns ``(labels, parents)``:

      * ``labels``: ``mesh:CURIE -> str``, populated from ``rdfs:label``
        triples whose subject is NOT a DescriptorQualifierPair (DQ-pair
        labels are intentionally dropped — see :func:`_mesh_iri_to_curie`).
        ``@en`` labels are preferred; non-language-tagged literals are
        accepted only as fallback.
      * ``parents``: ``mesh:CURIE -> [(parent_mesh_curie, mesh_relation), ...]``,
        populated from the three hierarchy predicates in
        :data:`_MESH_HIERARCHY_PREDS`.

    The N-Triples file is ~1 GB uncompressed (~15 M lines, ~17 s on a
    laptop) but cheap-to-filter lines without one of our predicates account
    for >95% of the cost.
    """
    labels: Dict[str, str] = {}
    parents: Dict[str, List[Tuple[str, str]]] = {}
    with gzip.open(nt_gz_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            # Cheap pre-filter: skip lines that don't mention any predicate we care about.
            if _MESH_PRED_LABEL not in line and not any(p in line for p in _MESH_HIERARCHY_PREDS):
                continue
            parsed = _parse_nt_line(line)
            if not parsed:
                continue
            subj_iri, pred_tok, obj_tok = parsed
            if pred_tok == _MESH_PRED_LABEL:
                subj_curie = _mesh_iri_to_curie(subj_iri, strict=True)
                if not subj_curie:
                    continue
                if obj_tok.endswith("@en"):
                    val = obj_tok[1 : obj_tok.rindex("@") - 1]
                    labels[subj_curie] = val
                elif obj_tok.startswith('"'):
                    val = obj_tok[1 : obj_tok.rindex('"')]
                    labels.setdefault(subj_curie, val)
                continue
            relation = _MESH_HIERARCHY_PREDS.get(pred_tok)
            if not relation:
                continue
            subj_curie = _mesh_iri_to_curie(subj_iri, strict=True)
            if not subj_curie:
                continue
            obj_curie = _mesh_iri_to_curie(obj_tok, strict=False)
            if not obj_curie or obj_curie == subj_curie:
                continue
            parents.setdefault(subj_curie, []).append((obj_curie, relation))
    return labels, parents
