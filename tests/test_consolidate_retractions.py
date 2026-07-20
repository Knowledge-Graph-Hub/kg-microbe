"""
Tests for the consolidator's retraction pass (apply_retractions).

The consolidator seeds each run from its own prior output, which is additive:
a corrected upstream grounding adds the right object record but cannot remove
the superseded one. ``apply_retractions`` drops explicitly-listed stale object
records, but only when their sole contributing source is
``culturebotai_reviewed`` so attribution stays unambiguous.
"""

import importlib.util
from pathlib import Path

import pytest

_CONSOLIDATOR_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "consolidate_chemical_mappings.py"
)


def _load_consolidator_module():
    """Import the standalone consolidator script as a module."""
    spec = importlib.util.spec_from_file_location(
        "consolidate_chemical_mappings", _CONSOLIDATOR_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def consolidator():
    """Return a consolidator seeded with drop / skip / keep / absent fixtures."""
    mod = _load_consolidator_module()
    c = mod.ChemicalMappingConsolidator()
    # Sole-source culturebotai phantom → must be dropped.
    c.add_chemical(
        id="CHEBI:15743",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed",
        priority=10,
    )
    # Mixed-source → must be SKIPPED (another source still asserts it).
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="Cobalamine",
        source="culturebotai_reviewed",
        priority=10,
    )
    c.add_chemical(
        id="CHEBI:30411",
        canonical_name="Cobalamine",
        source="mediadive_compounds",
        priority=1,
    )
    # Correct grounding, not listed → must be untouched.
    c.add_chemical(
        id="CHEBI:17201",
        canonical_name="Glycylglycine",
        source="culturebotai_reviewed",
        priority=10,
    )
    return c


def _write_retraction_tsv(path: Path):
    """Write a retraction TSV with a comment header + one already-absent row."""
    path.write_text(
        "# comment lines must be ignored by the reader\n"
        "subject_id\tsubject_label\tstale_object\tstale_object_label\tnow_asserted\tsource\n"
        "kgm.name:glycylglycine\tGlycylglycine\tCHEBI:15743\tGlycylglycine\tCHEBI:17201\tculturebotai_reviewed\n"
        "kgm.name:cobalamin\tCOBALAMIN\tCHEBI:30411\tCobalamine\tCHEBI:28911\tculturebotai_reviewed\n"
        "kgm.name:gone\tGone\tCHEBI:99999\tGone\tCHEBI:1\tculturebotai_reviewed\n",
        encoding="utf-8",
    )


def test_drops_sole_source_culturebotai_object(consolidator, tmp_path):
    """A stale object sourced solely from culturebotai_reviewed is removed."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:15743" not in consolidator.chemicals


def test_skips_mixed_source_object(consolidator, tmp_path):
    """A listed object that also has a non-culturebotai source is left in place."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:30411" in consolidator.chemicals


def test_leaves_unlisted_object_untouched(consolidator, tmp_path):
    """The correct grounding (not in the list) survives retraction."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    consolidator.apply_retractions(rf)
    assert "CHEBI:17201" in consolidator.chemicals


def test_absent_object_is_a_noop(consolidator, tmp_path):
    """A listed object not present in the graph does not raise."""
    rf = tmp_path / "retract.tsv"
    _write_retraction_tsv(rf)
    # CHEBI:99999 is listed but was never added — must be a silent no-op.
    consolidator.apply_retractions(rf)
    assert "CHEBI:99999" not in consolidator.chemicals


def test_missing_retraction_file_is_a_noop(consolidator, tmp_path):
    """A missing retraction file skips the pass without dropping anything."""
    consolidator.apply_retractions(tmp_path / "does_not_exist.tsv")
    assert "CHEBI:15743" in consolidator.chemicals
