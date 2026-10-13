"""Gzipped raw authorities are unpacked once, atomically, by whichever reader needs them first (#1526)."""

import gzip
from pathlib import Path

import pytest

from kg_microbe.utils import atomic_io
from kg_microbe.utils.atomic_io import gunzip_beside


def test_only_the_archive_present_is_unpacked_beside_it(tmp_path):
    """The uncompressed file appears next to its archive with the archive's content."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    assert gunzip_beside(tmp_path / "ncit.db", root=tmp_path).read_bytes() == b"sqlite bytes"


def test_an_unpacked_copy_of_the_archive_is_left_untouched(tmp_path):
    """A present file the archive's size agrees with is not unpacked again."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"archive!"))
    (tmp_path / "ncit.db").write_bytes(b"existing")
    before = (tmp_path / "ncit.db").stat()
    assert gunzip_beside(tmp_path / "ncit.db").read_bytes() == b"existing"
    after = (tmp_path / "ncit.db").stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_a_copy_from_an_older_archive_is_unpacked_again(tmp_path):
    """After a newer archive is downloaded, the stale database is replaced (#1536)."""
    (tmp_path / "ncit.db").write_bytes(b"older database")
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"newer database, other size"))
    assert gunzip_beside(tmp_path / "ncit.db").read_bytes() == b"newer database, other size"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db", "ncit.db.gz"]


def test_a_first_copy_published_by_another_writer_is_kept(tmp_path, monkeypatch):
    """Two first unpackers: the second keeps the first copy instead of replacing its inode (#1537)."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    real_link = atomic_io.os.link

    def other_writer_first(source, destination):
        """Publish another writer's copy just before this one links its own."""
        Path(destination).write_bytes(b"the other writer's copy")
        return real_link(source, destination)

    monkeypatch.setattr(atomic_io.os, "link", other_writer_first)
    gunzip_beside(tmp_path / "ncit.db")
    assert (tmp_path / "ncit.db").read_bytes() == b"the other writer's copy"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db", "ncit.db.gz"]


def test_a_truncated_archive_names_itself_and_leaves_no_file(tmp_path):
    """A truncated download is refused with the archive's path, not a bare EOFError (#1535)."""
    archive = gzip.compress(b"sqlite bytes" * 100)
    (tmp_path / "ncit.db.gz").write_bytes(archive[:-12] + archive[-4:])
    with pytest.raises(ValueError, match="Cannot unpack .*ncit.db.gz"):
        gunzip_beside(tmp_path / "ncit.db")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db.gz"]


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
