"""Resolve GO references before source publication using explicit local authority evidence."""

import csv
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS_CATEGORY,
    CATEGORY_COLUMN,
    CELLULAR_COMPONENT_CATEGORY,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    GO_REFERENCE_CONTEXT_COLUMN,
    HAS_PART,
    HAS_PART_PREDICATE,
    ID_COLUMN,
    MOLECULAR_ACTIVITY_CATEGORY,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PART_OF_PREDICATE,
    PART_OF_RELATION,
    PREDICATE_COLUMN,
    PROVIDED_BY_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.provenance import knowledge_source_tokens, serialize_knowledge_sources
from kg_microbe.utils.tsv_io import tsv_dict_writer

_ASPECTS = {
    "biological_process": BIOLOGICAL_PROCESS_CATEGORY,
    "molecular_function": MOLECULAR_ACTIVITY_CATEGORY,
    "cellular_component": CELLULAR_COMPONENT_CATEGORY,
}
_GO_ID = re.compile(r"GO:\d+$")
_PREDICATES = {
    "rdfs:label": "label",
    "owl:deprecated": "deprecated",
    "IAO:0100001": "replaced_by",
    "IAO:0000115": "definition",
    "http://www.w3.org/2000/01/rdf-schema#label": "label",
    "http://www.w3.org/2002/07/owl#deprecated": "deprecated",
    "http://purl.obolibrary.org/obo/IAO_0100001": "replaced_by",
    "http://purl.obolibrary.org/obo/IAO_0000115": "definition",
}
for _prefix in ("oio:", "oboInOwl:", "http://www.geneontology.org/formats/oboInOwl#"):
    for _suffix, _field in (
        ("hasOBONamespace", "namespace"),
        ("consider", "consider"),
        ("hasAlternativeId", "alternate_ids"),
    ):
        _PREDICATES[_prefix + _suffix] = _field

_CACHE = {}
_REPORT_VERSION = 1
_STRUCTURAL_POLICY_VERSION = 1
_STRUCTURAL_RELATIONS = {
    RDFS_SUBCLASS_OF: SUBCLASS_PREDICATE,
    PART_OF_RELATION: PART_OF_PREDICATE,
    HAS_PART: HAS_PART_PREDICATE,
}
_STRUCTURAL_RELATION_IRIS = {
    "http://www.w3.org/2000/01/rdf-schema#subClassOf": RDFS_SUBCLASS_OF,
    "http://purl.obolibrary.org/obo/BFO_0000050": PART_OF_RELATION,
    "http://purl.obolibrary.org/obo/BFO_0000051": HAS_PART,
}
_REPORT_FIELDS = [
    "source_file",
    "record_kind",
    "original_id",
    "canonical_id",
    "disposition",
    "authority",
    "authority_sha256",
    "replacement_chain",
    "consider",
    "original_record_json",
    "candidate_record_json",
    "bundle_fingerprint",
]


class GoReferenceError(ValueError):
    """A GO reference lacks exact usable evidence in the selected authority."""


@dataclass(frozen=True)
class GoTerm:
    """Immutable metadata for one exact GO identifier in an authority release."""

    identifier: str
    label: str
    namespace: str
    deprecated: bool = False
    replaced_by: tuple[str, ...] = ()
    consider: tuple[str, ...] = ()
    alternate_ids: tuple[str, ...] = ()
    definition: str = ""


