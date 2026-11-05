"""Offline acquisition and archive boundaries for the retained upgrade helper."""

import gzip
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/kgm_upgrade_inputs_20261105.py"


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    """Bind acquisition to a temporary checkout without invoking curl or production code."""
    spec = importlib.util.spec_from_file_location("upgrade_inputs_test", SCRIPT)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    root = tmp_path / "owned"
    root.mkdir()
    monkeypatch.setattr(helper, "ROOT", root)
    monkeypatch.setattr(helper, "CANDIDATES", root / "data/rebuild-evidence/20261105/upgrades/candidates")
    return helper


@pytest.fixture
def fake_curl(acquisition, monkeypatch):
    """Persist synthetic transport output while capturing the exact safe curl command."""
    state = {"body": b"downloaded candidate\n", "returncode": 0, "http_code": 200, "url": "https://example.org/file"}
    calls = []

    def run(command, *, stdout, stderr, stdin, check):
        """Model curl's files and final metrics without any network requests."""
        calls.append(command)
        assert stdin == subprocess.DEVNULL and check is False
        Path(command[command.index("--output") + 1]).write_bytes(state["body"])
        Path(command[command.index("--dump-header") + 1]).write_bytes(b"HTTP/2 200\r\ncontent-type: text/plain\r\n\r\n")
        metadata = {
            "url_effective": state["url"],
            "http_code": state["http_code"],
            "size_download": state.get("size_download", len(state["body"])),
        }
        stdout.write(json.dumps(metadata).encode())
        if state["returncode"]:
            stderr.write(b"synthetic curl failure\n")
        return subprocess.CompletedProcess(command, state["returncode"])

    monkeypatch.setattr(acquisition.subprocess, "run", run)
    return state, calls


def request_spec(**updates):
    """Create a small synthetic request using the same acquisition contract."""
    return {"key": "fixture", "url": "https://example.org/file", "relative_path": "fixture/input.bin", **updates}


def make_archive(path, entries):
    """Write synthetic tar members, including deliberate duplicate or unsafe names."""
    with tarfile.open(path, "w:bz2") as archive:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../outside"
            archive.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def native_entries():
    """Return minimal independent directions and compressed RDF byte streams."""
    return [
        ("143/tsv/rhea-directions.tsv", tarfile.REGTYPE, b"MASTER\tLR\tRL\tBI\n1\t2\t3\t4\n"),
        ("143/rdf/rhea.rdf.gz", tarfile.REGTYPE, gzip.compress(b"<rdf>synthetic</rdf>\n", mtime=0)),
    ]


def test_plan_is_read_only_and_uses_official_fixed_versions(acquisition, monkeypatch, capsys):
    """Planning exposes the six immutable URLs without creating the candidate tree."""
    monkeypatch.setattr(acquisition.subprocess, "run", lambda *a, **kw: pytest.fail("plan ran a subprocess"))
    assert acquisition.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not acquisition.CANDIDATES.exists()
    assert result["activates_raw_inputs"] is False
    downloads = {entry["key"]: entry for entry in result["downloads"]}
    assert len(downloads) == 6
    assert downloads["robot-jar"]["expected_sha256"] == (
        "53cd275c8e4c0dad1fc2c1c34174876795cd7d6b6926e1444adcbb0cb3c7ab26"
    )
    assert downloads["rhea-archive"]["url"] == "https://ftp.expasy.org/databases/rhea/old_releases/143.tar.bz2"
    assert {entry["url"] for key, entry in downloads.items() if key.startswith("biolink-")} == {
        f"https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/{name}"
        for name in ("biolink-model.yaml", "predicate_mapping.yaml", "attributes.yaml")
    }


@pytest.mark.parametrize("damage", ["existing", "parent_symlink", "dangling_link"])
def test_plan_refuses_existing_or_redirected_candidates(acquisition, tmp_path, damage):
    """Candidate acquisition cannot reuse earlier evidence or escape through linked parents."""
    if damage == "existing":
        acquisition.CANDIDATES.mkdir(parents=True)
    elif damage == "parent_symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        (acquisition.ROOT / "data").symlink_to(outside, target_is_directory=True)
    else:
        acquisition.CANDIDATES.parent.mkdir(parents=True)
        acquisition.CANDIDATES.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(ValueError):
        acquisition.plan()


