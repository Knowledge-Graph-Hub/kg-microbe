"""
Bind the promoted supported-only MIM set and unified artifact to their review.

The immutable reviewed export intentionally contains exact matches only. Requiring
asymmetric rows would reject that product and encourage replaying withheld claims.
Legacy/asymmetric direction behavior remains covered independently by
``tests/test_sssom_predicate_semantics.py``; it is not inferred from release dates
or disabled when the production supported subset contains no asymmetric rows.
"""

import gzip
import hashlib
from collections import Counter
from pathlib import Path
from unittest import TestCase

import yaml

from kg_microbe.utils.chemical_mapping_utils import _iter_sssom_rows, read_predicate_semantics
from scripts.refresh_reviewed_mim import load_release_pin

REPO_ROOT = Path(__file__).resolve().parents[1]
SSSOM = REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
UNIFIED = REPO_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"

# Byte identities accepted together in the immutable-export promotion review.
# Updating a release requires reviewing both products, not regenerating these
# expectations from whichever files happen to be present in the checkout.
SOURCE_COMMIT = "1848b0fe521bc2462f165912fcf92d09ad9a8cec"
MANIFEST_SHA256 = "9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af"
SUPPORTED_SHA256 = "6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb"
UNIFIED_SHA256 = "fe54cd1a1dc14123b41bd8f08c9c42096cf2815b2ae5a5bb4ce4bd349041c98d"
BUILDER_SHA256 = "a6cbacfba8bc9dc02d7f328ef7bfd86041c56c0988dee621df4ea4d536a7f8f8"


