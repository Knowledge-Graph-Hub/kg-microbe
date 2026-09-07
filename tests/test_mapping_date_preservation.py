"""The exporter must carry each row's published date forward (#953, #960)."""

import gzip
import importlib.util
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"

_spec = importlib.util.spec_from_file_location("consolidate_chemical_mappings", SCRIPT)
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)

#: One chemical is enough: it yields an xref row, a canonical-name row and a
#: synonym row, which is every shape the ``_row`` closure emits.
WATER = {
    "canonical_name": "water",
    "formula": "H2O",
    "category": "biolink:ChemicalEntity",
    "sources": {"test"},
    "xrefs": {"cas:7732-18-5"},
    "synonyms": {"dihydrogen oxide"},
}

XREF_TRIPLE = ("cas:7732-18-5", "skos:exactMatch", "CHEBI:15377")


def _consolidator():
    """
    Build a consolidator holding one chemical and nothing else.

    :return: A ``ChemicalMappingConsolidator`` ready to export.
    """
    consolidator = ccm.ChemicalMappingConsolidator()
    consolidator.chemicals = {"CHEBI:15377": dict(WATER)}
    return consolidator


def _write_prior(path, triple, mapping_date):
    """
    Write a one-row published set for the exporter to read dates from.

    :param path: Destination ``.gz`` path.
    :param triple: ``(subject, predicate, object)``.
    :param mapping_date: The date to record.
    :return: None.
    """
    with ccm.open_deterministic_gzip(path) as handle:
        handle.write("# curie_map:\n")
        handle.write("subject_id\tpredicate_id\tobject_id\tmapping_date\n")
        handle.write("\t".join([*triple, mapping_date]) + "\n")


def _rows(path):
    """
    Read a written set back as dicts.

    :param path: The exported ``.gz``.
    :return: List of row dicts.
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    header = lines[0].rstrip("\n").split("\t")
    return [dict(zip(header, line.rstrip("\n").split("\t"), strict=False)) for line in lines[1:]]


def _header(path, key):
    """
    Read one header comment value.

    :param path: The exported ``.gz``.
    :param key: Header key, e.g. ``mapping_set_version``.
    :return: The value, or ``""``.
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            if line.startswith(f"# {key}:"):
                return line.split(":", 1)[1].strip().strip('"')
    return ""


