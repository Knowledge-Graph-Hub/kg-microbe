"""Offline selection, checksum, and archive-integrity controls for the narrow refresh."""

import gzip
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/kgm_rebuild_refresh_20261105.py"
REQUIRED = ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp")


@pytest.fixture
def refresh(tmp_path, monkeypatch):
    """Bind the helper to a temporary owned checkout and isolated raw files."""
    spec = importlib.util.spec_from_file_location("rebuild_refresh_test", SCRIPT)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    root = tmp_path / "owned"
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    monkeypatch.setattr(helper, "ROOT", root)
    monkeypatch.setattr(helper, "RAW", raw)
    monkeypatch.setattr(helper, "EVIDENCE", root / "data/rebuild-evidence/refresh")
    return helper


def write_manifest(refresh):
    """Provide canonical inputs alongside unrelated sources that must never be selected."""
    entries = [
        {"url": refresh.URLS["taxdump.tar.gz"], "local_name": "taxdump.tar.gz", "tag": "gold"},
        {"url": refresh.URLS["mediadive.json"], "local_name": "mediadive.json", "tag": "mediadive"},
        {"url": "https://example.org/unrelated", "local_name": "gold.tsv", "tag": "gold"},
        {"url": "https://example.org/ontology.owl", "local_name": "ontology.owl", "tag": "ontologies"},
    ]
    (refresh.ROOT / "download.yaml").write_text(yaml.safe_dump(entries))
    for name in refresh.URLS:
        (refresh.RAW / name).write_bytes(b"preserved raw input: " + name.encode())
    return entries


def make_taxdump(refresh, entries=None):
    """Create a tiny real gzip/tar authority archive without extracting any files."""
    if entries is None:
        entries = [(name, tarfile.REGTYPE, (name + "\n").encode()) for name in REQUIRED]
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE:
                member.linkname = "outside"
            archive.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    path = refresh.RAW / "taxdump.tar.gz"
    path.write_bytes(gzip.compress(stream.getvalue(), mtime=0))
    return path


def supply_matching_checksums(refresh, path, monkeypatch):
    """Make official evidence match fixture bytes so structural tests reach the real archive reader."""
    expected = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    refresh.EVIDENCE.mkdir(parents=True, exist_ok=True)
    (refresh.EVIDENCE / "before-checksum.json").write_text(json.dumps({"official_md5": expected}))
    monkeypatch.setattr(refresh, "checksum", lambda label: expected)
    return expected


def test_prepare_selects_only_authorized_inputs_and_retags_them(refresh, monkeypatch):
    """The production config cannot accidentally activate full MediaDive or broad GOLD refreshes."""
    entries = write_manifest(refresh)
    originals = {name: (refresh.RAW / name).read_bytes() for name in refresh.URLS}
    calls = []

    def checksum(label):
        """Capture only the explicit before-checksum acquisition."""
        calls.append(label)
        return "1" * 32

    monkeypatch.setattr(refresh, "checksum", checksum)
    refresh.prepare()
    selected = yaml.safe_load((refresh.EVIDENCE / "download.yaml").read_text())
    assert selected == [
        {**entries[0], "tag": "refresh-taxdump"},
        {**entries[1], "tag": "refresh-mediadive-list"},
    ]
    assert calls == ["before"]
    assert yaml.safe_load((refresh.ROOT / "download.yaml").read_text()) == entries
    identities = json.loads((refresh.EVIDENCE / "before-inputs.json").read_text())
    for name, content in originals.items():
        assert (refresh.RAW / name).read_bytes() == content
        assert identities[name]["sha256"] == hashlib.sha256(content).hexdigest()
    before = (refresh.EVIDENCE / "download.yaml").read_bytes()
    with pytest.raises(FileExistsError):
        refresh.prepare()
    assert calls == ["before"] and (refresh.EVIDENCE / "download.yaml").read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "duplicate", "changed_url"])
def test_prepare_rejects_changed_canonical_identity_before_writes(refresh, monkeypatch, damage):
    """A missing, ambiguous, or redirected canonical source cannot create an actionable config."""
    entries = write_manifest(refresh)
    if damage == "missing":
        entries.pop(0)
    elif damage == "duplicate":
        entries.append(dict(entries[0]))
    else:
        entries[0]["url"] = "https://example.org/unreviewed.tar.gz"
    (refresh.ROOT / "download.yaml").write_text(yaml.safe_dump(entries))
    monkeypatch.setattr(refresh, "checksum", lambda label: pytest.fail("invalid selection fetched checksum"))
    with pytest.raises(RuntimeError, match="Canonical refresh identity"):
        refresh.prepare()
    assert not refresh.EVIDENCE.exists()


