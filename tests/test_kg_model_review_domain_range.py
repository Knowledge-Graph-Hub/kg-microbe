"""The reviewer's domain/range check must read the pinned model, and say which rule spoke (#1011)."""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / ".claude" / "skills" / "kg-model-review" / "kg_model_review.py"


def _load():
    """
    Import the standalone skill script as a module.

    :return: The module.
    """
    spec = importlib.util.spec_from_file_location("kg_model_review", SKILL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kg_model_review"] = mod
    spec.loader.exec_module(mod)
    return mod


def _node(nid, cat):
    """Minimal node row."""
    return {"id": nid, "category": cat}


def _edge(s, p, o):
    """Minimal edge row."""
    return {"subject": s, "predicate": p, "object": o}


PINNED_MODEL = REPO_ROOT / "data" / "raw" / "biolink-model.yaml"


@unittest.skipUnless(PINNED_MODEL.is_file(), "pinned Biolink model not downloaded")
class DomainRangeFromTheModelTests(unittest.TestCase):
    """Verdicts come from the pinned model; house rules are visible, not silent."""

    @classmethod
    def setUpClass(cls):
        """
        Load the skill against the pinned model, not the conftest's minimal fixture.

        ``tests/conftest.py`` points ``KG_MICROBE_BIOLINK_MODEL`` at a minimal
        schema that defines neither ``enables`` nor ``has_phenotype``; these
        tests are about what the real pinned model says.
        """
        import os

        cls._saved = {k: os.environ.get(k) for k in ("KG_MICROBE_BIOLINK_MODEL", "KG_MICROBE_BIOLINK_PREDICATE_MAP")}
        os.environ["KG_MICROBE_BIOLINK_MODEL"] = str(PINNED_MODEL)
        os.environ["KG_MICROBE_BIOLINK_PREDICATE_MAP"] = str(REPO_ROOT / "data" / "raw" / "predicate_mapping.yaml")
        cls.mod = _load()

    @classmethod
    def tearDownClass(cls):
        """Restore the conftest environment for the rest of the suite."""
        import os

        for k, v in cls._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run(self, nodes, edges, verbose=True):
        """
        Run the check and index findings by severity.

        :param nodes: Node rows.
        :param edges: Edge rows.
        :param verbose: Whether to request examples.
        :return: ``{severity: [Finding, ...]}``.
        """
        out = {}
        for f in self.mod.check_domain_range(nodes, edges, verbose):
            out.setdefault(f.severity, []).append(f)
        return out

    def test_an_organism_located_in_an_ecosystem_is_not_a_violation(self):
        """
        The #1011 false positive.

        A hand-written row gave located_in the domain {BiologicalEntity,
        Protein, Gene}; the model says named thing → named thing, so gold's
        228,762 organism → ecosystem edges are conformant.
        """
        nodes = [
            _node("NCBITaxon:1000569", "biolink:OrganismTaxon"),
            _node("gold.ecosystem:3381", "biolink:EnvironmentalFeature"),
        ]
        out = self._run(nodes, [_edge("NCBITaxon:1000569", "biolink:located_in", "gold.ecosystem:3381")])
        self.assertNotIn("WARNING", out, out)

    def test_a_molecular_activity_enabling_something_violates_the_model_and_says_so(self):
        """`enables` has domain physical entity; a bare MolecularActivity subject is not one (#645)."""
        nodes = [_node("RHEA:10000", "biolink:MolecularActivity"), _node("GO:0050168", "biolink:MolecularActivity")]
        out = self._run(nodes, [_edge("RHEA:10000", "biolink:enables", "GO:0050168")])
        self.assertIn("WARNING", out)
        self.assertIn("[model]", out["WARNING"][0].examples[0])

    def test_an_ec_node_typed_protein_passes_only_by_house_rule_and_says_so(self):
        """
        In the pinned 4.4.2 model `enables` has domain physical entity, and Protein is not one.

        EC nodes carry MolecularActivity|Protein by convention (#645); the
        edge is allowed, but as a counted, named house rule -- not silently.
        """
        nodes = [
            _node("EC:1.1.1.1", "biolink:MolecularActivity|biolink:Protein"),
            _node("GO:0004022", "biolink:MolecularActivity"),
        ]
        out = self._run(nodes, [_edge("EC:1.1.1.1", "biolink:enables", "GO:0004022")])
        self.assertNotIn("WARNING", out, out)
        info = [f for f in out.get("INFO", []) if "house allowance" in f.message]
        self.assertEqual(len(info), 1)
        self.assertIn("#645", info[0].examples[0])

    def test_a_house_allowance_is_counted_not_hidden(self):
        """
        has_phenotype → PhenotypicQuality fails the model (range PhenotypicFeature).

        The house rule lets it through, but as an INFO that names the rule and
        the count -- #643's 2.1M edges stay visible.
        """
        nodes = [_node("NCBITaxon:562", "biolink:OrganismTaxon"), _node("METPO:1000615", "biolink:PhenotypicQuality")]
        out = self._run(nodes, [_edge("NCBITaxon:562", "biolink:has_phenotype", "METPO:1000615")])
        self.assertNotIn("WARNING", out, out)
        info = [f for f in out.get("INFO", []) if "house allowance" in f.message]
        self.assertEqual(len(info), 1)
        self.assertIn("#643/#1000", info[0].examples[0])

    def test_a_metpo_predicate_is_judged_by_the_hand_table_and_labelled(self):
        """METPO has no machine-readable domain/range; the table speaks, and says so."""
        nodes = [_node("NCBITaxon:562", "biolink:OrganismTaxon"), _node("GO:0008150", "biolink:BiologicalProcess")]
        out = self._run(nodes, [_edge("NCBITaxon:562", "METPO:2000006", "GO:0008150")])
        self.assertIn("WARNING", out)
        self.assertIn("[table]", out["WARNING"][0].examples[0])

    def test_the_renderer_prints_every_example_the_check_returned(self):
        """The checker returned all six constraints; the markdown renderer used to print three."""
        finding = self.mod.Finding("WARNING", "DomainRange", "six constraints", [f"constraint {i}" for i in range(6)])
        rendered = finding.render() if hasattr(finding, "render") else str(finding)
        for i in range(6):
            self.assertIn(f"constraint {i}", rendered)

    def test_verbose_lists_every_constraint_not_the_first_five(self):
        """A release reviewer needs all of them; the old cap hid three of six."""
        cats = [
            "biolink:MolecularActivity",
            "biolink:BiologicalProcess",
            "biolink:Pathway",
            "biolink:PhysiologicalProcess",
            "biolink:Behavior",
            "biolink:Occurrent",
        ]
        nodes = [_node(f"S:{i}", c) for i, c in enumerate(cats)] + [_node("GO:1", "biolink:MolecularActivity")]
        edges = [_edge(f"S:{i}", "biolink:enables", "GO:1") for i in range(len(cats))]
        out = self._run(nodes, edges)
        self.assertEqual(len(out["WARNING"][0].examples), len(cats))


if __name__ == "__main__":
    unittest.main()
