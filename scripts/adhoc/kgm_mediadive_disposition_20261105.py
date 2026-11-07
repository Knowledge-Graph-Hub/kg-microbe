#!/usr/bin/env python3
"""
Propose and admit the finite reviewed MediaDive unknown cohort for the M5 rebuild.

Purpose/date: #1734 scientific disposition and independent release checks, 2026-11-05.
Inputs: actual sealed endpoint generation, pinned receipts and reviewed curated policy.
Outputs: new policy candidate/admission evidence; no HTTP, graph producer or GitHub writes.
Proposal cannot publish a generation. Activation requires exact externally reviewed bytes.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "data/rebuild-evidence/20261105/mediadive-resolution-1734"
RAW = ROOT / "data/raw/mediadive"


def require(condition, message):
    """Refuse unsupported scientific admission or evidence replacement."""
    if not condition:
        raise ValueError(message)


def digest(path):
    """Identify retained original bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    """Write new evidence exclusively under this run's existing evidence root."""
    path = Path(path).resolve()
    require(path.is_relative_to(R), "Evidence output must remain inside this run")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def view_from_receipt(path, expected):
    """Replay the exact immutable completed acquisition generation without changing policy or pointers."""
    from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes

    require(digest(path) == expected, "Acquisition receipt changed")
    receipt = outcomes.strict_json(Path(path).read_bytes())
    require(receipt["status"] == "verified" and receipt["step"] == "batch", "Require completed bounded batch")
    view = outcomes.validate_generation(
        receipt["generation"], receipt["manifest_sha256"], require_current=False, require_admissible=False
    )
    require(view.qualification["unresolved_endpoints"] == [], "Transport/malformed/missing evidence remains")
    require(view.qualification["recipe_coverage_complete"] is True, "Recipe coverage is incomplete")
    require(len(view.catalogue["data"]) == 3344 and len(view.endpoint_records) == 6688, "Reviewed scope changed")
    require(
        view.qualification["state_counts"]
        == {
            "nonempty": 6056,
            "explicit_empty": 0,
            "unknown_unavailable": 632,
            "transport_error": 0,
            "malformed": 0,
            "missing_evidence": 0,
        },
        "Actual finite disposition cohort changed",
    )
    return view


def proposal(view):
    """Bind only actual latest documented unknown observations; never create absent association data."""
    from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes

    unknown = {url: record for url, record in view.endpoint_records.items() if record["state"] == "unknown_unavailable"}
    evidence = {}
    for name in (
        "identity-comparison-1.json",
        "control-r2-scientific-comparison-1.json",
        "unknown-r2-scientific-assessment-1.json",
        "finite-unknown-policy-review-criteria-1.json",
    ):
        evidence[name] = digest(R / name)
    return {
        "schema_version": 1,
        "policy_version": "mediadive-source-unknown-20261105-v1",
        "catalogue_sha256": digest(view.native_paths["mediadive_media_list"]),
        "official_contract": {
            "version": outcomes.ERROR_CONTRACT,
            "documentation_url": "https://mediadive.dsmz.de/doc/assets/main.bundle.js",
            "documentation_sha256": digest(view.generation_dir / "official-documentation.body"),
        },
        "cases": {
            url: {
                "medium_id": url.rsplit("/", 1)[-1],
                "observation_id": record["observation_id"],
                "body_sha256": record["body_sha256"],
            }
            for url, record in sorted(unknown.items())
        },
        "scientific_impact": (
            "632 of 3344 exact medium-strain endpoints returned the documented ambiguous DataNotFound 404. "
            "These are source-declared unknown/unavailable associations, not valid empty lists, nonexistent media, "
            "negative growth evidence, or complete association data. All 3344 recipe responses and 2712 nonempty "
            "strain responses remain supported by their original source bytes. No explicit empty response was observed."
        ),
        "downstream_handling": (
            "Keep complete endpoint accounting separate from association coverage. Preserve all known native recipe "
            "and strain assertions. Emit no MediaDive strain, positive-growth, negative-growth or absence assertions "
            "from these 632 unknown endpoints. Carry exact per-endpoint outcomes and "
            "association_coverage_complete=false "
            "through consumed inputs, producer completion, independent replay and graph artifact qualifications, "
            "including admitted dependencies. Other independently evidenced sources retain their own claims. "
            "A later changed source observation requires a new generation and reviewed exact-case binding."
        ),
        "source_freshness_limitations": (
            "The API has no verified atomic dataset version. Retained client observation times, server Date headers, "
            "request identities and actual response bodies describe each observation, not one globally simultaneous "
            "snapshot. The latest 49 transport failures were resolved only by subsequent fresh source responses; "
            "earlier 404s were not substituted. SPARQL exact-ID/control probes established limited identities and "
            "positive control polarity but no dataset freshness or complete association coverage. Zero queried "
            "growth rows for 1366 do not establish an empty list or a negative claim."
        ),
        "association_coverage_complete": False,
        "endpoint_accounting_complete": True,
        "basis_generation": {"id": view.generation_dir.name, "manifest_sha256": view.manifest_identity["sha256"]},
        "supporting_review_sha256": evidence,
    }


