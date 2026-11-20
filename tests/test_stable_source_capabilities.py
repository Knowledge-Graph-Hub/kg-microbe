"""Closed consumer capability negotiation; mocks do not certify upstream replay."""

from copy import deepcopy

import pytest

from kg_microbe.utils.stable_source_native_bridge import (
    CM_REPLAY_CAPABILITY,
    CM_REPLAY_COUNTS,
    CM_REPLAY_INPUTS,
    SOURCE_CAPABILITIES,
    SOURCE_CAPABILITY,
    require_cm_replay,
    source_capabilities,
)


def replay_manifest():
    """Build only a synthetic proof envelope for boundary/refusal controls."""
    declarations = {key: {"path": key + ".json", "sha256": "a" * 64} for key in CM_REPLAY_INPUTS}
    return {
        "required_capabilities": sorted(SOURCE_CAPABILITIES),
        "inputs": {value["path"]: value["sha256"] for value in declarations.values()},
        "culturemech_intake_replay": {**declarations, "counts": dict.fromkeys(CM_REPLAY_COUNTS, 0)},
    }


def test_explicit_source_capabilities():
    """Ordinary native candidates remain valid without claiming integration replay."""
    assert source_capabilities({"required_capabilities": [SOURCE_CAPABILITY]}) == {SOURCE_CAPABILITY}
    assert source_capabilities(replay_manifest()) == SOURCE_CAPABILITIES


@pytest.mark.parametrize(
    "required",
    [None, [], [True], [SOURCE_CAPABILITY] * 2, [CM_REPLAY_CAPABILITY], [SOURCE_CAPABILITY, "future/v1"]],
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
