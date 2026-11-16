"""Keep bounded finalization evidence distinct from strict production merge acceptance."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/adhoc/finalize_bactotraits_identity_130_20261116.py"


@pytest.fixture
def helper():
    """Load the separate bounded helper without invoking its plan or live producer."""
    spec = importlib.util.spec_from_file_location("bactotraits_bounded_finalization", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paired_receipt(tmp_path, helper):
    """Bind a small prior receipt to one immutable artifact and one baseline identity."""
    source = tmp_path / "transformed/bactotraits"
    source.mkdir(parents=True)
    artifact = source / "nodes.tsv"
    artifact.write_bytes(b"id\tcategory\n")
    (source / "edges.tsv").write_bytes(b"subject\tpredicate\tobject\n")
    (source / helper.replay.AUDIT).write_bytes(b"row_sha256\noriginal\n")
    baseline = (tmp_path / "baseline.json", "a" * 64, [])
    plan = {"revision": "corrected", "shared": {"python": "pinned"}}
    receipt = {
        "profile": helper.replay.PROFILE,
        "mode": "candidate",
        "git_revision": plan["revision"],
        "shared_inputs": plan["shared"],
        "baseline_receipt": {"path": str(baseline[0]), "sha256": baseline[1]},
        "finalization_run": False,
        "all_edge_count": 0,
        "node_count": 0,
        "quarantine_rows": 1,
        "artifacts": {
            str(member.relative_to(tmp_path)): {
                "bytes": member.stat().st_size,
                "sha256": helper.replay.digest(member.read_bytes()),
            }
            for member in source.iterdir()
        },
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(receipt))
    return path, plan, baseline, receipt, artifact


@pytest.mark.parametrize("damage", ["artifact", "runtime", "baseline", "finalized"])
def test_changed_prior_pair_is_rejected(helper, paired_receipt, damage):
    """A new finalizer must not lend valid provenance to modified or unrelated prior execution."""
    path, plan, baseline, receipt, artifact = paired_receipt
    assert helper.checked_receipt(path, plan, baseline)["sha256"] == helper.replay.digest(path.read_bytes())
    if damage == "artifact":
        artifact.write_text("rewritten\n")
    elif damage == "runtime":
        receipt["shared_inputs"] = {"python": "different"}
    elif damage == "baseline":
        receipt["baseline_receipt"]["sha256"] = "b" * 64
    else:
        receipt["finalization_run"] = True
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        helper.checked_receipt(path, plan, baseline)


@pytest.mark.usefixtures("local_source_schema")
def test_actual_merge_gate_refuses_missing_bacdive_without_publishing(helper, tmp_path):
    """The real registered source/finalizer metadata cannot stand in for the required upstream."""
    from tests.test_merge_source_freshness import prepare_source

    stage = tmp_path.resolve()
    prepare_source(stage, "bactotraits", upstream=False)
    config = stage / "merge.json"
    config.write_text(json.dumps(helper.merge_configuration(stage)))
    result = helper.strict_merge_attempt(config, stage)
    assert result["status"] == "blocked_missing_current_bacdive_dependency"
    assert not (stage / "merged").exists()


def test_unfinalized_source_is_not_misreported_as_expected_upstream_blocker(helper, tmp_path):
    """A different finalization failure aborts the helper instead of receiving a completed receipt."""
    stage = tmp_path.resolve()
    source = stage / "transformed/bactotraits"
    source.mkdir(parents=True)
    (source / "nodes.tsv").write_text("id\tcategory\n")
    (source / "edges.tsv").write_text("subject\tpredicate\tobject\n")
    config = stage / "merge.json"
    config.write_text(json.dumps(helper.merge_configuration(stage)))
    with pytest.raises(ValueError, match="Unexpected strict merge failure"):
        helper.strict_merge_attempt(config, stage)
    assert not (stage / "merged").exists()
