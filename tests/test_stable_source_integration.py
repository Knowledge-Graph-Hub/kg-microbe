"""Hermetic controls for diagnostic reconciliation, never native-science approval."""

import csv
import hashlib
import io
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.stable_source_integration import CONTRACT, LEDGER_FIELDS, _digest, verify_integration
from kg_microbe.utils.stable_source_native_bridge import CM_REPLAY_CAPABILITY, SOURCE_CAPABILITY


def _json(path, value):
    """Write an explicitly synthetic contract input and return its digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(value) + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _tsv(rows, fields=None):
    """Retain complete synthetic TSV row values with ordinary CSV quoting."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


class _AdmittedFixture:
    """Stand in only for the already tested native constructor in unit controls."""

    def __init__(self, root, payload):
        """Keep mutable synthetic controls separate from real upstream outputs."""
        self.root, self._payload = root, payload
        self.edges = [{"predicate": "skos:exactMatch"}, {"predicate": "biolink:related_to"}]
        self._integration_current_checks = []

    def verify_current(self):
        """Exercise the actual installed integration guards after first admission."""
        for guard in self._integration_current_checks:
            guard.verify()

    def payload(self):
        """Mirror currentness enforcement without claiming a native fixture run."""
        self.verify_current()
        return deepcopy(self._payload)

    def graph_rows(self):
        """Provide only mapping/information rows unless a test injects biology."""
        return [], deepcopy(self.edges)


