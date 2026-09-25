"""Protect candidate and fallback paths from independently retained historical mistakes."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive.mediadive import MediaDiveTransform
from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import ingredient_mapping_allowed
from scripts import mim_conservative_refresh as refresh
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _metadata, _node, _read, _row, _table
from tests.test_mim_conservative_refresh import bundle as bundle
from tests.test_mim_conservative_refresh import inputs as inputs


def test_unaffected_historical_policy_claims_are_quarantined_without_losing_authorities(inputs):
    """An unrelated source tag cannot exempt a reviewed false name or exact xref."""
    baseline = inputs["baseline"]
    rows = list(refresh._rows(baseline))
    bad_name = _row(
        "kgm.name:cysteine-hcl",
        "CHEBI:5862",
        "idazoxan",
        "mediadive_compounds",
        "skos:closeMatch",
        "Cysteine-HCl",
        "synonym",
    )
    bad_xref = _row("CHEBI:91247", "CHEBI:52891", "QSY9 succinimidyl ester(1+)", "independent_prior")
    rows.extend(
        [
            bad_name,
            bad_xref,
            _row("kgm.name:idazoxan", "CHEBI:5862", "idazoxan", name="idazoxan", comment="canonical_name"),
            _row(
                "kgm.name:dye",
                "CHEBI:52891",
                "QSY9 succinimidyl ester(1+)",
                name="QSY9 succinimidyl ester(1+)",
                comment="canonical_name",
            ),
            _row(
                "CHEBI:91247",
                "CHEBI:52891",
                "QSY9 succinimidyl ester(1+)",
                "independent_prior",
                "skos:closeMatch",
                comment="fixture_nonidentity",
            ),
        ]
    )
    _table(baseline, FIELDS, rows, _metadata())
    result = refresh.build_conservative_candidate(**inputs)
    assert "CHEBI:5862" not in result.report["affected_entities"]
    assert result.report["counts"]["identity_policy_quarantined_rows"] == 2
    candidate, quarantine = _read(result.candidate_path), _read(result.quarantine_path)
    assert bad_name not in candidate
    assert bad_xref not in candidate
    for original, reason in [(bad_name, "reviewed_identity_policy_name"), (bad_xref, "reviewed_identity_policy_xref")]:
        assert dict(original, quarantine_reason=reason) in quarantine
    assert any(row["subject_label"] == "idazoxan" for row in candidate)
    assert any(row["subject_label"] == "QSY9 succinimidyl ester(1+)" for row in candidate)
    assert any(row["comment"] == "fixture_nonidentity" for row in candidate)


@pytest.mark.parametrize("native_present", [True, False])
def test_only_bad_historical_claim_restores_native_authority_or_reports_gap(inputs, native_present):
    """A rejected synonym cannot silently erase its target's independently valid identity."""
    baseline = inputs["baseline"]
    bad = _row(
        "kgm.name:cysteine-hcl",
        "CHEBI:5862",
        "idazoxan",
        "mediadive_compounds",
        "skos:closeMatch",
        "Cysteine-HCl",
        "synonym",
    )
    _table(baseline, FIELDS, [*refresh._rows(baseline), bad], _metadata())
    if native_present:
        authority = inputs["ontology_paths"][0]
        native_rows = [row for _, row in refresh._native_rows((authority,))]
        _table(authority, NODE_FIELDS, [*native_rows, _node("CHEBI:5862", "idazoxan", "Idazoxanum")])
    result = refresh.build_conservative_candidate(**inputs)
    rows = _read(result.candidate_path)
    assert "CHEBI:5862" not in result.report["affected_entities"]
    assert "CHEBI:5862" in result.report["policy_pruned_targets"]
    assert bad not in rows
    assert dict(bad, quarantine_reason="reviewed_identity_policy_name") in _read(result.quarantine_path)
    if native_present:
        assert "CHEBI:5862" in result.report["native_authority_entities"]
        assert any(row["subject_label"] == "idazoxan" for row in rows)
        assert any(row["subject_label"] == "Idazoxanum" for row in rows)
        assert "CHEBI:5862" not in result.report["unreconstructed_lexical_entities"]
    else:
        assert "CHEBI:5862" in result.report["unreconstructed_entities"]
        assert "CHEBI:5862" in result.report["unreconstructed_lexical_entities"]
    second = refresh.build_conservative_candidate(
        **dict(
            inputs,
            baseline=result.candidate_path,
            output_directory=inputs["output_directory"].with_name("second"),
        )
    )
    assert result.candidate_path.read_bytes() == second.candidate_path.read_bytes()


