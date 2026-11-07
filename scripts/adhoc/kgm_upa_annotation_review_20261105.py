#!/usr/bin/env python3
"""
Retain the 2026-11-05 source-OWL proof for added ROBOT xref annotations.

The generic comparator reads local OBOGraphs documents and source OWL. It never
changes input documents or drops annotations from production output. A private
comparison projection removes only source-verified additions to establish what
changed. Unsupported differences remain explicit and prevent equivalence claims.
"""

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OWL = "http://www.w3.org/2002/07/owl#"
XREF = "http://www.geneontology.org/formats/oboInOwl#hasDbXref"


def owl_xref_annotations(path):
    """Index exact native annotated-xref facts and one-based source axiom ordinals."""
    from lxml import etree

    facts, ordinals, count = defaultdict(set), defaultdict(list), 0
    fixed = {"{" + OWL + "}" + field for field in ("annotatedSource", "annotatedProperty", "annotatedTarget")}
    context = etree.iterparse(
        str(path), events=("end",), tag="{" + OWL + "}Axiom", resolve_entities=False, no_network=True, load_dtd=False
    )
    for _, element in context:
        count += 1
        source = element.find("{" + OWL + "}annotatedSource")
        prop = element.find("{" + OWL + "}annotatedProperty")
        target = element.find("{" + OWL + "}annotatedTarget")
        if source is not None and prop is not None and target is not None and prop.get("{" + RDF + "}resource") == XREF:
            key = (source.get("{" + RDF + "}resource"), target.get("{" + RDF + "}resource", target.text or ""))
            for child in element:
                if not isinstance(child.tag, str) or child.tag in fixed:
                    continue
                if len(child):
                    raise ValueError("Nested annotated-xref source property is unsupported")
                namespace, local = child.tag[1:].split("}", 1)
                facts[key].add((namespace + local, child.get("{" + RDF + "}resource", child.text or "")))
            ordinals[key].append(count)
        element.clear()
    if context.root is not None and context.root.getroottree().docinfo.doctype:
        raise ValueError("Source OWL DTD is unsupported")
    return facts, ordinals, count


def assess_added_xref_metadata(original_document, candidate_document, owl_path):
    """Prove complete added xref metadata against OWL, preserving all occurrence order."""
    facts, ordinals, axiom_count = owl_xref_annotations(owl_path)
    original_graphs, candidate_graphs = original_document.get("graphs"), candidate_document.get("graphs")
    if not isinstance(original_graphs, list) or not isinstance(candidate_graphs, list):
        raise ValueError("Expected OBOGraphs graph arrays")
    if len(original_graphs) != len(candidate_graphs):
        raise ValueError("Graph count changed")
    projected = dict(candidate_document)
    projected["graphs"] = []
    additions, unsupported, changed_nodes, predicates = [], [], [], Counter()
    for graph_position, (old_graph, new_graph) in enumerate(zip(original_graphs, candidate_graphs, strict=True)):
        old_nodes, new_nodes = old_graph.get("nodes", []), new_graph.get("nodes", [])
        if len(old_nodes) != len(new_nodes):
            raise ValueError("Native node count changed")
        graph_copy = dict(new_graph)
        graph_copy["nodes"] = []
        projected["graphs"].append(graph_copy)
        for position, (old, new) in enumerate(zip(old_nodes, new_nodes, strict=True)):
            locator = {"graph_position": graph_position, "node_position": position, "node": old.get("id")}
            if old.get("id") != new.get("id"):
                unsupported.append({**locator, "error": "Node ID/order changed"})
                graph_copy["nodes"].append(new)
                continue
            if old == new:
                graph_copy["nodes"].append(new)
                continue
            changed_nodes.append(locator)
            normalized = copy.deepcopy(new)
            graph_copy["nodes"].append(normalized)
            old_refs = old.get("meta", {}).get("xrefs", [])
            new_refs = new.get("meta", {}).get("xrefs", [])
            normalized_refs = normalized.get("meta", {}).get("xrefs", [])
            if len(old_refs) != len(new_refs):
                unsupported.append({**locator, "error": "Xref occurrence count changed"})
                continue
            for index, (before, after, stripped) in enumerate(zip(old_refs, new_refs, normalized_refs, strict=True)):
                if before == after:
                    continue
                here = {**locator, "xref_position": index, "xref_value": after.get("val")}
                if (
                    "meta" in before
                    or set(after) != set(before) | {"meta"}
                    or {key: value for key, value in after.items() if key != "meta"} != before
                ):
                    unsupported.append({**here, "error": "Xref change extends beyond newly added metadata"})
                    continue
                metadata = after["meta"]
                if not isinstance(metadata, dict) or set(metadata) != {"basicPropertyValues"}:
                    unsupported.append({**here, "error": "Unsupported xref metadata shape"})
                    continue
                properties = metadata["basicPropertyValues"]
                if not isinstance(properties, list) or any(set(item) != {"pred", "val"} for item in properties):
                    unsupported.append({**here, "error": "Unsupported annotated property shape"})
                    continue
                actual = {(item["pred"], item["val"]) for item in properties}
                key = (old.get("id"), after.get("val"))
                matched = actual == facts[key] and len(actual) == len(properties) and bool(actual)
                additions.append(
                    {
                        **here,
                        "candidate_annotation": metadata,
                        "source_owl_axiom_ordinals_one_based": ordinals[key],
                        "source_owl_annotations": sorted(facts[key]),
                        "exact_source_annotation_match": matched,
                    }
                )
                if matched:
                    stripped.pop("meta")
                    predicates.update(predicate for predicate, _ in actual)
                else:
                    unsupported.append({**here, "error": "Added annotation does not exactly match source OWL"})
            if normalized != old:
                unsupported.append({**locator, "error": "Complete node differs beyond verified annotation additions"})
    equivalent = projected == original_document and not unsupported
    return {
        "owl_axioms_inspected": axiom_count,
        "added_xref_metadata_occurrences": len(additions),
        "changed_nodes": len(changed_nodes),
        "added_annotation_predicate_counts": dict(predicates),
        "complete_added_annotation_evidence": additions,
        "unsupported_changes": unsupported,
        "source_annotation_mismatches": [row for row in additions if not row["exact_source_annotation_match"]],
        "only_added_xref_metadata": equivalent,
        "all_added_annotations_exactly_present_in_pinned_owl": all(
            row["exact_source_annotation_match"] for row in additions
        ),
        "removing_only_verified_additions_recovers_exact_original_document": equivalent,
        "production_inputs_mutated": False,
        "release_ready": False,
    }


def main():
    """Write a new local proof artifact without changing policies or native input bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-json", type=Path, required=True)
    parser.add_argument("--candidate-json", type=Path, required=True)
    parser.add_argument("--source-owl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = (args.original_json, args.candidate_json, args.source_owl)
    identities = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    result = assess_added_xref_metadata(
        json.loads(args.original_json.read_text()), json.loads(args.candidate_json.read_text()), args.source_owl
    )
    if identities != {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise ValueError("Review inputs changed during comparison")
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
                if key not in {"complete_added_annotation_evidence", "unsupported_changes"}
            },
            indent=2,
        )
    )
    return 0 if result["removing_only_verified_additions_recovers_exact_original_document"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
