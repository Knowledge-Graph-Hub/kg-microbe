#!/usr/bin/env python3
"""
Review non-UPA ROBOT conversion bindings for the approved 2026-11-05 rebuild.

Inputs: preserved raw JSON, unchanged source OWL, per-conversion receipts, and
current finite scientific policies. Outputs: a new evidence directory containing
complete annotation proofs, exact finite binding differences, and production
reader results. No policy, raw input, graph, or completion receipt is modified.
Diagnostic copies change only measured declaration/context hashes; they never
admit a release or change scientific categories, cohorts, paths, or exclusions.
"""

import argparse
import copy
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "data/rebuild-evidence/20261105/upgrades"
CONVERTED = ("foodon", "pato", "ro", "uberon")
OWL = "{http://www.w3.org/2002/07/owl#}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
OBO = "http://purl.obolibrary.org/obo/"
BINDINGS = {
    "finite_import_category_dispositions.json": {
        "loader": "finite_import_categories.load_import_category_evidence",
        "sources": ["foodon.json", "pato.json", "uberon.json"],
        "scope": "75 FOODON, two PCO/PATO, three COB/UBERON records",
        "fields": ["records.*.native_node_sha256", "records.*.ancestor_paths", "authorities.*.decisions_sha256"],
    },
    "native_ro_predicate_dispositions.json": {
        "loader": "native_ro_retention.NativeROPredicateRetention",
        "sources": ["ro.json", "pato.json", "uberon.json", "envo.json", "mondo.json"],
        "scope": "14 properties, 516 retained supplier assertions, eight unchanged controls",
        "fields": ["relations.*.native_node_sha256", "authorities.*.selected_sha256", "REVIEWED_POLICY_SHA256"],
    },
    "uberon_temporal_category_dispositions.json": {
        "loader": "uberon_temporal_categories.load_temporal_category_evidence",
        "sources": ["uberon.json"],
        "scope": "58 finite classes and complete live life-stage inventory",
        "fields": ["native_closure_sha256", "records.*.required_paths", "review_inventory_sha256"],
    },
    "ontology_parent_dispositions.json": {
        "loader": "ontology_parent_quarantine.json_context / owl_context",
        "sources": ["foodon.json", "envo.json"],
        "scope": "13 FOODON plus one ENVO quarantined parent; 396 FOODON context IDs",
        "fields": [
            "sources.*.json_context",
            "sources.*.json_context_sha256",
            "sources.*.owl_context_sha256",
            "POLICY_SHA256",
        ],
    },
    "foodon_kernel_quarantine.json": {
        "loader": "foodon_kernel_quarantine.json_evidence / owl_evidence",
        "sources": ["foodon.json"],
        "scope": "22 kernel classes, controls, incident edges, logical definitions, and named-parent closure",
        "fields": ["json_evidence", "json_evidence_sha256", "JSON_EVIDENCE_SHA256", "POLICY_SHA256"],
    },
    "foodon_anatomical_category_dispositions.json": {
        "loader": "foodon_anatomical_categories.load_policy / categories_for",
        "sources": ["foodon.json"],
        "scope": "22 pods and two whole tails, bound transitively to the parent policy",
        "fields": ["native_evidence.parent_policy_canonical_sha256", "POLICY_SHA256"],
    },
}


def require(condition, message):
    """Reject missing prerequisites or an unsupported scientific comparison."""
    if not condition:
        raise ValueError(message)