@pytest.mark.parametrize("marker", ["", "*"])
def test_checksum_accepts_official_format_and_retains_https_headers(refresh, monkeypatch, marker):
    """Checksum requests disable curl configuration and retain fresh official response evidence."""
    refresh.EVIDENCE.mkdir(parents=True)
    expected = "0123456789abcdef" * 2
    calls = []

    def curl(command, *, check):
        """Write a synthetic successful checksum response and its headers."""
        assert check is True
        calls.append(command)
        Path(command[command.index("--output") + 1]).write_text(f"{expected.upper()}  {marker}taxdump.tar.gz\n")
        Path(command[command.index("--dump-header") + 1]).write_text("HTTP/2 200\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(refresh.subprocess, "run", curl)
    assert refresh.checksum("before") == expected
    command = calls[0]
    assert command[:2] == ["/usr/bin/curl", "--disable"]
    assert command[-1] == refresh.URLS["taxdump.tar.gz"] + ".md5"
    assert command[command.index("--proto") + 1] == command[command.index("--proto-redir") + 1] == "=https"
    assert command[command.index("--retry") + 1] == "3"
    assert (refresh.EVIDENCE / "taxdump-before.headers").read_text() == "HTTP/2 200\n"


@pytest.mark.parametrize("suffix,link", [(".md5", False), (".headers", False), (".md5", True), (".headers", True)])
def test_checksum_preserves_orphan_headers_and_dangling_links(refresh, tmp_path, monkeypatch, suffix, link):
    """A retry must not replace prior HTTP evidence even if curl never produced the checksum body."""
    refresh.EVIDENCE.mkdir(parents=True)
    path = refresh.EVIDENCE / ("taxdump-before" + suffix)
    if link:
        path.symlink_to(tmp_path / "missing")
    else:
        path.write_text("preserved failed-request evidence")
    monkeypatch.setattr(refresh.subprocess, "run", lambda *a, **kw: pytest.fail("existing evidence reached curl"))
    with pytest.raises(RuntimeError, match="overwrite"):
        refresh.checksum("before")
    assert path.is_symlink() if link else path.read_text() == "preserved failed-request evidence"


@pytest.mark.parametrize(
    "body", ["abc taxdump.tar.gz", "f" * 32 + " other.tar.gz", "x" * 32 + " taxdump.tar.gz", "f" * 32]
)
def test_checksum_rejects_malformed_or_wrong_file_response(refresh, monkeypatch, body):
    """Only the named authority archive and a complete hexadecimal digest are accepted."""
    refresh.EVIDENCE.mkdir(parents=True)

    def curl(command, *, check):
        """Persist the malformed response without contacting a service."""
        Path(command[command.index("--output") + 1]).write_text(body)

    monkeypatch.setattr(refresh.subprocess, "run", curl)
    with pytest.raises((RuntimeError, ValueError)):
        refresh.checksum("before")
    assert (refresh.EVIDENCE / "taxdump-before.md5").read_text() == body


def test_taxdump_success_requires_stable_checksum_and_real_archive_integrity(refresh, monkeypatch):
    """A valid receipt records complete hashes and nonempty authority members without extracting them."""
    path = make_taxdump(refresh)
    expected = supply_matching_checksums(refresh, path, monkeypatch)
    monkeypatch.setattr(tarfile.TarFile, "extractall", lambda *a, **kw: pytest.fail("archive was extracted"))
    refresh.verify_taxdump()
    receipt = json.loads((refresh.EVIDENCE / "taxdump-receipt.json").read_text())
    assert receipt["identity"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["official_md5"] == expected
    assert set(receipt["members"]) == set(REQUIRED)
    assert receipt["gzip_integrity"] and receipt["stable_upstream_checksum"]
    assert not (refresh.RAW / "nodes.dmp").exists()


@pytest.mark.parametrize("damage", ["upstream_changed", "download_mismatch"])
def test_taxdump_rejects_checksum_change_or_mismatched_download(refresh, monkeypatch, damage):
    """Both upstream observations and actual downloaded bytes must identify the same snapshot."""
    path = make_taxdump(refresh)
    supply_matching_checksums(refresh, path, monkeypatch)
    monkeypatch.setattr(refresh, "checksum", lambda label: "0" * 32)
    if damage == "download_mismatch":
        (refresh.EVIDENCE / "before-checksum.json").write_text(json.dumps({"official_md5": "0" * 32}))
    with pytest.raises(RuntimeError, match="checksum changed"):
        refresh.verify_taxdump()
    assert not (refresh.EVIDENCE / "taxdump-receipt.json").exists()


@pytest.mark.parametrize("damage", ["missing", "empty", "duplicate", "symlink", "bad_crc", "truncated_gzip"])
def test_taxdump_rejects_invalid_archive_even_with_matching_official_md5(refresh, monkeypatch, damage):
    """A matching download digest cannot replace native-member and complete gzip validation."""
    entries = [(name, tarfile.REGTYPE, b"authority row\n") for name in REQUIRED]
    if damage == "missing":
        entries.pop()
    elif damage == "empty":
        entries[0] = (entries[0][0], tarfile.REGTYPE, b"")
    elif damage == "duplicate":
        entries.append(entries[0])
    elif damage == "symlink":
        entries[0] = (entries[0][0], tarfile.SYMTYPE, b"")
    path = make_taxdump(refresh, entries)
    if damage == "bad_crc":
        corrupted = bytearray(path.read_bytes())
        corrupted[-8] ^= 1
        path.write_bytes(corrupted)
    elif damage == "truncated_gzip":
        path.write_bytes(path.read_bytes()[:-4])
    supply_matching_checksums(refresh, path, monkeypatch)
    with pytest.raises((RuntimeError, OSError, EOFError, tarfile.TarError)):
        refresh.verify_taxdump()
    assert not (refresh.EVIDENCE / "taxdump-receipt.json").exists()
