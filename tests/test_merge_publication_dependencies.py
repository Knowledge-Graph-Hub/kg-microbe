"""Independent admission/publication guard probes, including configuration epochs."""

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg
from kg_microbe.merge_utils.stats_provenance import STATS_OPERATION
from tests.test_merge_canonical_serialization import _configuration, offline_kgx  # noqa: F401


@pytest.mark.parametrize("kind", ["raw", "absent", "tree"])
def test_stats_must_not_write_admitted_dependency(tmp_path, monkeypatch, kind):
    """Protect full admission, not just source node/edge filenames."""
    config, output = _configuration(tmp_path, "tar.gz")
    protected = tmp_path / "raw-dependency.json"
    if kind != "absent":
        protected.write_bytes(b'{"immutable":true}\n')
    data = yaml.safe_load(config.read_text())
    data["merged_graph"]["operations"] = [
        {"name": STATS_OPERATION, "args": {"graph_name": "fixture", "filename": str(protected)}}
    ]
    config.write_text(yaml.safe_dump(data))
    original = merge_kg._assert_sources_finalized

    def admitted(*args, **kwargs):
        """Bind the selected dependency as the actual admission would."""
        admission = original(*args, **kwargs)
        if kind == "tree":
            admission.capture_tree(tmp_path)
        else:
            admission.capture(protected, optional=kind == "absent")
        return admission

    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admitted)
    with pytest.raises(ValueError, match="conflicts"):
        merge_kg.load_and_merge(str(config))
    assert not (output / "merged-kg.tar.gz").exists()


def test_config_used_for_dependency_collision_guard_is_the_admitted_config(tmp_path, monkeypatch):
    """A once-changed config admitted as current cannot use a stale parsed mapping for safety checks."""
    config, output = _configuration(tmp_path, "tar.gz")
    protected = tmp_path / "raw-dependency.json"
    before = b'{"immutable":true}\n'
    protected.write_bytes(before)
    original = merge_kg._assert_sources_finalized

    def admitted(*args, **kwargs):
        """Change configuration before admission captures its new identity."""
        data = yaml.safe_load(config.read_text())
        data["merged_graph"]["operations"] = [
            {"name": STATS_OPERATION, "args": {"graph_name": "fixture", "filename": str(protected)}}
        ]
        config.write_text(yaml.safe_dump(data))
        admission = original(*args, **kwargs)
        admission.capture(protected)
        return admission

    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admitted)
    monkeypatch.setattr(merge_kg, "_repo_root", lambda: tmp_path)
    try:
        merge_kg.load_and_merge(str(config))
    except ValueError:
        assert protected.read_bytes() == before
        return
    assert protected.read_bytes() == before, "Freshly admitted configuration bypassed dependency publication guard"
    pytest.fail("Changed configuration was accepted using a stale pre-admission publication mapping")
