"""Gzipped raw authorities are unpacked once, atomically, by whichever reader needs them first (#1526)."""

import gzip

import pytest

from kg_microbe.utils import atomic_io
from kg_microbe.utils.atomic_io import gunzip_beside


def test_only_the_archive_present_is_unpacked_beside_it(tmp_path):
    """The uncompressed file appears next to its archive with the archive's content."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    assert gunzip_beside(tmp_path / "ncit.db", root=tmp_path).read_bytes() == b"sqlite bytes"


def test_an_existing_file_is_left_untouched(tmp_path):
    """Unpacking is idempotent: a present file is never rewritten from the archive."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"archive"))
    (tmp_path / "ncit.db").write_bytes(b"existing")
    assert gunzip_beside(tmp_path / "ncit.db").read_bytes() == b"existing"


def test_neither_file_present_returns_the_missing_path(tmp_path):
    """The caller decides what an absent authority means."""
    assert not gunzip_beside(tmp_path / "ncit.db").exists()


def test_an_archive_outside_the_root_is_refused(tmp_path):
    """A link from the selected directory to another tree is not followed."""
    raw, elsewhere = tmp_path / "raw", tmp_path / "elsewhere"
    raw.mkdir()
    elsewhere.mkdir()
    (elsewhere / "ncit.db.gz").write_bytes(gzip.compress(b"foreign"))
    (raw / "ncit.db.gz").symlink_to(elsewhere / "ncit.db.gz")
    with pytest.raises(ValueError, match="outside the selected directory"):
        gunzip_beside(raw / "ncit.db", root=raw)
    assert not (raw / "ncit.db").exists()


def test_an_interrupted_unpack_leaves_no_file(tmp_path, monkeypatch):
    """A failed copy publishes nothing, so the next reader unpacks again rather than reading a fragment."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))

    def fail(source, destination):
        """Write a fragment, then fail as an interrupted copy would."""
        destination.write(b"sql")
        raise OSError("fixture copy failure")

    monkeypatch.setattr(atomic_io.shutil, "copyfileobj", fail)
    with pytest.raises(OSError, match="copy failure"):
        gunzip_beside(tmp_path / "ncit.db")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db.gz"]
