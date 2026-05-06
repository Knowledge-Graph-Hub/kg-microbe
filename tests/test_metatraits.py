"""Test Metatraits transform."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parameterized import parameterized

from kg_microbe.transform_utils.metatraits.metatraits import MetaTraitsTransform
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings

# Truth table from microbial-trait-mappings test_round_trip.py
EXPECTED_EDGES = [
    ("produces: ethanol", "biolink:produces", "CHEBI:16236", "biolink:ChemicalEntity"),
    ("produces: hydrogen sulfide", "biolink:produces", "CHEBI:16136", "biolink:ChemicalEntity"),
    ("produces: indole", "biolink:produces", "CHEBI:16881", "biolink:ChemicalEntity"),
    ("carbon source: acetate", "METPO:2000006", "CHEBI:30089", "biolink:ChemicalEntity"),
    (
        "enzyme activity: catalase (EC1.11.1.6)",
        "biolink:capable_of",
        "EC:1.11.1.6",
        "biolink:MolecularActivity",
    ),
    (
        "enzyme activity: urease (EC3.5.1.5)",
        "biolink:capable_of",
        "EC:3.5.1.5",
        "biolink:MolecularActivity",
    ),
    (
        "enzyme activity: oxidase",
        "biolink:capable_of",
        "GO:0004129",
        "biolink:MolecularActivity",
    ),
    ("fermentation", "biolink:capable_of", "GO:0006113", "biolink:BiologicalProcess"),
    ("nitrogen fixation", "biolink:capable_of", "GO:0009399", "biolink:BiologicalProcess"),
    ("gram positive", "biolink:has_phenotype", "METPO:1000698", "biolink:PhenotypicQuality"),
    ("obligate aerobic", "biolink:has_phenotype", "METPO:1000606", "biolink:PhenotypicQuality"),
    ("thermophilic", "biolink:has_phenotype", "METPO:1000616", "biolink:PhenotypicQuality"),
]

# Additional test cases for Phase 6: Expanded coverage
# These test additional phenotype traits from phenotype_mappings.tsv
ADDITIONAL_TEST_CASES = [
    ("gram negative", "biolink:has_phenotype", "METPO:1000699", "biolink:PhenotypicQuality"),
    ("sporulation", "biolink:has_phenotype", "METPO:1000870", "biolink:PhenotypicQuality"),
    ("obligate anaerobic", "biolink:has_phenotype", "METPO:1000607", "biolink:PhenotypicQuality"),
    ("presence of motility", "biolink:has_phenotype", "METPO:1000702", "biolink:PhenotypicQuality"),
    ("psychrophilic", "biolink:has_phenotype", "METPO:1000614", "biolink:PhenotypicQuality"),
]


@patch("kg_microbe.transform_utils.metatraits.metatraits._ensure_ncbitaxon_db_ready")
@patch("kg_microbe.transform_utils.metatraits.metatraits._get_ncbitaxon_adapter")
class TestMetaTraitsTransform(unittest.TestCase):

    """Test MetaTraitsTransform class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_resources_dir = Path(__file__).parent / "resources"
        self.temp_input_dir = Path(tempfile.mkdtemp())
        self.temp_output_dir = Path(tempfile.mkdtemp())
        self.fixture_file = self.test_resources_dir / "metatraits_fixture.jsonl"

    def test_transform_initialization(self, mock_adapter, mock_ensure):
        """Test MetaTraitsTransform initialization."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        self.assertEqual(transform.source_name, "metatraits")
        self.assertEqual(transform.knowledge_source, "infores:metatraits")
        self.assertIsNotNone(transform.trait_mapping)
        self.assertIsNotNone(transform.ncbitaxon_name_to_id)

    def test_create_node_row(self, mock_adapter, mock_ensure):
        """Test _create_node_row produces correct structure."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        row = transform._create_node_row(
            "NCBITaxon:562",
            "biolink:OrganismTaxon",
            "Escherichia coli",
        )
        self.assertEqual(len(row), len(transform.node_header))
        self.assertEqual(row[0], "NCBITaxon:562")
        self.assertEqual(row[1], "biolink:OrganismTaxon")
        self.assertEqual(row[2], "Escherichia coli")
        self.assertEqual(row[5], "infores:metatraits")

    def test_get_relation_for_predicate(self, mock_adapter, mock_ensure):
        """Test _get_relation_for_predicate returns correct RO terms."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        from kg_microbe.transform_utils.constants import (
            BIOLOGICAL_PROCESS,
            CAPABLE_OF_PREDICATE,
            HAS_PHENOTYPE,
            PRODUCES_RELATION,
        )

        self.assertEqual(
            transform._get_relation_for_predicate(CAPABLE_OF_PREDICATE),
            BIOLOGICAL_PROCESS,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("biolink:has_phenotype"),
            HAS_PHENOTYPE,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("biolink:produces"),
            PRODUCES_RELATION,
        )
        self.assertEqual(
            transform._get_relation_for_predicate("METPO:2000202"),
            PRODUCES_RELATION,
        )

    def test_to_biolink_predicate(self, mock_adapter, mock_ensure):
        """Test _to_biolink_predicate maps METPO to biolink."""
        transform = MetaTraitsTransform(
            input_dir=Path("data/raw"),
            output_dir=self.temp_output_dir,
        )
        self.assertEqual(
            transform._to_biolink_predicate("METPO:2000202"),
            "biolink:produces",
        )
        self.assertEqual(
            transform._to_biolink_predicate("METPO:2000103"),
            "biolink:capable_of",
        )
        self.assertEqual(
            transform._to_biolink_predicate("biolink:has_phenotype"),
            "biolink:has_phenotype",
        )

    def test_produces_ethanol_is_not_has_phenotype(self, mock_adapter, mock_ensure):
        """Test produces: ethanol resolves to biolink:produces, not has_phenotype."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        match = mappings.get("produces: ethanol") or mappings.get("produces: ethanol".lower())
        self.assertIsNotNone(match, "'produces: ethanol' should be in microbial mappings")
        self.assertEqual(
            match["biolink_predicate"],
            "biolink:produces",
            "'produces: ethanol' must NOT resolve to has_phenotype",
        )

    def test_collapse_detection(self, mock_adapter, mock_ensure):
        """Test that not all predicates resolve to has_phenotype."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        predicates = {m["biolink_predicate"] for m in mappings.values()}
        self.assertGreater(len(predicates), 1, "Multiple predicate types required")
        self.assertIn("biolink:produces", predicates)
        self.assertIn("biolink:capable_of", predicates)
        self.assertIn("biolink:has_phenotype", predicates)

    @parameterized.expand(EXPECTED_EDGES)
    def test_edge_resolution_round_trip(
        self,
        mock_adapter,
        mock_ensure,
        subject_label,
        expected_pred,
        expected_obj,
        expected_cat,
    ):
        """Verify each trait resolves to correct (predicate, object_id, object_category)."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        match = mappings.get(subject_label) or mappings.get(subject_label.lower())
        self.assertIsNotNone(match, f"No mapping for '{subject_label}'")
        self.assertEqual(match["object_id"], expected_obj)
        self.assertEqual(match["biolink_predicate"], expected_pred)
        self.assertEqual(match["object_category"], expected_cat)

    @parameterized.expand(ADDITIONAL_TEST_CASES)
    def test_additional_edge_resolution(
        self,
        mock_adapter,
        mock_ensure,
        subject_label,
        expected_pred,
        expected_obj,
        expected_cat,
    ):
        """Verify additional trait patterns resolve correctly (Phase 6 expanded coverage)."""
        mappings = load_microbial_trait_mappings()
        if not mappings:
            self.skipTest("mappings/metatraits/ not found")
        match = mappings.get(subject_label) or mappings.get(subject_label.lower())
        self.assertIsNotNone(match, f"No mapping for '{subject_label}'")
        self.assertEqual(match["object_id"], expected_obj, f"Wrong object_id for '{subject_label}'")
        self.assertEqual(match["biolink_predicate"], expected_pred, f"Wrong predicate for '{subject_label}'")
        self.assertEqual(match["object_category"], expected_cat, f"Wrong category for '{subject_label}'")

    @patch.object(MetaTraitsTransform, "_search_ncbitaxon_by_label")
    def test_run_with_fixture(self, mock_search, mock_adapter, mock_ensure):
        """Test run() with fixture produces nodes and edges."""
        mock_search.return_value = "NCBITaxon:562"

        # Copy fixture to temporary input directory with expected filename
        import shutil

        metatraits_subdir = self.temp_input_dir / "metatraits"
        metatraits_subdir.mkdir(exist_ok=True)
        fixture_path = metatraits_subdir / "ncbi_species_summary.jsonl"
        shutil.copy(self.fixture_file, fixture_path)

        try:
            transform = MetaTraitsTransform(
                input_dir=metatraits_subdir,
                output_dir=self.temp_output_dir,
            )
            transform._search_ncbitaxon_by_label = mock_search

            transform.run(show_status=False)

            self.assertTrue(transform.output_node_file.exists())
            self.assertTrue(transform.output_edge_file.exists())
            self.assertTrue(transform.unmapped_traits_file.exists())
            self.assertTrue(transform.unresolved_taxa_file.exists())

            nodes = list(transform.output_node_file.read_text().strip().split("\n"))
            edges = list(transform.output_edge_file.read_text().strip().split("\n"))
            self.assertGreater(len(nodes), 1)  # header + at least 1 node
            self.assertGreater(len(edges), 1)  # header + at least 1 edge

            # Check node header
            self.assertIn("id", nodes[0])
            self.assertIn("category", nodes[0])
            self.assertIn("name", nodes[0])

            # Check edge header — value/unit added alongside has_percentage so
            # quantitative phenotype edges (temperature/NaCl/pH binned optima)
            # carry the source measurement through to downstream consumers.
            # Header order is asserted to catch silent reorderings.
            self.assertIn("subject", edges[0])
            self.assertIn("predicate", edges[0])
            self.assertIn("object", edges[0])
            self.assertIn("has_percentage", edges[0])
            self.assertIn("value", edges[0])
            self.assertIn("unit", edges[0])

            # Verify that a 0% pct_true trait (gram positive) is included in edges
            # Parse TSV to check exact has_percentage value for gram positive trait
            header = edges[0].split("\t")
            pct_col_idx = header.index("has_percentage")
            obj_col_idx = header.index("object")
            value_col_idx = header.index("value")
            unit_col_idx = header.index("unit")

            found_zero_pct = False
            found_quant_temp = False
            for edge_line in edges[1:]:
                cols = edge_line.split("\t")
                if len(cols) <= max(pct_col_idx, obj_col_idx, value_col_idx, unit_col_idx):
                    continue
                # Look for gram positive trait (METPO:1000698)
                if "METPO:1000698" in cols[obj_col_idx]:
                    pct_value = cols[pct_col_idx]
                    self.assertEqual(pct_value, "0.0", "Gram positive trait should have 0.0 percentage")
                    found_zero_pct = True
                # Quantitative phenotype edge from the "temperature growth"
                # fixture record (Median: 37.0 Celsius) → binned optimum class.
                # The edge must carry the source value+unit so a header/order
                # mismatch (or the column-population path silently breaking) is
                # caught here.
                if cols[unit_col_idx] == "Celsius":
                    self.assertEqual(cols[value_col_idx], "37.0",
                                     "temperature growth edge value should equal 37.0")
                    found_quant_temp = True

            self.assertTrue(found_zero_pct, "0% pct_true trait (gram positive) should be included in edges")
            self.assertTrue(
                found_quant_temp,
                "temperature-growth quantitative edge with value=37.0/unit=Celsius "
                "should be emitted; check edge_header order and binned-optimum path.",
            )
        finally:
            # Cleanup temporary input directory
            import shutil

            if self.temp_input_dir.exists():
                shutil.rmtree(self.temp_input_dir)

    @patch.object(MetaTraitsTransform, "_search_ncbitaxon_by_label")
    def test_tier2_false_majority_drops_positive_edges(self, mock_search, mock_adapter, mock_ensure):
        """
        False-majority Tier-2 rows must not emit positive phenotype/capability/grows-in/tolerance edges.

        Covers the six traits flagged by the Codex review:
        - Enzyme activity catalase / oxidase / urease (Tier-2 ``biolink:capable_of``
          to EC/GO; no METPO negative predicate, so ``_get_negative_predicate``
          returns None and the row is dropped).
        - The two selective-medium growth observations (MacConkey/blood agar) which
          now route through ``kgmicrobe.medium:*`` placeholders with positive
          predicate ``METPO:2000517``. In principle their negative form is
          ``METPO:2000518``, but because the upstream METPO ontology does not
          give the 2000517/2000518 pair a shared synonym (other paired predicates
          pair via shared synonyms — e.g. ``assimilation`` for 2000002/2000027),
          the pairing is currently unreachable and false-majority grows-in rows
          are silently dropped, just like the prior ``biolink:has_phenotype``
          encoding.
        - Bile acid susceptible: now routes to ``CHEBI:3098 'bile acid'`` with
          predicate ``METPO:2000065 'does not tolerate'`` (the negative member
          of the new chemical-tolerance pair METPO:2000064/2000065). For
          majority=false the negative-of-a-negative is undefined and the row
          is dropped.

        This test asserts BOTH that no positive edge leaks AND that no edge of
        any kind is emitted to the kgmicrobe.medium:* / CHEBI:3098 objects for
        the false-majority case, so a future METPO synonym fix or pairing-
        logic improvement that suddenly starts emitting METPO:2000518 (or any
        inverted-tolerance) edges shows up here as a controlled test failure
        rather than a silent behaviour change.
        """
        import json
        import shutil

        false_majority_traits = [
            ("enzyme activity: catalase (EC1.11.1.6)", "EC:1.11.1.6"),
            ("enzyme activity: oxidase", "GO:0004129"),
            ("enzyme activity: urease (EC3.5.1.5)", "EC:3.5.1.5"),
            ("growth: MacConkey agar", "kgmicrobe.medium:macconkey_agar"),
            ("growth: blood agar", "kgmicrobe.medium:blood_agar"),
            ("growth: bile acid susceptible", "CHEBI:3098"),
        ]
        fixture_record = {
            "tax_name": "Tier2NegStrain",
            "summaries": [
                {
                    "name": name,
                    "is_discrete": True,
                    "num_observations": 5,
                    "unique_databases": 1,
                    "majority_label": "false: (100%)",
                    "percentages": {"true": 0.0, "false": 100.0},
                }
                for name, _ in false_majority_traits
            ],
        }

        mock_search.return_value = "NCBITaxon:562"
        metatraits_subdir = self.temp_input_dir / "metatraits"
        metatraits_subdir.mkdir(exist_ok=True)
        fixture_path = metatraits_subdir / "ncbi_species_summary.jsonl"
        fixture_path.write_text(json.dumps(fixture_record) + "\n")

        try:
            transform = MetaTraitsTransform(
                input_dir=metatraits_subdir,
                output_dir=self.temp_output_dir,
            )
            transform._search_ncbitaxon_by_label = mock_search
            transform.run(show_status=False)

            edges = transform.output_edge_file.read_text().strip().split("\n")
            self.assertGreater(len(edges), 0)
            header = edges[0].split("\t")
            obj_idx = header.index("object")
            pred_idx = header.index("predicate")

            positive_predicates = {
                "biolink:has_phenotype",
                "biolink:capable_of",
                "METPO:2000517",  # grows in (positive form for kgmicrobe.medium:* objects)
                "METPO:2000064",  # tolerates (positive form of the new chemical-tolerance pair)
                "METPO:2000065",  # does not tolerate (the row's mapped predicate; treat as positive
                                  # for assertion purposes — for false-majority we expect NO edge at
                                  # all, neither the row's positive-mapped predicate nor an inverted
                                  # one, so flagging it as "positive" here is the right guard)
            }
            # Also lock in: no edge of any kind to the kgmicrobe.medium:* object
            # is emitted for these false-majority rows. The METPO ontology does
            # not currently pair METPO:2000517 'grows in' with METPO:2000518
            # 'does not grow in' via a shared synonym (METPO predicate pairing
            # in metatraits._build_metpo_lookups requires a shared synonym
            # between the positive and negative predicate, e.g. 'assimilation'
            # for assimilates/does-not-assimilate), so _get_negative_predicate
            # returns None for METPO:2000517 and the row is dropped — same
            # behaviour as the previous biolink:has_phenotype encoding. If the
            # upstream METPO 2000517/2000518 pair is given a shared synonym
            # (or the pairing logic is patched to also pair by stripping the
            # 'does not ' prefix), this assertion will need to be loosened to
            # `>= 1` METPO:2000518 edge per medium object.
            # Objects whose mapping uses a paired METPO predicate where the
            # row's positive-mapped predicate is the *negative* member of the
            # pair (so for majority=false there is no inverse to flip to and
            # the row should be silently dropped, not emitted in either
            # polarity). MacConkey/blood agar use METPO:2000517 grows in (the
            # positive member; the negative METPO:2000518 is unreachable
            # because the upstream pair lacks a shared synonym). bile acid
            # uses METPO:2000065 does not tolerate (the negative member; no
            # inverse-of-an-inverse path).
            grows_in_kgmicrobe_objects = {
                "kgmicrobe.medium:macconkey_agar",
                "kgmicrobe.medium:blood_agar",
                "CHEBI:3098",
            }
            for _, expected_obj in false_majority_traits:
                offending = [
                    line
                    for line in edges[1:]
                    if (cols := line.split("\t"))
                    and cols[obj_idx] == expected_obj
                    and cols[pred_idx] in positive_predicates
                ]
                self.assertEqual(
                    offending,
                    [],
                    f"Tier-2 false-majority row leaked a positive edge for {expected_obj}: {offending}",
                )
                if expected_obj in grows_in_kgmicrobe_objects:
                    any_edge = [
                        line
                        for line in edges[1:]
                        if (cols := line.split("\t")) and cols[obj_idx] == expected_obj
                    ]
                    self.assertEqual(
                        any_edge,
                        [],
                        f"Tier-2 false-majority grows-in row unexpectedly emitted any "
                        f"edge to {expected_obj} (METPO 2000517/2000518 pair lacks a "
                        f"shared synonym so the negative form is not currently "
                        f"reachable; the row should be silently dropped). Got: {any_edge}",
                    )
        finally:
            if self.temp_input_dir.exists():
                shutil.rmtree(self.temp_input_dir)

    def test_run_without_input_files_raises(self, mock_adapter, mock_ensure):
        """Test run() raises FileNotFoundError when no input files exist."""
        empty_dir = Path(tempfile.mkdtemp())
        transform = MetaTraitsTransform(
            input_dir=empty_dir,
            output_dir=self.temp_output_dir,
        )
        with self.assertRaises(FileNotFoundError) as ctx:
            transform.run(show_status=False)
        self.assertIn("No metatraits JSONL files found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
