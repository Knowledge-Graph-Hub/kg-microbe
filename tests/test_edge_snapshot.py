"""Lossless producer exports bind every occurrence to a completely verified snapshot."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "kg_microbe" / "edge_snapshot.py"
SPEC = importlib.util.spec_from_file_location("edge_snapshot", MODULE)
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)
FIXTURES = Path(__file__).parent / "resources" / "edge_snapshot"


def _manifest(directory, *, provenance=None):
    """Describe fixture bytes using the published producer's manifest-v1 format."""
    members = {}
    for path in sorted(directory.glob("*.tsv")):
        raw = path.read_bytes()
        members[path.name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "rows": len(raw.splitlines()) - 1,
        }
    path = directory / "manifest.json"
    path.write_text(
        json.dumps(
            {"manifest_version": 1, "members": members, "provenance": provenance or {"commit": "fixture"}}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def source(tmp_path):
    """Copy the tiny immutable corpus; every test mutates only its temporary copy."""
    directory = tmp_path / "input"
    shutil.copytree(FIXTURES, directory)
    return _manifest(directory)


def _export(source, destination, **kwargs):
    return snapshot.export_snapshot(source, destination, edge_member="edges.tsv", **kwargs)


def _records(output, result):
    return [
        json.loads(line)
        for shard in result["shards"]
        for line in (output / shard["file"]).read_text(encoding="utf-8").splitlines()
    ]


def test_complete_export_reconstructs_exact_source_and_independent_id(source, tmp_path):
    """Duplicate, negated, qualified, Unicode, quoted, and empty values survive intact."""
    output = tmp_path / "export"
    result = _export(source, output, shard_rows=2)
    records = _records(output, result)
    assert [row["row_number"] for row in records] == [1, 2, 3]
    assert len({row["occurrence_id"] for row in records}) == 3
    assert records[0]["source_row"] == records[1]["source_row"]
    rebuilt = result["members"]["edges.tsv"]["header_row"] + "".join(row["source_row"] for row in records)
    assert rebuilt.encode("utf-8") == (source.parent / "edges.tsv").read_bytes()
    assert (output / "source-manifest.json").read_bytes() == source.read_bytes()
    assert json.loads((output / "manifest.json").read_text()) == result
    assert result["selection"]["complete_export"] is True
    assert result["input_complete"] is True
    for record in records:
        payload = {
            key: record[key] for key in ("manifest_sha256", "member", "member_sha256", "row_number", "row_sha256")
        }
        assert payload["row_sha256"] == hashlib.sha256(record["source_row"].encode()).hexdigest()
        envelope = {"contract": "kg-microbe-curation/v1", "kind": "occurrence", "payload": payload}
        encoded = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        assert record["occurrence_id"] == "urn:kg-microbe:occurrence:v1:" + hashlib.sha256(encoded).hexdigest()
    for shard in result["shards"]:
        raw = (output / shard["file"]).read_bytes()
        assert shard["sha256"] == hashlib.sha256(raw).hexdigest()
        assert shard["bytes"] == len(raw)
        assert shard["rows"] == len(raw.splitlines()) <= 2


def test_subset_is_distinct_from_complete_verification(source, tmp_path):
    """A one-row export reports all input rows and verifies the auxiliary member too."""
    result = _export(source, tmp_path / "export", max_rows=1)
    assert result["selection"] == {
        "edge_member": "edges.tsv",
        "max_rows": 1,
        "exported_rows": 1,
        "complete_export": False,
    }
    assert result["input_complete"] is True
    assert result["members"]["edges.tsv"]["rows"] == 3
    assert result["members"]["reference_resolution.tsv"]["rows"] == 1


@pytest.mark.parametrize("member", ["edges.tsv", "nodes.tsv", "reference_resolution.tsv"])
def test_unexported_tail_and_other_members_must_match(source, tmp_path, member):
    """Late corruption cannot publish a subset that happened to look valid."""
    path = source.parent / member
    path.write_bytes(
        path.read_bytes().replace(b"retained", b"rejected")
        if member.startswith("reference")
        else path.read_bytes() + b"bad\n"
    )
    output = tmp_path / "export"
    with pytest.raises(ValueError):
        _export(source, output, max_rows=1)
    assert not output.exists()
    assert not list(tmp_path.glob(".export.export-*"))


@pytest.mark.parametrize("field,value", [("bytes", 1), ("rows", 99), ("sha256", "0" * 64)])
def test_all_manifest_identity_components_are_enforced(source, tmp_path, field, value):
    """Each declared identity component must independently match observed bytes."""
    data = json.loads(source.read_text())
    data["members"]["edges.tsv"][field] = value
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="does not match"):
        _export(source, tmp_path / "export")


def test_identity_is_relocation_stable_but_snapshot_specific(source, tmp_path):
    """Filesystem paths do not affect identity, but release provenance does."""
    first = tmp_path / "first"
    rows = _records(first, _export(source, first))
    relocated = tmp_path / "relocated"
    shutil.copytree(source.parent, relocated)
    second = tmp_path / "second"
    moved = _records(second, _export(relocated / source.name, second))
    assert rows == moved
    changed = _manifest(relocated, provenance={"commit": "different-release"})
    third = tmp_path / "third"
    different = _records(third, _export(changed, third))
    assert rows[0]["row_sha256"] == different[0]["row_sha256"]
    assert rows[0]["occurrence_id"] != different[0]["occurrence_id"]


def test_crlf_and_unterminated_final_row_are_exact(source, tmp_path):
    """Transport line endings remain evidence rather than being normalized."""
    path = source.parent / "edges.tsv"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n").removesuffix(b"\r\n"))
    _manifest(source.parent)
    output = tmp_path / "export"
    result = _export(source, output)
    rows = _records(output, result)
    assert rows[0]["source_row"].endswith("\r\n")
    assert not rows[-1]["source_row"].endswith("\n")
    rebuilt = result["members"]["edges.tsv"]["header_row"] + "".join(row["source_row"] for row in rows)
    assert rebuilt.encode() == path.read_bytes()


@pytest.mark.parametrize("bad", [b"a\ta\nx\ty\n", b"a\t\nx\ty\n", b"a\tb\nx\n", b"", b"a\nx\x00\n", b"a\n\xff\n"])
def test_malformed_member_is_rejected_even_with_matching_manifest(source, tmp_path, bad):
    """Correct checksums cannot admit ambiguous or malformed table structure."""
    (source.parent / "edges.tsv").write_bytes(bad)
    _manifest(source.parent)
    with pytest.raises(ValueError):
        _export(source, tmp_path / "export")


@pytest.mark.parametrize("name", ["../outside.tsv", "/absolute.tsv", "nested/member.tsv"])
def test_manifest_member_traversal_is_refused(source, tmp_path, name):
    """A member locator cannot escape the manifest's directory."""
    data = json.loads(source.read_text())
    data["members"][name] = data["members"].pop("edges.tsv")
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="member name"):
        _export(source, tmp_path / "export")


