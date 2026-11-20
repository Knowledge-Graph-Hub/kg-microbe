"""Test offline streaming source diagnostics extracted from unmapped-enzymes."""

import csv
import importlib.util
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/report_bacdive_missing_ec.py"
SPEC = importlib.util.spec_from_file_location("report_bacdive_missing_ec", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)
FIXTURE = Path(__file__).parent / "resources/bacdive_missing_ec/records.json"


def table(path):
    """Read a small diagnostic TSV from a test-owned directory."""
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def test_fixture_report_preserves_source_and_counts(tmp_path):
    """Keep missing annotation, malformed type, identity and activity distinctions."""
    before = FIXTURE.read_bytes()
    out = tmp_path / "report"
    summary = REPORT.write_report(FIXTURE, out)
    assert FIXTURE.read_bytes() == before
    assert summary["counts"] == {
        "source_records": 5,
        "enzyme_observations": 10,
        "affected_source_records": 3,
        "absent": 2,
        "null": 2,
        "blank": 1,
        "invalid_type": 4,
        "present": 1,
    }
    assert summary["distinct_reported_bacdive_ids"] == 1
    rows = table(out / "observations.tsv")
    assert len(rows) == 9
    assert rows[0]["bacdive_id"] == "7"
    assert json.loads(rows[0]["enzyme_json"])["activity"] == "negative"
    assert json.loads(rows[0]["enzyme_json"])["@ref"] == 19
    assert json.loads(rows[0]["source_path_json"]) == ["Physiology and metabolism", "enzymes", 0]
    assert json.loads(rows[0]["classification_json"])["strain designation"] == "test\tstrain\nalpha"
    assert json.loads(rows[-2]["source_path_json"]) == ["Physiology and metabolism", "enzymes"]
    assert rows[-1]["bacdive_id"] == ""
    assert "α" in json.loads(rows[-1]["enzyme_json"])["value"]
    assert json.loads(rows[6]["enzyme_json"], parse_float=Decimal)["fraction"] == Decimal(
        "0.12345678901234567890123456789"
    )
    assert table(out / "labels.tsv")[0] == {
        "enzyme_label_json": '{"value":"enzyme alpha"}',
        "ec_status": "absent",
        "observations": "2",
    }
    assert summary["source"]["sha256"] == REPORT.source_hash(FIXTURE)
    assert set(p.name for p in out.iterdir()) == {"observations.tsv", "labels.tsv", "summary.json"}


def test_object_records_and_unvalidated_present_string(tmp_path):
    """Retain arbitrary source keys and do not pretend a supplied string is a valid EC."""
    raw = tmp_path / "records.json"
    raw.write_text('{"weird/key~1":{"Physiology and metabolism":{"enzymes":[{}, {"ec":"not-an-EC"}]}}}')
    out = tmp_path / "report"
    summary = REPORT.write_report(raw, out)
    rows = table(out / "observations.tsv")
    assert rows[0]["source_coordinate_json"] == '"weird/key~1"'
    assert rows[0]["enzyme_label_json"] == "{}"
    assert summary["counts"]["present"] == 1
    assert summary["distinct_reported_bacdive_ids"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"null",
        b"[",
        b"[{}",
        b"[] {}",
        b"[4]",
        b'[{"Physiology and metabolism":[]}]',
        b'[{"Physiology and metabolism":{"enzymes":"enzyme"}}]',
        b'[{"Physiology and metabolism":{"enzymes":[null]}}]',
        b'[{"Physiology and metabolism":{"enzymes":{"ec":null,"ec":"1.2.3.4"}}}]',
        b'{"same":{},"same":{}}',
    ],
)
def test_malformed_input_never_publishes_a_report(tmp_path, payload):
    """Refuse structural data loss and truncated streams; clean only own staging files."""
    raw = tmp_path / "raw.json"
    raw.write_bytes(payload)
    out = tmp_path / "report"
    with pytest.raises(ValueError):
        REPORT.write_report(raw, out)
    assert raw.read_bytes() == payload
    assert not out.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["raw.json"]


@pytest.mark.parametrize("payload", ["[]", "{}", '[{}, {"Physiology and metabolism":null}]'])
def test_empty_or_no_enzyme_records(tmp_path, payload):
    """Valid empty collections produce a report with explicit zero diagnostic counts."""
    raw = tmp_path / "raw.json"
    raw.write_text(payload)
    summary = REPORT.write_report(raw, tmp_path / "report")
    assert summary["counts"]["enzyme_observations"] == 0
    assert table(tmp_path / "report/observations.tsv") == []


def test_no_clobber_and_no_source_overlap(tmp_path):
    """Neither existing reports, files nor symlinks are overwritten."""
    for target in (tmp_path, FIXTURE):
        with pytest.raises(FileExistsError):
            REPORT.write_report(FIXTURE, target)
    out = tmp_path / "report"
    out.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        REPORT.write_report(FIXTURE, out)
    assert out.is_symlink()


def test_source_drift_rejects_report(tmp_path, monkeypatch):
    """Fingerprint disagreement is a failed report, not an accepted mixed snapshot."""
    hashes = iter(["before", "after"])
    monkeypatch.setattr(REPORT, "source_hash", lambda path: next(hashes))
    with pytest.raises(ValueError, match="Source changed"):
        REPORT.write_report(FIXTURE, tmp_path / "report")
    assert list(tmp_path.iterdir()) == []


