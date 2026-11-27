"""Focused byte-bound transition controls; native reconstruction is tested separately."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.stable_source_candidate import _path, _require, _Snapshots
from kg_microbe.utils.stable_source_transitions import CONTRACT, DIMENSION, TransitionReconciliation, _digest


class _Guard:
    """Use actual guarded filesystem snapshots with a miniature admitted closure."""

    def __init__(self, root, inputs):
        """Retain the test input closure without inventing a native acceptance."""
        self.root, self.inputs = root, inputs
        self.snapshots = _Snapshots()

    def read(self, declaration):
        """Read only explicitly declared manifest members through real snapshots."""
        _require(
            self.inputs.get(declaration["path"]) == declaration["sha256"],
            "integration evidence is not a selected native input",
        )
        return self.snapshots.add(_path(self.root, declaration["path"]), declaration["sha256"])

    def verify(self):
        """Recheck the same currentness primitive used by production integration."""
        self.snapshots.verify()


def _fixture(
    tmp_path,
    *,
    before_status="SUPPORTED",
    after_status="SUPPORTED",
    owner="data/ingredients/mapped/Water.yaml",
    holds=(),
):
    """Build explicit before/after files and paired review data for helper units."""
    inputs = {}

    def write(name, raw):
        """Register actual fixture bytes in the immutable-selection input map."""
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        inputs[name] = digest
        return {"path": name, "sha256": digest}

    def document(name, value):
        """Write a complete literal JSON document and select its exact bytes."""
        return write(name, canonical_json(value) + b"\n")

    original_owner = "data/ingredients/mapped/Water.yaml"
    original_bytes = b"preferred_term: Water\nmapping_status: MAPPED\n"
    archived = write("accepted/consumer/" + original_owner, original_bytes)
    owner_metadata = {"sha256": archived["sha256"], "bytes": len(original_bytes)}
    package = document("accepted/package.json", {"files": {"consumer/" + original_owner: owner_metadata}})
    source = document("accepted/source/manifest.json", {"contract": "culturemech-direct-ingredients-v3"})
    binding = {
        "case_id": "case-a",
        "disposition": before_status,
        "owner_record": original_owner if before_status == "SUPPORTED" else "source/bundle/manifest.json",
        "owner_record_sha256": archived["sha256"] if before_status == "SUPPORTED" else source["sha256"],
        "payload_sha256": "a" * 64,
        "source_literal": "water; preserve qualifier",
        "positive_occurrences": "1",
        "context_only_mentions": "1",
        "held_source_mentions": "0",
    }
    historical_decision = {
        "case_id": binding["case_id"],
        "disposition": before_status,
        "owner_record": binding["owner_record"],
        "row_sha256": binding["payload_sha256"],
        "review_reason": "Historical fixture decision",
    }
    cm = {
        "source_manifest": source,
        "prepared_intake": document(
            "accepted/prepared/intake.json", {"mim_record_inputs": {original_owner: owner_metadata}}
        ),
        "reviewed_intake": document("accepted/reviewed/reviewed-intake.json", {"status": "REVIEWED_SOURCE_INTAKE"}),
        "binding_review": document("accepted/review.json", {"decisions": [historical_decision]}),
    }
    current_owner = None
    if owner is not None:
        current_owner = write(owner, b"mim_id: MIM:1\npreferred_term: Water\nmapping_status: MAPPED\n")
    nodes = write("current/nodes.tsv", b"id\tname\nCM:case-a\tWater\n")
    occurrences = write("current/occurrences.tsv", b"source_id\tvalue\nCM:case-a\t0\nCM:case-a\t1\n")
    native_source = {
        "nodes": nodes["path"],
        "nodes_sha256": nodes["sha256"],
        "occurrences": occurrences["path"],
        "occurrences_sha256": occurrences["sha256"],
    }
    claim = {
        "source_path": nodes["path"],
        "source_definition": native_source,
        "source_position": 1,
        "source_id": "CM:case-a",
        "source_row": {"id": "CM:case-a", "original_case_json": '{"case_id":"case-a"}'},
        "occurrence_path": occurrences["path"],
        "occurrences": [
            {"position": 1, "row": {"literal": "zero", "lane": "positive_inventory"}},
            {"position": 2, "row": {"literal": "REMOVE", "lane": "context_only"}},
        ],
        "owner_record": owner,
        "owner_record_sha256": current_owner["sha256"] if current_owner else None,
        "mim_id": "MIM:1" if owner else None,
        "mapping_status": "MAPPED" if owner else None,
        "holds": list(holds),
    }
    native = {"payload": claim, "payload_sha256": _digest(claim), "disposition": after_status}
    science = write(
        "evidence/material.txt", b"Captured source evidence fixture; no real scientific approval claimed.\n"
    )
    before = {
        "binding_row_sha256": _digest(binding),
        "binding_decision_sha256": _digest(historical_decision),
        **{k: binding[k] for k in ("disposition", "owner_record", "owner_record_sha256")},
    }
    after = {
        "source_id": claim["source_id"],
        "source_position": 1,
        "payload_sha256": _digest(claim),
        "disposition": after_status,
        "owner_record": owner,
        "owner_record_sha256": claim["owner_record_sha256"],
    }
    entry = {"case_id": "case-a", "before": before, "after": after, "evidence": [science]}
    ledger = {
        "contract": CONTRACT,
        "culturemech": cm,
        "native_source": {"nodes": nodes, "occurrences": occurrences},
        "entries": [entry],
    }
    selection = {
        "owner_transitions": None,
        "culturemech": cm,
        "combined_source_scope": {"authorities": {"culturemech_package": package}},
    }
    request = {
        "source": native_source,
        "inputs": inputs,
        "culturemech_intake_replay": package,
        "record_inputs": {owner: current_owner["sha256"]} if owner else {},
        "cases": [{"source_position": 1, "owner_record": owner}],
    }
    reports = {}
    for role in ("primary", "skeptic"):
        reference = {
            "path": "reviews/structured/" + role + "/review.yaml",
            "target_id": "source-1",
            "assessment_id": "identity-1",
        }
        reviewer = {
            "identity": role + "-reviewer",
            "kind": "agent",
            "independence": "independent" if role == "skeptic" else "self_review",
        }
        assessment = {
            "assessment_id": "identity-1",
            "area": "identity",
            "target_ids": ["source-1"],
            "outcome": "supported" if after_status == "SUPPORTED" else "unknown",
            "evidence_ids": ["transition", "material"],
            "dimensions": [],
        }
        report = {
            "repository": "CultureBotAI/MediaIngredientMech",
            "completion": "completed",
            "scientific_review": True,
            "reviewer": reviewer,
            "scope": {"reviewed_target_ids": ["source-1"]},
            "source": {"inputs": []},
            "assessments": [assessment],
            "evidence": [],
        }
        reports[role] = report
        request["cases"][0][role] = reference
        native[role] = {
            "reference": reference,
            "reviewer": reviewer,
            "assessment": assessment,
            "supported": after_status == "SUPPORTED",
            "provenance": {"status": "verified"},
        }
    payload = {
        "source_decisions": [native],
        "provenance": {"source_review": request, "source_manifest": {"inputs": inputs}},
    }

    def refresh(mutate_reports=None):
        """Rebind fixture bytes coherently before invoking the actual helper."""
        selected = document("transition/reconciliation.json", ledger)
        selection["owner_transitions"] = selected
        required = {name: digest for name, digest in inputs.items() if not name.startswith("reviews/structured/")}
        for role, report in reports.items():
            report["source"]["inputs"] = [
                {"path": name, "sha256": digest, "role": "captured fixture"}
                for name, digest in sorted(required.items())
            ]
            report["assessments"][0]["dimensions"] = [
                {
                    "name": DIMENSION,
                    "value": _digest(entry),
                    "definition": "Exact before/after transition",
                    "evidence_ids": ["transition", "material"],
                }
            ]
            report["evidence"] = [
                {
                    "evidence_id": "transition",
                    "kind": "prior_review",
                    "support": "supports",
                    "reference": selected["path"],
                    "snapshot_sha256": selected["sha256"],
                },
                {
                    "evidence_id": "material",
                    "kind": "primary_source",
                    "support": "supports",
                    "reference": science["path"],
                    "snapshot_sha256": science["sha256"],
                },
            ]
            if mutate_reports is not None:
                mutate_reports(role, report)
            reference = native[role]["reference"]
            write(reference["path"], yaml.safe_dump(report, sort_keys=False).encode())
            write(
                str(Path(reference["path"]).with_name("review.md")), b"Native-derived Markdown is verified upstream.\n"
            )
            native[role]["assessment"] = deepcopy(report["assessments"][0])
            native[role]["reviewer"] = deepcopy(report["reviewer"])

    refresh()

    def begin():
        """Use a new real snapshot guard for each immutable candidate attempt."""
        guard = _Guard(tmp_path, inputs)
        result = TransitionReconciliation(guard, selection, payload, {"case-a": binding})
        return result, guard

    return {
        "begin": begin,
        "refresh": refresh,
        "write": write,
        "document": document,
        "binding": binding,
        "historical_decision": historical_decision,
        "native": native,
        "claim": claim,
        "ledger": ledger,
        "entry": entry,
        "selection": selection,
        "inputs": inputs,
        "request": request,
        "reports": reports,
        "root": tmp_path,
        "science": science,
    }


def _complete(fixture, occurrences=1):
    """Run actual transition checks and the enclosing guard's currentness check."""
    result, guard = fixture["begin"]()
    for _ in range(occurrences):
        result.check(fixture["binding"], fixture["native"])
    summary = result.finish()
    guard.verify()
    return summary