@pytest.fixture
def integration(tmp_path):
    """Build small independent input lanes with a real Git checkout currentness pin."""
    root, kg = tmp_path / "mim", tmp_path / "kg"
    root.mkdir()
    kg.mkdir()
    subprocess.run(["git", "init", "-q", str(kg)], check=True)  # noqa: S603,S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(kg),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        check=True,
    )  # noqa: S603,S607
    revision = subprocess.check_output(["git", "-C", str(kg), "rev-parse", "HEAD"], text=True).strip()  # noqa: S603,S607
    inputs = {}

    def write(name, raw):
        """Register exact fixture bytes in the synthetic native input closure."""
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        inputs[name] = digest
        return {"bytes": len(raw), "sha256": digest}

    def document(name, value):
        """Write one JSON document selected by its exact independent hash."""
        metadata = write(name, canonical_json(value) + b"\n")
        return {"path": name, "sha256": metadata["sha256"]}

    base = {
        "recipe_id": "CultureMech:1",
        "counts_as_presence": "true",
        "source_product": "ingredient_occurrences.tsv",
        "source_row": "1",
        "case_id": "a",
        "change_action": "",
        "descriptor_role": "",
        "concentration_value": "0",
        "source_text": "Literal qualifier\n# retained line",
        "change_stage": "base",
    }
    context = dict(
        base,
        source_product="variant_ingredient_changes.tsv",
        case_id="b",
        change_action="REMOVE",
        counts_as_presence="false",
        change_stage="separate stage",
    )
    held = dict(
        base,
        source_product="variant_ingredient_holds.tsv",
        case_id="c",
        counts_as_presence="false",
        review_status="WITHHELD",
        change_action="",
        held_fields_json='["QUANTITY"]',
    )
    mentions = [base, context, held]
    bindings, decisions = [], []
    for row, status in zip(mentions, ("SUPPORTED", "WITHHOLD", "SUPPORTED"), strict=True):
        key = row["case_id"]
        binding = {
            "case_id": key,
            "payload_sha256": _digest({"case": key}),
            "disposition": status,
            "owner_record": "data/ingredients/mapped/owner.yaml",
            "owner_record_sha256": "c" * 64,
            "positive_occurrences": str(key == "a" and 1 or 0),
            "context_only_mentions": str(key == "b" and 1 or 0),
            "held_source_mentions": str(key == "c" and 1 or 0),
            "review_reason": "synthetic decision",
            "review_evidence": "review.json",
            "evidence_key": key,
            "canonical_row_sha256": "e" * 64 if status == "SUPPORTED" else "",
        }
        bindings.append(binding)
        decisions.append(
            {
                k: binding[k]
                for k in (
                    "case_id",
                    "disposition",
                    "owner_record",
                    "review_reason",
                    "review_evidence",
                    "evidence_key",
                    "canonical_row_sha256",
                )
            }
            | {"row_sha256": binding["payload_sha256"]}
        )
    prepared_files = {
        "source-mentions.tsv": write("prepared/source-mentions.tsv", _tsv([base, context])),
        "source-held-mentions.tsv": write("prepared/source-held-mentions.tsv", _tsv([held])),
    }
    canonical = {"schema_version": 1, "files": {}}
    canonical_metadata = {}
    for name in ("ingredient_mappings.sssom.tsv", "withheld_mappings.sssom.tsv", "mapping-dispositions.tsv"):
        metadata = write("reviewed/canonical-reviewed-sssom/" + name, ("synthetic " + name).encode())
        canonical["files"][name] = metadata["sha256"]
        canonical_metadata["canonical-reviewed-sssom/" + name] = metadata
    canonical_metadata["canonical-reviewed-sssom/manifest.json"] = write(
        "reviewed/canonical-reviewed-sssom/manifest.json", canonical_json(canonical) + b"\n"
    )
    source = document(
        "source/manifest.json",
        {
            "contract": "culturemech-direct-ingredients-v3",
            "counts": {"occurrences": 1, "variant_context_only_mentions": 1, "variant_held_mentions": 1},
        },
    )
    prepared = document(
        "prepared/intake.json",
        {
            "schema_version": 1,
            "source_contract": "culturemech-direct-ingredients-v3",
            "source_manifest_sha256": source["sha256"],
            "counts": {"source_occurrences": 1, "context_only_mentions": 1, "held_source_mentions": 1},
            "files": prepared_files,
            "canonical_sssom": canonical,
        },
    )
    review = document("review.json", {"schema_version": 1, "intake_sha256": prepared["sha256"], "decisions": decisions})
    reviewed_files = dict(canonical_metadata)
    for name, rows in (
        ("supported-bindings.tsv", [bindings[0], bindings[2]]),
        ("withheld-bindings.tsv", [bindings[1]]),
        ("binding-dispositions.tsv", bindings),
    ):
        reviewed_files[name] = write("reviewed/" + name, _tsv(rows))
    reviewed = document(
        "reviewed/reviewed-intake.json",
        {
            "schema_version": 1,
            "status": "REVIEWED_SOURCE_INTAKE",
            "source_contract": "culturemech-direct-ingredients-v3",
            "source_manifest_sha256": source["sha256"],
            "intake_sha256": prepared["sha256"],
            "review_sha256": review["sha256"],
            "counts": {"SUPPORTED": 2, "WITHHOLD": 1},
            "canonical_sssom": canonical,
            "files": reviewed_files,
        },
    )
    kg_files = {}

    def kg_snapshot(name, raw):
        """Freeze the same immutable fixture bytes as actual current checkout files."""
        relative = "snapshots/" + name
        kg_files[relative] = write("kg-source/" + relative, raw)
        actual = kg / name
        actual.parent.mkdir(parents=True, exist_ok=True)
        actual.write_bytes(raw)
        return kg_files[relative]["sha256"]

    kg_products = {}
    for name in (
        "ingredient_mappings.sssom.tsv",
        "withheld_mappings.sssom.tsv",
        "mapping-dispositions.tsv",
    ):
        kg_products[name] = kg_snapshot("export/" + name, ("synthetic " + name).encode())
    kg_manifest = {
        "schema_version": 1,
        "semantic_status": "PASS_SUPPORTED_SUBSET",
        "source_sssom": "mappings/ingredient_mappings.sssom.tsv",
        "source_sha256": "a" * 64,
        "review_sha256": "b" * 64,
        "files": kg_products,
    }
    kg_manifest_pin = kg_snapshot("export/manifest.json", canonical_json(kg_manifest) + b"\n")
    release = {
        "schema_version": 2,
        "origin": "immutable_commit_export",
        "source_commit": "d" * 40,
        "source_archive": {
            "url": "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + "d" * 40,
            "sha256": "c" * 64,
        },
        "export_recipe": {
            "id": "reviewed_sssom_v1",
            "python_version": "3.13",
            "lock_sha256": "e" * 64,
            "workflow_sha256": "f" * 64,
        },
        "validation_run_url": "https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/123",
        "manifest_sha256": kg_manifest_pin,
        "files": kg_products,
        "mode": "candidate_only",
    }
    kg_snapshot("mappings/mim_reviewed_release.json", canonical_json(release) + b"\n")
    subprocess.run(  # noqa: S603
        ["git", "-C", str(kg), "add", "mappings/mim_reviewed_release.json"],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(kg),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture.invalid",
            "commit",
            "-qm",
            "pin synthetic reviewed release",
        ],
        check=True,
    )
    revision = subprocess.check_output(["git", "-C", str(kg), "rev-parse", "HEAD"], text=True).strip()  # noqa: S603,S607
    kg_files["queue.json"] = write("kg-source/queue.json", b"{}\n")
    kg_receipt = document(
        "kg-source/source-manifest.json",
        {
            "schema_version": 1,
            "upstream_revision": revision,
            "files": kg_files,
            "consumed_reviewed": {
                "source_commit": "d" * 40,
                "directory": "snapshots/export",
                "manifest_sha256": kg_files["snapshots/export/manifest.json"]["sha256"],
                "files": {
                    Path(name).name: metadata["sha256"]
                    for name, metadata in kg_files.items()
                    if name.startswith("snapshots/export/")
                },
            },
        },
    )
    native, ledger = [], []
    for position, row in enumerate(mentions, 1):
        source_id = "SOURCE:" + row["case_id"]
        lane = ("positive_inventory", "context_only", "held")[position - 1]
        native.append(
            {
                "disposition": bindings[position - 1]["disposition"],
                "payload": {
                    "source_id": source_id,
                    "owner_record": bindings[position - 1]["owner_record"],
                    "owner_record_sha256": bindings[position - 1]["owner_record_sha256"],
                    "occurrences": [{"position": position, "row": {"cm_original_json": canonical_json(row).decode()}}],
                },
            }
        )
        ledger.append(
            {
                "lane": lane,
                "source_product": row["source_product"],
                "source_row": row["source_row"],
                "row_sha256": _digest(row),
                "case_id": row["case_id"],
                "native_source_id": source_id,
                "native_occurrence_position": str(position),
            }
        )
    reconciliation_meta = write("reconciliation.tsv", _tsv(ledger, LEDGER_FIELDS))
    selection = {
        "contract": CONTRACT,
        "mode": "diagnostic_only",
        "culturemech": {
            "source_manifest": source,
            "prepared_intake": prepared,
            "reviewed_intake": reviewed,
            "binding_review": review,
        },
        "kgm_source_receipt": kg_receipt,
        "current_kgm": {"root": str(kg), "revision": revision},
        "reconciliation": {"path": "reconciliation.tsv", "sha256": reconciliation_meta["sha256"]},
        "expected_counts": {
            "positive_inventory": 1,
            "context_only": 1,
            "held": 1,
            "supported_bindings": 2,
            "withheld_bindings": 1,
        },
        "native_occurrence_payload_column": "cm_original_json",
    }
    candidate = _AdmittedFixture(
        root,
        {
            "status": "PRIVATE_NOT_KG_ACCEPTED",
            "production_authorized": False,
            "manifest_sha256": "f" * 64,
            "source_decisions": native,
            "provenance": {
                "source_manifest": {
                    "inputs": inputs,
                    "required_capabilities": [SOURCE_CAPABILITY, CM_REPLAY_CAPABILITY],
                    "culturemech_intake_replay": {
                        **deepcopy(selection["culturemech"]),
                        "counts": deepcopy(selection["expected_counts"]),
                    },
                },
            },
        },
    )
    path = tmp_path / "integration.json"
    pin = _json(path, selection)
    return {
        "candidate": candidate,
        "selection": selection,
        "path": path,
        "pin": pin,
        "root": root,
        "kg": kg,
        "write": write,
        "document": document,
        "ledger": ledger,
        "mentions": mentions,
        "kg_snapshot": kg_snapshot,
        "kg_files": kg_files,
        "kg_release": release,
        "kg_manifest": kg_manifest,
    }


