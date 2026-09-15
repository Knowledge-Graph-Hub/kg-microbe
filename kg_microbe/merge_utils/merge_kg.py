"""Merging module."""

import csv
import os
import shutil
import tarfile
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx  # type: ignore
import yaml

from kg_microbe.merge_utils.artifact_manifest import build_provenance, write_graph_archive, write_loose_manifest
from kg_microbe.merge_utils.invariants import check_merged_invariants
from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION, annotate_graph_stats, stats_filename_from_config
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
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.source_finalization import verify_finalized_source_files, write_merge_validation_report
from kg_microbe.utils.tsv_io import tsv_writer

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

EDGE_COLUMNS_TO_DROP = {ID_COLUMN, "meta", "key"}
NODE_COLUMNS_TO_DROP = {"subsets", "meta", "iri"}
#: Known non-canonical edge columns. Membership is not what keeps a column:
#: ``_resolve_column_plan`` appends any unrecognised header anyway, so an
#: omission here loses no data — it only moves the column after the other
#: unknowns. Listing them keeps "which sources add what" answerable without
#: re-deriving it from every transform. ``original_object`` is Biolink's slot
#: for the pre-transformation target, used by gold when it resolves an
#: uninformative ecosystem upward.
EDGE_EXTENSION_COLUMNS = {"has_percentage", "original_object"}


def merge(*args, **kwargs):
    """Invoke KGX with local schema and provenance-preserving graph export (#1049)."""
    from kg_microbe.utils.biolink_model import prepare_kgx

    prepare_kgx()
    from kgx import transformer as transformer_module
    from kgx.cli import cli_utils

    from kg_microbe.merge_utils.kgx_source import (
        ProvenancePreservingTransformer,
        RelationAwareGraphSink,
        RelationAwareGraphSource,
        RelationAwareTsvSink,
        merge_assertion_graphs,
        parse_source,
    )

    original_transformer = cli_utils.Transformer
    original_parser = cli_utils.parse_source
    original_graph_merge = cli_utils.merge_all_graphs
    original_sink = transformer_module.GraphSink
    original_graph_source = transformer_module.SOURCE_MAP["graph"]
    original_tsv_sinks = {name: transformer_module.SINK_MAP[name] for name in ("tsv", "csv")}

    cli_utils.Transformer = ProvenancePreservingTransformer
    cli_utils.parse_source = parse_source
    cli_utils.merge_all_graphs = merge_assertion_graphs
    transformer_module.GraphSink = RelationAwareGraphSink
    transformer_module.SOURCE_MAP["graph"] = RelationAwareGraphSource
    transformer_module.SINK_MAP.update({name: RelationAwareTsvSink for name in original_tsv_sinks})
    try:
        return cli_utils.merge(*args, **kwargs)
    finally:
        cli_utils.Transformer = original_transformer
        cli_utils.parse_source = original_parser
        cli_utils.merge_all_graphs = original_graph_merge
        transformer_module.GraphSink = original_sink
        transformer_module.SOURCE_MAP["graph"] = original_graph_source
        transformer_module.SINK_MAP.update(original_tsv_sinks)


def parse_load_config(yaml_file: str) -> Dict:
    """
    Parse load config YAML.

    :param yaml_file: A string pointing to a KGX compatible config YAML.
    :return: Dict: The config as a dictionary.
    """
    with open(yaml_file) as yamlf:
        config = yaml.safe_load(yamlf)  # , Loader=yaml.FullLoader)
    return config


def _assert_sources_exist(yaml_file: str, sources: List[str]) -> None:
    """
    Fail before parsing anything if a requested source is not in the config.

    KGX indexes the config dict directly, so an unknown key surfaces as a
    bare ``KeyError: 'foo'`` only after the run is underway. A merge is a
    long, expensive operation; a typo should not be discovered an hour in.

    :param yaml_file: Path to the KGX merge config.
    :param sources: Source keys requested on the command line.
    :raises KeyError: If any requested source is absent from the config.
    """
    with open(yaml_file, "r") as fh:
        config = yaml.safe_load(fh)
    available = set((config.get("merged_graph", {}) or {}).get("source", {}) or {})
    unknown = [s for s in sources if s not in available]
    if unknown:
        raise KeyError(f"Source(s) {sorted(unknown)} not in {yaml_file}. Available: {sorted(available)}")


