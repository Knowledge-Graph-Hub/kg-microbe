"""
Build an offline, conservative MIM integration candidate for human review.

Historical entity-wide source unions cannot establish assertion-level support.
Reset their identity-connected scope, then reconstruct claims from explicit
current inputs. Withheld MIM mappings are not global scientific exclusions.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import (
    IDENTITY_POLICY,
    NAME_SCOPE_POLICY,
    accepted_name_scope,
    ingredient_case_sensitive_name_scope,
    ingredient_mapping_allowed,
    ingredient_name_scopes,
    ingredient_name_target,
    ingredient_xref_allowed,
)
from scripts import consolidate_chemical_mappings as consolidator
from scripts.mapping_provenance import context_paths, reproducibility_context
from scripts.mim_reviewed_release import validate_reviewed_bundle

INDEPENDENT_SOURCE_KINDS = frozenset(
    {
        "metabolite_json",
        "manual_annotations",
        "metatraits_chemical_mappings",
    }
)
_INDEPENDENT_TSV_FIELDS = {
    "manual_annotations": {"object_id", "object_label", "traits_dataset_term", "action"},
    "metatraits_chemical_mappings": {
        "object_id",
        "object_label",
        "subject_label",
        "subject_label_normalized",
    },
}
_NONIDENTITY = {"skos:closeMatch", "skos:narrowMatch", "skos:broadMatch"}
_NON_XREF_PREFIXES = {
    "kgm.name",
    "obo",
    "skos",
    "semapv",
    "orcid",
    "MIM",
    "MediaIngredientMech",
    "pubmed",
    "pmc",
    "doi",
    "patent",
    "citexplore",
    "ppr",
    "wikipedia.en",
}
_REQUIRED_FIELDS = {
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "object_source",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "object_formula",
    "object_category",
}


@dataclass(frozen=True)
class IndependentSource:
    """Select a specific offline loader and its required current source file."""

    kind: str
    path: Path


@dataclass(frozen=True)
class CandidateResult:
    """Identify an atomic candidate bundle and its audit report."""

    directory: Path
    candidate_path: Path
    quarantine_path: Path
    report_path: Path
    report: dict


def _hash(path):
    """Fingerprint a required input without loading the full file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open(path):
    """Open a plain or gzipped TSV for streaming reads."""
    return (
        gzip.open(path, "rt", encoding="utf-8", newline="")
        if str(path).endswith(".gz")
        else Path(path).open(encoding="utf-8", newline="")
    )


def _header(path):
    """Read only the metadata and column header of an SSSOM input."""
    metadata_lines = []
    with _open(path) as handle:
        for line in handle:
            if not line.startswith("#"):
                fields = next(csv.reader([line], delimiter="\t"))
                break
            metadata_lines.append(line[1:].removeprefix(" "))
        else:
            raise ValueError(f"Missing TSV header: {path}")
    metadata = yaml.safe_load("".join(metadata_lines)) or {}
    if not isinstance(metadata, dict) or len(fields) != len(set(fields)):
        raise ValueError(f"Invalid SSSOM header: {path}")
    return metadata, fields


def _rows(path):
    """Stream strict TSV records, skipping only initial SSSOM metadata."""
    with _open(path) as handle:
        for line in handle:
            if not line.startswith("#"):
                fields = next(csv.reader([line], delimiter="\t"))
                break
        else:
            raise ValueError(f"Missing TSV header: {path}")
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"Invalid TSV columns: {path}")
        for row in csv.DictReader(handle, fieldnames=fields, delimiter="\t", strict=True):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed TSV row width: {path}")
            yield row


def _mim_source(source):
    """Recognize the historical MIM/CultureBotAI entity provenance families."""
    families = ("mediaingredientmech_reviewed", "culturebotai_reviewed", "complex_ingredients")
    for token in source.split("|"):
        token = token.strip().removeprefix("kgm:")
        if token.startswith(("MIM:", "MediaIngredientMech:")):
            return True
        if any(token == family or token.startswith(family + "[") for family in families):
            return True
    return False


