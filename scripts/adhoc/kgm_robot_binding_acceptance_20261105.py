#!/usr/bin/env python3
"""Verify current finite ROBOT policies against pristine candidates without changing raw inputs."""

import argparse
import ast
import copy
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.adhoc import kgm_robot_binding_review_20261105 as review

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/rebuild-evidence/20261105/upgrades/robot-bindings"
CANDIDATES = ROOT / "data/rebuild-evidence/20261105/upgrades/robot-conversions"
OUTPUT = BASE / "current-policy-admission.json"
EXPECTED_NODE = "http://purl.obolibrary.org/obo/CL_0009080"
EXPECTED_PROPERTY = "http://xmlns.com/foaf/0.1/depiction"
EXPECTED_TARGET = "http://purl.obolibrary.org/obo/cl/images/Small-intestine-cells.png"
EXPECTED_MISSING = [["http://www.geneontology.org/formats/oboInOwl#hasDbXref", "doi:10.1186/s13619-020-00061-5"]]


def file_binding(path):
    """Use portable identity fields for current tracked code and policy files."""
    return {key: value for key, value in review.file_identity(path).items() if key != "path"}


def preparation_methods(text):
    """Compare actual preparation code without coupling unrelated converter adapter edits."""
    wanted = {"_sanitize_obograph_synonyms", "_drop_deprecated_terms"}
    result = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.ClassDef) and node.name == "OntologiesTransform":
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name in wanted:
                    result[method.name] = hashlib.sha256(
                        ast.dump(method, include_attributes=False).encode()
                    ).hexdigest()
    review.require(set(result) == wanted, "Missing production preparation methods")
    return result


def validate_disposition(value, exception, review_sha256, source_sha256, inputs_sha256):
    """Require root's exact recorded existing omission, never a general source-completeness waiver."""
    review.require(
        exception["node"] == EXPECTED_NODE
        and exception["annotated_property"] == EXPECTED_PROPERTY
        and exception["annotated_target"] == EXPECTED_TARGET
        and exception["source_annotations_still_unserialized_in_candidate"] == EXPECTED_MISSING
        and exception["source_annotations_newly_lost"] == []
        and exception["all_added_values_source_backed"] is True,
        "Unexpected source completeness exception",
    )
    expected = {
        "issue": 1737,
        "status": "recorded_preexisting_omission",
        "review5_sha256": review_sha256,
        "review5_inputs_sha256": inputs_sha256,
        "source_owl_sha256": source_sha256,
        "exception": exception,
        "all_added_annotation_values_source_backed": True,
        "complete_source_annotation_equality": False,
        "unchanged_omission_acknowledged": True,
        "release_ready": False,
    }
    review.require(
        all(value.get(key) == required for key, required in expected.items()),
        "Missing or mismatched exact source-omission disposition",
    )


def validate_policy_delta(originals, current):
    """Constrain the approved update to complete FOODON context/provenance and its anatomical seal."""
    parent_name = "ontology_parent_dispositions.json"
    anatomy_name = "foodon_anatomical_category_dispositions.json"
    for name in current:
        if name not in {parent_name, anatomy_name}:
            review.require(current[name] == originals[name], f"Unapproved finite policy update: {name}")
    restored = copy.deepcopy(current[parent_name])
    spec = restored["sources"]["foodon"]
    prior = originals[parent_name]["sources"]["foodon"]
    review.require("conversion_review_20261105" in spec, "Missing FOODON conversion provenance")
    spec.pop("conversion_review_20261105")
    for key in ("json_context", "json_context_sha256"):
        spec[key] = prior[key]
    review.require(restored == originals[parent_name], "FOODON update changed scientific or historical fields")
    restored = copy.deepcopy(current[anatomy_name])
    restored["native_evidence"]["parent_policy_canonical_sha256"] = originals[anatomy_name]["native_evidence"][
        "parent_policy_canonical_sha256"
    ]
    review.require(restored == originals[anatomy_name], "Anatomical update changed scientific or historical fields")


