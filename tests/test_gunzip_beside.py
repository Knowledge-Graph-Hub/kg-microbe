"""Gzipped raw authorities are unpacked atomically by the first reader that finds them missing (#1526)."""

import gzip
import os
import time

import pytest

from kg_microbe.utils import atomic_io
from kg_microbe.utils.atomic_io import gunzip_beside


def test_only_the_archive_present_is_unpacked_beside_it(tmp_path):
    """The uncompressed file appears next to its archive with the archive's content."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    assert gunzip_beside(tmp_path / "ncit.db", root=tmp_path).read_bytes() == b"sqlite bytes"


def test_an_existing_file_is_never_replaced(tmp_path):
    """
    Not by a newer archive, and not by a damaged one (#1536, #1545, #1547).

    The release preflight reports a database that is not its archive's copy, so the
    user chooses; replacing it here could put an older archive's copy over a newer
    database, or fail a run late over an archive it did not need.
    """
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"a newer database, of another size"))
    (tmp_path / "ncit.db").write_bytes(b"existing")
    before = (tmp_path / "ncit.db").stat()
    assert gunzip_beside(tmp_path / "ncit.db").read_bytes() == b"existing"
    (tmp_path / "ncit.db.gz").write_bytes(b"\x1f\x8b truncated")
    assert gunzip_beside(tmp_path / "ncit.db").read_bytes() == b"existing"
    after = (tmp_path / "ncit.db").stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_a_truncated_archive_names_itself_and_leaves_no_file(tmp_path):
    """A truncated download is refused with the archive's path, not a bare EOFError (#1535)."""
    archive = gzip.compress(b"sqlite bytes" * 100)
    (tmp_path / "ncit.db.gz").write_bytes(archive[:-12] + archive[-4:])
    with pytest.raises(ValueError, match="Cannot unpack .*ncit.db.gz"):
        gunzip_beside(tmp_path / "ncit.db")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db.gz"]


@pytest.mark.parametrize("archive", [b"", gzip.compress(b"")], ids=["zero-byte", "empty-member"])
def test_an_archive_that_unpacks_to_nothing_publishes_nothing(tmp_path, archive):
    """An empty database would fail hours later with a SQLite error that names no file (#1544)."""
    (tmp_path / "ncit.db.gz").write_bytes(archive)
    with pytest.raises(ValueError, match="ncit.db.gz unpacks to nothing"):
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


def test_a_symlink_loop_is_refused_by_name(tmp_path):
    """Resolving a loop raises RuntimeError; it is refused as a ValueError naming the path (#1550)."""
    (tmp_path / "ncit.db.gz").symlink_to(tmp_path / "loop.gz")
    (tmp_path / "loop.gz").symlink_to(tmp_path / "ncit.db.gz")
    with pytest.raises(ValueError, match="Cannot resolve .*ncit.db.gz"):
        gunzip_beside(tmp_path / "ncit.db", root=tmp_path)


def test_a_dangling_link_in_place_of_the_file_is_replaced(tmp_path):
    """The unpacked file replaces the link; nothing is written through it (#1550)."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    (tmp_path / "ncit.db").symlink_to(tmp_path / "gone.db")
    gunzip_beside(tmp_path / "ncit.db", root=tmp_path)
    assert not (tmp_path / "ncit.db").is_symlink()
    assert (tmp_path / "ncit.db").read_bytes() == b"sqlite bytes"
    assert not (tmp_path / "gone.db").exists()


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


def test_a_killed_unpack_does_not_strand_its_partial_file(tmp_path):
    """A partial left by a process that died a day ago is swept by the next unpack (#1546)."""
    (tmp_path / "ncit.db.gz").write_bytes(gzip.compress(b"sqlite bytes"))
    stranded = tmp_path / "ncit.db.4242.0.partial"
    stranded.write_bytes(b"sql")
    day_old = time.time() - 2 * 24 * 60 * 60
    os.utime(stranded, (day_old, day_old))
    gunzip_beside(tmp_path / "ncit.db")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ncit.db", "ncit.db.gz"]