def _mim_row(row):
    """Identify MIM-origin assertions, including translated historical parents."""
    return row["subject_id"].startswith(("MIM:", "MediaIngredientMech:")) or _mim_source(row.get("source", ""))


def _historical_policy_rejection(row):
    """Reject reviewed lexical/exact claims without banning targets or weaker relations."""
    subject, target = row["subject_id"], row["object_id"]
    if subject.startswith("kgm.name:") and row["predicate_id"] in {"skos:exactMatch", "skos:closeMatch"}:
        if not ingredient_mapping_allowed(row.get("subject_label", ""), target):
            return "reviewed_identity_policy_name"
    elif row["predicate_id"] == "skos:exactMatch" and not ingredient_xref_allowed(subject, target):
        return "reviewed_identity_policy_xref"
    return ""


def _candidate_name_lookup(name, names, declared):
    """Mirror finite runtime query scopes without putting case-sensitive aliases in a shared key."""
    recognized, target = ingredient_case_sensitive_name_scope(name)
    if recognized:
        return target if target in declared and ingredient_mapping_allowed(name, target) else None
    normalized = runtime.normalize_name(name)
    if ingredient_case_sensitive_name_scope(normalized)[0]:
        return None
    return names.get(normalized)


def _historical_object_label_rejected(row):
    """Detect unsafe descriptive metadata separately from an otherwise admissible claim."""
    label = row.get("object_label", "")
    return bool(label and not ingredient_mapping_allowed(label, row["object_id"]))


class _Components:
    """Track undirected identity connectivity, including shared external xrefs."""

    def __init__(self):
        """Start an empty union-find index."""
        self.parents = {}

    def root(self, value):
        """Find a component with path compression."""
        self.parents.setdefault(value, value)
        while self.parents[value] != value:
            self.parents[value] = self.parents[self.parents[value]]
            value = self.parents[value]
        return value

    def join(self, left, right):
        """Join identities without interpreting relationship direction."""
        left, right = self.root(left), self.root(right)
        if left != right:
            self.parents[right] = left


@dataclass
class _Entity:
    """Accumulate freshly supported attributes and per-assertion provenance."""

    labels: set = field(default_factory=set)
    names: dict = field(default_factory=lambda: defaultdict(set))
    xrefs: dict = field(default_factory=lambda: defaultdict(set))
    formulas: set = field(default_factory=set)
    categories: set = field(default_factory=set)

    @property
    def label(self):
        """Prefer MIM, native ontology, then current independent labels stably."""
        return min(self.labels)[2] if self.labels else ""

    @property
    def formula(self):
        """Choose the highest-priority current nonempty formula."""
        return min(self.formulas)[1] if self.formulas else ""


class _Evidence:
    """Collect only specific current claims, without synonym propagation."""

    def __init__(self, prefixes):
        """Remember known identity prefixes and fresh entity assertions."""
        self.records = {}
        self.prefixes = prefixes - _NON_XREF_PREFIXES

    def allowed_xref(self, curie, xref):
        """Apply existing identity exclusions and omit descriptive references."""
        return (
            isinstance(xref, str)
            and re.fullmatch(r"[^:\s]+:\S+", xref) is not None
            and xref.split(":", 1)[0] in self.prefixes
            and xref != curie
            and ingredient_xref_allowed(xref, curie)
            and (xref, curie) not in consolidator.KNOWN_BAD_XREF_PAIRS
            and (curie, xref) not in consolidator.KNOWN_BAD_XREF_PAIRS
        )

    def add(self, curie, label="", names=(), xrefs=(), source="", priority=1, formula="", category=""):
        """Register labels and equivalents only with their direct current source."""
        if not consolidator.is_accepted_primary(curie):
            return
        record = self.records.setdefault(curie, _Entity())

        def clean(value):
            return value.strip() if isinstance(value, str) else ""

        label = clean(label)
        if label and ingredient_mapping_allowed(label, curie):
            record.labels.add((-priority, source, label))
            record.names[label].add(source)
        for name in names:
            name = clean(name)
            if name and ingredient_mapping_allowed(name, curie):
                record.names[name].add(source)
        for xref in xrefs:
            xref = clean(xref)
            if self.allowed_xref(curie, xref):
                record.xrefs[xref].add(source)
        if clean(formula):
            record.formulas.add((-priority, clean(formula)))
        if clean(category):
            record.categories.add((-priority, clean(category)))


