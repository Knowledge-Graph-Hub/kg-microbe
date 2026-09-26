"""Native contextual aliases must not transfer observations between phenotype branches."""

from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as module


@pytest.fixture
def native_transform(monkeypatch):
    """Use the production loaders with immutable native template projections, offline."""
    monkeypatch.setenv(
        "KG_MICROBE_METPO_TEMPLATE_DIR", str(Path(__file__).parent / "resources/bacdive_phenotype_context")
    )
    transform = module.BacDiveTransform.__new__(module.BacDiveTransform)
    transform.bacdive_metpo_mappings = module.load_metpo_mappings("bacdive keyword synonym")
    transform.bacdive_metpo_tree = module._build_metpo_tree()
    return transform


@pytest.mark.parametrize("bare_context", ["motility", "sporulation"])
@pytest.mark.parametrize(
    "context,parent,yes,no",
    [
        ("motility", "METPO:1000701", "METPO:1000702", "METPO:1000703"),
        ("sporulation", "METPO:1000870", "METPO:1000871", "METPO:1000872"),
    ],
)
def test_context_beats_bare_alias_order(native_transform, bare_context, context, parent, yes, no):
    """Either template order yields the same field-specific terms for both polarities."""
    transform = native_transform
    for value, target in (("yes", yes), ("no", no)):
        transform.bacdive_metpo_mappings[value] = transform.bacdive_metpo_mappings[f"{bare_context}.{value}"]
        assert (
            transform._phenotype_mapping(value, transform.bacdive_metpo_tree[parent], "field.path")["curie"] == target
        )
    assert transform._ambiguous_metpo_aliases == {"yes", "no"}


def test_missing_context_does_not_accept_foreign_fallback(native_transform):
    """An absent contextual key cannot turn a motility observation into a spore claim."""
    transform = native_transform
    del transform.bacdive_metpo_mappings["motility.no"]
    parent = transform.bacdive_metpo_tree["METPO:1000701"]
    assert transform._phenotype_mapping("no", parent, "Morphology.cell morphology.motility") is None
    assert transform._phenotype_mapping("aerobe", parent, "Morphology.cell morphology.motility") is None
    assert transform._phenotype_mapping("unmapped", parent, "Morphology.cell morphology.motility") is None


def test_shared_keyword_path_is_not_sporulation_context(native_transform):
    """Preserve genuine oxygen/shape tags while rejecting unscoped yes/no."""
    transform = native_transform
    parent = transform.bacdive_metpo_tree["METPO:1000870"]
    for value, target in (("aerobe", "METPO:1000602"), ("rod-shaped", "METPO:1000681")):
        assert transform._phenotype_mapping(value, parent, "General.keywords")["curie"] == target
    for value in ("yes", "no"):
        assert transform._phenotype_mapping(value, parent, "General.keywords") is None


def test_missing_native_target_aborts(native_transform):
    """An infrastructure/configuration defect must not become an unexplained missing observation."""
    transform = native_transform
    del transform.bacdive_metpo_tree["METPO:1000702"]
    with pytest.raises(ValueError, match="absent from METPO"):
        transform._phenotype_mapping("yes", transform.bacdive_metpo_tree["METPO:1000701"], "field.path")


def test_broken_native_ancestry_aborts(native_transform):
    """Corrupt cyclic ancestry fails visibly, rather than hanging a production record."""
    transform = native_transform
    target = transform.bacdive_metpo_tree["METPO:1000702"]
    target.parent = target
    with pytest.raises(ValueError, match="Cycle"):
        transform._phenotype_mapping("yes", transform.bacdive_metpo_tree["METPO:1000701"], "field.path")
