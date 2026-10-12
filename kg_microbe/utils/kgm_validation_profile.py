"""Classify exact KGXVal diagnostics without waiving validation or editing a graph."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    ASSAY_BIOLOGICAL_PROCESS_PREDICATE,
    ASSAY_HAS_INPUT_PREDICATE,
    ASSAY_HAS_OUTPUT_PREDICATE,
)
from kg_microbe.utils.metpo_predicates import METPO_TO_BIOLINK_PREDICATE

CONTRACT_VERSION = "kgm-validation-contract-v1"
PROFILE_VERSION = 1
PROFILE_ID = "kgm-kgxval-dispositions-4.4.2-v1"
DEFAULT_PROFILE = Path(__file__).resolve().parents[2] / "mappings" / "kgxval_dispositions_v1.json"
DEFAULT_REFERENCE = DEFAULT_PROFILE.with_name("kgxval_reference_dispositions_v1.json")
CSV_FIELDS = ("INGEST_NAME", "NORMALIZED", "PREDICATE", "ERROR", "VALID_CATEGORIES", "ACTUAL_CATEGORIES")
NATIVE_ASSAY_PREDICATES = frozenset(
    (ASSAY_HAS_INPUT_PREDICATE, ASSAY_HAS_OUTPUT_PREDICATE, ASSAY_BIOLOGICAL_PROCESS_PREDICATE)
)
DISPOSITIONS = frozenset(
    (
        "native_predicate_project_extension",
        "class_subsumption_row_evidence_required",
        "growth_medium_row_evidence_required",
        "taxon_phenotype_row_evidence_required",
        "chemical_role_row_evidence_required",
        "food_taxon_row_evidence_required",
        "ontology_category_source_review_required",
        "domain_range_source_review_required",
    )
)
MAX_DISTINCT_DIAGNOSTICS = 10000


def validation_contract() -> dict:
    """Describe independent validation layers; no single layer authorizes release."""
    return {
        "version": CONTRACT_VERSION,
        "layers": {
            "source_finalization": "Canonical source representation, audited semantic decisions and input identities",
            "source_admission": "Current finalized producer bundles and their consumed dependencies",
            "merge_representation": "Canonical serialization and cross-source declared endpoint closure",
            "kgm_model": "Project modeling rules, with house-only results separate from Biolink results",
            "kgxval": "External predicate/category diagnostics; CSV records are not graph-row counts",
            "strict_kgx": "Unmodified installed-validator callbacks and limitations; no profile waiver",
            "paths": "Explicitly selected structural checks, not universal biological path validity",
            "scientific_disposition": "Evidence-bound interpretation, separate from syntax or report retention",
        },
        "graph_rewrites": False,
        "release_authorized": False,
    }


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def file_identity(path: Path) -> dict:
    """Hash a local input in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def diagnostic_signature(row: dict) -> str:
    """Identify all six literal CSV cells, including valid categories and ingest scope."""
    _require(set(row) == set(CSV_FIELDS), "Unexpected KGXVal diagnostic fields")
    _require(all(isinstance(row[key], str) for key in CSV_FIELDS), "Non-string KGXVal cell")
    payload = json.dumps([row[key] for key in CSV_FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _expected_disposition(row):
    """Constrain finite routing labels, never authorize an edge from category strings."""
    error, predicate = row["ERROR"], row["PREDICATE"]
    categories = set(row["ACTUAL_CATEGORIES"].split("|"))
    if error == "BAD BIOLINK":
        _require(
            predicate in METPO_TO_BIOLINK_PREDICATE or predicate in NATIVE_ASSAY_PREDICATES,
            f"Unregistered native predicate: {predicate}",
        )
        _require(not row["VALID_CATEGORIES"] and not row["ACTUAL_CATEGORIES"], "Malformed native diagnostic")
        return "native_predicate_project_extension"
    _require(error in {"BAD SUBJECT", "BAD OBJECT"}, f"Unknown KGXVal diagnostic type: {error}")
    if predicate == "biolink:subclass_of":
        if categories == {"growth medium"}:
            return "growth_medium_row_evidence_required"
        return "class_subsumption_row_evidence_required"
    if predicate == "biolink:has_phenotype" and categories != {"named thing"}:
        return "taxon_phenotype_row_evidence_required"
    if predicate == "biolink:has_chemical_role" and categories == {"macromolecular complex"}:
        return "chemical_role_row_evidence_required"
    if predicate == "biolink:in_taxon" and error == "BAD SUBJECT" and categories == {"food"}:
        return "food_taxon_row_evidence_required"
    if "ontology class" in categories:
        return "ontology_category_source_review_required"
    return "domain_range_source_review_required"


def load_profile(path: Path = DEFAULT_PROFILE) -> dict:
    """Validate the finite versioned registry, rejecting corruption and implicit waivers."""
    with Path(path).open(encoding="utf-8") as stream:
        profile = json.load(stream, object_pairs_hook=_unique_object)
    _require(
        type(profile.get("version")) is int and profile["version"] == PROFILE_VERSION,
        "Unsupported disposition profile version",
    )
    _require(profile.get("profile_id") == PROFILE_ID, "Unsupported disposition profile identity")
    _require(profile.get("contract_version") == CONTRACT_VERSION, "Unsupported validation contract")
    _require(set(profile.get("dispositions", {})) == DISPOSITIONS, "Incomplete disposition definitions")
    reference = profile["reference"]
    _require(reference["biolink_version"] == "4.4.2", "Different model requires a new reviewed profile")
    definitions = profile["dispositions"]
    for name, definition in definitions.items():
        _require(definition.get("scientific_acceptance") is False, f"Forbidden acceptance waiver: {name}")
        _require(bool(definition.get("evidence")) and bool(definition.get("remaining_verification")), name)
    entries, index = profile["diagnostics"], {}
    for entry in entries:
        _require(type(entry["reference_occurrences"]) is int and entry["reference_occurrences"] > 0, "Bad count")
        row = {
            **profile["csv_scope"],
            "PREDICATE": entry["predicate"],
            "ERROR": entry["error"],
            "VALID_CATEGORIES": profile["valid_category_sets"][entry["valid_category_set"]],
            "ACTUAL_CATEGORIES": entry["actual_categories"],
        }
        signature = diagnostic_signature(row)
        _require(signature == entry["signature_sha256"], "Diagnostic cells differ from their signature")
        _require(signature not in index, "Duplicate registered diagnostic")
        _require(entry["disposition"] == _expected_disposition(row), "Wrong finite diagnostic disposition")
        index[signature] = {**entry, "original_diagnostic": row}
    _require(len(index) == reference["distinct_diagnostics"], "Reference diagnostic count differs")
    _require(
        sum(e["reference_occurrences"] for e in entries) == reference["csv_records"], "Reference record count differs"
    )
    profile["index"] = index
    return profile


def classify_kgxval_report(
    report_path: Path,
    *,
    profile_path: Path = DEFAULT_PROFILE,
    reference_path: Path = DEFAULT_REFERENCE,
    expected_report_sha256: str | None = None,
    require_reference_cohort: bool = False,
    graph_archive_path: Path | None = None,
) -> dict:
    """Classify every CSV record while retaining unregistered and unresolved diagnostics."""
    report_path, profile_path, reference_path = Path(report_path), Path(profile_path), Path(reference_path)
    implementation = Path(__file__).resolve()
    bound_paths = (
        report_path,
        profile_path,
        reference_path,
        implementation,
        implementation.parent / "metpo_predicates.py",
        implementation.parents[1] / "transform_utils" / "constants.py",
    )
    if graph_archive_path is not None:
        graph_archive_path = Path(graph_archive_path)
        bound_paths += (graph_archive_path,)
    inputs = {str(path.resolve()): file_identity(path) for path in bound_paths}
    report_identity = inputs[str(report_path.resolve())]
    graph_identity = inputs[str(graph_archive_path.resolve())] if graph_archive_path is not None else None
    if expected_report_sha256 is not None:
        _require(report_identity["sha256"] == expected_report_sha256, "Report SHA-256 differs")
    profile = load_profile(profile_path)
    reference = load_reference_dispositions(reference_path, profile=profile)
    counts, rows, physical_lines = Counter(), {}, {}
    with report_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        _require(tuple(reader.fieldnames or ()) == CSV_FIELDS, "Expected the exact six-column KGXVal CSV header")
        for row in reader:
            signature = diagnostic_signature(row)
            _require(row["INGEST_NAME"] and row["NORMALIZED"] and row["PREDICATE"] and row["ERROR"], "Empty key cell")
            _require(row["ERROR"] in {"BAD BIOLINK", "BAD SUBJECT", "BAD OBJECT"}, "Unknown diagnostic type")
            counts[signature] += 1
            rows[signature] = row
            physical_lines.setdefault(signature, []).append(reader.line_num)
            _require(len(counts) <= MAX_DISTINCT_DIAGNOSTICS, "Diagnostic registry bound exceeded")
    _require(bool(counts), "No diagnostics supplied; an empty CSV does not certify validator completion")
    index = profile["index"]
    reference_counts = {key: value["reference_occurrences"] for key, value in index.items()}
    reference_cohort_matches = dict(counts) == reference_counts
    reference_evidence_applies = (
        reference_cohort_matches
        and report_identity["sha256"] == profile["reference"]["csv_sha256"]
        and graph_identity is not None
        and graph_identity["sha256"] == profile["reference"]["archive_sha256"]
    )
    if require_reference_cohort:
        _require(reference_cohort_matches, "Reference diagnostic cohort or record multiplicities differ")
        _require(report_identity["sha256"] == profile["reference"]["csv_sha256"], "Reference CSV bytes differ")
        if graph_identity is not None:
            _require(
                graph_identity["sha256"] == profile["reference"]["archive_sha256"], "Reference graph archive differs"
            )
    diagnostics, by_disposition = [], Counter()
    for signature in sorted(counts):
        entry = index.get(signature)
        disposition = entry["disposition"] if entry else "unregistered_diagnostic"
        definition = profile["dispositions"].get(disposition, {})
        by_disposition[disposition] += 1
        diagnostics.append(
            {
                "signature_sha256": signature,
                "original_diagnostic": rows[signature],
                "csv_records": counts[signature],
                "csv_physical_end_lines": physical_lines[signature],
                "disposition": disposition,
                "status": "registered_project_extension"
                if disposition == "native_predicate_project_extension"
                else "review_required",
                "evidence": definition.get("evidence", []),
                "remaining_verification": definition.get(
                    "remaining_verification", "New exact diagnostic requires explicit review and profile revision."
                ),
                "strict_conformance": False,
                "scientific_acceptance": False,
                "reference_assessment": reference["index"].get(signature) if reference_evidence_applies else None,
            }
        )
    review_required = sum(d["status"] == "review_required" for d in diagnostics)
    unregistered = by_disposition["unregistered_diagnostic"]
    unchanged = all(file_identity(Path(path)) == identity for path, identity in inputs.items())
    _require(unchanged, "Classification input bytes changed during review")
    return {
        "contract": validation_contract(),
        "profile_id": profile["profile_id"],
        "scope": "complete_supplied_csv_diagnostic_classification_only",
        "status": "UNREGISTERED_DIAGNOSTICS"
        if unregistered
        else "CLASSIFIED_REVIEW_REQUIRED"
        if review_required
        else "CLASSIFIED_NATIVE_EXTENSIONS_ONLY",
        "classification_complete": not unregistered,
        "reference_cohort_matches": reference_cohort_matches,
        "reference_evidence_applies": reference_evidence_applies,
        "reference_epoch": dict(profile["reference"]),
        "supplied_graph_archive": {"path": str(graph_archive_path.resolve()), **graph_identity}
        if graph_identity is not None
        else None,
        "reference_assessment_counts": reference["group_counts"] if reference_evidence_applies else {},
        "csv_records": sum(counts.values()),
        "distinct_diagnostics": len(counts),
        "by_disposition": dict(sorted(by_disposition.items())),
        "review_required_diagnostics": review_required,
        "unregistered_diagnostics": unregistered,
        "diagnostics": diagnostics,
        "inputs": inputs,
        "inputs_unchanged": unchanged,
        "model_reference": {
            key: value
            for key, value in profile["reference"].items()
            if key.startswith("biolink") or key.startswith("predicate_map")
        },
        "strict_conformance": False,
        "scientific_acceptance": False,
        "release_authorized": False,
        "limitations": [
            "CSV records and distinct diagnostics are not graph-row or complete edge-signature counts.",
            "CSV omits endpoint IDs, relation, source, and the opposite endpoint's categories.",
            "Reference row-rule coverage applies only to the exact original CSV and pinned graph epoch.",
            "Archive hashing binds supplied bytes; it does not establish CSV origins or rerun validation.",
            "Catalog evidence shapes are checked locally; the external saved join is not authenticated here.",
            "Unresolved source/model families remain actionable; no category signature grants a house-rule pass.",
            "Native predicate registration does not validate its endpoint types, relation or biological evidence.",
            "Model hashes identify the reference epoch; classification does not rerun or certify the validator.",
        ],
    }


def load_reference_dispositions(path: Path = DEFAULT_REFERENCE, *, profile: dict | None = None) -> dict:
    """Validate finite reference evidence, never transfer it to another graph epoch."""
    profile = profile if profile is not None else load_profile()
    with Path(path).open(encoding="utf-8") as stream:
        reference = json.load(stream, object_pairs_hook=_unique_object)
    _require(type(reference.get("version")) is int and reference["version"] == 1, "Unknown evidence version")
    _require(reference.get("profile_id") == "kgm-kgxval-reference-evidence-v1", "Unknown evidence profile")
    _require(reference.get("scope") == "exact_reference_epoch_only_not_a_signature_waiver", "Unsafe evidence scope")
    _require(reference["reference"] == profile["reference"], "Reference epoch differs")
    for flag in ("strict_conformance", "scientific_acceptance", "release_authorized"):
        _require(reference.get(flag) is False, f"Forbidden reference acceptance: {flag}")
    join = reference["evidence_join"]
    _require(join.get("inputs_unchanged") is True, "Unsettled join evidence")
    _require(isinstance(join.get("path"), str) and bool(join["path"].strip()), "Missing join evidence locator")
    _require(_valid_sha256(join.get("sha256")), "Missing or invalid join evidence SHA-256")
    _require(type(join.get("bytes")) is int and join["bytes"] > 0, "Missing or invalid join evidence size")
    expected = {key for key, entry in profile["index"].items() if entry["error"] != "BAD BIOLINK"}
    index, groups = {}, Counter()
    for entry in reference["diagnostics"]:
        signature, group = entry["signature_sha256"], entry["reference_disposition"]
        _require(signature in expected and signature not in index, "Unknown/duplicate reference diagnostic")
        _require(group in reference["groups"], "Unregistered reference disposition")
        definition = reference["groups"][group]
        _require(all(definition.get(k) for k in ("status", "diagnosis", "remaining_action")), "Incomplete action")
        total = entry["matched_endpoint_sides"]
        _require(type(total) is int and total > 0, "Invalid joined count")
        for field in ("existing_row_rule_counts", "sources", "relations", "prefix_pairs"):
            counter = entry[field]
            _require(counter and all(type(v) is int and v > 0 for v in counter.values()), "Invalid join counter")
            _require(sum(counter.values()) == total, "Incomplete reference join counter")
        supported = not entry["existing_row_rule_counts"].get("NO_EXISTING_PRECISE_RULE")
        _require(
            supported == (group == "documented_row_convention_supported"),
            "Unsupported reference row-rule acceptance",
        )
        _require(bool(entry["witnesses"]), "Missing reference witnesses")
        for witness in entry["witnesses"]:
            row = witness["assertion"]
            _require(_valid_sha256(witness.get("original_full_row_sha256")), "Missing or invalid witness SHA-256")
            declarations = witness.get("endpoint_declarations")
            _require(isinstance(declarations, list) and len(declarations) == 2, "Missing paired endpoint declarations")
            _require(
                [node.get("id") for node in declarations] == [row["subject"], row["object"]],
                "Witness endpoint declarations differ",
            )
            for node, side in zip(declarations, ("subject", "object"), strict=True):
                _require(
                    all(isinstance(node.get(key), str) for key in ("id", "category", "name", "provided_by")),
                    "Missing endpoint declaration fields",
                )
                _require(
                    node["category"].split("|") == witness.get(f"{side}_categories"),
                    "Witness endpoint categories differ",
                )
            _require(row["predicate"] == profile["index"][signature]["predicate"], "Witness predicate differs")
            _require(row["primary_knowledge_source"] in entry["sources"], "Unattributed witness")
            _require(row["relation"] in entry["relations"], "Unsupported witness relation")
        index[signature] = {**entry, **definition}
        groups[group] += 1
    _require(set(index) == expected, "Incomplete reference category dispositions")
    _require(dict(groups) == reference["group_counts"], "Reference group counts differ")
    reference["index"] = index
    return reference


def _valid_sha256(value) -> bool:
    """Check a recorded digest's shape, not the external evidence file's contents."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
