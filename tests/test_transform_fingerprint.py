"""Content fingerprints, because timestamps do not survive git (#797, #836)."""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.utils.transform_fingerprint import (
    FINGERPRINT_FILE,
    FINGERPRINT_VERSION,
    code_fingerprint,
    data_fingerprint,
    migrate_markers,
    read_fingerprint,
    schema_fingerprint,
    shared_code_fingerprint,
    upstream_fingerprint,
    write_fingerprint,
)


class FingerprintTest(TestCase):
    """The properties the freshness verdict rests on."""

    def setUp(self):
        """Build a scratch code dir and repo root."""
        self.tmp = Path(tempfile.mkdtemp())
        self.code = self.tmp / "code"
        self.code.mkdir()
        (self.code / "a.py").write_text("x = 1\n")
        (self.code / "b.py").write_text("y = 2\n")
        self.repo = self.tmp / "repo"
        (self.repo / "mappings").mkdir(parents=True)
        (self.repo / "mappings" / "m.tsv").write_text("a\tb\n")
        self.out = self.tmp / "out"
        self.out.mkdir()

    def test_touching_a_file_does_not_change_the_fingerprint(self):
        """
        The whole point: `git checkout` rewrites mtimes with no content change.

        That flipped the merge verdict on a file whose bytes were identical
        (#797), and two reviewers spent effort on the phantom disagreement.
        """
        before = code_fingerprint(self.code)
        (self.code / "a.py").touch()
        self.assertEqual(code_fingerprint(self.code), before)

    def test_editing_a_file_changes_it(self):
        """A guard that never fires is worse than none."""
        before = code_fingerprint(self.code)
        (self.code / "a.py").write_text("x = 2\n")
        self.assertNotEqual(code_fingerprint(self.code), before)

    def test_adding_a_file_changes_it(self):
        """
        Several transforms are split across helper modules in one package.

        Hashing only the entry module would miss a change to a helper that
        alters the output just as much, which is why this is directory-scoped.
        """
        before = code_fingerprint(self.code)
        (self.code / "c.py").write_text("z = 3\n")
        self.assertNotEqual(code_fingerprint(self.code), before)

    def test_renaming_a_file_changes_it(self):
        """
        Content alone is not enough: the path is folded in too.

        Renaming changes what runs — imports resolve differently — while the
        multiset of file contents is untouched.
        """
        before = code_fingerprint(self.code)
        (self.code / "a.py").rename(self.code / "renamed.py")
        self.assertNotEqual(code_fingerprint(self.code), before)

    def test_a_deleted_data_input_is_a_change_not_a_skip(self):
        """
        Skipping a missing file would read as "nothing changed".

        A curation file being deleted is exactly the kind of change a rebuild
        must notice, so absence is folded into the digest rather than passed
        over.
        """
        before = data_fingerprint(self.repo, ["mappings/m.tsv"])
        (self.repo / "mappings" / "m.tsv").unlink()
        self.assertNotEqual(data_fingerprint(self.repo, ["mappings/m.tsv"]), before)

    def test_code_and_data_are_recorded_separately(self):
        """
        A stale output must still be able to say *why*.

        `STALE_VS_CODE` and `STALE_VS_DATA` are different actions for whoever
        reads the report; one combined hash would collapse them.
        """
        payload = write_fingerprint(self.out, self.code, self.repo, ["mappings/m.tsv"])
        self.assertNotEqual(payload["code"], payload["data"])
        self.assertEqual(read_fingerprint(self.out), payload)

    def test_an_unparseable_marker_reads_as_absent(self):
        """
        Fall back to timestamps rather than asserting a mismatch we cannot judge.

        Claiming "stale" off a corrupt marker would be the cry-wolf failure this
        work exists to remove.
        """
        (self.out / FINGERPRINT_FILE).write_text("{not json")
        self.assertIsNone(read_fingerprint(self.out))

    def test_a_marker_from_another_scheme_version_reads_as_absent(self):
        """Comparing across hashing schemes would silently compare nothing."""
        write_fingerprint(self.out, self.code, self.repo, ["mappings/m.tsv"])
        path = self.out / FINGERPRINT_FILE
        payload = json.loads(path.read_text())
        payload["version"] = 999
        path.write_text(json.dumps(payload))
        self.assertIsNone(read_fingerprint(self.out))

    def test_an_absent_marker_reads_as_absent(self):
        """Fresh checkouts and pre-existing outputs have none; that is not an error."""
        self.assertIsNone(read_fingerprint(self.tmp / "nowhere"))