def test_duplicate_manifest_keys_and_symlink_members_are_refused(source, tmp_path):
    """Ambiguous metadata and indirect member paths are rejected."""
    original = source.read_bytes()
    source.write_bytes(original.replace(b'"manifest_version": 1', b'"manifest_version": 1, "manifest_version": 1'))
    with pytest.raises(ValueError, match="Duplicate"):
        _export(source, tmp_path / "export")
    source.write_bytes(original)
    member = source.parent / "edges.tsv"
    outside = tmp_path / "outside.tsv"
    member.rename(outside)
    member.symlink_to(outside)
    with pytest.raises(ValueError, match="non-symlink"):
        _export(source, tmp_path / "export")


def test_byte_bounds_rotate_shards_and_reject_oversize_rows(source, tmp_path):
    """Both transfer sizes and individual input rows obey explicit ceilings."""
    initial = tmp_path / "initial"
    result = _export(source, initial, shard_rows=1)
    size = max(shard["bytes"] for shard in result["shards"])
    output = tmp_path / "export"
    bounded = _export(source, output, shard_bytes=size)
    assert len(bounded["shards"]) == 3
    assert all(shard["bytes"] <= size for shard in bounded["shards"])
    with pytest.raises(ValueError, match="shard byte limit"):
        _export(source, tmp_path / "too-small", shard_bytes=size - 1)
    with pytest.raises(ValueError, match="Row exceeds"):
        _export(source, tmp_path / "long-row", max_row_bytes=10)
    assert not (tmp_path / "too-small").exists()
    assert not (tmp_path / "long-row").exists()