class _Collector(consolidator.ChemicalMappingConsolidator):
    """Reuse individual offline parsers without constructor side effects or export."""

    def __init__(self, evidence, source):
        """Avoid the original constructor's implicit filesystem discovery."""
        self.evidence = evidence
        self.source = source
        self.chemicals = {}
        self.mangle_blacklist = set()
        self.hydrate_equivalences = set()

    def add_chemical(self, id, canonical_name="", formula="", synonyms=None, xrefs=None, source="", priority=1):
        """Preserve assertion provenance at each parser call instead of flattening it."""
        if _mim_source(source):
            raise ValueError("MIM evidence cannot enter through an independent loader")
        self.evidence.add(
            id,
            canonical_name,
            synonyms or (),
            xrefs or (),
            f"independent:{self.source.kind}:{self.source.path.name}",
            priority,
            formula,
        )


def _preflight_independent(source):
    """Validate each admitted parser's actual input schema before using its evidence."""
    if source.kind == "metabolite_json":

        def unique(pairs):
            """Reject duplicate JSON identifiers instead of overwriting their labels."""
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate metabolite JSON identifier: {key}")
                result[key] = value
            return result

        data = json.loads(source.path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if (
            not isinstance(data, dict)
            or not data
            or any(
                not re.fullmatch(r"CHEBI:[0-9]+", curie) or not isinstance(label, str) or not label.strip()
                for curie, label in data.items()
            )
        ):
            raise ValueError("Metabolite JSON must map CHEBI identifiers to nonempty string labels")
        return
    required = _INDEPENDENT_TSV_FIELDS[source.kind]
    with source.path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", strict=True)
        columns = reader.fieldnames or []
        if not required.issubset(columns) or len(columns) != len(set(columns)) or any(not field for field in columns):
            raise ValueError(f"Invalid independent TSV columns for {source.kind}: {source.path}")
        count = 0
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed independent TSV row width: {source.path}")
            curie = row["object_id"].strip()
            if not consolidator.is_accepted_primary(curie) or (
                source.kind == "manual_annotations" and not re.fullmatch(r"CHEBI:[0-9]+", curie)
            ):
                raise ValueError(f"Invalid independent TSV object_id: {curie}")
            count += 1
        if not count:
            raise ValueError(f"Required independent TSV contains no evidence rows: {source.path}")


def _load_independent(sources, evidence):
    """Preflight and load only the three independently audited offline source kinds."""
    for source in sources:
        _preflight_independent(source)
    for source in sources:
        collector = _Collector(evidence, source)
        getattr(collector, "load_" + source.kind)(source.path)


def _native_rows(paths):
    """Yield only each ontology file's own namespace, never imported foreign terms."""
    for path in paths:
        if not path.name.endswith("_nodes.tsv"):
            raise ValueError(f"Expected <prefix>_nodes.tsv authority file: {path}")
        namespace = path.name.removesuffix("_nodes.tsv")
        _, fields = _header(path)
        if not {"id", "name", "synonym", "xref", "category"}.issubset(fields):
            raise ValueError(f"Missing ontology node columns: {path}")
        for row in _rows(path):
            if row["id"].split(":", 1)[0].casefold() != namespace.casefold():
                continue
            if row.get("deprecated", "").lower() in {"true", "1"}:
                continue
            yield namespace, row


def _slug(name):
    """Use the existing exporter's lexical identifier convention."""
    normalized = consolidator.normalize_name(name)
    folded = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9_.-]", "", folded.replace(" ", "_").replace("'", "_prime"))


def _serialize(row, fields):
    """Emit sanitized literal TSV compatible with the existing unified reader."""
    return "\t".join(
        str(row.get(field, "") or "").replace("\t", " ").replace("\r", " ").replace("\n", " ") for field in fields
    )


def _write_header(handle, metadata, fields):
    """Write deterministic SSSOM metadata and its column header."""
    for line in yaml.safe_dump(metadata, sort_keys=True, allow_unicode=True, width=100000).splitlines():
        handle.write("# " + line + "\n")
    handle.write("\t".join(fields) + "\n")


