"""One contradictory native FOODON parent, reviewed independently in full JSON and OWL (#1296)."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from kg_microbe.transform_utils.constants import FOOD_CATEGORY, NCBI_CATEGORY
from kg_microbe.utils.graph_canonicalization import compact_identifier as compact

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/foodon_kernel_quarantine.json"
POLICY_SHA256 = "b99986799f4211fc351822daf66573b63e8d962963dc996ab21f55a010aed12f"
JSON_EVIDENCE_SHA256 = "6b3ad72929810b9aa978d8890da81bb9aee08842281223002ae4c30d94ccca6a"
OWL_EVIDENCE_SHA256 = "ed16d92d6161720ab25aefb5d0330967f80d37e160cd5bef423407c301d2944d"
POLICY_ROLE = "ontology_foodon_kernel_policy"
JSON_ROLE = "ontology_foodon_kernel_json"
OWL_ROLE = "ontology_foodon_kernel_owl"
AUDIT_FILE = "foodon_kernel_quarantine.tsv"
ROOT_ID = "FOODON:00005106"
COHORT_IDS = frozenset(f"FOODON:{number:08d}" for number in (*range(5106, 5110), *range(5119, 5137)))
REJECTED_PARENT = "FOODON:00005088"
REJECTED_TRIPLE = (ROOT_ID, "is_a", REJECTED_PARENT)
_OWL = "{http://www.w3.org/2002/07/owl#}"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"


def canonical(value):
    """Stable complete evidence serialization, not a mutable receipt's assertion of identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    """Hash reviewed structure independent of formatting-only differences."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unique_object(pairs):
    """Refuse overwritten native or curated JSON assertions."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate FOODON kernel evidence JSON key")
        value[key] = item
    return value


def load_policy(stream):
    """Require the complete independently code-pinned scientific disposition."""
    policy = json.load(stream, object_pairs_hook=unique_object)
    if digest(policy) != POLICY_SHA256:
        raise ValueError("FOODON kernel policy changed; independent native review required")
    return policy


def _descendants(children, starts):
    found, todo = set(starts), list(starts)
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def _triple(edge):
    predicate = compact(edge["pred"])
    if predicate == "rdfs:subClassOf":
        predicate = "is_a"
    return compact(edge["sub"]), predicate, compact(edge["obj"])


def json_evidence(graphs, policy):
    """Check every selected class/incident assertion and the full asserted descendant closure."""
    if not isinstance(graphs, list) or not graphs:
        raise ValueError("Missing FOODON kernel native graph declarations")
    cohort = set(policy["cohort"])
    selected = cohort | set(policy["controls"])
    nodes = [node for graph in graphs for node in graph.get("nodes", [])]
    edges = [edge for graph in graphs for edge in graph.get("edges", [])]
    present = {compact(node["id"]) for node in nodes} & cohort
    touched = any(_triple(edge)[0] in cohort or _triple(edge)[2] in cohort for edge in edges)
    if not present and not touched:
        return None
    if present != cohort:
        raise ValueError("FOODON kernel reviewed cohort is partial or missing declarations")
    evidence = {
        "nodes": sorted([node for node in nodes if compact(node["id"]) in selected], key=canonical),
        "incident_edges": sorted(
            [edge for edge in edges if _triple(edge)[0] in cohort or _triple(edge)[2] in cohort], key=canonical
        ),
        "logical_definition_axioms": sorted(
            [
                axiom
                for graph in graphs
                for axiom in graph.get("logicalDefinitionAxioms", [])
                if compact(axiom["definedClassId"]) in cohort
            ],
            key=canonical,
        ),
    }
    if digest(evidence) != JSON_EVIDENCE_SHA256:
        raise ValueError("FOODON kernel native JSON class/axiom evidence changed or duplicated")
    children = defaultdict(set)
    for edge in edges:
        child, predicate, parent = _triple(edge)
        if predicate == "is_a":
            children[parent].add(child)
    if _descendants(children, {ROOT_ID}) != cohort:
        raise ValueError("FOODON kernel asserted descendant cohort changed")
    return evidence


def _xml_record(element):
    """Preserve complete native class structure without XML prefix/indentation artifacts."""
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": (element.text or "").strip(),
        "children": [_xml_record(child) for child in element if isinstance(child.tag, str)],
    }


def _owl_tree(stream):
    """Parse one complete local native OWL snapshot without external resource resolution."""
    binary = getattr(stream, "buffer", stream)
    return etree.parse(binary, etree.XMLParser(resolve_entities="internal", no_network=True, load_dtd=False))


def owl_evidence(stream, policy):
    """Independently validate full native OWL selected declarations and named-parent closure."""
    return _owl_evidence(_owl_tree(stream), policy)


def _owl_evidence(tree, policy):
    """Validate the complete finite native witnesses against the parsed source tree."""
    selected = set(policy["cohort"]) | set(policy["controls"])
    evidence, children = {}, defaultdict(set)
    for element in tree.iter(_OWL + "Class"):
        identifier = compact(element.get(_RDF + "about", ""))
        if not identifier or not len(element):
            continue
        if identifier in selected:
            if identifier in evidence:
                raise ValueError("Duplicate FOODON kernel native OWL class declaration")
            evidence[identifier] = _xml_record(element)
        for parent in element.findall(_RDFS + "subClassOf"):
            target = parent.get(_RDF + "resource")
            if target:
                children[compact(target)].add(identifier)
    if digest(evidence) != OWL_EVIDENCE_SHA256:
        raise ValueError("FOODON kernel native OWL evidence changed or incomplete")
    if _descendants(children, {ROOT_ID}) != set(policy["cohort"]):
        raise ValueError("FOODON kernel native OWL descendant cohort changed")
    children[REJECTED_PARENT].remove(ROOT_ID)
    from kg_microbe.utils.foodon_classification import ORGANISM_ROOTS

    if _descendants(children, ORGANISM_ROOTS) & set(policy["cohort"]):
        raise ValueError("FOODON kernel retains an alternate native OWL organism path")
    if not {REJECTED_PARENT, policy["source_plant"]} <= _descendants(children, ORGANISM_ROOTS):
        raise ValueError("FOODON kernel native OWL whole-plant controls lost organism ancestry")
    return evidence


def _live_hierarchy(graphs, tree):
    """
    Project source-proven retirements only after inspecting complete native declarations.

    The producer retains the original JSON/OWL snapshots. This classification
    view matches its later private deprecation preparation; it does not replace
    the complete finite witnesses or relax the ordinary live-class validator.
    """
    from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

    declarations = {}
    for graph in graphs:
        for node in graph.get("nodes", []):
            identifier = compact(node["id"])
            declaration = (node.get("type", ""), obograph_is_deprecated(node))
            if identifier in declarations and declarations[identifier] != declaration:
                raise ValueError(f"Conflicting FOODON declarations: {identifier}")
            declarations[identifier] = declaration
    retired = {identifier for identifier, (_, obsolete) in declarations.items() if obsolete}
    supported, source_parents = set(), set()
    source_types = {
        _OWL + "Class": "CLASS",
        _OWL + "ObjectProperty": "PROPERTY",
        _OWL + "DatatypeProperty": "PROPERTY",
        _OWL + "AnnotationProperty": "PROPERTY",
        _OWL + "NamedIndividual": "INDIVIDUAL",
        _RDF + "Description": "",
    }
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        identifier = compact(element.get(_RDF + "about", ""))
        if not identifier:
            continue
        if identifier in retired:
            for flag in element.findall(_OWL + "deprecated"):
                if (flag.text or "").strip() not in {"true", "1"}:
                    raise ValueError(f"Conflicting FOODON native OWL retirement: {identifier}")
                if source_types.get(element.tag) != declarations[identifier][0]:
                    raise ValueError(f"Conflicting FOODON native OWL declaration: {identifier}")
                supported.add(identifier)
        if element.tag == _OWL + "Class":
            for parent in element.findall(_RDFS + "subClassOf"):
                target = parent.get(_RDF + "resource")
                if target:
                    source_parents.add((identifier, "is_a", compact(target)))
    if retired != supported:
        raise ValueError(f"FOODON retirement lacks native OWL evidence: {sorted(retired - supported)}")
    for graph in graphs:
        for edge in graph.get("edges", []):
            child, predicate, parent = triple = _triple(edge)
            if predicate == "is_a":
                # Check both original endpoints before dropping incidence. A
                # retired endpoint must never hide a missing/nonclass peer.
                for identifier in (child, parent):
                    if declarations.get(identifier, (None,))[0] != "CLASS":
                        raise ValueError(f"Invalid FOODON subclass evidence: {identifier} lacks a CLASS declaration")
            if child in retired or parent in retired:
                if triple not in source_parents:
                    raise ValueError(f"FOODON retired incidence lacks native OWL named-parent evidence: {triple}")
    return [
        {
            **graph,
            "nodes": [node for node in graph.get("nodes", []) if compact(node["id"]) not in retired],
            "edges": [
                edge
                for edge in graph.get("edges", [])
                if compact(edge["sub"]) not in retired and compact(edge["obj"]) not in retired
            ],
        }
        for graph in graphs
    ]


@dataclass(frozen=True)
class KernelEvidence:
    """Finite category scope and original native witnesses, never a replacement ontology identity."""

    cohort: frozenset
    json_records: dict
    owl_records: dict


def reviewed_hierarchy(graphs, policy, *, native_owl=None):
    """Validate pristine witnesses, then exclude retired incidence and one exact parent from a live view."""
    if digest(policy) != POLICY_SHA256:
        raise ValueError("Unreviewed FOODON kernel policy")
    records = json_evidence(graphs, policy)
    if records is None:
        return graphs, None
    if native_owl is None:
        raise ValueError("FOODON kernel native OWL evidence is required")
    tree = _owl_tree(native_owl)
    xml = _owl_evidence(tree, policy)
    live = _live_hierarchy(graphs, tree)
    removed = [edge for graph in graphs for edge in graph.get("edges", []) if _triple(edge) == REJECTED_TRIPLE]
    if len(removed) != 1:
        raise ValueError("FOODON kernel must quarantine exactly one native named parent")
    view = [
        {**graph, "edges": [edge for edge in graph.get("edges", []) if _triple(edge) != REJECTED_TRIPLE]}
        for graph in live
    ]
    from kg_microbe.utils.foodon_classification import organism_classes

    original, retained = organism_classes(live), organism_classes(view)
    cohort = frozenset(policy["cohort"])
    if original - retained != cohort or retained - original:
        raise ValueError("FOODON kernel hierarchy correction changes an unreviewed category cohort")
    if not {REJECTED_PARENT, policy["source_plant"]} <= retained:
        raise ValueError("FOODON whole-plant controls were not retained")
    return view, KernelEvidence(cohort, records, xml)


def apply_kernel_category(identifier, category, evidence):
    """Replace only the reviewed unsupported organism category, refusing unrelated substantive conflicts."""
    if evidence is None or identifier not in evidence.cohort:
        return category
    existing = set(category.split("|")) - {""}
    allowed = {"biolink:OntologyClass", "biolink:NamedThing", FOOD_CATEGORY, NCBI_CATEGORY}
    if existing - allowed:
        raise ValueError(f"FOODON kernel has an unreviewed substantive category conflict: {identifier}")
    return FOOD_CATEGORY
