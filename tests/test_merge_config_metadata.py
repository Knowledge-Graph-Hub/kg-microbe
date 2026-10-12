"""Keep source descriptions outside the finalized-TSV input contract."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from kg_microbe.merge_utils.merge_contract import validate_merge_semantics
from kg_microbe.utils.biolink_model import prepare_kgx

REPO_ROOT = Path(__file__).resolve().parents[1]
RELOCATED_SOURCE_NAMES = {"upa", "madin_etal", "metatraits", "metatraits_gtdb", "bactotraits"}
VARIANTS = yaml.safe_load((REPO_ROOT / "config" / "merge_variants.yaml").read_text())["variants"]
CONFIG_PATHS = [REPO_ROOT / name for name in ("merge.yaml", *VARIANTS)]


@pytest.mark.parametrize("config_path", CONFIG_PATHS, ids=lambda path: path.name)
def test_shipped_config_accepts_finalized_tsv_contract(config_path):
    """Validate the canonical config and every manifest-generated variant."""
    validate_merge_semantics(yaml.safe_load(config_path.read_text()))


@pytest.mark.parametrize("config_path", CONFIG_PATHS, ids=lambda path: path.name)
def test_source_name_relocation_preserves_effective_kgx_inputs(config_path, tmp_path):
    """Metadata relocation must preserve all inputs without widening their whitelist."""
    prepare_kgx()
    from kgx.cli.cli_utils import prepare_input_args

    config = yaml.safe_load(config_path.read_text())
    sources = config["merged_graph"]["source"]
    relocated_names = RELOCATED_SOURCE_NAMES & sources.keys()
    assert relocated_names, "the fixture must exercise at least one repaired source"
    legacy = deepcopy(config)
    for name in relocated_names:
        assert sources[name]["name"] == name
        assert "name" not in sources[name]["input"]
        legacy_source = legacy["merged_graph"]["source"][name]
        legacy_source["input"]["name"] = legacy_source.pop("name")

    # KGX keys each graph by this source key, not either position of `name`.
    assert list(sources) == list(legacy["merged_graph"]["source"])
    for name, source in sources.items():
        assert prepare_input_args(name, deepcopy(source), str(tmp_path)) == prepare_input_args(
            name, deepcopy(legacy["merged_graph"]["source"][name]), str(tmp_path)
        )

    # The repair belongs in configuration metadata, not an expanded input API.
    with pytest.raises(ValueError, match=r"input: unsupported overrides \['name'\]"):
        validate_merge_semantics(legacy)