def test_download_preserves_request_and_persisted_byte_evidence(acquisition, fake_curl):
    """Success binds bytes to HTTPS transport evidence and requires an independent completed file."""
    state, calls = fake_curl
    expected = hashlib.sha256(state["body"]).hexdigest()
    receipt = acquisition.download(acquisition.CANDIDATES, request_spec(expected_sha256=expected))
    candidate = Path(receipt["candidate"])
    evidence = acquisition.CANDIDATES / "http/fixture"
    assert candidate.read_bytes() == state["body"] and candidate.stat().st_nlink == 1
    assert not candidate.with_name(candidate.name + ".partial").exists()
    assert receipt["sha256"] == receipt["expected_sha256"] == expected
    assert receipt["bytes"] == len(state["body"])
    assert receipt["actual_url"] == receipt["source_url"] == state["url"]
    assert receipt["finished"] >= receipt["started"]
    assert json.loads((evidence / "receipt.json").read_text()) == receipt
    assert (evidence / "headers.txt").is_file() and (evidence / "curl-metadata.json").is_file()
    command = calls[0]
    assert command[1] == "--disable"
    assert "--fail" in command and "--location" in command
    assert command[command.index("--retry") + 1] == "3"
    assert command[command.index("--proto") + 1] == command[command.index("--proto-redir") + 1] == "=https"
    assert json.loads((evidence / "command.json").read_text())["argv"] == command
    before = candidate.read_bytes()
    with pytest.raises(ValueError, match="replace candidate"):
        acquisition.download(acquisition.CANDIDATES, request_spec())
    assert len(calls) == 1 and candidate.read_bytes() == before


@pytest.mark.parametrize("damage", ["curl_failure", "sha256", "empty", "partial_http", "wrong_size", "http_redirect"])
def test_download_failure_retains_evidence_without_publishing(acquisition, fake_curl, damage):
    """Transport, completeness, and official-checksum failures cannot become successful candidates."""
    state, _ = fake_curl
    spec = request_spec()
    if damage == "curl_failure":
        state["returncode"] = 22
    elif damage == "sha256":
        spec["expected_sha256"] = "0" * 64
    elif damage == "empty":
        state["body"] = b""
    elif damage == "partial_http":
        state["http_code"] = 206
    elif damage == "wrong_size":
        state["size_download"] = 999
    else:
        state["url"] = "http://example.org/insecure"
    with pytest.raises(ValueError):
        acquisition.download(acquisition.CANDIDATES, spec)
    candidate = acquisition.CANDIDATES / spec["relative_path"]
    evidence = acquisition.CANDIDATES / "http/fixture"
    assert not candidate.exists() and candidate.with_name(candidate.name + ".partial").is_file()
    failure = json.loads((evidence / "failure.json").read_text())
    assert failure["status"] == "failed" and failure["sha256"] == hashlib.sha256(state["body"]).hexdigest()
    assert (evidence / "curl-metadata.json").is_file()
    assert not (evidence / "receipt.json").exists()


def test_atomic_publication_refuses_a_racing_destination(acquisition, tmp_path):
    """No-replace publication preserves an already-created destination and the unpublished bytes."""
    partial, destination = tmp_path / "receipt.partial", tmp_path / "receipt.json"
    partial.write_bytes(b"new evidence")
    destination.write_bytes(b"prior evidence")
    with pytest.raises(FileExistsError):
        acquisition.publish_new(partial, destination)
    assert destination.read_bytes() == b"prior evidence"
    assert partial.read_bytes() == b"new evidence"


