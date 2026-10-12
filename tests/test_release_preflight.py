"""Every byte-pinned upstream release is checked before a long run starts (#1420)."""

import hashlib
import json

import pytest

import kg_microbe.transform as dispatcher
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import release_preflight
from tests.test_reviewed_release_urls import REVIEWED_RELEASE_URLS


def _pins(directory, files):
    """Write each payload and pin its bytes, as a reviewed policy would."""
    pins = {}
    for name, payload in files.items():
        (directory / name).write_bytes(payload)
        pins[name] = {hashlib.sha256(payload).hexdigest(): ["mappings/fixture_policy.json"]}
    return pins


def test_reviewed_policies_agree_on_one_release_per_file():
    """Every pinned release file has one digest, and download.yaml fetches it from its release URL."""
    pins = release_preflight.reviewed_release_pins()
    assert set(pins) == {
        "envo.json",
        "foodon.owl",
        "go.owl",
        "mondo.json",
        "pato.owl",
        "po.owl",
        "ro.owl",
        "uberon.owl",
        "upa.owl",
    }
    assert all(len(digests) == 1 for digests in pins.values()), pins
    assert set(pins) <= set(REVIEWED_RELEASE_URLS)


def test_matching_release_files_pass(tmp_path):
    """Nothing is reported when every pinned file holds its reviewed bytes."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>", "envo.json": b"{}"})
    assert release_preflight.mismatched_release_files(tmp_path, pins=pins) == []


def test_missing_changed_and_disputed_release_files_are_each_reported(tmp_path):
    """A missing file, a rewritten file and policies that disagree each get their own message."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>", "envo.json": b"{}", "go.owl": b"<go/>"})
    (tmp_path / "ro.owl").unlink()
    (tmp_path / "envo.json").write_bytes(b'{"rewritten": true}')
    pins["go.owl"]["0" * 64] = ["mappings/other_policy.json"]
    problems = release_preflight.mismatched_release_files(tmp_path, pins=pins)
    by_file = {problem.split(" ", 1)[0].rstrip(":"): problem for problem in problems}
    assert set(by_file) == {"ro.owl", "envo.json", "go.owl"}
    assert "is missing" in by_file["ro.owl"] and "`kg download -t ontologies`" in by_file["ro.owl"]
    assert "is not the reviewed release" in by_file["envo.json"]
    assert "Move it aside" in by_file["envo.json"]
    assert "disagree" in by_file["go.owl"] and "mappings/other_policy.json" in by_file["go.owl"]


@pytest.mark.parametrize("damage", ["missing_source", "short_digest", "unsafe_name"])
def test_malformed_policy_pins_are_refused(tmp_path, monkeypatch, damage):
    """A pin that cannot be read is an error, never a file left unchecked."""
    source = {"file": "ro.owl", "sha256": "a" * 64}
    if damage == "short_digest":
        source["sha256"] = "a" * 12
    elif damage == "unsafe_name":
        source["file"] = "../ro.owl"
    authority = {} if damage == "missing_source" else {"source": source}
    (tmp_path / "mappings").mkdir()
    (tmp_path / "mappings/fixture_policy.json").write_text(json.dumps({"authorities": {"ro.json": authority}}))
    monkeypatch.setattr(
        release_preflight,
        "PINNING_POLICIES",
        (("mappings/fixture_policy.json", release_preflight._authority_sources),),
    )
    with pytest.raises(ValueError, match="Cannot read the release pins|Malformed release pin"):
        release_preflight.reviewed_release_pins(tmp_path)


def test_ontologies_preflight_fails_before_any_source_runs(tmp_path, monkeypatch):
    """The ontologies source reports a stale release through the batch's prerequisite check."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>"})
    (tmp_path / "ro.owl").write_bytes(b"<ro>rewritten in place</ro>")
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", lambda repo_root=None: pins)
    (problem,) = OntologiesTransform.missing_prerequisites(tmp_path)
    assert problem.startswith("ro.owl in ") and "is not the reviewed release" in problem
    assert dispatcher._missing_prerequisites(["ontologies"], tmp_path) == [f"ontologies: {problem}"]