def _sha256(path):
    """Fingerprint required tracked artifacts without loading complete files."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata(path):
    """Read only the leading SSSOM YAML metadata, including gzip artifacts."""
    opener = gzip.open if path.suffix == ".gz" else open
    header = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            header.append(line[1:].removeprefix(" "))
    return yaml.safe_load("".join(header))


class VendoredSetShapeTest(TestCase):
    """Require the exact-only supported product; missing tracked data must fail."""

    @classmethod
    def setUpClass(cls):
        """Read the small supported product and the independently committed pin."""
        cls.pin = load_release_pin(REPO_ROOT)
        cls.rows = list(_iter_sssom_rows(SSSOM))
        cls.metadata = _metadata(SSSOM)

    def test_supported_bytes_match_the_review_and_committed_pin(self):
        """Prevent a stale table, floating upstream export, or unreviewed repin."""
        self.assertEqual(self.pin["source_commit"], SOURCE_COMMIT)
        self.assertEqual(self.pin["manifest_sha256"], MANIFEST_SHA256)
        self.assertEqual(self.pin["files"][SSSOM.name], SUPPORTED_SHA256)
        self.assertEqual(_sha256(SSSOM), SUPPORTED_SHA256)

    def test_only_the_1747_supported_exact_assertions_are_vendored(self):
        """Do not reintroduce withheld asymmetric claims merely to satisfy a test."""
        self.assertEqual(Counter(row["predicate_id"] for row in self.rows), {"skos:exactMatch": 1747})
        self.assertTrue(all(row["subject_id"].startswith("MIM:") for row in self.rows))
        self.assertTrue(all(row["subject_label"] and row["object_id"] for row in self.rows))
        self.assertEqual(len({row["subject_id"] for row in self.rows}), 1696)
        self.assertEqual(len({row["subject_label"] for row in self.rows}), 1696)

    def test_supported_header_declares_skos_and_the_reviewed_version(self):
        """Keep predicate semantics explicit even when every current row is exact."""
        self.assertEqual(read_predicate_semantics(SSSOM), "skos")
        self.assertEqual(self.metadata["predicate_semantics"], "skos")
        self.assertEqual(self.metadata["mapping_set_version"], "2026-09-24")
        self.assertEqual(
            self.metadata["mapping_set_id"],
            "https://w3id.org/sssom/mappings/culturebotai_mim_ingredient/reviewed-supported",
        )
        self.assertEqual(self.metadata["curie_map"]["skos"], "http://www.w3.org/2004/02/skos/core#")
        self.assertEqual(
            self.metadata["curie_map"]["MIM"],
            "https://github.com/CultureBotAI/MediaIngredientMech/blob/main/data/ingredients/mapped/",
        )


class PromotedMappingPairTest(TestCase):
    """Protect the reviewed pair without claiming old transform outputs are fresh."""

    def test_both_production_artifacts_are_the_reviewed_pair(self):
        """A supported-only table cannot silently accompany an old unified seed."""
        pin = load_release_pin(REPO_ROOT)
        self.assertEqual(pin["source_commit"], SOURCE_COMMIT)
        self.assertEqual(pin["manifest_sha256"], MANIFEST_SHA256)
        self.assertEqual(pin["files"][SSSOM.name], SUPPORTED_SHA256)
        self.assertEqual(_sha256(SSSOM), SUPPORTED_SHA256)
        self.assertEqual(_sha256(UNIFIED), UNIFIED_SHA256)

    def test_unified_header_identifies_the_pinned_review_and_builder(self):
        """Bind the accepted reconstruction to its manifest, not a floating input."""
        metadata = _metadata(UNIFIED)
        pin = load_release_pin(REPO_ROOT)
        self.assertEqual(metadata["mapping_tool"], "kg-microbe/scripts/mim_conservative_refresh.py")
        self.assertEqual(metadata["mapping_tool_version"], "sha256:" + BUILDER_SHA256)
        self.assertIn("reviewed manifest sha256:" + pin["manifest_sha256"], metadata["mapping_set_description"])
        # The conservative builder preserves historical baseline metadata
        # (#1170). Absence retains the reader's legacy direction contract; the
        # accepted unified set has no asymmetric rows to interpret. Do not
        # rewrite its immutable bytes to copy the supported product's header.
        self.assertNotIn("predicate_semantics", metadata)
        self.assertEqual(read_predicate_semantics(UNIFIED), "")
        # The unified version preserves historical baseline metadata. It must not
        # be fabricated as the supported product's September 24 release date.
        self.assertEqual(metadata["mapping_set_version"], "2026-09-06")

    def test_unified_counts_and_native_categories_match_the_reviewed_candidate(self):
        """Stream counts and the five reviewed category rows without another full scan."""
        entities = set()
        predicates = Counter()
        native_rows = Counter()
        expected_native_rows = {
            ("MIM:Mucin", "skos:exactMatch", "NCIT:C16883", "biolink:ChemicalEntity"): 1,
            ("kgm.name:mucin", "skos:exactMatch", "NCIT:C16883", "biolink:ChemicalEntity"): 1,
            ("kgm.name:mucus_glycoprotein", "skos:closeMatch", "NCIT:C16883", "biolink:ChemicalEntity"): 1,
            ("MIM:Sugar", "skos:exactMatch", "NCIT:C71939", "biolink:Food"): 1,
            ("kgm.name:sugar", "skos:exactMatch", "NCIT:C71939", "biolink:Food"): 1,
        }
        rows = 0
        for row in _iter_sssom_rows(UNIFIED):
            rows += 1
            entities.add(row["object_id"])
            predicates[row["predicate_id"]] += 1
            if row["object_id"] in {"NCIT:C16883", "NCIT:C71939"}:
                native_rows[(row["subject_id"], row["predicate_id"], row["object_id"], row["object_category"])] += 1
        self.assertEqual(rows, 591893)
        self.assertEqual(len(entities), 120185)
        self.assertEqual(predicates, {"skos:exactMatch": 336050, "skos:closeMatch": 255843})
        self.assertEqual(predicates["skos:broadMatch"], 0)
        self.assertEqual(predicates["skos:narrowMatch"], 0)
        self.assertEqual(native_rows, expected_native_rows)
