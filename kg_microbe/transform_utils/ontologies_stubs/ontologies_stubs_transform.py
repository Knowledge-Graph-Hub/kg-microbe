"""
Ontologies-stubs transform.

KG-Microbe deliberately does NOT load the full NCIT or MESH ontologies — those
belong to the sibling ``kg-microbe-biomedical`` pipeline. But the
chemical-mapping consolidator and the BacDive isolation-source mapper reference
~150 NCIT and MESH IDs as canonical xrefs for ingredients (e.g.
``NCIT:C29298 'Oatmeal'``, ``mesh:D011136 'Tween'``). Without this transform
those CURIEs would appear as dangling node ids in the merged KG: edges point at
them but no node row carries the label.

This transform:

1. Calls :func:`~kg_microbe.utils.stub_curie_collection.collect_stub_curies` to
   discover every NCIT and MESH CURIE referenced anywhere under ``mappings/``.
2. For each CURIE, queries the local SemSQL DB (``data/raw/ncit.db``,
   ``data/raw/mesh.db``) via OAK to fetch its ``rdfs:label``, exact synonyms,
   and dbxrefs. The same pattern is used by the chemical-mapping consolidator
   for ChEBI in ``scripts/consolidate_chemical_mappings.py``.
3. Writes one KGX node TSV per stub ontology to
   ``data/transformed/ontologies_stubs/{ncit,mesh}_nodes.tsv`` carrying
   ``id, category, name, synonym, xref, provided_by, knowledge_source``.
   No edges file — stubs are isolated nodes; edges arrive from the source
   transforms (BacDive, MediaDive ingredients via the chemical-mapping path,
   etc.).

Note for downstream consumers: if a KG built with this transform is ever
merged with a kg-microbe-biomedical KG that loads NCIT/MESH fully, biolink
merge semantics will union nodes — the stub node here is a strict subset of
what the full ontology would emit (label/synonym/xref only; no edges, no
deprecated flag, no parent classes), so the union will simply pick the
fuller record.
"""

from __future__ import annotations

import csv
import gzip
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
# existing mapping rows) to the local SemSQL DB and the InforES knowledge
# source string.
STUB_ONTOLOGY_SOURCES: Dict[str, Dict[str, str]] = {
    "NCIT": {
        "db_filename": "ncit.db",
        "knowledge_source": "infores:ncit",
    },
    "mesh": {
        "db_filename": "mesh.db",
        "knowledge_source": "infores:mesh",
    },
}

ONTOLOGIES_STUBS_SOURCE_NAME = "ontologies_stubs"


class OntologiesStubsTransform(Transform):

    """Emit one labelled stub node per referenced NCIT / MESH CURIE."""

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
            raise FileNotFoundError(
                f"OAK adapter for {prefix} could not be opened (expected SemSQL DB at "
                f"{db_path}). Run `poetry run kg download` to fetch it. The stub "
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
                curie,                      # id
                STUB_ONTOLOGY_CATEGORY,     # category
                label,                      # name
                None,                        # description
                _join_pipe(xrefs),          # xref
                ONTOLOGIES_STUBS_SOURCE_NAME,  # provided_by
                _join_pipe(synonyms),       # synonym
                None,                        # deprecated
                None,                        # same_as
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
        Open an OAK SemSQL adapter against the local DB; return None on failure.

        OBO Foundry distributes the SemSQL DBs as ``.db.gz`` and ``download.yaml``
        stores the gzipped form. If the unzipped ``.db`` is missing but a sibling
        ``.db.gz`` is present, decompress it once (idempotent) and use the result.
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
            raise RuntimeError(
                f"oaklib import failed while opening SemSQL adapter for {prefix}: {exc}"
            ) from exc
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
