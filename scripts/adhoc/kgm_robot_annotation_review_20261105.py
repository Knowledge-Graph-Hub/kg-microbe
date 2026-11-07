#!/usr/bin/env python3
"""Prove newly serialized ROBOT annotation metadata against exact local OWL axiom facts."""

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OWL = "http://www.w3.org/2002/07/owl#"
OIO = "http://www.geneontology.org/formats/oboInOwl#"
XREF = OIO + "hasDbXref"
DEFINITION = "http://purl.obolibrary.org/obo/IAO_0000115"
SYNONYMS = frozenset(
    OIO + name for name in ("hasExactSynonym", "hasBroadSynonym", "hasNarrowSynonym", "hasRelatedSynonym")
)


def owl_annotation_index(path):
    """Index source/property/target triples and complete annotation values without ontology resolution."""
    from lxml import etree

    fixed = {"{" + OWL + "}" + field for field in ("annotatedSource", "annotatedProperty", "annotatedTarget")}
    facts, ordinals, details = defaultdict(set), defaultdict(list), defaultdict(list)
    count = 0
    out_of_scope = []
    context = etree.iterparse(
        str(path), events=("end",), tag="{" + OWL + "}Axiom", resolve_entities=False, no_network=True, load_dtd=False
    )
    for _, element in context:
        count += 1
        source = element.find("{" + OWL + "}annotatedSource")
        prop = element.find("{" + OWL + "}annotatedProperty")
        target = element.find("{" + OWL + "}annotatedTarget")
        if source is None or prop is None or target is None:
            raise ValueError("Incomplete source annotation axiom")
        if (
            len(source)
            or len(prop)
            or len(target)
            or not source.get("{" + RDF + "}resource")
            or not prop.get("{" + RDF + "}resource")
            or target.get("{" + RDF + "}nodeID") is not None
        ):
            # Logical axioms on anonymous expressions cannot justify any of the
            # named-node property records compared below. Retain their evidence
            # explicitly; never coerce a blank node/expression into a string key.
            out_of_scope.append(
                {
                    "axiom_ordinal_one_based": count,
                    "reason": "anonymous_or_nested_source_property_or_target",
                    "xml_serialization": etree.tostring(element, encoding="unicode", with_tail=False),
                }
            )
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
            continue
        key = (
            source.get("{" + RDF + "}resource"),
            prop.get("{" + RDF + "}resource"),
            target.get("{" + RDF + "}resource", target.text or ""),
        )
        if not key[0] or not key[1]:
            raise ValueError("Non-resource annotation source/property is unsupported")
        for child in element:
            if not isinstance(child.tag, str) or child.tag in fixed:
                continue
            if len(child):
                raise ValueError("Nested source annotation value is unsupported")
            namespace, local = child.tag[1:].split("}", 1)
            predicate, value = namespace + local, child.get("{" + RDF + "}resource", child.text or "")
            facts[key].add((predicate, value))
            details[key].append(
                {
                    "predicate": predicate,
                    "value": value,
                    "xml_attributes": dict(child.attrib),
                    "axiom_ordinal_one_based": count,
                }
            )
        ordinals[key].append(count)
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    if context.root is not None and context.root.getroottree().docinfo.doctype:
        raise ValueError("Source OWL DTD is unsupported")
    return facts, ordinals, details, count, out_of_scope


def annotation_slots(node):
    """Locate only the four explicitly supported OBOGraphs annotation-bearing record shapes."""
    meta = node.get("meta", {})
    result = {}
    if "definition" in meta:
        result[("meta", "definition")] = (DEFINITION, meta["definition"])
    for field in ("xrefs", "synonyms", "basicPropertyValues"):
        for index, record in enumerate(meta.get(field, [])):
            if not isinstance(record, dict):
                raise ValueError("Non-object OBOGraphs annotation record")
            if field == "xrefs":
                predicate = XREF
            elif field == "synonyms":
                predicate = record.get("pred", "")
                predicate = OIO + predicate if predicate.startswith("has") else predicate
                if predicate not in SYNONYMS:
                    raise ValueError("Unsupported synonym predicate")
            else:
                predicate = record.get("pred")
            result[("meta", field, index)] = (predicate, record)
    return result


def at_path(document, path):
    """Resolve one exact occurrence coordinate in a private comparison document."""
    for component in path:
        document = document[component]
    return document


def existing_annotation_facts(record):
    """Retain annotations already serialized in xrefs/synonymType before ROBOT1.9.11."""
    facts = set()
    for value in record.get("xrefs", []):
        if not isinstance(value, str):
            raise ValueError("Nonliteral existing annotation xref")
        facts.add((XREF, value))
    if "synonymType" in record:
        facts.add((OIO + "hasSynonymType", record["synonymType"]))
    return facts


