"""
Describe a finite reviewed material cohort without resolving chemical identity.

This catalogue is inventory metadata, never a producer dependency or an alias
table. Source records, existing graph endpoints, citations and evidence tiers
are matched exactly. Closed-cohort checks are explicit diagnostic operations.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from kg_microbe.transform_utils.constants import (
    BERGEY_KNOWLEDGE_SOURCE,
    COMPOUND_PREFIX,
    HAS_OUTPUT_RELATION,
    KNOWLEDGE_ASSERTION,
    LITERATURE_KNOWLEDGE_SOURCE,
    LPSN_PREFIX,
    MANUAL_AGENT,
    NCBI_TO_SUBSTRATE_EDGE,
    PRODUCES_PREDICATE,
    TROPHICALLY_INTERACTS_WITH,
)
from kg_microbe.transform_utils.microbedecoder.chemical_curation import canonical_raw_row_sha256
from kg_microbe.transform_utils.microbedecoder.curation import TextInput, _read_input
from kg_microbe.transform_utils.microbedecoder.utils import METABOLISM_GROUPS, split_multivalue

DEFAULT_MATERIAL_DISPOSITIONS = (
    Path(__file__).resolve().parents[3] / "mappings" / "canonical" / "microbedecoder_material_dispositions.tsv"
)
_SOURCE_RECORD = re.compile(r"sha256:([0-9a-f]{64})#record=([1-9][0-9]*)")
_GROUP_PROVIDERS = {"bergey": BERGEY_KNOWLEDGE_SOURCE, "literature": LITERATURE_KNOWLEDGE_SOURCE}
_MATERIAL_COLUMNS = {
    column: (role, group["columns"]["citation"], _GROUP_PROVIDERS[group["group_label"]])
    for group in METABOLISM_GROUPS
    if group["group_label"] in _GROUP_PROVIDERS
    for role, column in group["columns"].items()
    if role in {"substrates", "major_end_products", "minor_end_products"}
}
_DISPOSITIONS = frozenset(
    {
        "unresolved_product_identity",
        "reported_combined_culture_context",
        "reported_joint_substrate_condition",
        "reported_culture_medium",
        "reviewed_source_culture_medium",
        "unresolved_substrate_identity_taxon_caveat",
        "reported_substrate_class_group",
        "reported_undefined_protein_digest",
        "approved_record_scoped_unresolved",
        "reported_substrate_class_plural",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _escape_literal(value: str) -> str:
    """Match the producer's display encoding without changing the raw-record hash."""
    value = value.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