def load_and_merge(
    yaml_file: str,
    processes: int = 1,
    sources: Optional[List[str]] = None,
) -> nx.MultiDiGraph:
    """
    Load and merge sources defined in the config YAML.

    ``sources`` restricts the merge to a subset of the config's sources.
    KGX holds every source's graph in the parent process at once —
    ``kgx.cli.cli_utils.merge`` collects them all before calling
    ``merge_all_graphs`` — so peak memory scales with the whole set, not
    with the largest member. Merging in stages is the only way to keep a
    very large source (PREGO: 44.7M edges) from coexisting with all the
    others.

    :param yaml_file: A string pointing to a KGX compatible config YAML.
    :param processes: Number of processes to use. Each concurrent process
        holds its own source graph, so raising this raises peak memory.
    :param sources: Optional subset of source keys to merge. None merges all.
    :return: The pre-serialization KGX in-memory graph. Serialization projection
        affects the published TSV/archive, not this returned object; use its
        manifest for final byte identity and row counts. No post-merge semantic
        repairs are permitted. Sources must be explicitly finalized first.
    :raises KeyError: If a requested source is absent from the config.
    """
    if sources:
        _assert_sources_exist(yaml_file, sources)
    _assert_sources_finalized(yaml_file, sources)
    # KGX writes the destination before post-processing starts. Never give it
    # a published pathname: a later required failure must preserve the old
    # artifact, not merely propagate after KGX has already overwritten it.
    with _staged_merge_configuration(yaml_file) as (staged_config, staged_output, final_output, stats_outputs):
        merged_graph = merge(str(staged_config), source=list(sources) if sources else None, processes=processes)
        failed_stats = _cleanup_merged_outputs(
            str(staged_config), original_yaml_file=yaml_file, published_output_dir=final_output
        )
        written = _publish_staged_outputs(staged_output, final_output, stats_outputs, failed_stats)
        _warn_about_stale_siblings(final_output, written)
    return merged_graph


def _assert_sources_finalized(yaml_file, sources=None):
    """Require prepared graph bytes by default, independent of their directory or current working path."""
    config = parse_load_config(yaml_file)
    allow = config.get("configuration", {}).get("allow_unfinalized_sources", False)
    if not isinstance(allow, bool):
        raise ValueError("configuration.allow_unfinalized_sources must be a boolean")
    if allow:
        print("[merge-validation] WARNING: DIAGNOSTIC OPT-OUT allow_unfinalized_sources=true; not a finalized release")
        return
    filenames = []
    for name, source in (config.get("merged_graph", {}).get("source") or {}).items():
        if sources and name not in sources:
            continue
        inputs = source.get("input") or {}
        values = inputs.get("filename") or []
        values = [values] if isinstance(values, str) else values
        filenames.extend(
            _source_filename_at_original_location(value, Path(yaml_file).resolve().parent) for value in values
        )
    verify_finalized_source_files(filenames)
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness

    verify_source_freshness(filenames)


def _source_filename_at_original_location(filename: str, config_dir: Path) -> str:
    """Preserve KGX's existing-path-first, config-directory-second source resolution."""
    path = Path(filename)
    if path.is_absolute() or path.exists():
        return str(path.resolve())
    return str((config_dir / path).resolve())


