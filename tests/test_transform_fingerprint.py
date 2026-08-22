"""Content fingerprints, because timestamps do not survive git (#797, #836)."""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.utils.transform_fingerprint import (
    FINGERPRINT_FILE,
    code_fingerprint,
    data_fingerprint,
    read_fingerprint,
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