def _validate_output(path, metadata, fields):
    """Validate SSSOM in bounded batches so the candidate stays streamable."""
    from sssom.parsers import parse_sssom_table
    from sssom.validators import SchemaValidationType, check_all_prefixes_in_curie_map, validate

    batch = []

    def check():
        text = io.StringIO()
        _write_header(text, metadata, fields)
        text.write("\n".join(batch) + "\n")
        parsed = parse_sssom_table(io.StringIO(text.getvalue()))
        validate(parsed, [SchemaValidationType.JsonSchema], fail_on_error=True)
        check_all_prefixes_in_curie_map(parsed)

    for row in _rows(path):
        batch.append(_serialize(row, fields))
        if len(batch) == 10000:
            check()
            batch.clear()
    if batch:
        check()


def _current_category(curie, entity):
    """Use current categories or the repository's prefix-based fallback consistently."""
    return min(entity.categories)[1] if entity.categories else consolidator.category_for(curie)


def _fresh_rows(curie, entity, fields, date):
    """Emit current claims with specific provenance and uniform object attributes."""
    base = dict.fromkeys(fields, "")
    base.update(
        object_id=curie,
        object_label=entity.label,
        object_formula=entity.formula,
        object_category=_current_category(curie, entity),
        object_source=f"obo:{curie.split(':', 1)[0].lower()}.owl",
        mapping_date=date,
    )
    names = {}
    for name in sorted(entity.names):
        slug = _slug(name)
        if not slug:
            continue
        item = names.setdefault(slug, [name, set()])
        if name == entity.label:
            item[0] = name
        item[1].update(entity.names[name])
    canonical_slug = _slug(entity.label)
    for slug, (name, sources) in sorted(names.items()):
        canonical = slug == canonical_slug
        yield dict(
            base,
            subject_id="kgm.name:" + slug,
            subject_label=name,
            predicate_id="skos:exactMatch" if canonical else "skos:closeMatch",
            mapping_justification="semapv:LexicalMatching",
            comment="canonical_name" if canonical else "synonym",
            source="|".join(sorted(sources)),
        )
    for xref, sources in sorted(entity.xrefs.items()):
        yield dict(
            base,
            subject_id=xref,
            predicate_id="skos:exactMatch",
            mapping_justification="semapv:ManualMappingCuration"
            if xref.startswith("MIM:")
            else "semapv:UnspecifiedMatching",
            source="|".join(sorted(sources)),
        )
    if not names and not entity.xrefs:
        yield dict(
            base,
            subject_id=curie,
            predicate_id="skos:exactMatch",
            comment="attribute_carrier",
            mapping_justification="semapv:UnspecifiedMatching",
            source="current_independent_attributes",
        )