class SchemaFingerprintTests(TestCase):
    """The marker must say which Biolink schema produced the output (#943)."""

    def _root(self, td, version="4.4.2", extra=""):
        """
        Lay out a repo root with a pinned model.

        :param td: Temp directory.
        :param version: The ``version:`` line to write.
        :param extra: Extra text appended to the model.
        :return: The root path.
        """
        root = Path(td)
        raw = root / "data" / "raw"
        raw.mkdir(parents=True)
        (raw / "biolink-model.yaml").write_text(
            f"id: https://w3id.org/biolink/biolink-model\nname: Biolink-Model\nversion: {version}\n{extra}",
            encoding="utf-8",
        )
        (raw / "attributes.yaml").write_text("id: attributes\n", encoding="utf-8")
        return root

    def test_the_version_is_read_from_the_model(self):
        """The human-readable half of the record."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(schema_fingerprint(self._root(td))["version"], "4.4.2")

    def test_editing_the_model_changes_the_digest_even_at_the_same_version(self):
        """Two files claiming one version are still two schemas."""
        with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
            a = schema_fingerprint(self._root(td_a))
            b = schema_fingerprint(self._root(td_b, extra="classes:\n  thing: {}\n"))
        self.assertEqual(a["version"], b["version"])
        self.assertNotEqual(a["digest"], b["digest"])

    def test_the_same_schema_in_two_checkouts_is_one_schema(self):
        """
        The digest must not fold in the absolute path.

        A marker travels with its output directory; comparing it from another
        checkout, or on another machine, must not read as a schema change.
        """
        with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
            self.assertEqual(schema_fingerprint(self._root(td_a)), schema_fingerprint(self._root(td_b)))

    def test_no_schema_on_disk_records_none_rather_than_inventing_one(self):
        """Unknown provenance is recorded as unknown (#911)."""
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(schema_fingerprint(Path(td)))

    def test_the_marker_carries_the_schema(self):
        """Wired into ``write_fingerprint``, not just available beside it."""
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            code = root / "pkg"
            code.mkdir()
            (code / "t.py").write_text("x = 1\n", encoding="utf-8")
            out = root / "out"
            out.mkdir()
            payload = write_fingerprint(out, code, root, data_inputs=())
            recorded = read_fingerprint(out)
        self.assertEqual(payload["schema"]["version"], "4.4.2")
        self.assertEqual(recorded["schema"], payload["schema"])


def _package(root: Path, name: str, body: str) -> Path:
    """
    Lay out a one-module transform package under ``root``.

    :param root: Repository root.
    :param name: Package name.
    :param body: Module source.
    :return: The package directory.
    """
    pkg = root / "kg_microbe" / "transform_utils" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / f"{name}.py").write_text(body, encoding="utf-8")
    return pkg


def _shared(root: Path, body: str) -> None:
    """
    Lay out the shared code every transform runs through.

    :param root: Repository root.
    :param body: Source for the one utils module.
    :return: None.
    """
    (root / "kg_microbe" / "utils").mkdir(parents=True, exist_ok=True)
    (root / "kg_microbe" / "utils" / "helper.py").write_text(body, encoding="utf-8")


class PathIndependenceTests(TestCase):
    """The same code and data under two checkouts is one fingerprint (#983)."""

    def test_the_package_digest_does_not_fold_in_the_checkout_path(self):
        """A marker carried with its output must not read stale from another root."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            pa = _package(Path(a), "gold", "x = 1\n")
            pb = _package(Path(b), "gold", "x = 1\n")
            self.assertEqual(code_fingerprint(pa, Path(a)), code_fingerprint(pb, Path(b)))

    def test_the_data_digest_does_not_fold_in_the_checkout_path(self):
        """Same rule for declared curation inputs."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for root in (a, b):
                (Path(root) / "mappings").mkdir()
                (Path(root) / "mappings" / "m.tsv").write_text("k\tv\n", encoding="utf-8")
            self.assertEqual(
                data_fingerprint(Path(a), ["mappings/m.tsv"]), data_fingerprint(Path(b), ["mappings/m.tsv"])
            )

    def test_renaming_a_file_still_changes_the_digest(self):
        """Path independence must not lose rename detection."""
        with tempfile.TemporaryDirectory() as a:
            (Path(a) / "mappings").mkdir()
            (Path(a) / "mappings" / "m.tsv").write_text("k\tv\n", encoding="utf-8")
            before = data_fingerprint(Path(a), ["mappings/m.tsv"])
            (Path(a) / "mappings" / "m.tsv").rename(Path(a) / "mappings" / "n.tsv")
            self.assertNotEqual(before, data_fingerprint(Path(a), ["mappings/n.tsv"]))


