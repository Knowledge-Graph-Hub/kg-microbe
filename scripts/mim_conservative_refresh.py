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
import tarfile
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.cas import invalid_cas_identifier
from kg_microbe.utils.ingredient_context import (
    CONTEXT_POLICY,
    NATIVE_AUTHORITY,
    contextualize_ingredient_row,
    ingredient_context_allowed,
    ingredient_context_pair_allowed,
)
from kg_microbe.utils.ingredient_identity import (
    IDENTITY_POLICY,
    NAME_SCOPE_POLICY,
    accepted_name_scope,
    ingredient_authority_label,
    ingredient_case_sensitive_name_scope,
    ingredient_mapping_allowed,
    ingredient_name_scopes,
    ingredient_name_target,
    ingredient_xref_allowed,
)
from kg_microbe.utils.sssom_identity_policy import classify_mapping_row
from scripts import consolidate_chemical_mappings as consolidator
from scripts.mapping_provenance import context_paths, reproducibility_context
from scripts.mim_reviewed_release import row_sha256, validate_reviewed_bundle

HOLD_POLICY = Path(__file__).resolve().parents[1] / "mappings/mim_downstream_holds.json"
HOLD_POLICY_SHA256 = "ed136aca89d76107a456ddc11f3da49ce31bec8a474abdcab71c8cda9b6a9ddf"
HOLD_FIXTURE = Path(__file__).resolve().parents[1] / "tests/resources/mediadive/p3556_scope.json"
HOLD_REVIEW = Path(__file__).resolve().parents[1] / "docs/reviews/mediadive-p3556-scope-1241.md"

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


def _historical_policy_rejection(row, native_hydrate_names=None):
    """Reject invalid CAS endpoints, then apply reviewed lexical/exact exclusions."""
    subject, target = row["subject_id"], row["object_id"]
    if invalid_cas_identifier(subject) or invalid_cas_identifier(target):
        return "invalid_cas_identifier"
    if subject.startswith("kgm.name:") and row["predicate_id"] in {"skos:exactMatch", "skos:closeMatch"}:
        if not ingredient_mapping_allowed(row.get("subject_label", ""), target):
            return "reviewed_identity_policy_name"
        if not runtime.ingredient_hydration_compatible(
            row.get("subject_label", ""), row.get("object_label", ""), (native_hydrate_names or {}).get(target, ())
        ):
            return "hydration_scope_name"
    elif row["predicate_id"] == "skos:exactMatch" and not ingredient_xref_allowed(subject, target):
        return "reviewed_identity_policy_xref"
    return ""


def _candidate_name_lookup(name, names, declared, labels=None, native_hydrate_names=None):
    """Mirror finite runtime query scopes without putting case-sensitive aliases in a shared key."""
    recognized, target = ingredient_case_sensitive_name_scope(name)
    if recognized:
        return (
            target
            if target in declared and ingredient_context_allowed(target) and ingredient_mapping_allowed(name, target)
            else None
        )
    normalized = runtime.normalize_name(name)
    if ingredient_case_sensitive_name_scope(normalized)[0]:
        return None
    target = names.get(normalized)
    if not ingredient_context_allowed(target):
        return None
    if (
        target is not None
        and labels is not None
        and not runtime.ingredient_hydration_compatible(
            name, labels.get(target, ""), (native_hydrate_names or {}).get(target, ())
        )
    ):
        return None
    return target


def _historical_object_label_rejected(row):
    """Detect unsafe descriptive metadata separately from an otherwise admissible claim."""
    label = row.get("object_label", "")
    return bool(label and not ingredient_mapping_allowed(label, row["object_id"]))


class _Components:
    """Track explicit identity connectivity, including shared historical exact IDs."""

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
    native_names = [
        name for name, sources in entity.names.items() if any(s.startswith("native_ontology:") for s in sources)
    ]
    for name in sorted(entity.names):
        if not runtime.ingredient_hydration_compatible(name, entity.label, native_names):
            continue
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


