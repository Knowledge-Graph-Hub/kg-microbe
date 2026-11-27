"""Synthetic boundary controls; these never certify native reconstruction or release."""

import csv
import hashlib
import io
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe.utils.ingredient_bundle_contract import canonical_json
from kg_microbe.utils.stable_source_conservation import (
    ARTIFACT_ROLES,
    AUTHORITY_ROLES,
    CM_CARRIER,
    CM_CONTRACT,
    CM_PREFIX,
    verify_conservation,
)
from kg_microbe.utils.stable_source_integration import LEDGER_FIELDS, _digest, _IntegrationGuard, _reconcile
from kg_microbe.utils.stable_source_native_bridge import CONSERVATION_CAPABILITY, SOURCE_CAPABILITIES


def _sha(raw):
    """Hash actual unit-fixture bytes."""
    return hashlib.sha256(raw).hexdigest()


def _tsv(rows, fields):
    """Encode complete synthetic source cells with ordinary quoted TSV rules."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _fixture(tmp_path, *, owner_change=None):
    """
    Build real file guards around explicitly synthetic already-admitted payloads.

    Upstream reconstruction is deliberately not mocked as successful execution.
    The caller supplies the metadata that the separate KG-source check returns.
    Native positive/replay tests live in the required-native fixture controls.
    """
    root = tmp_path / "native-inputs"
    root.mkdir()
    inputs = {}

    def write(name, value):
        """Replace a private fixture member and update its manifest byte pin."""
        raw = value if isinstance(value, bytes) else canonical_json(value)
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        inputs[name] = _sha(raw)
        return {"path": name, "sha256": inputs[name]}

    def metadata(name):
        """Retain exact member sizes as well as digests."""
        return {"bytes": (root / name).stat().st_size, "sha256": inputs[name]}

    counts = {
        "positive_inventory": 1,
        "context_only": 0,
        "held": 0,
        "supported_bindings": 1,
        "withheld_bindings": 1,
    }
    cm = {
        name: write("cm/" + name + ".json", {"synthetic_kind": name})
        for name in ("source_manifest", "prepared_intake", "reviewed_intake", "binding_review")
    }
    write("cm/held.tsv", b"status\nWITHHOLD\n")
    cm_members = {Path(ref["path"]).name: metadata(ref["path"]) for ref in cm.values()}
    cm_members["held.tsv"] = metadata("cm/held.tsv")
    package = write("cm/package.json", {"files": cm_members})
    pin = write("kg/snapshots/mappings/mim_reviewed_release.json", {"source_commit": "c" * 40})
    write("kg/snapshots/data/transformed/synthetic/edges.tsv", b"subject\tpredicate\tobject\nKG:1\tP:1\tO:1\n")
    kg_members = {name.removeprefix("kg/"): metadata(name) for name in inputs if name.startswith("kg/snapshots/")}
    receipt = write("kg/source-manifest.json", {"files": kg_members})
    authorities = {
        role: write("authority/" + role + ".json", {"synthetic_role": role})
        for role in sorted(AUTHORITY_ROLES - {"culturemech_package", "kg_source_manifest", "kg_source_selection"})
    }
    authorities.update(culturemech_package=package, kg_source_manifest=receipt)
    current = {"root": str(tmp_path / "selected-kg"), "revision": "f" * 40}
    Path(current["root"]).mkdir()
    kg = {"consumed_reviewed": {"source_commit": "c" * 40}, "reviewed_release_record_sha256": pin["sha256"]}
    owner = {
        "selected_kgm": deepcopy(current),
        "consumed_prior_mim": {
            "source_commit": kg["consumed_reviewed"]["source_commit"],
            "committed_pin_record": {"sha256": pin["sha256"]},
        },
        "intended_accepted_cm_v3": {
            "expected_counts": deepcopy(counts),
            "selected": {
                name: {"path": "/historical/" + name + ".json", **metadata(ref["path"])} for name, ref in cm.items()
            },
            "transport_package": {"path": "/historical/package.json", **metadata(package["path"])},
        },
        "kg_transport_manifest_sha256": authorities["kg_transport_manifest"]["sha256"],
        "row_counts": {"kg_source_ids": 1, "kg_occurrences": 2},
    }
    if owner_change is not None:
        owner_change(owner)
    authorities["kg_source_selection"] = write("authority/kg_source_selection.json", owner)
    artifacts = {
        role: "artifacts/" + role + (".tsv" if "nodes" in role or "occurrences" in role else ".json")
        for role in sorted(ARTIFACT_ROLES)
    }
    for role, name in artifacts.items():
        write(name, {"synthetic_artifact": role})
    scope = {"profile": CONSERVATION_CAPABILITY, "authorities": authorities, "artifacts": artifacts}
    document = {"original_source_scope": deepcopy(scope), "synthetic_unit_declaration": True}
    raw_declaration = canonical_json(document)
    declaration = write("projection-declaration.json", raw_declaration)
    cm_ids = {CM_PREFIX + "positive", CM_PREFIX + "zero"}
    nodes = [
        {
            "source_id": CM_PREFIX + suffix,
            "source_label": suffix,
            "projection_contract": CM_CONTRACT,
            "original_case_id": "cm-" + suffix,
            "projection_declaration_json": raw_declaration.decode(),
            "projection_declaration_path": declaration["path"],
            "projection_declaration_sha256": declaration["sha256"],
        }
        for suffix in ("positive", "zero")
    ]
    nodes.append(
        {
            "source_id": "KG:1",
            "source_label": "opaque KG source",
            "projection_contract": "",
            "original_case_id": "",
            "projection_declaration_json": '{"original_source_scope":{"note":"opaque source data"}}',
            "projection_declaration_path": "unrelated source literal",
            "projection_declaration_sha256": "unrelated source literal",
        }
    )
    mention = {
        "source_product": "source-occurrences.tsv",
        "source_row": "1",
        "case_id": "cm-positive",
        "counts_as_presence": "true",
    }
    occurrences = [
        {"source_id": nodes[0]["source_id"], CM_CARRIER: canonical_json(mention).decode()},
        {"source_id": "KG:1", CM_CARRIER: "opaque KG cell, not a CM carrier"},
        {"source_id": "KG:1", CM_CARRIER: "another opaque cell"},
    ]
    write(artifacts["combined_nodes"], _tsv(nodes, tuple(nodes[0])))
    write(artifacts["combined_occurrences"], _tsv(occurrences, ("source_id", CM_CARRIER)))
    ledger = [
        {
            "lane": "positive_inventory",
            "source_product": mention["source_product"],
            "source_row": mention["source_row"],
            "row_sha256": _digest(mention),
            "case_id": "cm-positive",
            "native_source_id": nodes[0]["source_id"],
            "native_occurrence_position": "1",
        }
    ]
    reconciliation = write(artifacts["cm_reconciliation"], _tsv(ledger, LEDGER_FIELDS))
    source = {
        "nodes": artifacts["combined_nodes"],
        "nodes_sha256": inputs[artifacts["combined_nodes"]],
        "occurrences": artifacts["combined_occurrences"],
        "occurrences_sha256": inputs[artifacts["combined_occurrences"]],
        "id_column": "source_id",
        "label_column": "source_label",
        "occurrence_id_column": "source_id",
        "curie_map": {
            "MIM": "https://example.invalid/mim/",
            "MIMCMREFv1": "https://example.invalid/cm/",
            "KG": "https://example.invalid/kg/",
        },
    }
    owner_ref = write("data/ingredients/mapped/Water.yaml", b"preferred_term: Water\n")
    registry = write("data/ids/mim_id_registry.tsv", b"mim_id\nMIM:0000001\n")
    lifecycle = write("data/ids/mim_id_lifecycle.tsv", b"mim_id\n")
    record_inputs = {owner_ref["path"]: owner_ref["sha256"]}
    ledger_inputs = {ref["path"]: ref["sha256"] for ref in (registry, lifecycle)}
    generic_inputs = {name: digest for name, digest in inputs.items() if name not in record_inputs | ledger_inputs}
    decisions, cases = [], []
    for position, node in enumerate(nodes, 1):
        references = {
            role: {
                "path": "reviews/" + role + "/review.yaml",
                "target_id": "source-" + str(position),
                "assessment_id": "identity-" + str(position),
            }
            for role in ("primary", "skeptic")
        }
        claim = {
            "source_definition": deepcopy(source),
            "source_path": source["nodes"],
            "source_position": position,
            "source_id": node["source_id"],
            "source_row": deepcopy(node),
            "occurrence_path": source["occurrences"],
            "occurrences": [
                {"position": ordinal, "row": deepcopy(row)}
                for ordinal, row in enumerate(occurrences, 1)
                if row["source_id"] == node["source_id"]
            ],
            "owner_record": owner_ref["path"] if position == 1 else None,
            "owner_record_sha256": owner_ref["sha256"] if position == 1 else None,
        }
        decisions.append(
            {
                "payload": claim,
                "payload_sha256": _digest(claim),
                "disposition": "SUPPORTED" if position == 1 else "WITHHOLD",
                **{role: {"reference": deepcopy(reference)} for role, reference in references.items()},
            }
        )
        cases.append({"source_position": position, "owner_record": claim["owner_record"], "holds": [], **references})
    reports = {}
    report_inputs = [
        {"path": name, "sha256": digest, "role": "captured synthetic unit input"}
        for name, digest in sorted(inputs.items())
    ]
    for role in ("primary", "skeptic"):
        name = "reviews/" + role + "/review.yaml"
        reports[role] = name
        ref = write(name, yaml.safe_dump({"source": {"inputs": deepcopy(report_inputs)}}).encode())
        markdown = write(str(Path(name).with_name("review.md")), b"Synthetic unit report; no scientific approval.\n")
        generic_inputs.update({ref["path"]: ref["sha256"], markdown["path"]: markdown["sha256"]})
    review = {
        "source": source,
        "cases": cases,
        "record_inputs": record_inputs,
        "ledger_inputs": ledger_inputs,
        "inputs": generic_inputs,
        "culturemech_intake_replay": deepcopy(package),
    }
    manifest = {
        "required_capabilities": sorted(SOURCE_CAPABILITIES),
        "inputs": inputs,
        "culturemech_intake_replay": {**deepcopy(cm), "counts": deepcopy(counts)},
    }
    payload = {"source_decisions": decisions, "provenance": {"source_manifest": manifest, "source_review": review}}
    candidate = SimpleNamespace(root=root, payload=lambda: deepcopy(payload))
    selection = {
        "culturemech": deepcopy(cm),
        "kgm_source_receipt": deepcopy(receipt),
        "current_kgm": deepcopy(current),
        "reconciliation": reconciliation,
        "expected_counts": deepcopy(counts),
        "native_occurrence_payload_column": CM_CARRIER,
        "combined_source_scope": deepcopy(scope),
        "combined_source_declaration": deepcopy(declaration),
    }
    fixture = SimpleNamespace(
        root=root,
        candidate=candidate,
        payload=payload,
        selection=selection,
        kg=kg,
        inputs=inputs,
        write=write,
        reports=reports,
        cm_ids=cm_ids,
        mention=mention,
        ledger=ledger,
        selection_path=tmp_path / "selection.json",
    )

    def rewrite_report(role, change):
        """Alter a private report and keep its captured outer byte declarations coherent."""
        name = reports[role]
        report = yaml.safe_load((root / name).read_bytes())
        change(report["source"]["inputs"])
        ref = write(name, yaml.safe_dump(report).encode())
        review["inputs"][name] = ref["sha256"]

    fixture.rewrite_report = rewrite_report
    return fixture


def _run(fixture):
    """Invoke the real integration file guards and the pure conservation join only."""
    raw = canonical_json(fixture.selection)
    fixture.selection_path.write_bytes(raw)
    guard = _IntegrationGuard(fixture.candidate, fixture.selection_path, _sha(raw))
    result = verify_conservation(guard, fixture.selection, fixture.payload, fixture.kg)
    guard.verify()
    return result, guard


@pytest.fixture
def combined(tmp_path):
    """Provide a bounded synthetic combined input set with real immutable file reads."""
    return _fixture(tmp_path)


def test_three_field_native_reports_and_complete_profile_join(combined):
    """Required native InputFile.role is retained while every selected input is joined."""
    result, _ = _run(combined)
    assert result["scientific_report_count"] == 2
    assert result["cm_source_ids"] == sorted(combined.cm_ids)
    assert result["kg_source_ids"] == 1
    assert result["kg_occurrences"] == 2
    assert result["selected_input_count"] == len(combined.inputs) - 4
    assert result["production_authorized"] is False
    assert len(combined.selection["combined_source_scope"]["authorities"]) == 13
    assert len(combined.selection["combined_source_scope"]["artifacts"]) == 11


@pytest.mark.parametrize("role", ["primary", "skeptic"])
@pytest.mark.parametrize(
    "change",
    ["missing-role", "blank-role", "numeric-role", "unknown-field", "duplicate", "missing-input", "changed-hash"],
)
def test_each_native_report_requires_real_input_shape_and_complete_union(combined, role, change):
    """Both actual report files must retain native shape and the full selected closure."""

    def alter(rows):
        """Construct one explicit malformed input declaration in a private report."""
        if change == "missing-role":
            del rows[0]["role"]
        elif change == "blank-role":
            rows[0]["role"] = " "
        elif change == "numeric-role":
            rows[0]["role"] = 7
        elif change == "unknown-field":
            rows[0]["approved"] = True
        elif change == "duplicate":
            rows.append(deepcopy(rows[0]))
        elif change == "missing-input":
            rows.pop(0)
        else:
            rows[0]["sha256"] = "0" * 64

    combined.rewrite_report(role, alter)
    with pytest.raises(ValueError, match="selection fields|scientific input|scientific report"):
        _run(combined)


@pytest.mark.parametrize("group", ["authorities", "artifacts"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_fixed_native_profile_roles_cannot_be_relaxed(combined, group, change):
    """Final profile negotiation requires exactly the pinned native role sets."""
    roles = combined.selection["combined_source_scope"][group]
    if change == "missing":
        roles.pop(next(iter(roles)))
    else:
        roles["invented_role"] = deepcopy(next(iter(roles.values())))
    with pytest.raises(ValueError, match="selection fields"):
        _run(combined)


@pytest.mark.parametrize(
    "change", ["authority-pin", "artifact-input", "overlap", "profile", "declaration-newline", "declaration-scope"]
)
def test_independent_selection_and_exact_declaration_are_required(combined, change):
    """Native capability membership does not replace caller-selected bytes and profile."""
    scope = combined.selection["combined_source_scope"]
    if change == "authority-pin":
        scope["authorities"]["kg_transport_manifest"]["sha256"] = "0" * 64
    elif change == "artifact-input":
        combined.inputs.pop(scope["artifacts"]["combined_position_map"])
    elif change == "overlap":
        scope["artifacts"]["cm_nodes"] = scope["artifacts"]["kg_provider_cases"]
    elif change == "profile":
        scope["profile"] = "future-profile/v9"
    else:
        declaration = combined.selection["combined_source_declaration"]
        raw = (combined.root / declaration["path"]).read_bytes()
        if change == "declaration-newline":
            raw += b"\n"
        else:
            raw = canonical_json({"original_source_scope": {**scope, "profile": "future/v9"}})
        declaration.update(combined.write(declaration["path"], raw))
    with pytest.raises(
        ValueError, match="selected native input|unconsumed|overlap|profile|canonical JSON|independent selection"
    ):
        _run(combined)


@pytest.mark.parametrize("member", ["cm/held.tsv", "kg/snapshots/data/transformed/synthetic/edges.tsv"])
def test_complete_package_and_receipt_members_are_consumed(combined, member):
    """Non-authority leaf members cannot disappear from the native input closure."""
    combined.inputs.pop(member)
    with pytest.raises(ValueError, match="not a selected native input"):
        _run(combined)


@pytest.mark.parametrize("change", ["prior-commit", "prior-pin", "root", "revision", "carrier", "cm-hash", "cm-count"])
def test_selected_kg_prior_release_and_cm_bindings_are_exact(combined, change):
    """A valid profile cannot hide a different KG generation, consumed release or CM input."""
    if change == "prior-commit":
        combined.kg["consumed_reviewed"]["source_commit"] = "0" * 40
    elif change == "prior-pin":
        combined.kg["reviewed_release_record_sha256"] = "0" * 64
    elif change in {"root", "revision"}:
        combined.selection["current_kgm"][change] = "another-root" if change == "root" else "0" * 40
    elif change == "carrier":
        combined.selection["native_occurrence_payload_column"] = "cm_occurrence_json"
    elif change == "cm-hash":
        combined.selection["culturemech"]["binding_review"]["sha256"] = "0" * 64
    else:
        combined.selection["expected_counts"]["held"] = 1
    with pytest.raises(ValueError, match="prior consumed|generation|carrier|selected CM replay"):
        _run(combined)


@pytest.mark.parametrize("field", ["kg_source_ids", "kg_occurrences"])
@pytest.mark.parametrize("value", [True, -1, 0, 3])
def test_owner_accounting_must_match_actual_native_cohorts(tmp_path, field, value):
    """Source and occurrence counts remain exact non-boolean joins to native payloads."""
    fixture = _fixture(tmp_path, owner_change=lambda owner: owner["row_counts"].update({field: value}))
    with pytest.raises(ValueError, match="KG source count|KG occurrence count"):
        _run(fixture)


@pytest.mark.parametrize(
    "value", ["not JSON", '{"original_source_scope":{"note":"ordinary data"}}', '{"unrelated":[1,2]}']
)
def test_ordinary_kg_extra_cells_stay_opaque(combined, value):
    """KG literals do not acquire a CM cohort or carrier meaning from column names."""
    row = combined.payload["source_decisions"][2]["payload"]["source_row"]
    row["projection_declaration_json"] = value
    result, _ = _run(combined)
    assert result["kg_occurrences"] == 2
    assert result["cm_source_ids"] == sorted(combined.cm_ids)


@pytest.mark.parametrize("change", ["declaration", "marked-malformed", "source-definition", "duplicate-id"])
def test_actual_native_source_cohort_cannot_disagree_with_selection(combined, change):
    """All marked CM cases, including empty cases, retain the selected declaration."""
    decisions = combined.payload["source_decisions"]
    if change == "declaration":
        decisions[1]["payload"]["source_row"]["projection_declaration_sha256"] = "0" * 64
    elif change == "marked-malformed":
        decisions[1]["payload"]["source_row"]["projection_declaration_json"] = "not JSON"
    elif change == "source-definition":
        decisions[1]["payload"]["occurrence_path"] = "other-occurrences.tsv"
    else:
        decisions[1]["payload"]["source_id"] = decisions[0]["payload"]["source_id"]
    with pytest.raises(ValueError, match="cohort|malformed marked|another source|duplicate combined"):
        _run(combined)


@pytest.mark.parametrize(
    "member",
    [
        "projection-declaration.json",
        "cm/held.tsv",
        "reviews/skeptic/review.yaml",
        "reviews/primary/review.md",
        "data/ingredients/mapped/Water.yaml",
    ],
)
@pytest.mark.parametrize("replacement", [False, True])
def test_every_used_file_remains_live_after_reconciliation(combined, member, replacement):
    """Late content changes and same-byte inode replacements invalidate the real guard."""
    _, guard = _run(combined)
    path = combined.root / member
    if replacement:
        other = path.with_name(path.name + ".replacement")
        other.write_bytes(path.read_bytes())
        other.replace(path)
    else:
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="input changed between reads"):
        guard.verify()


class _Transitions:
    """Record case-check coverage only; this is not a scientific transition reviewer."""

    def __init__(self):
        """Start an isolated test-only list of visited binding cases."""
        self.seen = []

    def check(self, binding, decision):
        """Remember each historical case passed by the integration case pass."""
        self.seen.append((binding["case_id"], decision["payload"]["source_id"]))

    def finish(self):
        """Return only the synthetic count needed to observe invocation coverage."""
        return {"checked_cases": len(self.seen)}


def test_zero_occurrence_cm_cases_still_require_case_reconciliation(combined):
    """Occurrence accounting cannot silently omit a historical case with no rows."""
    _, guard = _run(combined)
    transitions = _Transitions()
    bindings = {"cm-positive": {"case_id": "cm-positive"}, "cm-zero": {"case_id": "cm-zero"}}
    mentions = {
        (combined.mention["source_product"], combined.mention["source_row"]): ("positive_inventory", combined.mention)
    }
    result = _reconcile(
        guard,
        combined.selection,
        combined.payload,
        mentions,
        bindings,
        cm_source_ids=combined.cm_ids,
        transitions=transitions,
    )
    assert result["reconciled_cm_occurrences"] == 1
    assert result["other_native_occurrences"] == 2
    assert transitions.seen == [("cm-positive", CM_PREFIX + "positive"), ("cm-zero", CM_PREFIX + "zero")]


@pytest.mark.parametrize("change", ["missing-empty", "duplicate-case", "foreign-case"])
def test_cm_case_inventory_refuses_missing_or_reassigned_empty_cases(combined, change):
    """All historical cases remain mandatory even when no occurrence would expose loss."""
    _, guard = _run(combined)
    decisions = combined.payload["source_decisions"]
    if change == "missing-empty":
        decisions.pop(1)
    else:
        decisions[1]["payload"]["source_row"]["original_case_id"] = (
            "cm-positive" if change == "duplicate-case" else "foreign"
        )
    bindings = {"cm-positive": {"case_id": "cm-positive"}, "cm-zero": {"case_id": "cm-zero"}}
    mentions = {
        (combined.mention["source_product"], combined.mention["source_row"]): ("positive_inventory", combined.mention)
    }
    with pytest.raises(ValueError, match="historical binding cases|CM case inventory"):
        _reconcile(
            guard,
            combined.selection,
            combined.payload,
            mentions,
            bindings,
            cm_source_ids=combined.cm_ids,
            transitions=_Transitions(),
        )
