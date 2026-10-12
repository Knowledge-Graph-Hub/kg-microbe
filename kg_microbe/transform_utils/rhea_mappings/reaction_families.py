"""Validate Rhea's explicit four-member families without inferring reaction flux."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TextIO

from kg_microbe.transform_utils.constants import RHEA_NEW_PREFIX

DIRECTIONS_HEADER = ("RHEA_ID_MASTER", "RHEA_ID_LR", "RHEA_ID_RL", "RHEA_ID_BI")
RHEA_RDF_BASE = "http://rdf.rhea-db.org/"
RHEA_DIRECTION_FIELD = "rhea_direction"
RHEA_MASTER_FIELD = "rhea_master_id"
RHEA_STATUS_FIELD = "rhea_status"
DIRECTIONAL_REACTION = "rheav:directionalReaction"
BIDIRECTIONAL_REACTION = "rheav:bidirectionalReaction"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_NUMERIC_ID = re.compile(r"[1-9][0-9]*")
_ROLE_FIELDS = ("side", "substrates", "products", "substratesOrProducts")
_ACTIVE_STATUSES = ("Approved", "Preliminary")
_NATIVE_STATUSES = (*_ACTIVE_STATUSES, "Obsolete")


def _canonical_reaction_id(identifier):
    """Reject noncanonical identifiers before using reaction records as family evidence."""
    if not isinstance(identifier, str) or not identifier.startswith(RHEA_NEW_PREFIX):
        raise ValueError(f"Not a canonical Rhea reaction identifier: {identifier!r}")
    if not _NUMERIC_ID.fullmatch(identifier[len(RHEA_NEW_PREFIX) :]):
        raise ValueError(f"Not a canonical Rhea reaction identifier: {identifier!r}")


@dataclass(frozen=True)
class ReactionFamily:
    """Four distinct canonical IDs whose roles come from one directions-table row."""

    master: str
    lr: str
    rl: str
    bi: str

    def __post_init__(self):
        """Refuse malformed or repeated IDs even for callers constructing families directly."""
        identifiers = (self.master, self.lr, self.rl, self.bi)
        for identifier in identifiers:
            _canonical_reaction_id(identifier)
        if len(set(identifiers)) != 4:
            raise ValueError("A reaction family must contain four distinct identifiers")

    @property
    def members(self) -> tuple[tuple[str, str], ...]:
        """Return source directions; UN is unspecified, never neutral or bidirectional."""
        return ((self.master, "UN"), (self.lr, "LR"), (self.rl, "RL"), (self.bi, "BI"))

    def node_annotations(self, identifier: str) -> dict[str, str]:
        """Return exact family annotations for one member, without changing its identity."""
        for member, direction in self.members:
            if member == identifier:
                return {RHEA_DIRECTION_FIELD: direction, RHEA_MASTER_FIELD: self.master}
        raise ValueError(f"{identifier!r} is not a member of {self.master}")

    @property
    def links(self) -> tuple[tuple[str, str, str], ...]:
        """Expose native RDF family links, not synthetic hierarchy or identity assertions."""
        return (
            (self.master, DIRECTIONAL_REACTION, self.lr),
            (self.master, DIRECTIONAL_REACTION, self.rl),
            (self.master, BIDIRECTIONAL_REACTION, self.bi),
        )


def load_reaction_families(text_stream: TextIO) -> tuple[ReactionFamily, ...]:
    """Read the exact native TSV layout and validate all membership before returning."""
    reader = csv.reader(text_stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    if tuple(next(reader, ())) != DIRECTIONS_HEADER:
        raise ValueError("Expected the exact four-column Rhea directions header")
    families, seen = [], set()
    for row in reader:
        if len(row) != len(DIRECTIONS_HEADER):
            raise ValueError(f"Rhea directions line {reader.line_num}: expected four cells")
        if any(not _NUMERIC_ID.fullmatch(value) for value in row):
            raise ValueError(f"Rhea directions line {reader.line_num}: expected canonical numeric identifiers")
        family = ReactionFamily(*(RHEA_NEW_PREFIX + value for value in row))
        identifiers = {identifier for identifier, _ in family.members}
        overlap = seen.intersection(identifiers)
        if overlap:
            raise ValueError(f"Rhea directions line {reader.line_num}: repeated membership {sorted(overlap)}")
        seen.update(identifiers)
        families.append(family)
    if not families:
        raise ValueError("The Rhea directions table contains no reaction families")
    return tuple(families)


def _values(record: Mapping[str, Iterable[str]], predicate: str) -> frozenset[str]:
    """Validate and compare selected RDF values independently of duplicate serialization."""
    values = record.get(predicate, ())
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Iterable):
        raise ValueError(f"RDF evidence for {predicate} must be a collection of values")
    result = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"RDF evidence for {predicate} contains an invalid value")
        result.add(value)
    return frozenset(result)


def _expect(record, predicate, expected, identifier):
    """Require exact native evidence for one member's expected role or family links."""
    if _values(record, predicate) != frozenset(expected):
        raise ValueError(f"{identifier}: RDF evidence disagrees for {predicate}")