def test_source_signature_change_rejects_identical_bytes(tmp_path, monkeypatch):
    """Replacing or rewriting the source cannot hide behind a matching final hash."""
    signatures = iter([(1, 2, 3, 4, 5), (1, 2, 3, 6, 7)])
    monkeypatch.setattr(REPORT, "source_signature", lambda path: next(signatures))
    with pytest.raises(ValueError, match="Source changed"):
        REPORT.write_report(FIXTURE, tmp_path / "report")
    assert list(tmp_path.iterdir()) == []


def test_report_does_not_load_whole_json(tmp_path, monkeypatch):
    """The report implementation never uses json.load or json.loads on the input."""

    def forbid_load(*args, **kwargs):
        """Fail an accidental eager JSON conversion."""
        raise AssertionError("Do not eagerly load JSON")

    monkeypatch.setattr(REPORT.json, "load", forbid_load)
    monkeypatch.setattr(REPORT.json, "loads", forbid_load)
    assert REPORT.write_report(FIXTURE, tmp_path / "report")["counts"]["source_records"] == 5


def test_failed_publication_leaves_no_empty_destination(tmp_path, monkeypatch):
    """Remove only this run's reservation if final publication fails."""

    def fail_replace(*args):
        """Simulate a filesystem publication failure."""
        raise OSError("publication failed")

    monkeypatch.setattr(REPORT.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failed"):
        REPORT.write_report(FIXTURE, tmp_path / "report")
    assert list(tmp_path.iterdir()) == []


def test_concurrent_destination_is_not_overwritten(tmp_path, monkeypatch):
    """A report created by another process while parsing belongs to that process."""
    output = tmp_path / "report"
    original = REPORT.iter_records

    def competing_report(stream):
        """Create another report after this run passes its initial existence check."""
        output.mkdir()
        (output / "other.txt").write_text("keep")
        yield from original(stream)

    monkeypatch.setattr(REPORT, "iter_records", competing_report)
    with pytest.raises(FileExistsError):
        REPORT.write_report(FIXTURE, output)
    assert (output / "other.txt").read_text() == "keep"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("replacement", ["empty", "sentinel", "missing", "symlink", "populated_owned"])
def test_changed_reservation_preserves_foreign_path_and_original_error(tmp_path, monkeypatch, replacement):
    """Failed publication must not remove substituted directories or hide its original exception."""
    output = tmp_path / "report"
    original_error = OSError("original publication failure")

    def fail_after_race(staging, destination):
        """Substitute or populate the reservation at the publication boundary."""
        if replacement != "populated_owned":
            destination.rename(tmp_path / "original-reservation")
        if replacement in {"empty", "sentinel"}:
            destination.mkdir()
        if replacement in {"sentinel", "populated_owned"}:
            (destination / "foreign.txt").write_text("keep")
        if replacement == "symlink":
            destination.symlink_to(tmp_path / "foreign-target")
        raise original_error

    monkeypatch.setattr(REPORT.os, "replace", fail_after_race)
    with pytest.raises(OSError) as failure:
        REPORT.write_report(FIXTURE, output)
    assert failure.value is original_error
    if replacement in {"sentinel", "populated_owned"}:
        assert (output / "foreign.txt").read_text() == "keep"
    elif replacement == "empty":
        assert output.is_dir()
    elif replacement == "symlink":
        assert output.is_symlink()
    else:
        assert not output.exists()


def test_changed_reservation_is_checked_before_publication(tmp_path, monkeypatch):
    """A foreign reservation detected before replace must never be used for publication."""
    output, staging = tmp_path / "report", tmp_path / "staging"
    staging.mkdir()
    original_lstat = Path.lstat
    calls = 0

    def raced_lstat(path):
        """Change ownership between reservation capture and the pre-publication check."""
        nonlocal calls
        if path == output:
            calls += 1
            if calls == 2:
                output.rename(tmp_path / "original-reservation")
                output.mkdir()
                (output / "foreign.txt").write_text("keep")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", raced_lstat)
    with pytest.raises(ValueError, match="reservation changed"):
        REPORT.publish_directory(staging, output)
    assert (output / "foreign.txt").read_text() == "keep"
    assert staging.is_dir()


def test_parser_uses_bounded_reads_and_yields_before_eof():
    """A large stream is not eagerly materialized or read with read(-1)."""

    class BoundedStream(io.BytesIO):
        """Record parser read bounds on synthetic large input."""

        def read(self, size=-1):
            """Refuse unbounded reads."""
            assert 0 <= size <= 1024 * 1024
            return super().read(size)

        def readinto(self, buffer):
            """Refuse unbounded parser buffers."""
            assert len(buffer) <= 1024 * 1024
            return super().readinto(buffer)

    payload = b"[" + b"{}," * 100000 + b"{}]"
    stream = BoundedStream(payload)
    records = REPORT.iter_records(stream)
    assert next(records) == (0, {})
    assert stream.tell() < len(payload)


def test_help_without_optional_parser(tmp_path, monkeypatch):
    """Argument help never needs a parser, a source download or ontology adapters."""
    import sys

    monkeypatch.setitem(sys.modules, "ijson", None)
    with pytest.raises(SystemExit) as stopped:
        REPORT.main(["--help"])
    assert stopped.value.code == 0
    assert REPORT.main(["--raw", str(FIXTURE), "--out", str(tmp_path / "report")]) == 1


def test_main_success_and_existing_output_error(tmp_path):
    """The CLI reports completion only after the complete report is published."""
    args = ["--raw", str(FIXTURE), "--out", str(tmp_path / "report")]
    assert REPORT.main(args) == 0
    assert REPORT.main(args) == 1
