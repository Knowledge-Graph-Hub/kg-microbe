"""Retire rejected historical metadata without erasing admissible assertions (#1154)."""

import pytest

from scripts import mim_conservative_refresh as refresh
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _metadata, _node, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs


@pytest.mark.parametrize("native_present", [True, False])
def test_policy_rejected_label_repairs_metadata_not_claim_identity(inputs, native_present):
    """An admitted B1 CAS or alias cannot keep the mixture label after lexical quarantine."""
    baseline = inputs["baseline"]
    target = "CHEBI:8309"
    bad_canonical = _row("kgm.name:polymyxin_b", target, "polymyxin b", name="polymyxin b", comment="canonical_name")
    valid_xref = _row("cas:4135-11-9", target, "polymyxin b")
    valid_alias = _row(
        "kgm.name:polymyxin_b1",
        target,
        "polymyxin b",
        predicate="skos:closeMatch",
        name="Polymyxin B(1)",
        comment="synonym",
    )
    valid_nonidentity = _row("CHEBI:4", target, "polymyxin b", predicate="skos:relatedMatch")
    already_safe = _row("cas:unrelated_valid_fixture", target, "polymyxin B1")
    originals = [valid_xref, valid_alias, valid_nonidentity]
    _table(baseline, FIELDS, [*refresh._rows(baseline), bad_canonical, *originals, already_safe], _metadata())
    if native_present:
        authority = inputs["ontology_paths"][0]
        native_rows = [row for _, row in refresh._native_rows((authority,))]
        _table(authority, NODE_FIELDS, [*native_rows, _node(target, "polymyxin B1", "Polymyxin B(1)|polymyxin b")])
    result = refresh.build_conservative_candidate(**inputs)
    candidate, quarantine = _read(result.candidate_path), _read(result.quarantine_path)
    assert target not in result.report["affected_entities"]
    assert target in result.report["policy_metadata_targets"]
    assert result.report["counts"]["identity_policy_relabelled_rows"] == 3
    counts = result.report["counts"]
    assert counts["preserved_rows"] + counts["quarantined_rows"] == (
        counts["baseline_rows"] + counts["identity_policy_relabelled_rows"]
    )
    assert already_safe in candidate
    assert bad_canonical not in candidate
    assert dict(bad_canonical, quarantine_reason="reviewed_identity_policy_name") in quarantine
    for original in originals:
        assert dict(original, quarantine_reason="reviewed_identity_policy_object_label") in quarantine
        repaired = dict(original, object_label="polymyxin B1" if native_present else "")
        assert repaired in candidate
        assert original not in candidate
    assert not any(refresh._historical_object_label_rejected(row) for row in candidate)
    if native_present:
        assert result.report["native_object_label_repairs"][target] == {
            "label": "polymyxin B1",
            "source": "native_ontology:chebi",
        }
        assert target not in result.report["unreconstructed_object_labels"]
    else:
        assert target in result.report["unreconstructed_object_labels"]
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=result.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert result.candidate_path.read_bytes() == second.candidate_path.read_bytes()


def test_metadata_only_bad_row_restores_native_declaration_without_false_canonical(inputs):
    """Do not rely on a separately rejected canonical lexical row to trigger authority recovery."""
    baseline = inputs["baseline"]
    target = "CHEBI:8309"
    original = _row("cas:4135-11-9", target, "polymyxin b")
    _table(baseline, FIELDS, [*refresh._rows(baseline), original], _metadata())
    authority = inputs["ontology_paths"][0]
    _table(
        authority,
        NODE_FIELDS,
        [
            *[row for _, row in refresh._native_rows((authority,))],
            _node(target, "polymyxin B1", "Polymyxin B(1)|polymyxin b"),
        ],
    )
    result = refresh.build_conservative_candidate(**inputs)
    rows = _read(result.candidate_path)
    assert target not in result.report["affected_entities"]
    assert target not in result.report["policy_pruned_targets"]
    assert target in result.report["policy_metadata_targets"]
    assert dict(original, object_label="polymyxin B1") in rows
    assert any(row["object_id"] == target and row["subject_label"] == "polymyxin B1" for row in rows)
    assert not any(row["object_id"] == target and row["subject_label"].lower() == "polymyxin b" for row in rows)


def test_affected_independent_nonidentity_metadata_keeps_original_in_quarantine(inputs):
    """The normal affected-entity relabel route must retain unsafe original metadata too."""
    baseline = inputs["baseline"]
    target = "CHEBI:8309"
    affected = _row("MIM:Polymyxin_B1", target, "polymyxin B1", source="mediaingredientmech_reviewed")
    original = _row("CHEBI:4", target, "polymyxin b", predicate="skos:broadMatch")
    _table(baseline, FIELDS, [*refresh._rows(baseline), affected, original], _metadata())
    authority = inputs["ontology_paths"][0]
    _table(
        authority, NODE_FIELDS, [*[row for _, row in refresh._native_rows((authority,))], _node(target, "polymyxin B1")]
    )
    result = refresh.build_conservative_candidate(**inputs)
    assert target in result.report["affected_entities"]
    assert dict(original, object_label="polymyxin B1") in _read(result.candidate_path)
    assert dict(original, quarantine_reason="reviewed_identity_policy_object_label") in _read(result.quarantine_path)
    assert result.report["counts"]["identity_policy_relabelled_rows"] == 1