@dataclass(frozen=True)
class GoResolution:
    """An evidence-backed identity decision, including retained historical references."""

    original_id: str
    canonical_id: str
    label: str
    namespace: str
    category: str
    deprecated: bool
    replacement_chain: tuple[str, ...]
    consider: tuple[str, ...]
    disposition: str
    definition: str = ""

    def node_fields(self) -> dict[str, str]:
        """Return authoritative KGX declaration fields without inventing assay evidence."""
        description = self.definition
        if self.deprecated:
            note = "Historical GO reference; deprecated in the selected GO authority."
            if self.consider:
                note += " GO consider suggestions (not identity replacements): " + ", ".join(self.consider) + "."
            description = " ".join(value for value in (description, note) if value)
        return {
            ID_COLUMN: self.canonical_id,
            NAME_COLUMN: self.label,
            CATEGORY_COLUMN: self.category,
            DEPRECATED_COLUMN: "true" if self.deprecated else "",
            DESCRIPTION_COLUMN: " ".join(description.split()),
            PROVIDED_BY_COLUMN: "infores:go",
        }


@dataclass(frozen=True)
class GoAuthority:
    """Read-only, pickleable GO evidence; resolution performs no database or network IO."""

    records: Mapping[str, GoTerm]
    authority_path: str = ""
    authority_sha256: str = ""
    source_paths: tuple[str, ...] = ()
    structural_edges: frozenset[tuple[str, str, str]] | None = None

    def __post_init__(self):
        """Freeze the records and reject contradictory alternative identities."""
        records = dict(self.records)
        aliases = {}
        for identifier, term in records.items():
            if term.identifier != identifier or not _GO_ID.fullmatch(identifier):
                raise ValueError(f"Invalid GO authority identifier: {identifier}")
            if (not term.label or term.namespace not in _ASPECTS) and not (
                term.deprecated and len(term.replaced_by) == 1
            ):
                raise ValueError(f"GO authority lacks a unique label/aspect for {identifier}")
            for alternate in term.alternate_ids:
                if not _GO_ID.fullmatch(alternate) or (alternate in aliases and aliases[alternate] != identifier):
                    raise ValueError(f"Conflicting GO alternative identifier: {alternate}")
                aliases[alternate] = identifier
        object.__setattr__(self, "records", MappingProxyType(records))
        object.__setattr__(self, "_aliases", MappingProxyType(aliases))
        if self.structural_edges is not None:
            structural_edges = frozenset(tuple(edge) for edge in self.structural_edges)
            for edge in structural_edges:
                if (
                    len(edge) != 3
                    or not _GO_ID.fullmatch(edge[0])
                    or edge[1] not in _STRUCTURAL_RELATIONS
                    or not _GO_ID.fullmatch(edge[2])
                ):
                    raise ValueError(f"Invalid asserted GO structural edge: {edge}")
            object.__setattr__(self, "structural_edges", structural_edges)
        for identifier in records:
            self.resolve(identifier)  # Validate exact chains before a producer opens its outputs.
        for alternate, owner in aliases.items():
            if self.resolve(alternate).canonical_id != self.resolve(owner).canonical_id:
                raise ValueError(f"Conflicting GO alternative identity: {alternate} -> {owner}")

    def __reduce__(self):
        """Recreate mapping proxies when a multiprocessing worker unpickles this authority."""
        return type(self), (
            dict(self.records),
            self.authority_path,
            self.authority_sha256,
            self.source_paths,
            self.structural_edges,
        )

    @classmethod
    def from_statements(
        cls,
        statements: Iterable[tuple],
        *,
        authority_path: str = "",
        authority_sha256: str = "",
        source_paths: tuple[str, ...] = (),
        structural_edges: frozenset[tuple[str, str, str]] | None = None,
    ):
        """Build from exact SemSQL-shaped rows, also supporting immutable offline fixtures."""
        metadata = defaultdict(lambda: defaultdict(set))
        for subject, predicate, obj, value in statements:
            subject = _compact_go(subject or "")
            field = _PREDICATES.get(predicate)
            if field is None or not _GO_ID.fullmatch(subject):
                continue
            result = obj or value
            if result is not None and str(result).strip():
                metadata[subject][field].add(str(result).strip())
        terms = {}
        for identifier, fields in metadata.items():
            for scalar in ("label", "namespace", "deprecated"):
                if len(fields.get(scalar, ())) > 1:
                    raise ValueError(f"Conflicting GO {scalar}: {identifier}")
            terms[identifier] = GoTerm(
                identifier=identifier,
                label=next(iter(fields.get("label", ())), ""),
                namespace=next(iter(fields.get("namespace", ())), ""),
                deprecated=next(iter(fields.get("deprecated", ())), "false").lower() in {"true", "1"},
                replaced_by=tuple(sorted(_compact_go(value) for value in fields.get("replaced_by", ()))),
                consider=tuple(sorted(_compact_go(value) for value in fields.get("consider", ()))),
                alternate_ids=tuple(sorted(_compact_go(value) for value in fields.get("alternate_ids", ()))),
                definition="\n".join(sorted(fields.get("definition", ()))),
            )
        if not terms:
            raise ValueError("GO authority contains no usable GO metadata")
        return cls(terms, str(authority_path), authority_sha256, source_paths, structural_edges)

    def resolve(self, identifier: str) -> GoResolution:
        """Follow unique explicit identity links; retain obsolete terms with only suggestions."""
        original = identifier
        current, chain = _compact_go(identifier), []
        while True:
            if current in chain:
                raise ValueError(f"Cyclic GO replacement: {' -> '.join([*chain, current])}")
            chain.append(current)
            if current not in self.records and current in self._aliases:
                current = self._aliases[current]
                continue
            term = self.records.get(current)
            if term is None:
                raise GoReferenceError(f"No exact GO authority record for {current} (reference {original})")
            if term.deprecated and len(term.replaced_by) == 1:
                current = term.replaced_by[0]
                continue
            if not term.label or term.namespace not in _ASPECTS:
                raise ValueError(f"GO authority lacks a unique label/aspect for {current}")
            if term.deprecated:
                disposition = "historical_ambiguous_replacement" if term.replaced_by else "historical_obsolete"
            else:
                disposition = "exact_replacement" if len(chain) > 1 else "current"
            return GoResolution(
                original,
                current,
                term.label,
                term.namespace,
                _ASPECTS[term.namespace],
                term.deprecated,
                tuple(chain),
                term.consider,
                disposition,
                term.definition,
            )