def assess_added_annotation_metadata(original_document, candidate_document, owl_path):
    """Compare full documents and prove only newly added nested metadata, preserving occurrence order."""
    facts, ordinals, details, count, out_of_scope = owl_annotation_index(owl_path)
    original_graphs, candidate_graphs = original_document.get("graphs"), candidate_document.get("graphs")
    if (
        not isinstance(original_graphs, list)
        or not isinstance(candidate_graphs, list)
        or len(original_graphs) != len(candidate_graphs)
    ):
        raise ValueError("Graph arrays differ in shape or count")
    projected = dict(candidate_document)
    projected["graphs"] = []
    additions, unsupported, changes = [], [], Counter()
    for graph_position, (before_graph, after_graph) in enumerate(zip(original_graphs, candidate_graphs, strict=True)):
        before_nodes, after_nodes = before_graph.get("nodes", []), after_graph.get("nodes", [])
        if len(before_nodes) != len(after_nodes):
            raise ValueError("Node occurrence count changed")
        graph = dict(after_graph)
        graph["nodes"] = []
        projected["graphs"].append(graph)
        for position, (before, after) in enumerate(zip(before_nodes, after_nodes, strict=True)):
            locator = {"graph_position": graph_position, "node_position": position, "node": before.get("id")}
            if before == after:
                graph["nodes"].append(after)
                continue
            if before.get("id") != after.get("id"):
                unsupported.append({**locator, "error": "Node identity/order changed"})
                graph["nodes"].append(after)
                continue
            normalized = copy.deepcopy(after)
            graph["nodes"].append(normalized)
            old_slots, new_slots = annotation_slots(before), annotation_slots(after)
            for path, (predicate, record) in new_slots.items():
                old_slot = old_slots.get(path)
                if old_slot is None:
                    if "meta" in record:
                        unsupported.append(
                            {
                                **locator,
                                "property_path": list(path),
                                "error": "New annotation record has no original occurrence",
                            }
                        )
                    continue
                if record == old_slot[1]:
                    continue
                old_predicate, old_record = old_slot
                if "meta" not in record:
                    continue
                here = {
                    **locator,
                    "property_path": list(path),
                    "annotated_property": predicate,
                    "annotated_target": record.get("val"),
                }
                if (
                    predicate != old_predicate
                    or "meta" in old_record
                    or set(record) != set(old_record) | {"meta"}
                    or {key: value for key, value in record.items() if key != "meta"} != old_record
                ):
                    unsupported.append({**here, "error": "Property changed beyond newly added metadata"})
                    continue
                metadata = record["meta"]
                if not isinstance(metadata, dict) or set(metadata) != {"basicPropertyValues"}:
                    unsupported.append({**here, "error": "Unsupported added metadata shape"})
                    continue
                properties = metadata["basicPropertyValues"]
                if not isinstance(properties, list) or any(
                    not isinstance(item, dict) or set(item) != {"pred", "val"} for item in properties
                ):
                    unsupported.append({**here, "error": "Unsupported added annotation shape"})
                    continue
                actual = {(item["pred"], item["val"]) for item in properties}
                carried = existing_annotation_facts(old_record)
                key = (before["id"], predicate, old_record.get("val"))
                matched = bool(actual) and len(actual) == len(properties) and actual | carried == facts[key]
                evidence = {
                    **here,
                    "candidate_annotation": metadata,
                    "existing_serialized_annotation_facts": sorted(carried),
                    "source_owl_annotations": sorted(facts[key]),
                    "source_owl_annotation_details": details[key],
                    "source_owl_axiom_ordinals_one_based": ordinals[key],
                    "exact_source_annotation_match": matched,
                }
                additions.append(evidence)
                if matched:
                    at_path(normalized, path).pop("meta")
                    changes[str(path[1])] += 1
                else:
                    unsupported.append(
                        {**here, "error": "Added and preserved annotations do not exactly match source OWL"}
                    )
            if normalized != before:
                unsupported.append(
                    {**locator, "error": "Complete node has differences beyond verified annotation additions"}
                )
    equivalent = projected == original_document and not unsupported
    if projected != original_document and not unsupported:
        unsupported.append({"error": "Other graph/document data or order changed"})
    return {
        "owl_axioms_inspected": count,
        "out_of_scope_source_axioms": out_of_scope,
        "added_metadata_occurrences": len(additions),
        "verified_additions_by_location": dict(changes),
        "complete_added_annotation_evidence": additions,
        "source_annotation_mismatches": [row for row in additions if not row["exact_source_annotation_match"]],
        "unsupported_changes": unsupported,
        "all_added_annotations_exactly_present_in_pinned_owl": not any("property_path" in row for row in unsupported)
        and all(row["exact_source_annotation_match"] for row in additions),
        "only_added_annotation_metadata": equivalent,
        "removing_only_verified_additions_recovers_exact_original_document": equivalent,
        "production_inputs_mutated": False,
        "release_ready": False,
    }


def main():
    """Write a new proof artifact; unsupported differences stay explicit and inputs stay unchanged."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-json", type=Path, required=True)
    parser.add_argument("--candidate-json", type=Path, required=True)
    parser.add_argument("--source-owl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = (args.original_json, args.candidate_json, args.source_owl)
    identities = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    result = assess_added_annotation_metadata(
        json.loads(args.original_json.read_text()), json.loads(args.candidate_json.read_text()), args.source_owl
    )
    if identities != {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise ValueError("Review input changed")
    result["inputs"] = identities
    result["helper_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key
                not in {"complete_added_annotation_evidence", "source_annotation_mismatches", "unsupported_changes"}
            },
            indent=2,
        )
    )
    return 0 if result["only_added_annotation_metadata"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