def _run(fixture):
    """Invoke the actual diagnostic verifier with independently selected fixture bytes."""
    return verify_integration(fixture["candidate"], fixture["path"], selection_sha256=fixture["pin"])


def _reselect(fixture):
    """Explicitly re-pin a mutated fixture selection without changing native admission."""
    fixture["pin"] = _json(fixture["path"], fixture["selection"])


def test_complete_diagnostic_keeps_inventory_distinct_from_presence(integration):
    """Zero inventory, removed context and held identity all remain evidence only."""
    result = _run(integration)
    assert result["counts"] == {"positive_inventory": 1, "context_only": 1, "held": 1}
    assert result["binding_counts"] == {"supported_bindings": 2, "withheld_bindings": 1}
    assert result["medium_presence_authorized"] is False
    assert result["production_authorized"] is False
    assert result["status"] == "PRIVATE_NOT_KG_ACCEPTED"
    assert result["kgm_source"]["frozen_files"] == 6
    assert result["kgm_source"]["current_snapshot_files"] == 5
    assert result["reconciled_cm_occurrences"] == 3
    assert len(integration["candidate"]._integration_current_checks) == 1


@pytest.mark.parametrize(
    "member",
    [
        "prepared/intake.json",
        "reviewed/reviewed-intake.json",
        "review.json",
        "source/manifest.json",
        "reconciliation.tsv",
        "kg-source/queue.json",
        "prepared/source-held-mentions.tsv",
    ],
)
def test_every_evidence_lane_must_be_native_consumed(integration, member):
    """A selected hash cannot manufacture native consumption of an omitted input."""
    integration["candidate"]._payload["provenance"]["source_manifest"]["inputs"].pop(member)
    with pytest.raises(ValueError, match="not a selected native input|CM replay input closure differs"):
        _run(integration)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "wrong_lane", "wrong_hash", "wrong_case", "wrong_position", "reuse_native"]
)
def test_complete_reconciliation_refuses_mutations(integration, change):
    """Rehashed ledgers must still account for every exact row and native position."""
    rows = deepcopy(integration["ledger"])
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows.append(rows[0])
    elif change == "wrong_lane":
        rows[1]["lane"] = "positive_inventory"
    elif change == "wrong_hash":
        rows[1]["row_sha256"] = "a" * 64
    elif change == "wrong_case":
        rows[1]["case_id"] = "a"
    elif change == "wrong_position":
        rows[1]["native_occurrence_position"] = "99"
    else:
        rows[1]["native_source_id"] = rows[0]["native_source_id"]
        rows[1]["native_occurrence_position"] = rows[0]["native_occurrence_position"]
    metadata = integration["write"]("reconciliation.tsv", _tsv(rows, LEDGER_FIELDS))
    integration["selection"]["reconciliation"]["sha256"] = metadata["sha256"]
    _reselect(integration)
    with pytest.raises(ValueError, match="reconciliation|native occurrence"):
        _run(integration)