@contextmanager
def _staged_merge_configuration(yaml_file: str):
    """Redirect file publication into a unique same-filesystem workspace without editing user YAML."""
    config_file = Path(yaml_file).absolute()
    config = deepcopy(parse_load_config(str(config_file)))
    configured = config.get("configuration", {}).get("output_directory")
    configured_output = Path(configured or "output")
    final_output = (
        configured_output
        if configured_output.is_absolute() or not configured
        else config_file.parent / configured_output
    ).resolve()
    final_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{final_output.name}.merge-", dir=final_output.parent) as temporary:
        staging = Path(temporary)
        staged_output = staging / "graph"
        staged_output.mkdir()
        config.setdefault("configuration", {})["output_directory"] = str(staged_output)
        graph = config.get("merged_graph", {})
        for source in (graph.get("source") or {}).values():
            inputs = source.get("input") or {}
            filenames = inputs.get("filename")
            if filenames:
                inputs["filename"] = [
                    _source_filename_at_original_location(filename, config_file.parent)
                    for filename in ([filenames] if isinstance(filenames, str) else filenames)
                ]
        for destination in (graph.get("destination") or {}).values():
            filename = destination.get("filename")
            if not filename:
                continue
            base = Path(filename[0] if isinstance(filename, list) else filename)
            if base.is_absolute() or ".." in base.parts:
                raise ValueError(f"Merge destination filename must stay inside output_directory: {filename}")
            (staged_output / base).parent.mkdir(parents=True, exist_ok=True)

        # KGX graph-operation filenames are interpreted relative to the process
        # cwd, not the config directory. Preserve that location on publication.
        stats_outputs = {}
        operation_lists = [graph.get("operations") or []]
        operation_lists.extend(source.get("operations") or [] for source in (graph.get("source") or {}).values())
        for operations in operation_lists:
            for operation in operations:
                if operation.get("name") != STATS_OPERATION:
                    continue
                args = operation.get("args") or {}
                if not args.get("filename"):
                    continue
                published = Path(args["filename"]).resolve()
                staged = stats_outputs.setdefault(published, staging / "stats" / f"{len(stats_outputs)}.yaml")
                staged.parent.mkdir(exist_ok=True)
                args["filename"] = str(staged)
        staged_config = staging / "merge.yaml"
        with staged_config.open("w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(config, stream, sort_keys=False)
        yield staged_config, staged_output, final_output, stats_outputs


def _publish_staged_outputs(
    staged_output: Path, final_output: Path, stats_outputs: Dict, failed_stats: Optional[set] = None
) -> set:
    """Publish completed files only after all required preparation; renames are per-file, not a transaction."""
    staged_files = sorted(path for path in staged_output.rglob("*") if path.is_file())
    for path in staged_files:
        if path.is_symlink():
            raise ValueError(f"Staged graph output must be a regular file, not a symlink: {path}")
    # Optional stats can live on another filesystem; their small atomic copy
    # is separate from graph publication and never puts an archive at risk.
    for published, staged in stats_outputs.items():
        if staged.is_file() and staged not in (failed_stats or set()):
            try:
                with staged.open("rb") as source, atomic_write(published, "wb") as target:
                    shutil.copyfileobj(source, target)
            except OSError as exc:
                print(f"[merge-stats] publication skipped: {exc}")
    written = set()
    # Ship archive/manifest markers last. This does not claim cross-file
    # atomicity for loose pairs or several independent destinations.
    staged_files.sort(key=lambda path: path.name.endswith((".tar.gz", "_manifest.json")))
    for staged in staged_files:
        published = final_output / staged.relative_to(staged_output)
        published.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, published)
        written.add(published)
    return written


def _repo_root() -> Path:
    """Return the checkout root; merge configs and stats paths are relative to it."""
    return Path(__file__).resolve().parents[2]


