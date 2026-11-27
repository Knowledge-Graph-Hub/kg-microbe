"""
Join independently selected final CM/KGM inputs to native conservation.

This module consumes an already reconstructed native candidate. It does not
invent a native proof object, execute a producer, or grant release authority.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json
from kg_microbe.utils.stable_source_candidate import _keys, _path, _require
from kg_microbe.utils.stable_source_native_bridge import CONSERVATION_CAPABILITY, require_combined_conservation

AUTHORITY_ROLES = frozenset(
    {
        "culturemech_package",
        "kg_source_selection",
        "kg_source_manifest",
        "kg_row_reconciliation",
        "kg_full_node_ledger",
        "kg_full_row_ledger_json",
        "kg_full_row_ledger_tsv",
        "kg_transport_manifest",
        "kg_nodes",
        "kg_occurrences",
        "original_case_ledger",
        "original_origin_ledger",
        "original_eligibility_intake",
    }
)
ARTIFACT_ROLES = frozenset(
    {
        "cm_nodes",
        "cm_occurrences",
        "cm_raw_row_map",
        "cm_case_crosswalk",
        "combined_nodes",
        "combined_occurrences",
        "combined_position_map",
        "cm_reconciliation",
        "kg_provider_cases",
        "historical_obligations",
        "obligation_crosswalk",
    }
)
CM_PREFIX = "MIMCMREFv1:"
CM_CONTRACT = "mim-culturemech-material-reference-v1"
CM_CARRIER = "original_occurrence_json"


def _scope(guard, scope):
    """Read the exact native profile roles selected independently by the caller."""
    _keys(scope, {"profile", "authorities", "artifacts"})
    _require(scope["profile"] == CONSERVATION_CAPABILITY, "unsupported combined source profile")
    _keys(scope["authorities"], AUTHORITY_ROLES)
    _keys(scope["artifacts"], ARTIFACT_ROLES)
    required, paths = {}, []
    for declaration in scope["authorities"].values():
        _keys(declaration, {"path", "sha256"})
        _require(
            isinstance(declaration["sha256"], str) and re.fullmatch("[a-f0-9]{64}", declaration["sha256"]),
            "invalid combined authority digest",
        )
        guard.read(declaration)
        paths.append(declaration["path"])
        required[declaration["path"]] = declaration["sha256"]
    for name in scope["artifacts"].values():
        _path(guard.root, name)
        digest = guard.inputs.get(name)
        _require(isinstance(digest, str) and re.fullmatch("[a-f0-9]{64}", digest), "unconsumed combined artifact")
        guard.read({"path": name, "sha256": digest})
        paths.append(name)
        required[name] = digest
    _require(len(paths) == len(set(paths)), "combined profile roles overlap")
    return required


def _marked(row):
    """Identify the native CM cohort while preserving unrelated opaque columns."""
    marked = row.get("source_id", "").startswith(CM_PREFIX) or row.get("projection_contract") == CM_CONTRACT
    text = row.get("projection_declaration_json", "")
    if not text:
        return marked
    try:
        declaration = read_json(text.encode("utf-8"))
    except (ValueError, UnicodeError):
        _require(not marked, "malformed marked CM declaration")
        return False
    scope = declaration.get("original_source_scope") if isinstance(declaration, dict) else None
    return marked or (isinstance(scope, dict) and bool({"profile", "authorities", "artifacts"} & set(scope)))


def _source_cohort(payload, source, declaration, raw):
    """Bind all native CM source rows to the same exact selected declaration."""
    cm_ids, all_ids = set(), set()
    for decision in payload["source_decisions"]:
        claim = decision["payload"]
        identifier = claim["source_id"]
        _require(identifier not in all_ids, "duplicate combined native source ID")
        all_ids.add(identifier)
        _require(
            claim["source_definition"] == source
            and claim["source_path"] == source["nodes"]
            and claim["occurrence_path"] == source["occurrences"],
            "combined native payload uses another source",
        )
        row = claim["source_row"]
        if _marked(row):
            _require(
                row.get("projection_declaration_json") == raw.decode("utf-8")
                and row.get("projection_declaration_path") == declaration["path"]
                and row.get("projection_declaration_sha256") == declaration["sha256"],
                "combined CM cohort differs from selected declaration",
            )
            cm_ids.add(identifier)
    _require(cm_ids, "final combined source has no declared CM cohort")
    return cm_ids, all_ids - cm_ids


def _members(guard, declaration, document, required):
    """Keep every selected receipt/package member in the required report union."""
    _require(isinstance(document.get("files"), dict) and document["files"], "missing combined member closure")
    base = Path(declaration["path"]).parent
    for name, metadata in document["files"].items():
        guard.member(declaration, name, metadata)
        path = (base / name).as_posix()
        _require(path != declaration["path"], "self-referencing combined member closure")
        _require(path not in required or required[path] == metadata["sha256"], "conflicting combined member pin")
        required[path] = metadata["sha256"]


def _report_union(guard, payload, required):
    """Require the complete selected closure in both actual scientific reports."""
    review = payload["provenance"]["source_review"]
    cases = review["cases"]
    _require(len(cases) == len(payload["source_decisions"]), "combined native case inventory differs")
    pairs = {}
    for decision, case in zip(payload["source_decisions"], cases, strict=True):
        for role in ("primary", "skeptic"):
            reference = decision[role]["reference"]
            _require(reference == case[role], "combined scientific reference differs from native request")
            _keys(reference, {"path", "target_id", "assessment_id"})
            pairs[reference["path"]] = Path(reference["path"]).with_name("review.md").as_posix()
    reports = {}
    report_members = set(pairs) | set(pairs.values())
    for group in ("record_inputs", "ledger_inputs", "inputs"):
        for name, digest in review[group].items():
            if name in report_members:
                continue
            _require(name not in required or required[name] == digest, "conflicting current native review input")
            guard.read({"path": name, "sha256": digest})
            required[name] = digest
    for name, markdown in pairs.items():
        for member in (name, markdown):
            digest = guard.inputs.get(member)
            _require(isinstance(digest, str), "missing actual native scientific report")
            raw = guard.read({"path": member, "sha256": digest})
            if member == name:
                reports[name] = yaml.safe_load(raw)
        report = reports[name]
        _require(isinstance(report, dict) and isinstance(report.get("source"), dict), "invalid native report envelope")
        declarations = report["source"].get("inputs")
        _require(isinstance(declarations, list), "missing native report source inputs")
        observed = {}
        for declaration in declarations:
            _keys(declaration, {"path", "sha256", "role"})
            _require(
                isinstance(declaration["role"], str) and declaration["role"].strip(),
                "invalid scientific input role",
            )
            _require(declaration["path"] not in observed, "duplicate scientific input declaration")
            observed[declaration["path"]] = declaration["sha256"]
        _require(
            all(observed.get(path) == digest for path, digest in required.items()),
            "scientific report omits selected combined input closure",
        )
    _require(reports, "missing paired combined scientific reviews")
    return len(reports)


def verify_conservation(guard, selection, payload, kg):
    """Join final-combined selection to native-reconstructed conservation inputs."""
    manifest = payload["provenance"]["source_manifest"]
    require_combined_conservation(manifest, selection)
    _require(selection["native_occurrence_payload_column"] == CM_CARRIER, "final combined CM carrier differs")
    scope = selection["combined_source_scope"]
    required = _scope(guard, scope)
    declaration = selection["combined_source_declaration"]
    raw = guard.read(declaration)
    document = read_json(raw)
    _require(raw == canonical_json(document), "combined declaration is not exact canonical JSON")
    _require(document.get("original_source_scope") == scope, "combined declaration differs from independent selection")
    _require(declaration["path"] not in required, "combined declaration overlaps a profile role")
    required[declaration["path"]] = declaration["sha256"]
    refs, artifacts = scope["authorities"], scope["artifacts"]
    review = payload["provenance"]["source_review"]
    source = review["source"]
    _require(
        source["nodes"] == artifacts["combined_nodes"]
        and source["occurrences"] == artifacts["combined_occurrences"]
        and source["nodes_sha256"] == required[source["nodes"]]
        and source["occurrences_sha256"] == required[source["occurrences"]],
        "selected combined tables differ from native request",
    )
    _require(
        review["culturemech_intake_replay"] == refs["culturemech_package"],
        "selected combined package differs from native replay",
    )
    _require(refs["kg_source_manifest"] == selection["kgm_source_receipt"], "selected combined KG receipt differs")
    _require(
        artifacts["cm_reconciliation"] == selection["reconciliation"]["path"]
        and required[artifacts["cm_reconciliation"]] == selection["reconciliation"]["sha256"],
        "selected combined occurrence reconciliation differs",
    )
    cm_ids, kg_ids = _source_cohort(payload, source, declaration, raw)
    owner = read_json(guard.read(refs["kg_source_selection"]))
    _require(
        {key: owner["selected_kgm"][key] for key in ("root", "revision")} == selection["current_kgm"],
        "selected combined KG generation differs",
    )
    _require(
        owner["consumed_prior_mim"]["source_commit"] == kg["consumed_reviewed"]["source_commit"]
        and owner["consumed_prior_mim"]["committed_pin_record"]["sha256"] == kg["reviewed_release_record_sha256"],
        "selected combined prior consumed release differs",
    )
    intended = owner["intended_accepted_cm_v3"]
    _require(intended["expected_counts"] == selection["expected_counts"], "owner-selected CM counts differ")
    for name, selected in selection["culturemech"].items():
        captured = guard.read(selected)
        original = intended["selected"][name]
        _require(
            original["sha256"] == selected["sha256"]
            and type(original["bytes"]) is int
            and original["bytes"] == len(captured),
            "owner-selected accepted CM evidence differs",
        )
        required[selected["path"]] = selected["sha256"]
    package_raw = guard.read(refs["culturemech_package"])
    _require(
        intended["transport_package"]["sha256"] == refs["culturemech_package"]["sha256"]
        and type(intended["transport_package"]["bytes"]) is int
        and intended["transport_package"]["bytes"] == len(package_raw),
        "owner-selected CM package differs",
    )
    receipt = read_json(guard.read(refs["kg_source_manifest"]))
    _members(guard, refs["kg_source_manifest"], receipt, required)
    _members(guard, refs["culturemech_package"], read_json(package_raw), required)
    _require(
        owner["kg_transport_manifest_sha256"] == refs["kg_transport_manifest"]["sha256"],
        "owner-selected KG transport differs",
    )
    counts = owner["row_counts"]
    _require(
        type(counts["kg_source_ids"]) is int
        and type(counts["kg_occurrences"]) is int
        and counts["kg_source_ids"] == len(kg_ids),
        "combined KG source count differs",
    )
    occurrences = sum(
        len(decision["payload"]["occurrences"])
        for decision in payload["source_decisions"]
        if decision["payload"]["source_id"] in kg_ids
    )
    _require(counts["kg_occurrences"] == occurrences, "combined KG occurrence count differs")
    report_count = _report_union(guard, payload, required)
    return {
        "profile": CONSERVATION_CAPABILITY,
        "declaration_sha256": hashlib.sha256(raw).hexdigest(),
        "selected_input_count": len(required),
        "scientific_report_count": report_count,
        "cm_source_ids": sorted(cm_ids),
        "kg_source_ids": len(kg_ids),
        "kg_occurrences": occurrences,
        "native_reconstruction_required": True,
        "production_authorized": False,
    }
