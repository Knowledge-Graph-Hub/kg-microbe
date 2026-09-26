"""Candidate artifacts retain hydration scope instead of hiding false aliases at read time."""

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from scripts import mim_conservative_refresh as refresh
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _metadata, _node, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs


@pytest.mark.parametrize("native_present", [True, False])
def test_false_hydrate_alias_is_quarantined_without_recreating_it(inputs, native_present):
    """Native authority survives; missing authority is reported; weak recipe edges remain intact."""
    bad = _row(
        "kgm.name:iron_hydrate",
        "CHEBI:30808",
        "iron trichloride",
        "legacy_recipe",
        "skos:closeMatch",
        "FeCl3 x 6 H2O",
        "synonym",
    )
    weak = _row(
        "CHEBI:30808",
        "CHEBI:86254",
        "iron trichloride hexahydrate",
        "legacy_recipe",
        "skos:closeMatch",
        comment="recipe_equivalent_hydrate",
    )
    baseline = inputs["baseline"]
    _table(baseline, FIELDS, [*refresh._rows(baseline), bad, weak], _metadata())
    authority = inputs["ontology_paths"][0]
    natives = [row for _, row in refresh._native_rows((authority,))]
    if native_present:
        # Deliberately conflicting native synonym is not regenerated as identity.
        natives.append(_node("CHEBI:30808", "iron trichloride", "FeCl3|FeCl3 x 6 H2O"))
    natives.append(_node("CHEBI:86254", "iron trichloride hexahydrate", "FeCl3.6H2O"))
    _table(authority, NODE_FIELDS, natives)
    result = refresh.build_conservative_candidate(**inputs)
    candidate = _read(result.candidate_path)
    assert bad not in candidate
    assert dict(bad, quarantine_reason="hydration_scope_name") in _read(result.quarantine_path)
    assert weak in candidate
    assert not any(row["subject_label"] == "FeCl3 x 6 H2O" for row in candidate)
    if native_present:
        assert any(row["subject_label"] == "iron trichloride" for row in candidate)
        assert any(row["subject_label"] == "FeCl3" for row in candidate)
    else:
        assert "CHEBI:30808" in result.report["unreconstructed_lexical_entities"]
    second = refresh.build_conservative_candidate(
        **dict(
            inputs,
            baseline=result.candidate_path,
            output_directory=inputs["output_directory"].with_name("second"),
        )
    )
    assert result.candidate_path.read_bytes() == second.candidate_path.read_bytes()


def test_supported_release_cannot_silently_override_explicit_native_hydration_scope(inputs):
    """An intentionally inconsistent fixture fails; the builder does not rewrite the publisher."""
    authority = inputs["ontology_paths"][0]
    nodes = [row for _, row in refresh._native_rows((authority,))]
    for row in nodes:
        if row["id"] == "CHEBI:15377":
            row["name"] = "synthetic fixture hexahydrate"
    _table(authority, NODE_FIELDS, nodes)
    with pytest.raises(ValueError, match="Supported MIM assertion changes declared hydration scope"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


def test_fresh_rows_keep_explicit_same_scope_aliases_and_identity_free_report():
    """No inferred alias replaces an omitted one; equivalent explicit hydrate aliases remain."""
    entity = refresh._Entity()
    entity.labels.add((-100, "native_ontology:chebi", "iron trichloride hexahydrate"))
    for name in ["iron trichloride hexahydrate", "FeCl3.6H2O", "FeCl3", "FeCl3 x 2 H2O"]:
        entity.names[name].add("native_ontology:chebi")
    rows = list(refresh._fresh_rows("CHEBI:86254", entity, FIELDS, "2026-09-25"))
    assert {row["subject_label"] for row in rows} == {"iron trichloride hexahydrate", "FeCl3.6H2O"}
    names = {runtime.normalize_name("FeCl3 x 2 H2O"): "CHEBI:86254"}
    labels = {"CHEBI:86254": "iron trichloride hexahydrate"}
    assert refresh._candidate_name_lookup("FeCl3 x 2 H2O", names, set(labels), labels) is None


def test_native_only_hydrate_refinement_is_preserved_across_candidate_cycles(inputs):
    """A generic native hydrate label can retain its independently explicit monohydrate synonym."""
    target, label, synonym = "CHEBI:51799", "imipenem hydrate", "N-formimidoyl thienamycin monohydrate"
    historical = _row("MIM:Impenum", target, label, "mediaingredientmech_reviewed", name="Impenum monohydrate")
    baseline = inputs["baseline"]
    _table(baseline, FIELDS, [*refresh._rows(baseline), historical], _metadata())
    authority = inputs["ontology_paths"][0]
    _table(
        authority, NODE_FIELDS, [*[row for _, row in refresh._native_rows((authority,))], _node(target, label, synonym)]
    )
    first = refresh.build_conservative_candidate(**inputs)
    rows = [row for row in _read(first.candidate_path) if row["object_id"] == target]
    assert {row["subject_label"] for row in rows} == {label, synonym}
    native = {target: [synonym]}
    assert all(not refresh._historical_policy_rejection(row, native) for row in rows)
    second = refresh.build_conservative_candidate(
        **dict(
            inputs,
            baseline=first.candidate_path,
            output_directory=inputs["output_directory"].with_name("native-hydrate-second"),
        )
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
