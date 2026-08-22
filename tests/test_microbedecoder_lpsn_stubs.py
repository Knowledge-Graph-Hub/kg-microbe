"""Stubs for LPSN ids the lpsn transform cannot supply (#811)."""

import csv
import io
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.constants import NCBI_CATEGORY
from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform


def _transform(tmp, supplied=("lpsn:797965",)):
    """Build a transform whose sibling lpsn output contains `supplied`."""
    out = Path(tmp) / "transformed"
    (out / "lpsn").mkdir(parents=True)
    (out / "microbedecoder").mkdir(parents=True)
    with (out / "lpsn" / "nodes.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["id", "category", "name"])
        for curie in supplied:
            w.writerow([curie, NCBI_CATEGORY, "Supplied name"])
    return MicrobeDecoderTransform(output_dir=out)


def _row(genus="Alborzia", species="kermanshahica", subsp="NA"):
    """Build a crosswalk row with naming columns."""
    return {"LPSN_Genus": genus, "LPSN_Species": species, "LPSN_Subspecies": subsp}


class LpsnStubTest(TestCase):
    """Emit a node only where lpsn cannot, and name it from the crosswalk."""

    def setUp(self):
        """Create a scratch output tree."""
        import tempfile

        self.tmp = tempfile.mkdtemp()

    def test_an_id_the_lpsn_transform_supplies_is_not_stubbed(self):
        """
        The original design rule still holds for the 34,301 ICNP names.

        Stubbing those would create shallow duplicates the merge has to dedup.
        """
        t = _transform(self.tmp)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied("lpsn:797965", _row(), csv.writer(buf, delimiter="\t"))
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(t._stats["lpsn_stubbed"], 0)

    def test_an_id_lpsn_cannot_supply_is_stubbed_with_a_real_name(self):
        """
        The 5,242 botanical-code cyanobacteria are absent from lpsn_gss.csv.

        They reached the merged graph as untyped `biolink:NamedThing`, which is
        what produced 21,196 `capable_of` domain violations.
        """
        t = _transform(self.tmp)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied("lpsn:7222", _row(), csv.writer(buf, delimiter="\t"))
        written = buf.getvalue().split("\t")
        self.assertEqual(written[0], "lpsn:7222")
        self.assertEqual(written[1], NCBI_CATEGORY)
        self.assertIn("Alborzia kermanshahica", buf.getvalue())

    def test_the_na_marker_is_not_treated_as_a_name_component(self):
        """`NA` is the crosswalk's empty cell, not a subspecies epithet."""
        t = _transform(self.tmp)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied("lpsn:7222", _row(subsp="NA"), csv.writer(buf, delimiter="\t"))
        self.assertNotIn("NA", buf.getvalue().split("\t")[2])

    def test_a_subspecies_is_included_when_present(self):
        """Real subspecies epithets must survive the NA filtering."""
        t = _transform(self.tmp)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied("lpsn:7222", _row(subsp="somesubsp"), csv.writer(buf, delimiter="\t"))
        self.assertIn("Alborzia kermanshahica somesubsp", buf.getvalue())

    def test_each_id_is_stubbed_once_however_many_rows_reference_it(self):
        """The crosswalk is per-strain, so one taxon appears on many rows."""
        t = _transform(self.tmp)
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t")
        for _ in range(4):
            t._emit_lpsn_stub_if_unsupplied("lpsn:7222", _row(), writer)
        self.assertEqual(len(buf.getvalue().strip().splitlines()), 1)
        self.assertEqual(t._stats["lpsn_stubbed"], 1)

    def test_an_unnamed_row_is_counted_rather_than_stubbed_blank(self):
        """A node with no label is no better than the phantom it replaces."""
        t = _transform(self.tmp)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied(
            "lpsn:7222", _row(genus="", species="", subsp="NA"), csv.writer(buf, delimiter="\t")
        )
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(t._stats["lpsn_stub_unnamed"], 1)

    def test_a_missing_lpsn_output_emits_nothing_rather_than_inventing_nodes(self):
        """
        Lpsn may not have run, and its GSS input is account-gated.

        Under-reporting is the safe failure: stubbing everything would mint
        34,301 duplicate taxa.
        """
        import tempfile

        out = Path(tempfile.mkdtemp()) / "transformed"
        (out / "microbedecoder").mkdir(parents=True)
        t = MicrobeDecoderTransform(output_dir=out)
        buf = io.StringIO()
        t._emit_lpsn_stub_if_unsupplied("lpsn:7222", _row(), csv.writer(buf, delimiter="\t"))
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(t._stats["lpsn_stubbed"], 0)
