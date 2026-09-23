"""Audit a newly built candidate without changing the production mapping or pin."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from kg_microbe.utils import chemical_mapping_utils as runtime
from kg_microbe.utils.ingredient_identity import accepted_name_scope


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--supported", type=Path, required=True)
    parser.add_argument("--chebi-edges", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fingerprints = {str(path): sha(path) for path in (args.candidate, args.supported, args.chebi_edges)}
    with args.supported.open() as stream:
        rows = list(csv.DictReader((line for line in stream if not line.startswith("#")), delimiter="\t"))
    runtime.load_unified_mappings(args.candidate)
    names, subjects = defaultdict(set), defaultdict(set)
    for row in rows:
        names[row["subject_label"]].add(row["object_id"])
        subjects[row["subject_id"]].add(row["object_id"])
    bad_names, accepted, bad_subjects = [], [], []
    for name, targets in sorted(names.items()):
        found = runtime.find_chebi_by_name(name)
        if found in targets:
            continue
        item = {"name": name, "runtime_id": found, "release_targets": sorted(targets)}
        reviewed_scope = any(
            row["subject_label"] == name and accepted_name_scope(
                row["subject_id"], row["object_id"], found, runtime.find_chebi_by_xref(row["subject_id"]))
            for row in rows
        )
        (accepted if reviewed_scope else bad_names).append(item)
    for subject, targets in sorted(subjects.items()):
        found = runtime.find_chebi_by_xref(subject)
        if found not in targets:
            bad_subjects.append({"subject_id": subject, "runtime_id": found, "release_targets": sorted(targets)})
    expected = {
        "Polymyxin B": "NCIT:C61894", "Polymyxin B1": "CHEBI:8309",
        "Rifamycin": "CHEBI:26580",
        "Rifamycin SV": "CHEBI:29673", "Xanthine": "CHEBI:15318", "9H-xanthine": "CHEBI:17712",
        "Sorbitan Monooleate": "kgmicrobe.ingredient:sorbitan_monooleate", "Tween 80": "CHEBI:53426",
    }
    routes = {name: runtime.find_chebi_by_name(name) for name in expected}
    assert routes == expected, routes
    routes["Polymyxin B sulfate"] = runtime.find_chebi_by_name("Polymyxin B sulfate")
    assert routes["Polymyxin B sulfate"] in {"CHEBI:8310", "NCIT:C61895"}
    cas_routes = {"1404-26-8": "NCIT:C61894", "4135-11-9": "CHEBI:8309", "6998-60-3": "CHEBI:29673", "69-89-6": "CHEBI:17712"}
    annotations = {}
    for cas, target in cas_routes.items():
        assert runtime.find_chebi_by_xref("cas:" + cas) == target
        annotations[target] = runtime.get_node_enrichment(target)["xref"].split("|")
        assert "cas:" + cas in annotations[target]
    local = "kgmicrobe.ingredient:sorbitan_monooleate"
    assert not any(token.lower().startswith("cas:") for token in runtime.get_node_enrichment(local)["xref"].split("|"))
    assert runtime.find_chebi_by_xref("MIM:Xanthine") == "CHEBI:17712"
    assert runtime.find_chebi_by_xref("MIM:Sorbitan_Monooleate") == local
    assert "CHEBI:17712" not in runtime.get_xrefs("CHEBI:15318")
    sulfate_xrefs = set(runtime.get_node_enrichment(routes["Polymyxin B sulfate"])["xref"].split("|"))
    assert not sulfate_xrefs & {"cas:1404-26-8", "cas:4135-11-9", "NCIT:C61894", "CHEBI:8309"}
    with args.chebi_edges.open() as stream:
        parent_edges = [row for row in csv.DictReader(stream, delimiter="\t")
                        if row["subject"] == "CHEBI:17712" and row["object"] == "CHEBI:15318"]
    assert any(row["predicate"] in {"biolink:subclass_of", "rdfs:subClassOf"} for row in parent_edges)
    assert not bad_subjects, bad_subjects
    assert len(accepted) == 1 and accepted[0]["name"] == "Xanthine", accepted
    assert all(sha(Path(path)) == value for path, value in fingerprints.items())
    report = {
        "scope": "Actual runtime audit of the full conservative candidate and newly reviewed local MIM bundle; no production promotion.",
        "input_sha256": fingerprints, "supported_assertions": len(rows), "subject_groups": len(subjects),
        "name_groups": len(names), "unresolved_name_disagreements": len(bad_names),
        "accepted_scope_distinctions": accepted, "remaining_name_disagreements": bad_names,
        "subject_disagreements": bad_subjects, "verified_routes": routes,
        "verified_cas_node_annotations": annotations, "native_xanthine_parent_edges": parent_edges,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key in {
        "supported_assertions", "subject_groups", "name_groups", "unresolved_name_disagreements",
        "accepted_scope_distinctions", "subject_disagreements", "verified_routes"}}, indent=2))


if __name__ == "__main__":
    main()
