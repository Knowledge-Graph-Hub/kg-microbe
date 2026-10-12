"""Project validated native Rhea families without inferring flux or part/whole identity."""

import re

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    AUTOMATED_AGENT,
    CATEGORY_COLUMN,
    CHEBI_CATEGORY,
    EC_CATEGORY,
    EC_PREFIX,
    HAS_INPUT_PREDICATE,
    HAS_INPUT_RELATION,
    HAS_OUTPUT_PREDICATE,
    HAS_OUTPUT_RELATION,
    HAS_PARTICIPANT,
    HAS_PARTICIPANT_PREDICATE,
    ID_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    LOGICAL_ENTAILMENT,
    MANUAL_AGENT,
    MOLECULAR_ACTIVITY_CATEGORY,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    RHEA_CATEGORY,
    RHEA_TO_EC_EDGE,
    RHEA_TO_GO_EDGE,
    RHEA_XREF_RELATION,
    SUBJECT_COLUMN,
)
from kg_microbe.transform_utils.rhea_mappings.native_rdf import LABEL, RDFS, RH, NativeRheaError
from kg_microbe.transform_utils.rhea_mappings.reaction_families import RHEA_STATUS_FIELD

SOURCE = "infores:rhea"
EDGE_WITNESS_FIELDS = ("rhea_compound", "rhea_participant", "rhea_participant_route", "rhea_side")
POLYMERIZATION_FIELD = "rhea_polymerization_index"
_EC_LOCAL = r"[1-9][0-9]*(?:\.(?:[0-9]+|-)){2}\.(?:[0-9]+|-|n[1-9][0-9]*)"
_EC_IRI = re.compile(r"http://purl\.uniprot\.org/enzyme/(" + _EC_LOCAL + r")\Z")
_GO_IRI = re.compile(r"http://purl\.obolibrary\.org/obo/GO_([0-9]{7})\Z")


def native_curie(iri):
    """Compact native nonnumeric resources without minting invalid numeric RHEA IDs."""
    if (
        not iri.startswith(RH)
        or not iri[len(RH) :]
        or iri[len(RH) :].isdigit()
        or any(char in iri for char in "\t\r\n| ")
    ):
        raise NativeRheaError(f"Unsupported native Rhea resource: {iri!r}")
    return "rheav:" + iri[len(RH) :]


def edge(subject, predicate, target, relation=None, *, asserted=False, **witness):
    """Distinguish native assertions from documented path-derived participation edges."""
    return {
        SUBJECT_COLUMN: subject,
        PREDICATE_COLUMN: predicate,
        OBJECT_COLUMN: target,
        RELATION_COLUMN: relation or predicate,
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: SOURCE,
        KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION if asserted else LOGICAL_ENTAILMENT,
        AGENT_TYPE_COLUMN: MANUAL_AGENT if asserted else AUTOMATED_AGENT,
        **witness,
    }


def curated_xref(subject, target):
    """Preserve the activity-cross-reference contract; this is not physical enablement."""
    if not re.fullmatch(r"RHEA:[1-9][0-9]*", subject) or not (
        re.fullmatch("EC:" + _EC_LOCAL, target) or re.fullmatch(r"GO:[0-9]{7}", target)
    ):
        raise ValueError(f"Not a Rhea activity cross-reference: {subject} -> {target}")
    predicate = RHEA_TO_EC_EDGE if target.startswith(EC_PREFIX) else RHEA_TO_GO_EDGE
    return edge(subject, predicate, target, RHEA_XREF_RELATION, asserted=True)


def native_xrefs(record):
    """Read EC and GO from the same RDF snapshot, never independent latest tables."""
    for iri in record.get(RH + "ec", ()):
        match = _EC_IRI.fullmatch(iri)
        if match is None:
            raise NativeRheaError(f"Unsupported native EC cross-reference: {iri}")
        yield EC_PREFIX + match.group(1), EC_CATEGORY
    for iri in record.get(RDFS + "seeAlso", ()):
        match = _GO_IRI.fullmatch(iri)
        if match:
            yield "GO:" + match.group(1), MOLECULAR_ACTIVITY_CATEGORY
        elif "/GO_" in iri:
            raise NativeRheaError(f"Unsupported native GO cross-reference: {iri}")


