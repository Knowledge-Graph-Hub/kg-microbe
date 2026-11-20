"""Test conservative local Rhea-UniProt direction audit without graph promotion."""

import csv
import io
import json
from pathlib import Path

import pytest

from scripts.adhoc import audit_rhea_uniprot_directions as reader

FIXTURE = Path(__file__).parent / "resources/rhea_uniprot_directions"


def policy_for(tmp_path, directions):
    """Write an explicitly synthetic two-file native policy; no RDF admission is claimed."""
    identity = reader.file_identity(directions)
    policy = {
        "schema_version": 2,
        "snapshot_id": "synthetic-fixture",
        "files": {
            "rhea-directions.tsv": {key: identity[key] for key in ("bytes", "sha256")},
            "rhea.rdf.gz": {"bytes": 1, "sha256": "0" * 64},
        },
        "archive": {
            "url": "https://example.org/synthetic.tar.bz2",
            "members": {
                "rhea-directions.tsv": "fixture/rhea-directions.tsv",
                "rhea.rdf.gz": "fixture/rhea.rdf.gz",
            },
        },
    }
    path = tmp_path / "release.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def run_audit(tmp_path, mapping=None, directions=None, policy=None, expected_sha=None, output=None):
    """Select only test-owned snapshots and an explicit mapping byte hash."""
    mapping = mapping or FIXTURE / "mapping.tsv"
    directions = directions or FIXTURE / "directions.tsv"
    policy = policy or policy_for(tmp_path, directions)
    return reader.audit_mapping(
        mapping,
        expected_sha or reader.file_identity(mapping)["sha256"],
        directions,
        policy,
        output or tmp_path / "report",
    )


def test_preserve_directional_subjects_duplicates_and_input_evidence(tmp_path):
    """Every native row survives once; LR/RL/BI never acquire inferred master associations."""
    before = {path: path.read_bytes() for path in FIXTURE.iterdir()}
    manifest = run_audit(tmp_path)
    assert manifest["rows"] == 6
    assert manifest["rows_by_direction"] == {"UN": 1, "LR": 3, "RL": 1, "BI": 1}
    assert manifest["production_admission"] is False
    assert manifest["mapping_release_provenance_verified"] is False
    with (tmp_path / "report/associations.tsv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert [row["rhea_id"] for row in rows] == [
        "RHEA:10000",
        "RHEA:11091",
        "RHEA:14005",
        "RHEA:20008",
        "RHEA:11091",
        "RHEA:31007",
    ]
    assert [row["source_line"] for row in rows] == ["2", "3", "4", "5", "6", "7"]
    assert rows[1]["source_row_json"] == rows[4]["source_row_json"]
    assert rows[-1]["protein_identifier"] == "A0A023GPI8-2"
    assert rows[-1]["rhea_master_id"] == "RHEA:30000"
    assert rows[-1]["directions_line"] == "3"
    assert json.loads(rows[-1]["family_row_json"]) == {
        "RHEA_ID_MASTER": "30000",
        "RHEA_ID_LR": "31007",
        "RHEA_ID_RL": "32008",
        "RHEA_ID_BI": "33009",
    }
    assert before == {path: path.read_bytes() for path in FIXTURE.iterdir()}
    assert json.loads((tmp_path / "report/manifest.json").read_text()) == manifest
    assert set(path.name for path in (tmp_path / "report").iterdir()) == {"associations.tsv", "manifest.json"}


@pytest.mark.parametrize(
    "body",
    [
        "",
        "10000\tUN\t10000\tP95896\n",
        "RHEA_ID\tID\n10000\tP95896\n",
        "RHEA_ID\tDIRECTION\tMASTER_ID\tID\n\n",
        "RHEA_ID\tDIRECTION\tMASTER_ID\tID\n10000\tUN\t10000\n",
        "RHEA_ID\tDIRECTION\tMASTER_ID\tID\n10000\tUN\t10000\tP95896\textra\n",
    ],
)
def test_exact_header_and_width_required(tmp_path, body):
    """Never discard the first row of a headerless historical file or silently skip malformed lines."""
    mapping = tmp_path / "mapping.tsv"
    mapping.write_text(body)
    with pytest.raises(ValueError):
        run_audit(tmp_path, mapping=mapping)
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize(
    "row",
    [
        "010000\tUN\t10000\tP95896",
        "10000\tUN\t010000\tP95896",
        "１００００\tUN\t10000\tP95896",
        "10000\t UN\t10000\tP95896",
        "10000\tN\t10000\tP95896",
        "10000\tUN\t10000\t",
        "10000\tUN\t10000\tP95896;Q01911",
        "10000\tUN\t10000\tP95896|Q01911",
        "10000\tUN\t10000\tP95896 ",
        "10000\tUN\t10000\tP95896\x00",
        "10000\tUN\t10000\tP95896-0",
        "10000\tLR\t10000\tP95896",
        "11091\tRL\t10000\tP95896",
        "14005\tLR\t10000\tP95896",
        "20008\tUN\t10000\tP95896",
        "11091\tLR\t30000\tP95896",
        "99999\tUN\t99999\tP95896",
    ],
)
def test_invalid_or_contradictory_rows_fail(tmp_path, row):
    """Unknown reactions, swapped directions, altered masters and malformed tokens cannot pass."""
    mapping = tmp_path / "mapping.tsv"
    mapping.write_text("\t".join(reader.HEADER) + "\n" + row + "\n")
    with pytest.raises(ValueError):
        run_audit(tmp_path, mapping=mapping)
    assert not (tmp_path / "report").exists()
    assert not list(tmp_path.glob(".rhea-uniprot-*"))