def _downstream_hold_policy():
    """Read the single byte-pinned local hold and bind its unchanged scientific evidence."""
    if HOLD_POLICY.is_symlink() or _hash(HOLD_POLICY) != HOLD_POLICY_SHA256:
        raise ValueError("Downstream hold policy identity changed")
    policy = json.loads(HOLD_POLICY.read_text(encoding="utf-8"))
    for path, binding_field in (
        (IDENTITY_POLICY, "identity_policy_sha256"),
        (HOLD_FIXTURE, "fixture_sha256"),
        (HOLD_REVIEW, "review_document_sha256"),
    ):
        if path.is_symlink() or _hash(path) != policy[binding_field]:
            raise ValueError(f"Downstream hold evidence identity changed: {binding_field}")
    if row_sha256(policy["row"]) != policy["row_sha256"]:
        raise ValueError("Downstream hold full-row identity differs")
    return policy


def _supported_partition(bundle, policy, pinned_provenance, upstream_provenance):
    """Hold only the exact reviewed native claim; every unfamiliar identity conflict remains fatal."""
    eligible, held = [], []
    for ordinal, row in enumerate(bundle.supported_rows, 1):
        if row["subject_id"] == policy["row"]["subject_id"] and row["predicate_id"] == "skos:exactMatch":
            if row != policy["row"] or row_sha256(row) != policy["row_sha256"]:
                raise ValueError("Known downstream-held native claim changed")
            if held:
                raise ValueError("Downstream-held native occurrence multiplicity changed")
            decisions = [
                item
                for item in bundle.disposition_rows
                if item["row_sha256"] == policy["row_sha256"] and item["disposition"] == "SUPPORTED"
            ]
            if decisions != [policy["decision"]]:
                raise ValueError("Downstream-held source decision or owner changed")
            for field in ("manifest_sha256", "source_sha256", "review_sha256"):
                if getattr(bundle, field) != policy[field]:
                    raise ValueError(f"Downstream-held source binding changed: {field}")
            pin = (upstream_provenance or {}).get("pin", {})
            if (
                pin.get("source_commit") != policy["source_commit"]
                or pin.get("source_archive", {}).get("sha256") != policy["source_archive_sha256"]
            ):
                raise ValueError("Downstream hold requires the exact pinned source archive")
            archives = [
                Path(path) for path, digest in pinned_provenance.items() if digest == policy["source_archive_sha256"]
            ]
            if len(archives) != 1 or _hash(archives[0]) != policy["source_archive_sha256"]:
                raise ValueError("Downstream hold source archive is not an actual bound input")
            owner_name = "MediaIngredientMech-" + policy["source_commit"] + "/" + policy["decision"]["owner_record"]
            owner_hashes = []
            with tarfile.open(archives[0], "r|gz") as archive:
                for member in archive:
                    if member.name != owner_name:
                        continue
                    if not member.isfile():
                        raise ValueError("Downstream-held owner is not a unique regular source member")
                    with archive.extractfile(member) as stream:
                        digest = hashlib.sha256()
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                        owner_hashes.append(digest.hexdigest())
            if owner_hashes != [policy["owner_sha256"]]:
                raise ValueError("Downstream-held source owner identity changed")
            held.append(
                {
                    "supported_ordinal": ordinal,
                    "row": dict(row),
                    "row_sha256": row_sha256(row),
                    "decision": dict(decisions[0]),
                    "owner_sha256": owner_hashes[0],
                    "source_archive": str(archives[0]),
                    "source_archive_sha256": policy["source_archive_sha256"],
                    "disposition": policy["disposition"],
                    "reason": policy["reason"],
                }
            )
        else:
            if row["predicate_id"] == "skos:exactMatch" and (
                not ingredient_context_pair_allowed(row["subject_id"], row["object_id"])
                or not ingredient_mapping_allowed(row["subject_label"], row["object_id"])
                or not ingredient_xref_allowed(row["subject_id"], row["object_id"])
            ):
                raise ValueError(f"Supported MIM assertion conflicts with current identity policy: {row['subject_id']}")
            eligible.append(row)
    return tuple(eligible), held


def _held_native_witness(row, policy):
    """Require the reviewed structured label in the exact current native molecular declaration."""
    selected = {key: row.get(key, "") for key in policy["native"]}
    label = ingredient_authority_label(row["id"])
    if (
        selected != policy["native"]
        or label != policy["authority_label"]
        or label not in [row["name"], *row["synonym"].split("|")]
    ):
        raise ValueError("Downstream-held target lacks its current structured native witness")
    return {"row": selected, "row_sha256": row_sha256(selected), "authority_label": label}


