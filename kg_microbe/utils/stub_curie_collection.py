"""
Collect stub-prefix CURIEs referenced anywhere in the mapping TSVs.

KG-Microbe deliberately does NOT load the full NCIT or MESH ontologies (those
belong to the sibling kg-microbe-biomedical pipeline), but the chemical-mapping
consolidator and the BacDive isolation-source mapper reference a small handful
of NCIT and MESH IDs. This collector finds every such CURIE so that the
downstream :class:`~kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform.OntologiesStubsTransform`
can fetch a labelled stub node for each one.

It scans a fixed set of mapping files at the repo root (no glob magic — wrong
edits silently change the import set, so the file list is explicit and
auditable):

* ``mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz`` — unified
  chemical/anatomy/environment mappings (object_id, subject_id columns).
* ``mappings/isolation_source_to_ontology.tsv`` — BacDive isolation-source
  mappings (object_id column).
* ``mappings/ingredient_mappings.sssom.tsv`` — vendored MIM SSSOM
  (object_id, subject_id).
* ``mappings/canonical/*.tsv`` — chemical/enzyme/pathway/phenotype canonical
  exports (object_id).

Returned dict shape: ``{normalized_prefix: {curie, curie, ...}}`` where
``normalized_prefix`` matches the case used in
:data:`~kg_microbe.utils.isolation_source_mapping_utils.STUB_ONTOLOGY_PREFIXES`
(e.g. ``"NCIT"`` is uppercase, ``"mesh"`` is lowercase). Inputs in any case
are accepted and normalized.
"""

from __future__ import annotations

import csv
import gzip
import re
from pathlib import Path
from typing import Dict, Iterable, Set

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Files explicitly scanned for stub CURIEs. Adding a new file here is an
# auditable opt-in change; missing files are silently skipped (so removing a
# mapping source from the repo doesn't break the collector).
DEFAULT_MAPPING_PATHS = (
    REPO_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
    REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv",
    REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv",
    REPO_ROOT / "mappings" / "canonical" / "chemical_mappings.tsv",
    REPO_ROOT / "mappings" / "canonical" / "enzyme_mappings.tsv",
    REPO_ROOT / "mappings" / "canonical" / "enzyme_name_to_go.tsv",
    REPO_ROOT / "mappings" / "canonical" / "metpo_alias_mappings.tsv",
    REPO_ROOT / "mappings" / "canonical" / "pathway_mappings.tsv",
    REPO_ROOT / "mappings" / "canonical" / "phenotype_mappings.tsv",
    REPO_ROOT / "mappings" / "canonical" / "special_chemical_mappings.tsv",
)

# Columns to scan for CURIEs across all mapping shapes. Any cell whose value
# parses as ``<prefix>:<id>`` and matches one of the requested prefixes is
# collected.
_CURIE_COLUMNS = (
    "object_id",
    "subject_id",
)

_CURIE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9._-]*):([A-Za-z0-9_.\-]+)$")


def _open_text(path: Path):
    """Open a TSV / TSV.GZ for text reading after stripping any SSSOM YAML header."""
    handle = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(
        "r", encoding="utf-8"
    )
    # SSSOM files prefix a YAML metadata header with `# `. Skip those before
    # handing the file to csv.DictReader.
    while True:
        pos = handle.tell()
        line = handle.readline()
        if not line:
            break
        if not line.startswith("#"):
            handle.seek(pos)
            break
    return handle


def _normalize_prefix(prefix: str, canonical_prefixes: Dict[str, str]) -> str | None:
    """Return the canonical-cased prefix string for ``prefix``, or ``None`` if unknown."""
    return canonical_prefixes.get(prefix.lower())


def collect_stub_curies(
    prefixes: Iterable[str],
    mapping_paths: Iterable[Path] | None = None,
) -> Dict[str, Set[str]]:
    """
    Scan the mapping TSVs and return the set of CURIEs that match each requested prefix.

    :param prefixes: Iterable of CURIE prefixes to collect. Case-insensitive on
        input; the returned dict's keys preserve the case as given here, so
        callers should pass them in the canonical form they want
        (``"NCIT"``, ``"mesh"``, ...).
    :param mapping_paths: Override the file list (mainly for tests). Defaults
        to :data:`DEFAULT_MAPPING_PATHS`.
    :returns: ``{canonical_prefix: {curie, ...}}`` for every prefix in
        ``prefixes``, with the empty set as default for prefixes that have no
        references in any mapping file.
    """
    canonical_prefixes: Dict[str, str] = {p.lower(): p for p in prefixes}
    result: Dict[str, Set[str]] = {p: set() for p in canonical_prefixes.values()}

    paths = list(mapping_paths) if mapping_paths is not None else list(DEFAULT_MAPPING_PATHS)

    for path in paths:
        if not path.is_file():
            continue
        with _open_text(path) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                for col in _CURIE_COLUMNS:
                    value = (row.get(col) or "").strip()
                    if not value:
                        continue
                    match = _CURIE_RE.match(value)
                    if not match:
                        continue
                    raw_prefix, local = match.group(1), match.group(2)
                    canonical = _normalize_prefix(raw_prefix, canonical_prefixes)
                    if canonical is None:
                        continue
                    result[canonical].add(f"{canonical}:{local}")

    return result


__all__ = [
    "DEFAULT_MAPPING_PATHS",
    "collect_stub_curies",
]