def test_reviewed_same_path_changed_owner_bytes_and_repeated_occurrences(tmp_path):
    """Byte changes require one exact entry even when the literal owner path stays."""
    fixture = _fixture(tmp_path)
    original = deepcopy(fixture["claim"]["occurrences"])
    assert _complete(fixture, 2) == {"reconciled_binding_transitions": 1, "transition_occurrences": 2}
    assert fixture["claim"]["occurrences"] == original


@pytest.mark.parametrize(
    "before,after,owner",
    [
        ("SUPPORTED", "SUPPORTED", "data/ingredients/mapped/Water_current.yaml"),
        ("WITHHOLD", "SUPPORTED", "data/ingredients/mapped/Water.yaml"),
        ("SUPPORTED", "WITHHOLD", None),
        ("WITHHOLD", "WITHHOLD", None),
    ],
)
def test_only_exact_reviewed_owner_and_disposition_transitions_are_supported(tmp_path, before, after, owner):
    """Each finite changed-owner or changed-disposition route keeps native status."""
    fixture = _fixture(tmp_path, before_status=before, after_status=after, owner=owner)
    assert _complete(fixture)["reconciled_binding_transitions"] == 1
    assert fixture["native"]["disposition"] == after


def test_absent_reconciliation_preserves_unchanged_route(tmp_path):
    """Unchanged native owner bindings do not require an invented transition entry."""
    fixture = _fixture(tmp_path)
    fixture["selection"]["owner_transitions"] = None
    fixture["binding"]["owner_record_sha256"] = fixture["claim"]["owner_record_sha256"]
    assert _complete(fixture) == {"reconciled_binding_transitions": 0, "transition_occurrences": 0}


