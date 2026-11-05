"""Bind current native category decisions to real 4.4.6 bytes without rewriting history."""

import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from kg_microbe.utils import mesh_finite_categories, ncit_eight_categories
from tests.ncit_eight_fixtures import seed_native_authority

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "tests/resources/biolink_4_4_6"
HISTORICAL = ROOT / "tests/resources/ingredient_bundle/native"
ORIGIN = json.loads((CURRENT / "origin.json").read_text())


@pytest.fixture(scope="module")
def complete_models():
    """Load both immutable complete official model epochs independently of policy contents."""
    return tuple(yaml.safe_load((directory / "biolink-model.yaml").read_text()) for directory in (HISTORICAL, CURRENT))


@pytest.mark.parametrize("name", [*ORIGIN["members"], *ORIGIN["excerpts"]])
def test_official_triplet_and_independent_excerpts_match_observed_bytes(name):
    """Fixture identity comes from retained upstream observations, never mutable policy restamping."""
    entry = ORIGIN["members"].get(name) or ORIGIN["excerpts"][name]
    assert hashlib.sha256((CURRENT / name).read_bytes()).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("module", [ncit_eight_categories, mesh_finite_categories])
def test_production_policy_accepts_complete_current_model_and_rejects_old_epoch(module, complete_models):
    """Exercise actual production validation against both real full models and the complete policy seal."""
    old, new = complete_models
    policy = module.load_policy(io.StringIO(module.POLICY_FILE.read_text()))
    assert policy["model_version"] == "4.4.6"
    assert policy["model_sha256"] == ORIGIN["members"]["biolink-model.yaml"]["sha256"]
    module.validate_model(new, policy)
    with pytest.raises(
        ValueError, match="Finite (NCIT|MeSH) selected (Biolink category evidence|model definitions) changed"
    ):
        module.validate_model(old, policy)
    review = ROOT / policy["model_review"]["file"]
    assert hashlib.sha256(review.read_bytes()).hexdigest() == policy["model_review"]["sha256"]


@pytest.mark.parametrize(
    "name,module",
    [("ncit_eight_categories", ncit_eight_categories), ("mesh_finite_category_dispositions", mesh_finite_categories)],
)
def test_current_binding_preserves_the_entire_reviewed_native_policy(name, module, complete_models):
    """Restoring only the historical model binding reconstructs the exact original policy identity."""
    old, _ = complete_models
    policy = json.loads(module.POLICY_FILE.read_text())
    policy.pop("model_review")
    policy.update(
        model_version=old["version"],
        model_sha256=hashlib.sha256((HISTORICAL / "biolink-model.yaml").read_bytes()).hexdigest(),
        model_classes={key: old["classes"][key] for key in policy["model_classes"]},
    )
    assert module.digest(module.canonical(policy).encode()) == ORIGIN["historical_policy_canonical_sha256"][name]


@pytest.mark.parametrize("module", [ncit_eight_categories, mesh_finite_categories])
def test_model_binding_and_review_cannot_be_edited_without_the_policy_seal(module):
    """Reject a candidate-model or review-evidence restamp before trusting its meaning."""
    original = json.loads(module.POLICY_FILE.read_text())
    for field in ("model_sha256", "model_review"):
        changed = copy.deepcopy(original)
        if field == "model_review":
            changed[field]["sha256"] = "0" * 64
        else:
            changed[field] = "0" * 64
        with pytest.raises(ValueError, match="Unreviewed"):
            module.load_policy(io.StringIO(json.dumps(changed)))


def test_historical_ingredient_fixture_selects_original_model_and_policy(tmp_path, monkeypatch, complete_models):
    """Keep old ingredient acceptance truthful while current production rejects the old epoch."""
    raw, _, policy = seed_native_authority(tmp_path, monkeypatch, model_path=HISTORICAL / "biolink-model.yaml")
    assert policy["model_version"] == "4.4.2"
    assert "model_review" not in policy
    assert hashlib.sha256((raw / "biolink-model.yaml").read_bytes()).hexdigest() == policy["model_sha256"]
    assert (
        ncit_eight_categories.digest(ncit_eight_categories.canonical(policy).encode())
        == ORIGIN["historical_policy_canonical_sha256"]["ncit_eight_categories"]
    )
    ncit_eight_categories.validate_model(complete_models[0], policy)
