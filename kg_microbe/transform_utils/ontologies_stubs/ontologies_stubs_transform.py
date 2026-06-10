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

import csv
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    KNOWLEDGE_ASSERTION,
    RDFS_SUBCLASS_OF,
    SUBCLASS_PREDICATE,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.isolation_source_mapping_utils import STUB_ONTOLOGY_CATEGORY
from kg_microbe.utils.stub_curie_collection import collect_stub_curies

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
            "NCIT:C1908",   # Drug, Food, Chemical or Biomedical Material  (48 stubs)
            "NCIT:C20181",  # Conceptual Entity                              (9)
            "NCIT:C14250",  # Organism                                       (5)
            "NCIT:C20189",  # Property or Attribute                          (5)
            "NCIT:C12219",  # Anatomic Structure, System, or Substance       (2)
            "NCIT:C3367",   # Finding                                        (1, Lesion)
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
        "source_type": "owl_mireot",
        "owl_filename": "po.owl",
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
        "source_type": "owl_mireot",
        "owl_filename": "micro.owl",
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


class OntologiesStubsTransform(Transform):

    """Emit one labelled stub node per referenced NCIT / mesh / BTO / PO / MICRO CURIE."""

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
                STUB_ONTOLOGY_CATEGORY,  # category
                label,  # name
                None,  # description
                _join_pipe(xrefs),  # xref
                ONTOLOGIES_STUBS_SOURCE_NAME,  # provided_by
                _join_pipe(synonyms),  # synonym
                None,  # deprecated
                None,  # same_as
            ]
            rows.append(row)

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
    ) -> Path:
        """
        Run ``robot extract --method MIREOT`` and convert the result to OBO Graph JSON.

        Writes intermediate ``.ofn`` and ``.json`` files into ``self.output_dir``
        so they're available for inspection if the module needs auditing.
        """
        robot_bin = shutil.which("robot")
        if not robot_bin:
            raise RuntimeError(
                f"ROBOT binary not on PATH but required to build the {prefix} "
                "stub hierarchy via MIREOT. Install robot "
                "(http://robot.obolibrary.org/) and ensure it is on PATH."
            )

        lower_iris: List[str] = []
        for c in lower_curies:
            lower_iris.extend(_curie_to_iris(c))
        upper_iris = _curie_to_iris(upper_curie)

        lower_terms_file = self.output_dir / f"{prefix.lower()}_mireot_lower.txt"
        lower_terms_file.write_text("\n".join(lower_iris) + "\n", encoding="utf-8")
        module_ofn = self.output_dir / f"{prefix.lower()}_mireot_module.ofn"
        module_json = self.output_dir / f"{prefix.lower()}_mireot_module.json"

        extract_cmd: List[str] = [
            robot_bin,
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
        extract_cmd += ["--output", str(module_ofn)]
        subprocess.run(extract_cmd, check=True)  # noqa: S603

        subprocess.run(  # noqa: S603
            [
                robot_bin,
                "convert",
                "--input",
                str(module_ofn),
                "--output",
                str(module_json),
                "-f",
                "json",
            ],
            check=True,
        )
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
            except Exception:
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
                f"mesh N-Triples walk for {prefix} needs {nt_path} on disk. "
                f"Run `poetry run kg download` to fetch it."
            )

        labels, parents = _stream_mesh_nt(nt_path)
        print(
            f"  [{prefix}] streamed {nt_path.name}: "
            f"{len(labels):,} labels, {len(parents):,} records with parent edges"
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
        sibling ``.db.gz`` is present, decompress it once (idempotent) and
        use the result.
        """
        if not db_path.is_file():
            gz_path = db_path.with_suffix(db_path.suffix + ".gz")
            if gz_path.is_file():
                print(f"  [{prefix}] decompressing {gz_path.name} → {db_path.name}")
                with gzip.open(gz_path, "rb") as src, db_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                return None
        try:
            from oaklib import get_adapter
        except ImportError as exc:  # pragma: no cover — oaklib is a dep
            raise RuntimeError(f"oaklib import failed while opening SemSQL adapter for {prefix}: {exc}") from exc
        return get_adapter(f"sqlite:{db_path}")

    def _fetch_metadata(self, adapter, curie: str):
        """Return (label, synonyms_list, xrefs_list) for ``curie`` via the OAK adapter."""
        label = ""
        synonyms: Set[str] = set()
        xrefs: Set[str] = set()
        try:
            label = adapter.label(curie) or ""
        except Exception:  # noqa: S110 — obsolete CURIEs are expected to miss
            pass
        try:
            synonyms = {s for s in adapter.entity_aliases(curie) if s}
        except Exception:  # noqa: S110
            pass
        # Drop the canonical label out of the synonym set to keep them disjoint.
        synonyms.discard(label)
        try:
            metadata = adapter.entity_metadata_map(curie) or {}
        except Exception:  # noqa: S110
            metadata = {}
        # OAK returns metadata keyed by short-form predicate. dbxref entries
        # land under "oio:hasDbXref" (or "oboInOwl:hasDbXref" on older
        # adapters). Accept both.
        for predicate_key in ("oio:hasDbXref", "oboInOwl:hasDbXref"):
            for value in metadata.get(predicate_key, []) or []:
                if value:
                    xrefs.add(str(value))
        return (
            _sanitize(label),
            sorted({_sanitize(s) for s in synonyms} - {""}),
            sorted({_sanitize(x) for x in xrefs} - {""}),
        )

    def _write_node_file(self, path: Path, rows: Iterable[Iterable[Optional[str]]]) -> None:
        """Write ``rows`` to ``path`` using the canonical Transform node header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
            writer.writerow(self.node_header)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])

    def _write_edge_file(self, path: Path, rows: Iterable[Iterable[Optional[str]]]) -> None:
        """Write ``rows`` to ``path`` using the canonical Transform edge header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
            writer.writerow(self.edge_header)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])


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
    rest = line[end_s + 2:]
    if not rest.startswith("<"):
        return None
    try:
        end_p = rest.index("> ", 1)
    except ValueError:
        return None
    predicate = rest[: end_p + 1]
    obj = rest[end_p + 2:].strip()
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
                    val = obj_tok[1:obj_tok.rindex("@") - 1]
                    labels[subj_curie] = val
                elif obj_tok.startswith('"'):
                    val = obj_tok[1:obj_tok.rindex('"')]
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