def test_missing_reconciliation_refuses_actual_change(tmp_path):
    """Absence never waives same-path owner byte drift."""
    fixture = _fixture(tmp_path)
    fixture["selection"]["owner_transitions"] = None
    with pytest.raises(ValueError, match="requires reviewed reconciliation"):
        _complete(fixture)


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("before", "binding_row_sha256", "0" * 64),
        ("before", "binding_decision_sha256", "0" * 64),
        ("before", "owner_record", "data/ingredients/mapped/Other.yaml"),
        ("before", "owner_record_sha256", "0" * 64),
        ("before", "disposition", "WITHHOLD"),
        ("after", "payload_sha256", "0" * 64),
        ("after", "owner_record", "data/ingredients/mapped/Other.yaml"),
        ("after", "owner_record_sha256", "0" * 64),
        ("after", "disposition", "WITHHOLD"),
        ("after", "source_id", "CM:other"),
        ("after", "source_position", 2),
    ],
)
def test_coherently_rehashed_wrong_transition_is_refused(tmp_path, part, field, value):
    """Fresh ledger/report hashes cannot replace the actual historical/native join."""
    fixture = _fixture(tmp_path)
    fixture["entry"][part][field] = value
    fixture["refresh"]()
    with pytest.raises(ValueError, match="transition"):
        _complete(fixture)