def canonical(value):
    """Retain array occurrences and order while normalizing dictionary key order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def file_identity(path):
    """Read a full artifact digest using bounded memory."""
    path = Path(path).resolve()
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": checksum.hexdigest()}


def unique_object(pairs):
    """Reject ambiguous JSON keys in policies, receipts, and native records."""
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    """Read one bounded ontology authority or evidence document."""
    with Path(path).open() as stream:
        return json.load(stream, object_pairs_hook=unique_object)


def save(path, value):
    """Preserve earlier evidence by creating each output exclusively."""
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def graph(document):
    """Require one graph and unique native declarations before finite comparisons."""
    graphs = document.get("graphs")
    require(isinstance(graphs, list) and len(graphs) == 1, "Expected one native authority graph")
    result = graphs[0]
    ids = [node["id"] for node in result["nodes"]]
    require(len(set(ids)) == len(ids), "Duplicate native node IDs")
    return result


def production_check(function, *args, **kwargs):
    """Report an expected policy rejection without treating it as release acceptance."""
    try:
        result = function(*args, **kwargs)
        return {"passed": True, "records": len(result) if isinstance(result, dict) else None}
    except ValueError as error:
        return {"passed": False, "error": str(error)}


def review_check(function, *args):
    """Retain an independent failed comparison without discarding other finite evidence."""
    try:
        return {"passed": True, "evidence": function(*args)}
    except ValueError as error:
        return {"passed": False, "error": str(error)}


def annotation_completeness_assessment(original, prepared, proof):
    """Explain source-backed additions and unchanged source omissions without waiving complete-source equality."""
    projected = copy.deepcopy(prepared)
    exceptions = []
    all_added_facts_supported = True
    for row in proof["complete_added_annotation_evidence"]:
        before = original["graphs"][row["graph_position"]]["nodes"][row["node_position"]]
        after = projected["graphs"][row["graph_position"]]["nodes"][row["node_position"]]
        for part in row["property_path"]:
            before, after = before[part], after[part]
        source = {tuple(value) for value in row["source_owl_annotations"]}
        carried = {tuple(value) for value in row["existing_serialized_annotation_facts"]}
        added = {(value["pred"], value["val"]) for value in row["candidate_annotation"]["basicPropertyValues"]}
        supported = bool(added) and added <= source and carried <= source
        supported = supported and "meta" not in before and {k: v for k, v in after.items() if k != "meta"} == before
        supported = supported and after.get("meta") == row["candidate_annotation"]
        all_added_facts_supported = all_added_facts_supported and supported
        if supported:
            after.pop("meta")
        missing = source - (carried | added)
        if missing or not supported:
            exceptions.append(
                {
                    "node": row["node"],
                    "property_path": row["property_path"],
                    "annotated_property": row["annotated_property"],
                    "annotated_target": row["annotated_target"],
                    "all_added_values_source_backed": supported,
                    "source_annotations_unserialized_in_original": sorted(source - carried),
                    "source_annotations_still_unserialized_in_candidate": sorted(missing),
                    "source_annotations_newly_lost": sorted(missing - (source - carried)),
                    "source_owl_annotation_details": row["source_owl_annotation_details"],
                }
            )
    return {
        "all_added_values_source_backed": all_added_facts_supported and projected == original,
        "removing_only_source_backed_additions_recovers_prepared_original": projected == original,
        "complete_source_annotation_equality": proof["only_added_annotation_metadata"],
        "explicit_source_completeness_exceptions": exceptions,
        "exceptions_approved": False,
        "policy_changes_applied": False,
        "release_ready": False,
    }


def owl_index(path, identifiers):
    """Stream named declarations, direct named parents, and exact existential source restrictions."""
    from lxml import etree

    records = defaultdict(
        lambda: {"types": set(), "labels": set(), "parents": set(), "restrictions": set(), "deprecated": set()}
    )
    restriction_nodes, references = {}, defaultdict(set)
    context = etree.iterparse(str(path), events=("end",), resolve_entities=False, no_network=True, load_dtd=False)
    for _, element in context:
        parent = element.getparent()
        if parent is None or parent.getparent() is not None:
            continue
        for restriction in element.iter(OWL + "Restriction"):
            node_id = restriction.get(RDF + "nodeID")
            prop, target = restriction.find(OWL + "onProperty"), restriction.find(OWL + "someValuesFrom")
            if node_id and prop is not None and target is not None:
                value = prop.get(RDF + "resource"), target.get(RDF + "resource")
                if all(value):
                    require(node_id not in restriction_nodes, f"Duplicate named OWL restriction: {node_id}")
                    restriction_nodes[node_id] = value
        for declaration in element.iter():
            identifier = declaration.get(RDF + "about")
            if identifier not in identifiers:
                continue
            row = records[identifier]
            row["types"].add(declaration.tag)
            row["labels"].update(label.text or "" for label in declaration.findall(RDFS + "label"))
            row["deprecated"].update(value.text or "" for value in declaration.findall(OWL + "deprecated"))
            row["parents"].update(
                value for node in declaration.findall(RDFS + "subClassOf") if (value := node.get(RDF + "resource"))
            )
            references[identifier].update(
                value for node in declaration.findall(RDFS + "subClassOf") if (value := node.get(RDF + "nodeID"))
            )
            for restriction in declaration.iter(OWL + "Restriction"):
                prop, target = restriction.find(OWL + "onProperty"), restriction.find(OWL + "someValuesFrom")
                if prop is not None and target is not None:
                    relation, value = prop.get(RDF + "resource"), target.get(RDF + "resource")
                    if relation and value:
                        row["restrictions"].add((relation, value))
        element.clear()
        while element.getprevious() is not None:
            del parent[0]
    for identifier, values in references.items():
        records[identifier]["restrictions"].update(
            restriction_nodes[value] for value in values if value in restriction_nodes
        )
    return records


def production_comparison_copy(name, candidate, source, output):
    """Apply unchanged production preparation only to a fresh independent review copy."""
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    pristine = graph(candidate)
    obsolete = {node["id"] for node in pristine["nodes"] if OntologiesTransform._is_deprecated_node(node)}
    witnesses = owl_index(source, obsolete)
    require(
        all(any(value.lower() in {"true", "1"} for value in witnesses[key]["deprecated"]) for key in obsolete),
        f"Candidate obsolete status lacks direct source OWL support: {name}",
    )
    path = output / "prepared" / (name + ".json")
    path.parent.mkdir(exist_ok=True)
    save(path, candidate)
    transform = object.__new__(OntologiesTransform)
    transform._sanitize_obograph_synonyms(path)
    sanitized = read_json(path)
    # A sanitizer change is a separate material difference and needs separate review.
    require(sanitized == candidate, f"Unexpected malformed synonym preparation difference: {name}")
    transform._drop_deprecated_terms(path)
    prepared = read_json(path)
    expected_graph = dict(pristine)
    expected_graph["nodes"] = [node for node in pristine["nodes"] if node["id"] not in obsolete]
    expected_graph["edges"] = [
        edge for edge in pristine["edges"] if edge["sub"] not in obsolete and edge["obj"] not in obsolete
    ]
    expected = {**candidate, "graphs": [expected_graph]}
    require(prepared == expected, f"Production preparation differs from exact deprecated incidence removal: {name}")
    proof = {
        "production_methods": ["_sanitize_obograph_synonyms", "_drop_deprecated_terms"],
        "prepared_file": file_identity(path),
        "pristine_authorities_validated_before_preparation": True,
        "comparison_copy_only": True,
        "malformed_synonyms_changed": False,
        "removed_nodes": [node for node in pristine["nodes"] if node["id"] in obsolete],
        "removed_edges": [edge for edge in pristine["edges"] if edge["sub"] in obsolete or edge["obj"] in obsolete],
        "source_owl_deprecation_witnesses": {key: sorted(witnesses[key]["deprecated"]) for key in sorted(obsolete)},
    }
    save(output / (name + "-preparation-proof.json"), proof)
    return prepared


def verify_finite_owl(path, policy, filename, decisions):
    """Compare every finite class label and complete supporting named-parent set with unchanged OWL."""
    selected = {identifier: row for identifier, row in policy["records"].items() if row["authority_file"] == filename}
    pairs = {(subject, target) for decision in decisions.values() for subject, _, target in decision.supporting_axioms}
    identifiers = {value for pair in pairs for value in pair} | {row["native_iri"] for row in selected.values()}
    native = owl_index(path, identifiers)
    for identifier, row in selected.items():
        source = native[row["native_iri"]]
        require(OWL + "Class" in source["types"], f"Finite OWL CLASS declaration missing: {identifier}")
        require(row["native_label"] in source["labels"], f"Finite OWL label differs: {identifier}")
    actual = {(subject, target) for subject in identifiers for target in native[subject]["parents"]}
    require(actual == pairs, f"Finite OWL named-parent evidence differs: {filename}: {sorted(actual ^ pairs)}")
    return {"class_records": len(selected), "complete_named_parent_axioms": len(pairs), "axioms": sorted(pairs)}


def selected_parent_context(document, spec):
    """Select full native parent evidence without replacing its reviewed digest."""
    from kg_microbe.utils import ontology_parent_quarantine as parent

    graphs = document["graphs"]
    selected, cohort = set(spec["context_ids"]), set(spec["incident_ids"])
    return {
        "graphs": [{key: value[key] for key in ("id", "meta") if key in value} for value in graphs],
        "nodes": sorted(
            (node for value in graphs for node in value["nodes"] if parent._identifier(node["id"]) in selected),
            key=parent.canonical,
        ),
        "edges": sorted(
            (
                edge
                for value in graphs
                for edge in value["edges"]
                if parent._native_key(edge)[0] in selected | cohort or parent._native_key(edge)[2] in cohort
            ),
            key=parent.canonical,
        ),
        "logical_definitions": sorted(
            (
                axiom
                for value in graphs
                for axiom in value.get("logicalDefinitionAxioms", [])
                if parent._identifier(axiom["definedClassId"]) in selected
            ),
            key=parent.canonical,
        ),
    }


def selected_kernel_context(document, policy):
    """Select complete kernel declarations and incidence for an explicit new-evidence comparison."""
    from kg_microbe.utils import foodon_kernel_quarantine as kernel

    cohort = set(policy["cohort"])
    selected = cohort | set(policy["controls"])
    return {
        "nodes": sorted(
            (node for value in document["graphs"] for node in value["nodes"] if kernel.compact(node["id"]) in selected),
            key=kernel.canonical,
        ),
        "incident_edges": sorted(
            (
                edge
                for value in document["graphs"]
                for edge in value["edges"]
                if kernel._triple(edge)[0] in cohort or kernel._triple(edge)[2] in cohort
            ),
            key=kernel.canonical,
        ),
        "logical_definition_axioms": sorted(
            (
                axiom
                for value in document["graphs"]
                for axiom in value.get("logicalDefinitionAxioms", [])
                if kernel.compact(axiom["definedClassId"]) in cohort
            ),
            key=kernel.canonical,
        ),
    }


def review_finite(policies, documents, original_documents, sources):
    """Use production ancestry/decision gates and independently verify complete OWL named-parent witnesses."""
    from kg_microbe.utils import finite_import_categories as finite

    policy = finite.load_import_category_policy(
        io.StringIO(json.dumps(policies["finite_import_category_dispositions.json"]))
    )
    results, updates = {}, []
    for filename in sorted(policy["authorities"]):
        name = filename[:-5]
        baseline = finite.load_import_category_evidence(
            policy, filename, io.StringIO(json.dumps(original_documents[name]))
        )
        candidate = documents[name]
        unchanged = production_check(
            finite.load_import_category_evidence, policy, filename, io.StringIO(json.dumps(candidate))
        )
        diagnostic = copy.deepcopy(policy)
        nodes = {node["id"]: node for node in graph(candidate)["nodes"]}
        for identifier, record in diagnostic["records"].items():
            if record["authority_file"] != filename:
                continue
            measured = finite._digest(nodes[record["native_iri"]])
            if measured != record["native_node_sha256"]:
                updates.append(
                    {
                        "field": ["records", identifier, "native_node_sha256"],
                        "before": record["native_node_sha256"],
                        "after": measured,
                    }
                )
                record["native_node_sha256"] = measured
        decisions = finite.load_import_category_evidence(diagnostic, filename, io.StringIO(json.dumps(candidate)))
        require(decisions == baseline, f"Finite scientific decisions changed: {filename}")
        results[filename] = {
            "unchanged_policy": unchanged,
            "diagnostic_declaration_hash_rebind_only": True,
            "decisions_unchanged": True,
            "decisions": {key: asdict(value) for key, value in decisions.items()},
            "owl_witnesses": verify_finite_owl(sources[name], policy, filename, decisions),
        }
    return {"authorities": results, "proposed_binding_changes": updates}


def review_ro(policy, documents, original_documents, sources):
    """Verify all 14 property declarations and all 524 supplier assertions, retaining exact new records."""
    from kg_microbe.utils import native_ro_retention as native
    from kg_microbe.utils.graph_canonicalization import compact_identifier
    from kg_microbe.utils.ontology_metadata import obograph_is_deprecated
    from kg_microbe.utils.release_binding import canonical_digest, graph_release

    native.load_policy(io.StringIO(json.dumps(policy)))
    results, updates = {}, []
    for filename, authority in policy["authorities"].items():
        name = filename[:-5]
        old_graph, new_graph = graph(original_documents[name]), graph(documents[name])
        require(
            native.selected_content_sha256(name, old_graph) == authority["selected_sha256"],
            f"Original RO content differs: {name}",
        )
        require(
            new_graph["id"] == authority["graph_id"] and graph_release(new_graph) == authority["release"],
            f"RO release changed: {name}",
        )
        nodes = {node["id"]: node for node in new_graph["nodes"]}
        if name == "ro":
            owl = owl_index(sources[name], {OBO + key.replace(":", "_", 1) for key in policy["relations"]})
            declarations = {}
            for identifier, contract in policy["relations"].items():
                iri = OBO + identifier.replace(":", "_", 1)
                node = nodes[iri]
                require(
                    node.get("type") == "PROPERTY"
                    and node.get("propertyType") == "OBJECT"
                    and not obograph_is_deprecated(node),
                    f"RO property meaning changed: {identifier}",
                )
                require(node.get("lbl") == contract["label"], f"RO property label changed: {identifier}")
                require(
                    OWL + "ObjectProperty" in owl[iri]["types"] and contract["label"] in owl[iri]["labels"],
                    f"RO OWL declaration changed: {identifier}",
                )
                measured = canonical_digest(node)
                if measured != contract["native_node_sha256"]:
                    updates.append(
                        {
                            "field": ["relations", identifier, "native_node_sha256"],
                            "before": contract["native_node_sha256"],
                            "after": measured,
                            "complete_candidate_node": node,
                        }
                    )
                declarations[identifier] = node
            require(
                not any(compact_identifier(edge["pred"]) in policy["relations"] for edge in new_graph["edges"]),
                "RO gained supplier assertions",
            )
            results[name] = {"property_declarations": declarations, "native_owl_declarations_verified": True}
        else:
            edges = [edge for edge in new_graph["edges"] if compact_identifier(edge["pred"]) in policy["relations"]]
            observed = Counter(tuple(compact_identifier(edge[key]) for key in ("sub", "pred", "obj")) for edge in edges)
            expected = Counter(
                (row["subject"], row["relation"], row["object"])
                for row in policy["records"] + policy["unchanged_records"]
                if row["ontology"] == name
            )
            require(observed == expected, f"RO supplier assertion cohort changed: {name}")
            for edge in edges:
                require(
                    all(
                        nodes[edge[key]].get("type") == "CLASS" and not obograph_is_deprecated(nodes[edge[key]])
                        for key in ("sub", "obj")
                    ),
                    f"RO endpoint declaration changed: {name}",
                )
            owl_verified = None
            if name in sources:
                source = owl_index(sources[name], {edge["sub"] for edge in edges})
                missing = [
                    edge for edge in edges if (edge["pred"], edge["obj"]) not in source[edge["sub"]]["restrictions"]
                ]
                require(not missing, f"RO supplier lacks exact source OWL restriction witnesses: {name}: {missing[:3]}")
                owl_verified = len(edges)
            results[name] = {
                "assertion_occurrences": len(edges),
                "exact_policy_cohort": True,
                "source_owl_restrictions_verified": owl_verified,
            }
        measured = native.selected_content_sha256(name, new_graph)
        if measured != authority["selected_sha256"]:
            require(name == "ro", f"RO supplier full assertion records changed: {name}")
            updates.append(
                {
                    "field": ["authorities", filename, "selected_sha256"],
                    "before": authority["selected_sha256"],
                    "after": measured,
                }
            )
    return {
        "authorities": results,
        "proposed_binding_changes": updates,
        "historical_reviewed_model_preserved": policy["reviewed_model"],
    }


def review_foodon(policies, old, candidate, owl_path):
    """Check parent/kernel cohorts against complete source OWL and preserve all scientific decisions."""
    from kg_microbe.utils import foodon_anatomical_categories as anatomical
    from kg_microbe.utils import foodon_kernel_quarantine as kernel
    from kg_microbe.utils import ontology_parent_quarantine as parent

    parent_policy = parent.load_policy(io.StringIO(json.dumps(policies["ontology_parent_dispositions.json"])))
    spec = parent_policy["sources"]["foodon"]
    before = parent.json_context(old, spec)
    require(before == selected_parent_context(old, spec), "Independent parent selector disagrees with production")
    with owl_path.open("rb") as stream:
        owl = parent.owl_context(stream, spec)
    new_context = selected_parent_context(candidate, spec)
    diagnostic = copy.deepcopy(spec)
    diagnostic["json_context_sha256"] = parent.digest(new_context)
    parent.json_context(candidate, diagnostic)
    kernel_policy = kernel.load_policy(io.StringIO(json.dumps(policies["foodon_kernel_quarantine.json"])))
    before_kernel = kernel.json_evidence(old["graphs"], kernel_policy)
    require(
        before_kernel == selected_kernel_context(old, kernel_policy),
        "Independent kernel selector disagrees with production",
    )
    with owl_path.open("rb") as stream:
        kernel_owl = kernel.owl_evidence(stream, kernel_policy)
    after_kernel = selected_kernel_context(candidate, kernel_policy)
    require(after_kernel["incident_edges"] == before_kernel["incident_edges"], "Kernel incidence changed")
    require(
        after_kernel["logical_definition_axioms"] == before_kernel["logical_definition_axioms"],
        "Kernel logical definitions changed",
    )
    old_graph, new_graph = graph(old), graph(candidate)
    deprecated = {node["id"] for node in new_graph["nodes"] if node.get("meta", {}).get("deprecated") is True}
    require(
        old_graph["edges"]
        == [edge for edge in new_graph["edges"] if edge["sub"] not in deprecated and edge["obj"] not in deprecated],
        "Kernel live named-parent/descendant graph changed",
    )
    anatomical_policy = anatomical.load_policy(
        io.StringIO(json.dumps(policies["foodon_anatomical_category_dispositions.json"]))
    )
    diagnostic_parent = copy.deepcopy(parent_policy)
    diagnostic_parent["sources"]["foodon"] = diagnostic
    categories = anatomical.categories_for(
        candidate["graphs"], policy=anatomical_policy, parent_policy=diagnostic_parent
    )
    require(categories == anatomical.categories_for(old["graphs"]), "Anatomical category decisions changed")
    return {
        "parent": {
            "unchanged_policy": production_check(parent.json_context, candidate, spec),
            "complete_candidate_context": new_context,
            "candidate_context_sha256": parent.digest(new_context),
            "owl_context_sha256": parent.digest(owl),
            "diagnostic_context_rebind_preserves_all_other_checks": True,
        },
        "kernel": {
            "unchanged_policy": production_check(kernel.json_evidence, candidate["graphs"], kernel_policy),
            "complete_candidate_evidence": after_kernel,
            "candidate_evidence_sha256": kernel.digest(after_kernel),
            "owl_evidence_sha256": kernel.digest(kernel_owl),
            "incidence_logical_definitions_and_hierarchy_unchanged": True,
        },
        "anatomical": {
            "categories": categories,
            "scientific_decisions_unchanged": True,
            "transitive_parent_policy_binding_requires_update_if_parent_changes": new_context != before,
        },
    }


def compare(original_raw, candidates, output):
    """Compare completed finite authority conversions and retain all diagnostic evidence without activation."""
    from kg_microbe.utils import uberon_temporal_categories as temporal
    from scripts.adhoc.kgm_robot_annotation_review_20261105 import assess_added_annotation_metadata

    require(output.resolve().is_relative_to(EVIDENCE_ROOT), "Review evidence must stay in the owned evidence tree")
    for path in (output, *output.parents):
        if path == ROOT:
            break
        require(not path.is_symlink(), f"Review evidence traverses a symlink: {path}")
    require(not os.path.lexists(output), f"Review evidence already exists: {output}")
    policies = {name: read_json(ROOT / "mappings" / name) for name in BINDINGS}
    identities = {str(ROOT / "mappings" / name): file_identity(ROOT / "mappings" / name) for name in policies}
    code_paths = [
        Path(__file__),
        ROOT / "scripts/adhoc/kgm_robot_annotation_review_20261105.py",
        ROOT / "kg_microbe/transform_utils/ontologies/ontologies_transform.py",
    ]
    code_paths.extend(
        ROOT / "kg_microbe/utils" / (name + ".py")
        for name in (
            "finite_import_categories",
            "native_ro_retention",
            "ontology_parent_quarantine",
            "foodon_kernel_quarantine",
            "foodon_anatomical_categories",
            "uberon_temporal_categories",
        )
    )
    identities.update({str(path): file_identity(path) for path in code_paths})
    original_documents, documents, sources = {}, {}, {}
    for name in CONVERTED:
        receipt_path = candidates / "receipts" / (name + ".json")
        receipt = read_json(receipt_path)
        candidate = candidates / (name + ".json")
        source = candidates / (name + ".owl")
        for path in (receipt_path, candidate, source, original_raw / candidate.name, original_raw / source.name):
            identities[str(path)] = file_identity(path)
        require(identities[str(candidate)]["sha256"] == receipt["sha256"], f"Candidate receipt differs: {name}")
        require(
            identities[str(source)]["sha256"]
            == receipt["input"]["sha256"]
            == identities[str(original_raw / source.name)]["sha256"],
            f"Conversion source differs from preserved OWL: {name}",
        )
        for filename, key in (("robot.jar", "robot_sha256"), ("robot", "robot_wrapper_sha256")):
            tool = candidates / filename
            identities[str(tool)] = file_identity(tool)
            require(identities[str(tool)]["sha256"] == receipt[key], f"Conversion toolchain differs: {name}:{filename}")
        original_documents[name], documents[name], sources[name] = (
            read_json(original_raw / candidate.name),
            read_json(candidate),
            source,
        )
    for name in ("envo", "mondo"):
        path = original_raw / (name + ".json")
        staged = ROOT / "data/raw" / path.name
        identities[str(path)], identities[str(staged)] = file_identity(path), file_identity(staged)
        require(
            identities[str(path)]["sha256"] == identities[str(staged)]["sha256"],
            f"Canonical JSON source changed: {name}",
        )
        original_documents[name] = documents[name] = read_json(path)
    for policy_name in ("finite_import_category_dispositions.json", "native_ro_predicate_dispositions.json"):
        for authority in policies[policy_name]["authorities"].values():
            source = original_raw / authority["source"]["file"]
            identities[str(source)] = file_identity(source)
            require(
                identities[str(source)]["sha256"] == authority["source"]["sha256"],
                f"Unreviewed original authority release: {source}",
            )
    output.mkdir(parents=True, exist_ok=False)
    save(output / "inputs.json", identities)
    snapshot_root = output / "reviewed-code-and-policies"
    for source_path in [ROOT / "mappings" / name for name in policies] + code_paths:
        snapshot = snapshot_root / source_path.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as source, snapshot.open("xb") as destination:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                destination.write(chunk)
        require(
            file_identity(snapshot)["sha256"] == identities[str(source_path)]["sha256"],
            f"Review code/policy snapshot changed during copy: {source_path}",
        )
    annotations = {}
    completeness = {}
    for name in CONVERTED:
        prepared = production_comparison_copy(name, documents[name], sources[name], output)
        proof = assess_added_annotation_metadata(original_documents[name], prepared, sources[name])
        save(output / (name + "-annotation-proof.json"), proof)
        annotations[name] = {key: value for key, value in proof.items() if key != "complete_added_annotation_evidence"}
        completeness[name] = annotation_completeness_assessment(original_documents[name], prepared, proof)
        save(output / (name + "-annotation-completeness.json"), completeness[name])
    annotations_accepted = all(
        proof["only_added_annotation_metadata"]
        and proof["all_added_annotations_exactly_present_in_pinned_owl"]
        and not proof["unsupported_changes"]
        for proof in annotations.values()
    )
    results = {
        "finite_imports": review_check(review_finite, policies, documents, original_documents, sources),
        "native_ro": review_check(
            review_ro, policies["native_ro_predicate_dispositions.json"], documents, original_documents, sources
        ),
        "foodon": review_check(
            review_foodon, policies, original_documents["foodon"], documents["foodon"], sources["foodon"]
        ),
    }
    temporal_policy = temporal.load_temporal_category_policy(
        io.StringIO(json.dumps(policies["uberon_temporal_category_dispositions.json"]))
    )
    old_temporal = temporal.load_temporal_category_evidence(
        temporal_policy, io.StringIO(json.dumps(original_documents["uberon"]))
    )
    new_temporal = temporal.load_temporal_category_evidence(
        temporal_policy, io.StringIO(json.dumps(documents["uberon"]))
    )
    require(old_temporal == new_temporal, "Temporal category decisions changed")
    results["temporal"] = {
        "unchanged_policy_passed": True,
        "decisions": {key: asdict(value) for key, value in new_temporal.items()},
    }
    require(
        all(file_identity(Path(path)) == expected for path, expected in identities.items()),
        "Comparison inputs changed while being reviewed",
    )
    result = {
        "binding_inventory": BINDINGS,
        "checks": results,
        "annotation_summary": annotations,
        "annotation_completeness_assessment": completeness,
        "complete_annotation_proof_accepted": annotations_accepted,
        "policy_updates_applied": False,
        "raw_activation": False,
        "release_ready": False,
        "required_followup": (
            "Review and apply complete new declaration/context bindings with updated guards and faithful fixtures; "
            "rebuild GO and pass production admission before graph use."
        ),
    }
    save(output / "binding-review.json", result)
    return result


def main(argv=None):
    """Print binding inventory or review explicitly selected, completed conversion candidates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "compare"), nargs="?", default="plan")
    parser.add_argument("--original-raw", type=Path)
    parser.add_argument("--candidates", type=Path, default=EVIDENCE_ROOT / "robot-conversions")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "plan":
        print(
            json.dumps(
                {
                    "bindings": BINDINGS,
                    "converted_authorities": CONVERTED,
                    "unchanged_json_controls": ["envo", "mondo"],
                    "go_db_review": (
                        "Required separately after a genuine SemSQL rebuild; restriction policy binds unchanged "
                        "PATO/GO OWL and computed DB evidence."
                    ),
                },
                indent=2,
            )
        )
        return 0
    require(
        args.original_raw is not None and args.output is not None, "Comparison requires --original-raw and --output"
    )
    result = compare(args.original_raw.resolve(), args.candidates.resolve(), args.output.absolute())
    print(
        json.dumps(
            {
                "output": str(args.output),
                "policy_updates_applied": result["policy_updates_applied"],
                "release_ready": result["release_ready"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