@dataclass(frozen=True)
class MaterialDisposition:
    """One original source use, its unchanged graph witness and unresolved identity."""

    source_record: str
    raw_record_sha256: str
    subject: str
    source_column: str
    source_literal: str
    source_citation: str
    object_curie: str
    predicate: str
    relation: str
    primary_knowledge_source: str
    knowledge_level: str
    agent_type: str
    value_encoding: str
    disposition: str
    identity_status: str
    identity_approved: str
    evidence_uri: str
    curation_rationale: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Identify an exact record/field/token, not a global chemical name."""
        return self.source_record, self.source_column, self.source_literal


class MaterialDispositionCuration:
    """Load exact finite review metadata; never mint or redirect graph identities."""

    def __init__(self, mapping_input: TextInput = DEFAULT_MATERIAL_DISPOSITIONS) -> None:
        """Validate the supplied table anew, retaining caller-owned input streams."""
        self._rules = self._load_rules(mapping_input)
        snapshots = {_SOURCE_RECORD.fullmatch(rule.source_record).group(1) for rule in self.rules}
        if len(snapshots) != 1:
            raise ValueError("Material dispositions must bind one reviewed source snapshot")
        self.source_sha256 = snapshots.pop()

    @property
    def rules(self) -> tuple[MaterialDisposition, ...]:
        """Expose immutable declarations for complete-cohort diagnostics."""
        return tuple(self._rules.values())

    def resolve_edge(self, edge: Mapping[str, str]) -> MaterialDisposition | None:
        """Describe a known use, rejecting changed evidence; leave unseen uses unreviewed."""
        key = (edge.get("source_record", ""), edge.get("source_column", ""), edge.get("value", ""))
        rule = self._rules.get(key)
        if rule is None:
            return None
        expected = {
            "subject": rule.subject,
            "object": rule.object_curie,
            "source_citation": rule.source_citation,
            "predicate": rule.predicate,
            "relation": rule.relation,
            "primary_knowledge_source": rule.primary_knowledge_source,
            "knowledge_level": rule.knowledge_level,
            "agent_type": rule.agent_type,
            "value_encoding": rule.value_encoding,
        }
        if any(edge.get(name) != value for name, value in expected.items()):
            raise ValueError(f"Reviewed material source-use evidence changed: {key!r}")
        return rule

    @staticmethod
    def _load_rules(mapping_input: TextInput) -> dict[tuple[str, str, str], MaterialDisposition]:
        expected_fields = {field.name for field in fields(MaterialDisposition)}
        rules, raw_hashes = {}, {}
        with _read_input(mapping_input) as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            if len(header) != len(expected_fields) or set(header) != expected_fields:
                raise ValueError("Invalid MicrobeDecoder material disposition columns")
            for line, row in enumerate(reader, start=2):
                if None in row or any(
                    value is None or not value or value != value.strip() or any(ord(char) < 32 for char in value)
                    for value in row.values()
                ):
                    raise ValueError(f"Malformed material disposition at line {line}")
                rule = MaterialDisposition(**row)
                if not _SOURCE_RECORD.fullmatch(rule.source_record) or not re.fullmatch(
                    r"[0-9a-f]{64}", rule.raw_record_sha256
                ):
                    raise ValueError(f"Invalid material source fingerprint at line {line}")
                if not re.fullmatch(re.escape(LPSN_PREFIX) + r"[1-9][0-9]*", rule.subject):
                    raise ValueError(f"Invalid material subject at line {line}")
                if not re.fullmatch(re.escape(COMPOUND_PREFIX) + r"[a-z0-9_]+", rule.object_curie):
                    raise ValueError(f"Material review cannot grant an external chemical identity at line {line}")
                if rule.source_column not in _MATERIAL_COLUMNS:
                    raise ValueError(f"Invalid material source column at line {line}")
                role, _, provider = _MATERIAL_COLUMNS[rule.source_column]
                expected_route = (
                    (NCBI_TO_SUBSTRATE_EDGE, TROPHICALLY_INTERACTS_WITH)
                    if role == "substrates"
                    else (PRODUCES_PREDICATE, HAS_OUTPUT_RELATION)
                )
                if (rule.predicate, rule.relation) != expected_route or (
                    rule.primary_knowledge_source,
                    rule.knowledge_level,
                    rule.agent_type,
                    rule.value_encoding,
                ) != (provider, KNOWLEDGE_ASSERTION, MANUAL_AGENT, "backslash"):
                    raise ValueError(f"Invalid material scientific role or provenance at line {line}")
                if rule.identity_status != "unresolved" or rule.identity_approved != "false":
                    raise ValueError(f"Material disposition cannot approve chemical identity at line {line}")
                if rule.disposition not in _DISPOSITIONS:
                    raise ValueError(f"Unreviewed material disposition at line {line}")
                for uri in rule.evidence_uri.split("|"):
                    parsed = urlsplit(uri)
                    if (
                        parsed.scheme != "https"
                        or not parsed.hostname
                        or parsed.username is not None
                        or parsed.password is not None
                        or any(char.isspace() for char in uri)
                    ):
                        raise ValueError(f"Invalid material evidence URI at line {line}")
                if rule.key in rules:
                    raise ValueError(f"Duplicate or conflicting material source use at line {line}")
                if raw_hashes.setdefault(rule.source_record, rule.raw_record_sha256) != rule.raw_record_sha256:
                    raise ValueError(f"Conflicting complete material raw-record hashes at line {line}")
                rules[rule.key] = rule
        if not rules:
            raise ValueError("No MicrobeDecoder material dispositions")
        return rules

    def validate_raw(self, raw_path: Path) -> dict:
        """Explicitly verify the full reviewed records against an unchanged raw snapshot."""
        before = _sha256(raw_path)
        if before != self.source_sha256:
            raise ValueError("Raw material source snapshot is not the reviewed snapshot")
        by_ordinal = defaultdict(list)
        for rule in self.rules:
            by_ordinal[int(_SOURCE_RECORD.fullmatch(rule.source_record).group(2))].append(rule)
        seen = set()
        with raw_path.open(encoding="utf-8", errors="surrogateescape", newline="") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames or []
            required = {rule.source_column for rule in self.rules} | {
                _MATERIAL_COLUMNS[rule.source_column][1] for rule in self.rules
            }
            if len(header) != len(set(header)) or not required.issubset(header):
                raise ValueError("Missing or duplicate reviewed material raw fields")
            for ordinal, row in enumerate(reader, start=1):
                if ordinal not in by_ordinal:
                    continue
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Malformed reviewed material raw record")
                for rule in by_ordinal[ordinal]:
                    citation_column = _MATERIAL_COLUMNS[rule.source_column][1]
                    if (
                        canonical_raw_row_sha256(row) != rule.raw_record_sha256
                        or rule.source_literal
                        not in [_escape_literal(x) for x in split_multivalue(row[rule.source_column])]
                        or _escape_literal(row[citation_column]) != rule.source_citation
                    ):
                        raise ValueError(f"Reviewed complete material raw record changed: {rule.key!r}")
                seen.add(ordinal)
        if seen != set(by_ordinal) or _sha256(raw_path) != before:
            raise ValueError("Missing or changed reviewed material source records")
        return {"source_sha256": before, "raw_records": len(seen), "reviewed_uses": len(self._rules)}

    def validate_edges(self, edges_path: Path, *, require_all: bool = True) -> dict:
        """Stream an explicit cohort diagnostic without making it a transform dependency."""
        before, seen, snapshot_seen = _sha256(edges_path), set(), False
        required = {
            "source_record",
            "source_column",
            "value",
            "source_citation",
            "subject",
            "object",
            "predicate",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
            "value_encoding",
        }
        with edges_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = reader.fieldnames or []
            if len(header) != len(set(header)) or not required.issubset(header):
                raise ValueError("Missing or duplicate material edge fields")
            for edge in reader:
                if None in edge or any(value is None for value in edge.values()):
                    raise ValueError("Malformed material edge row")
                snapshot_seen |= edge["source_record"].startswith(f"sha256:{self.source_sha256}#record=")
                rule = self.resolve_edge(edge)
                if rule is None:
                    continue
                if rule.key in seen:
                    raise ValueError(f"Duplicate reviewed material source assertion: {rule.key!r}")
                seen.add(rule.key)
        if _sha256(edges_path) != before:
            raise ValueError("Material edge input changed during validation")
        missing = set(self._rules) - seen
        if require_all and missing:
            raise ValueError(f"Incomplete reviewed material cohort: {len(missing)} source uses missing")
        return {
            "edges_sha256": before,
            "reviewed_material_assertions": len(seen),
            "reviewed_material_records": len({key[0] for key in seen}),
            "reviewed_material_ids": len({self._rules[key].object_curie for key in seen}),
            "missing_reviewed_uses": len(missing),
            "cohort_complete": not missing,
            "source_snapshot_seen": snapshot_seen,
        }
