"""
Tests that Drive-hosted MetaTraits inputs survive arriving decompressed.

Google Drive silently serves some uploads decompressed, so a file named `*.gz`
can be plain text. This already happened to `ncbi_*_summary.jsonl.gz`, which sit
in `data/raw` as plain JSON under a `.gz` name. Any read of a Drive-hosted input
must tolerate both forms.
"""

import gzip

from kg_microbe.transform_utils.metatraits import io as mt_io
from kg_microbe.transform_utils.metatraits import metatraits as mt

CROSSWALK_HEADER = "taxonID NCBI\ttaxonID GTDB\tspecies (NCBI)\tgenus (GTDB)\tspecies (GTDB)\n"
CROSSWALK_ROW = "562\t599451526\tEscherichia coli\tEscherichia\tEscherichia coli\n"


def _write_gzipped(path, text):
    """Write real gzip-compressed text."""
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)


def _write_plain(path, text):
    """Write plain text under whatever name the caller chose (e.g. a .gz name)."""
    path.write_text(text, encoding="utf-8")


class TestOpenMaybeGzipped:

    """_open_maybe_gzipped must read both real gzip and misnamed plain text."""

    def test_reads_real_gzip(self, tmp_path):
        """A genuinely compressed .gz still works."""
        path = tmp_path / "sample.tsv.gz"
        _write_gzipped(path, "hello\n")
        with mt_io.open_maybe_gzipped(path) as f:
            assert f.read() == "hello\n"

    def test_reads_plain_text_named_gz(self, tmp_path):
        """A .gz that Drive decompressed must not raise BadGzipFile."""
        path = tmp_path / "sample.tsv.gz"
        _write_plain(path, "hello\n")
        with mt_io.open_maybe_gzipped(path) as f:
            assert f.read() == "hello\n"

    def test_reads_uncompressed_name(self, tmp_path):
        """A file with no .gz suffix opens as plain text."""
        path = tmp_path / "sample.tsv"
        _write_plain(path, "hello\n")
        with mt_io.open_maybe_gzipped(path) as f:
            assert f.read() == "hello\n"

    def test_open_jsonl_delegates(self, tmp_path):
        """_open_jsonl keeps its tolerant behaviour after the refactor."""
        path = tmp_path / "sample.jsonl.gz"
        _write_plain(path, '{"tax_name": "x"}\n')
        with mt_io.open_jsonl(path) as f:
            assert "tax_name" in f.read()

    @staticmethod
    def _track_probes(monkeypatch):
        """Wrap gzip.open so a test can see whether probe handles get closed."""
        opened = []
        real_gzip_open = mt_io.gzip.open

        def tracking_open(*args, **kwargs):
            """Record every handle gzip.open hands out."""
            handle = real_gzip_open(*args, **kwargs)
            opened.append(handle)
            return handle

        monkeypatch.setattr(mt_io.gzip, "open", tracking_open)
        return opened

    def test_probe_handle_is_closed_on_fallback(self, tmp_path, monkeypatch):
        """The failed gzip probe must not leak its handle (#621)."""
        path = tmp_path / "sample.tsv.gz"
        _write_plain(path, "hello\n")
        opened = self._track_probes(monkeypatch)

        with mt_io.open_maybe_gzipped(path) as f:
            assert f.read() == "hello\n"

        assert len(opened) == 1, "the gzip probe should have run once"
        assert opened[0].closed, "the probe handle must be closed before falling back"

    def test_probe_handle_is_closed_for_a_header_truncated_gz(self, tmp_path, monkeypatch):
        """
        A .gz truncated inside its header raises EOFError, not BadGzipFile (#629).

        The original close() only ran on BadGzipFile, so this realistic
        partial-download shape leaked the handle — silently, since callers wrap
        the read in `except Exception`.
        """
        real = tmp_path / "real.gz"
        _write_gzipped(real, "hello\n")
        path = tmp_path / "sample.tsv.gz"
        path.write_bytes(real.read_bytes()[:5])  # cut inside the 10-byte header
        opened = self._track_probes(monkeypatch)

        handle = mt_io.open_maybe_gzipped(path)
        handle.close()

        assert opened, "the probe should have opened a handle"
        assert all(h.closed for h in opened), "every probe handle must be closed"

    def test_probe_handle_is_closed_for_undecodable_content(self, tmp_path, monkeypatch):
        """A payload that is gzip but not UTF-8 raises UnicodeDecodeError (#629)."""
        path = tmp_path / "sample.tsv.gz"
        with gzip.open(path, "wb") as f:
            f.write(b"\xff\xfe\x00binary\x80\x81")
        opened = self._track_probes(monkeypatch)

        handle = mt_io.open_maybe_gzipped(path)
        handle.close()

        assert opened
        assert all(h.closed for h in opened), "every probe handle must be closed"