def _compact_go(identifier: str) -> str:
    """Compact only the canonical GO OBO IRI; no label or suffix identity inference."""
    prefix = "http://purl.obolibrary.org/obo/GO_"
    return "GO:" + identifier[len(prefix) :] if identifier.startswith(prefix) else identifier


def _prepare_go_database(raw_dir: Path) -> Path:
    """Validate/build the selected local authority before any producer uses it."""
    from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError, _ensure_go_db

    path = raw_dir / "go.db"
    if not _ensure_go_db(str(path), source_path=raw_dir / "go.owl"):
        raise OntologyDbUnavailableError(f"No usable local GO authority at {path}")
    return path


def _file_key(path: Path) -> tuple:
    """Key successful in-process caches by file identity, including replacement and modification."""
    stat = path.stat()
    return str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _authority_key(path: Path, raw_dir: Path) -> tuple:
    """Invalidate prepared metadata when either its database or selected OWL input changes."""
    sources = tuple(_file_key(source) for source in (raw_dir / "go.owl", raw_dir / "go.owl.gz") if source.exists())
    return _file_key(path), sources


def _load_asserted_structural_edges(connection) -> frozenset[tuple[str, str, str]]:
    """Read exact asserted SemSQL edges, never an entailed or reflexive closure."""
    relations = (*_STRUCTURAL_RELATIONS, *_STRUCTURAL_RELATION_IRIS)
    placeholders = ",".join("?" for _ in relations)
    query = (
        "SELECT subject,predicate,object FROM edge "  # noqa: S608 — only bound placeholders are interpolated
        f"WHERE predicate IN ({placeholders})"
    )
    edges = set()
    for subject, relation, obj in connection.execute(query, relations):
        subject, obj = _compact_go(subject or ""), _compact_go(obj or "")
        relation = _STRUCTURAL_RELATION_IRIS.get(relation, relation)
        if _GO_ID.fullmatch(subject) and _GO_ID.fullmatch(obj):
            edges.add((subject, relation, obj))
    return frozenset(edges)


