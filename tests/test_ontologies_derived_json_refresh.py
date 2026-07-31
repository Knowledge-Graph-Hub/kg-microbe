"""Tests that a refreshed compressed ontology does not leave a stale derived JSON."""

import gzip
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

_OWL = (
    '<?xml version="1.0"?>\n<owl:Ontology>'
    '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/ncbitaxon/{d}/ncbitaxon.owl"/>'
    "</owl:Ontology>\n"
)
_JSON = '{{"meta":{{"basicPropertyValues":[{{"pred":"versionInfo","val":"{d}"}}]}}}}'


class DerivedJsonRefreshTest(TestCase):

    """`kg download` refreshes <x>.owl.gz in place; the derived JSON must follow."""

    def setUp(self):
        """Instantiate the transform without base __init__ side effects."""
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def _fixture(self, tmp, owl_release, json_release):
        """Write an archive and a derived JSON at the given releases."""
        archive = Path(tmp) / "ncbitaxon.owl.gz"
        with gzip.open(archive, "wt", encoding="utf-8") as handle:
            handle.write(_OWL.format(d=owl_release))
        derived = Path(tmp) / "ncbitaxon_removed_subset.json"
        derived.write_text(_JSON.format(d=json_release), encoding="utf-8")
        return archive, derived

    def test_a_stale_derived_json_is_removed(self):
        """
        The regeneration guard is `is_file()`, and ROBOT no-ops on an existing target.

        So the transform emitted nodes from the previous release while the SemSQL
        builders — which do read the refreshed archive — rebuilt from the new one.
        Nothing caught it: the version gates compare the DB against the OWL, never
        against the JSON that is consumed.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archive, derived = self._fixture(tmp, "2026-07-12", "2026-01-01")
            plain = Path(tmp) / "ncbitaxon.owl"
            plain.write_text(_OWL.format(d="2026-01-01"), encoding="utf-8")

            self.transform._drop_stale_derived_json(archive, derived)

            self.assertFalse(derived.exists(), "the stale JSON must be removed so ROBOT re-runs")
            # The plain OWL is left alone: `decompress` runs whenever the JSON is
            # absent and republishes it atomically, so deleting it here bought
            # nothing and could destroy the only good copy.
            self.assertTrue(plain.exists())
            self.transform.decompress(archive)
            self.assertEqual(plain.read_text(encoding="utf-8"), _OWL.format(d="2026-07-12"), "and is refreshed")

    def test_a_current_derived_json_is_kept(self):
        """Regenerating an up-to-date JSON would re-run a very expensive conversion."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archive, derived = self._fixture(tmp, "2026-07-12", "2026-07-12")
            plain = Path(tmp) / "ncbitaxon.owl"
            plain.write_text(_OWL.format(d="2026-07-12"), encoding="utf-8")

            self.transform._drop_stale_derived_json(archive, derived)

            self.assertTrue(derived.exists())
            self.assertTrue(plain.exists())

    def test_decompression_leaves_no_truncated_owl(self):
        """
        Writing straight to the real filename left a truncated OWL there.

        A truncated OWL is not detectable downstream — its version stamp lives in
        the head and still parses — so both ROBOT and the SemSQL build would
        accept it.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ncbitaxon.owl.gz"
            with gzip.open(archive, "wt", encoding="utf-8") as handle:
                handle.write(_OWL.format(d="2026-07-12"))

            self.transform.decompress(archive)

            plain = Path(tmp) / "ncbitaxon.owl"
            self.assertEqual(plain.read_text(encoding="utf-8"), _OWL.format(d="2026-07-12"))
            self.assertEqual(list(Path(tmp).glob("*.partial")), [], "no temp file may survive")

    def test_a_good_plain_owl_survives_a_stale_json(self):
        """
        Forcing a refresh by deleting the plain OWL could destroy the last copy.

        The archive's head reports the new release, so the JSON reads as stale --
        but the plain OWL is complete and already at that release, while the
        archive is truncated further in. Deleting both left the decompression that
        was meant to replace the OWL to fail, with neither OWL nor JSON remaining.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            # Larger than the 2 MB head read, so the release is readable from the
            # front while the truncation sits beyond it.
            body = _OWL.format(d="2026-07-12") + ("<!-- pad -->" * 300_000)
            archive = Path(tmp) / "ncbitaxon.owl.gz"
            with gzip.open(archive, "wt", encoding="utf-8") as handle:
                handle.write(body)
            derived = Path(tmp) / "ncbitaxon_removed_subset.json"
            derived.write_text(_JSON.format(d="2026-01-01"), encoding="utf-8")
            plain = Path(tmp) / "ncbitaxon.owl"
            plain.write_text(body, encoding="utf-8")
            intact = archive.read_bytes()
            archive.write_bytes(intact[: len(intact) - 200])

            self.transform._drop_stale_derived_json(archive, derived)

            self.assertFalse(derived.exists(), "the stale JSON is still removed")
            self.assertTrue(plain.exists(), "the only good OWL must survive")
            self.assertEqual(plain.read_text(encoding="utf-8"), body)


class PostProcessingAtomicityTest(TestCase):

    """ROBOT publishes the JSON atomically; the post-processors must not undo that."""

    def setUp(self):
        """Instantiate the transform without base __init__ side effects."""
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def _interrupted_dump(self, method_name, payload):
        """Run a post-processor whose json.dump dies part-way, and return the file."""
        import json
        import tempfile
        from unittest import mock

        tmp = tempfile.mkdtemp()
        target = Path(tmp) / "go.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        original = target.read_text(encoding="utf-8")

        def dying_dump(data, handle, *args, **kwargs):
            """Write a plausible prefix, then fail as a full disk would."""
            handle.write('{"graphs": [{"nodes": [{"id": "GO:1"')
            raise OSError("No space left on device")

        with mock.patch.object(json, "dump", dying_dump):
            with self.assertRaises(OSError):
                getattr(self.transform, method_name)(target)
        return target, original, Path(tmp)

    def test_an_interrupted_synonym_pass_publishes_nothing(self):
        """
        A truncated derived JSON is unrecoverable.

        The staleness check reads a release stamp from the head and still sees a
        current one, `is_file()` then blocks reconversion, and KGX fails on every
        later run until someone deletes the file by hand.
        """
        import json

        payload = {
            "graphs": [{"nodes": [{"id": "GO:1", "meta": {"synonyms": [{"pred": "x"}, {"pred": "y", "val": "ok"}]}}]}]
        }
        target, original, tmp = self._interrupted_dump("_sanitize_obograph_synonyms", payload)

        self.assertEqual(target.read_text(encoding="utf-8"), original, "the published file must be untouched")
        self.assertIsInstance(json.loads(target.read_text(encoding="utf-8")), dict)
        self.assertEqual(list(tmp.glob("*.partial")), [], "and no temp may survive")

    def test_an_interrupted_deprecated_pass_publishes_nothing(self):
        """The deprecated-term removal rewrites the same file the same way."""
        import json

        payload = {
            "graphs": [
                {
                    "nodes": [
                        {"id": "GO:1", "meta": {"deprecated": True}},
                        {"id": "GO:2"},
                    ],
                    "edges": [{"sub": "GO:1", "pred": "is_a", "obj": "GO:2"}],
                }
            ]
        }
        target, original, tmp = self._interrupted_dump("_drop_deprecated_terms", payload)

        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertIsInstance(json.loads(target.read_text(encoding="utf-8")), dict)
        self.assertEqual(list(tmp.glob("*.partial")), [])