@pytest.mark.parametrize("change", ["duplicate", "unknown_case", "empty", "extra", "no_op"])
def test_transition_entries_have_complete_changed_pair_coverage(tmp_path, change):
    """Duplicates, absent cohorts, extras and unchanged entries are not evidence."""
    fixture = _fixture(tmp_path)
    if change == "duplicate":
        fixture["ledger"]["entries"].append(deepcopy(fixture["entry"]))
    elif change == "unknown_case":
        fixture["entry"]["case_id"] = "other"
    elif change == "empty":
        fixture["ledger"]["entries"] = []
    elif change == "extra":
        extra = deepcopy(fixture["entry"])
        extra["after"]["source_id"] = "CM:unused"
        fixture["ledger"]["entries"].append(extra)
    else:
        fixture["binding"]["owner_record_sha256"] = fixture["claim"]["owner_record_sha256"]
    fixture["refresh"]()
    with pytest.raises(ValueError, match="transition"):
        _complete(fixture)


@pytest.mark.parametrize(
    "change",
    [
        "missing_dimension",
        "wrong_dimension",
        "duplicate_dimension",
        "missing_ledger_evidence",
        "nonprimary",
        "evidence_hash",
        "missing_input",
        "same_reviewer",
        "nonindependent",
        "assessment_scope",
    ],
)
def test_both_native_reports_must_explicitly_review_the_entry(tmp_path, change):
    """A correct primary report cannot substitute for missing skeptical evidence."""
    fixture = _fixture(tmp_path)

    def mutate(role, report):
        """Alter only the skeptical report while maintaining its selected byte pin."""
        if role != "skeptic":
            return
        assessment = report["assessments"][0]
        if change == "missing_dimension":
            assessment["dimensions"] = []
        elif change == "wrong_dimension":
            assessment["dimensions"][0]["value"] = "0" * 64
        elif change == "duplicate_dimension":
            assessment["dimensions"].append(deepcopy(assessment["dimensions"][0]))
        elif change == "missing_ledger_evidence":
            assessment["dimensions"][0]["evidence_ids"] = ["material"]
        elif change == "nonprimary":
            report["evidence"][1]["kind"] = "record_content"
        elif change == "evidence_hash":
            report["evidence"][1]["snapshot_sha256"] = "0" * 64
        elif change == "missing_input":
            report["source"]["inputs"] = [
                row
                for row in report["source"]["inputs"]
                if row["path"] != fixture["selection"]["owner_transitions"]["path"]
            ]
        elif change == "same_reviewer":
            report["reviewer"]["identity"] = "primary-reviewer"
        elif change == "nonindependent":
            report["reviewer"]["independence"] = "self_review"
        else:
            assessment["target_ids"] = ["other-target"]

    fixture["refresh"](mutate)
    with pytest.raises(ValueError, match="transition"):
        _complete(fixture)


