"""Merging module."""

import csv
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx  # type: ignore
import yaml
from kgx.cli.cli_utils import merge  # type: ignore

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
    XREF_COLUMN,
)

CANONICAL_NODE_HEADER = [
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

# Canonical edge header; metatraits extension `has_percentage` preserved if present.
CANONICAL_EDGE_HEADER = [
    SUBJECT_COLUMN,
    PREDICATE_COLUMN,
    OBJECT_COLUMN,
    RELATION_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    AGENT_TYPE_COLUMN,
]

EDGE_COLUMNS_TO_DROP = {ID_COLUMN, "meta"}
NODE_COLUMNS_TO_DROP = {"subsets", "meta", "iri"}
EDGE_EXTENSION_COLUMNS = {"has_percentage"}


def parse_load_config(yaml_file: str) -> Dict:
    """
    Parse load config YAML.

    :param yaml_file: A string pointing to a KGX compatible config YAML.
    :return: Dict: The config as a dictionary.
    """
    with open(yaml_file) as yamlf:
        config = yaml.safe_load(yamlf)  # , Loader=yaml.FullLoader)
    return config


def load_and_merge(yaml_file: str, processes: int = 1) -> nx.MultiDiGraph:
    """
    Load and merge sources defined in the config YAML.

    :param yaml_file: A string pointing to a KGX compatible config YAML.
    :param processes: Number of processes to use.
    :return: networkx.MultiDiGraph: The merged graph.

    """
    merged_graph = merge(yaml_file, processes=processes)
    try:
        _cleanup_merged_outputs(yaml_file)
    except Exception as exc:  # noqa: BLE001
        # Cleanup is belt-and-suspenders; never let it mask a successful merge.
        print(f"[merge] post-merge cleanup skipped: {exc}")
    return merged_graph


def _cleanup_merged_outputs(yaml_file: str) -> None:
    r"""
    Defensive post-merge normalization of the KGX-merged TSVs.

    Why this step exists: `kgx.cli.cli_utils.merge` takes the column union
    across source TSVs, and `kgx.sink.TsvSink` writes them out. That
    combination produces three classes of artifacts we see in practice:

      1. Duplicate header columns (e.g. `provided_by` x2, `agent_type` x2)
         when source files are headerless-subsets of each other and column
         order is reconstructed from per-record property sets.
      2. Auxiliary columns from obograph ingestion that leak through
         (`subsets`, `meta`, edge `id`) plus the deprecated
         `knowledge_source` alongside its biolink 3.x replacement
         `primary_knowledge_source`.
      3. Stray `\r` characters emitted mid-header by TsvSink when a source
         description field contained an embedded CR (seen in ChEBI
         descriptions). This corrupts CSV-reader parsing downstream.

    Upstream schema normalization in each transform (see Task #7, #8 in
    the PR) removes most causes of (1) and (2); this step is therefore
    largely defensive and is idempotent — it becomes a no-op when sources
    are already uniform. It does NOT fix the `\r` issue upstream because
    that byte is injected by KGX's sink, not by the source files.

    TODO: After the transform-level schema normalization (Task #7/#8) has
    been validated across a full pipeline run, re-evaluate whether this
    post-merge cleanup still detects drift. If it consistently logs
    "no changes", we can (a) drop it, or (b) demote it to an assertion
    that fails CI when KGX regresses.

    Handles both the uncompressed TSV pair and the tar.gz archive.
    """
    config = parse_load_config(yaml_file)
    output_dir = Path(config.get("configuration", {}).get("output_directory", "data/merged"))
    destinations = config.get("merged_graph", {}).get("destination", {})

    for dest in destinations.values():
        if dest.get("format") != "tsv":
            continue
        base = dest.get("filename")
        if not base:
            continue
        nodes_file = output_dir / f"{base}_nodes.tsv"
        edges_file = output_dir / f"{base}_edges.tsv"
        archive = output_dir / f"{base}.tar.gz"

        # KGX's TsvSink with compression: tar.gz writes the TSVs into the
        # archive and removes the loose files. Extract them first so we can
        # normalize in place, then re-tar.
        extracted_from_archive = False
        if (
            dest.get("compression") == "tar.gz"
            and archive.is_file()
            and not (nodes_file.is_file() and edges_file.is_file())
        ):
            print(f"[merge-cleanup] extracting {archive.name} to normalize TSVs in place")
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(output_dir)
            extracted_from_archive = True

        if nodes_file.is_file():
            _normalize_nodes_tsv(nodes_file)
        if edges_file.is_file():
            _normalize_edges_tsv(edges_file)

        if dest.get("compression") == "tar.gz":
            if nodes_file.is_file() and edges_file.is_file():
                _rewrite_tarball(archive, [nodes_file, edges_file])
                if extracted_from_archive:
                    # KGX didn't leave loose TSVs before, so don't leave them now.
                    nodes_file.unlink(missing_ok=True)
                    edges_file.unlink(missing_ok=True)


def _iter_clean_lines(path: Path):
    r"""Yield lines with stray carriage returns stripped (KGX occasionally emits \r mid-line)."""
    with open(path, "r", newline="\n") as src:
        for line in src:
            yield line.replace("\r", "")


def _log_schema_diff(kind: str, path: Path, in_header: List[str], out_header: List[str]) -> None:
    """Log the before/after schema so reviewers can see when this step is a no-op."""
    dropped = [c for c in in_header if c not in out_header]
    added = [c for c in out_header if c not in in_header]
    duplicates = [c for c in set(in_header) if in_header.count(c) > 1]
    if not (dropped or added or duplicates) and in_header == out_header:
        print(f"[merge-cleanup] {kind} {path.name}: schema already canonical (no-op)")
        return
    print(
        f"[merge-cleanup] {kind} {path.name}: "
        f"dropped={dropped} added={added} deduped={duplicates}"
    )


def _normalize_nodes_tsv(path: Path) -> None:
    """Dedup node columns, drop auxiliary KGX columns, order by canonical header."""
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, newline="") as tmp:
        tmp_path = Path(tmp.name)
        reader = csv.reader(_iter_clean_lines(path), delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            tmp_path.unlink(missing_ok=True)
            return
        keep_indices, out_header = _resolve_column_plan(
            header, CANONICAL_NODE_HEADER, NODE_COLUMNS_TO_DROP, extension_columns=set()
        )
        _log_schema_diff("nodes", path, header, out_header)
        writer = csv.writer(tmp, delimiter="\t")
        writer.writerow(out_header)
        for row in reader:
            writer.writerow(_project_row(row, keep_indices))
    tmp_path.replace(path)


def _normalize_edges_tsv(path: Path) -> None:
    """Dedup edge columns, drop `id`/`meta`, merge `knowledge_source` into primary."""
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, newline="") as tmp:
        tmp_path = Path(tmp.name)
        reader = csv.reader(_iter_clean_lines(path), delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            tmp_path.unlink(missing_ok=True)
            return

        # Merge knowledge_source into primary_knowledge_source (fill if primary empty)
        ks_idx = _first_index(header, "knowledge_source")
        pks_idx = _first_index(header, PRIMARY_KNOWLEDGE_SOURCE_COLUMN)

        keep_indices, out_header = _resolve_column_plan(
            header,
            CANONICAL_EDGE_HEADER,
            EDGE_COLUMNS_TO_DROP | {"knowledge_source"},
            extension_columns=EDGE_EXTENSION_COLUMNS,
        )
        _log_schema_diff("edges", path, header, out_header)
        writer = csv.writer(tmp, delimiter="\t")
        writer.writerow(out_header)
        for row in reader:
            if ks_idx is not None and pks_idx is not None and pks_idx < len(row):
                if not row[pks_idx] and ks_idx < len(row):
                    row[pks_idx] = row[ks_idx]
            writer.writerow(_project_row(row, keep_indices))
    tmp_path.replace(path)


def _first_index(header: List[str], name: str) -> Optional[int]:
    """Return first index of `name` in header, or None if absent."""
    try:
        return header.index(name)
    except ValueError:
        return None


def _resolve_column_plan(
    header: List[str],
    canonical: List[str],
    drop: set,
    extension_columns: set,
):
    """
    Build (keep_indices, out_header) enforcing canonical order + dedup.

    - Canonical columns are emitted in canonical order.
    - Extension columns (e.g. has_percentage) are appended if present.
    - Any other unknown columns are appended (preserves forward-compat data).
    - Duplicate occurrences keep the first non-empty value is handled at row time.
    """
    keep_indices: List[List[int]] = []  # each entry = list of source indices to coalesce
    out_header: List[str] = []
    used = set()

    def add_column(name: str):
        indices = [i for i, h in enumerate(header) if h == name]
        if not indices:
            return
        keep_indices.append(indices)
        out_header.append(name)
        used.update(indices)

    for col in canonical:
        if col in drop:
            continue
        add_column(col)

    for col in extension_columns:
        if col in drop:
            continue
        add_column(col)

    for i, col in enumerate(header):
        if i in used or col in drop or col in out_header:
            continue
        add_column(col)

    return keep_indices, out_header


def _project_row(row: List[str], keep_indices: List[List[int]]) -> List[str]:
    """Project a row onto the resolved column plan, coalescing duplicates."""
    out = []
    for group in keep_indices:
        value = ""
        for idx in group:
            if idx < len(row) and row[idx]:
                value = row[idx]
                break
        out.append(value)
    return out


def _rewrite_tarball(archive: Path, files: List[Path]) -> None:
    """Re-archive the cleaned TSVs into the same tar.gz path."""
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=archive.parent, suffix=".tar.gz") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            for f in files:
                tar.add(f, arcname=f.name)
        shutil.move(str(tmp_path), str(archive))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
