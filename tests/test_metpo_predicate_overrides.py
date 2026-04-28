"""
Pin METPO predicate overrides for org→medium/carbon/pathway/enzyme edges.

These constants override the default biolink:consumes / biolink:capable_of with
the METPO-specific domain-predicate. If anyone reverts them, the test fails and
the regression is caught before downstream queries break.
"""

import pytest

from kg_microbe.transform_utils import constants

METPO_OVERRIDE_EXPECTATIONS = {
    "NCBI_TO_CARBON_SUBSTRATE_EDGE": "METPO:2000006",
    "NCBI_TO_PATHWAY_EDGE": "METPO:2000103",
    "NCBI_TO_ENZYME_EDGE": "METPO:2000103",
}


@pytest.mark.parametrize("name,expected", sorted(METPO_OVERRIDE_EXPECTATIONS.items()))
def test_metpo_predicate_override(name: str, expected: str) -> None:
    """Each org→{carbon,pathway,enzyme} predicate is pinned to its METPO CURIE."""
    actual = getattr(constants, name)
    assert actual == expected, (
        f"{name} regressed from METPO override {expected!r} to {actual!r}. "
        "These predicates are deliberate METPO overrides of biolink defaults; "
        "do not revert without coordinating downstream KG users."
    )
