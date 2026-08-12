"""
Regression tests for the METPO proposal extractor.

The CI gate enforces that committed proposal artifacts equal the extractor's
fresh output: re-running the script must not produce a diff against
mappings/metpo_proposal_*.tsv, mappings/metpo_existing_aliases.tsv, or
mappings/canonical/metpo_alias_mappings.tsv.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
import unittest
from collections import defaultdict
from difflib import unified_diff
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "extract_metpo_proposals.py"
COMMITTED_MAPPINGS = REPO_ROOT / "mappings"
COMMITTED_METATRAITS = REPO_ROOT / "mappings" / "canonical"
PROPOSAL_FILES = (
    "metpo_proposal_quantitative.tsv",
    "metpo_proposal_categorical.tsv",
    "metpo_existing_aliases.tsv",
    "metpo_label_corrections.tsv",
    "metpo_proposal_classes_robot.tsv",
    "metpo_proposal_properties_robot.tsv",
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("extract_metpo_proposals", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _diff(actual: Path, expected: Path) -> str:
    if not expected.exists():
        return f"committed {expected} is missing"
    a = actual.read_text().splitlines()
    b = expected.read_text().splitlines()
    diff = "\n".join(unified_diff(b, a, fromfile=str(expected), tofile=str(actual), lineterm=""))
    return diff


class TestProposalOutputsMatchCommitted(unittest.TestCase):

    """Re-run the extractor and assert it reproduces every committed artifact byte-for-byte."""

    def test_outputs_match_committed(self):
        """Run extract_metpo_proposals.main(tmp dirs) and diff every output."""
        if not (REPO_ROOT / "data" / "transformed" / "ontologies" / "metpo_nodes.tsv").exists():
            self.skipTest("METPO snapshot absent — run ontologies transform first")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mappings_out = tmp_path / "mappings"
            metatraits_out = tmp_path / "metatraits_mappings"

            cwd = Path.cwd()
            module = _load_script_module()
            try:
                # Script reads data/raw/bacdive_strains.json + data/transformed/ontologies
                # via repo-relative paths, so cwd must be the repo root.
                import os

                os.chdir(REPO_ROOT)
                module.main(output_dir=mappings_out, metatraits_dir=metatraits_out)
            finally:
                import os

                os.chdir(cwd)

            for name in PROPOSAL_FILES:
                actual = mappings_out / name
                expected = COMMITTED_MAPPINGS / name
                self.assertTrue(actual.exists(), f"extractor did not write {actual}")
                diff = _diff(actual, expected)
                self.assertEqual(diff, "", f"{name} drift:\n{diff}")

            actual_alias = metatraits_out / "metpo_alias_mappings.tsv"
            expected_alias = COMMITTED_METATRAITS / "metpo_alias_mappings.tsv"
            self.assertTrue(actual_alias.exists(), "extractor did not write metpo_alias_mappings.tsv")
            diff = _diff(actual_alias, expected_alias)
            self.assertEqual(diff, "", f"metpo_alias_mappings.tsv drift:\n{diff}")


def _load_property_rows() -> tuple[list[dict], dict]:
    """
    Parse the committed properties ROBOT template.

    :return: ``(data rows as dicts keyed by column name, column -> directive)``.

    Deliberately reads the *committed* artifact rather than regenerating: that
    file is what gets submitted upstream, and it is the thing whose semantics
    #749 broke. Columns are addressed by header name, not position, so
    reordering or inserting a column cannot silently shift what this test reads
    -- a positional index would reintroduce the same class of defect.
    """
    path = COMMITTED_MAPPINGS / "metpo_proposal_properties_robot.tsv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header, directives, data = rows[0], rows[1], rows[2:]
    # strict=True is load-bearing, not lint appeasement: a row whose column
    # count differs from the header is precisely what ROBOT rejects with
    # "Number of columns ... does not match", so raising here is correct.
    return (
        [dict(zip(header, r, strict=True)) for r in data],
        dict(zip(header, directives, strict=True)),
    )


def _pattern_keys(row: dict) -> tuple[str, list[str]]:
    """
    Reproduce _build_metpo_lookups' keying for one property row.

    The loader (metatraits.py, ``_build_metpo_lookups``) treats a label starting
    with ``does not `` as the negative half and keys the pattern map on the
    label plus every synonym, lowercased and stripped. It reads
    ``node["meta"]["synonyms"]`` -- *all* synonym types -- so this keys on the
    synonyms column whatever annotation directive that column carries.
    """
    label = row["label"]
    polarity = "negative" if label.lower().startswith("does not ") else "positive"
    synonyms = [s for s in (row.get("synonyms") or "").split("|") if s.strip()]
    return polarity, [k.lower().strip() for k in [label] + synonyms if k.strip()]


def _positive_stems(label: str) -> set[str]:
    """
    Candidate `does not <stem>` forms for a positive predicate label.

    Inflects the *first* word only, which is where the third-person -s sits in
    every METPO predicate shape (``grows in``, ``shows activity of``). Matching
    on a candidate set rather than one ``removesuffix("s")`` is what makes
    multi-word and -ies predicates visible; the naive form silently missed
    ``grows in`` / ``does not grow in`` -- METPO:2000517/2000518, the very pair
    the pairing fix exists to prevent (#755).
    """
    words = label.lower().split()
    if not words:
        return set()
    head, rest = words[0], words[1:]
    heads = {head}
    if head.endswith("ies"):
        heads.add(head[:-3] + "y")
    if head.endswith("es"):
        heads.update({head[:-2], head[:-1]})
    if head.endswith("s"):
        heads.add(head[:-1])
    return {" ".join([h, *rest]).strip() for h in heads}


class TestPositiveStemHeuristic(unittest.TestCase):

    """
    The pairing test is only as good as its stem derivation.

    These are the real predicate shapes in METPO. A heuristic that misses one
    makes the sibling check pass vacuously -- worse than no test, because the
    suite then looks like it covers pairing.
    """

    def test_real_predicate_shapes_are_paired(self):
        """Each positive must generate the stem its `does not` partner uses."""
        shapes = [
            ("tolerates", "does not tolerate"),
            ("produces", "does not produce"),
            ("grows in", "does not grow in"),  # METPO:2000517/2000518
            ("shows activity of", "does not show activity of"),
            ("denitrifies", "does not denitrify"),
            ("assimilates", "does not assimilate"),
            ("oxidizes", "does not oxidize"),
        ]
        missed = [
            f"{pos!r} does not generate {neg!r} (stems: {sorted(_positive_stems(pos))})"
            for pos, neg in shapes
            if neg.removeprefix("does not ") not in _positive_stems(pos)
        ]
        self.assertEqual(missed, [], "\n  ".join(missed))


class TestProposedPredicatePairing(unittest.TestCase):

    """
    Guard the pairing contract that #749 broke silently.

    The regenerate-and-diff gate above cannot catch an unpaired predicate: a
    proposal that omits the shared synonym is perfectly self-consistent, so the
    artifact matches and the gate stays green while ``_get_negative_predicate``
    returns None and false-majority observations are dropped downstream.
    """

    def test_synonyms_column_carries_a_synonym_directive(self):
        """The column must exist AND carry an annotation directive to reach OWL."""
        _, directives = _load_property_rows()
        self.assertIn(
            "synonyms",
            directives,
            "properties template has no synonyms column -- Term.synonyms will be "
            "silently dropped and no proposed predicate can auto-pair (#749)",
        )
        self.assertIn(
            "Synonym",
            directives["synonyms"],
            f"synonyms column carries directive {directives['synonyms']!r}, which "
            "emits no synonym annotation; the pairing loader will see nothing",
        )

    def test_no_orphan_negative_predicates(self):
        """Every `does not X` property shares a pattern key with a positive."""
        rows, _ = _load_property_rows()
        by_key = defaultdict(dict)
        for row in rows:
            polarity, keys = _pattern_keys(row)
            for key in keys:
                by_key[key][polarity] = row["proposed_id"]

        orphans = []
        for row in rows:
            polarity, keys = _pattern_keys(row)
            if polarity != "negative":
                continue
            if not any("positive" in by_key[key] for key in keys):
                orphans.append(f"{row['proposed_id']} {row['label']!r}")
        self.assertEqual(
            orphans,
            [],
            "negative predicates with no positive partner reachable through a "
            "shared synonym; give both members a shared related synonym:\n  " + "\n  ".join(orphans),
        )

    def test_does_not_stem_siblings_are_paired(self):
        """A `does not <stem>` sibling of a proposed positive must pair with it."""
        rows, _ = _load_property_rows()
        positives = {}
        for row in rows:
            polarity, keys = _pattern_keys(row)
            if polarity == "positive":
                for stem in _positive_stems(row["label"]):
                    positives[stem] = (row["proposed_id"], set(keys))

        unpaired = []
        for row in rows:
            polarity, keys = _pattern_keys(row)
            if polarity != "negative":
                continue
            stem = row["label"].lower().removeprefix("does not ").strip()
            sibling = positives.get(stem)
            if sibling and not (sibling[1] & set(keys)):
                unpaired.append(f"{sibling[0]} / {row['proposed_id']} ({row['label']!r}) share no key")
        self.assertEqual(unpaired, [], "\n  ".join(unpaired))

    def test_no_same_polarity_pattern_key_clash(self):
        """Two same-polarity properties sharing a key silently collapse (#753)."""
        rows, _ = _load_property_rows()
        claims = defaultdict(set)
        for row in rows:
            polarity, keys = _pattern_keys(row)
            for key in keys:
                claims[(key, polarity)].add(row["proposed_id"])

        clashes = [
            f"{polarity} key {key!r} claimed by {sorted(ids)}"
            for (key, polarity), ids in sorted(claims.items())
            if len(ids) > 1
        ]
        self.assertEqual(
            clashes,
            [],
            "the loader writes last-wins, so all but one of these becomes "
            "unreachable through that pattern:\n  " + "\n  ".join(clashes),
        )


if __name__ == "__main__":
    unittest.main()