@pytest.mark.parametrize("group", ["request", "manifest"])
def test_reconciliation_and_evidence_must_be_native_consumed(tmp_path, group):
    """A standalone selected sidecar never supplies the mandatory native closure."""
    fixture = _fixture(tmp_path)
    name = fixture["selection"]["owner_transitions"]["path"]
    if group == "request":
        fixture["request"]["inputs"] = {k: v for k, v in fixture["inputs"].items() if k != name}
    else:
        fixture["inputs"].pop(name)
    with pytest.raises(ValueError, match="transition|selected native input"):
        _complete(fixture)


def test_native_scientific_holds_cannot_be_cleared_by_transition(tmp_path):
    """Even paired-looking transition data cannot override the native held payload."""
    fixture = _fixture(tmp_path, holds=["identity unresolved"])
    with pytest.raises(ValueError, match="cannot replace native identity or hold"):
        _complete(fixture)


def test_current_owner_bytes_are_read_not_trusted(tmp_path):
    """The current owner pin must still name the actual file bytes."""
    fixture = _fixture(tmp_path)
    (tmp_path / fixture["claim"]["owner_record"]).write_text("changed owner\n")
    with pytest.raises(ValueError, match="input pin differs"):
        _complete(fixture)


def test_historical_owner_bytes_are_read_not_trusted(tmp_path):
    """Accepted historical owner metadata must rejoin the archived beforeimage."""
    fixture = _fixture(tmp_path)
    (tmp_path / ("accepted/consumer/" + fixture["binding"]["owner_record"])).write_text("changed beforeimage\n")
    with pytest.raises(ValueError, match="input pin differs"):
        _complete(fixture)


def test_same_object_payload_drift_after_cached_check_is_refused(tmp_path):
    """Repeated occurrence caching still checks complete payload bytes at finish."""
    fixture = _fixture(tmp_path)
    result, _ = fixture["begin"]()
    result.check(fixture["binding"], fixture["native"])
    fixture["claim"]["occurrences"][0]["row"]["literal"] = "changed qualifier"
    result.check(fixture["binding"], fixture["native"])
    with pytest.raises(ValueError, match="changed during reconciliation"):
        result.finish()


def test_late_evidence_drift_is_rejected_by_retained_guard(tmp_path):
    """The integration guard retains every transition evidence file after use."""
    fixture = _fixture(tmp_path)
    result, guard = fixture["begin"]()
    result.check(fixture["binding"], fixture["native"])
    result.finish()
    (tmp_path / fixture["science"]["path"]).write_text("changed primary source\n")
    with pytest.raises(ValueError, match="input changed"):
        guard.verify()


def test_profile_and_historical_selection_are_exact(tmp_path):
    """A valid transition from another accepted CM selection cannot be borrowed."""
    fixture = _fixture(tmp_path)
    fixture["ledger"]["culturemech"] = deepcopy(fixture["ledger"]["culturemech"])
    fixture["ledger"]["culturemech"]["binding_review"]["sha256"] = "0" * 64
    fixture["refresh"]()
    with pytest.raises(ValueError, match="historical selection differs"):
        _complete(fixture)


def test_transition_native_source_is_exact(tmp_path):
    """Changed current source table hashes cannot inherit a prior transition proof."""
    fixture = _fixture(tmp_path)
    fixture["ledger"]["native_source"]["nodes"] = {"path": "elsewhere.tsv", "sha256": "0" * 64}
    fixture["refresh"]()
    with pytest.raises(ValueError, match="native source differs"):
        _complete(fixture)


def test_zero_occurrence_changed_case_still_requires_review(tmp_path):
    """No positive rows are necessary for a changed owner to require explicit review."""
    fixture = _fixture(tmp_path)
    fixture["claim"]["occurrences"] = []
    fixture["native"]["payload_sha256"] = _digest(fixture["claim"])
    fixture["entry"]["after"]["payload_sha256"] = _digest(fixture["claim"])
    fixture["refresh"]()
    assert _complete(fixture) == {"reconciled_binding_transitions": 1, "transition_occurrences": 0}
    fixture["selection"]["owner_transitions"] = None
    with pytest.raises(ValueError, match="requires reviewed reconciliation"):
        _complete(fixture)


