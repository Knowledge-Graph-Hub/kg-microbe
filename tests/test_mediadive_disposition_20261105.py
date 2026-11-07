"""Reviewed policy bytes remain fixed until actual generation activation."""

import json
from types import SimpleNamespace

import pytest

from kg_microbe.transform_utils.mediadive import acquisition, endpoint_outcomes
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from scripts.adhoc import kgm_mediadive_disposition_20261105 as helper
from tests.mediadive_generation_fixtures import seal_fixture_raw


def _reviewed(tmp_path, monkeypatch):
    """Prepare a real one-medium unknown generation and explicit synthetic independent review."""
    raw = tmp_path / "data/raw"
    bulk = raw / "mediadive"
    bulk.mkdir(parents=True)
    (raw / "mediadive.json").write_text(json.dumps({"status": 200, "count": 1, "data": [{"id": 1}]}, indent=2) + "\n")
    for name, value in {
        "media_detailed.json": {"1": {"medium": {"id": 1}}},
        "media_strains.json": {},
        "solutions.json": {},
        "compounds.json": {},
    }.items():
        (bulk / name).write_text(json.dumps(value) + "\n")
    view = seal_fixture_raw(raw, unknown_ids=("1",))
    monkeypatch.setattr(endpoint_outcomes, "CURATED_UNKNOWN_POLICY", view.curated_policy_path)
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper, "RAW", bulk)
    # This controlled fixture represents an unselected sealed parent for initial activation.
    (bulk / "current.json").unlink()
    policy_sha = helper.digest(view.curated_policy_path)
    review = tmp_path / "independent-review.json"
    review.write_text(json.dumps({"status": "pass", "policy_sha256": policy_sha}))
    args = SimpleNamespace(
        policy_sha256=policy_sha, review=review, review_sha256=helper.digest(review), generation_id="admitted"
    )
    return args, view


def test_unchanged_reviewed_policy_is_activated(tmp_path, monkeypatch):
    """Exact reviewed policy and native evidence can produce a qualified current pointer."""
    args, parent = _reviewed(tmp_path, monkeypatch)
    result = helper.admit(args, parent)
    assert result["status"] == "pass"
    assert result["generation"]["policy"]["sha256"] == args.policy_sha256
    assert result["generation"]["curated_policy"]["sha256"] == args.policy_sha256
    assert result["qualification"]["association_coverage_complete"] is False
    assert (helper.RAW / "current.json").is_file()


@pytest.mark.parametrize("changed", ["policy", "review"])
def test_post_review_mutation_cannot_reach_publication(tmp_path, monkeypatch, changed):
    """A changed but structurally valid policy cannot inherit the preceding independent review."""
    args, parent = _reviewed(tmp_path, monkeypatch)
    real = acquisition.checkpoint_generation

    def replace_after_initial_check(handle, **kwargs):
        """Model a competing write after review validation and before checkpoint consumption."""
        path = parent.curated_policy_path if changed == "policy" else args.review
        value = json.loads(path.read_text())
        value["scientific_impact" if changed == "policy" else "new_unreviewed_field"] = (
            "Changed after independent review"
        )
        path.write_text(json.dumps(value))
        return real(handle, **kwargs)

    monkeypatch.setattr(acquisition, "checkpoint_generation", replace_after_initial_check)
    with pytest.raises((ValueError, SourceFinalizationRequired), match="changed|differs"):
        helper.admit(args, parent)
    assert not (helper.RAW / "current.json").exists()


def test_review_of_another_policy_refuses_before_staging(tmp_path, monkeypatch):
    """An externally supplied review hash is insufficient when it names different policy bytes."""
    args, parent = _reviewed(tmp_path, monkeypatch)
    args.review.write_text(json.dumps({"status": "pass", "policy_sha256": "different"}))
    args.review_sha256 = helper.digest(args.review)
    with pytest.raises(ValueError, match="does not approve"):
        helper.admit(args, parent)
    assert not (helper.RAW / ".staging/admitted").exists()
    assert not (helper.RAW / "current.json").exists()
