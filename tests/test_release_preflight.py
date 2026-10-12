"""Every byte-pinned upstream release is checked before a long run starts (#1420)."""

import gzip
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
    """Every pinned file has one digest, and download.yaml fetches each release from its release URL."""
    pins = release_preflight.reviewed_release_pins()
    assert set(pins) == {
        "biolink-model.yaml",
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
    # The Biolink model is pinned by its tag; tests/test_biolink_schema_pin.py checks that URL.
    assert set(pins) - {"biolink-model.yaml"} <= set(REVIEWED_RELEASE_URLS)


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


def _only(pins):
    """Stand in for the policies: these pins, and no derived file pins."""
    return lambda repo_root=None, *, policies=None: pins if policies is None else {}


def test_ontologies_preflight_fails_before_any_source_runs(tmp_path, monkeypatch):
    """The ontologies source reports a stale release through the batch's prerequisite check."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>"})
    (tmp_path / "ro.owl").write_bytes(b"<ro>rewritten in place</ro>")
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite"))
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    (problem,) = OntologiesTransform.missing_prerequisites(tmp_path)
    assert problem.startswith("ro.owl in ") and "is not the reviewed release" in problem
    assert dispatcher._missing_prerequisites(["ontologies"], tmp_path) == [f"ontologies: {problem}"]


def test_a_single_ontology_gets_the_ontologies_check_once(tmp_path, monkeypatch):
    """`kg transform -s go` runs under the ontologies source, so it is checked the same way (#1528)."""
    pins = _pins(tmp_path, {"go.owl": b"<go/>"})
    (tmp_path / "go.owl").unlink()
    (tmp_path / "ncit.db").write_bytes(b"sqlite")
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    (problem,) = dispatcher._missing_prerequisites(["go"], tmp_path)
    assert problem.startswith("go: go.owl is missing")
    assert dispatcher._missing_prerequisites(["go", "uberon"], tmp_path) == [problem]
    assert dispatcher._missing_prerequisites(["ontologies", "go"], tmp_path) == [
        problem.replace("go: ", "ontologies: ", 1)
    ]


@pytest.mark.parametrize("state", ["absent", "matching", "stale"])
def test_an_existing_derived_file_must_be_the_pinned_conversion(tmp_path, monkeypatch, state):
    """A stale upa.json is reported up front; a missing one is derived by the run (#1527)."""
    payload = b'{"graphs": []}'
    derived = {"upa.json": {hashlib.sha256(payload).hexdigest(): ["mappings/fixture_policy.json"]}}
    monkeypatch.setattr(
        release_preflight,
        "reviewed_release_pins",
        lambda repo_root=None, *, policies=None: derived if policies is release_preflight.DERIVED_PINS else {},
    )
    if state != "absent":
        (tmp_path / "upa.json").write_bytes(payload if state == "matching" else payload + b" ")
    problems = release_preflight.stale_derived_files(tmp_path)
    if state == "stale":
        (problem,) = problems
        assert problem.startswith("upa.json in ") and "Move it aside" in problem
    else:
        assert problems == []


@pytest.mark.parametrize("present", [(), ("ncit.db",), ("ncit.db.gz",)])
def test_the_ncit_authority_or_its_archive_must_be_present(tmp_path, present):
    """FOODON's NCIT ids need ncit.db when the ontologies source finalizes (#1526)."""
    for name in present:
        (tmp_path / name).write_bytes(b"x")
    problems = release_preflight.missing_ncit_authority(tmp_path)
    if present:
        assert problems == []
    else:
        (problem,) = problems
        assert "ncit.db" in problem and "`kg download -t stubs`" in problem


def test_check_only_entry_point_reports_without_running(tmp_path, monkeypatch, capsys):
    """`python -m kg_microbe.utils.release_preflight RAW_DIR` checks without starting a run (#1533)."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>"})
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    assert release_preflight.main([str(tmp_path)]) == 1
    assert "ncit.db" in capsys.readouterr().out
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite"))
    assert release_preflight.main([str(tmp_path)]) == 0
    assert "is ready" in capsys.readouterr().out