def _broader_projections(exact_rows, broader_rows, fields, source):
    """Project each broader claim only through its explicitly supported exact form siblings."""
    identities = defaultdict(list)
    for row in exact_rows:
        identities[row["subject_id"]].append(row)
    projected = {}
    for broad in broader_rows:
        subject, parent = broad["subject_id"], broad["object_id"]
        siblings = identities[subject]
        if not siblings:
            raise ValueError(f"Supported broader assertion lacks an exact form identity: {subject}")
        broad_hash = row_sha256(broad)
        for exact in siblings:
            child = exact["object_id"]
            if child == parent:
                raise ValueError(f"Broader parent is also a supplied exact identity: {subject}")
            if not ingredient_mapping_allowed(
                broad["subject_label"], child
            ) or not runtime.ingredient_hydration_compatible(broad["subject_label"], exact["subject_label"]):
                raise ValueError(f"Broader source changes its supported exact form scope: {subject}")
            item = projected.setdefault(
                (broad_hash, child),
                {
                    "source_subject_id": subject,
                    "broad_row_sha256": broad_hash,
                    "exact_identity_row_sha256": set(),
                    "row": dict(
                        {field: broad.get(field, "") for field in fields},
                        subject_id=child,
                        object_formula="",
                        object_category="",
                    ),
                },
            )
            item["exact_identity_row_sha256"].add(row_sha256(exact))
    derivations = []
    for key in sorted(projected):
        item = projected[key]
        hashes = sorted(item["exact_identity_row_sha256"])
        item["exact_identity_row_sha256"] = hashes
        item["row"]["source"] = "|".join(
            f"{source}[broad-row-sha256={item['broad_row_sha256']};exact-row-sha256={digest}]" for digest in hashes
        )
        item["derived_row_sha256"] = row_sha256(item["row"])
        derivations.append(item)
    return derivations


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
    if any(row.get("predicate_modifier", "").strip() for row in bundle.supported_rows):
        raise ValueError("Supported MIM predicate modifiers cannot become positive assertions")
    native_exact_rows = tuple(row for row in bundle.supported_rows if row["predicate_id"] == "skos:exactMatch")
    broader_rows = tuple(row for row in bundle.supported_rows if row["predicate_id"] == "skos:broadMatch")
    if len(native_exact_rows) + len(broader_rows) != len(bundle.supported_rows):
        raise ValueError("Unsupported predicate in reviewed MIM reconstruction")
    repo_root = Path(__file__).resolve().parents[1]
    build_context = reproducibility_context(repo_root)
    code_paths = (
        Path(__file__).resolve(),
        HOLD_POLICY,
        HOLD_FIXTURE,
        HOLD_REVIEW,
        Path(consolidator.__file__).resolve(),
        Path(runtime.__file__).resolve(),
        Path(__file__).with_name("mim_reviewed_release.py").resolve(),
        IDENTITY_POLICY.resolve(),
        NAME_SCOPE_POLICY.resolve(),
        CONTEXT_POLICY.resolve(),
        NATIVE_AUTHORITY.resolve(),
        IDENTITY_POLICY.parent.parent / "kg_microbe/utils/ingredient_context.py",
        IDENTITY_POLICY.parent.parent / "kg_microbe/utils/ingredient_identity.py",
        IDENTITY_POLICY.parent.parent / "kg_microbe/utils/cas.py",
        IDENTITY_POLICY.parent.parent / "kg_microbe/utils/sssom_identity_policy.py",
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
    hold_policy = _downstream_hold_policy()
    eligible_rows, held_claims = _supported_partition(bundle, hold_policy, pinned_provenance, upstream_provenance)
    exact_rows = tuple(row for row in eligible_rows if row["predicate_id"] == "skos:exactMatch")
    held_targets = {item["row"]["object_id"] for item in held_claims}
    held_native_witnesses = {}
    metadata, fields = _header(baseline)
    if not _REQUIRED_FIELDS.issubset(fields) or not isinstance(metadata.get("curie_map"), dict):
        raise ValueError("Baseline lacks unified SSSOM columns or curie_map")
    mim_source = "mediaingredientmech_reviewed[manifest=" + bundle.manifest_sha256 + "]"
    broader_derivations = _broader_projections(exact_rows, broader_rows, fields, mim_source)
    current_broader_rows = {item["derived_row_sha256"] for item in broader_derivations}
    prefixes = dict(metadata["curie_map"])
    prefix_differences = {}
    for prefix, upstream_uri in bundle.supported_metadata["curie_map"].items():
        if prefix in prefixes and prefixes[prefix] != upstream_uri:
            prefix_differences[prefix] = {"baseline_uri": prefixes[prefix], "upstream_uri": upstream_uri}
        prefixes.setdefault(prefix, upstream_uri)
    evidence = _Evidence(set(prefixes))
    components, initial, baseline_entities = _Components(), set(), set()
    native_hydrate_names = {}
    for _, row in _native_rows(ontology_paths):
        if row["id"] in held_targets:
            if row["id"] in held_native_witnesses:
                raise ValueError("Downstream-held target has repeated native declarations")
            held_native_witnesses[row["id"]] = _held_native_witness(row, hold_policy)
        if "hydrate" in row["name"].casefold():
            native_hydrate_names[row["id"]] = tuple(row["synonym"].split("|"))
        # New annotations cannot demonstrate historical identity propagation.
        # Join only native identities that reconstruction may actually reassert;
        # historical exactMatch links below still trace potential contamination.
        for xref in row.get("same_as", "").split("|"):
            xref = xref.strip()  # Match _Evidence.add before testing identity scope.
            if evidence.allowed_xref(row["id"], xref):
                components.join(row["id"], xref)
    if set(held_native_witnesses) != held_targets:
        raise ValueError("Downstream-held target lacks its current structured native witness")
    policy_pruned_targets = set()
    policy_metadata_targets = set()
    baseline_count = 0
    baseline_asymmetric_count = 0
    for row in _rows(baseline):
        baseline_count += 1
        baseline_asymmetric_count += row["predicate_id"] in {"skos:broadMatch", "skos:narrowMatch"}
        target, subject = row["object_id"], row["subject_id"]
        baseline_entities.add(target)
        components.root(target)
        if _historical_policy_rejection(row, native_hydrate_names):
            policy_pruned_targets.add(target)
        if _historical_object_label_rejected(row):
            policy_metadata_targets.add(target)
        # Exact current derived broader rows never copied parent identity or
        # names. Recognize the whole row, including both source hashes, so a
        # second cycle cannot expand reset scope across this nonidentity link.
        if _mim_row(row) and row_sha256(row) not in current_broader_rows:
            initial.add(target)
        # Even an invalid historical registry link may have propagated copied
        # aliases. Trace it for quarantine scope only; never reassert the link.
        if row["predicate_id"] == "skos:exactMatch" and not subject.startswith("kgm.name:"):
            components.join(target, subject)
    _load_independent(independent_sources, evidence)
    for curie, entity in evidence.records.items():
        for xref in entity.xrefs:
            components.join(curie, xref)
    if broader_rows:
        semantics = metadata.get("predicate_semantics", "")
        if semantics not in {"", "skos"} or (baseline_asymmetric_count and semantics != "skos"):
            raise ValueError("Cannot mix legacy or unknown asymmetric semantics with supported SKOS broader rows")
    for row in exact_rows:
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
            native_label = held_native_witnesses.get(curie, {}).get("authority_label", row["name"])
            if native_label and ingredient_mapping_allowed(native_label, curie):
                native_object_labels[curie] = {"label": native_label, "source": f"native_ontology:{namespace}"}
            evidence.add(
                curie,
                native_label,
                row["synonym"].split("|"),
                row.get("same_as", "").split("|"),
                f"native_ontology:{namespace}",
                100,
                category=row["category"],
            )
    for row in exact_rows:
        curie = row["object_id"]
        if (
            not ingredient_context_pair_allowed(row["subject_id"], curie)
            or not ingredient_mapping_allowed(row["subject_label"], curie)
            or not ingredient_xref_allowed(row["subject_id"], curie)
        ):
            raise ValueError(f"Supported MIM assertion conflicts with current identity policy: {row['subject_id']}")
        declared_label = evidence.records.get(curie, _Entity()).label or row["object_label"]
        if not runtime.ingredient_hydration_compatible(
            row["subject_label"], declared_label, native_hydrate_names.get(curie, ())
        ):
            raise ValueError(f"Supported MIM assertion changes declared hydration scope: {row['subject_id']}")
        evidence.add(
            curie,
            row["subject_label"],
            [row["object_label"], *row.get("other", "").split("|")],
            source=mim_source,
            priority=110,
        )
        evidence.records[curie].xrefs[row["subject_id"]].add(mim_source)
    for row in broader_rows:
        if not consolidator.is_accepted_primary(row["object_id"]):
            raise ValueError(f"Unsupported current MIM broader target: {row['object_id']}")
    date = str(bundle.supported_metadata.get("mapping_set_version") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Reviewed release requires an ISO mapping_set_version for deterministic new-row dates")
    candidate_metadata = dict(metadata)
    if broader_rows:
        candidate_metadata["predicate_semantics"] = "skos"
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
        "ingredient_context_scoped_rows": 0,
        "baseline_asymmetric_rows": baseline_asymmetric_count,
        "native_supported_rows": len(bundle.supported_rows),
        "native_withheld_rows": len(bundle.withheld_rows),
        "eligible_supported_rows": len(eligible_rows),
        "eligible_exact_rows": len(exact_rows),
        "downstream_held_rows": len(held_claims),
        "supported_exact_rows": len(native_exact_rows),
        "supported_broader_rows": len(broader_rows),
        "derived_broader_rows": len(broader_derivations),
    }
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mim-candidate-", dir=output_directory.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        candidate, quarantine = stage / "candidate.sssom.tsv.gz", stage / "quarantine.sssom.tsv.gz"
        database = sqlite3.connect(Path(temporary) / "rows.sqlite")
        database.execute("CREATE TABLE rows (object TEXT, subject TEXT, predicate TEXT, comment TEXT, value TEXT)")

        def insert(row, audit_handle):
            contextualized = contextualize_ingredient_row(row)
            if contextualized != row:
                audit_handle.write(_serialize(row, fields) + "\tingredient_material_identity_context\n")
                stats["quarantined_rows"] += 1
                stats["ingredient_context_scoped_rows"] += 1
            row = contextualized
            database.execute(
                "INSERT INTO rows VALUES (?, ?, ?, ?, ?)",
                (row["object_id"], row["subject_id"], row["predicate_id"], row["comment"], _serialize(row, fields)),
            )

        with consolidator.open_deterministic_gzip(quarantine) as handle:
            _write_header(handle, quarantine_metadata, [*fields, "quarantine_reason"])
            for row in _rows(baseline):
                curie = row["object_id"]
                policy_reason = _historical_policy_rejection(row, native_hydrate_names)
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
                    insert(adjusted, handle)
                    stats["preserved_rows"] += 1
                    continue
                if curie not in affected and not _mim_row(row):
                    insert(row, handle)
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
                    insert(row, handle)
                    stats["rebuilt_rows"] += 1
            for derivation in broader_derivations:
                insert(derivation["row"], handle)
                stats["rebuilt_rows"] += 1
        database.commit()
        names, ranks, mim_xrefs, named_entities, declared_labels = {}, {}, {}, set(), {}
        with consolidator.open_deterministic_gzip(candidate) as handle:
            _write_header(handle, candidate_metadata, fields)
            for (line,) in database.execute(
                "SELECT value FROM rows ORDER BY object, subject, predicate, comment, value"
            ):
                handle.write(line + "\n")
                row = dict(zip(fields, line.split("\t"), strict=True))
                route, _ = classify_mapping_row(row, candidate_metadata)
                if route not in {"identity", "attribute", "canonical_name", "synonym"}:
                    continue
                if row["object_label"]:
                    named_entities.add(row["object_id"])
                    declared_labels.setdefault(row["object_id"], row["object_label"])
                for label, rank in ((row["object_label"], 0), (row["subject_label"], 1)):
                    if not ingredient_context_allowed(row["object_id"]):
                        continue
                    if rank and not (row["subject_id"].startswith("kgm.name:") and row["comment"] == "synonym"):
                        continue
                    if not runtime.ingredient_hydration_compatible(
                        label, declared_labels.get(row["object_id"], ""), native_hydrate_names.get(row["object_id"], ())
                    ):
                        continue
                    normalized = runtime.normalize_name(label)
                    scoped_target = ingredient_name_target(label)
                    if scoped_target is not None and scoped_target != row["object_id"]:
                        continue
                    if normalized and (normalized not in names or rank < ranks[normalized]):
                        names[normalized], ranks[normalized] = row["object_id"], rank
                if row["subject_id"].startswith("MIM:") and ingredient_context_pair_allowed(
                    row["subject_id"], row["object_id"]
                ):
                    mim_xrefs.setdefault(row["subject_id"], row["object_id"])
        for query, target in ingredient_name_scopes()[0].items():
            if target in named_entities and ingredient_context_allowed(target):
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
        supported_targets = defaultdict(set)
        supported_names = defaultdict(set)
        for row in exact_rows:
            supported_targets[row["subject_id"]].add(row["object_id"])
            supported_names[(row["subject_id"], row["subject_label"])].add(row["object_id"])
        conflicts = [
            {
                "name": row["subject_label"],
                "subject_id": row["subject_id"],
                "expected": row["object_id"],
                "resolved": _candidate_name_lookup(
                    row["subject_label"], names, named_entities, declared_labels, native_hydrate_names
                ),
            }
            for row in exact_rows
            if _candidate_name_lookup(
                row["subject_label"], names, named_entities, declared_labels, native_hydrate_names
            )
            not in supported_names[(row["subject_id"], row["subject_label"])]
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
        xref_conflicts = [
            {"subject_id": subject, "approved_targets": sorted(targets), "resolved": mim_xrefs.get(subject)}
            for subject, targets in sorted(supported_targets.items())
            if mim_xrefs.get(subject) not in targets
        ]
        held_ledger = {
            "schema_version": 1,
            "policy_sha256": fingerprints[str(HOLD_POLICY)],
            "manifest_sha256": bundle.manifest_sha256,
            "source_sha256": bundle.source_sha256,
            "review_sha256": bundle.review_sha256,
            "native_supported_count": len(bundle.supported_rows),
            "eligible_exact_count": len(exact_rows),
            "eligible_broader_count": len(broader_rows),
            "downstream_held_count": len(held_claims),
            "claims": held_claims,
            "native_witnesses": held_native_witnesses,
        }
        held_path = stage / "downstream-held.json"
        held_text = json.dumps(held_ledger, sort_keys=True, indent=2) + "\n"
        held_bytes = held_text.encode("utf-8")
        held_path.write_text(held_text, encoding="utf-8")
        if held_path.read_bytes() != held_bytes:
            raise ValueError("Mandatory downstream-held ledger differs from reviewed claims")
        held_digest = hashlib.sha256(held_bytes).hexdigest()
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
            "downstream_held_ledger": {"name": held_path.name, "sha256": held_digest, "rows": len(held_claims)},
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
            "supported_broader_relation_derivations": broader_derivations,
            "supported_multitarget_subjects": {
                subject: sorted(targets) for subject, targets in sorted(supported_targets.items()) if len(targets) > 1
            },
            "upstream_prefix_differences": prefix_differences,
            "independent_sources": [{"kind": source.kind, "path": str(source.path)} for source in independent_sources],
            "limitations": [
                "Native SUPPORTED claims partition into eligible exact, eligible broader and reviewed downstream-held "
                "claims; the separate complete-payload held ledger is not the publisher's WITHHOLD partition.",
                "Held claims supply no identity, alias or broader licensing; independently witnessed native structured "
                "names remain eligible. Unknown or changed downstream conflicts are fatal.",
                "Historical quarantine covers entities and undirected exact-identity closure, including shared xrefs.",
                "Absent historical provenance cannot be recovered; current direct evidence replaces affected claims.",
                "No synonym propagation, roles, components, or scientific approval of withheld mappings is performed.",
                "Supported broader claims project only through explicit same-subject exact identities; "
                "each derived relation binds both input row hashes and contributes no identity or alias evidence.",
                "derived_broader_rows is included in rebuilt_rows; supported_broader_rows counts original claims.",
                (
                    "Source/review bytes were bound to the pinned source archive; scientific review is not repeated."
                    if upstream_provenance
                    and upstream_provenance.get("verification") == "verified_archived_source_and_manifest_binding"
                    else "Source/review hashes are publisher claims; "
                    "original scientific evidence is outside this bundle."
                ),
                "The caller must establish independent input lineage; a manual/legacy filename does not prove it.",
                "Native xref annotations neither expand quarantine scope nor establish identity; "
                "native same_as participates before reconstruction. Historical exactMatch links still trace taint.",
                "Invalid CAS endpoints are quarantined with full original rows, never repaired; "
                "historical exactMatch links involving them still trace potential copied-name contamination.",
                "Already-erased historical identity links cannot establish reset scope from the surviving seed; "
                "retained historical claims are not newly scientifically validated.",
                "preserved_rows counts retained assertions including metadata-repaired copies, not unchanged bytes; "
                "their originals also count in quarantined_rows. identity_policy_relabelled_rows reports the overlap.",
            ],
        }
        (stage / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if _hash(held_path) != held_digest:
            raise ValueError("Mandatory downstream-held ledger changed before publication")
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