def test_existing_output_and_cooperating_writer_are_refused(source, tmp_path):
    """Existing output and another exporter's reservation are never overwritten."""
    output = tmp_path / "export"
    output.mkdir()
    sentinel = output / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(FileExistsError):
        _export(source, output)
    assert sentinel.read_text() == "untouched"
    (tmp_path / ".other.export-lock").write_text("another process")
    with pytest.raises(FileExistsError):
        _export(source, tmp_path / "other")


def test_input_change_after_scanning_prevents_publication(source, tmp_path, monkeypatch):
    """Detect replacement of an earlier member while a later one is consumed."""
    real_open = snapshot._regular_open

    def mutate_when_opening_reference(path):
        """Simulate replacing an earlier member while a later member is read."""
        if path.name == "reference_resolution.tsv":
            edges = source.parent / "edges.tsv"
            edges.write_bytes(edges.read_bytes() + b"changed\n")
        return real_open(path)

    monkeypatch.setattr(snapshot, "_regular_open", mutate_when_opening_reference)
    with pytest.raises(ValueError, match="Snapshot changed"):
        _export(source, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_write_failure_cleans_only_own_stage(source, tmp_path, monkeypatch):
    """A mid-export disk failure leaves source files and output visibility unchanged."""
    real_write = snapshot._Shards.write

    def fail_after_one(self, row):
        """Simulate a disk failure after the first occurrence has been staged."""
        if self.total:
            raise OSError("simulated disk failure")
        real_write(self, row)

    monkeypatch.setattr(snapshot._Shards, "write", fail_after_one)
    with pytest.raises(OSError, match="simulated"):
        _export(source, tmp_path / "export")
    assert not (tmp_path / "export").exists()
    assert (source.parent / "edges.tsv").read_bytes() == (FIXTURES / "edges.tsv").read_bytes()
    assert not list(tmp_path.glob(".export.export-*"))


def test_empty_edge_table_is_a_complete_empty_export(source, tmp_path):
    """Header-only input needs no placeholder shard or invented occurrence."""
    path = source.parent / "edges.tsv"
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    _manifest(source.parent)
    result = _export(source, tmp_path / "export")
    assert result["shards"] == []
    assert result["selection"]["complete_export"] is True
    assert result["selection"]["exported_rows"] == 0


def test_standalone_cli_works_without_site_packages_and_reports_failure(source, tmp_path):
    """The actual argparse entry point requires only Python's standard library."""
    command = [sys.executable, "-S", str(MODULE)]
    env = {**os.environ, "PYTHONPATH": ""}
    result = subprocess.run(command + ["--help"], env=env, capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0
    assert "inventory" in result.stdout
    result = subprocess.run(  # noqa: S603
        command + ["export", str(source), str(tmp_path / "export"), "--edge-member", "edges.tsv", "--max-rows", "1"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selection"]["exported_rows"] == 1
    assert (tmp_path / "export" / "manifest.json").stat().st_size > 0
    (source.parent / "nodes.tsv").write_bytes(b"broken\n")
    result = subprocess.run(  # noqa: S603
        command + ["inventory", str(source), "--edge-member", "edges.tsv"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "does not match" in result.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO admission applies to POSIX filesystems")
@pytest.mark.parametrize("name", ["manifest.json", "edges.tsv"])
def test_fifo_input_fails_without_waiting_for_a_writer(source, tmp_path, name):
    """Reject named pipes promptly before reading metadata or rows (KG #1717; CLAW #759)."""
    path = source.parent / name
    path.unlink()
    os.mkfifo(path)
    output = tmp_path / "export"
    result = subprocess.run(  # noqa: S603 - fixed local interpreter and temporary fixture paths
        [sys.executable, "-S", str(MODULE), "export", str(source), str(output), "--edge-member", "edges.tsv"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "regular, non-symlink file" in result.stderr
    assert result.stdout == ""
    assert not output.exists()
    assert not list(tmp_path.glob(".export.export-*"))
