"""The CSV the transform reads is always the pinned zip's copy (#1420, #1518)."""

import zipfile

import pytest

from kg_microbe.transform_utils.microbedecoder import microbedecoder
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform


def _zip(path, payload, *, member="Shiny/MicrobeDecoder/data/database/database.csv"):
    """Write a zip holding one nested database.csv, as the pinned upload does."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, payload)
    return path


def _transform(tmp_path):
    """Build a transform whose raw directory is test-owned."""
    (tmp_path / "raw").mkdir()
    return MicrobeDecoderTransform(tmp_path / "raw", tmp_path / "transformed", chemical_loader=object())


def test_first_use_extracts_the_csv_beside_the_zip(tmp_path):
    """The CSV lands next to the zip, where the policies' readers look for it."""
    transform = _transform(tmp_path)
    archive = _zip(transform.input_base_dir / "microbedecoder_database.zip", b"LPSN_ID\n1\n")
    assert transform._unzip(archive) == archive.parent / "database.csv"
    assert (archive.parent / "database.csv").read_bytes() == b"LPSN_ID\n1\n"


def test_matching_csv_is_reused_untouched(tmp_path):
    """An extraction that is already the zip's copy is not rewritten."""
    transform = _transform(tmp_path)
    archive = _zip(transform.input_base_dir / "microbedecoder_database.zip", b"LPSN_ID\n1\n")
    csv_path = transform._unzip(archive)
    before = csv_path.stat()
    assert transform._unzip(archive) == csv_path
    after = csv_path.stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


@pytest.mark.parametrize("stale", [b"LPSN_ID\n2\n", b"LPSN_ID\n1\n2\n"])
def test_stale_csv_is_replaced_by_the_zip_copy(tmp_path, stale):
    """Re-fetching the pinned zip refreshes an extraction from an older upload."""
    transform = _transform(tmp_path)
    archive = _zip(transform.input_base_dir / "microbedecoder_database.zip", b"LPSN_ID\n1\n")
    (archive.parent / "database.csv").write_bytes(stale)
    assert transform._unzip(archive).read_bytes() == b"LPSN_ID\n1\n"


def test_interrupted_extraction_leaves_the_previous_csv(tmp_path, monkeypatch):
    """A failed copy publishes nothing partial over the existing file."""
    transform = _transform(tmp_path)
    archive = _zip(transform.input_base_dir / "microbedecoder_database.zip", b"LPSN_ID\n1\n")
    (archive.parent / "database.csv").write_bytes(b"LPSN_ID\n2\n")

    def fail(source, destination):
        """Write a fragment, then fail as an interrupted copy would."""
        destination.write(b"LPSN")
        raise OSError("fixture copy failure")

    monkeypatch.setattr(microbedecoder.shutil, "copyfileobj", fail)
    with pytest.raises(OSError, match="copy failure"):
        transform._unzip(archive)
    assert (archive.parent / "database.csv").read_bytes() == b"LPSN_ID\n2\n"
    assert sorted(path.name for path in archive.parent.iterdir()) == ["database.csv", "microbedecoder_database.zip"]
