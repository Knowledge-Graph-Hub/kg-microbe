"""Exercise reviewed-release CLI selection and the legacy reintroduction guard."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import consolidate_chemical_mappings as legacy
from scripts import refresh_reviewed_mim as cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_committed_release_pin():
    """Pin the selected supported release independently of downloaded bytes."""
    pin = cli.load_release_pin(REPO_ROOT)
    assert pin["release_tag"] == "mim-sssom-2026-09-21"
    assert pin["manifest_sha256"] == "cf883804354b5d4e9796e7e952a023b240ff951ed95372fb212c7afd47c65dcd"
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

    with patch.object(builder, "build_conservative_candidate", return_value="candidate") as build:
        result = cli.build_candidate(
            repo_root=REPO_ROOT,
            data_root=tmp_path / "data",
            release_directory=tmp_path / "release",
            output_directory=tmp_path / "candidate",
        )
    assert result == "candidate"
    parameters = build.call_args.kwargs
    names = {source.path.name for source in parameters["independent_sources"]}
    assert names == {"metabolite_mapping.json", "chebi_manual_annotation.tsv", "chemical_mappings.tsv"}
    assert len(parameters["ontology_paths"]) == 9
    assert parameters["baseline"] == REPO_ROOT / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    assert parameters["expected_manifest_sha256"] == cli.load_release_pin(REPO_ROOT)["manifest_sha256"]


def test_committed_reconstruction_inputs_have_valid_shapes():
    """Guard the real curated tables, including explicit empty trailing TSV cells."""
    from scripts import mim_conservative_refresh as builder

    for kind, path in cli.REPO_INPUTS:
        builder._preflight_independent(builder.IndependentSource(kind, REPO_ROOT / path))
