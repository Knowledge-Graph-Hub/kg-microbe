"""Closed consumer capability negotiation; mocks do not certify upstream replay."""

from copy import deepcopy

import pytest

from kg_microbe.utils.stable_source_native_bridge import (
    CM_REPLAY_CAPABILITY,
    CM_REPLAY_COUNTS,
    CM_REPLAY_INPUTS,
    CONSERVATION_CAPABILITY,
    SOURCE_CAPABILITIES,
    SOURCE_CAPABILITY,
    require_cm_replay,
    require_combined_conservation,
    source_capabilities,
)


def replay_manifest(*, combined=False):
    """Build only a synthetic proof envelope for boundary/refusal controls."""
    declarations = {key: {"path": key + ".json", "sha256": "a" * 64} for key in CM_REPLAY_INPUTS}
    capabilities = [SOURCE_CAPABILITY, CM_REPLAY_CAPABILITY]
    if combined:
        capabilities.append(CONSERVATION_CAPABILITY)
    return {
        "required_capabilities": capabilities,
        "inputs": {value["path"]: value["sha256"] for value in declarations.values()},
        "culturemech_intake_replay": {**declarations, "counts": dict.fromkeys(CM_REPLAY_COUNTS, 0)},
    }


def test_explicit_source_capabilities():
    """Ordinary native candidates remain valid without claiming integration replay."""
    assert source_capabilities({"required_capabilities": [SOURCE_CAPABILITY]}) == {SOURCE_CAPABILITY}
    assert source_capabilities(replay_manifest()) == {SOURCE_CAPABILITY, CM_REPLAY_CAPABILITY}
    assert source_capabilities(replay_manifest(combined=True)) == SOURCE_CAPABILITIES


@pytest.mark.parametrize(
    "required",
    [
        None,
        [],
        SOURCE_CAPABILITY,
        (SOURCE_CAPABILITY,),
        [True],
        [SOURCE_CAPABILITY, {}],
        [SOURCE_CAPABILITY] * 2,
        [CM_REPLAY_CAPABILITY],
        [CM_REPLAY_CAPABILITY, CONSERVATION_CAPABILITY],
        [SOURCE_CAPABILITY, "future/v1"],
    ],
)
def test_invalid_source_capabilities(required):
    """A selected producer cannot silently expand the consumer's supported set."""
    with pytest.raises(ValueError, match="capabilit"):
        source_capabilities({"required_capabilities": required})


@pytest.mark.parametrize("kind", ["missing-proof", "missing-capability", "null-proof", "extra-key", "missing-key"])
def test_cm_capability_requires_exact_proof(kind):
    """A marker, boolean or incomplete metadata is not a CM replay proof."""
    value = replay_manifest()
    if kind == "missing-proof":
        del value["culturemech_intake_replay"]
    elif kind == "missing-capability":
        value["required_capabilities"].remove(CM_REPLAY_CAPABILITY)
    elif kind == "null-proof":
        value["culturemech_intake_replay"] = None
    elif kind == "extra-key":
        value["culturemech_intake_replay"]["approved"] = True
    else:
        del value["culturemech_intake_replay"]["source_manifest"]
    with pytest.raises(ValueError, match="CM replay"):
        source_capabilities(value)


@pytest.mark.parametrize("kind", ["absent", "digest", "path", "boolean", "negative", "extra-count"])
def test_cm_proof_requires_closed_inputs_and_counts(kind):
    """Every proof reference is an exact native input; count types remain strict."""
    value = replay_manifest()
    proof = value["culturemech_intake_replay"]
    if kind == "absent":
        del value["inputs"][proof["source_manifest"]["path"]]
    elif kind == "digest":
        proof["source_manifest"]["sha256"] = "b" * 64
    elif kind == "path":
        proof["source_manifest"]["path"] = []
    elif kind == "boolean":
        proof["counts"]["held"] = False
    elif kind == "negative":
        proof["counts"]["held"] = -1
    else:
        proof["counts"]["anything"] = 0
    with pytest.raises(ValueError, match="CM replay"):
        source_capabilities(value)


