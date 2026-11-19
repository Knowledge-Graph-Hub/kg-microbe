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
    plan = {
        "revision": "corrected",
        "shared": {"python": "pinned"},
        "code_inputs": {
            "kg_microbe/transform_utils/bactotraits/bactotraits.py": "c" * 64,
            "kg_microbe/utils/source_finalization.py": "d" * 64,
        },
        "policy": {
            "path": str(tmp_path / "mappings/canonical/bactotraits_identity_quarantine.json"),
            "sha256": "e" * 64,
            "bytes": 42,
        },
    }
    receipt = {
        "profile": helper.replay.PROFILE,
        "mode": "candidate",
        "git_revision": plan["revision"],
        "shared_inputs": plan["shared"],
        "code_inputs": dict(plan["code_inputs"]),
        "consumed_inputs": {
            "bactotraits_identity_policy": {key: plan["policy"][key] for key in ("path", "sha256")},
        },
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


@pytest.mark.parametrize("damage", ["changed_file", "missing_file", "extra_file"])
def test_same_head_candidate_code_drift_is_rejected(helper, paired_receipt, damage):
    """#1876: a shared Git HEAD does not make differing dirty source inventories equivalent."""
    path, plan, baseline, receipt, _ = paired_receipt
    assert helper.checked_receipt(path, plan, baseline)["sha256"] == helper.replay.digest(path.read_bytes())
    source = "kg_microbe/transform_utils/bactotraits/bactotraits.py"
    if damage == "changed_file":
        receipt["code_inputs"][source] = "f" * 64
    elif damage == "missing_file":
        del receipt["code_inputs"][source]
    else:
        receipt["code_inputs"]["kg_microbe/extra.py"] = "f" * 64
    path.write_text(json.dumps(receipt))
    assert receipt["git_revision"] == plan["revision"]
    with pytest.raises(ValueError, match="Candidate pair implementation inputs differ"):
        helper.checked_receipt(path, plan, baseline)


@pytest.mark.parametrize("field", ["path", "sha256"])
def test_same_head_candidate_policy_drift_is_rejected(helper, paired_receipt, field):
    """#1876: compare the actual consumed policy, independently of unchanged code and Git HEAD."""
    path, plan, baseline, receipt, _ = paired_receipt
    receipt["consumed_inputs"]["bactotraits_identity_policy"][field] = (
        str(path.parent / "different-policy.json") if field == "path" else "f" * 64
    )
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Candidate pair consumed policy differs"):
        helper.checked_receipt(path, plan, baseline)


@pytest.mark.parametrize("value", [None, [], {}, {"kg_microbe/producer.py": "not-a-sha256"}])
def test_malformed_candidate_code_identity_is_rejected(helper, paired_receipt, value):
    """Missing or malformed code inventories receive an explicit provenance failure."""
    path, plan, baseline, receipt, _ = paired_receipt
    receipt["code_inputs"] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Candidate receipt code inputs missing or malformed"):
        helper.checked_receipt(path, plan, baseline)


@pytest.mark.parametrize("field", ["code_inputs", "consumed_inputs", "policy", "path", "sha256"])
def test_missing_candidate_identity_is_rejected(helper, paired_receipt, field):
    """A historical receipt must carry both exact implementation and consumed-policy identities."""
    path, plan, baseline, receipt, _ = paired_receipt
    if field in {"code_inputs", "consumed_inputs"}:
        del receipt[field]
    elif field == "policy":
        del receipt["consumed_inputs"]["bactotraits_identity_policy"]
    else:
        del receipt["consumed_inputs"]["bactotraits_identity_policy"][field]
    path.write_text(json.dumps(receipt))
    expected = "code inputs" if field == "code_inputs" else "consumed policy"
    with pytest.raises(ValueError, match=f"Candidate receipt {expected} missing or malformed"):
        helper.checked_receipt(path, plan, baseline)


@pytest.mark.parametrize(
    "value",
    [None, [], {}, {"path": "/policy.json", "sha256": "not-a-sha256"}, {"path": None, "sha256": "e" * 64}],
)
def test_malformed_candidate_policy_identity_is_rejected(helper, paired_receipt, value):
    """An incomplete or mistyped policy snapshot cannot certify a preceding candidate."""
    path, plan, baseline, receipt, _ = paired_receipt
    receipt["consumed_inputs"]["bactotraits_identity_policy"] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Candidate receipt consumed policy missing or malformed"):
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