def _node(identifier, category, name="", **annotations):
    """Declare an entity with source provenance and explicit source-specific annotations."""
    return {
        ID_COLUMN: identifier,
        CATEGORY_COLUMN: category,
        NAME_COLUMN: name,
        PROVIDED_BY_COLUMN: SOURCE,
        **annotations,
    }


def _native_entity(native, iri):
    """Retain a native compound/part, including its polymer index when supplied."""
    metadata = native.entity_metadata.get(iri, {})
    name = metadata.get(RH + "name", metadata.get(LABEL, ""))
    index = metadata.get(RH + "polymerizationIndex", "")
    return _node(native_curie(iri), CHEBI_CATEGORY, name, **{POLYMERIZATION_FIELD: index})


def family_rows(family, native, label_lookup):
    """
    Yield (kind, row) for one validated family, retaining every source participant path.

    Direct rh:chebi participants use ChEBI. Generic compounds and polymers keep
    their native identity: reactive parts and underlying ChEBI references are
    connected by their exact native relations, never substituted as reactants.
    UN and BI have undirected participation; only LR/RL get input/output roles.
    """
    side_witnesses = {side: native.chemical_participants(side) for side in native.reactions[family.master][RH + "side"]}
    for identifier, direction in family.members:
        record = native.reactions[identifier]
        annotations = family.node_annotations(identifier)
        annotations[RHEA_STATUS_FIELD] = record[RH + "status"][0][len(RH) :]
        yield "node", _node(identifier, RHEA_CATEGORY, record[LABEL][0], **annotations)
        # Most annotations are on the master, but the pinned native snapshot
        # includes exceptions. Keep their actual subjects; never move a claim.
        xrefs = tuple(native_xrefs(record))
        for target, category in xrefs:
            yield "node", _node(target, category, label_lookup(target) or "")
            yield "edge", curated_xref(identifier, target)
        fields = (
            (("side", HAS_PARTICIPANT_PREDICATE, HAS_PARTICIPANT),)
            if direction == "UN"
            else (
                (("substratesOrProducts", HAS_PARTICIPANT_PREDICATE, HAS_PARTICIPANT),)
                if direction == "BI"
                else (
                    ("substrates", HAS_INPUT_PREDICATE, HAS_INPUT_RELATION),
                    ("products", HAS_OUTPUT_PREDICATE, HAS_OUTPUT_RELATION),
                )
            )
        )
        for field, predicate, relation in fields:
            for side in record[RH + field]:
                seen_participants = set()
                for witness in side_witnesses[side]:
                    target = witness.chebi_id if witness.route == "direct_chebi" else native_curie(witness.compound_iri)
                    if witness.participant_iri not in seen_participants:
                        yield (
                            "edge",
                            edge(
                                identifier,
                                predicate,
                                target,
                                relation,
                                rhea_side=native_curie(side),
                                rhea_participant=native_curie(witness.participant_iri),
                                rhea_compound=native_curie(witness.compound_iri),
                                rhea_participant_route=witness.route,
                            ),
                        )
                        seen_participants.add(witness.participant_iri)
    for subject, predicate, target in family.links:
        yield "edge", edge(subject, predicate, target, asserted=True)
    # Entity/link rows are emitted once per witness here and deduplicated by the
    # producer across families. Participation edges retain distinct witnesses.
    for witnesses in side_witnesses.values():
        for witness in witnesses:
            yield "node", _node(witness.chebi_id, CHEBI_CATEGORY, label_lookup(witness.chebi_id) or "")
            if witness.route == "direct_chebi":
                continue
            compound = native_curie(witness.compound_iri)
            yield "node", _native_entity(native, witness.compound_iri)
            if witness.route == "underlying_chebi":
                yield "edge", edge(compound, "rheav:underlyingChebi", witness.chebi_id, asserted=True)
            else:
                part = native_curie(witness.reactive_part_iri)
                yield "node", _native_entity(native, witness.reactive_part_iri)
                yield "edge", edge(compound, "rheav:reactivePart", part, asserted=True)
                yield "edge", edge(part, "rheav:chebi", witness.chebi_id, asserted=True)