class TestCrosswalkLoading:

    """
    NCBI2GTDB.tsv.gz must load whether or not it arrives compressed.

    _load_ncbi_gtdb_mappings wraps its read in `except Exception`, so a
    BadGzipFile there does not crash the transform — it silently produces zero
    mappings and the NCBI->GTDB fallback quietly stops working. That silent
    degradation is the regression these tests guard.
    """

    def _load_from(self, tmp_path, monkeypatch, writer):
        """Point the loader at a temp NCBI2GTDB file written by `writer`."""
        writer(tmp_path / "NCBI2GTDB.tsv.gz", CROSSWALK_HEADER + CROSSWALK_ROW)
        monkeypatch.setattr(mt, "RAW_DATA_DIR", tmp_path)
        transform = mt.MetaTraitsTransform.__new__(mt.MetaTraitsTransform)
        return transform._load_ncbi_gtdb_mappings()

    def test_loads_from_real_gzip(self, tmp_path, monkeypatch):
        """The normal case: a properly compressed crosswalk."""
        mappings = self._load_from(tmp_path, monkeypatch, _write_gzipped)
        assert mappings["escherichia coli"]["gtdb_genus"] == "Escherichia"

    def test_loads_from_decompressed_gz(self, tmp_path, monkeypatch):
        """The Drive case: same content, not actually compressed."""
        mappings = self._load_from(tmp_path, monkeypatch, _write_plain)
        assert mappings["escherichia coli"]["gtdb_genus"] == "Escherichia", (
            "a decompressed .gz must still yield mappings, not silently zero"
        )

    def test_garbage_payload_is_reported_not_announced_as_success(self, tmp_path, monkeypatch, capsys):
        """
        A non-gzip error page must not print the success line (F6).

        Tolerating a decompressed .gz is right for the Drive-hosted inputs, but it
        also means an HTML quota interstitial reads as an empty table. Master's
        bare gzip.open at least raised BadGzipFile here; the tolerant reader has
        to say something instead of "Loaded 0 ... mappings".
        """
        (tmp_path / "NCBI2GTDB.tsv.gz").write_text("<html><body>Quota exceeded</body></html>", encoding="utf-8")
        monkeypatch.setattr(mt, "RAW_DATA_DIR", tmp_path)
        transform = mt.MetaTraitsTransform.__new__(mt.MetaTraitsTransform)

        assert transform._load_ncbi_gtdb_mappings() == {}
        out = capsys.readouterr().out
        assert "Warning" in out, "an unusable crosswalk must warn"
        assert "no usable rows" in out or "no NCBI to GTDB mappings" in out

    def test_empty_file_is_reported(self, tmp_path, monkeypatch, capsys):
        """A 0-byte download is the other realistic gdrive failure mode."""
        (tmp_path / "NCBI2GTDB.tsv.gz").write_bytes(b"")
        monkeypatch.setattr(mt, "RAW_DATA_DIR", tmp_path)
        transform = mt.MetaTraitsTransform.__new__(mt.MetaTraitsTransform)

        assert transform._load_ncbi_gtdb_mappings() == {}
        assert "Warning" in capsys.readouterr().out

    def test_partial_read_reports_how_much_loaded(self, tmp_path, monkeypatch, capsys):
        """A truncated body yields a partial crosswalk; the count must be stated."""
        import gzip as gz

        path = tmp_path / "NCBI2GTDB.tsv.gz"
        rows = "".join(f"{i}\t{i}\tSpecies {i}\tGenus{i}\tSpecies {i}\n" for i in range(2000))
        with gz.open(path, "wt", encoding="utf-8") as f:
            f.write(CROSSWALK_HEADER + rows)
        path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])  # truncate body

        monkeypatch.setattr(mt, "RAW_DATA_DIR", tmp_path)
        transform = mt.MetaTraitsTransform.__new__(mt.MetaTraitsTransform)
        mappings = transform._load_ncbi_gtdb_mappings()

        out = capsys.readouterr().out
        assert "Could not fully load" in out
        assert f"{len(mappings)} mappings loaded" in out

    def test_missing_file_yields_empty_mapping(self, tmp_path, monkeypatch):
        """An absent crosswalk is tolerated (pre-existing behaviour)."""
        monkeypatch.setattr(mt, "RAW_DATA_DIR", tmp_path)
        transform = mt.MetaTraitsTransform.__new__(mt.MetaTraitsTransform)
        assert transform._load_ncbi_gtdb_mappings() == {}