@pytest.mark.parametrize(
    "name",
    [
        "Cystein-HCL",
        "Cysteine-HCl",
        "Cysteine HCl",
        "L-Cystein HCl",
        "L-Cysteine-HCl",
        "L-cysteine HCl",
        "L-Cysteine x HCl",
    ],
)
def test_reviewed_cysteine_aliases_do_not_resolve_as_idazoxan(name):
    """Keep the finite historical erroneous aliases separate from native drug identity."""
    assert not ingredient_mapping_allowed(name, "CHEBI:5862")
    assert ingredient_mapping_allowed("idazoxan", "CHEBI:5862")


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
def test_bare_thiosulfate_cannot_acquire_pentahydrate_scope(route):
    """Preserve source identity when only unsupported hydrate strengthening is available."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: "CHEBI:32150" if route == "unified" else None
    )
    transform.compound_mappings = {"na2s2o3": "CHEBI:32150"} if route == "legacy" else {}
    transform.compounds_data = {"99": {"ChEBI": "32150"}} if route == "embedded" else {}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", "Na2S2O3") == "mediadive.ingredient:99"
    assert ingredient_mapping_allowed("Na2S2O3.5H2O", "CHEBI:32150")
    assert ingredient_mapping_allowed("sodium thiosulfate pentahydrate", "CHEBI:32150")
    transform.chemical_loader = SimpleNamespace(find_chebi_by_name=lambda *args, **kwargs: "CHEBI:132112")
    assert transform.standardize_compound_id("99", "Na2S2O3") == "CHEBI:132112"


def test_raw_thiosulfate_guard_is_applied_before_legacy_deduplication(tmp_path):
    """A later justified anhydrous mapping remains usable after rejecting a bad first row."""
    path = tmp_path / "mapping.tsv"
    path.write_text("original\tmapped\nNa2S2O3\tCHEBI:32150\nNa2S2O3\tCHEBI:132112\nNa2S2O3.5H2O\tCHEBI:32150\n")
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    rows = transform._load_mapping_file(path, "test")
    assert rows["na2s2o3"] == "CHEBI:132112"
    assert rows["na2s2o3.5h2o"] == "CHEBI:32150"


@pytest.mark.parametrize("route", ["unified", "legacy", "embedded"])
@pytest.mark.parametrize("padding", ["", "  "])
@pytest.mark.parametrize(
    "name,target",
    [
        ("CoCl2 x 2 H2O", "CHEBI:29365"),
        ("CoCl2 x 2 H2O", "CHEBI:35696"),
        ("FeCl2 x 6 H2O", "CHEBI:30812"),
        ("Na2HPO4 x 6 H2O", "CHEBI:34683"),
        ("NiCl2 x 2 H2O", "CHEBI:34887"),
        ("potassium 5-dehydro-D-gluconate", "CHEBI:17659"),
        ("Soytone", "CHEBI:8150"),
        ("Bacto Soytone", "CHEBI:8150"),
        ("Sulfur (powder)", "CHEBI:14258"),
        ("Sulfur powder", "CHEBI:14258"),
        ("HEPES buffer", "CHEBI:19708"),
    ],
)
def test_demonstrated_false_source_identities_preserve_ingredient(route, name, target, padding):
    """A failed unified correction cannot fall back to the same unrelated chemical (#1151)."""
    transform = MediaDiveTransform.__new__(MediaDiveTransform)
    transform.chemical_loader = SimpleNamespace(
        find_chebi_by_name=lambda *args, **kwargs: target if route == "unified" else None
    )
    transform.compound_mappings = {name.lower().strip(): target} if route == "legacy" else {}
    transform.compounds_data = {"99": {"ChEBI": target.split(":")[1]}} if route == "embedded" else {}
    transform.using_bulk_data = True
    transform.api_calls_avoided = 0
    assert transform.standardize_compound_id("99", padding + name + padding) == "mediadive.ingredient:99"


def test_hydrated_cobalt_guard_preserves_native_phosgene_formula(tmp_path, monkeypatch):
    """Reject a demonstrated hydrate collision without erasing case-sensitive native COCl2."""
    assert ingredient_mapping_allowed("COCl2", "CHEBI:29365")
    assert ingredient_mapping_allowed("phosgene", "CHEBI:29365")
    path = tmp_path / "native-formula.tsv"
    _table(
        path,
        FIELDS,
        [
            _row("kgm.name:phosgene", "CHEBI:29365", "phosgene", name="phosgene", comment="canonical_name"),
            _row("kgm.name:cocl2", "CHEBI:29365", "phosgene", name="COCl2", comment="synonym"),
        ],
        _metadata(),
    )
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(path)
    assert runtime.find_chebi_by_name("COCl2") == "CHEBI:29365"
    assert runtime.find_chebi_by_name("CoCl2 x 2 H2O", fuzzy_hydrate=True) is None
    assert runtime.find_chebi_by_name("  CoCl2 x 2 H2O  ", fuzzy_hydrate=True) is None
    assert runtime.find_chebi_by_name("COCl2") == "CHEBI:29365"


def test_obsolete_false_ingredient_targets_do_not_ban_native_replacements():
    """The native retirement fixture supports exclusion, not guessed chemical substitutions."""
    path = Path(__file__).parent / "resources/chemical_grounding_retirements.tsv"
    with path.open() as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            assert row["deprecated"] == "true"
            assert ingredient_mapping_allowed(row["replacement_label"], row["replacement"])
            assert ingredient_mapping_allowed(row["replacement_label"], row["id"])
