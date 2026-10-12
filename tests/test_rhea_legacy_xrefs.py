"""Finite historical Rhea exclusions remain digest-bound evidence, never graph repairs."""

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.rhea_mappings.legacy_xrefs import (
    AUDIT_HEADER,
    DISPOSITION,
    INPUT_ROLE,
    POLICY_PATH,
    REQUIRED_INPUTS,
    load_legacy_xref_audit,
    read_legacy_policy,
)
from kg_microbe.transform_utils.rhea_mappings.native_rdf import LABEL, RDFS, RH, load_native_rdf
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_consumed_inputs
from tests.rhea_legacy_fixtures import empty_legacy_policy

FIXTURE = Path(__file__).parent / "resources" / "rhea" / "legacy-xref-selected.rdf"


class LegacyAuditFixture(Transform):
    """Exercise genuine immutable reads without historical files or a producer run."""

    REQUIRED_CONSUMED_INPUTS = ("rhea_rdf", *REQUIRED_INPUTS)


def _policy():
    """Read the committed curated evidence without modifying it in a test."""
    with POLICY_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def _prepare(tmp_path):
    """Read immutable fixture RDF through the real snapshot mechanism and pin a test policy."""
    transform = LegacyAuditFixture("rhea_mappings", tmp_path / "raw", tmp_path / "out")
    raw = tmp_path / "fixture.rdf.gz"
    payload = gzip.compress(FIXTURE.read_bytes(), mtime=0)
    raw.write_bytes(payload)
    selected = {
        "snapshot_id": "hermetic-legacy-context",
        "rdf": {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    }
    policy = _policy()
    policy["selected_snapshot"] = selected
    path = tmp_path / "legacy-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    release = {"snapshot_id": selected["snapshot_id"], "files": {"rhea.rdf.gz": dict(selected["rdf"])}}
    with transform.consume_input("rhea_rdf", raw) as stream:
        native = load_native_rdf(stream.buffer, compressed=True)
    return transform, path, release, native, policy


def _run(prepared):
    """Invoke the public helper with its explicitly selected fixture contract."""
    transform, path, release, native, _ = prepared
    return load_legacy_xref_audit(transform, release, native, policy_path=path)


def test_curated_policy_has_six_historical_records_and_seven_variant_annotations():
    """The production policy is finite and self-contained, not dependent on an ignored review report."""
    with POLICY_PATH.open(encoding="utf-8") as stream:
        policy = read_legacy_policy(stream)
    assert len(policy["exclusions"]) == 6
    assert policy["expected_count"] == 6
    assert len(policy["preserved_directional_go_annotations"]) == 7
    assert policy["historical_snapshot"]["rdf"]["sha256"] == (
        "c5ece10984a2f7c4c95c241cde134b108f0dc865335b232bdd77e67e5f074078"
    )
    assert policy["selected_snapshot"]["rdf"]["sha256"] == (
        "8ee48d7044cf3eef1001fa730dae2a491902ab25b259b519d6826796bb8acedf"
    )


def test_exact_six_audits_preserve_original_and_normalized_go_without_graph_mutation(tmp_path):
    """Audit rows expose distinct history stages and cannot create or edit a native graph assertion."""
    prepared = _prepare(tmp_path)
    transform, path, _, native, _ = prepared
    before = copy.deepcopy(native)
    rows = _run(prepared)
    assert native == before
    assert len(rows) == 6
    assert all(set(row) == set(AUDIT_HEADER) for row in rows)
    assert all(all(isinstance(value, str) for value in row.values()) for row in rows)
    assert {row["disposition"] for row in rows} == {DISPOSITION}
    special = next(row for row in rows if row["subject"] == "RHEA:19441")
    assert special["original_object"] == "GO:0018581"
    assert special["legacy_normalized_object"] == "GO:0047074"
    assert special["legacy_line"] == "2020"
    assert json.loads(special["normalization_evidence"])["audit_line"] == 4749
    assert special["policy_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "historical_explanations_not_revalidated" in special["runtime_validation_scope"]
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
    verify_consumed_inputs(transform)
    assert _run(prepared) == rows


@pytest.mark.parametrize(
    "subject,old",
    [
        ("RHEA:15929", "EC:3.5.3.21"),
        ("RHEA:19441", "GO:0018581"),
        ("RHEA:19441", "GO:0047074"),
        ("RHEA:22140", "GO:0008252"),
        ("RHEA:28338", "GO:0008735"),
        ("RHEA:47152", "GO:0004029"),
        ("RHEA:58872", "GO:0102177"),
    ],
)
def test_any_old_original_or_normalized_assertion_reappearing_fails(tmp_path, subject, old):
    """Neither historical originals nor downstream-normalized targets may be silently excluded if present."""
    prepared = _prepare(tmp_path)
    native = prepared[3]
    predicate = RH + "ec" if old.startswith("EC:") else RDFS + "seeAlso"
    value = (
        "http://purl.uniprot.org/enzyme/" + old[3:]
        if old.startswith("EC:")
        else ("http://purl.obolibrary.org/obo/" + old.replace(":", "_"))
    )
    record = native.reactions[subject]
    record[predicate] = (*record.get(predicate, ()), value)
    with pytest.raises(ValueError, match="assertion is present"):
        _run(prepared)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(prepared[0])


@pytest.mark.parametrize("change", ["snapshot", "release_hash", "release_size", "consumed_hash", "missing_read"])
def test_selected_snapshot_is_bound_to_both_release_and_actual_consumption(tmp_path, change):
    """A matching in-memory label dictionary cannot waive a different or absent RDF input read."""
    prepared = _prepare(tmp_path)
    transform, _, release, _, _ = prepared
    if change == "snapshot":
        release["snapshot_id"] += "-other"
    elif change == "release_hash":
        release["files"]["rhea.rdf.gz"]["sha256"] = "0" * 64
    elif change == "release_size":
        release["files"]["rhea.rdf.gz"]["bytes"] += 1
    elif change == "consumed_hash":
        transform._consumed_input_snapshots["rhea_rdf"]["sha256"] = "0" * 64
    else:
        del transform._consumed_input_snapshots["rhea_rdf"]
    with pytest.raises(ValueError, match="consumed selected snapshot"):
        _run(prepared)


@pytest.mark.parametrize("change", ["label", "ambiguous_label", "status", "xref", "related_context"])
def test_required_current_native_context_drift_fails(tmp_path, change):
    """Historical prose cannot substitute for present indexed scientific evidence."""
    prepared = _prepare(tmp_path)
    records = prepared[3].reactions
    if change == "label":
        records["RHEA:15929"][LABEL] = ("different reaction",)
    elif change == "ambiguous_label":
        records["RHEA:15929"][LABEL] += ("different reaction",)
    elif change == "status":
        records["RHEA:15929"][RH + "status"] = (RH + "Preliminary",)
    elif change == "xref":
        records["RHEA:22140"][RDFS + "seeAlso"] = ()
    else:
        del records["RHEA:35595"]
    with pytest.raises(ValueError, match="native Rhea context changed"):
        _run(prepared)


@pytest.mark.parametrize("index", range(7))
def test_every_native_directional_go_annotation_is_preserved_on_exact_subject(tmp_path, index):
    """Moving a native annotation to its master does not satisfy the required variant evidence."""
    prepared = _prepare(tmp_path)
    variant = prepared[4]["preserved_directional_go_annotations"][index]
    native = prepared[3]
    native.reactions[variant["master"]][RDFS + "seeAlso"] = native.reactions[variant["subject"]].pop(RDFS + "seeAlso")
    with pytest.raises(ValueError, match="native Rhea context changed"):
        _run(prepared)


@pytest.mark.parametrize("change", ["swap_policy_direction", "swap_native_sides", "ambiguous_native_sides"])
def test_direction_labels_must_agree_with_exact_native_side_roles(tmp_path, change):
    """Variant membership alone cannot certify a policy that swaps LR and RL scientific meaning."""
    prepared = _prepare(tmp_path)
    variant = prepared[4]["preserved_directional_go_annotations"][0]
    record = prepared[3].reactions[variant["subject"]]
    if change == "swap_policy_direction":
        variant["direction"] = "RL"
        prepared[1].write_text(json.dumps(prepared[4]), encoding="utf-8")
    elif change == "swap_native_sides":
        record[RH + "substrates"], record[RH + "products"] = (RH + "25074_R",), (RH + "25074_L",)
    else:
        record[RH + "substrates"] = (RH + "25074_L", RH + "25074_R")
    with pytest.raises(ValueError, match="direction.*context"):
        _run(prepared)


@pytest.mark.parametrize(
    "change",
    [
        "schema_bool",
        "schema_unknown",
        "root_extra",
        "snapshot_extra",
        "bad_digest",
        "bool_size",
        "missing_row",
        "duplicate_row",
        "unknown_subject",
        "unknown_reason",
        "bad_target",
        "wrong_locator",
        "bool_line",
        "row_extra",
        "missing_normalization",
        "normalization_extra",
        "normalization_bad_predicate",
        "duplicate_assertion",
        "unknown_assertion_predicate",
        "missing_focal_label",
        "missing_variants",
        "duplicate_variant",
        "unknown_variant_direction",
        "variant_extra",
    ],
)
def test_policy_schema_and_finite_evidence_refuse_unknown_or_ambiguous_shapes(change):
    """No optional catch-all policy fields or duplicate evidence can silently broaden an exclusion."""
    policy = _policy()
    row = policy["exclusions"][0]
    if change == "schema_bool":
        policy["schema_version"] = True
    elif change == "schema_unknown":
        policy["schema_version"] = 2
    elif change == "root_extra":
        policy["restore"] = True
    elif change == "snapshot_extra":
        policy["selected_snapshot"]["path"] = "ambient.rdf"
    elif change == "bad_digest":
        policy["historical_snapshot"]["rdf"]["sha256"] = "bad"
    elif change == "bool_size":
        policy["selected_snapshot"]["rdf"]["bytes"] = True
    elif change == "missing_row":
        policy["exclusions"].pop()
    elif change == "duplicate_row":
        policy["exclusions"][1] = row
    elif change == "unknown_subject":
        row["subject"] = "RHEA:1"
    elif change == "unknown_reason":
        row["reason"] = "globally_invalid"
    elif change == "bad_target":
        row["original_object"] = "GO:bad"
    elif change == "wrong_locator":
        row["legacy_locator"] = "../ambient.tsv"
    elif change == "bool_line":
        row["legacy_line"] = True
    elif change == "row_extra":
        row["replacement"] = "EC:1.1.1.1"
    elif change == "missing_normalization":
        policy["exclusions"][1]["normalization_evidence"] = None
    elif change == "normalization_extra":
        policy["exclusions"][1]["normalization_evidence"]["restore"] = True
    elif change == "normalization_bad_predicate":
        policy["exclusions"][1]["normalization_evidence"]["predicate"] = "oboInOwl:consider"
    elif change == "duplicate_assertion":
        row["required_native_assertions"].append(row["required_native_assertions"][0])
    elif change == "unknown_assertion_predicate":
        row["required_native_assertions"][0]["predicate"] = RDFS + "comment"
    elif change == "missing_focal_label":
        row["required_native_assertions"] = [a for a in row["required_native_assertions"] if a["predicate"] != LABEL]
    elif change == "missing_variants":
        policy["preserved_directional_go_annotations"].pop()
    elif change == "duplicate_variant":
        policy["preserved_directional_go_annotations"][1] = policy["preserved_directional_go_annotations"][0]
    elif change == "unknown_variant_direction":
        policy["preserved_directional_go_annotations"][0]["direction"] = "UN"
    else:
        policy["preserved_directional_go_annotations"][0]["rewrite_subject"] = True
    with pytest.raises(ValueError):
        read_legacy_policy(io.StringIO(json.dumps(policy)))


@pytest.mark.parametrize(
    "document",
    [
        '{"schema_version": 0, "schema_version": 1}',
        '{"selected_snapshot": {"snapshot_id": "old", "snapshot_id": "new"}}',
    ],
)
def test_duplicate_json_fields_rejected_before_last_value_wins(document):
    """Nested and top-level duplicate keys are errors regardless of the eventual schema."""
    with pytest.raises(ValueError, match="Duplicate Rhea legacy policy key"):
        read_legacy_policy(io.StringIO(document))


def test_policy_drift_after_audit_cannot_be_finalized(tmp_path):
    """Returned audit evidence retains the actual read hash rather than a later mutable file hash."""
    prepared = _prepare(tmp_path)
    rows = _run(prepared)
    prepared[1].write_text(prepared[1].read_text() + "\n")
    assert rows[0]["policy_sha256"] != hashlib.sha256(prepared[1].read_bytes()).hexdigest()
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        verify_consumed_inputs(prepared[0])


def test_caught_failure_stays_failed_even_after_evidence_is_repaired_in_memory(tmp_path):
    """Only a new producer run may reset failed consumed-input evidence."""
    prepared = _prepare(tmp_path)
    native = prepared[3]
    label = native.reactions["RHEA:15929"].pop(LABEL)
    with pytest.raises(ValueError):
        _run(prepared)
    native.reactions["RHEA:15929"][LABEL] = label
    with pytest.raises(ValueError, match="consumed selected snapshot"):
        _run(prepared)
    with pytest.raises(SourceFinalizationRequired, match="read failed"):
        verify_consumed_inputs(prepared[0])


def test_empty_history_is_truthful_for_an_explicit_different_fixture_snapshot(tmp_path):
    """A synthetic graph can bind a header-only historical audit without inventing six source records."""
    prepared = _prepare(tmp_path)
    policy = empty_legacy_policy(prepared[2])
    prepared[1].write_text(json.dumps(policy), encoding="utf-8")
    assert _run(prepared) == ()
    assert INPUT_ROLE in prepared[0].consumed_input_snapshots
    verify_consumed_inputs(prepared[0])


@pytest.mark.parametrize(
    "change",
    ["production_id", "production_hash", "count_bool", "count_other", "history", "sources", "exclusion", "variant"],
)
def test_empty_history_never_waives_production_identity_or_declared_evidence(tmp_path, change):
    """The empty fixture variant has no path into the reviewed six-record production snapshot."""
    prepared = _prepare(tmp_path)
    policy = empty_legacy_policy(prepared[2])
    production = _policy()
    if change == "production_id":
        policy["selected_snapshot"]["snapshot_id"] = production["selected_snapshot"]["snapshot_id"]
    elif change == "production_hash":
        policy["selected_snapshot"]["rdf"]["sha256"] = production["selected_snapshot"]["rdf"]["sha256"]
    elif change == "count_bool":
        policy["expected_count"] = False
    elif change == "count_other":
        policy["expected_count"] = 5
    elif change == "history":
        policy["historical_snapshot"] = production["historical_snapshot"]
    elif change == "sources":
        policy["legacy_sources"] = production["legacy_sources"]
    elif change == "exclusion":
        policy["exclusions"] = production["exclusions"]
    else:
        policy["preserved_directional_go_annotations"] = production["preserved_directional_go_annotations"]
    with pytest.raises(ValueError):
        read_legacy_policy(io.StringIO(json.dumps(policy)))


def test_no_history_contract_does_not_depend_on_test_prefixes(tmp_path):
    """Explicit reviewed history selection, not a synthetic name convention, defines the contract."""
    prepared = _prepare(tmp_path)
    prepared[2]["snapshot_id"] = "distinct-selected-local-snapshot"
    policy = empty_legacy_policy(prepared[2])
    prepared[1].write_text(json.dumps(policy), encoding="utf-8")
    assert _run(prepared) == ()