def _cleanup_merged_outputs(
    yaml_file: str, original_yaml_file: Optional[str] = None, published_output_dir: Optional[Path] = None
) -> set:
    r"""
    Project KGX serialization, validate immutable semantics, and package the result.

    This boundary orders columns, removes documented auxiliary/internal
    columns, coalesces only nonconflicting duplicate fields, and normalizes
    transport CRLF. It preserves literal quote text. Conflicting values and
    embedded carriage returns fail instead of silently losing observations.
    Legacy knowledge_source filling remains explicit format compatibility.

    Identity, category and ontology-reference decisions happen in source
    finalization, before KGX. This function never consults live raw ontology
    authorities or repairs biological assertions. Required validation and
    manifest failures propagate before staged publication; optional reports
    and statistics retain their isolated failure behavior.

    Handles both the uncompressed TSV pair and the tar.gz archive. Returns
    optional stats paths whose annotation failed, so staging can withhold
    those files without suppressing a valid graph publication.
    """
    config = parse_load_config(yaml_file)
    provenance_config = Path(original_yaml_file or yaml_file)
    output_dir = Path(config.get("configuration", {}).get("output_directory", "data/merged"))
    destinations = config.get("merged_graph", {}).get("destination", {})

    # Accumulated across every destination, TSV or not: "did this run write it"
    # is a property of the whole run. Warning per-destination made each one
    # report the others' fresh output as stale (#848).
    written: set = set()
    failed_stats: set = set()

    for dest in destinations.values():
        base = dest.get("filename")
        if not base:
            continue
        if dest.get("format") != "tsv":
            # Not normalised here, but still ours — record it so it is never
            # reported as a leftover.
            written.add(output_dir / base)
            continue
        nodes_file = output_dir / f"{base}_nodes.tsv"
        edges_file = output_dir / f"{base}_edges.tsv"
        reference_report = output_dir / f"{base}_reference_resolution.tsv"
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
                # Read only the requested graph pair. In particular do not
                # unpack a generic manifest.json over another destination's
                # manifest, or trust arbitrary paths/links from an old archive.
                for graph_file in (nodes_file, edges_file):
                    member = tar.getmember(graph_file.name)
                    if not member.isfile():
                        raise ValueError(f"Graph member must be a regular file: {member.name}")
                    with tar.extractfile(member) as source, atomic_write(graph_file, "wb") as target:
                        shutil.copyfileobj(source, target)
            extracted_from_archive = True

        if not nodes_file.is_file() or not edges_file.is_file():
            raise FileNotFoundError(f"Merge destination is missing its TSV pair: {nodes_file}, {edges_file}")
        if nodes_file.is_file():
            _normalize_nodes_tsv(nodes_file)
        if edges_file.is_file():
            _normalize_edges_tsv(edges_file)
            # Semantic decisions belong to source finalization (#1082).
            # Merge checks the result without consulting live raw authorities
            # or remapping categories, identities or original assertions.
            validation_counts = write_merge_validation_report(nodes_file, edges_file, reference_report)
            print(f"[merge-validation] {base}: {validation_counts}; no semantic rewrites")
            # Checked here rather than in each transform: a transform can only
            # police the edges it writes, and kgmicrobe.strain is a namespace
            # several sources mint into (#896).
            #
            # Optional diagnostics must not decide whether the artifact ships
            # (#914). Required normalization/manifest/publication failures,
            # unlike this report, propagate to the caller (#1075).
            try:
                check_merged_invariants(edges_file, output_dir, nodes_file=nodes_file)
            except Exception as exc:  # noqa: BLE001
                print(f"[merge-invariants] check skipped: {exc}")
            # The stats file KGX wrote says nothing about what produced it and
            # cannot name a METPO predicate (#1013, #993). Annotate it here,
            # while the loose edges file exists. Same isolation as above: a
            # bookkeeping failure must not stop the archive from shipping.
            stats_name = stats_filename_from_config(config)
            if stats_name:
                try:
                    annotate_graph_stats(
                        Path(stats_name),
                        edges_file,
                        provenance_config,
                        _repo_root(),
                        edges_archive=(published_output_dir or output_dir) / archive.relative_to(output_dir)
                        if dest.get("compression") == "tar.gz"
                        else None,
                        published_edges_file=(published_output_dir or output_dir) / edges_file.relative_to(output_dir),
                        finalized_nodes_file=nodes_file,
                    )
                    print(f"[merge-stats] {stats_name}: provenance and raw predicate counts written")
                except Exception as exc:  # noqa: BLE001
                    print(f"[merge-stats] annotation skipped: {exc}")
                    # Keep the failed staged file private, rather than publish
                    # pre-normalization stats as a description of this graph.
                    failed_stats.add(Path(stats_name))

        if nodes_file.is_file() and edges_file.is_file():
            stats_name = stats_filename_from_config(config)
            provenance = build_provenance(
                provenance_config, _repo_root(), ignore=(Path(stats_name),) if stats_name else ()
            )
            diagnostic = config.get("configuration", {}).get("allow_unfinalized_sources", False)
            provenance["source_finalization"] = {"required": not diagnostic, "diagnostic_opt_out": diagnostic}
            if dest.get("compression") == "tar.gz":
                _rewrite_tarball(archive, [nodes_file, edges_file, reference_report], provenance=provenance)
                if extracted_from_archive:
                    # KGX didn't leave loose TSVs before, so don't leave them now.
                    nodes_file.unlink(missing_ok=True)
                    edges_file.unlink(missing_ok=True)
            else:
                manifest_file = output_dir / f"{base}_manifest.json"
                write_loose_manifest(manifest_file, [nodes_file, edges_file, reference_report], provenance)
                written.add(manifest_file)

        written |= {nodes_file, edges_file, reference_report, archive}

    _warn_about_stale_siblings(output_dir, written)
    return failed_stats


