"""Every byte-pinned upstream release is checked before a long run starts (#1420)."""

import gzip
import hashlib
import json
import os

import pytest

import kg_microbe.transform as dispatcher
from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform
from kg_microbe.utils import release_preflight
from kg_microbe.utils.atomic_io import SQLITE_HEADER
from tests.test_reviewed_release_urls import REVIEWED_RELEASE_URLS

# The start of a SQLite database, as the NCIT check reads it.
_SQLITE = SQLITE_HEADER + b" fixture pages"


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
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(_SQLITE))
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


def test_a_source_named_twice_is_checked_once(tmp_path, monkeypatch):
    """`-s ontologies -s ontologies` runs the check once and reports each problem once (#1548)."""
    calls = []

    def problems(raw_dir, *, repo_root=None, ontology=None):
        """Record each check and report one problem."""
        calls.append(ontology)
        return ["a problem"]

    monkeypatch.setattr(release_preflight, "release_input_problems", problems)
    assert dispatcher._missing_prerequisites(["ontologies", "ontologies"], tmp_path) == ["ontologies: a problem"]
    assert dispatcher._missing_prerequisites(["go", "go"], tmp_path) == ["go: a problem"]
    assert calls == [None, "go"]


def test_ncit_db_checked_by_two_sources_is_reported_once(tmp_path, monkeypatch):
    """The ontologies and ontologies_stubs checks both read ncit.db; a missing one is one problem (#1536)."""
    from kg_microbe.transform_utils.ontologies_stubs import ontologies_stubs_transform as stubs

    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only({}))
    monkeypatch.setattr(stubs, "missing_robot", lambda raw_dir: [])
    monkeypatch.setattr(stubs, "_pinned_import_problems", lambda prefix, cfg, raw_dir: [])
    (problem,) = dispatcher._missing_prerequisites(["ontologies_stubs", "ontologies"], tmp_path)
    assert problem.startswith("ontologies_stubs: Neither ncit.db nor ncit.db.gz")


def test_every_checked_file_is_mapped_to_a_single_ontology_that_reads_it():
    """A new pin must be mapped to the single ontologies that read it (#1534, #1543)."""
    pinned = set(release_preflight.reviewed_release_pins())
    derived = set(release_preflight.reviewed_release_pins(policies=release_preflight.DERIVED_PINS))
    mapped = set().union(*release_preflight.SINGLE_ONTOLOGY_INPUTS.values())
    assert pinned | derived <= mapped
    assert mapped - {"ncit.db"} <= pinned | derived
    assert set(release_preflight.SINGLE_ONTOLOGY_INPUTS) <= set(dispatcher._ontology_map())


def test_every_native_ro_supplier_is_checked_for_ro_owl():
    """Native RO checks ro.owl in each supplier's run, so each is checked for it up front (#1543)."""
    from kg_microbe.utils.native_ro_retention import _SUPPLIERS

    assert sorted(name for name in _SUPPLIERS if "ro.owl" not in release_preflight.SINGLE_ONTOLOGY_INPUTS[name]) == []


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


_ARCHIVE = gzip.compress(_SQLITE)
_TRUNCATED = _ARCHIVE[:-12] + _ARCHIVE[-4:]
_OLDER = _SQLITE + b" an older release"
# The files each layout puts in the raw directory; links are made in the test.
_NCIT_LAYOUTS = {
    "neither": {},
    "database": {"ncit.db": _SQLITE},
    "archive": {"ncit.db.gz": _ARCHIVE},
    "matching_pair": {"ncit.db": _SQLITE, "ncit.db.gz": _ARCHIVE},
    "multi_member_pair": {"ncit.db": _SQLITE, "ncit.db.gz": gzip.compress(_SQLITE[:9]) + gzip.compress(_SQLITE[9:])},
    "dangling_database_link": {"ncit.db.gz": _ARCHIVE},
    "stale_database": {"ncit.db": _OLDER, "ncit.db.gz": _ARCHIVE},
    "database_beside_truncated_archive": {"ncit.db": _OLDER, "ncit.db.gz": _TRUNCATED},
    "database_beside_short_archive": {"ncit.db": _OLDER, "ncit.db.gz": b"\x1f\x8b"},
    "database_beside_empty_archive": {"ncit.db": _OLDER, "ncit.db.gz": gzip.compress(b"")},
    "database_beside_not_sqlite_archive": {"ncit.db": _OLDER, "ncit.db.gz": gzip.compress(b"<html>error</html>")},
    "not_sqlite_database": {"ncit.db": b"not a database"},
    "truncated_archive": {"ncit.db.gz": _TRUNCATED},
    "empty_archive": {"ncit.db.gz": gzip.compress(b"")},
    "zero_byte_archive": {"ncit.db.gz": b""},
    "not_sqlite_archive": {"ncit.db.gz": gzip.compress(b"plain text")},
    "outside": {},
    "loop": {},
}


