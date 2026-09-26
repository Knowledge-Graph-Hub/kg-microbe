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


def test_explicit_spore_keyword_uses_native_context(native_transform):
    """The observed source tag reuses native metadata without adding a shared alias."""
    transform = native_transform
    mappings_before = dict(transform.bacdive_metpo_mappings)
    parent = transform.bacdive_metpo_tree["METPO:1000870"]
    assert (
        transform._phenotype_mapping("spore-forming", parent, "General.keywords") == mappings_before["sporulation.yes"]
    )
    assert transform.bacdive_metpo_mappings == mappings_before
    assert "spore-forming" not in transform.bacdive_metpo_mappings
    assert transform._phenotype_mapping("spore-forming", parent, "Physiology and metabolism.spore formation") is None
    assert (
        transform._phenotype_mapping("spore-forming", transform.bacdive_metpo_tree["METPO:1000701"], "General.keywords")
        is None
    )


@pytest.mark.parametrize(
    "value",
    ["yes", "no", "non-spore-forming", "not spore-forming", "no spore-forming", "Spore-forming", "spore forming"],
)
def test_explicit_spore_keyword_does_not_normalize_other_values(native_transform, value):
    """Neither bare polarity nor negation, case or whitespace variants activate this alias."""
    transform = native_transform
    assert (
        transform._phenotype_mapping(value, transform.bacdive_metpo_tree["METPO:1000870"], "General.keywords") is None
    )


@pytest.mark.parametrize("defect", ["wrong-parent", "missing-parent"])
def test_spore_keyword_incomplete_or_foreign_native_context_is_rejected(native_transform, defect):
    """A known keyword aborts on broken native ancestry rather than silently disappearing."""
    transform = native_transform
    parent = transform.bacdive_metpo_tree["METPO:1000870"]
    transform.bacdive_metpo_tree["METPO:1000871"].parent = (
        transform.bacdive_metpo_tree["METPO:1000701"] if defect == "wrong-parent" else None
    )
    with pytest.raises(ValueError, match="outside native sporulation ancestry"):
        transform._phenotype_mapping("spore-forming", parent, "General.keywords")


@pytest.mark.parametrize("defect", ["alias", "foreign-target", "opposite-polarity"])
def test_spore_keyword_requires_native_positive_mapping(native_transform, defect):
    """Absent or wrong native positive mappings abort rather than lose or invert a known tag."""
    transform = native_transform
    if defect == "alias":
        del transform.bacdive_metpo_mappings["sporulation.yes"]
    else:
        key = "motility.yes" if defect == "foreign-target" else "sporulation.no"
        transform.bacdive_metpo_mappings["sporulation.yes"] = transform.bacdive_metpo_mappings[key]
    with pytest.raises(ValueError, match="requires native sporulation.yes"):
        transform._phenotype_mapping("spore-forming", transform.bacdive_metpo_tree["METPO:1000870"], "General.keywords")


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "non-spore forming"),
        ("inferred_category", "biolink:ChemicalEntity"),
        ("predicate_biolink_equivalent", "biolink:has_attribute"),
    ],
)
def test_spore_keyword_requires_consistent_native_metadata(native_transform, field, value):
    """A known positive target cannot carry a conflicting label, category or predicate."""
    transform = native_transform
    transform.bacdive_metpo_mappings["sporulation.yes"] = {
        **transform.bacdive_metpo_mappings["sporulation.yes"],
        field: value,
    }
    with pytest.raises(ValueError, match="inconsistent native METPO metadata"):
        transform._phenotype_mapping("spore-forming", transform.bacdive_metpo_tree["METPO:1000870"], "General.keywords")


@pytest.mark.parametrize("defect", ["missing-target", "cycle"])
def test_spore_keyword_native_infrastructure_errors_abort(native_transform, defect):
    """Do not convert absent targets or cyclic native ancestry into silent coverage loss."""
    transform = native_transform
    if defect == "missing-target":
        del transform.bacdive_metpo_tree["METPO:1000871"]
        message = "absent from METPO"
    else:
        target = transform.bacdive_metpo_tree["METPO:1000871"]
        target.parent = target
        message = "Cycle"
    with pytest.raises(ValueError, match=message):
        transform._phenotype_mapping("spore-forming", transform.bacdive_metpo_tree["METPO:1000870"], "General.keywords")


def test_absent_sporulation_route_keeps_existing_outer_noop(native_transform):
    """Keep the outer helper's pre-existing missing-parent routing contract unchanged."""
    transform = native_transform
    del transform.bacdive_metpo_tree["METPO:1000870"]
    assert (
        transform._process_phenotype_by_metpo_parent(
            {"General": {"keywords": ["spore-forming"]}},
            "METPO:1000870",
            "kgmicrobe.strain:bacdive_654",
            "654",
            None,
            None,
        )
        is None
    )
