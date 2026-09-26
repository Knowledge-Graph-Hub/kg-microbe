"""Exercise reviewed-release CLI selection and the legacy reintroduction guard."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import consolidate_chemical_mappings as legacy
from scripts import refresh_reviewed_mim as cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_committed_release_pin():
    """Pin the selected immutable export without inventing a published release tag."""
    pin = cli.load_release_pin(REPO_ROOT)
    assert pin["schema_version"] == 2
    assert pin["origin"] == "immutable_commit_export"
    assert pin["source_commit"] == "1848b0fe521bc2462f165912fcf92d09ad9a8cec"
    assert pin["manifest_sha256"] == "9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af"
    assert "release_tag" not in pin and "release_url" not in pin
    assert pin["mode"] == "candidate_only"


@pytest.mark.parametrize(
    "args", [[], ["--dry-run"], ["--allow-stale-vendored"], ["--dry-run", "--allow-stale-vendored"]]
)
def test_legacy_cli_cannot_reintroduce_mim(args):
    """Abort before any seed load, sibling sync, or artifact write."""
    with patch.object(legacy, "ChemicalMappingConsolidator") as constructor:
        with pytest.raises(ValueError, match="reviewed MIM release is pinned"):
            legacy.main(args)
        constructor.assert_not_called()


def test_identity_only_policy_is_still_bounded(tmp_path):
    """Existing explicit identity-exclusion refresh does not read MIM sources."""
    with patch.object(legacy, "refresh_identity_policy", return_value={}) as refresh:
        legacy.main(["--identity-policy-only", "--output", str(tmp_path / "candidate.gz")])
        refresh.assert_called_once()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", True),
        ("mode", "publish"),
        ("manifest_sha256", ""),
        ("source_commit", "main"),
        ("release_tag", "main"),
        ("release_url", "https://example.org"),
    ],
)
def test_invalid_pin_fails_closed(tmp_path, key, value):
    """Do not infer a release or publication permission from malformed metadata."""
    pin = cli.load_release_pin(REPO_ROOT)
    pin[key] = value
    destination = tmp_path / cli.PIN_FILE
    destination.parent.mkdir()
    destination.write_text(json.dumps(pin))
    with pytest.raises(ValueError):
        cli.load_release_pin(tmp_path)


def test_cli_help_is_offline(capsys):
    """Help does not require release assets, ontology adapters, or mapping inputs."""
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert error.value.code == 0
    assert "--release-directory" in capsys.readouterr().out


def test_candidate_uses_only_explicit_reconstruction_inputs(tmp_path):
    """Do not silently replay MIM companions or feedback-derived fallback tables."""
    from scripts import mim_conservative_refresh as builder

    with (
        patch.object(builder, "build_conservative_candidate", return_value="candidate") as build,
        patch.object(cli, "validate_immutable_export", return_value={"verification": "test-only"}) as verify,
    ):
        result = cli.build_candidate(
            repo_root=REPO_ROOT,
            data_root=tmp_path / "data",
            release_directory=tmp_path / "release",
            output_directory=tmp_path / "candidate",
            source_archive=tmp_path / "source.tar.gz",
        )
    verify.assert_called_once()
    assert result == "candidate"
    parameters = build.call_args.kwargs
    names = {source.path.name for source in parameters["independent_sources"]}
    assert names == {"metabolite_mapping.json", "chebi_manual_annotation.tsv", "chemical_mappings.tsv"}
    assert len(parameters["ontology_paths"]) == 9
    assert parameters["baseline"] == REPO_ROOT / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    assert parameters["expected_manifest_sha256"] == cli.load_release_pin(REPO_ROOT)["manifest_sha256"]
    assert parameters["upstream_provenance"]["pin"] == cli.load_release_pin(REPO_ROOT)
    assert str(tmp_path / "source.tar.gz") in {str(path) for path in parameters["provenance_inputs"]}


def test_committed_reconstruction_inputs_have_valid_shapes():
    """Guard the real curated tables, including explicit empty trailing TSV cells."""
    from scripts import mim_conservative_refresh as builder

    for kind, path in cli.REPO_INPUTS:
        builder._preflight_independent(builder.IndependentSource(kind, REPO_ROOT / path))
