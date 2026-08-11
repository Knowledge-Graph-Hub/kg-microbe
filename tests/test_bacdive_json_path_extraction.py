"""Tests for BacDive JSON-path extraction across inconsistent record shapes."""

from unittest import TestCase

from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform

# The same path is a dict on one strain and a list of per-reference dicts on the
# next. Both shapes are real; these are reduced from BacDive documents 98 and 99.
OBJECT_SHAPED = {
    "Morphology": {
        "cell morphology": {
            "@ref": 119306,
            "gram stain": "negative",
            "cell shape": "coccus-shaped",
            "motility": "no",
        }
    }
}
ARRAY_SHAPED = {
    "Morphology": {
        "cell morphology": [
            {"@ref": 22965, "gram stain": "negative", "cell shape": "coccus-shaped", "motility": "no"},
            {"@ref": 67771, "cell shape": "coccus-shaped"},
            {"@ref": 67771, "gram stain": "negative"},
            {"@ref": 120258, "gram stain": "positive", "cell shape": "rod-shaped", "motility": "yes"},
        ]
    }
}


class BacDiveJsonPathExtractionTest(TestCase):

    """`_extract_value_from_json_path` must traverse arrays, not bail on them."""

    def setUp(self):
        """Build a transform without the base __init__ side effects."""
        self.transform = BacDiveTransform.__new__(BacDiveTransform)

    def _extract(self, record, path):
        """Shorthand for the method under test."""
        return self.transform._extract_value_from_json_path(record, path)

    def test_an_intermediate_array_no_longer_drops_everything(self):
        """
        The traversal bailed the moment an intermediate node was a list.

        That silently lost 24,808 of 118,613 record-path combinations (20.9%),
        and 66.9% of halophily alone — the whole point of #474.
        """
        values = self._extract(ARRAY_SHAPED, "Morphology.cell morphology.gram stain")
        self.assertTrue(values, "an array-shaped block must yield values")
        self.assertIn("negative", values)
        self.assertIn("positive", values)

    def test_the_object_shape_is_unchanged(self):
        """The fix must be a strict superset; the dict path is the common case."""
        self.assertEqual(self._extract(OBJECT_SHAPED, "Morphology.cell morphology.gram stain"), ["negative"])
        self.assertEqual(self._extract(OBJECT_SHAPED, "Morphology.cell morphology.cell shape"), ["coccus-shaped"])
        self.assertEqual(self._extract(OBJECT_SHAPED, "Morphology.cell morphology.motility"), ["no"])

    def test_members_lacking_the_key_are_skipped_not_fatal(self):
        """Per-reference entries are partial — most carry only some of the keys."""
        motility = self._extract(ARRAY_SHAPED, "Morphology.cell morphology.motility")
        self.assertEqual(sorted(motility), ["no", "yes"], "only the two entries carrying motility")

    def test_a_missing_path_still_yields_nothing(self):
        """Absent data must stay absent rather than becoming an empty string."""
        self.assertEqual(self._extract(OBJECT_SHAPED, "Morphology.absent.key"), [])
        self.assertEqual(self._extract({}, "Morphology.cell morphology.gram stain"), [])
        self.assertEqual(self._extract(ARRAY_SHAPED, "Morphology.cell morphology.absent"), [])

    def test_a_scalar_leaf_is_returned_as_is(self):
        """Not every routed path ends in a dict."""
        self.assertEqual(self._extract({"a": {"b": "value"}}, "a.b"), ["value"])

    def test_arrays_at_more_than_one_level_fan_out(self):
        """
        Nothing guarantees only one level is array-shaped.

        A cursor-based traversal cannot express this at all; a frontier can.
        """
        record = {"a": [{"b": [{"c": "x"}, {"c": "y"}]}, {"b": {"c": "z"}}]}
        self.assertEqual(sorted(self._extract(record, "a.b.c")), ["x", "y", "z"])

    def test_a_scalar_intermediate_does_not_invent_values(self):
        """
        The frontier must not treat a non-dict member as the requested value.

        `{"a": ["x", "y"]}` asked for `a.b` has no `b` anywhere; returning the
        strings would invent data for a path that does not exist (#739) — a new
        failure mode rather than a leftover of the bug being fixed.
        """
        self.assertEqual(self._extract({"a": ["x", "y"]}, "a.b"), [])
        self.assertEqual(self._extract({"a": [1, 2]}, "a.b"), [])

    def test_nested_lists_are_flattened_not_stringified(self):
        """A list inside a list yielded the repr of the inner list."""
        self.assertEqual(self._extract({"a": [[{"b": "v"}]]}, "a.b"), ["v"])

    def test_a_one_part_path_still_returns_its_scalar(self):
        """The legitimate scalar case must survive the #739 tightening."""
        self.assertEqual(self._extract({"a": "v"}, "a"), ["v"])