class MappingDatePreservationTests(unittest.TestCase):
    """Restamping every row is what made the artifact churn; prove it stopped."""

    def test_an_existing_triple_keeps_its_published_date(self):
        """
        The join the unit tests could not reach.

        `published_mapping_dates` being correct proves nothing if the exporter
        never calls it -- the lookups could be deleted and every other test in
        this suite would still pass (#960).
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            prior, out = Path(td) / "prior.sssom.tsv.gz", Path(td) / "out.sssom.tsv.gz"
            _write_prior(prior, XREF_TRIPLE, "2019-01-01")
            _consolidator().export_unified_sssom(out, published_path=prior)
            carried = [
                row for row in _rows(out) if (row["subject_id"], row["predicate_id"], row["object_id"]) == XREF_TRIPLE
            ]
            self.assertEqual(len(carried), 1)
            self.assertEqual(carried[0]["mapping_date"], "2019-01-01")

    def test_a_new_triple_gets_today(self):
        """A row with no published date is genuinely new and dates from now."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            prior, out = Path(td) / "prior.sssom.tsv.gz", Path(td) / "out.sssom.tsv.gz"
            _write_prior(prior, XREF_TRIPLE, "2019-01-01")
            _consolidator().export_unified_sssom(out, published_path=prior)
            fresh = [
                row for row in _rows(out) if (row["subject_id"], row["predicate_id"], row["object_id"]) != XREF_TRIPLE
            ]
            self.assertTrue(fresh)
            for row in fresh:
                self.assertEqual(row["mapping_date"], date.today().isoformat())

    def test_no_published_set_dates_everything_today(self):
        """A first run has nothing to preserve, and must not fail looking."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.sssom.tsv.gz"
            _consolidator().export_unified_sssom(out, published_path=Path(td) / "absent.gz")
            for row in _rows(out):
                self.assertEqual(row["mapping_date"], date.today().isoformat())

    def test_set_version_is_the_newest_row_date_not_the_clock(self):
        """
        A set version should move when the data does, not when the exporter runs.

        Checked with a *future* date so a passing clock cannot fake it.
        """
        import tempfile

        future = "2099-12-31"
        with tempfile.TemporaryDirectory() as td:
            prior, out = Path(td) / "prior.sssom.tsv.gz", Path(td) / "out.sssom.tsv.gz"
            _write_prior(prior, XREF_TRIPLE, future)
            _consolidator().export_unified_sssom(out, published_path=prior)
            self.assertEqual(_header(out, "mapping_set_version"), future)
            self.assertEqual(_header(out, "mapping_date"), future)

    def test_a_malformed_published_date_is_not_carried_into_the_header(self):
        """
        One bad row must not claim the version for the whole set (#958).

        Any non-digit string sorts above every real date, and the value would be
        preserved on the next run too, so it would keep it.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            prior, out = Path(td) / "prior.sssom.tsv.gz", Path(td) / "out.sssom.tsv.gz"
            _write_prior(prior, XREF_TRIPLE, "not-a-date")
            _consolidator().export_unified_sssom(out, published_path=prior)
            self.assertEqual(_header(out, "mapping_set_version"), date.today().isoformat())
            for row in _rows(out):
                self.assertEqual(row["mapping_date"], date.today().isoformat())

    def test_the_same_inputs_export_identical_bytes(self):
        """The whole point of #953, exercised through the exporter itself."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            prior = Path(td) / "prior.sssom.tsv.gz"
            _write_prior(prior, XREF_TRIPLE, "2019-01-01")
            first, second = Path(td) / "a.sssom.tsv.gz", Path(td) / "b.sssom.tsv.gz"
            _consolidator().export_unified_sssom(first, published_path=prior)
            _consolidator().export_unified_sssom(second, published_path=prior)
            self.assertEqual(first.read_bytes(), second.read_bytes())


class ProvenanceHeaderTests(unittest.TestCase):
    """Provenance must name the code that ran, not the commit it sat on (#961)."""

    TOOL = "kg-microbe/scripts/consolidate_chemical_mappings.py"

    @staticmethod
    def _export(directory):
        """
        Export the one-chemical set and return the path written.

        :param directory: Directory to write into.
        :return: The exported ``.gz`` path.
        """
        out = Path(directory) / "out.sssom.tsv.gz"
        _consolidator().export_unified_sssom(out)
        return out

    def test_the_tool_version_survives_an_export_outside_the_repository(self):
        """
        --dry-run exports to a temp dir, where the old lookup wrote "unknown".

        The provenance of the script has nothing to do with where its output
        lands, so resolving it from the output path made the preview differ
        from the apply in a header line no mapping had touched.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out = self._export(td)
            self.assertEqual(_header(out, "mapping_tool"), self.TOOL)
            self.assertNotEqual(_header(out, "mapping_tool_version"), "unknown")

    def test_the_version_is_the_hash_of_the_script_that_ran(self):
        """
        The claim has to be checkable against the file, or it is decoration.

        A commit SHA is not: the run precedes the commit that carries its
        output, so the recorded commit's copy of the script can differ from
        the one that produced the artifact.
        """
        import hashlib
        import tempfile

        expected = "sha256:" + hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_header(self._export(td), "mapping_tool_version"), expected)

    def test_the_version_is_not_a_git_commit(self):
        """
        Guard against a well-meaning revert to `rev-parse HEAD`.

        A bare 40-hex value is exactly what the old code wrote, and it reads
        as provenance while being unverifiable against anything on disk.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            self.assertNotRegex(_header(self._export(td), "mapping_tool_version"), r"^[0-9a-f]{40}$")

    def test_the_tool_name_does_not_carry_the_version(self):
        """
        `mapping_tool` and `mapping_tool_version` are separate SSSOM slots.

        Packing the version into the name made a spec-aware reader see a tool
        called "...py@sha256:..." (#971).
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            self.assertNotIn("@", _header(self._export(td), "mapping_tool"))

    def test_editing_the_script_changes_the_fingerprint(self):
        """One byte of behaviour change must not leave the identifier alone."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            first, second = Path(td) / "a.py", Path(td) / "b.py"
            first.write_text("print('one')\n", encoding="utf-8")
            second.write_text("print('two')\n", encoding="utf-8")
            self.assertNotEqual(ccm.script_fingerprint(first), ccm.script_fingerprint(second))

    def test_identical_scripts_at_different_paths_agree(self):
        """
        The identifier is the content, so a copy of the script is the same tool.

        This is the property a commit SHA lacked: it moved with the checkout,
        not with the code.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            first, second = Path(td) / "here.py", Path(td) / "elsewhere.py"
            first.write_text("print('same')\n", encoding="utf-8")
            second.write_text("print('same')\n", encoding="utf-8")
            self.assertEqual(ccm.script_fingerprint(first), ccm.script_fingerprint(second))

    def test_a_missing_script_reports_unknown_out_loud(self):
        """
        An export must not die because provenance could not be computed.

        It must not fall silent either: the only other evidence is a header
        line inside a 13 MB gzip (#975).
        """
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                fingerprint = ccm.script_fingerprint(Path(td) / "absent.py")
            self.assertEqual(fingerprint, "unknown")
            self.assertIn("absent.py", said.getvalue())


if __name__ == "__main__":
    unittest.main()