@pytest.mark.parametrize(
    "layout, expected",
    [
        ("neither", "`kg download -t stubs`"),
        ("database", None),
        ("archive", None),
        ("matching_pair", None),
        # The trailer records only the last member's size, so a mismatch is confirmed by unpacking.
        ("multi_member_pair", None),
        # The run replaces the link with the unpacked file.
        ("dangling_database_link", None),
        ("stale_database", "is not the copy of the ncit.db.gz beside it"),
        ("database_beside_truncated_archive", "cannot be unpacked"),
        ("database_beside_short_archive", "is not a gzip archive"),
        # Not "delete the database": that would leave no working copy (#1559).
        ("database_beside_empty_archive", "does not unpack to a SQLite database (0 bytes unpacked)"),
        ("database_beside_not_sqlite_archive", "does not unpack to a SQLite database (18 bytes unpacked)"),
        ("not_sqlite_database", "is not a SQLite database"),
        ("truncated_archive", "cannot be unpacked"),
        ("empty_archive", "does not unpack to a SQLite database (0 bytes unpacked)"),
        ("zero_byte_archive", "does not unpack to a SQLite database (0 bytes unpacked)"),
        ("not_sqlite_archive", "does not unpack to a SQLite database (10 bytes unpacked)"),
        ("outside", "resolves outside"),
        ("loop", "cannot be resolved"),
    ],
)
def test_ncit_db_must_be_usable_inside_the_raw_directory(tmp_path, layout, expected):
    """
    The run reads an existing ncit.db as it is, and unpacks a missing one.

    So an existing copy must be a SQLite database and its archive's copy, and an
    archive the run would unpack must unpack to one (#1526, #1535, #1536, #1544, #1550).
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, payload in _NCIT_LAYOUTS[layout].items():
        (raw / name).write_bytes(payload)
    if layout == "dangling_database_link":
        (raw / "ncit.db").symlink_to(raw / "gone.db")
    elif layout == "outside":
        (tmp_path / "ncit.db.gz").write_bytes(_ARCHIVE)
        (raw / "ncit.db.gz").symlink_to(tmp_path / "ncit.db.gz")
    elif layout == "loop":
        (raw / "ncit.db.gz").symlink_to(raw / "loop.gz")
        (raw / "loop.gz").symlink_to(raw / "ncit.db.gz")
    problems = release_preflight.ncit_authority_problems(raw)
    if expected is None:
        assert problems == []
    else:
        (problem,) = problems
        assert expected in problem
    if layout.startswith("database_beside_"):
        assert "move it aside to keep the database" in problem
        assert "delete it" not in problem


def test_a_replaced_archive_is_read_again_even_with_its_size_and_mtime_kept(tmp_path):
    """A same-size damaged copy whose modification time was preserved is not served from the cache (#1560)."""
    archive = tmp_path / "ncit.db.gz"
    archive.write_bytes(_ARCHIVE)
    assert release_preflight.ncit_authority_problems(tmp_path) == []
    status = archive.stat()
    damaged = bytearray(_ARCHIVE)
    damaged[12] ^= 0xFF
    replacement = tmp_path / "replacement.gz"
    replacement.write_bytes(bytes(damaged))
    os.utime(replacement, ns=(status.st_atime_ns, status.st_mtime_ns))
    os.replace(replacement, archive)
    assert (archive.stat().st_size, archive.stat().st_mtime_ns) == (status.st_size, status.st_mtime_ns)
    (problem,) = release_preflight.ncit_authority_problems(tmp_path)
    assert "cannot be unpacked" in problem


def test_mediadive_is_checked_for_ncit_db(tmp_path):
    """MediaDive's nodes include reviewed NCIT classes, so the NCIT policy reads ncit.db when it finalizes (#1557)."""
    (tmp_path / "ncit.db").write_bytes(_OLDER)
    (tmp_path / "ncit.db.gz").write_bytes(_ARCHIVE)
    (problem,) = dispatcher._missing_prerequisites(["mediadive"], tmp_path)
    assert problem.startswith("mediadive: ") and "is not the copy of the ncit.db.gz beside it" in problem


def test_check_only_entry_point_reports_without_running(tmp_path, monkeypatch, capsys):
    """`python -m kg_microbe.utils.release_preflight RAW_DIR` checks without starting a run (#1533)."""
    pins = _pins(tmp_path, {"ro.owl": b"<ro/>"})
    monkeypatch.setattr(release_preflight, "reviewed_release_pins", _only(pins))
    assert release_preflight.main([str(tmp_path)]) == 1
    assert "ncit.db" in capsys.readouterr().out
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(_SQLITE))
    assert release_preflight.main([str(tmp_path)]) == 0
    assert "is ready" in capsys.readouterr().out
