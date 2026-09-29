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
import json
from collections import Counter
from pathlib import Path
from unittest import TestCase

import yaml

from kg_microbe.utils.cas import invalid_cas_identifier
from kg_microbe.utils.chemical_mapping_utils import _iter_sssom_rows, read_predicate_semantics
from scripts.refresh_reviewed_mim import load_release_pin

REPO_ROOT = Path(__file__).resolve().parents[1]
SSSOM = REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
UNIFIED = REPO_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
RELEASE_PIN = REPO_ROOT / "mappings" / "mim_reviewed_release.json"
PRIOR_CLAIMS = REPO_ROOT / "tests" / "resources" / "cas_mapping_promotion" / "prior_claims.tsv"
POTATO_SCOPE = REPO_ROOT / "tests" / "resources" / "mediadive" / "potato_scope.json"
P3556_SCOPE = REPO_ROOT / "tests" / "resources" / "mediadive" / "p3556_scope.json"

# Byte identities accepted together in the immutable-export promotion review.
# Updating a release requires reviewing both products, not regenerating these
# expectations from whichever files happen to be present in the checkout.
SOURCE_COMMIT = "1848b0fe521bc2462f165912fcf92d09ad9a8cec"
MANIFEST_SHA256 = "9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af"
SUPPORTED_SHA256 = "6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb"
UNIFIED_SHA256 = "67c48e1bf6bed1f1fef03a0da1d7d1b56af9fc72374dddd703c222fb36df3cd4"
IDENTITY_REFRESH_WRITER_SHA256 = "257fe4d8bf16f92eb78d5e375065e030ea56d7c1174d859fecd2baa80ac18c27"
IDENTITY_POLICY_SHA256 = "4670cbb9255bdac7e9654fc415c9bfd35e55955fea5f27865a74e55849810b4c"
RELEASE_PIN_SHA256 = "f082c05656a0910c85176eec7b41deeb77c27967aecb80393fddc262819b6d97"
PRIOR_CLAIMS_SHA256 = "629198d090f7e45f7f17ce97a124eb9cad879b0bb066930b11ea8cf80ce15b2c"
POTATO_SCOPE_SHA256 = "b4755925efe8cde9871569b047e28c185ac56e2cba6295fca20fef2901062723"
P3556_SCOPE_SHA256 = "7c06f4e2179356ddf1d917a6938cba5e3bdf6669f42a29019b93963e4a70646c"
P3556_REVIEWED_LABEL = (
    "[(2R)-3-hexadecanoyloxy-2-[(9E,12E)-octadeca-9,12-dienoyl]oxy-propyl] "
    "2-(trimethylammonio)ethyl phosphate"
)


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


