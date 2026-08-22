"""Tests for the BacDive per-reference conflict report (#737)."""

import importlib.util
import sys
from pathlib import Path
from unittest import TestCase

_SPEC = importlib.util.spec_from_file_location(
    "bacdive_reference_conflicts",
    Path(__file__).resolve().parents[1] / "scripts" / "bacdive_reference_conflicts.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["bacdive_reference_conflicts"] = _MODULE
_SPEC.loader.exec_module(_MODULE)

# A slice of the real METPO oxygen-tolerance chain, synonyms included.
OWNERS = {
    "anaerobic": {"METPO:1000603"},
    "anaerobe": {"METPO:1000603"},
    "obligately anaerobic": {"METPO:1000607"},
    "obligate anaerobe": {"METPO:1000607"},
    "strictly anaerobic": {"METPO:1000611"},
    "microaerophilic": {"METPO:1000604"},
    "microaerophile": {"METPO:1000604"},
    # The real collision: 'yes'/'no' are claimed by both the motility and the
    # spore-formation axes (verified in metpo_nodes.tsv; 67 aliases collide).
    "yes": {"METPO:1000702", "METPO:1000871"},
    "no": {"METPO:1000703", "METPO:1000872"},
}
SUBSUMPTION = {
    "METPO:1000607": {"METPO:1000603"},
    "METPO:1000611": {"METPO:1000607", "METPO:1000603"},
}


class ObservationExtractionTest(TestCase):
    """Both BacDive block shapes must be read by one code path."""

    def test_a_list_of_per_reference_dicts(self):
        """The array shape #474 recovered."""
        block = [
            {"@ref": 1, "oxygen tolerance": "anaerobe"},
            {"@ref": 2, "oxygen tolerance": "obligate anaerobe"},
        ]
        self.assertEqual(
            _MODULE.observations(block, "oxygen tolerance"),
            [("1", "anaerobe"), ("2", "obligate anaerobe")],
        )

    def test_a_single_dict(self):
        """
        The shape PR #776 forgot in one of two branches (#793).

        Handling it here rather than at each call site is the point: it is one
        code path, so it cannot be right in one section and wrong in another.
        """
        self.assertEqual(
            _MODULE.observations({"@ref": 5523, "oxygen tolerance": "anaerobe"}, "oxygen tolerance"),
            [("5523", "anaerobe")],
        )

    def test_booleans_normalise_to_yes_no(self):
        """Motility and spore formation arrive as booleans in some records."""
        block = [{"@ref": 1, "motility": True}, {"@ref": 2, "motility": False}]
        self.assertEqual(_MODULE.observations(block, "motility"), [("1", "yes"), ("2", "no")])

    def test_entries_without_the_field_are_skipped_not_counted_as_empty(self):
        """A reference that says nothing about a field is not a disagreement with one that does."""
        block = [{"@ref": 1, "motility": "yes"}, {"@ref": 2, "gram stain": "positive"}]
        self.assertEqual(_MODULE.observations(block, "motility"), [("1", "yes")])


class ClassifyTest(TestCase):
    """Separating 'more specific' from 'contradictory' is the whole point."""

    def test_a_term_and_its_parent_is_specificity_not_conflict(self):
        """
        The case that inflates #737's headline number.

        A strain that is obligately anaerobic *is* anaerobic. Both edges are
        true, so picking one would discard a true statement.
        """
        self.assertEqual(
            _MODULE.classify({"anaerobe", "obligate anaerobe"}, "oxygen tolerance", OWNERS, SUBSUMPTION),
            "specificity",
        )

    def test_subsumption_is_transitive(self):
        """'strictly anaerobic' is two hops from 'anaerobic'; one hop is not enough."""
        self.assertEqual(
            _MODULE.classify({"anaerobe", "strictly anaerobic"}, "oxygen tolerance", OWNERS, SUBSUMPTION),
            "specificity",
        )

    def test_siblings_are_a_real_contradiction(self):
        """
        Neither subsumes the other, so the strain cannot be both.

        This is the majority of oxygen-tolerance disagreements, contrary to the
        assumption that subsumption explains most of #737.
        """
        self.assertEqual(
            _MODULE.classify({"anaerobe", "microaerophile"}, "oxygen tolerance", OWNERS, SUBSUMPTION),
            "contradiction",
        )

    def test_two_spellings_of_one_term_are_not_a_disagreement(self):
        """String inequality is not term inequality — resolve before comparing."""
        self.assertEqual(
            _MODULE.classify({"anaerobe", "anaerobic"}, "oxygen tolerance", OWNERS, SUBSUMPTION),
            "specificity",
        )

    def test_an_unmappable_value_is_unresolved_not_contradiction(self):
        """
        A colour has no METPO term, so the relation cannot be judged.

        Calling it a contradiction would report a curation gap as a data
        conflict — 1,196 `colony color` rows land here.
        """
        self.assertEqual(
            _MODULE.classify({"anaerobe", "beige"}, "colony color", OWNERS, SUBSUMPTION),
            "unresolved",
        )

    def test_no_ontology_means_unresolved_rather_than_a_guess(self):
        """Without the extracts the script must not assert conflicts it cannot check."""
        self.assertEqual(_MODULE.classify({"a", "b"}, "motility", {}, {}), "unresolved")


class FieldScopedResolutionTest(TestCase):
    """
    A synonym shared by two METPO terms must be resolved per field.

    67 METPO aliases are claimed by more than one CURIE, and the collisions land
    on exactly the yes/no fields: `yes` belongs to both METPO:1000702 (motile)
    and METPO:1000871 (spore forming). A single flat index judged every yes/no
    field on whichever axis sorted first.
    """

    def test_yes_resolves_to_motile_on_the_motility_field(self):
        """Scoping by axis is what makes the two fields mean different things."""
        self.assertEqual(_MODULE.resolve("yes", "motility", OWNERS), "METPO:1000702")

    def test_yes_resolves_to_spore_forming_on_the_spore_field(self):
        """Same string, different field, different term — the point of FIELD_AXIS."""
        self.assertEqual(_MODULE.resolve("yes", "spore formation", OWNERS), "METPO:1000871")

    def test_an_ambiguous_alias_on_an_unscoped_field_refuses_to_guess(self):
        """
        `forms multicellular complex` has no METPO terms at all.

        Before scoping, its yes/no values were judged on the motility axis —
        551 observations classified against terms that have nothing to do with
        the field. Refusing is the honest answer.
        """
        self.assertEqual(_MODULE.resolve("yes", "forms multicellular complex", OWNERS), "")
        self.assertEqual(
            _MODULE.classify({"yes", "no"}, "forms multicellular complex", OWNERS, SUBSUMPTION),
            "unresolved",
        )

    def test_a_scoped_field_still_yields_contradiction_for_real_opposites(self):
        """Scoping must not cost the verdicts that were already right."""
        self.assertEqual(
            _MODULE.classify({"yes", "no"}, "motility", OWNERS, SUBSUMPTION),
            "contradiction",
        )

    def test_an_unambiguous_alias_needs_no_axis(self):
        """Most values are claimed by exactly one term and resolve without scoping."""
        self.assertEqual(_MODULE.resolve("anaerobe", "oxygen tolerance", OWNERS), "METPO:1000603")
