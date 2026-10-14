"""The shared finalization-side release binding (#1645)."""

import pytest

from kg_microbe.utils.release_binding import bound_release_snapshot

PIN = "a" * 64
OWN = {"path": "/raw/pato-2026-01-01.json", "sha256": PIN}
SEPARATE = {"path": "/raw/pato-2026-01-01.owl", "sha256": PIN}


def test_the_policy_names_decide_which_snapshot_is_the_release():
    """Recorded paths are resolved, so neither snapshot's name is consulted."""
    assert bound_release_snapshot("pato.json", {"file": "pato.json", "sha256": PIN}, OWN, None) is OWN
    assert bound_release_snapshot("pato.json", {"file": "pato.owl", "sha256": PIN}, OWN, SEPARATE) is SEPARATE


@pytest.mark.parametrize(
    "separate",
    [
        None,
        {"path": "/raw/pato.owl"},
        {"path": "/raw/pato.owl", "sha256": PIN, "extra": 1},
        {"path": None, "sha256": PIN},
        {"path": "/raw/pato.owl", "sha256": "b" * 64},
        "/raw/pato.owl",
    ],
    ids=["missing", "no-digest", "extra-key", "no-path", "other-release", "not-a-record"],
)
def test_a_missing_malformed_or_other_release_is_refused(separate):
    """Only a well-formed record of the pinned bytes binds the release."""
    with pytest.raises(ValueError, match="not bound to its pinned release"):
        bound_release_snapshot("pato.json", {"file": "pato.owl", "sha256": PIN}, OWN, separate)


def test_the_json_as_its_own_release_must_carry_the_pin():
    """When the JSON is the release, its own snapshot is checked against the pin."""
    with pytest.raises(ValueError):
        bound_release_snapshot("pato.json", {"file": "pato.json", "sha256": "b" * 64}, OWN, SEPARATE)