def load_go_authority(raw_dir: Path) -> GoAuthority:
    """Load verified local GO metadata once per authority file version, with an exact byte digest."""
    from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

    raw_dir = Path(raw_dir)
    try:
        path = raw_dir / "go.db"
        if path.exists():
            key = _authority_key(path, raw_dir)
            if key in _CACHE:
                return _CACHE[key]
        path = _prepare_go_database(raw_dir)
        key = _authority_key(path, raw_dir)
        if key in _CACHE:
            return _CACHE[key]
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        placeholders = ",".join("?" for _ in _PREDICATES)
        query = (
            "SELECT subject,predicate,object,value FROM statements "  # noqa: S608 — only bound placeholders are interpolated
            f"WHERE subject LIKE 'GO:%' AND predicate IN ({placeholders})"
        )
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            structural_edges = _load_asserted_structural_edges(connection)
            rows = connection.execute(query, tuple(_PREDICATES))
            authority = GoAuthority.from_statements(
                rows,
                authority_path=str(path.resolve()),
                authority_sha256=digest.hexdigest(),
                source_paths=tuple(
                    str(source.resolve()) for source in (raw_dir / "go.owl", raw_dir / "go.owl.gz") if source.exists()
                ),
                structural_edges=structural_edges,
            )
        if key != _authority_key(path, raw_dir):
            raise ValueError(f"GO authority changed while being read: {path}")
        if len(_CACHE) >= 4:
            _CACHE.clear()
        _CACHE[key] = authority
        return authority
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise OntologyDbUnavailableError(f"Cannot load exact GO authority {path}: {exc}") from exc


def _rows(path: Path, quoting=csv.QUOTE_NONE):
    """Stream strict, header-aware KGX rows, including quoted tabs and embedded newlines."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=quoting)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"Invalid TSV header: {path}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed TSV row at {path}:{reader.line_num}")
            yield row


def _header(path: Path, quoting=csv.QUOTE_NONE) -> list[str]:
    """Read one source header without inferring column positions."""
    with path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle, delimiter="\t", quoting=quoting), [])
    if not header or len(header) != len(set(header)):
        raise ValueError(f"Invalid TSV header: {path}")
    return header


def _graph_writer(handle, fields, quoting):
    """Preserve literal quote characters when using KGX's unquoted TSV dialect."""
    return tsv_dict_writer(
        handle, fieldnames=fields, quoting=quoting, quotechar=None if quoting == csv.QUOTE_NONE else '"'
    )


def write_empty_go_report(report_path: Path) -> None:
    """Atomically clear a stale GO audit without scanning authority files or rewriting graph bytes."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(report_path, encoding="utf-8", newline="") as handle:
        writer = tsv_dict_writer(handle, fieldnames=_REPORT_FIELDS)
        writer.writeheader()


def _sha256_file(path: Path) -> str:
    """Fingerprint graph-scale TSV bytes using bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bundle_fingerprint(node_paths, edge_paths):
    """Bind reusable diagnostic evidence to the exact paired source output bytes."""
    return [
        {"kind": kind, "file": path.name, "sha256": _sha256_file(path)}
        for kind, paths in (("nodes", node_paths), ("edges", edge_paths))
        for path in paths
    ]


