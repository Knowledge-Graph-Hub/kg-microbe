#!/usr/bin/env python3
"""
2026-11-16: bounded M5 finalization check for the exact BactoTraits #130 row.

Inputs: a new completed baseline/candidate replay pair, unchanged original raw
inputs, current corrected producer, pinned local schema and retained NCBI DB.
Outputs: one exclusive private producer/finalizer stage and strict merge refusal
evidence. The real finalizer runs on the same live object as the real producer.
This does not rebuild the BacDive/ontologies dependency chain and must not claim
a merged graph or publication. No network, subprocess or freshness bypass runs.
The earlier replay helper and its pre-finalization receipts remain unchanged.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import importlib.util
import json
import os
import socket
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REPLAY_FILE = Path(__file__).with_name("replay_bactotraits_identity_130_20261115.py")
SPEC = importlib.util.spec_from_file_location("bactotraits_pre_finalization_replay", REPLAY_FILE)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)
PROFILE = "bactotraits-130-bounded-finalization/v1"
SCHEMA_NAMES = ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml")


def checked_receipt(path, plan, baseline):
    """Reject a mismatched, finalized or modified pre-finalization candidate pair."""
    path = replay.safe_path(path)
    raw = replay.bytes_at(path)
    receipt = json.loads(raw)
    replay.require(
        receipt["profile"] == replay.PROFILE
        and receipt["mode"] == "candidate"
        and receipt["git_revision"] == plan["revision"]
        and receipt["finalization_run"] is False,
        "Expected an unchanged pre-finalization candidate receipt",
    )
    replay.require(receipt["shared_inputs"] == plan["shared"], "Candidate pair inputs/runtime differ")
    replay.require(
        receipt["baseline_receipt"] == {"path": str(baseline[0]), "sha256": baseline[1]},
        "Candidate receipt belongs to a different baseline pair",
    )
    replay.require(
        receipt["all_edge_count"] == receipt["node_count"] == 0 and receipt["quarantine_rows"] == 1,
        "Candidate pair did not prove the expected exact-row quarantine",
    )
    members = {f"transformed/bactotraits/{name}" for name in ("nodes.tsv", "edges.tsv", replay.AUDIT)}
    replay.require(members <= receipt["artifacts"].keys(), "Candidate pair lacks persisted graph/audit identities")
    for name, identity in receipt["artifacts"].items():
        artifact = replay.safe_path(path.parent / name)
        replay.require(artifact.is_relative_to(path.parent), "Escaping candidate artifact")
        payload = replay.bytes_at(artifact)
        replay.require(
            {"bytes": len(payload), "sha256": replay.digest(payload)} == identity,
            f"Candidate pair artifact changed: {name}",
        )
    for kind in ("nodes", "edges"):
        replay.require(
            not replay.graph_rows(path.parent / f"transformed/bactotraits/{kind}.tsv"),
            "Candidate pair persisted graph is not empty",
        )
    replay.require(
        len(replay.graph_rows(path.parent / "transformed/bactotraits" / replay.AUDIT)) == 1,
        "Candidate pair persisted audit differs",
    )
    return {"path": str(path), "sha256": replay.digest(raw)}


def merge_configuration(stage):
    """Select only the new source through the ordinary strict production merge API."""
    source = stage / "transformed/bactotraits"
    return {
        "configuration": {
            "output_directory": str(stage / "merged"),
            "checkpoint": False,
            "preserve": ["primary_knowledge_source"],
            "category_allowlist": ["METPO:1004005"],
        },
        "merged_graph": {
            "name": "bounded BactoTraits identity correction candidate",
            "source": {
                "bactotraits": {
                    "name": "BactoTraits",
                    "input": {
                        "format": "tsv",
                        "filename": [str(source / name) for name in ("nodes.tsv", "edges.tsv")],
                    },
                }
            },
            "destination": {"merged": {"format": "tsv", "compression": "tar.gz", "filename": "bounded-kg"}},
        },
    }


def verify_quarantine(producer, plan):
    """Check the complete original occurrence and zero emitted graph rows on disk."""
    replay.require(not replay.graph_rows(producer.output_node_file), "Quarantined row emitted nodes")
    replay.require(not replay.graph_rows(producer.output_edge_file), "Quarantined row emitted edges")
    rows = replay.graph_rows(producer.output_dir / replay.AUDIT)
    replay.require(len(rows) == 1, "Expected one complete quarantine audit")
    row = rows[0]
    expected = {
        "bacdive_id": "17851",
        "ncbitaxon_id": replay.SUBJECT,
        "row_sha256": replay.ROW_SHA,
        "source_data_row": "1",
        "reviewed_source_data_row": "8521",
        "source_sha256": replay.digest(plan["staged"]["raw/BactoTraits_databaseV2_Jun2022.csv"]),
        "reviewed_source_sha256": replay.SOURCE_SHA,
        "policy_sha256": plan["policy"]["sha256"],
        "disposition": "quarantine_mixed_strain_row",
    }
    replay.require(all(row[key] == value for key, value in expected.items()), "Quarantine identity differs")
    replay.require(json.loads(row["raw_row_json"]) == plan["row"], "Complete original row differs")
    return replay.digest(replay.bytes_at(producer.output_dir / replay.AUDIT))


def strict_merge_attempt(config_path, stage):
    """Accept only the precise missing-upstream refusal, never arbitrary pipeline failure."""
    from kg_microbe.merge_utils.merge_kg import load_and_merge
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    expected = str(stage / "transformed/bacdive/source_finalization.json")
    try:
        load_and_merge(str(config_path), processes=1)
    except SourceFinalizationRequired as error:
        message = str(error)
        replay.require(
            "bactotraits: invalid upstream bacdive:" in message
            and "Missing/unreadable whole-source finalization record:" in message
            and expected in message,
            f"Unexpected strict merge failure: {message}",
        )
        output = stage / "merged"
        replay.require(not output.exists() or not any(output.iterdir()), "Rejected merge published files")
        return {
            "status": "blocked_missing_current_bacdive_dependency",
            "exception": type(error).__name__,
            "message": message,
        }
    raise ValueError("Bounded candidate unexpectedly passed strict merge without completed dependencies")


def prepare(args):
    """Bind the prior new pair, current implementation, schema and strict configuration."""
    args.mode = "candidate"
    plan = replay.prepare(args)
    replay.require(plan["code_root"] == ROOT, "Finalization must use this helper's current corrected checkout")
    baseline = replay.baseline_data(args, plan["shared"])
    plan["baseline"] = {"path": str(baseline[0]), "sha256": baseline[1]}
    plan["candidate"] = checked_receipt(args.candidate_receipt, plan, baseline)
    plan["schema"] = [
        replay.source_pin(ROOT / "data/raw" / name, replay.bytes_at(ROOT / "data/raw" / name)) for name in SCHEMA_NAMES
    ]
    # Read this static declaration without importing the dependency/cache chain
    # during the read-only plan. Its Python bytes are already in code_inputs.
    fingerprint_file = ROOT / "kg_microbe/utils/transform_fingerprint.py"
    fingerprint_bytes = replay.bytes_at(fingerprint_file)
    replay.require(
        replay.digest(fingerprint_bytes) == plan["code_inputs"][str(fingerprint_file.relative_to(ROOT))],
        "Finalization input declaration changed during planning",
    )
    declarations = [
        node.value
        for node in ast.parse(fingerprint_bytes).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SHARED_DATA_INPUTS" for target in node.targets)
    ]
    replay.require(len(declarations) == 1, "Ambiguous shared finalization input declaration")
    shared_paths = ast.literal_eval(declarations[0])
    replay.require(isinstance(shared_paths, tuple) and bool(shared_paths), "Shared finalization inputs missing")
    plan["finalization_data"] = [replay.source_pin(ROOT / name, replay.bytes_at(ROOT / name)) for name in shared_paths]
    plan["configuration"] = merge_configuration(plan["stage"])
    plan["finalization_helper_sha256"] = replay.digest(Path(__file__).read_bytes())
    return plan


def verify_pins(plan):
    """Refuse an implementation, schema, authority or paired-receipt change during execution."""
    replay.verify_runtime_inputs(plan)
    for name, expected in plan["code_inputs"].items():
        replay.require(replay.digest(replay.bytes_at(ROOT / name)) == expected, "Implementation changed")
    for identity in (*plan["schema"], *plan["finalization_data"], plan["baseline"], plan["candidate"], plan["policy"]):
        replay.require(
            replay.digest(replay.bytes_at(Path(identity["path"]))) == identity["sha256"], "Pinned input changed"
        )
    replay.require(
        replay.digest(Path(__file__).read_bytes()) == plan["finalization_helper_sha256"], "Finalization helper changed"
    )
    database = Path(plan["authority"]["database_metadata"]["path"])
    replay.require(replay.database_stat(database) == plan["authority"]["database_metadata"], "NCBI DB metadata changed")
    replay.require(
        replay.authority_rows(database) == plan["authority"]["queried_statements"], "NCBI authority statements changed"
    )
    for name, loaded in tuple(sys.modules.items()):
        filename = getattr(loaded, "__file__", None)
        if name.startswith("kg_microbe") and filename and Path(filename).suffix == ".py":
            path = Path(filename).resolve()
            replay.require(path.is_relative_to(ROOT), "Mixed KG-Microbe implementation checkouts")
            replay.require(str(path.relative_to(ROOT)) in plan["code_inputs"], "Unpinned imported implementation")


def run(args, plan):
    """Execute one real producer/finalizer unit, inspect it, and retain strict merge refusal."""
    stage = plan["stage"]
    os.umask(0o077)
    replay.STAGING_ROOT.mkdir(mode=0o700, exist_ok=True)
    stage.mkdir(mode=0o700)
    for name, payload in plan["staged"].items():
        replay.write_new(stage / name, payload)
    record = {key: value for key, value in plan.items() if key not in {"stage", "code_root", "staged"}}
    replay.write_new(stage / "input-plan.json", replay.json_bytes(record))
    config_path = stage / "merge.json"
    replay.write_new(config_path, replay.json_bytes(plan["configuration"]))
    temporary = replay.configure_private_environment(stage)
    sys.path.insert(0, str(ROOT))
    replay.install_guards(stage)
    with (stage / "execution.stdout.txt").open("x") as stdout, (stage / "execution.stderr.txt").open("x") as stderr:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from kg_microbe.transform import _record_fingerprint
            from kg_microbe.transform_utils.bactotraits import bactotraits as module
            from kg_microbe.utils import mapping_file_utils
            from kg_microbe.utils.producer_audits import verify_producer_audits
            from kg_microbe.utils.source_finalization import verify_finalized_source_files

            module.BACTOTRAITS_TMP_DIR = temporary / "bactotraits"
            module.BACDIVE_TMP_DIR = stage / "lookup"
            module.CUSTOM_CURIES_YAML_FILE = stage / "mappings/custom_curies.yaml"
            mapping_file_utils.LOCAL_METPO_ALIAS_OVERRIDES_PATH = stage / "mappings/metpo_alias_mappings.tsv"
            replay.bind_staged_prefix_registry(stage)
            verify_pins(plan)
            producer = module.BactoTraitsTransform(stage / "raw", stage / "transformed")
            producer.ncbi_impl = replay.ReadOnlyNCBILabels(
                Path(plan["authority"]["database_metadata"]["path"]), plan["authority"]["queried_statements"]
            )
            producer.run(show_status=False)
            producer.verify_consumed_inputs()
            verify_producer_audits(producer)
            original_audit = verify_quarantine(producer, plan)
            report = producer.finalize(fresh_run=True)
            _record_fingerprint(producer, "bactotraits")
            replay.require((producer.output_dir / "source_fingerprint.json").is_file(), "Producer fingerprint absent")
            verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
            replay.require(verify_quarantine(producer, plan) == original_audit, "Finalization changed quarantine audit")
            merge = strict_merge_attempt(config_path, stage)
            replay.require(
                replay.bytes_at(config_path) == replay.json_bytes(plan["configuration"]), "Merge configuration changed"
            )
            verify_pins(plan)
            verify_producer_audits(producer)
            verify_finalized_source_files([producer.output_node_file, producer.output_edge_file])
    artifacts = {}
    for path in sorted(stage.rglob("*")):
        replay.safe_path(path)
        if path.is_file():
            replay.require(stat.S_IMODE(path.stat().st_mode) == 0o600, "Artifact is not private")
            artifacts[str(path.relative_to(stage))] = {
                "bytes": path.stat().st_size,
                "sha256": replay.digest(path.read_bytes()),
            }
    result = {
        "profile": PROFILE,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "process": {"pid": os.getpid(), "host": socket.gethostname(), "argv": sys.argv, "processes": 1},
        "git_revision": plan["revision"],
        "code_root": str(ROOT),
        "code_inputs": plan["code_inputs"],
        "shared_inputs": plan["shared"],
        "finalization_helper_sha256": plan["finalization_helper_sha256"],
        "baseline_receipt": plan["baseline"],
        "candidate_receipt": plan["candidate"],
        "schema": plan["schema"],
        "finalization_data": plan["finalization_data"],
        "artifacts": artifacts,
        "finalization_report": report,
        "finalization_run": True,
        "finalized_node_count": 0,
        "finalized_edge_count": 0,
        "quarantine_rows": 1,
        "quarantine_audit_unchanged": True,
        "merge": merge,
        "merged_graph_verified": False,
        "published_release_verified": False,
        "scientific_claim_resolved": False,
        "provider_calls": 0,
        "scope": "One original row through actual producer and finalizer; strict merge blocked by absent upstream.",
    }
    replay.write_new(stage / "receipt.json", replay.json_bytes(result))
    replay.require(json.loads((stage / "receipt.json").read_text()) == result, "Receipt readback differs")
    return {"receipt": str(stage / "receipt.json"), "finalization_run": True, "merge": merge}


def main():
    """Require an explicit read-only plan or one bounded actual execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--code-root", type=Path, default=ROOT)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, default=replay.CANONICAL)
    parser.add_argument("--ncbi-db", type=Path, default=replay.CANONICAL / "data/raw/ncbitaxon.db")
    parser.add_argument("--baseline-receipt", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    args = parser.parse_args()
    csv.field_size_limit(16 * 1024 * 1024)
    plan = prepare(args)
    if args.plan:
        result = {
            "action": "plan",
            "ready": True,
            "writes": 0,
            "provider_calls": 0,
            "stage": str(plan["stage"]),
            "git_revision": plan["revision"],
            "baseline_receipt": plan["baseline"],
            "candidate_receipt": plan["candidate"],
            "expected_merge_status": "blocked_missing_current_bacdive_dependency",
            "scope": "Fresh exact-row producer/finalizer; strict merge admission attempt only",
        }
    else:
        result = run(args, plan)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