def admit(args, parent):
    """Publish only a newly sealed child using an exact independently reviewed curated policy."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.transform_utils.mediadive import acquisition
    from kg_microbe.transform_utils.mediadive import endpoint_outcomes as outcomes

    guard = SourceAdmission()
    policy_bytes = guard.capture(outcomes.CURATED_UNKNOWN_POLICY, retain=True)
    review_bytes = guard.capture(args.review, retain=True)
    require(
        hashlib.sha256(policy_bytes).hexdigest() == args.policy_sha256, "Curated policy differs from reviewed bytes"
    )
    require(hashlib.sha256(review_bytes).hexdigest() == args.review_sha256, "Independent policy review changed")
    review = outcomes.strict_json(review_bytes)
    require(
        review.get("status") == "pass" and review.get("policy_sha256") == args.policy_sha256,
        "Independent review does not approve this exact policy",
    )
    require(not (RAW / "current.json").exists(), "Initial activation requires explicit absent current pointer")
    require(args.generation_id, "An explicit new activation generation ID is required")
    with acquisition.start_generation(
        RAW,
        args.generation_id,
        ROOT / "data/raw/mediadive.json",
        base_generation=parent,
        evidence_files={"evidence/finite-policy-independent-review.json": Path(args.review)},
    ) as handle:
        result = acquisition.checkpoint_generation(handle, unknown_policy=outcomes.CURATED_UNKNOWN_POLICY)
    require(result.qualification["admissible"] is True, "Reviewed disposition did not establish legitimate admission")
    require(result.qualification["association_coverage_complete"] is False, "Unknown cohort cannot claim completeness")
    guard.verify()
    contract = result.contract()
    require(
        all(contract[role]["sha256"] == args.policy_sha256 for role in ("policy", "curated_policy")),
        "Checkpoint policy differs from independently reviewed bytes",
    )
    guard.verify()
    result = acquisition.publish_generation(RAW, args.generation_id, result.manifest_identity["sha256"], None)
    return {
        "status": "pass",
        "generation": result.contract(),
        "qualification": result.qualification,
        "review": {"path": str(Path(args.review).resolve()), "sha256": args.review_sha256},
        "policy_sha256": args.policy_sha256,
    }


def main():
    """Run one bounded read-only proposal or explicitly reviewed initial activation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["propose", "admit"])
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--generation-id")
    parser.add_argument("--policy-sha256")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--review-sha256")
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT and sys.dont_write_bytecode, "Use the owned bytecode-disabled launcher")
    require(
        Path(os.environ.get("KGM_REBUILD_LAUNCHER", "")).resolve() == ROOT / "scripts/adhoc/kgm_rebuild_20261105.py",
        "Production launcher required",
    )
    require(args.output.resolve().is_relative_to(R), "Evidence output must remain inside this run")
    require(not args.output.exists(), "Evidence output already exists")
    require(
        args.mode == "propose" or all((args.generation_id, args.policy_sha256, args.review, args.review_sha256)),
        "Activation requires explicit generation, policy and independent review identities",
    )
    view = view_from_receipt(args.receipt, args.receipt_sha256)
    result = proposal(view) if args.mode == "propose" else admit(args, view)
    save(args.output, result)
    print(json.dumps({"output": str(args.output), "sha256": digest(args.output), "mode": args.mode}))


if __name__ == "__main__":
    main()