def test_rhea_extracts_only_exact_members_and_records_native_hashes(acquisition, tmp_path):
    """Extraction streams selected contents into fixed names and never unpacks unrelated members."""
    archive, output = tmp_path / "143.tar.bz2", tmp_path / "rhea143"
    entries = native_entries()
    make_archive(archive, [*entries, ("143/unrelated.txt", tarfile.REGTYPE, b"ignored")])
    result = acquisition.extract_rhea(archive, output)
    assert set(path.name for path in output.iterdir()) == {"rhea-directions.tsv", "rhea.rdf.gz", "extraction.json"}
    assert result["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    for name, _, content in entries:
        measured = result["members"][name]
        assert Path(measured["path"]).read_bytes() == content
        assert measured["sha256"] == hashlib.sha256(content).hexdigest()
        assert measured["bytes"] == len(content)
    with pytest.raises(ValueError, match="replace extracted"):
        acquisition.extract_rhea(archive, output)


@pytest.mark.parametrize(
    "damage", ["missing", "empty", "duplicate", "symlink", "hardlink", "directory", "traversal", "absolute"]
)
def test_rhea_rejects_unsafe_or_ambiguous_archive_before_publication(acquisition, tmp_path, damage):
    """Missing, repeated, linked, or unsafe headers cannot publish either native member."""
    archive, output = tmp_path / "143.tar.bz2", tmp_path / "rhea143"
    entries = native_entries()
    if damage == "missing":
        entries.pop()
    elif damage == "empty":
        entries[0] = (entries[0][0], tarfile.REGTYPE, b"")
    elif damage == "duplicate":
        entries.append(entries[0])
    elif damage in {"symlink", "hardlink", "directory"}:
        kind = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "directory": tarfile.DIRTYPE}[damage]
        entries[1] = (entries[1][0], kind, b"")
    else:
        entries.append(("../outside" if damage == "traversal" else "/outside", tarfile.REGTYPE, b"unsafe"))
    make_archive(archive, entries)
    with pytest.raises(ValueError):
        acquisition.extract_rhea(archive, output)
    assert not (output / "extraction.json").exists()
    assert not (output / "rhea-directions.tsv").exists()
    assert not (output / "rhea.rdf.gz").exists()
    assert not (tmp_path / "outside").exists()


def test_failed_batch_retains_failure_without_success_receipt(acquisition, monkeypatch):
    """One acquisition failure blocks extraction and the overall success receipt."""
    monkeypatch.chdir(acquisition.ROOT)
    monkeypatch.setattr(
        acquisition,
        "sys",
        SimpleNamespace(prefix=str(acquisition.ROOT / ".venv"), executable="fixture-python", argv=["execute"]),
    )
    monkeypatch.setattr(acquisition, "DOWNLOADS", (request_spec(),))

    def fail_download(candidate_dir, spec):
        """Model a recorded worker failure without accessing the network."""
        raise ValueError("synthetic worker failure")

    monkeypatch.setattr(acquisition, "download", fail_download)
    monkeypatch.setattr(acquisition, "extract_rhea", lambda *a: pytest.fail("failed batch reached extraction"))
    with pytest.raises(ValueError, match="synthetic worker failure"):
        acquisition.execute()
    assert (acquisition.CANDIDATES / "plan.json").is_file()
    assert (acquisition.CANDIDATES / "failure.json").is_file()
    assert not (acquisition.CANDIDATES / "receipt.json").exists()


def test_successful_batch_keeps_raw_inputs_untouched(acquisition, monkeypatch):
    """Overall success records extraction while leaving existing production raw bytes intact."""
    monkeypatch.chdir(acquisition.ROOT)
    monkeypatch.setattr(
        acquisition,
        "sys",
        SimpleNamespace(prefix=str(acquisition.ROOT / ".venv"), executable="fixture-python", argv=["execute"]),
    )
    raw = acquisition.ROOT / "data/raw"
    raw.mkdir(parents=True)
    marker = raw / "rhea.rdf.gz"
    marker.write_bytes(b"preserved original snapshot")
    monkeypatch.setattr(
        acquisition, "DOWNLOADS", (request_spec(key="rhea-archive", relative_path="rhea143/143.tar.bz2"),)
    )

    def acquire_fixture(candidate_dir, spec):
        """Produce an independent local fixture at the planned candidate location."""
        archive = candidate_dir / spec["relative_path"]
        archive.parent.mkdir()
        make_archive(archive, native_entries())
        return {"candidate": str(archive), "sha256": acquisition.digest(archive)}

    monkeypatch.setattr(acquisition, "download", acquire_fixture)
    result = acquisition.execute()
    assert result["status"] == "acquired_not_activated"
    assert result["scientific_release_admission"] is False
    assert json.loads((acquisition.CANDIDATES / "receipt.json").read_text()) == result
    assert set(result["rhea_extraction"]["members"]) == set(acquisition.RHEA_MEMBERS)
    assert marker.read_bytes() == b"preserved original snapshot"
    assert list(raw.iterdir()) == [marker]
