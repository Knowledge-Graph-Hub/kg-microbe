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
2. For each CURIE, fetches metadata via OAK. The adapter type depends on
   ``STUB_ONTOLOGY_SOURCES[prefix]["source_type"]``:

   * ``"semsql"`` (default — NCIT, mesh, BTO, PO): queries the local SemSQL
     DB (``data/raw/{ncit,mesh,bto,po}.db``) via OAK. The same pattern is
     used by the chemical-mapping consolidator for ChEBI in
     ``scripts/consolidate_chemical_mappings.py``.
   * ``"obograph_json"`` (MICRO): MICRO's bbop-sqlite SemSQL DB is broken
     (a 29-byte placeholder), so we fall back to parsing
     ``data/raw/micro.json`` via an in-house adapter. The JSON is
     generated on demand by :func:`_open_adapter` (which invokes ROBOT
     against the downloaded ``data/raw/micro.owl`` from ``download.yaml``
     if the JSON is missing) — MICRO is no longer part of the full
     ontologies-transform load path, so nothing else produces this file.
     The adapter normalizes both standard
     (``http://purl.obolibrary.org/obo/MICRO_0000082``) and quirky
     (``http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0003152``) IRI
     forms to the canonical ``MICRO:NNNN`` CURIE.

3. Writes one KGX node TSV per stub ontology to
   ``data/transformed/ontologies_stubs/{ncit,mesh,bto,po,micro}_nodes.tsv``
   carrying ``id, category, name, synonym, xref, provided_by,
   knowledge_source``. No edges file — stubs are isolated nodes; edges
   arrive from the source transforms (BacDive, MediaDive ingredients via
   the chemical-mapping path, etc.).

Note for downstream consumers: if a KG built with this transform is ever
merged with a kg-microbe-biomedical KG that loads any of these ontologies
fully, biolink merge semantics will union nodes — the stub node here is a
strict subset of what the full ontology would emit (label/synonym/xref only;
no edges, no deprecated flag, no parent classes), so the union will simply
pick the fuller record.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    NAME_COLUMN,
    PROVIDED_BY_COLUMN,
    SAME_AS_COLUMN,
    SYNONYM_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.isolation_source_mapping_utils import STUB_ONTOLOGY_CATEGORY
from kg_microbe.utils.stub_curie_collection import collect_stub_curies

# Stub ontologies handled by this transform. Each entry maps the canonical
# CURIE prefix (case-sensitive — must match how the prefix appears in
# existing mapping rows) to the input filename, OAK-adapter source_type, and
# the InforES knowledge source string.
#
# source_type controls how `_open_adapter` reaches into the file:
#   * "semsql"        — OAK `sqlite:` adapter against a bbop-sqlite SemSQL DB
#                       (decompressed from a sibling .db.gz on demand).
#   * "obograph_json" — in-house `_ObographJsonAdapter` reading an OBO Graph
#                       JSON produced by ROBOT (used for MICRO because its
#                       bbop-sqlite distribution is a broken 29-byte file).
STUB_ONTOLOGY_SOURCES: Dict[str, Dict[str, str]] = {
    "NCIT": {
        "source_type": "semsql",
        "db_filename": "ncit.db",
        "knowledge_source": "infores:ncit",
    },
    "mesh": {
        "source_type": "semsql",
        "db_filename": "mesh.db",
        "knowledge_source": "infores:mesh",
    },
    "BTO": {
        # BRENDA Tissue Ontology. Only ~2 CURIEs in current kg-microbe
        # mappings (wound fluid from BacDive isolation_source; cell lysate
        # added by the MIM 2026-05-18 republish). Added here so those nodes
        # carry full label + synonyms + xrefs instead of label-only stubs.
        "source_type": "semsql",
        "db_filename": "bto.db",
        "knowledge_source": "infores:bto",
    },
    "PO": {
        # Plant Ontology. ~6-8 CURIEs in current kg-microbe mappings
        # (root, leaf, flower, rhizome, etc.) referenced by BacDive
        # isolation_source. Previously loaded in full by the ontologies
        # transform (~2,170 nodes); the stub path emits one labelled node
        # per reference and skips the rest.
        "source_type": "semsql",
        "db_filename": "po.db",
        "knowledge_source": "infores:po",
    },
    "MICRO": {
        # Microbial Conditions Ontology (Carrine Blank's MicrO). ~34
        # distinct CURIEs in current kg-microbe mappings (~150 total
        # references from chemical/ingredient mappings) — nutrient broth,
        # tryptic soy agar, peptone, etc. Previously loaded in full
        # (~17,600 nodes / ~10 MB OWL). MICRO's bbop-sqlite SemSQL DB is
        # a 29-byte placeholder, so the stub path parses the OBO Graph
        # JSON converted from micro.owl. The JSON is generated on demand
        # by _open_adapter via a ROBOT subprocess; nothing else produces
        # it (MICRO is no longer part of the full ontologies-transform
        # load path).
        "source_type": "obograph_json",
        "db_filename": "micro.json",
        "knowledge_source": "infores:micro",
    },
}

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

    def run(self, data_file=None) -> None:  # noqa: D401 — base class signature
        """
        Collect stub CURIEs, fetch metadata via OAK, write per-ontology node TSVs.

        :param data_file: Unused (kept for the base-class signature). The
            transform discovers its inputs from the mapping TSVs and the
            SemSQL DBs in ``input_base_dir``.
        """
        prefixes = list(STUB_ONTOLOGY_SOURCES.keys())
        curies_by_prefix = collect_stub_curies(prefixes)

        for prefix, curies in curies_by_prefix.items():
            cfg = STUB_ONTOLOGY_SOURCES[prefix]
            db_path = self.input_base_dir / cfg["db_filename"]
            output_file = self.output_dir / f"{prefix.lower()}_nodes.tsv"
            self._write_stub_nodes(
                prefix=prefix,
                curies=sorted(curies),
                db_path=db_path,
                knowledge_source=cfg["knowledge_source"],
                output_file=output_file,
            )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _write_stub_nodes(
        self,
        prefix: str,
        curies: List[str],
        db_path: Path,
        knowledge_source: str,
        output_file: Path,
    ) -> None:
        """Fetch label/synonyms/xrefs per CURIE and write the node TSV."""
        if not curies:
            print(f"  [{prefix}] no CURIEs to import; skipping {output_file.name}")
            # Write an empty file with header so the merge step doesn't fail
            # on a missing file declared in merge.yaml.
            self._write_node_file(output_file, [])
            return

        adapter = self._open_adapter(prefix, db_path)
        if adapter is None:
            source_type = STUB_ONTOLOGY_SOURCES.get(prefix, {}).get("source_type", "semsql")
            if source_type == "obograph_json":
                owl_path = db_path.with_suffix(".owl")
                detail = (
                    f"expected OBO Graph JSON at {db_path} (auto-generated from "
                    f"{owl_path} via ROBOT on first run). Neither file is present — "
                    f"run `poetry run kg download` to fetch the OWL, then re-run "
                    f"this transform."
                )
            else:
                detail = (
                    f"expected SemSQL DB at {db_path} (or sibling {db_path.name}.gz "
                    f"to auto-decompress). Run `poetry run kg download` to fetch it."
                )
            raise FileNotFoundError(
                f"OAK adapter for {prefix} could not be opened: {detail} The stub "
                f"transform refuses to silently emit unlabelled nodes — that would "
                f"reintroduce the dangling-xref hazard this transform exists to fix."
            )

        rows: List[List[Optional[str]]] = []
        missing: List[str] = []
        for curie in curies:
            label, synonyms, xrefs = self._fetch_metadata(adapter, curie)
            if not label:
                # Last-resort fallback: use the CURIE as the name. Log it so
                # curators can chase down obsolete or missing entries upstream.
                missing.append(curie)
                label = curie
            row = [
                curie,  # id
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

    def _open_adapter(self, prefix: str, db_path: Path):
        """
        Open the configured OAK-compatible adapter for ``prefix``; return None if the source file is missing.

        Dispatches on the ``source_type`` field of :data:`STUB_ONTOLOGY_SOURCES`:

        * ``"semsql"`` — OAK SemSQL adapter against ``db_path``. OBO Foundry
          distributes the SemSQL DBs as ``.db.gz`` and ``download.yaml``
          stores the gzipped form, so if the unzipped ``.db`` is missing but
          a sibling ``.db.gz`` is present, decompress it once (idempotent)
          and use the result.
        * ``"obograph_json"`` — in-house :class:`_ObographJsonAdapter` that
          implements the subset of the OAK adapter interface this transform
          actually calls (``label``, ``entity_aliases``,
          ``entity_metadata_map``).
        """
        cfg = STUB_ONTOLOGY_SOURCES.get(prefix, {})
        source_type = cfg.get("source_type", "semsql")
        if source_type == "obograph_json":
            if not db_path.is_file():
                # MICRO ships only as OWL in download.yaml; convert once via
                # ROBOT if the sibling .owl is present. Mirrors the .db.gz →
                # .db decompression flow below.
                owl_path = db_path.with_suffix(".owl")
                if owl_path.is_file():
                    print(f"  [{prefix}] converting {owl_path.name} → {db_path.name} via ROBOT")
                    from kg_microbe.utils.robot_utils import convert_to_json

                    convert_to_json(str(owl_path.parent), owl_path.stem)
                if not db_path.is_file():
                    return None
            return _ObographJsonAdapter.from_file(db_path)
        # semsql (default)
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
        """Return (label, synonyms_set, xrefs_set) for ``curie`` via the OAK adapter."""
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
        return label, sorted(synonyms), sorted(xrefs)

    def _write_node_file(self, path: Path, rows: Iterable[Iterable[Optional[str]]]) -> None:
        """Write ``rows`` to ``path`` using the standard Transform node header."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Use the canonical 9-column node header from the Transform base class.
        header = [
            ID_COLUMN,
            CATEGORY_COLUMN,
            NAME_COLUMN,
            DESCRIPTION_COLUMN,
            XREF_COLUMN,
            PROVIDED_BY_COLUMN,
            SYNONYM_COLUMN,
            DEPRECATED_COLUMN,
            SAME_AS_COLUMN,
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
            writer.writerow(header)
            for row in rows:
                writer.writerow(["" if cell is None else cell for cell in row])


def _join_pipe(values: Iterable[str]) -> str:
    """Pipe-join a sequence; return ``""`` when empty (matches existing TSV convention)."""
    items = [v for v in values if v]
    return "|".join(items) if items else ""


# Match the local ID at the tail of an OBO Foundry IRI. Handles both the
# standard ``http://purl.obolibrary.org/obo/MICRO_0000082`` shape and MicrO's
# quirky ``http://purl.obolibrary.org/obo/MicrO.owl/MICRO_0003152`` variant.
_OBO_LOCAL_ID_RE = re.compile(r"/([A-Za-z][A-Za-z0-9]*)_([A-Za-z0-9]+)$")


class _ObographJsonAdapter:

    """
    Minimal OAK-adapter-shaped reader over an OBO Graph JSON file.

    Implements only the methods :class:`OntologiesStubsTransform` calls
    (``label``, ``entity_aliases``, ``entity_metadata_map``); everything else
    intentionally remains undefined so a future caller that needs more of the
    OAK interface fails loudly rather than silently returning empties.

    Used for ontologies whose bbop-sqlite SemSQL distribution is unavailable
    or broken (MICRO at time of writing).
    """

    def __init__(self, nodes_by_curie: Dict[str, Dict]):
        """Cache the parsed obograph JSON keyed by canonical ``PREFIX:local`` CURIE."""
        self._nodes = nodes_by_curie

    @classmethod
    def from_file(cls, json_path: Path) -> "_ObographJsonAdapter":
        """Parse ``json_path`` (OBO Graph JSON) and key its nodes by canonical CURIE."""
        with json_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        nodes_by_curie: Dict[str, Dict] = {}
        for graph in data.get("graphs", []) or []:
            for node in graph.get("nodes", []) or []:
                iri = node.get("id") or ""
                m = _OBO_LOCAL_ID_RE.search(iri)
                if not m:
                    continue
                curie = f"{m.group(1)}:{m.group(2)}"
                # First occurrence wins (obograph rarely duplicates within a graph).
                nodes_by_curie.setdefault(curie, node)
        return cls(nodes_by_curie)

    def label(self, curie: str) -> str:
        """Return ``rdfs:label`` for ``curie`` or ``""`` if absent."""
        node = self._nodes.get(curie)
        return (node or {}).get("lbl") or ""

    def entity_aliases(self, curie: str) -> List[str]:
        """Return all synonym literals for ``curie`` (any predicate kind)."""
        node = self._nodes.get(curie) or {}
        meta = node.get("meta") or {}
        out: List[str] = []
        for syn in meta.get("synonyms", []) or []:
            val = syn.get("val") if isinstance(syn, dict) else None
            if val:
                out.append(val)
        return out

    def entity_metadata_map(self, curie: str) -> Dict[str, List[str]]:
        """
        Return a dict shaped like OAK's ``entity_metadata_map`` output.

        Only the ``oio:hasDbXref`` key is populated — that's the only field
        the stub transform consumes from the OAK metadata map. Other
        OAK-emitted keys (``IAO:0000115`` definition, ``createdBy``, etc.)
        are intentionally omitted; the stub transform does not write them.
        """
        node = self._nodes.get(curie) or {}
        meta = node.get("meta") or {}
        xrefs = [x.get("val") if isinstance(x, dict) else x for x in (meta.get("xrefs") or [])]
        xrefs = [x for x in xrefs if x]
        return {"oio:hasDbXref": xrefs} if xrefs else {}