@pytest.mark.parametrize("change", ["context", "disposition", "owner_path", "owner_hash"])
def test_native_binding_cannot_silently_change_accepted_context(integration, change):
    """Native source support alone is not proof of unchanged CM ownership or context."""
    native = integration["candidate"]._payload["source_decisions"]
    if change == "context":
        native[0]["payload"]["occurrences"][0]["row"]["cm_original_json"] = "{}"
    elif change == "disposition":
        native[1]["disposition"] = "SUPPORTED"
    else:
        native[0]["payload"]["owner_record" if change == "owner_path" else "owner_record_sha256"] = "changed"
    with pytest.raises(ValueError, match="CM context|CM binding disposition|CM owner transition"):
        _run(integration)


@pytest.mark.parametrize("change", ["before", "after", "missing", "head"])
def test_actual_current_kg_checkout_is_required_and_kept_live(integration, change):
    """Matching a frozen receipt alone cannot certify a different live KG source."""
    path = integration["kg"] / "export/ingredient_mappings.sssom.tsv"
    if change == "after":
        _run(integration)
        path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="input pin differs|input changed"):
            integration["candidate"].payload()
        return
    if change == "head":
        integration["selection"]["current_kgm"]["revision"] = "1" * 40
        _reselect(integration)
    elif change == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed")
    with pytest.raises((ValueError, FileNotFoundError), match="revision differs|input pin differs|No such file"):
        _run(integration)