def _authority_fingerprint(authority):
    """Identify exact metadata even for immutable in-memory test authorities with no database path."""
    digest = hashlib.sha256()
    for identifier in sorted(authority.records):
        digest.update(json.dumps(vars(authority.records[identifier]), sort_keys=True).encode("utf-8"))
        digest.update(b"\n")
    structural_digest = None
    if authority.structural_edges is not None:
        structural_digest = hashlib.sha256(
            json.dumps(sorted(authority.structural_edges), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "path": authority.authority_path,
        "sha256": authority.authority_sha256,
        "metadata_sha256": digest.hexdigest(),
        "structural_edges_sha256": structural_digest,
        "structural_policy_version": _STRUCTURAL_POLICY_VERSION,
    }


def _replacement_structural_axiom(row):
    """Identify replacement-affected GO structure, including previously normalized rows."""
    subject, obj = row[SUBJECT_COLUMN], row[OBJECT_COLUMN]
    if not (_GO_ID.fullmatch(subject) and _GO_ID.fullmatch(obj)):
        return None
    relation, predicate = row.get(RELATION_COLUMN), row.get(PREDICATE_COLUMN)
    if relation not in _STRUCTURAL_RELATIONS and predicate not in _STRUCTURAL_RELATIONS.values():
        return None
    history = json.loads(row.get(GO_REFERENCE_CONTEXT_COLUMN) or "[]")
    if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
        raise GoReferenceError("Invalid GO replacement history for a structural assertion")
    affected = any(
        item.get("column") in (SUBJECT_COLUMN, OBJECT_COLUMN)
        and _compact_go(item.get("original_id") or "") != _compact_go(item.get("canonical_id") or "")
        for item in history
    )
    if not affected:
        return None
    if _STRUCTURAL_RELATIONS.get(relation) != predicate:
        raise GoReferenceError(
            f"Inconsistent replacement-affected GO structural predicate/relation: {predicate}/{relation}"
        )
    return subject, relation, obj


def _report_checkpoint(report_path):
    """Read a bounded exact-bundle checkpoint; legacy reports without one cannot be safely inherited."""
    checkpoint = None
    if report_path.is_file():
        for row in _rows(report_path, csv.QUOTE_MINIMAL):
            if row.get("record_kind") == "bundle_checkpoint":
                checkpoint = json.loads(row["bundle_fingerprint"])
                if not isinstance(checkpoint, dict):
                    raise ValueError(f"Invalid GO audit checkpoint: {report_path}")
    return checkpoint


def normalize_go_bundle(
    node_paths: Sequence[Path],
    edge_paths: Sequence[Path],
    authority: GoAuthority,
    report_path: Path,
    *,
    quoting=csv.QUOTE_NONE,
) -> dict[str, int]:
    """
    Normalize one source's staged files before publication, preserving observation evidence.

    All references are resolved before writes begin, then complete replacements
    are staged. The caller owns whole-source publication atomicity: this helper
    never edits a merged graph. Memory holds GO identifiers/declarations only,
    not the complete edge graph. Observation rows and source evidence are
    preserved. Replacement-affected GO-to-GO structural rows require exact
    asserted-authority support; unsupported candidates are quarantined in the
    audit rather than transferred into a current hierarchy.
    """
    node_paths, edge_paths = [Path(path) for path in node_paths], [Path(path) for path in edge_paths]
    report_path = Path(report_path)
    if not node_paths:
        raise ValueError("GO normalization requires at least one source node file")
    if len(set([*node_paths, *edge_paths, report_path])) != len(node_paths) + len(edge_paths) + 1:
        raise ValueError("GO bundle file paths must be distinct")
    identifiers, referenced = set(), set()
    for path in node_paths:
        for row in _rows(path, quoting):
            if _compact_go(row[ID_COLUMN]).startswith("GO:"):
                identifiers.add(row[ID_COLUMN])
    for path in edge_paths:
        for row in _rows(path, quoting):
            for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
                if _compact_go(row[column]).startswith("GO:"):
                    identifiers.add(row[column])
                    referenced.add(row[column])
    if not identifiers:
        write_empty_go_report(report_path)
        return {}
    resolutions = {identifier: authority.resolve(identifier) for identifier in sorted(identifiers)}
    input_fingerprint = _bundle_fingerprint(node_paths, edge_paths)
    authority_fingerprint = _authority_fingerprint(authority)
    previous = _report_checkpoint(report_path)
    retain_audit = bool(
        previous and previous.get("version") == _REPORT_VERSION and previous.get("bundle") == input_fingerprint
    )
    if retain_audit and previous.get("authority") == authority_fingerprint:
        return {"already_normalized": 1}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with TemporaryDirectory(prefix=".go-normalization-", dir=report_path.parent) as stage:
        stage = Path(stage)
        replacements = []
        staged_report = stage / "report.tsv"
        with staged_report.open("w", encoding="utf-8", newline="") as report:
            writer = tsv_dict_writer(report, fieldnames=_REPORT_FIELDS)
            writer.writeheader()
            report_rows = set()

            def emit_report(row):
                """Stream unique audit records without retaining their large original-row payloads."""
                normalized = {field: row.get(field, "") for field in _REPORT_FIELDS}
                fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).digest()
                if fingerprint not in report_rows:
                    writer.writerow(normalized)
                    report_rows.add(fingerprint)

            if retain_audit:
                for previous_row in _rows(report_path, csv.QUOTE_MINIMAL):
                    if previous_row.get("record_kind") != "bundle_checkpoint":
                        emit_report(previous_row)

            def record(path, kind, identifier, original=None):
                """Retain complete changed-record evidence alongside the authority decision."""
                decision = resolutions[identifier]
                emit_report(
                    {
                        "source_file": Path(path).name if path else "",
                        "record_kind": kind,
                        "original_id": identifier,
                        "canonical_id": decision.canonical_id,
                        "disposition": decision.disposition,
                        "authority": authority.authority_path,
                        "authority_sha256": authority.authority_sha256,
                        "replacement_chain": json.dumps(decision.replacement_chain),
                        "consider": json.dumps(decision.consider),
                        "original_record_json": json.dumps(original, ensure_ascii=False, sort_keys=True)
                        if original is not None
                        else "",
                    }
                )

            declared = set()
            for number, path in enumerate(node_paths):
                fields = _header(path, quoting)
                for field in (NAME_COLUMN, CATEGORY_COLUMN, PROVIDED_BY_COLUMN, DEPRECATED_COLUMN, DESCRIPTION_COLUMN):
                    if field not in fields and identifiers:
                        fields.append(field)
                target = stage / f"nodes-{number}.tsv"
                with target.open("w", encoding="utf-8", newline="") as handle:
                    output = _graph_writer(handle, fields, quoting)
                    output.writeheader()
                    seen = set()
                    for original in _rows(path, quoting):
                        identifier = original[ID_COLUMN]
                        row = dict(original)
                        if identifier in resolutions:
                            decision = resolutions[identifier]
                            row.update(decision.node_fields())
                            if identifier == decision.canonical_id and original.get(DESCRIPTION_COLUMN):
                                description = original[DESCRIPTION_COLUMN]
                                extra = row[DESCRIPTION_COLUMN]
                                row[DESCRIPTION_COLUMN] = (
                                    description if not extra or extra in description else description + " " + extra
                                )
                            # Attribution of the source declaration survives authority enrichment.
                            row[PROVIDED_BY_COLUMN] = serialize_knowledge_sources(
                                [
                                    *knowledge_source_tokens(original.get(PROVIDED_BY_COLUMN)),
                                    "infores:go",
                                ]
                            )
                            declared.add(decision.canonical_id)
                            if row != original:
                                record(path, "node", identifier, original)
                                counts["normalized_node_rows"] += 1
                            fingerprint = tuple(row.get(field, "") for field in fields)
                            if fingerprint in seen:
                                counts["duplicate_go_declarations"] += 1
                                continue
                            seen.add(fingerprint)
                        output.writerow(row)
                replacements.append((target, path))
            missing = sorted({resolutions[identifier].canonical_id for identifier in referenced} - declared)
            if missing:
                by_canonical = {decision.canonical_id: decision for decision in resolutions.values()}
                target = replacements[0][0]
                fields = _header(target, quoting)
                with target.open("a", encoding="utf-8", newline="") as handle:
                    output = _graph_writer(handle, fields, quoting)
                    for identifier in missing:
                        output.writerow(by_canonical[identifier].node_fields())
                        counts["added_reference_nodes"] += 1
            for number, path in enumerate(edge_paths):
                fields = _header(path, quoting)
                remapped = any(identifier != result.canonical_id for identifier, result in resolutions.items())
                if remapped:
                    for field in ("original_subject", "original_object", GO_REFERENCE_CONTEXT_COLUMN):
                        if field not in fields:
                            fields.append(field)
                target = stage / f"edges-{number}.tsv"
                with target.open("w", encoding="utf-8", newline="") as handle:
                    output = _graph_writer(handle, fields, quoting)
                    output.writeheader()
                    for original in _rows(path, quoting):
                        row = dict(original)
                        for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
                            identifier = original[column]
                            if identifier in resolutions and identifier != resolutions[identifier].canonical_id:
                                decision = resolutions[identifier]
                                row[column] = decision.canonical_id
                                row["original_" + column] = row.get("original_" + column) or identifier
                                history = json.loads(row.get(GO_REFERENCE_CONTEXT_COLUMN) or "[]")
                                if not isinstance(history, list):
                                    raise ValueError(f"Invalid scalar GO reference history in {path}: {history!r}")
                                history.append(
                                    {
                                        "column": column,
                                        "original_id": identifier,
                                        "canonical_id": decision.canonical_id,
                                        "replacement_chain": decision.replacement_chain,
                                        "authority": authority.authority_path,
                                        "authority_sha256": authority.authority_sha256,
                                    }
                                )
                                row[GO_REFERENCE_CONTEXT_COLUMN] = json.dumps(
                                    history, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                                record(path, "edge", identifier, original)
                                counts["remapped_endpoints"] += 1
                        axiom = _replacement_structural_axiom(row)
                        if axiom is not None:
                            if authority.structural_edges is None:
                                raise GoReferenceError(
                                    "Asserted GO structural authority is required for replacement-affected axioms"
                                )
                            if axiom not in authority.structural_edges:
                                emit_report(
                                    {
                                        "source_file": path.name,
                                        "record_kind": "quarantined_structural_edge",
                                        "original_id": original[SUBJECT_COLUMN],
                                        "canonical_id": row[SUBJECT_COLUMN],
                                        "disposition": "unsupported_replacement_structural_axiom",
                                        "authority": authority.authority_path,
                                        "authority_sha256": authority.authority_sha256,
                                        "original_record_json": json.dumps(
                                            original, ensure_ascii=False, sort_keys=True
                                        ),
                                        "candidate_record_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
                                    }
                                )
                                counts["quarantined_structural_edges"] += 1
                                continue
                            counts["supported_replacement_structural_edges"] += 1
                        output.writerow(row)
                replacements.append((target, path))
            for identifier, result in resolutions.items():
                record("", "resolution", identifier)
                counts[result.disposition] += 1
            # Use source basenames rather than ephemeral staging names so the
            # checkpoint remains valid after caller-owned source publication.
            output_fingerprint = [
                {
                    "kind": "nodes" if index < len(node_paths) else "edges",
                    "file": final.name,
                    "sha256": _sha256_file(staged),
                }
                for index, (staged, final) in enumerate(replacements)
            ]
            emit_report(
                {
                    "record_kind": "bundle_checkpoint",
                    "bundle_fingerprint": json.dumps(
                        {"version": _REPORT_VERSION, "authority": authority_fingerprint, "bundle": output_fingerprint},
                        sort_keys=True,
                    ),
                }
            )
        replacements.append((staged_report, report_path))
        for staged, final in replacements:
            os.replace(staged, final)
    return dict(counts)
