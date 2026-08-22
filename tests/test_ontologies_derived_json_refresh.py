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


_EC_OWL = (
    '<?xml version="1.0"?>\n<rdf:RDF>\n'
    '<owl:Ontology rdf:about="http://purl.obolibrary.org/obo/eccode.owl">\n'
    '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/eccode/{d}/eccode.owl"/>\n'
    "</owl:Ontology>\n</rdf:RDF>\n"
)
# ROBOT-shaped: mirrors what `robot convert --input ec.owl -f json` actually
# emits. EC's versionIRI is `.../obo/eccode/DATE/eccode.owl` with no
# `releases/` segment, and ROBOT stashes it verbatim into `meta.version` —
# it does not synthesise a `versionInfo` basicPropertyValue for EC, so a
# fixture that fabricated one masked the real reader shape. The stamp lookup
# has to catch the `"version": "..."` form to keep the transform's derived
# JSON honest about its release.
_EC_JSON = (
    '{{"graphs":[{{"id":"http://purl.obolibrary.org/obo/eccode.owl",'
    '"meta":{{"basicPropertyValues":['
    '{{"pred":"http://www.geneontology.org/formats/oboInOwl#hasOBOFormatVersion","val":"1.2"}}],'
    '"version":"http://purl.obolibrary.org/obo/eccode/{d}/eccode.owl"}}}}]}}'
)


class EcSingleSourceTest(TestCase):
    """EC must ship one release, not two: derive ec.json from ec.owl, don't download both."""

    def setUp(self):
        """Instantiate the transform without base __init__ side effects."""
        self.transform = OntologiesTransform.__new__(OntologiesTransform)

    def test_ontologies_map_derives_ec_json_from_owl(self):
        """
        EC must consume ec.owl.gz, not a separately-downloaded ec.json.

        A prior revision downloaded both ec.json and ec.owl.gz independently
        from w3id.org/biopragmatics/resources/eccode/. Their release schedules
        drifted (2024-11-27 JSON vs 2024-10-02 OWL when Codex round 29
        checked): the ontologies transform emitted EC nodes from the newer
        JSON while `_ensure_ec_db` built ec.db from the older OWL, so
        `rhea_mappings` label enrichment against ec.db returned blank labels
        for the ~42 terms unique to the newer JSON. This map keeps both the
        transform output and the guarded lookup DB on the same release.
        """
        from kg_microbe.transform_utils.ontologies.ontologies_transform import ONTOLOGIES_MAP

        self.assertEqual(
            ONTOLOGIES_MAP["ec"],
            "ec.owl.gz",
            "EC must consume ec.owl.gz so ec.json is derived from the same OWL that ec.db is built from",
        )

    def test_download_yaml_has_no_standalone_ec_json(self):
        """`kg download` must fetch only ec.owl.gz — a standalone ec.json download would re-open the drift."""
        import yaml

        from kg_microbe.transform_utils.constants import CHEBI_SOURCE

        download_yaml = Path(CHEBI_SOURCE).parent.parent.parent / "download.yaml"
        if not download_yaml.exists():
            self.skipTest("download.yaml not present in this checkout")
        entries = yaml.safe_load(download_yaml.read_text(encoding="utf-8"))
        ec_json = [e for e in entries if e.get("local_name") == "ec.json"]
        self.assertEqual(
            ec_json,
            [],
            "download.yaml must not fetch ec.json — the ontologies transform derives it from ec.owl.gz",
        )

    def test_a_stale_derived_ec_json_is_dropped(self):
        """A drifted ec.json left over from the standalone download must be dropped."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ec.owl.gz"
            with gzip.open(archive, "wt", encoding="utf-8") as handle:
                handle.write(_EC_OWL.format(d="2026-07-31"))
            derived = Path(tmp) / "ec.json"
            derived.write_text(_EC_JSON.format(d="2024-11-27"), encoding="utf-8")

            self.transform._drop_stale_derived_json(archive, derived)

            self.assertFalse(derived.exists(), "a drifted derived ec.json must be dropped so ROBOT re-runs")

    def test_a_mid_file_truncated_json_is_detected(self):
        """
        Head-only checks miss a JSON truncated after a valid start.

        ROBOT can crash after writing several MB of a multi-GB conversion:
        the file starts with ``{`` and may carry the current release stamp,
        so the release-comparison guard passes and ``convert_to_json``
        skips regeneration. Every subsequent run then fails on the same
        corruption. The trailer check closes that gap.
        """
        import tempfile

        from kg_microbe.utils.ontology_utils import _derived_json_is_unusable

        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp) / "big.json"
            # Well over the tail window; the trailer never gets written.
            derived.write_text(
                '{"graphs":[{"id":"http://example.org/x","meta":{"basicPropertyValues":['
                '{"pred":"versionInfo","val":"2026-07-31"}]},"nodes":['
                + ",".join(f'{{"id":"X:{i}"}}' for i in range(20_000)),
                encoding="utf-8",
            )
            self.assertTrue(
                _derived_json_is_unusable(derived),
                "a JSON that opens with '{' but never closes must be flagged unusable",
            )

    def test_a_complete_json_is_not_flagged_unusable(self):
        """The trailer heuristic must accept a well-formed document."""
        import tempfile

        from kg_microbe.utils.ontology_utils import _derived_json_is_unusable

        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp) / "good.json"
            derived.write_text('{"graphs":[{"nodes":[{"id":"X:1"}]}]}\n', encoding="utf-8")
            self.assertFalse(_derived_json_is_unusable(derived))

    def test_a_truncated_plain_owl_is_replaced(self):
        """
        A plain OWL missing its closing tag must be replaced from the archive.

        Round 32 added the trailer check to :func:`_archive_release_differs`
        so a partial plain OWL surviving a mid-decompression crash cannot
        pass the release-only comparison and be reused for every subsequent
        build.
        """
        import tempfile

        from kg_microbe.utils.ontology_utils import _archive_release_differs

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ncbitaxon.owl.gz"
            body = _OWL.format(d="2026-07-31")
            with gzip.open(archive, "wt", encoding="utf-8") as handle:
                handle.write(body)
            plain = Path(tmp) / "ncbitaxon.owl"
            # Same release stamp, but no closing element.
            plain.write_text(
                '<?xml version="1.0"?>\n<owl:Ontology>'
                '<owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/ncbitaxon/2026-07-31/ncbitaxon.owl"/>',
                encoding="utf-8",
            )

            self.assertTrue(
                _archive_release_differs(plain),
                "a truncated plain OWL must be reported as needing replacement",
            )


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
