"""Pin main-level write suppression, including the legacy companion branch (#954)."""

import gzip
import hashlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import consolidate_chemical_mappings as consolidator

FIXTURES = Path(__file__).parent / "resources"


def snapshot(root):
    """Record all fixture bytes and modification timestamps without excluding hidden files."""
    return {
        str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("vendored_companion", [False, True])
def test_legacy_main_preview_preserves_all_inputs_and_outputs(tmp_path, monkeypatch, capsys, vendored_companion):
    """Exercise real main/sync/delta paths while replacing expensive ontology consolidation."""
    root = tmp_path / "kgm"
    mappings = root / "mappings"
    mappings.mkdir(parents=True)
    upstream = tmp_path / "explicit-non-sibling-mim" / "mappings"
    upstream.mkdir(parents=True)
    fixture = FIXTURES / "ingredient_identity_stale.sssom.tsv"
    current = FIXTURES / "peptone_specific_identity.sssom.tsv"
    published = mappings / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    published.write_bytes(gzip.compress(fixture.read_bytes(), mtime=0))
    for name in ("ingredient_mappings.sssom.tsv", "culturebotai_reviewed_ingredients.tsv"):
        shutil.copyfile(fixture, mappings / name)
    sssom_source = upstream.parent / consolidator._MIM_SIBLING_RELPATH
    reviewed_source = upstream.parent / consolidator._CBAI_SIBLING_RELPATH
    for source in (sssom_source, reviewed_source):
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current, source)
    companion = upstream / "complex_ingredients.tsv.gz"
    companion.write_bytes(gzip.compress(current.read_bytes(), mtime=0))
    vendored = mappings / companion.name
    if vendored_companion:
        vendored.write_bytes(gzip.compress(fixture.read_bytes(), mtime=0))

    monkeypatch.setattr(consolidator, "__file__", str(root / "scripts/consolidate_chemical_mappings.py"))
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(upstream.parent))
    worker = MagicMock(spec=consolidator.ChemicalMappingConsolidator)
    exports = []

    def export(candidate, *, published_path):
        """Produce a tiny scratch preview, preserving main's real destination decisions."""
        assert published_path == published
        assert candidate != published
        candidate.write_bytes(gzip.compress(current.read_bytes(), mtime=0))
        exports.append(candidate)

    worker.export_unified_sssom.side_effect = export
    monkeypatch.setattr(consolidator, "ChemicalMappingConsolidator", lambda: worker)
    before = snapshot(tmp_path)

    consolidator.main(["--dry-run"])

    assert snapshot(tmp_path) == before
    assert len(exports) == 1 and not exports[0].exists()
    worker.load_existing_unified.assert_called_once_with(published)
    worker.load_mediaingredientmech_sssom.assert_called_once_with(sssom_source.resolve())
    worker.load_culturebotai_reviewed.assert_called_once_with(reviewed_source.resolve())
    worker.load_complex_ingredients.assert_called_once_with(vendored if vendored_companion else companion)
    assert vendored.exists() is vendored_companion
    output = capsys.readouterr().out
    assert "Nothing was written" in output
    assert ("would sync complex_ingredients.tsv.gz" in output) is not vendored_companion


def test_pinned_main_preview_refuses_before_any_write(tmp_path, monkeypatch):
    """Testing the legacy branch never grants permission to bypass the production pin."""
    root = tmp_path / "kgm"
    mappings = root / "mappings"
    mappings.mkdir(parents=True)
    production = Path(consolidator.__file__).resolve().parents[1]
    shutil.copyfile(production / "mappings/mim_reviewed_release.json", mappings / "mim_reviewed_release.json")
    shutil.copyfile(FIXTURES / "ingredient_identity_stale.sssom.tsv", mappings / "ingredient_mappings.sssom.tsv")
    monkeypatch.setattr(consolidator, "__file__", str(root / "scripts/consolidate_chemical_mappings.py"))
    worker = MagicMock()
    monkeypatch.setattr(consolidator, "ChemicalMappingConsolidator", worker)
    before = snapshot(tmp_path)

    with pytest.raises(ValueError, match="reviewed MIM release is pinned"):
        consolidator.main(["--dry-run", "--allow-stale-vendored"])

    assert snapshot(tmp_path) == before
    worker.assert_not_called()
