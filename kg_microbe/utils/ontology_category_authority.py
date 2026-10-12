"""
Classify generic ontology declarations using one pinned asserted hierarchy.

This policy is independent of labels, graph predicates and identity mappings.
Each namespace has one explicit authority: imports from unrelated releases are
never combined to manufacture an ancestry path. Unknown, obsolete, individual,
property and disconnected declarations have no category decision.
"""

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from lxml import etree

from kg_microbe.transform_utils.constants import (
    ANATOMICAL_ENTITY_CATEGORY,
    ASSAY_CATEGORY,
    ATTRIBUTE_CATEGORY,
    BIOLOGICAL_PROCESS_CATEGORY,
    CELLULAR_COMPONENT_CATEGORY,
    CHEMICAL_CATEGORY,
    ENVIRONMENT_CATEGORY,
    ENVIRONMENTAL_PROCESS_CATEGORY,
    INFORMATION_CONTENT_ENTITY_CATEGORY,
    MEDIUM_CATEGORY,
    MOLECULAR_ACTIVITY_CATEGORY,
    NCBI_CATEGORY,
    PHYSICAL_ENTITY_CATEGORY,
    POPULATION_CATEGORY,
    ROLE_CATEGORY,
    SOLUTION_CATEGORY,
)
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

# ENVO roots have exact mappings in the pinned Biolink model. Material entity
# is projected only to PhysicalEntity, without claiming a chemical mixture.
# The remaining roots are explicit anatomy, chemistry, quality, process and
# information declarations. Bare BFO occurrents remain unresolved: Biolink's
# Occurrent is a mixin, not a substantive category for this policy.
_ROOT_CATEGORIES = {
    "ENVO:01000254": ENVIRONMENT_CATEGORY,
    "ENVO:02500000": ENVIRONMENTAL_PROCESS_CATEGORY,
    "BFO:0000040": PHYSICAL_ENTITY_CATEGORY,
    "CHEBI:24431": CHEMICAL_CATEGORY,
    "CHEBI:60004": SOLUTION_CATEGORY,
    "CHEBI:50906": ROLE_CATEGORY,
    "UBERON:0001062": ANATOMICAL_ENTITY_CATEGORY,
    "CARO:0000000": ANATOMICAL_ENTITY_CATEGORY,
    "PO:0025131": ANATOMICAL_ENTITY_CATEGORY,
    "PO:0000003": NCBI_CATEGORY,
    "COB:0000022": NCBI_CATEGORY,
    "PATO:0000001": ATTRIBUTE_CATEGORY,
    "GO:0008150": BIOLOGICAL_PROCESS_CATEGORY,
    "GO:0003674": MOLECULAR_ACTIVITY_CATEGORY,
    "GO:0005575": CELLULAR_COMPONENT_CATEGORY,
    "OBI:0000011": ASSAY_CATEGORY,
    "OBI:0000079": MEDIUM_CATEGORY,
    "IAO:0000030": INFORMATION_CONTENT_ENTITY_CATEGORY,
    "PCO:0000001": POPULATION_CATEGORY,
}
_AUTHORITY_BY_PREFIX = {
    "ENVO": "envo.json",
    "BFO": "envo.json",
    "RO": "envo.json",
    "PCO": "envo.json",
    "IAO": "envo.json",
    "OBI": "envo.json",
    "PO": "po.owl",
    "MICRO": "micro.owl",
    # These selected pinned imports contain explicit native-ID declarations;
    # lack of a complete asserted path produces no decision.
    "NBO": "uberon.json",
    "BSPO": "uberon.json",
    "CARO": "uberon.json",
    "FAO": "foodon.json",
    "FLOPO": "foodon.json",
    "GENEPIO": "foodon.json",
}
_SUBCLASS_PREDICATES = {"is_a", "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf"}
_OWL = "{http://www.w3.org/2002/07/owl#}"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"


@dataclass(frozen=True)
class CategoryEvidence:
    """Immutable decision and complete shortest asserted witness paths to roots."""

    identifier: str
    authority: str
    category: str | None
    disposition: str
    root_paths: tuple[tuple[str, ...], ...] = ()
    supporting_axioms: tuple[tuple[str, str, str], ...] = ()


