"""
Guard the asymmetric-row machinery against the two ways it can rot (#822).

`predicate_semantics` (#829) settled *how* the flip happens: the mapping set
declares which convention it was built under, absence means legacy, and either
repo can land its half first. `tests/test_sssom_predicate_semantics.py` covers
that mechanism from both directions.

What it does not cover is the vendored file itself. Two failure modes survive:

  1. MIM re-emits as `broadMatch` **without** adding the declaration. The
     declaration is what carries the signal, so an undeclared flip is read as
     legacy and inverts every asymmetric row silently — no dangling nodes, no
     bad categories, nothing a structural check catches.
  2. The asymmetric rows disappear entirely, leaving the direction machinery as
     dead code that nobody notices is dead.

Both are properties of the data, not the code, so they need a data test.
"""

import csv
from pathlib import Path
from unittest import TestCase

REPO_ROOT = Path(__file__).resolve().parents[1]
SSSOM = REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"


def _predicate_counts():
    """
    Count asymmetric predicates in the vendored MIM set.

    :return: ``{predicate: n}`` for narrowMatch and broadMatch.
    """
    counts = {"skos:narrowMatch": 0, "skos:broadMatch": 0}
    with SSSOM.open(encoding="utf-8") as handle:
        rows = [line for line in handle if not line.startswith("#")]
    for row in csv.DictReader(rows, delimiter="\t"):
        predicate = (row.get("predicate_id") or "").strip()
        if predicate in counts:
            counts[predicate] += 1
    return counts


class VendoredSetShapeTest(TestCase):
    """The declaration only helps if the file's shape matches what it declares."""

    def setUp(self):
        """Skip where the vendored set is absent, as on a fresh checkout."""
        if not SSSOM.is_file():
            self.skipTest("vendored MIM SSSOM not present")
        self.counts = _predicate_counts()

    def test_the_asymmetric_rows_have_not_vanished(self):
        """
        Keep the direction machinery from becoming dead code unnoticed.

        `read_predicate_semantics`, the two indexing branches and the
        consolidator pass-through all exist to serve these rows. If MIM stopped
        emitting them, every one of those paths would keep passing its unit
        tests while doing nothing at all.
        """
        total = self.counts["skos:narrowMatch"] + self.counts["skos:broadMatch"]
        self.assertGreater(total, 0, "no asymmetric rows in the vendored set — is the direction code still needed?")

    def test_an_undeclared_flip_to_broad_match_is_caught(self):
        """
        The one flip the declaration cannot protect against.

        #829 makes a *declared* flip safe: the file says ``predicate_semantics:
        "skos"`` and the reader switches with it. But if MIM re-emits as
        ``broadMatch`` and forgets the header, absence means legacy, the reader
        keeps the old orientation, and 141 subclass edges invert into a graph
        that still looks entirely plausible.

        Predominantly-narrowMatch-and-undeclared is the expected state;
        predominantly-broadMatch-and-undeclared is the alarm. A declared set
        skips, because then the reader knows what it is holding and the shape
        no longer has to be inferred.
        """
        from kg_microbe.utils.chemical_mapping_utils import read_predicate_semantics

        if read_predicate_semantics(SSSOM):
            self.skipTest("the set declares its semantics, so the reader cannot be fooled by its shape")
        self.assertGreaterEqual(
            self.counts["skos:narrowMatch"],
            self.counts["skos:broadMatch"],
            "The undeclared set has flipped to spec-conformant broadMatch "
            f"({self.counts['skos:broadMatch']} broadMatch vs "
            f"{self.counts['skos:narrowMatch']} narrowMatch). Absence of `predicate_semantics` "
            "means legacy, so the reader keeps the old orientation and inverts ~141 subclass "
            "edges silently. MIM must add the header in the same release. See #822 and #829.",
        )