def test_two_file_policy_does_not_pin_the_auxiliary_mapping(tmp_path):
    """An explicit auxiliary mapping hash is required even with a matching directions policy."""
    with pytest.raises(ValueError, match="explicitly selected SHA"):
        run_audit(tmp_path, expected_sha="0" * 64)
    with pytest.raises(ValueError, match="lowercase mapping SHA"):
        run_audit(tmp_path, expected_sha="not-a-pin")
    assert not (tmp_path / "report").exists()


def test_directions_must_match_policy_bytes(tmp_path):
    """The family lookup cannot silently use an unrelated local directions snapshot."""
    policy = policy_for(tmp_path, FIXTURE / "directions.tsv")
    directions = tmp_path / "directions.tsv"
    directions.write_bytes((FIXTURE / "directions.tsv").read_bytes() + b"40000\t40001\t40002\t40003\n")
    with pytest.raises(ValueError, match="Directions do not match"):
        run_audit(tmp_path, directions=directions, policy=policy)


def test_conflicting_direction_membership_is_rejected_by_native_contract(tmp_path):
    """Reusing a member in two families is rejected even under a matching byte pin."""
    directions = tmp_path / "directions.tsv"
    directions.write_bytes((FIXTURE / "directions.tsv").read_bytes() + b"40000\t11091\t40002\t40003\n")
    with pytest.raises(ValueError, match="repeated membership"):
        run_audit(tmp_path, directions=directions)


def test_no_overwrite_or_dangling_symlink(tmp_path):
    """Existing destinations belong to their owner and are never replaced."""
    output = tmp_path / "report"
    output.symlink_to(tmp_path / "other")
    with pytest.raises(FileExistsError):
        run_audit(tmp_path)
    assert output.is_symlink()


def test_source_mutation_rejects_publication(tmp_path, monkeypatch):
    """A modified input cannot be accepted with its earlier byte fingerprint."""
    mapping = tmp_path / "mapping.tsv"
    mapping.write_bytes((FIXTURE / "mapping.tsv").read_bytes())
    original = reader.mapping_rows

    def change_after_read(stream):
        """Change the selected mapping after its complete row stream has been emitted."""
        yield from original(stream)
        mapping.write_text(mapping.read_text() + "10000\tUN\t10000\tQ01911\n")

    monkeypatch.setattr(reader, "mapping_rows", change_after_read)
    with pytest.raises(ValueError, match="Input changed"):
        run_audit(tmp_path, mapping=mapping)
    assert not (tmp_path / "report").exists()


def test_concurrent_report_is_preserved(tmp_path, monkeypatch):
    """Another publisher winning the output path is not overwritten or deleted."""
    output = tmp_path / "report"
    original = reader.mapping_rows

    def competing_report(stream):
        """Create a competing report after initial path validation."""
        output.mkdir()
        (output / "keep.txt").write_text("keep")
        yield from original(stream)

    monkeypatch.setattr(reader, "mapping_rows", competing_report)
    with pytest.raises(FileExistsError):
        run_audit(tmp_path)
    assert (output / "keep.txt").read_text() == "keep"


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

    monkeypatch.setattr(reader.os, "replace", fail_after_race)
    with pytest.raises(OSError) as failure:
        run_audit(tmp_path)
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
        reader.publish_directory(staging, output)
    assert (output / "foreign.txt").read_text() == "keep"
    assert staging.is_dir()


def test_reader_streams_mapping_rows():
    """Mapping cardinality never requires an in-memory list of all protein associations."""

    class LineStream(io.StringIO):
        """Reject eager reads while supporting CSV's line iterator."""

        def read(self, *args):
            """Reject full-stream reads."""
            raise AssertionError("read is not allowed")

        def readlines(self, *args):
            """Reject collecting the whole mapping."""
            raise AssertionError("readlines is not allowed")

    stream = LineStream("\t".join(reader.HEADER) + "\n" + "10000\tUN\t10000\tP95896\n" * 100000)
    observations = reader.mapping_rows(stream)
    assert next(observations)[0] == 2
    assert stream.tell() < 1000


def test_empty_mapping_reports_zero_without_invented_associations(tmp_path):
    """A header-only mapping yields an honest zero-row audit."""
    mapping = tmp_path / "mapping.tsv"
    mapping.write_text("\t".join(reader.HEADER) + "\n")
    assert run_audit(tmp_path, mapping=mapping)["rows"] == 0


def test_help_needs_no_source(tmp_path):
    """CLI help never opens source files or native ontology infrastructure."""
    with pytest.raises(SystemExit) as stopped:
        reader.main(["--help"])
    assert stopped.value.code == 0
