"""Stream selected local Rhea RDF assertions without a graph loader or remote cache."""

from __future__ import annotations

import gzip
import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from lxml import etree

from kg_microbe.transform_utils.constants import CHEBI_PREFIX, RHEA_NEW_PREFIX

RH = "http://rdf.rhea-db.org/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
LABEL = RDFS + "label"
TYPE = RDF + "type"
REACTION_FIELDS = frozenset(
    {LABEL, TYPE, RDFS + "seeAlso"}
    | {
        RH + name
        for name in (
            "equation",
            "status",
            "directionalReaction",
            "bidirectionalReaction",
            "side",
            "substrates",
            "products",
            "substratesOrProducts",
            "ec",
            "citation",
        )
    }
)
LINK_FIELDS = frozenset(RH + name for name in ("contains", "compound", "chebi", "underlyingChebi", "reactivePart"))
CHEMICAL_FIELDS = frozenset(RH + name for name in ("chebi", "underlyingChebi", "reactivePart"))
ENTITY_METADATA_FIELDS = frozenset({LABEL, RH + "name", RH + "polymerizationIndex"})
LITERAL_FIELDS = ENTITY_METADATA_FIELDS | {RH + "equation"}
CHEBI_IRI = re.compile(r"http://purl\.obolibrary\.org/obo/CHEBI_([0-9]+)\Z")


class NativeRheaError(ValueError):
    """Signal missing, ambiguous or unsupported structure in selected native assertions."""


@dataclass(frozen=True)
class ChemicalParticipant:
    """Retain a ChEBI path witness without claiming whole-compound equivalence."""

    chebi_id: str
    side_iri: str
    participant_iri: str
    compound_iri: str
    route: str
    reactive_part_iri: str | None = None


def _unique(values: tuple[str, ...], description: str) -> str:
    """Require a single explicit target instead of selecting an arbitrary first value."""
    if not values:
        raise NativeRheaError(f"Missing {description}")
    if len(values) != 1:
        raise NativeRheaError(f"Ambiguous {description}: {values!r}")
    return values[0]


def _chebi(value: str) -> str:
    """Compact only the authoritative native ChEBI IRI spelling."""
    match = CHEBI_IRI.fullmatch(value)
    if match is None:
        raise NativeRheaError(f"Unsupported ChEBI resource: {value!r}")
    return CHEBI_PREFIX + match.group(1)


@dataclass(frozen=True)
class NativeRheaIndex:
    """Hold compact selected RDF adjacency, not a materialized XML or general RDF graph."""

    reactions: dict[str, dict[str, tuple[str, ...]]]
    sides: dict[str, tuple[str, ...]]
    participants: dict[str, tuple[str, ...]]
    compounds: dict[str, dict[str, tuple[str, ...]]]
    reactive_parts: dict[str, tuple[str, ...]]
    entity_metadata: dict[str, dict[str, str]] = field(default_factory=dict)

    def chemical_participants(self, side: str) -> tuple[ChemicalParticipant, ...]:
        """Resolve every direct, underlying-polymer or reactive-part path on one explicit side."""
        participants = self.sides.get(side, ())
        if not participants:
            raise NativeRheaError(f"Missing or empty reaction side: {side}")
        result = []
        for participant in participants:
            compound = _unique(self.participants.get(participant, ()), f"participant compound for {participant}")
            properties = self.compounds.get(compound, {})
            routes = [predicate for predicate in CHEMICAL_FIELDS if properties.get(predicate)]
            if not routes:
                raise NativeRheaError(f"Missing chemical route for compound {compound}")
            if len(routes) != 1:
                raise NativeRheaError(f"Ambiguous chemical route for compound {compound}: {sorted(routes)!r}")
            predicate = routes[0]
            if predicate == RH + "reactivePart":
                for reactive_part in properties[predicate]:
                    target = _unique(
                        self.reactive_parts.get(reactive_part, ()), f"reactive part ChEBI for {reactive_part}"
                    )
                    result.append(
                        ChemicalParticipant(
                            _chebi(target), side, participant, compound, "reactive_part_chebi", reactive_part
                        )
                    )
            else:
                target = _unique(properties[predicate], f"compound ChEBI for {compound}")
                route = "direct_chebi" if predicate == RH + "chebi" else "underlying_chebi"
                result.append(ChemicalParticipant(_chebi(target), side, participant, compound, route))
        return tuple(result)


def _iri(tag: str) -> str:
    """Expand an XML Clark-name into its exact namespace IRI."""
    if not tag.startswith("{") or "}" not in tag:
        raise NativeRheaError(f"Unqualified native RDF element: {tag!r}")
    namespace, name = tag[1:].split("}", 1)
    return namespace + name


