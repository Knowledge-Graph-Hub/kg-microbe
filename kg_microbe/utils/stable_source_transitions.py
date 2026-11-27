"""
Reconcile explicitly reviewed historical CM owner changes without granting identity.

This extension consumes already reconstructed native decisions. It does not
replace native scientific review, source conservation, or downstream hold policy.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

import yaml

from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json
from kg_microbe.utils.stable_source_candidate import _keys, _require

CONTRACT = "kg-microbe-cm-binding-transitions/v1"
DIMENSION = "cm_binding_transition_sha256"
CM_INPUTS = {"source_manifest", "prepared_intake", "reviewed_intake", "binding_review"}
BEFORE_FIELDS = {
    "binding_row_sha256",
    "binding_decision_sha256",
    "disposition",
    "owner_record",
    "owner_record_sha256",
}
AFTER_FIELDS = {
    "source_id",
    "source_position",
    "payload_sha256",
    "disposition",
    "owner_record",
    "owner_record_sha256",
}


def _digest(value):
    """Hash the complete literal JSON domain shared with native payload review."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _sha(value):
    """Require an actual lowercase SHA256 string, never a truthy placeholder."""
    _require(isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value), "invalid transition digest")


def _declaration(value):
    """Require one explicit repository-relative input declaration."""
    _keys(value, {"path", "sha256"})
    name = value["path"]
    _require(
        isinstance(name, str)
        and name
        and not PurePosixPath(name).is_absolute()
        and PurePosixPath(name).as_posix() == name
        and ".." not in PurePosixPath(name).parts
        and "\\" not in name,
        "unsafe transition evidence path",
    )
    _sha(value["sha256"])


def _index(values, field, label):
    """Index exact identifiers while refusing duplicates and malformed arrays."""
    _require(isinstance(values, list), "invalid transition " + label)
    result = {}
    for value in values:
        _require(isinstance(value, dict), "invalid transition " + label)
        key = value.get(field)
        _require(isinstance(key, str) and key and key not in result, "duplicate transition " + label)
        result[key] = value
    return result


