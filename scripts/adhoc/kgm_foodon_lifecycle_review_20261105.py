#!/usr/bin/env python3
"""Compare actual FOODON live closures and retain source-backed retirement evidence (#1745)."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from kg_microbe.utils import foodon_anatomical_categories as anatomy
from kg_microbe.utils import foodon_kernel_quarantine as native
from kg_microbe.utils.foodon_classification import foodon_categories, organism_classes
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/rebuild-evidence/20261105/upgrades/foodon-lifecycle"


def identity(path):
    """Fingerprint complete source bytes without modifying the source."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def require(condition, message):
    """Refuse incomplete or changed evidence even when Python assertions are disabled."""
    if not condition:
        raise ValueError(message)


def write_new_json(path, value):
    """Retain a new evidence artifact without replacing existing bytes."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def review(label):
    """Compare fixed actual inputs and write only a fresh labeled evidence directory."""
    w = ROOT
    e = BASE
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", label) is None:
        raise ValueError("Use a unique label of 1-80 letters, digits, underscores, or hyphens")
    if e.resolve() != e:
        raise ValueError("Evidence directory must not traverse a symbolic link")
    out = e / label
    if os.path.lexists(out):
        raise FileExistsError(out)
    old = w.parent / "kg-microbe/data/raw/foodon.json"
    candidate = w / "data/rebuild-evidence/20261105/upgrades/robot-conversions/foodon.json"
    owl = w / "data/rebuild-evidence/20261105/upgrades/robot-conversions/foodon.owl"
    codepaths = [
        "kg_microbe/utils/foodon_kernel_quarantine.py",
        "kg_microbe/utils/foodon_classification.py",
        "kg_microbe/utils/foodon_kernel_producer.py",
        "kg_microbe/utils/source_category_authority.py",
        "kg_microbe/utils/ontology_metadata.py",
        "kg_microbe/utils/graph_canonicalization.py",
        "kg_microbe/utils/foodon_anatomical_categories.py",
        "kg_microbe/utils/ontology_parent_quarantine.py",
        "kg_microbe/transform_utils/ontologies/ontologies_transform.py",
        "tests/test_foodon_cold_conversion.py",
        "mappings/foodon_kernel_quarantine.json",
        "mappings/foodon_anatomical_category_dispositions.json",
        "mappings/ontology_parent_dispositions.json",
        "mappings/foodon_model_dispositions.tsv",
    ]
    paths = [
        old,
        candidate,
        owl,
        w / "data/raw/foodon.json",
        w / "data/raw/foodon.owl",
        Path(__file__),
        e / "before-code.json",
    ] + [w / p for p in codepaths]
    inputs = {str(p): identity(p) for p in paths}
    require(
        inputs[str(candidate)]["sha256"] == inputs[str(w / "data/raw/foodon.json")]["sha256"],
        "Active FOODON JSON differs from reviewed conversion",
    )
    require(
        inputs[str(owl)]["sha256"] == inputs[str(w / "data/raw/foodon.owl")]["sha256"],
        "Active FOODON OWL differs from reviewed source",
    )
    with native.POLICY_FILE.open() as stream:
        policy = native.load_policy(stream)
    original = json.loads(old.read_text())["graphs"]
    pristine = json.loads(candidate.read_text())["graphs"]
    with owl.open("rb") as stream:
        tree = native._owl_tree(stream)
    live = native._live_hierarchy(pristine, tree)
    with owl.open("rb") as stream:
        view, evidence = native.reviewed_hierarchy(pristine, policy, native_owl=stream)
    with owl.open("rb") as stream:
        oldview, oldevidence = native.reviewed_hierarchy(original, policy, native_owl=stream)
    retired = {native.compact(n["id"]): n for graph in pristine for n in graph["nodes"] if obograph_is_deprecated(n)}
    incident = [
        edge
        for graph in pristine
        for edge in graph["edges"]
        if native.compact(edge["sub"]) in retired or native.compact(edge["obj"]) in retired
    ]
    source_retirements = {}
    source_parents = {}
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        identifier = native.compact(element.get(native._RDF + "about", ""))
        if identifier in retired and element.find(native._OWL + "deprecated") is not None:
            source_retirements.setdefault(identifier, []).append(native._xml_record(element))
        if element.tag == native._OWL + "Class":
            for parent in element.findall(native._RDFS + "subClassOf"):
                target = parent.get(native._RDF + "resource")
                if target:
                    source_parents.setdefault((identifier, "is_a", native.compact(target)), []).append(
                        native._xml_record(parent)
                    )
    require(set(retired) == set(source_retirements), "Retirement declaration lacks source evidence")
    require(all(native._triple(edge) in source_parents for edge in incident), "Retired incidence lacks source evidence")
    oldcategories = foodon_categories(oldview, anatomical_categories={})
    newcategories = foodon_categories(view, anatomical_categories={})
    anatomy_decisions = anatomy.categories_for(pristine)
    oldwithanatomy = foodon_categories(oldview, anatomical_categories=anatomy_decisions)
    newwithanatomy = foodon_categories(view, anatomical_categories=anatomy_decisions)
    oldorganism = organism_classes(oldview)
    neworganism = organism_classes(view)
    changed = organism_classes(live) - neworganism
    checks = {
        "native_category_maps_equal": oldcategories == newcategories,
        "category_maps_equal_with_previously_reviewed_current_anatomy_overlay": oldwithanatomy == newwithanatomy,
        "organism_closures_equal": oldorganism == neworganism,
        "kernel_delta_exact_frozen_22": changed == evidence.cohort and not neworganism - organism_classes(live),
        "finite_complete_json_evidence_unchanged": evidence.json_records == oldevidence.json_records,
        "finite_complete_owl_evidence_unchanged": evidence.owl_records == oldevidence.owl_records,
        "all_retired_declarations_source_backed": set(retired) == set(source_retirements),
        "all_removed_incidence_source_backed": all(native._triple(edge) in source_parents for edge in incident),
    }
    require(all(checks.values()), f"Closure comparison failed: {checks}")
    before = json.loads((e / "before-code.json").read_text())
    checks["strict_classifier_producer_transform_unchanged"] = all(
        identity(w / p)["sha256"] == d["sha256"]
        for p, d in before.items()
        if p != "kg_microbe/utils/foodon_kernel_quarantine.py"
    )
    require(
        checks["strict_classifier_producer_transform_unchanged"], "Unexpected classifier, producer, or transform change"
    )
    require(inputs == {str(p): identity(p) for p in paths}, "Input/code changed during review")
    out.mkdir()
    retirement = {
        "nodes": [
            {"id": key, "native_json_record": retired[key], "native_owl_records": source_retirements[key]}
            for key in sorted(retired)
        ],
        "incident_edges": [
            {"native_json_record": edge, "native_owl_named_parent_records": source_parents[native._triple(edge)]}
            for edge in incident
        ],
    }
    write_new_json(out / "source-backed-retirements.json", retirement)
    result = {
        "schema_version": 1,
        "issue": 1745,
        "status": "passed",
        "scope": (
            "Read-only current implementation lifecycle and actual source comparison, "
            "not source completion or release admission"
        ),
        "utc": datetime.now(timezone.utc).isoformat(),
        "inputs_and_code": inputs,
        "checks": checks,
        "counts": {
            "retired_nodes": len(retired),
            "retired_node_types": dict(Counter(n.get("type", "untyped") for n in retired.values())),
            "retired_incident_edges": len(incident),
            "kernel_category_cohort": len(evidence.cohort),
            "live_category_mapping": len(newcategories),
            "anatomical_decisions": len(anatomy_decisions),
            "retained_organism_closure": len(neworganism),
        },
        "closure_identity": {
            "old_organism": native.digest(sorted(oldorganism)),
            "candidate_organism": native.digest(sorted(neworganism)),
            "old_categories": native.digest(oldcategories),
            "candidate_categories": native.digest(newcategories),
            "old_categories_with_anatomy": native.digest(oldwithanatomy),
            "candidate_categories_with_anatomy": native.digest(newwithanatomy),
        },
        "kernel_delta": sorted(changed),
        "retirement_evidence": identity(out / "source-backed-retirements.json"),
        "source_bytes_preserved": True,
    }
    write_new_json(out / "comparison.json", result)
    return {
        "path": str(out / "comparison.json"),
        "status": result["status"],
        "counts": result["counts"],
        "checks": checks,
    }


def main():
    """Require a unique evidence label; all native source paths remain read-only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="Unique output directory name beneath the fixed FOODON lifecycle evidence root")
    args = parser.parse_args()
    print(json.dumps(review(args.label), indent=2))


if __name__ == "__main__":
    main()
