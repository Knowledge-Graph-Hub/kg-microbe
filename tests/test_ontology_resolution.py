"""Focused tests for ontology category policy without databases or network."""

from kg_microbe.utils.ontology_resolution import (
    chebi_category,
    go_category_for_namespace,
    ncbitaxon_category,
    replace_category_by_prefix,
    replace_deprecated_category_names,
    uberon_category,
)


class FakeAdapter:
    """Small injected ChEBI view for deterministic policy tests."""

    def __init__(self, *, ancestors=(), label=None, parents=()):
        """Store the explicit lookup results returned by this fake."""
        self._ancestors = ancestors
        self._label = label
        self._parents = parents

    def ancestors(self, _term_id):
        """Return configured ancestors."""
        return self._ancestors

    def label(self, _term_id):
        """Return the configured preferred label."""
        return self._label

    def relationships(self, _term_id, predicates):
        """Return configured direct parents as OAK-shaped relationships."""
        assert predicates == ["rdfs:subClassOf"]
        return [(None, None, parent) for parent in self._parents]


def test_go_namespace_policy() -> None:
    """Known namespaces and a missing term receive stable categories."""
    assert go_category_for_namespace("molecular_function") == "biolink:MolecularActivity"
    assert go_category_for_namespace("cellular_component") == "biolink:CellularComponent"
    assert go_category_for_namespace(None) == "biolink:BiologicalProcess"


def test_chebi_policy_uses_ancestry_label_and_direct_parent() -> None:
    """The three ChEBI signals can be tested independently of OAK."""
    assert chebi_category("CHEBI:1", FakeAdapter(ancestors=["CHEBI:33839"])) == "biolink:MacromolecularComplex"
    assert chebi_category("CHEBI:2", FakeAdapter(label="enzyme inhibitor")) == "biolink:ChemicalRole"
    assert chebi_category("CHEBI:3", FakeAdapter(label="unknown", parents=["CHEBI:50906"])) == "biolink:ChemicalRole"
    assert chebi_category("CHEBI:4", FakeAdapter(label=None)) == "biolink:ChemicalEntity"


def test_simple_category_policies() -> None:
    """Prefix, invariant ontology, and deprecation policies are pure."""
    assert replace_category_by_prefix("GO:1\told", 0, 1) == "GO:1\tbiolink:BiologicalProcess"
    assert uberon_category("UBERON:1") == "biolink:AnatomicalEntity"
    assert ncbitaxon_category("NCBITaxon:1") == "biolink:OrganismTaxon"
    assert replace_deprecated_category_names("biolink:ChemicalSubstance") == "biolink:ChemicalEntity"
