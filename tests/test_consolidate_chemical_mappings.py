r"""
Tests for the chemical mappings consolidator script.

Focused on ``extract_curie``: the prefix-preserving extractor introduced to
fix the regression where ``extract_chebi_id``'s ``re.search(r"(\d+)", v)``
silently rewrote FOODON / UBERON / PubChem / CAS-RN ids in the heterogeneous
``mapped`` column to ``CHEBI:<numeric_tail>`` (see
CultureBotHT/docs/AUDIT_TRAIL.md). Worst case is the colliding rewrite
``CAS-RN:51142-18-8`` -> ``CHEBI:51142``, which references a real but
unrelated ChEBI entity.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "consolidate_chemical_mappings.py"


def _load_module():
    """Load the consolidator script as an importable module for tests."""
    spec = importlib.util.spec_from_file_location(
        "consolidate_chemical_mappings", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


class ExtractCurieTests(unittest.TestCase):

    """``extract_curie`` preserves accepted prefixes and rejects everything else."""

    @classmethod
    def setUpClass(cls):
        """Load the consolidator module once per test class."""
        cls.mod = _load_module()

    def test_preserves_ontology_prefixes(self):
        """Ontology CURIEs (FOODON/UBERON/ENVO/NCIT) pass through unchanged."""
        for raw in ("FOODON:03315426", "UBERON:0000178", "ENVO:00002007", "NCIT:C12345"):
            self.assertEqual(self.mod.extract_curie(raw), raw)

    def test_preserves_chebi(self):
        """CHEBI ids pass through unchanged."""
        self.assertEqual(self.mod.extract_curie("CHEBI:16236"), "CHEBI:16236")

    def test_normalises_pubchem_aliases(self):
        """PubChem spelling variants normalise to canonical pubchem.compound."""
        for raw in (
            "PubChem:167312541",
            "PUBCHEM:167312541",
            "PUBCHEM.COMPOUND:167312541",
            "Pubchem:167312541",
        ):
            self.assertEqual(
                self.mod.extract_curie(raw),
                "pubchem.compound:167312541",
                f"failed on {raw!r}",
            )

    def test_normalises_cas_aliases(self):
        """CAS-RN/CAS aliases normalise to canonical cas without numeric mangling."""
        # The colliding case: CAS-RN:51142-18-8 must NOT become CHEBI:51142.
        self.assertEqual(self.mod.extract_curie("CAS-RN:51142-18-8"), "cas:51142-18-8")
        self.assertEqual(self.mod.extract_curie("CAS:51142-18-8"), "cas:51142-18-8")

    def test_lowercase_ontology_prefix_normalised(self):
        """Lowercase ontology prefixes normalise to upper-case canonical form."""
        self.assertEqual(self.mod.extract_curie("chebi:16236"), "CHEBI:16236")
        self.assertEqual(self.mod.extract_curie("foodon:03315426"), "FOODON:03315426")

    def test_rejects_bare_digits(self):
        """Bare numeric strings are not reinterpreted as CHEBI."""
        # The mangling regex's input shape — a plain numeric string — must
        # NOT be reinterpreted as CHEBI here.
        self.assertEqual(self.mod.extract_curie("51142"), "")
        self.assertEqual(self.mod.extract_curie("51142-18-8"), "")

    def test_rejects_unknown_prefix(self):
        """CURIEs with unrecognised prefixes are rejected (return empty)."""
        self.assertEqual(self.mod.extract_curie("KEGG:C00031"), "")
        self.assertEqual(self.mod.extract_curie("FOO:bar"), "")

    def test_handles_empty_and_missing(self):
        """Empty / whitespace / NA / None inputs return empty without raising."""
        import pandas as pd

        self.assertEqual(self.mod.extract_curie(""), "")
        self.assertEqual(self.mod.extract_curie("   "), "")
        self.assertEqual(self.mod.extract_curie(pd.NA), "")
        self.assertEqual(self.mod.extract_curie(None), "")


class IsMangledChebiTests(unittest.TestCase):

    """``is_mangled_chebi_id`` recognises pre-fix mangler outputs."""

    @classmethod
    def setUpClass(cls):
        """Load the consolidator module once per test class."""
        cls.mod = _load_module()

    def test_leading_zero_is_mangled(self):
        """FOODON/UBERON values rewritten to CHEBI:0NNNN are mangled."""
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:03315426"))
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:0000178"))

    def test_pubchem_watermark_is_mangled(self):
        """CHEBI ids >= 1_000_000 are PubChem CIDs misrouted to CHEBI:."""
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:167312541"))
        self.assertTrue(self.mod.is_mangled_chebi_id("CHEBI:1000000"))
        # 999_999 is borderline; current threshold rejects only >=1M.
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:999999"))

    def test_blacklist_only_drops_with_safe_sources(self):
        """Blacklist hits are dropped only when sources are auto-mappers."""
        bl = {"CHEBI:8013", "CHEBI:51142"}
        # mediadive_compounds source → drop
        self.assertTrue(self.mod.is_mangled_chebi_id(
            "CHEBI:8013", "mediadive_compounds", bl,
        ))
        # mixed-with-curated → keep (small CHEBI ids may be legitimate)
        self.assertFalse(self.mod.is_mangled_chebi_id(
            "CHEBI:8013", "mediadive_compounds|mediaingredientmech_reviewed", bl,
        ))
        # not in blacklist, sources auto → keep
        self.assertFalse(self.mod.is_mangled_chebi_id(
            "CHEBI:99999", "mediadive_compounds", bl,
        ))

    def test_real_chebi_passes(self):
        """Real CHEBI ids in the 4-6 digit range with no blacklist hit pass."""
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:16236"))  # ethanol
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:26710"))  # NaCl
        self.assertFalse(self.mod.is_mangled_chebi_id("CHEBI:78020"))  # casamino acids

    def test_non_chebi_ignored(self):
        """Non-CHEBI ids are never flagged."""
        self.assertFalse(self.mod.is_mangled_chebi_id("FOODON:03315426"))
        self.assertFalse(self.mod.is_mangled_chebi_id("pubchem.compound:167312541"))
        self.assertFalse(self.mod.is_mangled_chebi_id("cas:8013-01-2"))


class LoaderFilteringTests(unittest.TestCase):

    """
    Loader-side filtering tests.

    Exercises the filtering paths the unit tests on ``is_mangled_chebi_id``
    alone do not cover: a typo in source-label matching or skip logic could
    silently discard legitimate mappings or keep polluted ones. We feed each
    loader a hand-crafted fixture that mixes clean rows, FOODON/UBERON-style
    mangles, PubChem-watermark mangles, blacklist-with-auto-source rows, and
    blacklist-with-curated-source rows, then assert which ids end up in
    ``consolidator.chemicals``.
    """

    @classmethod
    def setUpClass(cls):
        """Load the consolidator module once per test class."""
        cls.mod = _load_module()

    def _make_consolidator(self, mangle_blacklist=None):
        c = self.mod.ChemicalMappingConsolidator()
        if mangle_blacklist is not None:
            c.mangle_blacklist = set(mangle_blacklist)
        return c

    def test_load_compound_mappings_filters_mangles(self):
        """Pre-mangled CHEBI:>=1M in ``mapped`` is dropped, real ids kept."""
        import tempfile

        rows = [
            # (original, mapped, chebi_id, chebi_label) -> expected primary id
            # 1. real CHEBI in chebi_id → kept as CHEBI
            ("water",        "",                  "CHEBI:15377", "water"),
            # 2. real CHEBI in mapped (chebi_id empty) → kept as CHEBI
            ("ethanol",      "CHEBI:16236",       "",            "ethanol"),
            # 3. PubChem in mapped → routed to pubchem.compound
            ("dummy_pubchem","PubChem:135398658", "",            ""),
            # 4. CAS-RN in mapped → routed to cas:
            ("dummy_cas",    "CAS-RN:7647-14-5",  "",            ""),
            # 5. FOODON in mapped → kept as FOODON
            ("yeast_extract","FOODON:00002441",   "",            ""),
            # 6. pre-mangled CHEBI:>=1M in mapped → DROPPED by source-loader guard
            ("Tris-HCl",     "CHEBI:1185531",     "",            ""),
            # 7. pre-mangled CHEBI:0... in mapped → DROPPED (leading-zero rule)
            ("foodon_mangle","CHEBI:03315426",    "",            ""),
        ]

        header = (
            "medium_id\toriginal\tmapped\tchebi_label\tchebi_formula\tvalue\t"
            "concentration\tunit\tmmol_l\toptional\tsource\t"
            "normalized_compound\thydration_number\tchebi_match\tchebi_id\t"
            "chebi_original_name\tsimilarity_score\tmatch_confidence\t"
            "matching_method\tmapping_status\tmapping_quality\tbase_compound\t"
            "base_formula\twater_molecules\thydrate_formula\tbase_chebi_id\t"
            "base_chebi_label\tbase_chebi_formula\thydration_state\t"
            "hydration_parsing_method\thydration_confidence\t"
            "base_compound_for_mapping\tbase_molecular_weight\t"
            "water_molecular_weight\thydrated_molecular_weight\t"
            "corrected_mmol_l\n"
        )
        # Index of needed columns in the header (others left blank).
        cols = header.rstrip("\n").split("\t")

        def render_row(original, mapped, chebi_id, chebi_label):
            d = {c: "" for c in cols}
            d["medium_id"] = "test_medium"
            d["original"] = original
            d["mapped"] = mapped
            d["chebi_id"] = chebi_id
            d["chebi_label"] = chebi_label
            return "\t".join(d[c] for c in cols) + "\n"

        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
            fh.write(header)
            for r in rows:
                fh.write(render_row(*r))
            tmp_path = fh.name

        c = self._make_consolidator(mangle_blacklist=set())
        c.load_compound_mappings(self.mod.Path(tmp_path))

        ids = set(c.chemicals.keys())
        self.assertIn("CHEBI:15377", ids, "real CHEBI from chebi_id column dropped")
        self.assertIn("CHEBI:16236", ids, "real CHEBI from mapped column dropped")
        self.assertIn("pubchem.compound:135398658", ids, "PubChem id mangled or dropped")
        self.assertIn("cas:7647-14-5", ids, "CAS-RN id mangled or dropped")
        self.assertIn("FOODON:00002441", ids, "FOODON id mangled or dropped")
        self.assertNotIn("CHEBI:1185531", ids,
                         "pre-mangled CHEBI:>=1M leaked through load_compound_mappings")
        self.assertNotIn("CHEBI:03315426", ids,
                         "leading-zero CHEBI mangle leaked through load_compound_mappings")

    def test_load_existing_unified_filters_mangles_from_sssom(self):
        """SSSOM baseline loader drops mangled CHEBIs but keeps curated rows."""
        import gzip
        import tempfile

        # Minimal SSSOM with the columns load_existing_unified consumes.
        # _read_sssom_records groups rows by object_id, so we emit one xref
        # row per entity. Sources column drives the mangle source-restriction.
        sssom_header = (
            "# curie_map:\n"
            "#   CHEBI: \"http://purl.obolibrary.org/obo/CHEBI_\"\n"
            "#   FOODON: \"http://purl.obolibrary.org/obo/FOODON_\"\n"
            "#   skos: \"http://www.w3.org/2004/02/skos/core#\"\n"
            "#   semapv: \"https://w3id.org/semapv/vocab/\"\n"
            "# mapping_set_id: \"https://example.org/test\"\n"
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tobject_formula\tobject_category\t"
            "mapping_justification\tcomment\tsource\n"
        )

        rows = [
            # 1. clean CHEBI with auto source → kept
            ("CHEBI:15377", "water", "CHEBI:15377", "water", "H2O",
             "biolink:ChemicalSubstance", "mediadive_compounds"),
            # 2. mangled CHEBI:0... → DROPPED (leading-zero rule)
            ("CHEBI:03315426", "yeast extract", "CHEBI:03315426", "yeast extract", "",
             "biolink:ChemicalSubstance", "mediadive_compounds"),
            # 3. mangled CHEBI:>=1M → DROPPED (PubChem watermark)
            ("CHEBI:1185531", "Tris-HCl", "CHEBI:1185531", "Tris-HCl", "",
             "biolink:ChemicalSubstance", "mediadive_compounds"),
            # 4. blacklist-hit CHEBI with auto source only → DROPPED
            ("CHEBI:8013", "yeast extract", "CHEBI:8013", "yeast extract", "",
             "biolink:ChemicalSubstance", "mediadive_compounds"),
            # 5. blacklist-hit CHEBI with curated source → KEPT (small real CHEBI ids
            #    may legitimately collide with a CAS-RN first-numeric block)
            ("CHEBI:7732", "(?)", "CHEBI:7732", "test entry",  "",
             "biolink:ChemicalSubstance", "mediaingredientmech_reviewed"),
        ]

        def render(row):
            sid, slabel, oid, olabel, formula, category, source_tag = row
            return "\t".join([
                sid, slabel, "skos:exactMatch", oid, olabel,
                formula, category, "semapv:LexicalMatching", "", source_tag,
            ]) + "\n"

        with tempfile.NamedTemporaryFile("wb", suffix=".sssom.tsv.gz",
                                          delete=False) as fh:
            tmp_path = fh.name
        with gzip.open(tmp_path, "wt", encoding="utf-8") as gz:
            gz.write(sssom_header)
            for r in rows:
                gz.write(render(r))

        c = self._make_consolidator(mangle_blacklist={"CHEBI:8013", "CHEBI:7732"})
        c.load_existing_unified(self.mod.Path(tmp_path))

        ids = set(c.chemicals.keys())
        self.assertIn("CHEBI:15377", ids, "clean CHEBI dropped from SSSOM baseline")
        self.assertNotIn("CHEBI:03315426", ids,
                         "leading-zero mangle leaked through SSSOM baseline")
        self.assertNotIn("CHEBI:1185531", ids,
                         "PubChem-watermark mangle leaked through SSSOM baseline")
        self.assertNotIn("CHEBI:8013", ids,
                         "blacklist mangle with auto source not dropped")
        self.assertIn("CHEBI:7732", ids,
                      "blacklist hit with curated source incorrectly dropped")


if __name__ == "__main__":
    unittest.main()
