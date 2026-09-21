"""Release destination support is checked before expensive source admission or KGX."""

from unittest.mock import Mock

import pytest
import yaml

from kg_microbe.merge_utils import merge_kg


def _config(tmp_path, destinations, *, diagnostic=False):
    """Write only a minimal config; rejected destinations need no graph inputs."""
    path = tmp_path / "merge.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "output_directory": str(tmp_path / "published"),
                    "allow_unfinalized_sources": diagnostic,
                },
                "merged_graph": {"destination": destinations},
            }
        )
    )
    return str(path)


@pytest.mark.parametrize("diagnostic", [False, True])
@pytest.mark.parametrize(
    "entry",
    [
        {"format": "csv", "filename": "graph", "compression": "tar.gz"},
        {"format": "nt", "filename": "graph"},
        {"format": "tsv", "filename": "graph", "compression": "tar"},
        {"format": "tsv", "filename": "graph", "compression": "gz"},
        {"format": "tsv", "filename": "graph", "compression": ""},
        {"format": "tsv", "filename": "graph", "compression": False},
        {"format": "tsv", "filename": "graph", "compression": []},
        {"format": None, "filename": "graph"},
        {"filename": "graph"},
        None,
        [],
        "tsv",
    ],
)
def test_unsupported_destination_fails_before_admission_or_kgx(tmp_path, monkeypatch, entry, diagnostic):
    """Neither malformed configuration nor diagnostic opt-out can bypass release validation."""
    config = _config(tmp_path, {"unsupported": entry}, diagnostic=diagnostic)
    admission, kgx = Mock(), Mock()
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admission)
    monkeypatch.setattr(merge_kg, "merge", kgx)
    with pytest.raises(ValueError, match="destination.*unsupported"):
        merge_kg.load_and_merge(config)
    admission.assert_not_called()
    kgx.assert_not_called()
    assert not (tmp_path / "published").exists()
    assert not list(tmp_path.glob(".published.merge-*"))


@pytest.mark.parametrize("destinations", [None, {}, [], "tsv", 1])
def test_release_requires_nonempty_destination_mapping(tmp_path, monkeypatch, destinations):
    """A release must not silently succeed without a supported publication destination."""
    config = _config(tmp_path, destinations)
    admission = Mock()
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admission)
    with pytest.raises(ValueError, match="destination"):
        merge_kg.load_and_merge(config)
    admission.assert_not_called()


@pytest.mark.parametrize(
    "filename",
    [
        None,
        "",
        "  ",
        [],
        ["graph"],
        False,
        "/outside/graph",
        "../graph",
        "nested/../graph",
        ".",
        "nested/",
        "graph\nname",
        "graph\x00name",
    ],
)
def test_destination_filename_is_unambiguous_and_contained(tmp_path, filename):
    """Reject misleading bases before filesystem staging or source hashing."""
    config = _config(tmp_path, {"bad-path": {"format": "tsv", "filename": filename}})
    with pytest.raises(ValueError, match="destination.*bad-path"):
        merge_kg.load_and_merge(config)


@pytest.mark.parametrize("filename", ["nested/.", "nested/./."])
@pytest.mark.parametrize("diagnostic", [False, True])
def test_terminal_dot_destination_fails_before_admission(tmp_path, monkeypatch, filename, diagnostic):
    """A directory-like base must not reach differing serializer/cleanup path normalization."""
    config = _config(
        tmp_path,
        {"dot-base": {"format": "tsv", "filename": filename, "compression": "tar.gz"}},
        diagnostic=diagnostic,
    )
    admission, kgx = Mock(), Mock()
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admission)
    monkeypatch.setattr(merge_kg, "merge", kgx)
    with pytest.raises(ValueError, match="destination.*dot-base"):
        merge_kg.load_and_merge(config)
    admission.assert_not_called()
    kgx.assert_not_called()
    assert not (tmp_path / "published").exists()
    assert not list(tmp_path.glob(".published.merge-*"))


@pytest.mark.parametrize("other", ["graph", "./graph", "GRAPH", "graph_nodes.tsv/nested"])
def test_colliding_destination_artifacts_are_rejected_together(tmp_path, other):
    """Supported individual destinations cannot overwrite each other or become file/directories."""
    destinations = {
        "first": {"format": "tsv", "filename": "graph", "compression": "tar.gz"},
        "second": {"format": "tsv", "filename": other},
    }
    with pytest.raises(ValueError, match="destination.*second.*first"):
        merge_kg.load_and_merge(_config(tmp_path, destinations))


@pytest.mark.parametrize("compression", [None, "tar.gz"])
def test_supported_nested_destinations_stage_without_editing_user_config(tmp_path, compression):
    """Keep accepted relative paths, mixed loose/compressed destinations and user YAML unchanged."""
    destinations = {
        "first": {"format": "tsv", "filename": "./nested/first", "compression": compression},
        "second": {"format": "tsv", "filename": "nested/second"},
    }
    config = _config(tmp_path, destinations)
    with open(config, "rb") as stream:
        before = stream.read()
    with merge_kg._staged_merge_configuration(config) as (staged, output, final, _stats):
        result = merge_kg.parse_load_config(str(staged))
        assert result["merged_graph"]["destination"]["first"]["compression"] is None
        assert (output / "nested").is_dir()
        assert final == tmp_path / "published"
    with open(config, "rb") as stream:
        assert stream.read() == before


@pytest.mark.parametrize("boundary", ["staging", "cleanup"])
def test_direct_private_boundaries_cannot_skip_destination_gate(tmp_path, boundary):
    """Compatibility callers must not publish CSV without graph-wide validation/manifests."""
    config = _config(tmp_path, {"unsupported": {"format": "csv", "filename": "graph"}})
    with pytest.raises(ValueError, match="destination.*unsupported"):
        if boundary == "staging":
            with merge_kg._staged_merge_configuration(config):
                pytest.fail("unsupported destination was staged")
        else:
            merge_kg._cleanup_merged_outputs(config)


def test_supported_first_destination_does_not_hide_unsupported_second(tmp_path, monkeypatch):
    """Validate the whole release configuration before any individual destination runs."""
    config = _config(
        tmp_path,
        {
            "a-supported": {"format": "tsv", "filename": "first"},
            "z-unsupported": {"format": "csv", "filename": "second"},
        },
    )
    admission = Mock()
    monkeypatch.setattr(merge_kg, "_assert_sources_finalized", admission)
    with pytest.raises(ValueError, match="destination.*z-unsupported"):
        merge_kg.load_and_merge(config)
    admission.assert_not_called()


@pytest.mark.parametrize(
    "document", [None, [], "not a mapping", {"merged_graph": None}, {"merged_graph": []}, {"merged_graph": {}}]
)
def test_malformed_graph_configuration_has_clear_destination_error(tmp_path, document):
    """Wrong YAML shapes cannot crash halfway through source processing."""
    config = tmp_path / "merge.yaml"
    config.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="destination"):
        merge_kg.load_and_merge(str(config))