def _row_key(row):
    """Retain every field for exact full-row multiplicity comparisons."""
    return tuple(sorted(row.items()))


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
        self.assertEqual(_sha256(RELEASE_PIN), RELEASE_PIN_SHA256)

    def test_prior_claim_fixture_is_fixed_before_candidate_reconstruction(self):
        """Keep the original CAS33 and native lexical controls, not candidate-derived rows."""
        self.assertEqual(_sha256(PRIOR_CLAIMS), PRIOR_CLAIMS_SHA256)
        rows = list(_iter_sssom_rows(PRIOR_CLAIMS))
        invalid = [row for row in rows if any(invalid_cas_identifier(row[key]) for key in ("subject_id", "object_id"))]
        lexical = [row for row in rows if row["mapping_justification"] == "semapv:LexicalMatching"]
        native_lexical = [row for row in lexical if row["source"] == "chebi_xrefs"]
        self.assertEqual(len(rows), 123)
        self.assertEqual(len({_row_key(row) for row in rows}), 123)
        self.assertTrue(all(len(row) == 13 for row in rows))
        self.assertEqual(len(invalid), 33)
        self.assertEqual(
            Counter((row["source"], row["predicate_id"]) for row in invalid),
            {("chebi_xrefs", "skos:exactMatch"): 32, ("mediadive_compounds", "skos:closeMatch"): 1},
        )
        self.assertEqual(len(native_lexical), 90)
        self.assertEqual(len({row["object_id"] for row in native_lexical}), 32)
        self.assertEqual(
            Counter(row["predicate_id"] for row in native_lexical),
            {"skos:exactMatch": 32, "skos:closeMatch": 58},
        )
        self.assertTrue(all(row["mapping_date"] == "2026-09-04" for row in rows))

    def test_unified_header_identifies_the_pinned_review_and_identity_refresh_writer(self):
        """Keep the original reviewed origin and name the actual bounded-update writer."""
        metadata = _metadata(UNIFIED)
        pin = load_release_pin(REPO_ROOT)
        self.assertEqual(metadata["mapping_tool"], "kg-microbe/scripts/consolidate_chemical_mappings.py")
        self.assertEqual(metadata["mapping_tool_version"], "sha256:" + IDENTITY_REFRESH_WRITER_SHA256)
        self.assertEqual(
            metadata["mapping_set_description"],
            "Conservative MIM candidate; reviewed manifest sha256:"
            + pin["manifest_sha256"]
            + ". Ingredient identity policy sha256:"
            + IDENTITY_POLICY_SHA256
            + ".",
        )
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
        """Stream counts, CAS endpoints and exact native provenance without another full scan."""
        entities = set()
        predicates = Counter()
        native_rows = Counter()
        self.assertEqual(_sha256(POTATO_SCOPE), POTATO_SCOPE_SHA256)
        potato_claim = json.loads(POTATO_SCOPE.read_text(encoding="utf-8"))["mapping_claims"]["unified"]["row"]
        self.assertEqual(len(potato_claim), 13)
        held_potato_row = _row_key(potato_claim)
        retained_potato_claims = 0
        # Full original claims predate this candidate; only the reviewed native
        # object-label replacement is licensed on the four retained synonyms.
        self.assertEqual(_sha256(P3556_SCOPE), P3556_SCOPE_SHA256)
        p3556_fixture = json.loads(P3556_SCOPE.read_text(encoding="utf-8"))
        p3556_originals = [claim["row"] for claim in p3556_fixture["mapping_claims"] if claim["table"] == "unified"]
        self.assertEqual(len(p3556_originals), 7)
        self.assertTrue(all(len(row) == 13 and row["object_id"] == "CHEBI:86658" for row in p3556_originals))
        p3556_original_keys = {_row_key(row) for row in p3556_originals}
        self.assertEqual(len(p3556_original_keys), 7)
        p3556_structured = [row for row in p3556_originals if row["source"] == "native_ontology:chebi"]
        self.assertEqual(len(p3556_structured), 4)
        self.assertTrue(all(row["comment"] == "synonym" for row in p3556_structured))
        self.assertIn(
            P3556_REVIEWED_LABEL,
            {entry["val"] for entry in p3556_fixture["native_structure"][0]["node"]["meta"]["synonyms"]},
        )
        expected_p3556 = Counter(
            _row_key({**row, "object_label": P3556_REVIEWED_LABEL}) for row in p3556_structured
        )
        retained_p3556_originals = Counter()
        relabelled_p3556 = Counter()
        prior_rows = list(_iter_sssom_rows(PRIOR_CLAIMS))
        prior_invalid = {
            _row_key(row)
            for row in prior_rows
            if any(invalid_cas_identifier(row[key]) for key in ("subject_id", "object_id"))
        }
        prior_lexical = {
            _row_key(row): row
            for row in prior_rows
            if row["source"] == "chebi_xrefs" and row["mapping_justification"] == "semapv:LexicalMatching"
        }
        targets = {row["object_id"] for row in prior_lexical.values()}
        # These 90 full lexical claims predate the candidate. Native evidence
        # adds only its reviewed source/date; no candidate rows seed expectations.
        expected_provenance = Counter(
            _row_key({**row, "source": "native_ontology:chebi", "mapping_date": "2026-09-24"})
            for row in prior_lexical.values()
        )
        retained_lexical = Counter()
        added_provenance = Counter()
        invalid_endpoints = Counter()
        retained_invalid = Counter()
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
            if row["object_id"] == potato_claim["object_id"] and _row_key(row) == held_potato_row:
                retained_potato_claims += 1
            if row["object_id"] == "CHEBI:86658":
                full_row = _row_key(row)
                if full_row in p3556_original_keys:
                    retained_p3556_originals[full_row] += 1
                if full_row in expected_p3556:
                    relabelled_p3556[full_row] += 1
            for key in ("subject_id", "object_id"):
                if invalid_cas_identifier(row[key]):
                    invalid_endpoints[(key, row[key])] += 1
            # Full-row counters retain duplicate multiplicity and extra fields.
            if row["object_id"] in targets or row["object_id"] == "cas:977046-75-5":
                full_row = _row_key(row)
                if full_row in prior_invalid:
                    retained_invalid[full_row] += 1
                if full_row in prior_lexical:
                    retained_lexical[full_row] += 1
                if row["object_id"] in targets and row["source"] == "native_ontology:chebi":
                    added_provenance[full_row] += 1
            if row["object_id"] in {"NCIT:C16883", "NCIT:C71939"}:
                native_rows[(row["subject_id"], row["predicate_id"], row["object_id"], row["object_category"])] += 1
        self.assertEqual(rows, 591946)
        self.assertEqual(len(entities), 120183)
        self.assertEqual(predicates, {"skos:exactMatch": 336048, "skos:closeMatch": 255898})
        self.assertEqual(predicates["skos:broadMatch"], 0)
        self.assertEqual(predicates["skos:narrowMatch"], 0)
        self.assertEqual(native_rows, expected_native_rows)
        self.assertFalse(invalid_endpoints)
        self.assertFalse(retained_invalid)
        self.assertEqual(retained_potato_claims, 0)
        self.assertFalse(retained_p3556_originals)
        self.assertEqual(relabelled_p3556, expected_p3556)
        self.assertEqual(retained_lexical, Counter({key: 1 for key in prior_lexical}))
        self.assertEqual(added_provenance, expected_provenance)