def test_same_content_replacement_remains_a_late_change(integration):
    """Physical replacement after diagnostic completion is not hidden by equal hashes."""
    _run(integration)
    path = integration["kg"] / "export/ingredient_mappings.sssom.tsv"
    other = path.with_suffix(".new")
    other.write_bytes(path.read_bytes())
    other.replace(path)
    with pytest.raises(ValueError, match="input changed between reads"):
        integration["candidate"].payload()


@pytest.mark.parametrize(
    "predicate", ["biolink:has_part", "biolink:subclass_of", "biolink:produces", "biolink:located_in"]
)
def test_mapping_integration_never_authorizes_biological_edges(integration, predicate):
    """Inventory or identity cannot be promoted into medium or biological assertions."""
    integration["candidate"].edges.append({"predicate": predicate})
    with pytest.raises(ValueError, match="non-mapping biological assertions"):
        _run(integration)


def test_selected_counts_are_independent_checks(integration):
    """A new selection cannot hide incomplete source-lane accounting."""
    integration["selection"]["expected_counts"]["held"] = 0
    _reselect(integration)
    with pytest.raises(ValueError, match="held count differs|CM replay counts differ"):
        _run(integration)


def test_unknown_selection_fields_and_mode_refuse(integration):
    """No extra flag may grant publication or silently expand the contract."""
    integration["selection"]["production_authorized"] = True
    _reselect(integration)
    with pytest.raises(ValueError, match="unexpected selection fields"):
        _run(integration)


def test_integration_does_not_replace_native_candidate_status(integration):
    """Require the admitted candidate-only interface before reconciliation."""
    integration["candidate"]._payload["production_authorized"] = True
    with pytest.raises(ValueError, match="admitted private candidate"):
        _run(integration)


@pytest.mark.parametrize("kind", ["duplicate", "altered", "unlisted_case"])
def test_extra_cm_native_occurrences_never_count_as_other_sources(integration, kind):
    """Every nonempty selected CM payload belongs to the exact reconciliation closure."""
    decisions = integration["candidate"]._payload["source_decisions"]
    extra = deepcopy(decisions[0])
    extra["payload"]["source_id"] = "SOURCE:extra"
    extra["payload"]["occurrences"][0]["position"] = 99
    if kind == "altered":
        extra["payload"]["occurrences"][0]["row"]["cm_original_json"] = "{}"
    elif kind == "unlisted_case":
        row = deepcopy(integration["mentions"][0])
        row["case_id"] = "not-reviewed"
        extra["payload"]["occurrences"][0]["row"]["cm_original_json"] = canonical_json(row).decode()
    decisions.append(extra)
    with pytest.raises(ValueError, match="unreconciled native CM occurrence"):
        _run(integration)


@pytest.mark.parametrize("row", [{"other_source": "KG"}, {"cm_original_json": "", "other_source": "KG"}])
def test_genuine_other_source_occurrences_are_separate(integration, row):
    """Ordinary KG occurrences have no selected CM payload and remain separately counted."""
    integration["candidate"]._payload["source_decisions"].append(
        {"disposition": "WITHHOLD", "payload": {"source_id": "KG:other", "occurrences": [{"position": 99, "row": row}]}}
    )
    assert _run(integration)["other_native_occurrences"] == 1


