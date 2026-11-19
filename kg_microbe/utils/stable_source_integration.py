"""
Reconcile selected CM v3 evidence with an already admitted native MIM candidate.

This diagnostic extends the existing consumer. It neither substitutes an intake
for native source admission nor grants source identity, physical presence or
release authority. A persisted candidate must explicitly repeat this check.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import subprocess
from collections import Counter
from pathlib import Path

from kg_microbe.transform_utils.constants import PREDICATE_COLUMN, RELATED_TO_PREDICATE
from kg_microbe.utils.ingredient_bundle_contract import canonical_json, read_json
from kg_microbe.utils.stable_ingredient_kgx import PREDICATES
from kg_microbe.utils.stable_source_candidate import STATUS, _head, _keys, _path, _require, _root, _Snapshots
from kg_microbe.utils.stable_source_native_bridge import require_cm_replay

CONTRACT = "kg-microbe-stable-source-integration/v1"
LANES = ("positive_inventory", "context_only", "held")
COUNT_FIELDS = (*LANES, "supported_bindings", "withheld_bindings")
LEDGER_FIELDS = (
    "lane",
    "source_product",
    "source_row",
    "row_sha256",
    "case_id",
    "native_source_id",
    "native_occurrence_position",
)


def _digest(value):
    """Hash a complete parsed row without discarding its context columns."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _kg_head(root):
    """Require the selected physical directory to be its own Git checkout root."""
    top = (
        subprocess.check_output(  # noqa: S603,S607 - fixed read-only Git operation
            ["git", "--no-optional-locks", "rev-parse", "--show-toplevel"],  # noqa: S607
            cwd=root,
            timeout=30,
        )
        .decode()
        .strip()
    )
    _require(Path(top).resolve(strict=True) == root, "current KG root is not its physical Git top-level")
    return _head(root)


