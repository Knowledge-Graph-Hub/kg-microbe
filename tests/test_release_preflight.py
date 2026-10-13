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


def test_a_single_ontology_is_checked_for_the_files_its_run_reads(tmp_path, monkeypatch):
    """`-s go` checks go.owl, not mondo.json; `-s ec` reads no pinned file (#1528, #1534)."""
    pins = _pins(tmp_path, {"go.owl": b"<go/>", "mondo.json": b"{}"})
    (tmp_path / "go.owl").unlink()
    (tmp_path / "mondo.json").write_bytes(b'{"rewritten": true}')
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    assert dispatcher._missing_prerequisites(["ec"], tmp_path) == []
    (problem,) = dispatcher._missing_prerequisites(["go"], tmp_path)
    assert problem.startswith("go: go.owl is missing")
    (problem,) = dispatcher._missing_prerequisites(["mondo"], tmp_path)
    assert problem.startswith("mondo: mondo.json in ")
    # go.owl is read by the go, pato and upa runs; it is reported once, under the first.
    problems = dispatcher._missing_prerequisites(["go", "pato", "upa"], tmp_path)
    assert [problem.split(":", 1)[0] for problem in problems if "go.owl" in problem] == ["go"]
    # With the whole ontologies source selected, its full check runs once and covers them.
    problems = dispatcher._missing_prerequisites(["ontologies", "go"], tmp_path)
    assert {problem.split(":", 1)[0] for problem in problems} == {"ontologies"}
    assert any("go.owl is missing" in problem for problem in problems)
    assert any("mondo.json in " in problem for problem in problems)


def test_every_checked_file_belongs_to_a_single_ontology_or_the_whole_run():
    """A new pin must be mapped to the single ontologies that read it, or the whole run (#1534)."""
    pinned = set(release_preflight.reviewed_release_pins())
    derived = set(release_preflight.reviewed_release_pins(policies=release_preflight.DERIVED_PINS))
    mapped = set().union(*release_preflight.SINGLE_ONTOLOGY_INPUTS.values())
    assert pinned | derived <= mapped | release_preflight.WHOLE_RUN_ONLY
    assert mapped - {"ncit.db"} <= pinned | derived
    assert set(release_preflight.SINGLE_ONTOLOGY_INPUTS) <= set(dispatcher._ontology_map())


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


@pytest.mark.parametrize(
    "layout", ["neither", "database", "archive", "stale_database", "truncated", "stale_truncated", "outside"]
)
def test_ncit_must_be_readable_or_soundly_unpackable_inside_the_raw_directory(tmp_path, layout):
    """The run reads ncit.db, unpacking a missing or stale one; the preflight checks it can (#1526, #1535)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    payload = b"sqlite database bytes"
    archive = gzip.compress(payload)
    if layout in {"database", "stale_database", "stale_truncated"}:
        (raw / "ncit.db").write_bytes(payload if layout == "database" else payload + b" older")
    if layout in {"archive", "stale_database", "database"}:
        (raw / "ncit.db.gz").write_bytes(archive)
    if layout in {"truncated", "stale_truncated"}:
        (raw / "ncit.db.gz").write_bytes(archive[:-12] + archive[-4:])
    if layout == "outside":
        (tmp_path / "ncit.db.gz").write_bytes(archive)
        (raw / "ncit.db.gz").symlink_to(tmp_path / "ncit.db.gz")
    problems = release_preflight.ncit_authority_problems(raw)
    if layout in {"database", "archive", "stale_database"}:
        assert problems == []
    else:
        (problem,) = problems
        expected = {
            "neither": "`kg download -t stubs`",
            "truncated": "cannot be unpacked",
            "stale_truncated": "cannot be unpacked",
            "outside": "resolves outside",
        }[layout]
        assert expected in problem


def test_check_only_entry_point_reports_without_running(tmp_path, monkeypatch, capsys):
    """`python -m kg_microbe.utils.release_preflight RAW_DIR` checks without starting a run (#1533)."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>"})
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    assert release_preflight.main([str(tmp_path)]) == 1
    assert "ncit.db" in capsys.readouterr().out
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite"))
    assert release_preflight.main([str(tmp_path)]) == 0
    assert "is ready" in capsys.readouterr().out
