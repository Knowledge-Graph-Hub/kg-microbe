"""Tests for the BacDive isolation-source → ontology mapping loader and validator."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"
VALIDATOR_PATH = REPO_ROOT / "mappings" / "validate_isolation_source_mappings.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kg_microbe.utils.isolation_source_mapping_utils import (  # noqa: E402
    BANNED_OBJECT_LABEL_SUBSTRINGS,
    DISALLOWED_OBJECT_SOURCES,
    load_isolation_source_mappings,
    normalize_isolation_source_label,
)


def _load_validator_module():
    """Import the standalone validator script as a module without triggering kg_microbe init."""
    spec = importlib.util.spec_from_file_location("_iso_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mappings():
    """Load the committed isolation-source mappings once per test module."""
    return load_isolation_source_mappings(MAPPING_FILE)


def test_normalize_handles_hyphens_commas_and_case():
    """BacDive raw values come hyphenated and sometimes carry commas; the normalizer must collapse all of these."""
    assert normalize_isolation_source_label("Heavy-metal") == "heavy metal"
    assert normalize_isolation_source_label("Bovinae-Cow,-Cattle") == "bovinae cow cattle"
    assert normalize_isolation_source_label("Plant-litter-Forest") == "plant litter forest"
    assert normalize_isolation_source_label("Animal-habitation-Nest,Burrow") == "animal habitation nest burrow"
    assert normalize_isolation_source_label("  Blood  ") == "blood"
    assert normalize_isolation_source_label("") == ""


def test_loader_returns_known_anatomy_mapping(mappings):
    """A high-confidence exactMatch like 'Blood' → UBERON:0000178 must be honored."""
    # Loader returns (object_id, object_label, object_source, predicate_override).
    # For non-PATO rows the override is None — the BacDive transform falls back
    # to its standard <source> --location_of--> <organism> emit shape.
    assert mappings.get("blood") == ("UBERON:0000178", "blood", "UBERON", None)


def test_loader_drops_family_mismatched_rows(mappings):
    """The three rows the reviewer flagged (Foot/Human/Infection) must be unmapped at runtime."""
    assert mappings.get("foot") is None  # was UO:0010013 (unit), now cleared
    assert mappings.get("human") is None  # was ENVO:00000070 (human construction), now cleared
    assert mappings.get("infection") is None  # was ENVO:01000170 (plant root-nodule zone), now cleared


def test_loader_honors_manually_curated_fixes(mappings):
    """
    Rows promoted by manual curation are honored — but ONLY when predicate is skos:exactMatch.

    The 2026-05 Codex adversarial review tightened the trust policy so that
    ``skos:closeMatch`` rows are no longer trusted for canonical node
    substitution, even when manually curated, because closeMatch only
    asserts similarity (not equivalence). After the post-Codex re-audit,
    34 of the 41 originally-closeMatch manually-curated rows were promoted
    to exactMatch (the BacDive label and the ontology term denote the same
    entity in isolation-source context). The other 7 stayed dropped because
    the targets were family-mismatched (devices, qualities, phenotype
    classes).
    """
    # exactMatch rows that survive the tightened trust check:
    assert mappings.get("mammals") == ("NCBITaxon:40674", "Mammalia", "NCBITaxon", None)
    assert mappings.get("plant") == ("NCBITaxon:33090", "Viridiplantae", "NCBITaxon", None)
    assert mappings.get("birds") == ("NCBITaxon:8782", "Aves", "NCBITaxon", None)
    assert mappings.get("gastrointestinal tract") == ("UBERON:0005409", "digestive tract", "UBERON", None)
    assert mappings.get("wound") == ("mesh:D014947", "Wounds and Injuries", "mesh", None)
    # closeMatch rows that stay dropped (family-mismatched targets, no PATO override):
    assert mappings.get("catheter") is None  # device, not isolation source
    assert mappings.get("humid") is None  # quality, not source
    assert mappings.get("psychrophilic <10°c") == (
        "ENVO:01000309", "cold environment", "ENVO", None,
    )  # retargeted from METPO trait → ENVO environment


def test_loader_loads_pato_rows_with_predicate_override(mappings):
    """
    Load PATO targets when the row carries a METPO:2000067/2000068 override token.

    The override flips the BacDive transform's edge shape from the default
    (incoherent) `<source> --location_of--> <organism>` to the quality-aware
    `<organism> --METPO:2000067/2000068--> <PATO term>`. The loader returns
    the override CURIE in the fourth tuple element so the transform can
    branch on it.
    """
    # Host-quality rows route through METPO:2000067 (all skos:exactMatch — trusted):
    assert mappings.get("child") == ("PATO:0001190", "juvenile", "PATO", "METPO:2000067")
    assert mappings.get("juvenile") == ("PATO:0001190", "juvenile", "PATO", "METPO:2000067")
    assert mappings.get("female") == ("PATO:0000383", "female", "PATO", "METPO:2000067")
    assert mappings.get("male") == ("PATO:0000384", "male", "PATO", "METPO:2000067")
    # Environment-quality rows route through METPO:2000068 (skos:exactMatch — trusted):
    assert mappings.get("acidic") == ("PATO:0001429", "acidic", "PATO", "METPO:2000068")
    assert mappings.get("alkaline") == ("PATO:0001430", "alkaline", "PATO", "METPO:2000068")
    assert mappings.get("cold") == ("PATO:0001306", "decreased temperature", "PATO", "METPO:2000068")
    assert mappings.get("anoxic anaerobic") == ("PATO:0001456", "anaerobic", "PATO", "METPO:2000068")

    # The override is orthogonal to the trust check: a PATO row with the override
    # token but only skos:closeMatch is still dropped, because closeMatch never
    # passes the trust policy (closeMatch only asserts similarity, not equivalence,
    # and the override does NOT promote it to exact). The 'Non-marine-Saline-and-
    # Alkaline → PATO:0001430' row uses closeMatch because the PATO 'alkaline'
    # term captures only the alkaline component (drops saline + non-marine aspects),
    # so it correctly falls through to the placeholder path at runtime.
    assert mappings.get("non marine saline and alkaline") is None


def test_loader_rejects_low_trust_lexical_close_matches(mappings):
    """
    An ols4_auto skos:closeMatch row that has not been promoted must be silently dropped.

    'Aquaculture → ENVO:03600074 aquaculture farm' is a representative example
    of an untrusted auto-match (skos:closeMatch / medium / LexicalMatching /
    ols4_auto) that the loader should silently drop without raising. If a
    curator later promotes this row to skos:exactMatch / high / Manual, swap
    this assertion to a different still-untrusted row from the TSV.
    """
    assert mappings.get("aquaculture") is None


def test_validator_passes_on_committed_mapping_file():
    """The committed TSV must validate cleanly: any failure is a regression."""
    validator = _load_validator_module()
    failures = list(validator.iter_validation_failures(MAPPING_FILE))
    assert failures == [], f"Unexpected validation failures: {failures}"


def test_validator_rules_match_loader():
    """
    Validator script and runtime loader must agree on what counts as a family mismatch.

    The validator is intentionally standalone (stdlib-only) so it can run in
    minimal CI containers. This test catches drift between its rule set and
    the loader's rule set, which would otherwise let CI pass while the
    runtime drops mappings the validator considers fine (or vice versa).
    """
    validator = _load_validator_module()
    assert validator.DISALLOWED_OBJECT_SOURCES == DISALLOWED_OBJECT_SOURCES
    assert validator.BANNED_OBJECT_LABEL_SUBSTRINGS == BANNED_OBJECT_LABEL_SUBSTRINGS


def test_validator_flags_synthetic_family_mismatch(tmp_path):
    """A trusted row mapped to a UO unit must be reported as a validation failure."""
    validator = _load_validator_module()
    bad_file = tmp_path / "bad.tsv"
    with bad_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow([
            "subject_label", "subject_label_normalized", "object_id", "object_label",
            "object_source", "predicate_id", "confidence", "mapping_justification",
            "curator", "source_dataset", "notes", "verified_date",
        ])
        # A trusted row (high-confidence exactMatch) but with a UO target — must fail.
        writer.writerow([
            "Foot", "foot", "UO:0010013", "foot", "UO", "skos:exactMatch", "high",
            "semapv:LexicalMatching", "ols4_auto", "bacdive", "", "2026-05-02",
        ])
    failures = list(validator.iter_validation_failures(bad_file))
    assert len(failures) == 1
    _, _, reason = failures[0]
    assert "object_source 'UO' is disallowed" in reason


def test_bacdive_transform_imports_and_loads_mappings():
    """
    The BacDive transform module must successfully import the loader.

    This is the lightweight wiring check — full transform execution is too
    expensive for a unit test, but a smoke-import catches missing imports
    or accidental name typos in the wiring change.
    """
    # Heavy package import — gated behind dependency availability since some
    # CI lanes may not install kghub_downloader and friends.
    pytest.importorskip("kghub_downloader")
    from kg_microbe.transform_utils.bacdive import bacdive as bacdive_module

    # The module must export the loader functions (proves the import worked).
    assert hasattr(bacdive_module, "load_isolation_source_mappings")
    assert hasattr(bacdive_module, "normalize_isolation_source_label")