def _native_status(identifier, record, allowed=_NATIVE_STATUSES):
    """Return one explicitly supported status without promoting preliminary reactions."""
    if not isinstance(record, Mapping):
        raise ValueError(f"{identifier}: missing native RDF reaction record")
    statuses = _values(record, RHEA_RDF_BASE + "status")
    if len(statuses) != 1:
        raise ValueError(f"{identifier}: RDF evidence disagrees for native status (expected one value)")
    value = next(iter(statuses))
    for status in allowed:
        if value == RHEA_RDF_BASE + status:
            return status
    raise ValueError(f"{identifier}: RDF evidence disagrees for native status (unsupported {value!r})")


def validate_family_evidence(
    family: ReactionFamily,
    evidence: Mapping[str, Mapping[str, Iterable[str]]],
) -> None:
    """
    Require native RDF links, coherent active statuses, labels, and exact side roles.

    Reaction keys are canonical RHEA CURIEs. Predicate keys and object values
    are full native IRIs, while labels are literal strings. The caller must
    combine all RDF descriptions of each subject before invoking this check.
    RDF duplicate triples are set-equivalent. Unrelated properties are retained
    outside this finite check; no labels, sides, statuses or links are repaired.
    Master side names follow the explicit native ``<master>_L/_R`` convention,
    not the numerical spacing or iteration order of reaction identifiers.
    Approved and Preliminary are both active native states and must agree
    across all four members; neither status is converted or promoted.
    This does not validate participants, stoichiometry, or physiological flux.
    """
    if not isinstance(evidence, Mapping):
        raise ValueError("Native RDF evidence must be a mapping of reaction records")
    master_iri = RHEA_RDF_BASE + family.master[len(RHEA_NEW_PREFIX) :]
    left, right = master_iri + "_L", master_iri + "_R"
    expected_roles = {
        "UN": {"side": (left, right)},
        "LR": {"substrates": (left,), "products": (right,)},
        "RL": {"substrates": (right,), "products": (left,)},
        "BI": {"substratesOrProducts": (left, right)},
    }
    directional = tuple(RHEA_RDF_BASE + member[len(RHEA_NEW_PREFIX) :] for member in (family.lr, family.rl))
    bidirectional = (RHEA_RDF_BASE + family.bi[len(RHEA_NEW_PREFIX) :],)
    statuses = set()
    for identifier, direction in family.members:
        record = evidence.get(identifier)
        statuses.add(_native_status(identifier, record, _ACTIVE_STATUSES))
        labels = _values(record, RDFS_LABEL)
        if len(labels) != 1 or not next(iter(labels)).strip():
            raise ValueError(f"{identifier}: expected one nonblank native RDF label")
        _expect(record, RHEA_RDF_BASE + "directionalReaction", directional if direction == "UN" else (), identifier)
        _expect(record, RHEA_RDF_BASE + "bidirectionalReaction", bidirectional if direction == "UN" else (), identifier)
        for field in _ROLE_FIELDS:
            _expect(record, RHEA_RDF_BASE + field, expected_roles[direction].get(field, ()), identifier)
    if len(statuses) != 1:
        raise ValueError(f"{family.master}: RDF evidence disagrees across family statuses")


def validate_family_cohort(
    families: Iterable[ReactionFamily],
    evidence: Mapping[str, Mapping[str, Iterable[str]]],
) -> dict:
    """
    Require directions membership to equal all active native RDF reaction IDs.

    Only explicitly Obsolete records may lie outside the directions table;
    they need no labels or family structure and are returned for an upstream
    exclusion audit. Unknown, ambiguous, missing or mixed statuses fail.
    No native records are changed, and Preliminary is never called Approved.
    """
    if not isinstance(evidence, Mapping):
        raise ValueError("Native RDF evidence must be a mapping of reaction records")
    families = tuple(families)
    if not families:
        raise ValueError("The Rhea directions cohort contains no reaction families")
    members, family_status_counts = set(), dict.fromkeys(_ACTIVE_STATUSES, 0)
    for family in families:
        if not isinstance(family, ReactionFamily):
            raise ValueError("The Rhea directions cohort contains a non-family entry")
        current = {identifier for identifier, _ in family.members}
        if members.intersection(current):
            raise ValueError("The Rhea directions cohort contains repeated membership")
        validate_family_evidence(family, evidence)
        family_status_counts[_native_status(family.master, evidence[family.master])] += 1
        members.update(current)
    active, obsolete = set(), set()
    for identifier, record in evidence.items():
        _canonical_reaction_id(identifier)
        status = _native_status(identifier, record)
        (obsolete if status == "Obsolete" else active).add(identifier)
    if members != active:
        raise ValueError(
            "Rhea directions membership differs from the active native RDF cohort: "
            f"missing_from_table={sorted(active - members)}, nonactive_members={sorted(members - active)}"
        )
    return {
        "families": len(families),
        "members": len(members),
        "family_status_counts": family_status_counts,
        "obsolete_ids": tuple(sorted(obsolete)),
    }