def test_nested_noncheckout_cannot_inherit_matching_parent_revision(integration):
    """A matching ancestor commit and copied scientific bytes do not make a checkout root."""
    nested = integration["kg"] / "nested"
    shutil.copytree(integration["kg"] / "export", nested / "export")
    integration["selection"]["current_kgm"]["root"] = str(nested)
    _reselect(integration)
    with pytest.raises(ValueError, match="physical Git top-level"):
        _run(integration)


def test_actual_linked_worktree_is_a_valid_selected_root(integration, tmp_path):
    """Require genuine linked-worktree ownership without insisting on a .git directory."""
    linked = tmp_path / "linked-kg"
    subprocess.run(  # noqa: S603,S607 - private fixture worktree
        ["git", "-C", str(integration["kg"]), "worktree", "add", "--detach", str(linked), "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    shutil.copytree(integration["kg"] / "export", linked / "export")
    integration["selection"]["current_kgm"]["root"] = str(linked)
    _reselect(integration)
    assert _run(integration)["kgm_source"]["current_snapshot_files"] == 5


def test_late_checkout_root_substitution_is_refused(integration, tmp_path):
    """A different directory cannot replace the selected physical KG checkout after admission."""
    _run(integration)
    old = integration["kg"]
    moved = tmp_path / "moved-kg"
    old.rename(moved)
    shutil.copytree(moved, old)
    with pytest.raises(ValueError, match="root identity changed"):
        integration["candidate"].payload()


@pytest.mark.parametrize(
    "change", ["missing_record", "wrong_commit", "wrong_pin", "wrong_manifest", "wrong_archive", "coherent_commit"]
)
def test_consumed_sssom_claim_requires_actual_reviewed_release_record(integration, change):
    """Consistent frozen copies cannot invent the reviewed release's source commit or pins."""
    receipt = json.loads((integration["root"] / "kg-source/source-manifest.json").read_text())
    release = deepcopy(integration["kg_release"])
    if change == "missing_record":
        receipt["files"].pop("snapshots/mappings/mim_reviewed_release.json")
    elif change == "wrong_commit":
        receipt["consumed_reviewed"]["source_commit"] = "0" * 40
    elif change == "wrong_pin":
        release["files"]["ingredient_mappings.sssom.tsv"] = "0" * 64
    elif change == "wrong_archive":
        release["source_archive"]["url"] += "-unreviewed"
    elif change == "coherent_commit":
        receipt["consumed_reviewed"]["source_commit"] = "0" * 40
        release["source_commit"] = "0" * 40
        release["source_archive"]["url"] = (
            "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + "0" * 40
        )
    else:
        manifest = deepcopy(integration["kg_manifest"])
        manifest["files"]["ingredient_mappings.sssom.tsv"] = "0" * 64
        pin = integration["kg_snapshot"]("export/manifest.json", canonical_json(manifest) + b"\n")
        receipt["files"]["snapshots/export/manifest.json"] = integration["kg_files"]["snapshots/export/manifest.json"]
        receipt["consumed_reviewed"]["files"]["manifest.json"] = pin
        receipt["consumed_reviewed"]["manifest_sha256"] = pin
        release["manifest_sha256"] = pin
    if change in {"wrong_pin", "wrong_archive", "wrong_manifest", "coherent_commit"}:
        integration["kg_snapshot"]("mappings/mim_reviewed_release.json", canonical_json(release) + b"\n")
        receipt["files"]["snapshots/mappings/mim_reviewed_release.json"] = integration["kg_files"][
            "snapshots/mappings/mim_reviewed_release.json"
        ]
    integration["selection"]["kgm_source_receipt"] = integration["document"]("kg-source/source-manifest.json", receipt)
    _reselect(integration)
    with pytest.raises(ValueError, match="reviewed-release|export manifest"):
        _run(integration)


def test_current_release_record_remains_live_after_reconciliation(integration):
    """A later current pin change invalidates the diagnostic despite a stable frozen copy."""
    _run(integration)
    (integration["kg"] / "mappings/mim_reviewed_release.json").write_text("{}\n")
    with pytest.raises(ValueError, match="input changed|input pin differs"):
        integration["candidate"].payload()