class TransitionReconciliation:
    """Require an exact paired-review entry for every final-route owner change."""

    def __init__(self, guard, selection, payload, bindings):
        """Bind a selected ledger to immutable historical and native evidence."""
        self.guard = guard
        self.selection = selection
        self.payload = payload
        self.bindings = bindings
        self.entries = {}
        self.used = set()
        self.occurrences = 0
        self._seen = {}
        self._reports = {}
        self._checks = {}
        self.declaration = selection["owner_transitions"]
        if self.declaration is None:
            return
        _declaration(self.declaration)
        document = read_json(guard.read(self.declaration))
        _keys(document, {"contract", "culturemech", "native_source", "entries"})
        _require(document["contract"] == CONTRACT, "unsupported CM transition reconciliation")
        _keys(document["culturemech"], CM_INPUTS)
        _require(document["culturemech"] == selection["culturemech"], "transition historical selection differs")
        self.source_review = payload["provenance"]["source_review"]
        self.inputs = payload["provenance"]["source_manifest"]["inputs"]
        self.request_inputs = self.source_review["inputs"]
        _require(
            self.request_inputs.get(self.declaration["path"]) == self.declaration["sha256"],
            "transition ledger is not a native request input",
        )
        source = self.source_review["source"]
        expected = {
            "nodes": {"path": source["nodes"], "sha256": source["nodes_sha256"]},
            "occurrences": {"path": source["occurrences"], "sha256": source["occurrences_sha256"]},
        }
        _require(document["native_source"] == expected, "transition native source differs")
        for declaration in expected.values():
            guard.read(declaration)
        historical = read_json(guard.read(selection["culturemech"]["binding_review"]))
        self.decisions = _index(historical["decisions"], "case_id", "historical decisions")
        self.prepared = read_json(guard.read(selection["culturemech"]["prepared_intake"]))
        package_ref = selection["combined_source_scope"]["authorities"]["culturemech_package"]
        _declaration(package_ref)
        _require(
            self.source_review["culturemech_intake_replay"] == package_ref,
            "transition historical package differs",
        )
        self.package = read_json(guard.read(package_ref))
        self.package_root = PurePosixPath(package_ref["path"]).parent
        entries = document["entries"]
        _require(isinstance(entries, list) and entries, "empty transition reconciliation")
        for entry in entries:
            _keys(entry, {"case_id", "before", "after", "evidence"})
            _keys(entry["before"], BEFORE_FIELDS)
            _keys(entry["after"], AFTER_FIELDS)
            _require(
                isinstance(entry["case_id"], str) and entry["case_id"] in bindings,
                "unknown transition historical case",
            )
            for field in ("binding_row_sha256", "binding_decision_sha256", "owner_record_sha256"):
                _sha(entry["before"][field])
            _sha(entry["after"]["payload_sha256"])
            before, after = entry["before"], entry["after"]
            _require(
                before["disposition"] in {"SUPPORTED", "WITHHOLD"}
                and after["disposition"] in {"SUPPORTED", "WITHHOLD"}
                and isinstance(before["owner_record"], str)
                and bool(before["owner_record"]),
                "invalid transition disposition or historical owner",
            )
            _require(
                isinstance(after["source_id"], str)
                and bool(after["source_id"])
                and type(after["source_position"]) is int
                and after["source_position"] > 0,
                "invalid transition native coordinate",
            )
            if after["owner_record"] is None:
                _require(
                    after["owner_record_sha256"] is None and after["disposition"] == "WITHHOLD",
                    "ownerless transition cannot support identity",
                )
            else:
                _require(isinstance(after["owner_record"], str) and after["owner_record"], "invalid transition owner")
                _sha(after["owner_record_sha256"])
            evidence = entry["evidence"]
            _require(isinstance(evidence, list) and evidence, "transition lacks substantive evidence")
            names = set()
            for declaration in evidence:
                _declaration(declaration)
                _require(
                    declaration["path"] not in names and declaration["path"] != self.declaration["path"],
                    "duplicate or self-referential transition evidence",
                )
                names.add(declaration["path"])
                _require(
                    self.request_inputs.get(declaration["path"]) == declaration["sha256"],
                    "transition evidence is not a native request input",
                )
                guard.read(declaration)
            key = entry["case_id"], after["source_id"], after["source_position"]
            _require(key not in self.entries, "duplicate transition entry")
            self.entries[key] = entry

    def _historical_owner(self, binding):
        """Resolve historical bytes through the selected accepted package only."""
        name, digest = binding["owner_record"], binding["owner_record_sha256"]
        if name == "source/bundle/manifest.json":
            declaration = self.selection["culturemech"]["source_manifest"]
            _require(digest == declaration["sha256"], "historical source fallback owner differs")
            self.guard.read(declaration)
            return declaration["path"]
        metadata = self.prepared["mim_record_inputs"].get(name)
        _keys(metadata, {"bytes", "sha256"})
        _require(
            name.startswith("data/ingredients/")
            and name.endswith(".yaml")
            and metadata["sha256"] == digest
            and type(metadata["bytes"]) is int
            and metadata["bytes"] >= 0,
            "historical transition owner differs",
        )
        member = "consumer/" + name
        _require(self.package["files"].get(member) == metadata, "historical owner package member differs")
        path = (self.package_root / member).as_posix()
        raw = self.guard.read({"path": path, "sha256": digest})
        _require(len(raw) == metadata["bytes"], "historical transition owner size differs")
        return path

    def _report(self, reference):
        """Read the actual native YAML/Markdown pair selected by manifest bytes."""
        _keys(reference, {"path", "target_id", "assessment_id"})
        path = reference["path"]
        if path in self._reports:
            return self._reports[path]
        _require(PurePosixPath(path).name == "review.yaml", "noncanonical native transition review")
        pair = (path, str(PurePosixPath(path).with_name("review.md")))
        raw = None
        for member in pair:
            digest = self.inputs.get(member)
            _sha(digest)
            _require(self.request_inputs.get(member) == digest, "transition review pair is not selected")
            value = self.guard.read({"path": member, "sha256": digest})
            if member == path:
                raw = value
        report = yaml.safe_load(raw)
        _require(
            isinstance(report, dict)
            and report.get("repository") == "CultureBotAI/MediaIngredientMech"
            and report.get("scientific_review") is True
            and report.get("completion") == "completed",
            "transition requires completed native scientific reports",
        )
        parsed = (
            report,
            _index(report["assessments"], "assessment_id", "native assessments"),
            _index(report["source"]["inputs"], "path", "native report inputs"),
            _index(report["evidence"], "evidence_id", "native report evidence"),
            set(report["scope"]["reviewed_target_ids"]),
        )
        self._reports[path] = parsed
        return parsed

    def _assessment(self, role, decision, entry, forbidden, forbidden_digests):
        """Require explicit entry review and exact shared captured source evidence."""
        validated = decision[role]
        reference = validated["reference"]
        report, assessments, report_inputs, evidence, reviewed_targets = self._report(reference)
        assessment = assessments.get(reference["assessment_id"])
        _require(
            assessment == validated["assessment"]
            and report["reviewer"] == validated["reviewer"]
            and assessment["target_ids"] == [reference["target_id"]]
            and assessment["area"] == "identity"
            and reference["target_id"] in reviewed_targets,
            "transition native assessment differs",
        )
        declarations = [self.declaration, *entry["evidence"]]
        for declaration in declarations:
            _require(
                report_inputs.get(declaration["path"], {}).get("sha256") == declaration["sha256"],
                "transition evidence missing from paired report inputs",
            )
        dimensions = _index(assessment.get("dimensions", []), "name", "assessment dimensions")
        dimension = dimensions.get(DIMENSION, {})
        _require(
            dimension.get("value") == _digest(entry)
            and isinstance(dimension.get("definition"), str)
            and dimension["definition"].strip(),
            "native report lacks exact transition-entry review",
        )
        selected = dimension.get("evidence_ids")
        _require(
            isinstance(selected, list)
            and selected
            and len(set(selected)) == len(selected)
            and set(selected) <= set(assessment["evidence_ids"])
            and set(selected) <= set(evidence),
            "transition review evidence references differ",
        )
        referenced = [evidence[name] for name in selected]
        for declaration in declarations:
            matches = [
                item
                for item in referenced
                if item["reference"] == declaration["path"]
                and item.get("snapshot_sha256") == declaration["sha256"]
                and item.get("support") == "supports"
            ]
            _require(matches, "transition assessment omits captured evidence")
            if declaration != self.declaration:
                _require(
                    declaration["path"] not in forbidden
                    and declaration["sha256"] not in forbidden_digests
                    and any(item["kind"] in {"primary_source", "database", "authority"} for item in matches),
                    "transition lacks independent substantive source evidence",
                )

    def _validate(self, binding, decision, entry):
        """Join complete before/after claims and both already-admitted reviews."""
        before = {
            "binding_row_sha256": _digest(binding),
            "binding_decision_sha256": _digest(self.decisions[binding["case_id"]]),
            **{key: binding[key] for key in ("disposition", "owner_record", "owner_record_sha256")},
        }
        claim = decision["payload"]
        after = {
            "source_id": claim["source_id"],
            "source_position": claim["source_position"],
            "payload_sha256": _digest(claim),
            "disposition": decision["disposition"],
            "owner_record": claim["owner_record"],
            "owner_record_sha256": claim["owner_record_sha256"],
        }
        _require(
            entry["before"] == before
            and entry["after"] == after
            and decision["payload_sha256"] == after["payload_sha256"],
            "transition before/after binding differs",
        )
        previous_owner = self._historical_owner(binding)
        current_owner = claim["owner_record"]
        if current_owner is not None:
            _require(
                self.source_review["record_inputs"].get(current_owner) == claim["owner_record_sha256"],
                "transition current owner is not selected",
            )
            self.guard.read({"path": current_owner, "sha256": claim["owner_record_sha256"]})
        cases = self.source_review["cases"]
        position = claim["source_position"]
        _require(position <= len(cases), "transition native case is missing")
        case = cases[position - 1]
        _require(
            case["source_position"] == position
            and case["owner_record"] == current_owner
            and case["primary"] == decision["primary"]["reference"]
            and case["skeptic"] == decision["skeptic"]["reference"],
            "transition selected native review references differ",
        )
        primary, skeptic = decision["primary"], decision["skeptic"]
        _require(
            primary["reference"]["path"] != skeptic["reference"]["path"]
            and primary["reviewer"]["identity"] != skeptic["reviewer"]["identity"]
            and skeptic["reviewer"]["independence"] == "independent"
            and type(primary["supported"]) is bool
            and type(skeptic["supported"]) is bool,
            "transition requires distinct independent native reviewers",
        )
        supported = primary["supported"] and skeptic["supported"]
        _require(
            (decision["disposition"] == "SUPPORTED") == supported
            and (
                not supported
                or (current_owner and not claim["holds"] and claim["mapping_status"] in {"MAPPED", "UNMAPPED"})
            ),
            "transition cannot replace native identity or hold admission",
        )
        forbidden = {self.declaration["path"], previous_owner, current_owner}
        forbidden_digests = {
            self.declaration["sha256"],
            binding["owner_record_sha256"],
            *self.source_review["record_inputs"].values(),
        }
        for role in ("primary", "skeptic"):
            path = decision[role]["reference"]["path"]
            pair = (path, str(PurePosixPath(path).with_name("review.md")))
            forbidden.update(pair)
            for member in pair:
                digest = self.inputs.get(member)
                _sha(digest)
                forbidden_digests.add(digest)
        for digest in forbidden_digests:
            _sha(digest)
        for role in ("primary", "skeptic"):
            self._assessment(role, decision, entry, forbidden, forbidden_digests)

    def check(self, binding, decision):
        """Validate every case, including zero-occurrence cases, before final counts."""
        claim = decision["payload"]
        _require(
            type(claim["source_position"]) is int
            and claim["source_position"] > 0
            and isinstance(claim["occurrences"], list),
            "invalid transition native case coordinate",
        )
        key = binding["case_id"], claim["source_id"], claim["source_position"]
        changed = any(
            binding[field] != (decision[field] if field == "disposition" else claim[field])
            for field in ("disposition", "owner_record", "owner_record_sha256")
        )
        entry = self.entries.get(key) if changed else None
        _require(not changed or entry is not None, "CM binding transition requires reviewed reconciliation")
        identity = id(binding), id(decision)
        previous = self._checks.get(identity)
        if previous is not None:
            _require(previous[4] == key and previous[2] is entry, "transition pair changed between occurrences")
        else:
            token = _digest(binding), _digest(decision), _digest(entry) if entry is not None else None
            _require(key not in self._seen or self._seen[key] == token, "transition pair changed between occurrences")
            _require(decision["payload_sha256"] == _digest(claim), "transition native payload digest differs")
            if changed:
                self._validate(binding, decision, entry)
            self._seen[key] = token
            self._checks[identity] = binding, decision, entry, token, key
        if changed and key not in self.used:
            self.used.add(key)
            self.occurrences += len(claim["occurrences"])

    def finish(self):
        """Reject unconsumed entries or in-memory drift before returning counts."""
        _require(self.used == set(self.entries), "extra or unchanged transition entry")
        for binding, decision, entry, expected, _ in self._checks.values():
            _require(
                (_digest(binding), _digest(decision), _digest(entry) if entry is not None else None) == expected,
                "transition pair changed during reconciliation",
            )
        return {"reconciled_binding_transitions": len(self.used), "transition_occurrences": self.occurrences}