def _warn_about_stale_siblings(output_dir: Path, written: set) -> None:
    """
    Report merged artifacts in the output directory that this run did not write.

    ``data/merged/`` is where consumers look, and it accumulates. A reviewer of
    #826 read ``merged-kg_default_{nodes,edges}.tsv`` — seven months old, 1.2 GB,
    sitting beside the current tarball — and reported the graph as 1.51M/6.13M
    against the tarball's 2.85M/14.66M, then flagged the difference as an
    unexplained discrepancy. Both numbers were right about different files, and
    nothing but the mtime said which was current (#828).

    Warns rather than deletes. These are large, untracked, and may be someone's
    deliberate copy; silently removing a gigabyte of another person's output is
    not a merge step's call to make.

    :param output_dir: The merge output directory.
    :param written: Paths this run produced, which are never reported.
    """
    if not output_dir.is_dir():
        return
    stale = sorted(
        p for p in output_dir.glob("merged-kg*") if p.is_file() and p not in written and not p.name.endswith(".yaml")
    )
    if not stale:
        return
    print(
        f"[merge-cleanup] {len(stale)} older merged artifact(s) remain in {output_dir}/ "
        "and were NOT written by this run — anything reading them gets the previous graph:"
    )
    for path in stale:
        size_mb = path.stat().st_size / 1_048_576
        age_days = (time.time() - path.stat().st_mtime) / 86400.0
        print(f"[merge-cleanup]   {path.name}  ({size_mb:,.0f} MB, {age_days:.0f} days old)")
    print("[merge-cleanup] Remove them once you are sure nothing depends on them.")


def _iter_clean_lines(path: Path):
    r"""Normalize transport CRLF only; embedded controls are source errors, never erased."""
    with open(path, "r", newline="\n") as src:
        for line in src:
            if line.endswith("\r\n"):
                line = line[:-2] + "\n"
            if "\r" in line:
                raise ValueError(f"{path}: embedded carriage return requires source finalization")
            yield line


def _log_schema_diff(kind: str, path: Path, in_header: List[str], out_header: List[str]) -> None:
    """Log the before/after schema so reviewers can see when this step is a no-op."""
    dropped = [c for c in in_header if c not in out_header]
    added = [c for c in out_header if c not in in_header]
    duplicates = [c for c in set(in_header) if in_header.count(c) > 1]
    if not (dropped or added or duplicates) and in_header == out_header:
        print(f"[merge-cleanup] {kind} {path.name}: schema already canonical (no-op)")
        return
    print(f"[merge-cleanup] {kind} {path.name}: dropped={dropped} added={added} deduped={duplicates}")


def _normalize_nodes_tsv(path: Path) -> None:
    """Dedup node columns, drop auxiliary KGX columns, order by canonical header."""
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, newline="") as tmp:
        tmp_path = Path(tmp.name)
        reader = csv.reader(_iter_clean_lines(path), delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            header = next(reader)
        except StopIteration:
            tmp_path.unlink(missing_ok=True)
            return
        keep_indices, out_header = _resolve_column_plan(
            header, CANONICAL_NODE_HEADER, NODE_COLUMNS_TO_DROP, extension_columns=set()
        )
        _log_schema_diff("nodes", path, header, out_header)
        writer = tsv_writer(tmp, quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(out_header)
        for row in reader:
            writer.writerow(_project_row(row, keep_indices))
    tmp_path.replace(path)


def _normalize_edges_tsv(path: Path) -> None:
    """Dedup edge columns, drop `id`/`meta`, merge `knowledge_source` into primary."""
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, newline="") as tmp:
        tmp_path = Path(tmp.name)
        reader = csv.reader(_iter_clean_lines(path), delimiter="\t", quoting=csv.QUOTE_NONE)
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
        writer = tsv_writer(tmp, quoting=csv.QUOTE_NONE, quotechar=None)
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
        """Append column ``name`` (with all source indices) to the output plan."""
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
        values = {row[idx] for idx in group if idx < len(row) and row[idx]}
        if len(values) > 1:
            raise ValueError("Conflicting duplicate KGX columns cannot be silently coalesced")
        out.append(next(iter(values), ""))
    return out


def _rewrite_tarball(archive: Path, files: List[Path], provenance: Optional[Dict] = None) -> None:
    """Atomically re-archive cleaned TSVs with a portable manifest (#1075)."""
    write_graph_archive(archive, files, provenance)
