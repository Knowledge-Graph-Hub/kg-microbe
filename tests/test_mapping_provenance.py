"""Check read-only exporter agreement and explicit reproducibility boundaries."""

import gzip
import json
from unittest.mock import patch

import pytest

from scripts import mapping_provenance as provenance


def _repository(tmp_path):
    """Create a small source/config tree entirely owned by the test."""
    for relative in (
        "scripts/consolidate_chemical_mappings.py",
        "kg_microbe/utils/chemical_mapping_utils.py",
        "kg_microbe/profiles/example.yaml",
        "kg_microbe/transform_utils/constants.py",
        "pyproject.toml",
        "poetry.lock",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    return tmp_path


def _artifact(root, tool="kg-microbe/scripts/consolidate_chemical_mappings.py"):
    """Write metadata and no graph-scale body for the diagnostic."""
    path = root / "artifact.tsv.gz"
    digest = provenance.file_sha256(root / "scripts/consolidate_chemical_mappings.py")
    with gzip.open(path, "wt") as handle:
        handle.write(f"# mapping_tool: {tool}\n# mapping_tool_version: sha256:{digest}\nsubject_id\n")
    return path


def test_drift_is_reported_without_rewriting_or_failing_cli(tmp_path, capsys):
    """Changing exporter code must be visible without forced regeneration (#973)."""
    root = _repository(tmp_path)
    artifact = _artifact(root)
    original = artifact.read_bytes()
    assert provenance.exporter_agreement(artifact, root)["status"] == "MATCH"
    (root / "scripts/consolidate_chemical_mappings.py").write_text("changed\n")
    provenance.main(["--artifact", str(artifact), "--repo-root", str(root)])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "DRIFT"
    assert result["blocking"] is False
    assert artifact.read_bytes() == original


def test_unknown_tool_cannot_select_an_arbitrary_file(tmp_path):
    """SSSOM metadata is data, not permission to open arbitrary exporter paths."""
    root = _repository(tmp_path)
    report = provenance.exporter_agreement(_artifact(root, "../../secret"), root)
    assert report["status"] == "UNRECOGNIZED_EXPORTER"
    assert report["current_exporter"] is None


def test_imported_code_and_lock_change_context(tmp_path):
    """Imported runtime and dependency versions must affect candidate provenance (#974)."""
    root = _repository(tmp_path)
    with patch.object(provenance.importlib.metadata, "distributions", return_value=[]):
        first = provenance.reproducibility_context(root)
        (root / "kg_microbe/utils/chemical_mapping_utils.py").write_text("new behavior\n")
        second = provenance.reproducibility_context(root)
        (root / "poetry.lock").write_text("new lock\n")
        third = provenance.reproducibility_context(root)
    assert len({first["sha256"], second["sha256"], third["sha256"]}) == 3
    assert "kg_microbe/utils/chemical_mapping_utils.py" in first["code_and_config_sha256"]
    assert not any(key.startswith("/") for key in first["code_and_config_sha256"])


def test_actual_library_versions_are_recorded(tmp_path):
    """A lock file alone cannot prove which library version executed the builder."""
    from types import SimpleNamespace

    root = _repository(tmp_path)
    with patch.object(provenance.importlib.metadata, "distributions") as distributions:
        distributions.return_value = [SimpleNamespace(metadata={"Name": "sssom"}, version="1.0")]
        first = provenance.reproducibility_context(root)
        distributions.return_value = [SimpleNamespace(metadata={"Name": "sssom"}, version="2.0")]
        second = provenance.reproducibility_context(root)
    assert first["environment"]["installed_distributions"] == {"sssom": ["1.0"]}
    assert first["sha256"] != second["sha256"]


def test_missing_reproducibility_input_fails(tmp_path):
    """An incomplete source tree cannot claim reproducibility evidence."""
    with pytest.raises(ValueError, match="Missing mapping reproducibility input"):
        provenance.reproducibility_context(tmp_path)
