"""The `predicate_semantics` declaration decouples the two halves of #822."""

import gzip
from pathlib import Path
from unittest import TestCase, mock

from kg_microbe.utils import chemical_mapping_utils as cmu

HEADER = """# curie_map:
#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"
# mapping_set_id: "https://example/test"
# mapping_set_version: "2026-08-18"
"""
COLUMNS = "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\n"
ROW = "MIM:Thing\tThing\tskos:narrowMatch\tCHEBI:1\tparent thing\n"


def _write(tmp, declaration=None, gz=False):
    """Write an SSSOM file, optionally declaring its predicate semantics."""
    text = HEADER
    if declaration is not None:
        text += f'# predicate_semantics: "{declaration}"\n'
    text += COLUMNS + ROW
    path = Path(tmp) / ("m.sssom.tsv.gz" if gz else "m.sssom.tsv")
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


class ReadDeclarationTest(TestCase):

    """Absence means legacy — the property that makes either half land first."""

    def setUp(self):
        """Scratch dir."""
        import tempfile

        self.tmp = tempfile.mkdtemp()

    def test_an_absent_declaration_reads_as_empty(self):
        """
        A file with no declaration is legacy, however new the reader.

        This is what makes a rebuild of unfixed content safe. MIM's
        `mapping_set_version` is build time and bumps on every build, so a date
        threshold would stamp a post-cutover date onto legacy rows and invert
        141 edges that were never corrected.
        """
        self.assertEqual(cmu.read_predicate_semantics(_write(self.tmp)), "")

    def test_a_declaration_is_read(self):
        """The signal travels with the content, not the clock."""
        self.assertEqual(cmu.read_predicate_semantics(_write(self.tmp, "skos")), "skos")

    def test_it_works_on_a_gzipped_set(self):
        """The unified mapping set ships gzipped; the header must still be readable."""
        self.assertEqual(cmu.read_predicate_semantics(_write(self.tmp, "skos", gz=True)), "skos")

    def test_a_missing_file_is_not_an_error(self):
        """An unreadable set must degrade to legacy, not raise mid-load."""
        self.assertEqual(cmu.read_predicate_semantics(Path(self.tmp) / "absent.tsv"), "")

    def test_a_declaration_after_the_data_starts_is_ignored(self):
        """
        Only the header counts.

        A `#`-prefixed line in the body is data, not metadata, and must not be
        able to change how the whole file is read.
        """
        path = Path(self.tmp) / "late.sssom.tsv"
        path.write_text(HEADER + COLUMNS + ROW + '# predicate_semantics: "skos"\n', encoding="utf-8")
        self.assertEqual(cmu.read_predicate_semantics(path), "")


class DirectionTest(TestCase):

    """The same row must index opposite parents under the two declarations."""

    def setUp(self):
        """Scratch dir."""
        import tempfile

        self.tmp = tempfile.mkdtemp()

    def _parents(self, declaration):
        """Load a one-row set and return the parent index."""
        path = _write(self.tmp, declaration)
        with mock.patch.object(cmu, "_PARENT_INDEX", {}, create=False):
            cmu.load_unified_mappings(path)
            return dict(cmu._PARENT_INDEX)

    def test_legacy_treats_the_object_as_the_parent(self):
        """MIM's documented meaning: `MIM:X narrowMatch CHEBI:Y` is "X is a kind-of Y"."""
        parents = self._parents(None)
        self.assertEqual(parents.get("MIM:Thing"), ["CHEBI:1"])

    def test_the_declaration_flips_it_to_the_spec(self):
        """
        Under SKOS, `A narrowMatch B` means B is narrower — so A is the parent.

        This is the branch that activates only once MIM declares the change,
        which is why either repo can land its half first.
        """
        parents = self._parents("skos")
        self.assertEqual(parents.get("CHEBI:1"), ["MIM:Thing"])

    def test_an_unrecognised_value_falls_back_to_legacy(self):
        """
        Fail closed.

        A typo'd or future value must not be read as "flip" — the cost of
        guessing wrong is 141 silently inverted subclass edges.
        """
        parents = self._parents("sk0s")
        self.assertEqual(parents.get("MIM:Thing"), ["CHEBI:1"])