def _value(element, predicate: str) -> str:
    """Require the native resource-versus-literal shape for every selected property."""
    if len(element):
        raise NativeRheaError(f"Nested selected RDF property is unsupported: {predicate}")
    resource = element.get("{" + RDF + "}resource")
    if predicate in LITERAL_FIELDS:
        if resource is not None or element.get("{" + RDF + "}nodeID") is not None:
            raise NativeRheaError(f"Expected literal for {predicate}")
        return element.text or ""
    if any(element.get("{" + RDF + "}" + name) is not None for name in ("nodeID", "datatype", "parseType")):
        raise NativeRheaError(f"Conflicting resource shape for {predicate}")
    if not resource or not resource.startswith(("http://", "https://")) or (element.text or "").strip():
        raise NativeRheaError(f"Expected absolute resource for {predicate}")
    return resource


def _collect_record(element, records: dict[str, dict[str, set[str]]]) -> None:
    """Union selected values from a complete top-level RDF record, including split descriptions."""
    subject = element.get("{" + RDF + "}about", "")
    numeric = subject.startswith(RH) and re.fullmatch(r"[0-9]+", subject[len(RH) :]) is not None
    selected = REACTION_FIELDS | LINK_FIELDS if numeric else LINK_FIELDS | ENTITY_METADATA_FIELDS
    properties: dict[str, set[str]] = {}
    if numeric and element.tag != "{" + RDF + "}Description":
        properties[TYPE] = {_iri(element.tag)}
    for child in element:
        if not isinstance(child.tag, str):
            continue
        predicate = _iri(child.tag)
        if predicate in selected:
            properties.setdefault(predicate, set()).add(_value(child, predicate))
    if not properties:
        return
    if not subject.startswith(("http://", "https://")):
        raise NativeRheaError("Selected RDF record requires an absolute rdf:about subject")
    target = records.setdefault(subject, {})
    for predicate, values in properties.items():
        target.setdefault(predicate, set()).update(values)


def _stream_records(stream: BinaryIO) -> dict[str, dict[str, tuple[str, ...]]]:
    """Consume XML records incrementally, clearing completed siblings while retaining only selected fields."""
    records: dict[str, dict[str, set[str]]] = {}
    context = etree.iterparse(stream, events=("start", "end"), resolve_entities=False, no_network=True, load_dtd=False)
    root = None
    for event, element in context:
        if root is None:
            root = element
            if root.tag != "{" + RDF + "}RDF":
                raise NativeRheaError("Expected a native rdf:RDF root")
        if event == "end" and element.getparent() is root:
            _collect_record(element, records)
            element.clear()
            while element.getprevious() is not None:
                del root[0]
    if root is None:
        raise NativeRheaError("Empty native Rhea RDF")
    if root.getroottree().docinfo.doctype:
        raise NativeRheaError("DTD declarations are unsupported in selected native Rhea RDF")
    return {
        subject: {predicate: tuple(sorted(values)) for predicate, values in properties.items()}
        for subject, properties in records.items()
    }


def load_native_rdf(source: Path | str | BinaryIO, *, compressed: bool | None = None) -> NativeRheaIndex:
    """Read only the supplied local path or caller-owned binary stream; never consult remote or home caches."""
    with ExitStack() as stack:
        if isinstance(source, (str, Path)):
            path = Path(source)
            stream = stack.enter_context(path.open("rb"))
            if compressed is None:
                compressed = path.suffix == ".gz"
        else:
            if compressed is None:
                raise ValueError("Caller-owned streams require explicit compressed=True or compressed=False")
            stream = source
        if compressed:
            stream = stack.enter_context(gzip.GzipFile(fileobj=stream, mode="rb"))
        records = _stream_records(stream)
    reactions = {
        RHEA_NEW_PREFIX + subject[len(RH) :]: {
            predicate: values for predicate, values in properties.items() if predicate in REACTION_FIELDS
        }
        for subject, properties in records.items()
        if subject.startswith(RH) and re.fullmatch(r"[0-9]+", subject[len(RH) :])
    }
    if not reactions:
        raise NativeRheaError("No numeric reaction records in selected native Rhea RDF")
    sides = {
        subject: properties[RH + "contains"] for subject, properties in records.items() if RH + "contains" in properties
    }
    participants = {
        subject: properties[RH + "compound"] for subject, properties in records.items() if RH + "compound" in properties
    }
    compound_ids = {compound for values in participants.values() for compound in values}
    compounds = {
        subject: {predicate: values for predicate, values in properties.items() if predicate in CHEMICAL_FIELDS}
        for subject, properties in records.items()
        if subject in compound_ids
    }
    reactive_ids = {part for properties in compounds.values() for part in properties.get(RH + "reactivePart", ())}
    reactive_parts = {
        subject: properties[RH + "chebi"]
        for subject, properties in records.items()
        if subject in reactive_ids and RH + "chebi" in properties
    }
    entity_ids = compound_ids | reactive_ids
    entity_metadata = {
        subject: {
            predicate: _unique(values, f"entity metadata {predicate} for {subject}")
            for predicate, values in properties.items()
            if predicate in ENTITY_METADATA_FIELDS
        }
        for subject, properties in records.items()
        if subject in entity_ids
    }
    return NativeRheaIndex(reactions, sides, participants, compounds, reactive_parts, entity_metadata)