@pytest.mark.parametrize("which", ["current_owner", "historical_owner"])
def test_owner_bytes_alone_cannot_be_the_substantive_transition_evidence(tmp_path, which):
    """Calling an owner file primary evidence does not establish a source identity."""
    fixture = _fixture(tmp_path)
    if which == "current_owner":
        path = fixture["claim"]["owner_record"]
    else:
        path = "accepted/consumer/" + fixture["binding"]["owner_record"]
    fixture["science"].update(path=path, sha256=fixture["inputs"][path])
    fixture["refresh"]()
    with pytest.raises(ValueError, match="independent substantive source evidence"):
        _complete(fixture)


def test_boolean_native_position_is_not_integer_coordinate(tmp_path):
    """Python boolean equality cannot alias a native source-position integer."""
    fixture = _fixture(tmp_path)
    fixture["claim"]["source_position"] = True
    fixture["native"]["payload_sha256"] = _digest(fixture["claim"])
    fixture["entry"]["after"]["payload_sha256"] = _digest(fixture["claim"])
    fixture["refresh"]()
    with pytest.raises(ValueError, match="native case coordinate"):
        _complete(fixture)


def test_actual_report_pair_markdown_remains_required(tmp_path):
    """A selected YAML report cannot silently lose its native Markdown sibling."""
    fixture = _fixture(tmp_path)
    path = str(Path(fixture["native"]["skeptic"]["reference"]["path"]).with_name("review.md"))
    fixture["inputs"].pop(path)
    with pytest.raises(ValueError, match="transition digest"):
        _complete(fixture)


def test_incomplete_native_report_is_not_transition_review(tmp_path):
    """A partial skeptical report cannot qualify a completed transition."""
    fixture = _fixture(tmp_path)

    def mutate(role, report):
        """Retain exact report bytes while marking the real skeptical result partial."""
        if role == "skeptic":
            report["completion"] = "partial"

    fixture["refresh"](mutate)
    with pytest.raises(ValueError, match="completed native scientific reports"):
        _complete(fixture)


def test_distinct_object_for_same_pair_cannot_change_payload(tmp_path):
    """Equivalent coordinates never excuse a different complete after payload."""
    fixture = _fixture(tmp_path)
    result, _ = fixture["begin"]()
    result.check(fixture["binding"], fixture["native"])
    forged = deepcopy(fixture["native"])
    forged["payload"]["occurrences"][0]["row"]["literal"] = "new qualifier"
    forged["payload_sha256"] = _digest(forged["payload"])
    with pytest.raises(ValueError, match="pair changed between occurrences"):
        result.check(fixture["binding"], forged)


@pytest.mark.parametrize("which", ["current", "historical", "other_current"])
def test_copied_owner_bytes_are_not_substantive_transition_evidence(tmp_path, which):
    """A different regular filename does not turn owner bytes into independent evidence."""
    fixture = _fixture(tmp_path)
    if which == "historical":
        path = "accepted/consumer/" + fixture["binding"]["owner_record"]
    elif which == "other_current":
        other = fixture["write"]("data/ingredients/mapped/Other.yaml", b"mim_id: MIM:2\npreferred_term: Other\n")
        fixture["request"]["record_inputs"][other["path"]] = other["sha256"]
        path = other["path"]
    else:
        path = fixture["claim"]["owner_record"]
    copied = fixture["write"]("evidence/copied-owner.txt", (tmp_path / path).read_bytes())
    fixture["science"].update(copied)
    fixture["refresh"]()
    with pytest.raises(ValueError, match="substantive source evidence"):
        _complete(fixture)
