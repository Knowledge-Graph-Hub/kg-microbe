#!/usr/bin/env python3
"""
Review 2026-11-05 ROBOT/UPA and Rhea candidates without promoting inputs.

Read preserved and candidate inputs; write a new evidence directory only. No
network, ontology conversion, graph transform, policy update, or raw promotion is
performed. Provisional Rhea policies are diagnostics, never reviewed production
policies. Evidence retains actual native differences and consumed-input checks.
"""

import argparse
import copy
import hashlib
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "data/rebuild-evidence/20261105/upgrades"


def require(condition, message):
    """Reject incomplete review prerequisites without repairing them."""
    if not condition:
        raise ValueError(message)


def canonical(value):
    """Serialize object keys deterministically, retaining every list occurrence/order."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def file_identity(path):
    """Record actual complete bytes and the explicit local locator."""
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def write_json(path, value):
    """Write new evidence without overwriting an earlier review."""
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def mapping_delta(before, after):
    """Retain complete changed records, including additions and removals."""
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key) or (key in before) != (key in after)
    }


def multiset_delta(before, after):
    """Compare record occurrences without dropping duplicates."""
    left, right = Counter(map(canonical, before)), Counter(map(canonical, after))
    return {
        "removed": [{"record": json.loads(key), "count": count} for key, count in sorted((left - right).items())],
        "added": [{"record": json.loads(key), "count": count} for key, count in sorted((right - left).items())],
    }


def native_upa_projection(document):
    """Project keyed declarations and edge occurrences while exposing array-order changes."""
    graphs = document.get("graphs")
    require(isinstance(graphs, list) and len(graphs) == 1, "Expected one native UPA graph")
    graph = graphs[0]
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    require(isinstance(nodes, list) and isinstance(edges, list), "UPA graph lacks nodes/edges")
    by_id = {}
    for node in nodes:
        require(isinstance(node, dict) and isinstance(node.get("id"), str), "Invalid UPA node")
        require(node["id"] not in by_id, "Duplicate UPA node ID")
        by_id[node["id"]] = node
    return {
        "nodes": by_id,
        "node_order": [node["id"] for node in nodes],
        "edges": edges,
        "graph_other_fields": {key: value for key, value in graph.items() if key not in {"nodes", "edges"}},
        "document_other_fields": {key: value for key, value in document.items() if key != "graphs"},
    }


def verify_upa_finite(module, policy, document, owl, connection, authority):
    """Run the existing finite witness gate and report its exact failure, if any."""
    try:
        present = module._verify_finite(policy, document, owl, connection, authority)
        require(present, "The seven-rule finite UPA cohort is absent")
        return {"passed": True}
    except ValueError as exc:
        return {"passed": False, "error": str(exc)}


def compare_upa(args, evidence):
    """Compare conversion bytes, full records, and actual order-sensitive route witnesses."""
    from kg_microbe.utils import upa_route_review as upa

    original = args.original_json.resolve()
    candidate = args.candidate_json.resolve()
    owl_path = (args.original_owl or original.with_suffix(".owl")).resolve()
    go_path = (args.go_db or original.with_name("go.db")).resolve()
    paths = [original, candidate, owl_path, go_path, upa.POLICY_FILE]
    identities = {str(path): file_identity(path) for path in paths}
    policy = upa.load_policy(upa.POLICY_FILE.read_bytes())
    require(
        identities[str(original)]["sha256"] == policy["sources"]["upa.json"]["sha256"],
        "Original UPA JSON is not the reviewed baseline",
    )
    require(
        identities[str(owl_path)]["sha256"] == policy["sources"]["upa.owl"],
        "Original UPA OWL is not the reviewed baseline",
    )
    for suffix in ("-wal", "-shm", "-journal"):
        require(not os.path.lexists(str(go_path) + suffix), "Comparison GO database has SQLite sidecars")
    documents = {"original": upa.decode(original.read_bytes()), "candidate": upa.decode(candidate.read_bytes())}
    projected = {name: native_upa_projection(document) for name, document in documents.items()}
    with closing(sqlite3.connect(go_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        authority = upa._authority(connection, identities[str(go_path)])
        finite = {
            name: verify_upa_finite(upa, policy, document, owl_path.read_bytes(), connection, authority)
            for name, document in documents.items()
        }
        routes = {name: upa.enumerate_candidates(document, authority, policy) for name, document in documents.items()}
    for name, records in routes.items():
        write_json(evidence / f"upa-{name}-ordered-routes.json", records)
    before, after = projected["original"], projected["candidate"]
    edge_delta = multiset_delta(before["edges"], after["edges"])
    changes = {
        "node_records": mapping_delta(before["nodes"], after["nodes"]),
        "edges": edge_delta,
        "graph_other_fields": mapping_delta(before["graph_other_fields"], after["graph_other_fields"]),
        "document_other_fields": mapping_delta(before["document_other_fields"], after["document_other_fields"]),
        "route_groups": mapping_delta(
            {canonical(row["key"]): row for row in routes["original"]},
            {canonical(row["key"]): row for row in routes["candidate"]},
        ),
    }
    write_json(evidence / "upa-native-differences.json", changes)
    same_records = not any(changes[name] for name in ("node_records", "graph_other_fields", "document_other_fields"))
    same_records = same_records and not edge_delta["removed"] and not edge_delta["added"]
    result = {
        "inputs": identities,
        "bytes_identical": identities[str(original)]["sha256"] == identities[str(candidate)]["sha256"],
        "json_identical_including_all_array_order": documents["original"] == documents["candidate"],
        "keyed_native_records_and_edge_multiplicities_identical": same_records,
        "node_order_identical": before["node_order"] == after["node_order"],
        "edge_order_identical": before["edges"] == after["edges"],
        "ordered_route_witnesses_identical": routes["original"] == routes["candidate"],
        "finite_policy_gate": finite,
        "counts": {
            name: {
                "nodes": len(value["nodes"]),
                "edges": len(value["edges"]),
                "route_groups": len(routes[name]),
                "route_witnesses": sum(len(row["witnesses"]) for row in routes[name]),
            }
            for name, value in projected.items()
        },
        "changed_node_count": len(changes["node_records"]),
        "changed_route_group_count": len(changes["route_groups"]),
        "go_authority_scope": "Same preserved GO authority for both conversions; rebuilt GO remains unverified.",
        "policy_updated": False,
        "release_ready": False,
    }
    require(
        all(file_identity(path) == identities[str(path)] for path in paths), "UPA review inputs changed during read"
    )
    result["inputs_unchanged"] = True
    result["requires_binding_review"] = not result["bytes_identical"]
    result["comparison_completed"] = True
    return result


def consumed_reader(input_dir, output_dir):
    """Construct a reader using production immutable-input tracking, never a producer run."""
    from kg_microbe.transform_utils.transform import Transform

    class CandidateReader(Transform):
        """Record candidate acquisition reads without emitting or finalizing graph output."""

        REQUIRED_CONSUMED_INPUTS = ("rhea_directions", "rhea_rdf")

    return CandidateReader("rhea_candidate_review", input_dir, output_dir)


def read_rhea_pair(directory, evidence):
    """Consume both actual native files and validate their full active cohort."""
    from kg_microbe.transform_utils.rhea_mappings.native_rdf import load_native_rdf
    from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
        load_reaction_families,
        validate_family_cohort,
    )

    reader = consumed_reader(directory, evidence)
    with reader.consume_input("rhea_directions", directory / "rhea-directions.tsv") as stream:
        families = load_reaction_families(stream)
    with reader.consume_input("rhea_rdf", directory / "rhea.rdf.gz") as stream:
        native = load_native_rdf(stream.buffer, compressed=True)
        cohort = validate_family_cohort(families, native.reactions)
    return reader, families, native, cohort


def rhea_projection(families, native):
    """Validate every selected xref/participant route and retain its exact native subject."""
    from kg_microbe.transform_utils.rhea_mappings.native_graph import native_xrefs
    from kg_microbe.transform_utils.rhea_mappings.native_rdf import LABEL, RH

    families_by_id, participants, xrefs, directional_go = {}, {}, {}, {}
    route_counts = Counter()
    missing_labels = []
    for family in families:
        families_by_id[family.master] = asdict(family)
        witnesses = []
        for side in native.reactions[family.master][RH + "side"]:
            for witness in native.chemical_participants(side):
                witnesses.append(asdict(witness))
                route_counts[witness.route] += 1
        participants[family.master] = sorted(witnesses, key=canonical)
        for identifier, direction in family.members:
            values = sorted(native_xrefs(native.reactions[identifier]))
            if values:
                xrefs[identifier] = values
            if direction != "UN":
                selected = [target for target, _ in values if target.startswith("GO:")]
                if selected:
                    directional_go[identifier] = {"master": family.master, "direction": direction, "go": selected}
    for identifier, metadata in native.entity_metadata.items():
        if not metadata.get(RH + "name", metadata.get(LABEL)):
            missing_labels.append(identifier)
    return {
        "families": families_by_id,
        "participation": participants,
        "xrefs": xrefs,
        "directional_go": directional_go,
        "route_counts": dict(route_counts),
        "native_entities_without_labels": sorted(missing_labels),
    }


def precheck_legacy(policy, native):
    """Assess all six exclusions and seven directional witnesses before drafting bindings."""
    from kg_microbe.transform_utils.rhea_mappings import legacy_xrefs as legacy
    from kg_microbe.transform_utils.rhea_mappings.native_rdf import RDFS, RH

    require(policy["expected_count"] == 6 and len(policy["exclusions"]) == 6, "Known six-exclusion history is required")
    require(len(policy["preserved_directional_go_annotations"]) == 7, "Known seven-variant history is required")
    exclusions, variants = [], []
    for row in policy["exclusions"]:
        entry = {
            "subject": row["subject"],
            "required_native_assertions": row["required_native_assertions"],
            "original_object": row["original_object"],
            "normalized_object": row["normalized_object"],
        }
        errors = []
        for assertion in row["required_native_assertions"]:
            try:
                legacy._require(native, assertion["subject"], assertion["predicate"], assertion["value"])
            except ValueError as exc:
                errors.append(str(exc))
        current = native.reactions.get(row["subject"], {}).get(row["native_predicate"], ())
        for target in {row["original_object"], row["normalized_object"]}:
            if legacy._target(target, row["native_predicate"]) in current:
                errors.append(f"Excluded assertion restored on original subject: {target}")
        entry.update(passed=not errors, errors=errors)
        exclusions.append(entry)
    for row in policy["preserved_directional_go_annotations"]:
        entry = dict(row)
        try:
            legacy._require(native, row["subject"], RH + "status", RH + "Approved")
            legacy._require(native, row["subject"], RDFS + "seeAlso", legacy._target(row["object"], RDFS + "seeAlso"))
            legacy._require(native, row["master"], RH + "directionalReaction", RH + row["subject"][5:])
            legacy._require_variant_direction(native, row)
            entry["passed"] = True
        except (KeyError, ValueError) as exc:
            entry.update(passed=False, error=str(exc))
        variants.append(entry)
    return {
        "exclusions": exclusions,
        "directional_annotations": variants,
        "passed": all(row["passed"] for row in exclusions + variants),
    }


def consumed_legacy_audit(reader, policy, actual_rdf, native, evidence):
    """Run the real audit on consumed 143 RDF after successful finite semantic comparison."""
    from kg_microbe.transform_utils.rhea_mappings import legacy_xrefs as legacy

    require(precheck_legacy(policy, native)["passed"], "Finite native comparison failed; no candidate policy written")
    candidate = copy.deepcopy(policy)
    candidate["selected_snapshot"] = {
        "snapshot_id": "rhea-release-143-candidate-review-20261105",
        "rdf": {key: actual_rdf[key] for key in ("bytes", "sha256")},
    }
    # This diagnostic policy is written only after every selected native fact
    # has passed precheck. It never replaces a reviewed repository policy.
    policy_path = evidence / "PROVISIONAL-rhea-legacy-policy.json"
    write_json(policy_path, candidate)
    release = {
        "snapshot_id": candidate["selected_snapshot"]["snapshot_id"],
        "files": {"rhea.rdf.gz": candidate["selected_snapshot"]["rdf"]},
    }
    rows = legacy.load_legacy_xref_audit(reader, release, native, policy_path=policy_path)
    require(len(rows) == 6, "Consumed candidate audit did not preserve all six exclusions")
    reader.verify_consumed_inputs()
    write_json(evidence / "consumed143-legacy-audit.json", rows)
    require(candidate["historical_snapshot"] == policy["historical_snapshot"], "Historical 141 identity changed")
    require(candidate["legacy_sources"] == policy["legacy_sources"], "Historical source evidence changed")
    require(candidate["exclusions"] == policy["exclusions"], "Historical GO normalization or explanation changed")
    return {
        "passed": True,
        "rows": len(rows),
        "production_function": "load_legacy_xref_audit",
        "candidate_policy": file_identity(policy_path),
        "historical_evidence_unchanged": True,
        "historical_explanations_revalidated": False,
        "requires_selected_context_prose_review": [
            row["subject"] for row in policy["exclusions"] if "142" in row["selected_context"]
        ],
    }


def compare_rhea(args, evidence):
    """Compare complete selected native structure and run the genuine consumed-input legacy gate."""
    from kg_microbe.transform_utils.rhea_mappings import legacy_xrefs as legacy
    from kg_microbe.transform_utils.rhea_mappings.native_inputs import POLICY_PATH, read_release_policy

    old_dir, new_dir = args.original_dir.resolve(), args.candidate_dir.resolve()
    with POLICY_PATH.open() as stream:
        baseline = read_release_policy(stream)
    identities = {
        str(directory / name): file_identity(directory / name)
        for directory in (old_dir, new_dir)
        for name in ("rhea-directions.tsv", "rhea.rdf.gz")
    }
    for name, pin in baseline["files"].items():
        require(
            all(identities[str(old_dir / name)][key] == pin[key] for key in ("sha256", "bytes")),
            "Original Rhea pair is not the reviewed baseline",
        )
    old_reader, old_families, old_native, old_cohort = read_rhea_pair(old_dir, evidence / "original-reads")
    new_reader, new_families, new_native, new_cohort = read_rhea_pair(new_dir, evidence / "candidate-reads")
    with new_reader.consume_input("review_baseline_legacy_policy", legacy.POLICY_PATH) as stream:
        policy = legacy.read_legacy_policy(stream)
    before = rhea_projection(old_families, old_native)
    after = rhea_projection(new_families, new_native)
    changes = {
        field: mapping_delta(before[field], after[field])
        for field in ("families", "participation", "xrefs", "directional_go")
    }
    changes["reaction_records"] = mapping_delta(old_native.reactions, new_native.reactions)
    changes["entity_metadata"] = mapping_delta(old_native.entity_metadata, new_native.entity_metadata)
    write_json(evidence / "rhea143-native-differences.json", changes)
    assessment = precheck_legacy(policy, new_native)
    write_json(evidence / "rhea143-finite-legacy-assessment.json", assessment)
    audit = {"passed": False, "reason": "Finite semantic precheck did not pass; no candidate policy was written"}
    if assessment["passed"]:
        audit = consumed_legacy_audit(
            new_reader, policy, identities[str(new_dir / "rhea.rdf.gz")], new_native, evidence
        )
    old_reader.verify_consumed_inputs()
    new_reader.verify_consumed_inputs()
    require(
        all(file_identity(path) == value for path, value in identities.items()), "Rhea inputs changed during review"
    )
    return {
        "inputs": identities,
        "original_cohort": old_cohort,
        "candidate_cohort": new_cohort,
        "changes": {key: len(value) for key, value in changes.items()},
        "route_counts": {"original": before["route_counts"], "candidate": after["route_counts"]},
        "native_entities_without_labels": {
            "original": before["native_entities_without_labels"],
            "candidate": after["native_entities_without_labels"],
        },
        "candidate_directional_go": after["directional_go"],
        "external_labels_checked": False,
        "external_label_acceptance": "Prepared CHEBI/GO/EC label authorities are checked by the later producer.",
        "acquisition_release_verified_here": False,
        "acquisition_scope": "Caller supplies the 143 pair; official acquisition receipt remains required.",
        "legacy_semantic_precheck_passed": assessment["passed"],
        "consumed143_legacy_audit": audit,
        "consumed_inputs": {
            "original": old_reader.consumed_input_snapshots,
            "candidate": new_reader.consumed_input_snapshots,
        },
        "inputs_unchanged": True,
        "comparison_completed": True,
        "policy_updated": False,
        "release_ready": False,
        "acceptance_remaining": [
            "Review all retained native differences and missing labels",
            "Review 143 selected-context prose without rewriting 141 history",
            "Extend zero-history protection to 143 while retaining 142",
            "Update reviewed policy bindings only after evidence review",
            "Production producer/finalizer/audit and merge admission",
        ],
    }


def main(argv=None):
    """Read candidates and create explicitly non-release review evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    upa = sub.add_parser("upa", help="Compare preserved and newly converted UPA JSON")
    upa.add_argument("--original-json", required=True, type=Path)
    upa.add_argument("--candidate-json", required=True, type=Path)
    upa.add_argument("--original-owl", type=Path)
    upa.add_argument("--go-db", type=Path)
    rhea = sub.add_parser("rhea", help="Compare preserved 142 and quarantined 143 native pairs")
    rhea.add_argument("--original-dir", required=True, type=Path)
    rhea.add_argument("--candidate-dir", required=True, type=Path)
    for command in (upa, rhea):
        command.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    evidence = args.evidence_dir.resolve()
    require(
        evidence.is_relative_to(EVIDENCE_ROOT.resolve()), "Evidence must be under this rebuild's upgrades directory"
    )
    require(not evidence.exists(), "Refusing to overwrite previous review evidence")
    evidence.mkdir(parents=True)
    receipt = {
        "kind": args.kind,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "helper": file_identity(__file__),
        "production_run": False,
        "release_ready": False,
    }
    try:
        receipt["review"] = (compare_upa if args.kind == "upa" else compare_rhea)(args, evidence)
        receipt["status"] = "comparison_completed"
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(evidence / "review-receipt.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if args.kind == "rhea" and not receipt["review"]["consumed143_legacy_audit"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