def _rows(raw):
    """Read literal source TSV cells, preserving quoting and complete row shape."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), delimiter="\t")
    _require(
        reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "invalid integration TSV header"
    )
    for row in reader:
        _require(None not in row and all(value is not None for value in row.values()), "malformed integration TSV row")
        yield row


class _IntegrationGuard:
    """Keep diagnostic inputs and the selected upstream KG checkout live."""

    def __init__(self, candidate, selection_path, selection_sha256):
        """Capture the independently selected contract without altering persistence."""
        self.snapshots = _Snapshots()
        self.root = candidate.root
        self.inputs = candidate.payload()["provenance"]["source_manifest"]["inputs"]
        self.selection = read_json(self.snapshots.add(Path(selection_path).absolute(), selection_sha256))
        self.kg_root = None
        self.kg_revision = None
        self.kg_identity = None

    def read(self, declaration):
        """Require actual bytes to be selected by the admitted native manifest."""
        _keys(declaration, {"path", "sha256"})
        name, digest = declaration["path"], declaration["sha256"]
        _require(self.inputs.get(name) == digest, "integration evidence is not a selected native input: " + str(name))
        return self.snapshots.add(_path(self.root, name), digest)

    def member(self, declaration, name, metadata):
        """Resolve a receipt-relative member with its exact byte count and hash."""
        _keys(metadata, {"bytes", "sha256"})
        _require(type(metadata["bytes"]) is int and metadata["bytes"] >= 0, "invalid integration member size")
        base = _path(self.root, declaration["path"]).parent
        path = _path(base, name)
        raw = self.read({"path": path.relative_to(self.root).as_posix(), "sha256": metadata["sha256"]})
        _require(len(raw) == metadata["bytes"], "integration member size differs")
        return raw

    def verify(self):
        """Reject late file replacement or a moved selected KG revision."""
        if self.kg_root is not None:
            _root(str(self.kg_root))
            state = self.kg_root.stat()
            _require((state.st_dev, state.st_ino) == self.kg_identity, "current KG root identity changed")
            _require(_kg_head(self.kg_root) == self.kg_revision, "current KG revision changed")
        self.snapshots.verify()


def _consumed_release(guard, declaration, receipt, consumed):
    """Join a claimed consumed commit to the selected frozen/current release record."""
    name = "snapshots/mappings/mim_reviewed_release.json"
    _require(name in receipt["files"], "KG receipt lacks the current reviewed-release record")
    raw = guard.member(declaration, name, receipt["files"][name])
    committed = subprocess.check_output(  # noqa: S603 - revision is a validated full SHA
        [  # noqa: S607 - fixed read-only Git operation
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "show",
            guard.kg_revision + ":mappings/mim_reviewed_release.json",
        ],
        cwd=guard.kg_root,
        timeout=30,
    )
    _require(committed == raw, "KG reviewed-release record differs from the selected KG revision")
    pin = read_json(raw)
    _keys(
        pin,
        {
            "schema_version",
            "origin",
            "source_commit",
            "source_archive",
            "export_recipe",
            "validation_run_url",
            "manifest_sha256",
            "files",
            "mode",
        },
    )
    _require(
        pin["schema_version"] == 2 and pin["origin"] == "immutable_commit_export" and pin["mode"] == "candidate_only",
        "unsupported KG reviewed-release record",
    )
    _require(
        pin["source_commit"] == consumed["source_commit"], "KG consumed commit differs from the reviewed-release pin"
    )
    _keys(pin["source_archive"], {"url", "sha256"})
    _require(
        pin["source_archive"]["url"]
        == "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + pin["source_commit"],
        "KG reviewed-release archive does not identify the consumed commit",
    )
    _require(
        isinstance(pin["source_archive"]["sha256"], str)
        and re.fullmatch("[a-f0-9]{64}", pin["source_archive"]["sha256"]),
        "invalid KG reviewed-release archive pin",
    )
    products = {name: digest for name, digest in consumed["files"].items() if name != "manifest.json"}
    _require(
        pin["manifest_sha256"] == consumed["manifest_sha256"] and pin["files"] == products,
        "KG consumed products differ from the reviewed-release pin",
    )
    manifest_name = (Path(consumed["directory"]) / "manifest.json").as_posix()
    manifest = read_json(guard.member(declaration, manifest_name, receipt["files"][manifest_name]))
    _require(
        manifest.get("schema_version") == 1
        and manifest.get("semantic_status") == "PASS_SUPPORTED_SUBSET"
        and manifest.get("source_sssom") == "mappings/ingredient_mappings.sssom.tsv"
        and manifest.get("files") == products,
        "KG consumed export manifest differs from the reviewed-release pin",
    )
    for field in ("source_sha256", "review_sha256"):
        _require(
            isinstance(manifest.get(field), str) and re.fullmatch("[a-f0-9]{64}", manifest[field]),
            "KG consumed export lacks its exact source/review pins",
        )
    return receipt["files"][name]["sha256"]


def _kg_source(guard, selection):
    """Recheck the complete frozen KG receipt against its actual selected checkout."""
    current = selection["current_kgm"]
    _keys(current, {"root", "revision"})
    _require(
        isinstance(current["revision"], str) and re.fullmatch("[a-f0-9]{40}", current["revision"]),
        "invalid KG revision",
    )
    guard.kg_root = _root(current["root"])
    guard.kg_revision = current["revision"]
    state = guard.kg_root.stat()
    guard.kg_identity = state.st_dev, state.st_ino
    _require(_kg_head(guard.kg_root) == guard.kg_revision, "current KG revision differs")
    declaration = selection["kgm_source_receipt"]
    receipt = read_json(guard.read(declaration))
    _require(
        receipt.get("schema_version") == 1 and receipt.get("upstream_revision") == guard.kg_revision,
        "KG source receipt revision differs",
    )
    _require(isinstance(receipt.get("files"), dict) and receipt["files"], "KG receipt lacks complete frozen files")
    snapshots = 0
    for name, metadata in receipt["files"].items():
        raw = guard.member(declaration, name, metadata)
        if name.startswith("snapshots/"):
            actual = _path(guard.kg_root, name[len("snapshots/") :])
            _require(guard.snapshots.add(actual, metadata["sha256"]) == raw, "current KG snapshot bytes differ")
            snapshots += 1
    _require(snapshots > 0, "KG receipt has no upstream snapshot closure")
    consumed = receipt.get("consumed_reviewed", {})
    _require(
        isinstance(consumed.get("source_commit"), str) and re.fullmatch("[a-f0-9]{40}", consumed["source_commit"]),
        "KG receipt lacks exact consumed SSSOM commit",
    )
    expected = {
        "manifest.json",
        "ingredient_mappings.sssom.tsv",
        "withheld_mappings.sssom.tsv",
        "mapping-dispositions.tsv",
    }
    _require(
        isinstance(consumed.get("files"), dict) and set(consumed["files"]) == expected,
        "KG consumed SSSOM partitions incomplete",
    )
    for name, digest in consumed["files"].items():
        member = (Path(consumed["directory"]) / name).as_posix()
        _require(
            member in receipt["files"] and receipt["files"][member]["sha256"] == digest, "KG consumed SSSOM pin differs"
        )
    _require(consumed["manifest_sha256"] == consumed["files"]["manifest.json"], "KG consumed SSSOM manifest differs")
    release_pin = _consumed_release(guard, declaration, receipt, consumed)
    return {
        "reviewed_release_record_sha256": release_pin,
        "revision": guard.kg_revision,
        "frozen_files": len(receipt["files"]),
        "current_snapshot_files": snapshots,
        "consumed_reviewed": consumed,
    }


def _culturemech(guard, selection):
    """Bind the separate accepted intake, its partitions and complete occurrence rows."""
    selected = selection["culturemech"]
    _keys(selected, {"source_manifest", "prepared_intake", "reviewed_intake", "binding_review"})
    source = read_json(guard.read(selected["source_manifest"]))
    intake = read_json(guard.read(selected["prepared_intake"]))
    reviewed = read_json(guard.read(selected["reviewed_intake"]))
    binding_review = read_json(guard.read(selected["binding_review"]))
    _require(source.get("contract") == "culturemech-direct-ingredients-v3", "selected CultureMech contract differs")
    _require(
        intake.get("source_contract") == source["contract"] and reviewed.get("source_contract") == source["contract"],
        "intake source contract differs",
    )
    _require(
        intake.get("schema_version") == 1
        and reviewed.get("schema_version") == 1
        and binding_review.get("schema_version") == 1,
        "unsupported intake schema",
    )
    _require(reviewed.get("status") == "REVIEWED_SOURCE_INTAKE", "selected intake is not reviewed")
    _require(
        intake.get("source_manifest_sha256")
        == selected["source_manifest"]["sha256"]
        == reviewed.get("source_manifest_sha256"),
        "selected CM source pin differs",
    )
    _require(
        reviewed.get("intake_sha256") == selected["prepared_intake"]["sha256"] == binding_review.get("intake_sha256"),
        "prepared intake selection differs",
    )
    _require(reviewed.get("review_sha256") == selected["binding_review"]["sha256"], "selected binding review differs")
    _require(reviewed.get("canonical_sssom") == intake.get("canonical_sssom"), "CM canonical SSSOM snapshot differs")
    source_counts = source["counts"]
    expected = selection["expected_counts"]
    _require(
        source_counts["occurrences"] == intake["counts"]["source_occurrences"] == expected["positive_inventory"],
        "positive inventory count differs",
    )
    _require(
        source_counts["variant_context_only_mentions"]
        == intake["counts"]["context_only_mentions"]
        == expected["context_only"],
        "context count differs",
    )
    _require(
        source_counts["variant_held_mentions"] == intake["counts"]["held_source_mentions"] == expected["held"],
        "held count differs",
    )
    # Require both complete native partitions and the disposition table; these
    # bindings are independent of any later source-identity decision.
    bindings = {}
    for filename, status, count_key in (
        ("supported-bindings.tsv", "SUPPORTED", "supported_bindings"),
        ("withheld-bindings.tsv", "WITHHOLD", "withheld_bindings"),
    ):
        rows = list(_rows(guard.member(selected["reviewed_intake"], filename, reviewed["files"][filename])))
        _require(len(rows) == expected[count_key] == reviewed["counts"][status], "binding partition count differs")
        for row in rows:
            _require(
                row["disposition"] == status and row["case_id"] not in bindings, "duplicate or misplaced binding case"
            )
            bindings[row["case_id"]] = row
    dispositions = list(
        _rows(
            guard.member(
                selected["reviewed_intake"], "binding-dispositions.tsv", reviewed["files"]["binding-dispositions.tsv"]
            )
        )
    )
    _require(
        Counter(_digest(row) for row in dispositions) == Counter(_digest(row) for row in bindings.values()),
        "binding partition is not lossless",
    )
    decisions = binding_review.get("decisions")
    _require(isinstance(decisions, list) and len(decisions) == len(bindings), "binding review case coverage differs")
    seen = set()
    for decision in decisions:
        key = decision.get("case_id")
        _require(key in bindings and key not in seen, "binding review case differs")
        seen.add(key)
        row = bindings[key]
        _require(
            decision.get("disposition") == row["disposition"] and decision.get("row_sha256") == row["payload_sha256"],
            "binding scientific decision differs",
        )
        for field in ("owner_record", "review_reason", "review_evidence", "evidence_key"):
            _require(decision.get(field) == row[field], "binding evidence differs")
        _require(
            decision.get("canonical_row_sha256", "") == row["canonical_row_sha256"],
            "binding canonical identity differs",
        )
        _require(
            bool(row["canonical_row_sha256"]) == (row["disposition"] == "SUPPORTED"),
            "binding canonical partition differs",
        )
    canonical = reviewed["canonical_sssom"]
    canonical_names = {"ingredient_mappings.sssom.tsv", "withheld_mappings.sssom.tsv", "mapping-dispositions.tsv"}
    _require(
        isinstance(canonical.get("files"), dict) and set(canonical["files"]) == canonical_names,
        "CM canonical partitions incomplete",
    )
    for name in canonical_names | {"manifest.json"}:
        relative = "canonical-reviewed-sssom/" + name
        _require(relative in reviewed["files"], "CM canonical member missing")
        metadata = reviewed["files"][relative]
        raw = guard.member(selected["reviewed_intake"], relative, metadata)
        if name == "manifest.json":
            _require(read_json(raw) == canonical, "CM canonical manifest differs")
        else:
            _require(metadata["sha256"] == canonical["files"][name], "CM canonical product differs")
    mentions = {}
    counts = Counter()
    for name, held in (("source-mentions.tsv", False), ("source-held-mentions.tsv", True)):
        raw = guard.member(selected["prepared_intake"], name, intake["files"][name])
        for row in _rows(raw):
            _require(row.get("counts_as_presence") in {"true", "false"}, "invalid inventory flag")
            lane = "held" if held else "positive_inventory" if row["counts_as_presence"] == "true" else "context_only"
            if held:
                _require(
                    row.get("review_status") == "WITHHELD" and row["counts_as_presence"] == "false",
                    "held source assertion promoted",
                )
            if row.get("change_action") == "REMOVE" or row.get("descriptor_role") == "replaced_ingredient":
                _require(lane == "context_only", "removed or displaced descriptor promoted")
            key = (row["source_product"], row["source_row"])
            _require(key not in mentions and row["case_id"] in bindings, "duplicate or unreviewed source occurrence")
            mentions[key] = (lane, row)
            counts[lane] += 1
    _require(
        dict(counts) == {key: expected[key] for key in LANES if expected[key]},
        "complete CM occurrence coverage differs",
    )
    per_case = Counter((row["case_id"], lane) for lane, row in mentions.values())
    for key, row in bindings.items():
        for lane, field in (
            ("positive_inventory", "positive_occurrences"),
            ("context_only", "context_only_mentions"),
            ("held", "held_source_mentions"),
        ):
            _require(str(per_case[key, lane]) == row[field], "binding occurrence count differs")
    return mentions, bindings, dict(counts)


def _reconcile(guard, selection, payload, mentions, bindings):
    """Match complete original rows to actual selected native occurrence positions."""
    native = {}
    for decision in payload["source_decisions"]:
        claim = decision["payload"]
        for occurrence in claim["occurrences"]:
            key = (claim["source_id"], str(occurrence["position"]))
            _require(key not in native, "duplicate native occurrence coordinate")
            native[key] = (decision, occurrence["row"])
    column = selection["native_occurrence_payload_column"]
    _require(
        isinstance(column, str) and column.strip() == column and column, "explicit native CM payload column required"
    )
    raw = guard.read(selection["reconciliation"])
    reader = csv.DictReader(io.StringIO(raw.decode(), newline=""), delimiter="\t")
    _require(reader.fieldnames == list(LEDGER_FIELDS), "reconciliation columns differ")
    seen, used_native = set(), set()
    for row in reader:
        _require(None not in row and all(value is not None for value in row.values()), "malformed reconciliation row")
        key = (row["source_product"], row["source_row"])
        _require(key in mentions and key not in seen, "reconciliation occurrence missing or duplicate")
        seen.add(key)
        lane, original = mentions[key]
        _require(
            row["lane"] == lane and row["row_sha256"] == _digest(original) and row["case_id"] == original["case_id"],
            "reconciliation source context differs",
        )
        target = (row["native_source_id"], row["native_occurrence_position"])
        _require(target in native and target not in used_native, "native occurrence missing or reused")
        used_native.add(target)
        decision, native_row = native[target]
        _require(
            column in native_row and read_json(native_row[column].encode()) == original,
            "native occurrence loses complete CM context",
        )
        binding = bindings[row["case_id"]]
        _require(
            decision["disposition"] == binding["disposition"],
            "CM binding disposition changed without reviewed reconciliation",
        )
        if binding["disposition"] == "SUPPORTED":
            _require(
                decision["payload"].get("owner_record") == binding["owner_record"]
                and decision["payload"].get("owner_record_sha256") == binding["owner_record_sha256"],
                "CM owner transition requires separately reviewed reconciliation",
            )
    _require(seen == set(mentions), "reconciliation omits CM source occurrences")
    _require(
        {key for key, (_, row) in native.items() if row.get(column) not in (None, "")} == used_native,
        "unreconciled native CM occurrence cannot be counted as another source",
    )
    return {"reconciled_cm_occurrences": len(seen), "other_native_occurrences": len(native) - len(used_native)}


def verify_integration(candidate, selection_path, *, selection_sha256):
    """Verify complete selected input accounting, retaining only diagnostic authority."""
    candidate.verify_current()
    payload = candidate.payload()
    _require(
        payload["status"] == STATUS and payload["production_authorized"] is False,
        "integration requires an admitted private candidate",
    )
    guard = _IntegrationGuard(candidate, selection_path, selection_sha256)
    selection = guard.selection
    _keys(
        selection,
        {
            "contract",
            "mode",
            "culturemech",
            "kgm_source_receipt",
            "current_kgm",
            "reconciliation",
            "expected_counts",
            "native_occurrence_payload_column",
        },
    )
    _require(
        selection["contract"] == CONTRACT and selection["mode"] == "diagnostic_only",
        "unsupported integration selection",
    )
    _keys(selection["expected_counts"], COUNT_FIELDS)
    _require(
        all(type(value) is int and value >= 0 for value in selection["expected_counts"].values()),
        "invalid selected integration counts",
    )
    require_cm_replay(payload["provenance"]["source_manifest"], selection)
    kg = _kg_source(guard, selection)
    mentions, bindings, counts = _culturemech(guard, selection)
    accounting = _reconcile(guard, selection, payload, mentions, bindings)
    # The existing projector's exact assertion envelopes remain the graph gate.
    # Its only active relations are SKOS identities/mappings; all other lanes
    # are information. Inventory flags cannot authorize a medium-presence edge.
    _, edges = candidate.graph_rows()
    _require(
        all(edge[PREDICATE_COLUMN] in PREDICATES | {RELATED_TO_PREDICATE} for edge in edges),
        "integration graph contains non-mapping biological assertions",
    )
    guard.verify()
    candidate.verify_current()
    if not hasattr(candidate, "_integration_current_checks"):
        candidate._integration_current_checks = []
    candidate._integration_current_checks.append(guard)
    return {
        "contract": CONTRACT,
        "status": STATUS,
        "production_authorized": False,
        "integration_selection_sha256": selection_sha256,
        "source_manifest_sha256": payload["manifest_sha256"],
        "counts": counts,
        "binding_counts": {
            key: selection["expected_counts"][key] for key in ("supported_bindings", "withheld_bindings")
        },
        "kgm_source": kg,
        **accounting,
        "medium_presence_authorized": False,
        "limitations": [
            "Read-only input and graph reconciliation, not a new scientific review, "
            "source production, final artifact canary or release admission",
            "CM baseline disposition or owner transitions require a separately reviewed reconciliation contract",
            "Integration verification is not persisted; a reloaded candidate must repeat the explicit check",
        ],
    }