class OntologyCategoryAuthority:
    """
    Load selected local authorities lazily, recording every consulted path.

    ``opener(path)`` must return a context manager yielding the immutable text
    snapshot consumed by finalization. Without an opener, this read-only helper
    opens local files directly; callers then own input fingerprint verification.
    """

    def __init__(self, raw_dir, *, opener=None):
        """Retain the selected raw directory without opening unrelated authorities."""
        self.raw_dir = Path(raw_dir)
        self.opener = opener or (lambda path: path.open(encoding="utf-8"))
        self.source_paths = set()
        self._hierarchies = {}
        self._decisions = {}
        from kg_microbe.utils.finite_import_categories import FiniteImportCategoryAuthority

        self.finite_imports = FiniteImportCategoryAuthority(self.raw_dir, opener=self.opener)

    def finite_evidence_for(self, identifier):
        """Consult exact reviewed imports without widening the namespace authorities."""
        evidence = self.finite_imports.evidence_for(identifier)
        self.source_paths.update(self.finite_imports.source_paths)
        return evidence

    def _load(self, filename):
        """Parse one hierarchy; missing, malformed or empty authority is fatal."""
        if filename in self._hierarchies:
            return self._hierarchies[filename]
        path = self.raw_dir / filename
        self.source_paths.add(path)
        declarations, parents, axioms = {}, defaultdict(set), {}
        with self.opener(path) as stream:
            if path.suffix == ".json":
                document = json.load(stream)
                graphs = document.get("graphs")
                if not isinstance(graphs, list) or not graphs:
                    raise ValueError(f"Missing ontology graphs: {path}")
                for graph in graphs:
                    for node in graph["nodes"]:
                        identifier = compact_identifier(node["id"])
                        kind = node.get("type", "")
                        deprecated = obograph_is_deprecated(node)
                        previous = declarations.get(identifier)
                        value = (kind, deprecated)
                        if previous is not None and previous != value:
                            raise ValueError(f"Conflicting declarations for {identifier}: {path}")
                        declarations[identifier] = value
                    for edge in graph.get("edges", []):
                        if edge["pred"] in _SUBCLASS_PREDICATES:
                            child, parent = compact_identifier(edge["sub"]), compact_identifier(edge["obj"])
                            parents[child].add(parent)
                            axioms[child, parent] = "rdfs:subClassOf"
            else:
                # Selected XML authorities are small source ontologies, not
                # graph-scale merged inputs. Keep equivalent intersections
                # intact to read their asserted named genus; never follow a
                # restriction filler, union operand, part_of or other relation.
                binary = stream.buffer if hasattr(stream, "buffer") else BytesIO(stream.read().encode("utf-8"))
                document = etree.parse(
                    binary, etree.XMLParser(resolve_entities="internal", no_network=True, load_dtd=False)
                )
                for element in document.iter(_OWL + "Class"):
                    iri = element.get(_RDF + "about")
                    if iri:
                        identifier = compact_identifier(iri)
                        obsolete_values = {
                            (annotation.text or "").strip().lower()
                            for annotation in element.findall(_OWL + "deprecated")
                        }
                        if obsolete_values - {"true", "false", "1", "0"}:
                            raise ValueError(f"Malformed obsolete flag for {identifier}: {path}")
                        if obsolete_values & {"true", "1"} and obsolete_values & {"false", "0"}:
                            raise ValueError(f"Conflicting obsolete flags for {identifier}: {path}")
                        obsolete = bool(obsolete_values & {"true", "1"})
                        previous = declarations.get(identifier)
                        if previous and previous[1] != obsolete and len(element):
                            raise ValueError(f"Conflicting declarations for {identifier}: {path}")
                        declarations[identifier] = ("CLASS", obsolete or bool(previous and previous[1]))
                        for parent in element.findall(_RDFS + "subClassOf"):
                            target = parent.get(_RDF + "resource")
                            if target:
                                parent_id = compact_identifier(target)
                                parents[identifier].add(parent_id)
                                axioms[identifier, parent_id] = "rdfs:subClassOf"
                        for equivalent in element.findall(_OWL + "equivalentClass"):
                            for intersection in equivalent.findall(_OWL + "Class/" + _OWL + "intersectionOf"):
                                for genus in intersection:
                                    if genus.tag in {_RDF + "Description", _OWL + "Class"}:
                                        target = genus.get(_RDF + "about")
                                        if target:
                                            parent_id = compact_identifier(target)
                                            parents[identifier].add(parent_id)
                                            axioms[identifier, parent_id] = (
                                                "owl:equivalentClass/owl:intersectionOf/named_genus"
                                            )
        if not declarations:
            raise ValueError(f"No ontology declarations: {path}")
        result = declarations, dict(parents), axioms
        self._hierarchies[filename] = result
        return result

    def evidence_for(self, identifier):
        """Return a category only for a live declared class with supported ancestry."""
        identifier = compact_identifier(identifier)
        if identifier in self._decisions:
            return self._decisions[identifier]
        finite = self.finite_evidence_for(identifier)
        if finite is not None:
            decision = CategoryEvidence(
                identifier,
                str(self.raw_dir / finite.authority),
                finite.category,
                finite.disposition,
                finite.root_paths,
                finite.supporting_axioms,
            )
            self._decisions[identifier] = decision
            return decision
        filename = _AUTHORITY_BY_PREFIX.get(identifier.partition(":")[0])
        if filename is None:
            decision = CategoryEvidence(identifier, "", None, "no_selected_authority")
        else:
            declarations, parents, axioms = self._load(filename)
            declaration = declarations.get(identifier)
            if declaration != ("CLASS", False):
                disposition = "undeclared" if declaration is None else "obsolete_or_not_class"
                decision = CategoryEvidence(identifier, str(self.raw_dir / filename), None, disposition)
            else:
                paths, pending = {identifier: (identifier,)}, deque([identifier])
                while pending:
                    current = pending.popleft()
                    for parent in sorted(parents.get(current, ())):
                        if parent not in paths and declarations.get(parent) == ("CLASS", False):
                            paths[parent] = (*paths[current], parent)
                            pending.append(parent)
                matches = {root: paths[root] for root in _ROOT_CATEGORIES if root in paths}
                categories = {_ROOT_CATEGORIES[root] for root in matches}
                processes = {
                    BIOLOGICAL_PROCESS_CATEGORY,
                    ENVIRONMENTAL_PROCESS_CATEGORY,
                    MOLECULAR_ACTIVITY_CATEGORY,
                    ASSAY_CATEGORY,
                }
                materials = {
                    PHYSICAL_ENTITY_CATEGORY,
                    ENVIRONMENT_CATEGORY,
                    CHEMICAL_CATEGORY,
                    SOLUTION_CATEGORY,
                    MEDIUM_CATEGORY,
                    ANATOMICAL_ENTITY_CATEGORY,
                    NCBI_CATEGORY,
                    POPULATION_CATEGORY,
                    CELLULAR_COMPONENT_CATEGORY,
                }
                distinct_kinds = sum(
                    bool(categories & group)
                    for group in (
                        processes,
                        materials,
                        {ATTRIBUTE_CATEGORY, ROLE_CATEGORY},
                        {INFORMATION_CONTENT_ENTITY_CATEGORY},
                    )
                )
                if distinct_kinds > 1:
                    raise ValueError(
                        f"Contradictory material/process/quality/information ancestry for {identifier} "
                        f"in {filename}: {sorted(matches)}"
                    )
                # Broad material and organism-containing anatomy ancestors add
                # no information once a more specific, independently asserted
                # substantive category is available.
                if len(categories) > 1:
                    categories.discard(PHYSICAL_ENTITY_CATEGORY)
                if NCBI_CATEGORY in categories:
                    categories.discard(ANATOMICAL_ENTITY_CATEGORY)
                if POPULATION_CATEGORY in categories:
                    categories.discard(NCBI_CATEGORY)
                if SOLUTION_CATEGORY in categories:
                    categories.discard(CHEMICAL_CATEGORY)
                category = "|".join(sorted(categories)) or None
                witnesses = tuple(matches[root] for root in sorted(matches))
                supporting = tuple(
                    sorted(
                        {
                            (child, axioms[child, parent], parent)
                            for path in witnesses
                            for child, parent in zip(path, path[1:], strict=False)
                        }
                    )
                )
                decision = CategoryEvidence(
                    identifier,
                    str(self.raw_dir / filename),
                    category,
                    "asserted_ancestry" if category else "no_supported_ancestor",
                    witnesses,
                    supporting,
                )
        self._decisions[identifier] = decision
        return decision

    def category_for(self, identifier):
        """Return the evidence-backed category string, or None for unresolved IDs."""
        return self.evidence_for(identifier).category