def build_conservative_candidate(
    *,
    baseline: Path,
    release_directory: Path,
    expected_manifest_sha256: str,
    ontology_paths: tuple[Path, ...],
    independent_sources: tuple[IndependentSource, ...],
    output_directory: Path,
    provenance_inputs: dict[Path, str] | None = None,
    upstream_provenance: dict | None = None,
) -> CandidateResult:
    """
    Atomically create a separate candidate, historical quarantine, and audit report.

    All supplied inputs are required and fingerprinted before and after use.
    Affected historical claims are quarantined even when fresh evidence rebuilds
    the same triple; quarantine means historical attribution is insufficient,
    not that the claim is scientifically false. No propagated names are created.
    """
    baseline, output_directory = Path(baseline).resolve(), Path(output_directory).absolute()
    ontology_paths = tuple(Path(path).resolve() for path in ontology_paths)
    independent_sources = tuple(
        IndependentSource(source.kind, Path(source.path).resolve()) for source in independent_sources
    )
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError("Candidate output_directory must not already exist")
    if not ontology_paths:
        raise ValueError("At least one current ontology authority file is required")
    if any(source.kind not in INDEPENDENT_SOURCE_KINDS for source in independent_sources):
        raise ValueError("Unknown independent source kind")
    if bool(provenance_inputs) != bool(upstream_provenance):
        raise ValueError("Upstream provenance requires paired pinned input fingerprints")
    pinned_provenance = {}
    for path, digest in (provenance_inputs or {}).items():
        path = Path(path)
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid pinned provenance input")
        pinned_provenance[str(path.resolve())] = digest
    bundle = validate_reviewed_bundle(release_directory, expected_manifest_sha256=expected_manifest_sha256)
    repo_root = Path(__file__).resolve().parents[1]
    build_context = reproducibility_context(repo_root)
    code_paths = (
        Path(__file__).resolve(),
        Path(consolidator.__file__).resolve(),
        Path(runtime.__file__).resolve(),
        Path(__file__).with_name("mim_reviewed_release.py").resolve(),
        IDENTITY_POLICY.resolve(),
        NAME_SCOPE_POLICY.resolve(),
        IDENTITY_POLICY.parent.parent / "kg_microbe/utils/ingredient_identity.py",
    )
    inputs = [
        baseline,
        *ontology_paths,
        *(source.path for source in independent_sources),
        *code_paths,
        *context_paths(repo_root),
    ]
    inputs.extend(bundle.directory / name for name in ("manifest.json", *bundle.manifest["files"]))
    inputs.extend(Path(path) for path in pinned_provenance)
    fingerprints = {str(path): _hash(path) for path in inputs}
    if any(fingerprints[path] != digest for path, digest in pinned_provenance.items()):
        raise ValueError("Upstream provenance input changed after pin verification")
    verified_release_hashes = {"manifest.json": bundle.manifest_sha256, **bundle.manifest["files"]}
    if any(fingerprints[str(bundle.directory / name)] != value for name, value in verified_release_hashes.items()):
        raise ValueError("Reviewed release changed after validation")
    metadata, fields = _header(baseline)
    if not _REQUIRED_FIELDS.issubset(fields) or not isinstance(metadata.get("curie_map"), dict):
        raise ValueError("Baseline lacks unified SSSOM columns or curie_map")
    prefixes = dict(metadata["curie_map"])
    prefix_differences = {}
    for prefix, upstream_uri in bundle.supported_metadata["curie_map"].items():
        if prefix in prefixes and prefixes[prefix] != upstream_uri:
            prefix_differences[prefix] = {"baseline_uri": prefixes[prefix], "upstream_uri": upstream_uri}
        prefixes.setdefault(prefix, upstream_uri)
    evidence = _Evidence(set(prefixes))
    components, initial, baseline_entities = _Components(), set(), set()
    policy_pruned_targets = set()
    policy_metadata_targets = set()
    baseline_count = 0
    for row in _rows(baseline):
        baseline_count += 1
        target, subject = row["object_id"], row["subject_id"]
        baseline_entities.add(target)
        components.root(target)
        if _historical_policy_rejection(row):
            policy_pruned_targets.add(target)
        if _historical_object_label_rejected(row):
            policy_metadata_targets.add(target)
        if _mim_row(row):
            initial.add(target)
        if row["predicate_id"] == "skos:exactMatch" and not subject.startswith("kgm.name:"):
            components.join(target, subject)
    _load_independent(independent_sources, evidence)
    for curie, entity in evidence.records.items():
        for xref in entity.xrefs:
            components.join(curie, xref)
    for _, row in _native_rows(ontology_paths):
        for xref in (row["xref"] + "|" + row.get("same_as", "")).split("|"):
            if evidence.allowed_xref(row["id"], xref):
                components.join(row["id"], xref)
    for row in bundle.supported_rows:
        curie = row["object_id"]
        if not consolidator.is_accepted_primary(curie):
            raise ValueError(f"Unsupported current MIM primary: {curie}")
        initial.add(curie)
        components.join(curie, row["subject_id"])
    tainted_roots = {components.root(curie) for curie in initial}
    affected = {curie for curie in baseline_entities | initial if components.root(curie) in tainted_roots}
    # A rejected lexical claim may be a target's only historical declaration.
    # Restore current direct authority without quarantining its unrelated valid rows.
    reconstruction_targets = affected | policy_pruned_targets | policy_metadata_targets
    evidence.records = {curie: record for curie, record in evidence.records.items() if curie in reconstruction_targets}
    native_found = set()
    native_object_labels = {}
    for namespace, row in _native_rows(ontology_paths):
        curie = row["id"]
        if curie in reconstruction_targets:
            native_found.add(curie)
            if row["name"] and ingredient_mapping_allowed(row["name"], curie):
                native_object_labels[curie] = {"label": row["name"], "source": f"native_ontology:{namespace}"}
            evidence.add(
                curie,
                row["name"],
                row["synonym"].split("|"),
                row.get("same_as", "").split("|"),
                f"native_ontology:{namespace}",
                100,
                category=row["category"],
            )
    mim_source = "mediaingredientmech_reviewed[manifest=" + bundle.manifest_sha256 + "]"
    for row in bundle.supported_rows:
        curie = row["object_id"]
        if not ingredient_mapping_allowed(row["subject_label"], curie) or not ingredient_xref_allowed(
            row["subject_id"], curie
        ):
            raise ValueError(f"Supported MIM assertion conflicts with current identity policy: {row['subject_id']}")
        evidence.add(
            curie,
            row["subject_label"],
            [row["object_label"], *row.get("other", "").split("|")],
            source=mim_source,
            priority=110,
        )
        evidence.records[curie].xrefs[row["subject_id"]].add(mim_source)
    date = str(bundle.supported_metadata.get("mapping_set_version") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Reviewed release requires an ISO mapping_set_version for deterministic new-row dates")
    candidate_metadata = dict(metadata)
    candidate_metadata.update(
        curie_map=prefixes,
        mapping_set_description=f"Conservative MIM candidate; reviewed manifest sha256:{bundle.manifest_sha256}.",
        mapping_tool="kg-microbe/scripts/mim_conservative_refresh.py",
        mapping_tool_version="sha256:" + fingerprints[str(Path(__file__).resolve())],
    )
    quarantine_metadata = dict(candidate_metadata)
    quarantine_metadata["mapping_set_description"] = (
        "Historical assertions reset pending review; not a scientific rejection list."
    )
    quarantine_metadata["extension_definitions"] = [
        *metadata.get("extension_definitions", []),
        {
            "slot_name": "quarantine_reason",
            "property": "https://w3id.org/kg-microbe/quarantine_reason",
            "type_hint": "xsd:string",
        },
    ]
    stats = {
        "baseline_rows": baseline_count,
        "preserved_rows": 0,
        "relabelled_nonidentity_rows": 0,
        "quarantined_rows": 0,
        "rebuilt_rows": 0,
        "removed_mim_nonidentity_rows": 0,
        "identity_policy_quarantined_rows": 0,
        "identity_policy_relabelled_rows": 0,
    }
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mim-candidate-", dir=output_directory.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        candidate, quarantine = stage / "candidate.sssom.tsv.gz", stage / "quarantine.sssom.tsv.gz"
        database = sqlite3.connect(Path(temporary) / "rows.sqlite")
        database.execute("CREATE TABLE rows (object TEXT, subject TEXT, predicate TEXT, comment TEXT, value TEXT)")

        def insert(row):
            database.execute(
                "INSERT INTO rows VALUES (?, ?, ?, ?, ?)",
                (row["object_id"], row["subject_id"], row["predicate_id"], row["comment"], _serialize(row, fields)),
            )

        with consolidator.open_deterministic_gzip(quarantine) as handle:
            _write_header(handle, quarantine_metadata, [*fields, "quarantine_reason"])
            for row in _rows(baseline):
                curie = row["object_id"]
                policy_reason = _historical_policy_rejection(row)
                if policy_reason:
                    handle.write(_serialize(row, fields) + "\t" + policy_reason + "\n")
                    stats["quarantined_rows"] += 1
                    stats["identity_policy_quarantined_rows"] += 1
                    continue
                nonidentity = row["predicate_id"] in _NONIDENTITY and not row["subject_id"].startswith("kgm.name:")
                retained_claim = not _mim_row(row) and (curie not in affected or nonidentity)
                if retained_claim and _historical_object_label_rejected(row):
                    # Preserve a valid historical xref/alias while retiring its unsafe
                    # descriptive label. The full original remains auditable (#1154).
                    handle.write(_serialize(row, fields) + "\treviewed_identity_policy_object_label\n")
                    stats["quarantined_rows"] += 1
                    stats["identity_policy_relabelled_rows"] += 1
                    row = dict(row, object_label=native_object_labels.get(curie, {}).get("label", ""))
                if nonidentity and not _mim_row(row):
                    adjusted = dict(row)
                    if curie in affected:
                        replacement = evidence.records.get(curie, _Entity())
                        adjusted.update(
                            object_label=replacement.label,
                            object_formula=replacement.formula,
                            object_category=_current_category(curie, replacement),
                        )
                    if row["subject_id"] in affected:
                        adjusted["subject_label"] = evidence.records.get(row["subject_id"], _Entity()).label
                    stats["relabelled_nonidentity_rows"] += int(adjusted != row)
                    insert(adjusted)
                    stats["preserved_rows"] += 1
                    continue
                if curie not in affected and not _mim_row(row):
                    insert(row)
                    stats["preserved_rows"] += 1
                    continue
                reason = (
                    "historical_mim_nonidentity"
                    if nonidentity
                    else "historical_entity_provenance_or_identity_component"
                )
                handle.write(_serialize(row, fields) + "\t" + reason + "\n")
                stats["quarantined_rows"] += 1
                stats["removed_mim_nonidentity_rows"] += int(nonidentity)
        for curie in sorted(evidence.records):
            for row in _fresh_rows(curie, evidence.records[curie], fields, date):
                insert(row)
                stats["rebuilt_rows"] += 1
        database.commit()
        names, ranks, mim_xrefs, named_entities = {}, {}, {}, set()
        with consolidator.open_deterministic_gzip(candidate) as handle:
            _write_header(handle, candidate_metadata, fields)
            for (line,) in database.execute(
                "SELECT value FROM rows ORDER BY object, subject, predicate, comment, value"
            ):
                handle.write(line + "\n")
                row = dict(zip(fields, line.split("\t"), strict=True))
                if row["object_label"]:
                    named_entities.add(row["object_id"])
                for label, rank in ((row["object_label"], 0), (row["subject_label"], 1)):
                    if rank and not (row["subject_id"].startswith("kgm.name:") and row["comment"] == "synonym"):
                        continue
                    normalized = runtime.normalize_name(label)
                    scoped_target = ingredient_name_target(label)
                    if scoped_target is not None and scoped_target != row["object_id"]:
                        continue
                    if normalized and (normalized not in names or rank < ranks[normalized]):
                        names[normalized], ranks[normalized] = row["object_id"], rank
                if row["subject_id"].startswith("MIM:"):
                    mim_xrefs.setdefault(row["subject_id"], row["object_id"])
        for query, target in ingredient_name_scopes()[0].items():
            if target in named_entities:
                names[runtime.normalize_name(query)] = target
        unreconstructed_lexicals = sorted(
            curie for curie in reconstruction_targets if not evidence.records.get(curie, _Entity()).label
        )
        stats.update(
            candidate_rows=stats["preserved_rows"] + stats["rebuilt_rows"],
            candidate_entities=database.execute("SELECT COUNT(DISTINCT object) FROM rows").fetchone()[0],
            rebuilt_entities=len(evidence.records),
            unreconstructed_lexical_entities=len(unreconstructed_lexicals),
        )
        database.close()
        _validate_output(candidate, candidate_metadata, fields)
        for path, fingerprint in fingerprints.items():
            if _hash(Path(path)) != fingerprint:
                raise ValueError(f"Input changed during conservative refresh: {path}")
        if reproducibility_context(repo_root) != build_context:
            raise ValueError("Code or environment changed during conservative refresh")
        conflicts = [
            {
                "name": row["subject_label"],
                "subject_id": row["subject_id"],
                "expected": row["object_id"],
                "resolved": _candidate_name_lookup(row["subject_label"], names, named_entities),
            }
            for row in bundle.supported_rows
            if _candidate_name_lookup(row["subject_label"], names, named_entities) != row["object_id"]
        ]
        accepted_scopes = [
            dict(
                conflict,
                explicit_resolved=mim_xrefs.get(conflict["subject_id"]),
                reason="Reviewed generic trait versus 9H ingredient scope; native subclass relation retained.",
            )
            for conflict in conflicts
            if accepted_name_scope(
                conflict["subject_id"],
                conflict["expected"],
                conflict["resolved"],
                mim_xrefs.get(conflict["subject_id"]),
            )
        ]
        conflicts = [
            conflict
            for conflict in conflicts
            if not accepted_name_scope(
                conflict["subject_id"],
                conflict["expected"],
                conflict["resolved"],
                mim_xrefs.get(conflict["subject_id"]),
            )
        ]
        supported_targets = defaultdict(set)
        for row in bundle.supported_rows:
            supported_targets[row["subject_id"]].add(row["object_id"])
        xref_conflicts = [
            {"subject_id": subject, "approved_targets": sorted(targets), "resolved": mim_xrefs.get(subject)}
            for subject, targets in sorted(supported_targets.items())
            if mim_xrefs.get(subject) not in targets
        ]
        report = {
            "schema_version": 1,
            "status": "CANDIDATE_REQUIRES_REVIEW",
            "manifest_sha256": bundle.manifest_sha256,
            "source_sha256": bundle.source_sha256,
            "review_sha256": bundle.review_sha256,
            "input_sha256": fingerprints,
            "reproducibility_context": build_context,
            "upstream_provenance": upstream_provenance,
            "candidate_sha256": _hash(candidate),
            "quarantine_sha256": _hash(quarantine),
            "counts": stats,
            "initial_affected_entities": sorted(initial),
            "affected_entities": sorted(affected),
            "policy_pruned_targets": sorted(policy_pruned_targets),
            "policy_metadata_targets": sorted(policy_metadata_targets),
            "native_object_label_repairs": {
                curie: native_object_labels[curie]
                for curie in sorted(policy_metadata_targets & native_object_labels.keys())
            },
            "unreconstructed_object_labels": sorted(policy_metadata_targets - native_object_labels.keys()),
            "reconstruction_targets": sorted(reconstruction_targets),
            "native_authority_entities": sorted(native_found),
            "unreconstructed_entities": sorted(reconstruction_targets - evidence.records.keys()),
            "unreconstructed_lexical_entities": unreconstructed_lexicals,
            "supported_name_lookup_conflicts": conflicts,
            "accepted_name_scope_distinctions": accepted_scopes,
            "supported_xref_lookup_conflicts": xref_conflicts,
            "supported_multitarget_subjects": {
                subject: sorted(targets) for subject, targets in sorted(supported_targets.items()) if len(targets) > 1
            },
            "upstream_prefix_differences": prefix_differences,
            "independent_sources": [{"kind": source.kind, "path": str(source.path)} for source in independent_sources],
            "limitations": [
                "Historical quarantine covers entities and undirected exact-identity closure, including shared xrefs.",
                "Absent historical provenance cannot be recovered; current direct evidence replaces affected claims.",
                "No synonym propagation, roles, components, or scientific approval of withheld mappings is performed.",
                (
                    "Source/review bytes were bound to the pinned source archive; scientific review is not repeated."
                    if upstream_provenance
                    and upstream_provenance.get("verification") == "verified_archived_source_and_manifest_binding"
                    else "Source/review hashes are publisher claims; "
                    "original scientific evidence is outside this bundle."
                ),
                "The caller must establish independent input lineage; a manual/legacy filename does not prove it.",
                "Native xref annotations inform quarantine scope only; new identity claims require explicit same_as.",
                "preserved_rows counts retained assertions including metadata-repaired copies, not unchanged bytes; "
                "their originals also count in quarantined_rows. identity_policy_relabelled_rows reports the overlap.",
            ],
        }
        (stage / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if output_directory.exists():
            raise ValueError("Candidate output_directory appeared during generation")
        os.replace(stage, output_directory)
    return CandidateResult(
        output_directory,
        output_directory / candidate.name,
        output_directory / quarantine.name,
        output_directory / "report.json",
        report,
    )
