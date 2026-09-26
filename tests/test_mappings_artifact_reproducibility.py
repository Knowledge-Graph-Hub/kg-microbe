"""The unified mappings artifact must be a pure function of its inputs (#953)."""

import gzip
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"

_spec = importlib.util.spec_from_file_location("consolidate_chemical_mappings", SCRIPT)
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)


def _write_sssom(path: Path, rows, header=("# curie_map:",)):
    """
    Write a minimal SSSOM file, gzipped when the path says so.

    :param path: Destination path.
    :param rows: ``(subject, predicate, object, date)`` tuples.
    :param header: Comment lines to precede the table.
    :return: None.
    """
    columns = ["subject_id", "predicate_id", "object_id", "mapping_date"]
    body = "\n".join(list(header) + ["\t".join(columns)] + ["\t".join(r) for r in rows]) + "\n"
    if str(path).endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        path.write_text(body, encoding="utf-8")


class PublishedMappingDatesTests(unittest.TestCase):
    """A row's date belongs to the assertion, so it has to be readable back."""

    def test_reads_dates_keyed_on_the_triple(self):
        """The triple is the identity; other columns may change without a new date."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sssom.tsv"
            _write_sssom(path, [("A:1", "skos:exactMatch", "B:1", "2026-01-02")])
            self.assertEqual(
                ccm.published_mapping_dates(path),
                {("A:1", "skos:exactMatch", "B:1"): "2026-01-02"},
            )

    def test_reads_gzipped_sets(self):
        """The published artifact is gzipped, so that is the path that matters."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sssom.tsv.gz"
            _write_sssom(path, [("A:1", "skos:closeMatch", "B:1", "2026-03-04")])
            self.assertEqual(ccm.published_mapping_dates(path)[("A:1", "skos:closeMatch", "B:1")], "2026-03-04")

    def test_absent_file_is_not_an_error(self):
        """A first run has nothing to read; every row is genuinely new."""
        self.assertEqual(ccm.published_mapping_dates(Path("/nonexistent/m.sssom.tsv.gz")), {})

    def test_blank_dates_are_skipped_rather_than_recorded_as_empty(self):
        """An empty date must fall back to today, not pin the row to ''."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sssom.tsv"
            _write_sssom(path, [("A:1", "skos:exactMatch", "B:1", "")])
            self.assertEqual(ccm.published_mapping_dates(path), {})

    def test_unreadable_file_degrades_instead_of_failing_the_refresh(self):
        """
        A corrupt previous artifact must not block publishing a new one.

        The fallback is today's date on every row -- the pre-#953 behaviour --
        which is worse output, not a failed run.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.sssom.tsv.gz"
            path.write_bytes(b"this is not gzip")
            self.assertEqual(ccm.published_mapping_dates(path), {})


class ArchiveDeterminismTests(unittest.TestCase):
    """Identical content must compress to identical bytes."""

    @staticmethod
    def _write(path, text):
        with ccm.open_deterministic_gzip(path) as fh:
            fh.write(text)

    def test_identical_content_gives_identical_bytes(self):
        """The property the issue asks for, stated directly."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.gz", Path(td) / "b.gz"
            self._write(a, "subject\tobject\nA:1\tB:1\n")
            self._write(b, "subject\tobject\nA:1\tB:1\n")
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_the_output_path_does_not_leak_into_the_archive(self):
        """
        ``GzipFile(path, ...)`` stores the filename in the header.

        --dry-run exports to a scratch path and compares against the published
        one, so a path-dependent archive would make the preview disagree with
        the apply for reasons that have nothing to do with the mappings.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            scratch, published = Path(td) / "scratch.sssom.tsv.gz", Path(td) / "published.sssom.tsv.gz"
            self._write(scratch, "x\n")
            self._write(published, "x\n")
            self.assertEqual(scratch.read_bytes(), published.read_bytes())

    def test_the_stdlib_default_is_what_made_it_churn(self):
        """Guards the reason for the change: the default writer embeds the clock."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pinned, wall = Path(td) / "p.gz", Path(td) / "w.gz"
            self._write(pinned, "x\n")
            with gzip.open(wall, "wt", encoding="utf-8") as fh:
                fh.write("x\n")
            self.assertEqual(pinned.read_bytes()[4:8], b"\x00\x00\x00\x00")
            self.assertNotEqual(wall.read_bytes()[4:8], b"\x00\x00\x00\x00")

    def test_the_stream_round_trips(self):
        """A deterministic archive still has to be a readable one."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.gz"
            self._write(path, "hello\nworld\n")
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "hello\nworld\n")

    def test_the_shipped_artifact_has_a_pinned_mtime(self):
        """The committed artifact itself must satisfy the property, not just the writer."""
        artifact = REPO_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
        if not artifact.is_file():
            self.skipTest("unified mappings artifact not present")
        self.assertEqual(
            artifact.read_bytes()[4:8],
            b"\x00\x00\x00\x00",
            "gzip header carries a wall-clock mtime; regenerate with the #953 writer",
        )


if __name__ == "__main__":
    unittest.main()