def publish(path, value):
    """Publish a complete new acceptance artifact atomically without overwriting any evidence."""
    review.require(not os.path.lexists(path), f"Evidence already exists: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=".current-policy-admission-", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def current_foodon_evidence(policies, pristine, owl_path):
    """Use a private comparison view while sending pristine bytes' records to every actual FOODON gate."""
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    baseline = dict(pristine)
    baseline["graphs"] = []
    for graph in pristine["graphs"]:
        obsolete = {node["id"] for node in graph["nodes"] if OntologiesTransform._is_deprecated_node(node)}
        view = dict(graph)
        view["nodes"] = [node for node in graph["nodes"] if node["id"] not in obsolete]
        view["edges"] = [edge for edge in graph["edges"] if edge["sub"] not in obsolete and edge["obj"] not in obsolete]
        baseline["graphs"].append(view)
    return review.review_foodon(policies, baseline, pristine, owl_path)


def verify(disposition_path):
    """Verify active guards and native source evidence, keeping completeness separate from added-fact support."""
    from kg_microbe.utils import uberon_temporal_categories as temporal

    review.require(not os.path.lexists(OUTPUT), f"Evidence already exists: {OUTPUT}")
    for path in (OUTPUT.parent, *OUTPUT.parent.parents):
        review.require(not path.is_symlink(), f"Evidence path traverses symlink: {path}")
        if path == ROOT:
            break
    review_path = BASE / "review-5/binding-review.json"
    report = review.read_json(review_path)
    inputs_path = BASE / "review-5/inputs.json"
    prior_inputs = review.read_json(inputs_path)
    snapshot = BASE / "review-5/reviewed-code-and-policies"
    originals = {name: review.read_json(snapshot / "mappings" / name) for name in review.BINDINGS}
    for name in originals:
        relative = "mappings/" + name
        expected = {key: value for key, value in prior_inputs[str(ROOT / relative)].items() if key != "path"}
        review.require(file_binding(snapshot / relative) == expected, f"Reviewed policy snapshot changed: {relative}")
    policies = {name: review.read_json(ROOT / "mappings" / name) for name in review.BINDINGS}
    validate_policy_delta(originals, policies)
    identities = {"mappings/" + name: file_binding(ROOT / "mappings" / name) for name in policies}
    helper_paths = [
        "scripts/adhoc/kgm_robot_binding_review_20261105.py",
        "scripts/adhoc/kgm_robot_annotation_review_20261105.py",
        "scripts/adhoc/kgm_robot_binding_acceptance_20261105.py",
    ]
    loaders = [
        "finite_import_categories",
        "native_ro_retention",
        "ontology_parent_quarantine",
        "foodon_kernel_quarantine",
        "foodon_anatomical_categories",
        "uberon_temporal_categories",
    ]
    for relative in helper_paths + ["kg_microbe/utils/" + name + ".py" for name in loaders]:
        path = ROOT / relative
        identities[relative] = file_binding(path)
        if relative == helper_paths[-1]:
            continue
        original = snapshot / relative
        expected = {key: value for key, value in prior_inputs[str(path)].items() if key != "path"}
        review.require(file_binding(original) == expected, f"Reviewed code snapshot changed: {relative}")
        if path.stem in {"ontology_parent_quarantine", "foodon_anatomical_categories"}:

            def normalize(text):
                """Keep the permitted seal replacement separate from policy-reader behavior."""
                return re.sub(r'^POLICY_SHA256 = "[a-f0-9]{64}"$', "POLICY_SHA256 = REVIEWED", text, flags=re.MULTILINE)

            review.require(
                normalize(path.read_text()) == normalize(original.read_text()),
                f"Unapproved policy-loader logic change: {relative}",
            )
        else:
            review.require(file_binding(path) == file_binding(original), f"Reviewed checker changed: {relative}")
    converter = "kg_microbe/transform_utils/ontologies/ontologies_transform.py"
    identities[converter] = file_binding(ROOT / converter)
    expected = {key: value for key, value in prior_inputs[str(ROOT / converter)].items() if key != "path"}
    review.require(file_binding(snapshot / converter) == expected, "Reviewed converter snapshot changed")
    methods = preparation_methods((ROOT / converter).read_text())
    review.require(methods == preparation_methods((snapshot / converter).read_text()), "Production preparation changed")
    candidate_bindings, documents, sources, measured = {}, {}, {}, {}
    for name in review.CONVERTED:
        candidate_bindings[name] = {}
        for role, path in (
            ("json", CANDIDATES / (name + ".json")),
            ("source", CANDIDATES / (name + ".owl")),
            ("receipt", CANDIDATES / "receipts" / (name + ".json")),
        ):
            actual = review.file_identity(path)
            review.require(actual == prior_inputs[str(path)], f"Previously reviewed candidate changed: {path}")
            candidate_bindings[name][role] = actual
            measured[str(path)] = actual
        documents[name] = review.read_json(CANDIDATES / (name + ".json"))
        sources[name] = CANDIDATES / (name + ".owl")
    for name in ("envo", "mondo"):
        path = ROOT / "data/raw" / (name + ".json")
        measured[str(path)] = review.file_identity(path)
        review.require(measured[str(path)] == prior_inputs[str(path)], f"Canonical supplier changed: {name}")
        documents[name] = review.read_json(path)
    for policy_name in ("finite_import_category_dispositions.json", "native_ro_predicate_dispositions.json"):
        for authority in policies[policy_name]["authorities"].values():
            source = authority["source"]
            path = CANDIDATES / source["file"]
            if path.suffix != ".owl":
                path = ROOT / "data/raw" / source["file"]
            review.require(review.file_identity(path)["sha256"] == source["sha256"], f"Policy source differs: {path}")
    complete = report["annotation_completeness_assessment"]
    review.require(
        all(
            row["all_added_values_source_backed"] is True
            and row["removing_only_source_backed_additions_recovers_prepared_original"] is True
            for row in complete.values()
        ),
        "Added annotation source support is incomplete",
    )
    gaps = [(name, gap) for name, row in complete.items() for gap in row["explicit_source_completeness_exceptions"]]
    review.require(len(gaps) == 1 and gaps[0][0] == "uberon", "Unexpected source annotation completeness exceptions")
    review_binding = review.file_identity(review_path)
    inputs_binding = review.file_identity(inputs_path)
    disposition_binding = review.file_identity(disposition_path)
    validate_disposition(
        review.read_json(disposition_path),
        gaps[0][1],
        review_binding["sha256"],
        candidate_bindings["uberon"]["source"]["sha256"],
        inputs_binding["sha256"],
    )
    measured[str(review_path)] = review_binding
    measured[str(inputs_path)] = inputs_binding
    measured[str(disposition_path)] = disposition_binding
    checks = {
        "finite_imports": review.review_finite(policies, documents, documents, sources),
        "native_ro": review.review_ro(policies["native_ro_predicate_dispositions.json"], documents, documents, sources),
        "foodon": current_foodon_evidence(policies, documents["foodon"], sources["foodon"]),
    }
    review.require(
        not checks["finite_imports"]["proposed_binding_changes"]
        and not checks["native_ro"]["proposed_binding_changes"],
        "Current policies still need diagnostic rebinding",
    )
    review.require(
        all(row["unchanged_policy"]["passed"] for row in checks["finite_imports"]["authorities"].values()),
        "A current finite policy rejected the candidate",
    )
    review.require(
        all(checks["foodon"][name]["unchanged_policy"]["passed"] for name in ("parent", "kernel")),
        "A current FOODON policy rejected the candidate",
    )
    temporal_policy = temporal.load_temporal_category_policy(
        io.StringIO(json.dumps(policies["uberon_temporal_category_dispositions.json"]))
    )
    decisions = temporal.load_temporal_category_evidence(temporal_policy, io.StringIO(json.dumps(documents["uberon"])))
    checks["temporal"] = {"current_policy_passed": True, "decision_count": len(decisions)}
    review.require(
        all(file_binding(ROOT / path) == expected for path, expected in identities.items()),
        "Current code/policy changed during verification",
    )
    review.require(
        all(review.file_identity(Path(path)) == expected for path, expected in measured.items()),
        "Verification evidence changed during verification",
    )
    result = {
        "version": 1,
        "status": "passed",
        "current_policy_checks_passed": True,
        "scope": "Current finite bindings for FOODON/PATO/RO/UBERON and unchanged ENVO/MONDO suppliers",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "identities": identities,
        "review5": review_binding,
        "review5_inputs": inputs_binding,
        "candidates": candidate_bindings,
        "canonical_suppliers": {
            name: measured[str(ROOT / "data/raw" / (name + ".json"))] for name in ("envo", "mondo")
        },
        "preparation_method_sha256": methods,
        "checks": checks,
        "all_added_annotation_values_source_backed": True,
        "removing_only_source_backed_additions_recovers_prepared_original": True,
        "complete_source_annotation_equality": False,
        "source_completeness_exceptions": [gaps[0][1]],
        "source_completeness_disposition": disposition_binding,
        "release_ready": False,
        "raw_activation": False,
    }
    publish(OUTPUT, result)
    return result


def main():
    """Print the fixed scope or create one current-policy acceptance artifact after coordinated review."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "verify"), nargs="?", default="plan")
    parser.add_argument("--disposition", type=Path)
    args = parser.parse_args()
    if args.action == "plan":
        print(
            json.dumps(
                {
                    "output": str(OUTPUT),
                    "candidate_names": review.CONVERTED,
                    "requires_exact_root_disposition": True,
                    "raw_activation": False,
                }
            )
        )
        return 0
    review.require(args.disposition is not None, "Verification requires the exact root-owned #1737 disposition")
    result = verify(args.disposition.resolve())
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "status": result["status"],
                "complete_source_annotation_equality": result["complete_source_annotation_equality"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