def test_integration_selection_matches_reconstructed_proof():
    """Exact selection is additional to native replay, never a replacement for it."""
    manifest = replay_manifest()
    proof = manifest["culturemech_intake_replay"]
    selection = {
        "culturemech": {key: deepcopy(proof[key]) for key in CM_REPLAY_INPUTS},
        "expected_counts": deepcopy(proof["counts"]),
    }
    require_cm_replay(manifest, selection)
    for kind in ("source_manifest", "prepared_intake", "reviewed_intake", "binding_review", "count"):
        altered = deepcopy(selection)
        if kind == "count":
            altered["expected_counts"]["held"] += 1
        else:
            altered["culturemech"][kind]["sha256"] = "b" * 64
        with pytest.raises(ValueError, match="selected CM replay"):
            require_cm_replay(manifest, altered)
    with pytest.raises(ValueError, match="upstream integration prerequisite unresolved"):
        require_cm_replay({"required_capabilities": [SOURCE_CAPABILITY]}, selection)


@pytest.mark.parametrize("with_proof", [False, True])
def test_conservation_requires_cm_replay_capability(with_proof):
    """The combined marker cannot bypass CM replay, even with pasted metadata."""
    manifest = replay_manifest(combined=True)
    manifest["required_capabilities"].remove(CM_REPLAY_CAPABILITY)
    if not with_proof:
        del manifest["culturemech_intake_replay"]
    with pytest.raises(ValueError, match="combined conservation requires CM replay capability"):
        source_capabilities(manifest)


@pytest.mark.parametrize("capability", [SOURCE_CAPABILITY, CM_REPLAY_CAPABILITY, CONSERVATION_CAPABILITY, "future/v1"])
def test_combined_capabilities_remain_closed_and_unique(capability):
    """Combined support neither admits an unknown marker nor hides duplicates."""
    manifest = replay_manifest(combined=True)
    manifest["required_capabilities"].append(capability)
    with pytest.raises(ValueError, match="source capabilities"):
        source_capabilities(manifest)


def _selection(manifest):
    """Select exact synthetic CM declarations without asserting native validation."""
    proof = manifest["culturemech_intake_replay"]
    return {
        "culturemech": {name: deepcopy(proof[name]) for name in CM_REPLAY_INPUTS},
        "expected_counts": deepcopy(proof["counts"]),
    }


def test_final_combined_requires_all_three_capabilities():
    """Historical replay remains usable but cannot claim final combined admission."""
    historical = replay_manifest()
    selection = _selection(historical)
    require_cm_replay(historical, selection)
    with pytest.raises(ValueError, match="source conservation capability required for final combined"):
        require_combined_conservation(historical, selection)
    historical["combined_conservation"] = True
    with pytest.raises(ValueError, match="source conservation capability required for final combined"):
        require_combined_conservation(historical, selection)
    combined = replay_manifest(combined=True)
    require_combined_conservation(combined, _selection(combined))


@pytest.mark.parametrize("field", [*sorted(CM_REPLAY_INPUTS), "count"])
def test_final_combined_keeps_exact_cm_selection(field):
    """The third capability does not relax any selected CM evidence binding."""
    manifest = replay_manifest(combined=True)
    selection = _selection(manifest)
    if field == "count":
        selection["expected_counts"]["held"] += 1
    else:
        selection["culturemech"][field]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="selected CM replay"):
        require_combined_conservation(manifest, selection)


@pytest.mark.parametrize("value", [True, False, -1, 0.0, "0", None])
def test_combined_counts_must_be_nonnegative_true_integers(value):
    """Combined replay counts reject booleans, numeric coercion and nulls."""
    manifest = replay_manifest(combined=True)
    manifest["culturemech_intake_replay"]["counts"]["positive_inventory"] = value
    with pytest.raises(ValueError, match="invalid CM replay counts"):
        source_capabilities(manifest)


@pytest.mark.parametrize("change", ["missing-count", "extra-count", "missing-input", "changed-input", "extra-field"])
def test_combined_keeps_closed_replay_inputs_and_counts(change):
    """A valid third marker cannot bless altered replay declarations or closure."""
    manifest = replay_manifest(combined=True)
    proof = manifest["culturemech_intake_replay"]
    if change == "missing-count":
        del proof["counts"]["held"]
    elif change == "extra-count":
        proof["counts"]["new_count"] = 0
    elif change == "missing-input":
        del manifest["inputs"][proof["source_manifest"]["path"]]
    elif change == "changed-input":
        manifest["inputs"][proof["source_manifest"]["path"]] = "b" * 64
    else:
        proof["source_manifest"]["approved"] = True
    with pytest.raises(ValueError, match="CM replay"):
        source_capabilities(manifest)