class SharedCodeTests(TestCase):
    """A change under kg_microbe/utils/ must mark every transform stale (#1002)."""

    def test_editing_shared_code_changes_the_shared_digest_not_the_package(self):
        """The two are recorded apart so the report can say which moved."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = _package(root, "gold", "x = 1\n")
            _shared(root, "def f():\n    return 1\n")
            code_before, shared_before = code_fingerprint(pkg, root), shared_code_fingerprint(root)
            _shared(root, "def f():\n    return 2\n")
            self.assertEqual(code_fingerprint(pkg, root), code_before)
            self.assertNotEqual(shared_code_fingerprint(root), shared_before)

    def test_the_marker_records_the_shared_digest(self):
        """Wired into write_fingerprint."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = _package(root, "gold", "x = 1\n")
            _shared(root, "y = 1\n")
            out = root / "out"
            out.mkdir()
            payload = write_fingerprint(out, pkg, root, data_inputs=())
            self.assertEqual(payload["shared"], shared_code_fingerprint(root))
            self.assertEqual(payload["version"], FINGERPRINT_VERSION)


class MigrationTests(TestCase):
    """Scheme-2 markers that still vouch for their output are carried forward."""

    def _v2_marker(self, out: Path, pkg: Path, root: Path, data_inputs=(), upstream=None):
        """
        Write a scheme-2 marker the way the old code did (absolute paths, no shared).

        :param out: Output directory.
        :param pkg: Package directory.
        :param root: Repository root.
        :param data_inputs: Declared inputs.
        :param upstream: Precomputed scheme-2 upstream digest, if any.
        :return: None.
        """
        import kg_microbe.utils.transform_fingerprint as fp

        payload = {
            "version": 2,
            "code": fp._v2_code_fingerprint(pkg),
            "data": fp._v2_hash_files(root / rel for rel in data_inputs),
            "upstream": upstream or fp._v2_upstream_fingerprint(out.parent, ()),
        }
        (out / "source_fingerprint.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_a_marker_that_still_holds_is_rewritten_as_scheme_3(self):
        """The rebuilt tree keeps its FRESH verdicts across the scheme bump."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = _package(root, "gold", "x = 1\n")
            _shared(root, "y = 1\n")
            out = root / "data" / "transformed" / "gold"
            out.mkdir(parents=True)
            self._v2_marker(out, pkg, root)
            outcome = migrate_markers(
                root / "data" / "transformed",
                root,
                [{"name": "gold", "output_dir": "gold", "code_dir": pkg, "data_inputs": (), "transform_inputs": ()}],
            )
            self.assertEqual(outcome, {"gold": "migrated"})
            recorded = read_fingerprint(out)
            self.assertEqual(recorded["version"], FINGERPRINT_VERSION)
            self.assertEqual(recorded["code"], code_fingerprint(pkg, root))
            self.assertEqual(recorded["shared"], shared_code_fingerprint(root))

    def test_a_marker_that_no_longer_holds_is_left_for_a_real_rerun(self):
        """Migration must not launder staleness into a fresh marker."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = _package(root, "gold", "x = 1\n")
            out = root / "data" / "transformed" / "gold"
            out.mkdir(parents=True)
            self._v2_marker(out, pkg, root)
            _package(root, "gold", "x = 2\n")  # behaviour changed after the marker was written
            outcome = migrate_markers(
                root / "data" / "transformed",
                root,
                [{"name": "gold", "output_dir": "gold", "code_dir": pkg, "data_inputs": (), "transform_inputs": ()}],
            )
            self.assertEqual(outcome, {"gold": "left: stale under scheme 2; rerun the transform"})
            self.assertIsNone(read_fingerprint(out))

    def test_downstream_is_rewritten_after_its_upstream(self):
        """A downstream's new upstream digest must see the upstream's new marker."""
        import kg_microbe.utils.transform_fingerprint as fp

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            up_pkg = _package(root, "gtdb", "x = 1\n")
            down_pkg = _package(root, "lpsn", "x = 1\n")
            transformed = root / "data" / "transformed"
            for name in ("gtdb", "lpsn"):
                (transformed / name).mkdir(parents=True)
            self._v2_marker(transformed / "gtdb", up_pkg, root)
            self._v2_marker(
                transformed / "lpsn", down_pkg, root, upstream=fp._v2_upstream_fingerprint(transformed, ("gtdb",))
            )
            sources = [
                {
                    "name": "lpsn",
                    "output_dir": "lpsn",
                    "code_dir": down_pkg,
                    "data_inputs": (),
                    "transform_inputs": ("gtdb",),
                },
                {"name": "gtdb", "output_dir": "gtdb", "code_dir": up_pkg, "data_inputs": (), "transform_inputs": ()},
            ]
            outcome = migrate_markers(transformed, root, sources)
            self.assertEqual(outcome, {"gtdb": "migrated", "lpsn": "migrated"})
            self.assertEqual(
                read_fingerprint(transformed / "lpsn")["upstream"], upstream_fingerprint(transformed, ("gtdb",))
            )
