"""
Quarantine only individually reviewed, snapshot-bound crosswalk claims.

This is a finite source-quality disposition, never a taxonomy resolver or an
instruction to replace one taxid with another. Unknown claims retain their
existing emission behavior. A changed source or reviewed witness must receive
new review rather than silently bypassing the disposition.
"""

from __future__ import annotations

import base64
import binascii
import csv
import gzip
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, TextIO
from urllib.parse import urlsplit

from kg_microbe.transform_utils.constants import (
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    GOLD_PREFIX,
    KNOWLEDGE_ASSERTION,
    LPSN_PREFIX,
    MANUAL_AGENT,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    NCBITAXON_PREFIX,
)
from kg_microbe.transform_utils.microbedecoder.crosswalk_witnesses import (
    HistoricalTaxonomy,
    WitnessObjects,
    validate_witness,
)
from kg_microbe.transform_utils.microbedecoder.curation import TextInput, _read_input
from kg_microbe.transform_utils.microbedecoder.utils import crosswalk_curie, split_multivalue_comma_only

DEFAULT_CROSSWALK_QUARANTINE_POLICY = (
    Path(__file__).resolve().parents[3] / "mappings/canonical/microbedecoder_crosswalk_quarantine.json"
)
QUARANTINE_REPORT_FILENAME = "crosswalk_quarantine.tsv"
QUARANTINE_REPORT_FIELDS = (
    "rule_id",
    "witness_id",
    "source_record",
    "raw_record_sha256",
    "source_column",
    "source_cell_base64",
    "source_token",
    "subject",
    "object",
    "disposition",
    "original_claim_json",
    "original_claim_base64",
    "raw_record_json",
    "raw_record_base64",
    "evidence_uri",
    "rationale",
    "decisions_sha256",
    "evidence_sha256",
    "evidence_uncompressed_sha256",
    "evidence_uncompressed_bytes",
)
_SOURCE_COLUMNS = {"NCBI_Taxonomy_ID": NCBITAXON_PREFIX, "GOLD_Organism_ID": GOLD_PREFIX}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECORD = re.compile(r"sha256:([0-9a-f]{64})#record=([1-9][0-9]*)")
_LOCAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_DISPOSITION = "quarantine_authority_contradiction"
_MAX_EVIDENCE_BYTES = 256 * 1024 * 1024


def canonical_record_json(row: Mapping[str, Any]) -> str:
    """Preserve every raw field, including surrogate-escaped non-UTF8 bytes."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def crosswalk_raw_record_sha256(row: Mapping[str, Any]) -> str:
    """Use the explicitly reviewed crosswalk-record hash, not a chemical-row hash."""
    return hashlib.sha256(canonical_record_json(row).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"MicrobeDecoder crosswalk quarantine: {message}")


def _json(text: str) -> dict:
    def unique_pairs(items):
        """Reject duplicate JSON keys rather than silently accepting the last value."""
        value = {}
        for key, item in items:
            _require(key not in value, f"duplicate JSON key {key!r}")
            value[key] = item
        return value

    result = json.loads(text, object_pairs_hook=unique_pairs)
    _require(isinstance(result, dict), "JSON document must be an object")
    return result


def _text(source: TextInput) -> str:
    with _read_input(source) as stream:
        return stream.read()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _uri(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None


@dataclass(frozen=True)
class QuarantinePolicy:
    """Bind one complete source snapshot and its finite reviewed decisions."""

    version: int
    source_sha256: str
    source_records: int
    decisions_file: str
    decisions_sha256: str
    decisions_rows: int
    evidence_file: str
    evidence_sha256: str
    evidence_uncompressed_sha256: str | None = None
    evidence_uncompressed_bytes: int | None = None

    @classmethod
    def load(cls, source: TextInput) -> QuarantinePolicy:
        """Read a strict, hash-bound policy without any default permissive route."""
        data = _json(_text(source))
        optional = {"evidence_uncompressed_sha256", "evidence_uncompressed_bytes"}
        mandatory = {field.name for field in fields(cls)} - optional
        _require(mandatory <= set(data) and set(data) <= mandatory | optional, "invalid policy fields")
        _require(type(data["version"]) is int and data["version"] == 1, "unsupported policy version")
        for field in ("source_sha256", "decisions_sha256", "evidence_sha256"):
            _require(_digest(data[field]), f"invalid {field}")
        for field in ("source_records", "decisions_rows"):
            _require(type(data[field]) is int and data[field] >= 0, f"invalid {field}")
        for field in ("decisions_file", "evidence_file"):
            value = data[field]
            _require(
                isinstance(value, str)
                and _LOCAL_ID.fullmatch(value) is not None
                and Path(value).name == value
                and value not in {".", ".."},
                f"unsafe {field}",
            )
        _require(data["decisions_file"] != data["evidence_file"], "decision/evidence filenames collide")
        if data["evidence_file"].endswith(".gz") or optional & set(data):
            _require(optional <= set(data), "compressed evidence requires decoded byte/hash pins")
            _require(_digest(data["evidence_uncompressed_sha256"]), "invalid decoded evidence hash")
            size = data["evidence_uncompressed_bytes"]
            _require(type(size) is int and 0 < size <= _MAX_EVIDENCE_BYTES, "invalid/excessive decoded evidence length")
        return cls(**data)


def _evidence_text(source: TextInput, policy: QuarantinePolicy) -> str:
    # Read the consumed snapshot's binary buffer before any text read. The
    # compressed file is itself the immutable consumed input, not a live path.
    if policy.evidence_file.endswith(".gz"):
        with _read_input(source) as stream:
            _require(hasattr(stream, "buffer"), "compressed evidence needs a binary-backed snapshot")
            stream.seek(0)
            raw = stream.buffer.read(_MAX_EVIDENCE_BYTES + 1)
        _require(len(raw) <= _MAX_EVIDENCE_BYTES, "compressed evidence exceeds safety bound")
        _require(hashlib.sha256(raw).hexdigest() == policy.evidence_sha256, "witness bytes differ from policy")
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
            decoded = compressed.read(policy.evidence_uncompressed_bytes + 1)
        _require(len(decoded) == policy.evidence_uncompressed_bytes, "decoded evidence length differs from policy")
        _require(
            hashlib.sha256(decoded).hexdigest() == policy.evidence_uncompressed_sha256,
            "decoded evidence hash differs from policy",
        )
        return decoded.decode("utf-8")
    text = _text(source)
    raw = text.encode("utf-8")
    _require(len(raw) <= _MAX_EVIDENCE_BYTES, "evidence exceeds safety bound")
    _require(hashlib.sha256(raw).hexdigest() == policy.evidence_sha256, "witness bytes differ from policy")
    if policy.evidence_uncompressed_sha256 is not None:
        _require(
            len(raw) == policy.evidence_uncompressed_bytes
            and hashlib.sha256(raw).hexdigest() == policy.evidence_uncompressed_sha256,
            "decoded evidence pins differ",
        )
    return text


@dataclass(frozen=True)
class CrosswalkDecision:
    """One rejected original crosswalk assertion, without a replacement identity."""

    rule_id: str
    source_record: str
    raw_record_sha256: str
    raw_lpsn_id: str
    subject: str
    source_column: str
    source_cell_base64: str
    source_token: str
    object: str
    predicate: str
    relation: str
    primary_knowledge_source: str
    knowledge_level: str
    agent_type: str
    disposition: str
    witness_id: str
    rationale: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Identify a literal claim by record, original field and unsplit token."""
        return self.source_record, self.source_column, self.source_token


class CrosswalkQuarantine:
    """Validate reviewed policy, preflight exact raw evidence, then suppress only matched claims."""

    def __init__(self, policy: QuarantinePolicy, decisions_input: TextInput, evidence_input: TextInput) -> None:
        """Require consistent immutable decisions and reviewed witness bytes."""
        self.policy = policy
        decisions_text, evidence_text = _text(decisions_input), _evidence_text(evidence_input, policy)
        self._evidence_uncompressed_bytes = len(evidence_text.encode("utf-8"))
        _require(
            hashlib.sha256(decisions_text.encode("utf-8")).hexdigest() == policy.decisions_sha256,
            "decision-table bytes differ from policy",
        )
        reader = csv.DictReader(io.StringIO(decisions_text, newline=""), delimiter="\t", quoting=csv.QUOTE_NONE)
        expected_fields = {field.name for field in fields(CrosswalkDecision)}
        _require(
            reader.fieldnames is not None
            and len(reader.fieldnames) == len(expected_fields)
            and set(reader.fieldnames) == expected_fields,
            "missing/duplicate decision columns",
        )
        self._rules, rule_ids = {}, set()
        self._by_record = defaultdict(list)
        for row in reader:
            _require(
                None not in row
                and all(
                    isinstance(value, str)
                    and value
                    and value == value.strip()
                    and not any(ord(char) < 32 for char in value)
                    for value in row.values()
                ),
                "malformed/incomplete decision row",
            )
            rule = CrosswalkDecision(**row)
            record = _RECORD.fullmatch(rule.source_record)
            _require(
                record is not None and record.group(1) == policy.source_sha256,
                "decision refers to another raw snapshot",
            )
            _require(int(record.group(2)) <= policy.source_records, "decision ordinal outside source")
            _require(_digest(rule.raw_record_sha256), "invalid complete raw-record hash")
            _require(
                _LOCAL_ID.fullmatch(rule.rule_id) is not None and _LOCAL_ID.fullmatch(rule.witness_id) is not None,
                "invalid decision/witness ID",
            )
            _require(rule.rule_id not in rule_ids and rule.key not in self._rules, "duplicate/conflicting decision")
            _require(
                re.fullmatch(r"[1-9][0-9]*", rule.raw_lpsn_id) is not None
                and re.fullmatch(re.escape(LPSN_PREFIX) + r"[1-9][0-9]*", rule.subject) is not None,
                "invalid raw/effective LPSN identity",
            )
            _require(rule.source_column in _SOURCE_COLUMNS, "unreviewed source namespace")
            expected_object = crosswalk_curie(rule.source_token, _SOURCE_COLUMNS[rule.source_column])
            target_pattern = r"NCBITaxon:[1-9][0-9]*" if rule.source_column == "NCBI_Taxonomy_ID" else r"gold:Go[0-9]+"
            _require(
                rule.object == expected_object and re.fullmatch(target_pattern, rule.object) is not None,
                "decision does not bind original pre-fold target",
            )
            _require(
                (rule.predicate, rule.relation, rule.primary_knowledge_source, rule.knowledge_level, rule.agent_type)
                == (
                    CLOSE_MATCH_PREDICATE,
                    CLOSE_MATCH_RELATION,
                    MICROBEDECODER_KNOWLEDGE_SOURCE,
                    KNOWLEDGE_ASSERTION,
                    MANUAL_AGENT,
                ),
                "unreviewed scientific route/provenance",
            )
            _require(rule.disposition == _DISPOSITION, "unsupported quarantine disposition")
            try:
                cell_bytes = base64.b64decode(rule.source_cell_base64, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError("MicrobeDecoder crosswalk quarantine: invalid source cell base64") from error
            _require(
                base64.b64encode(cell_bytes).decode("ascii") == rule.source_cell_base64,
                "noncanonical source cell base64",
            )
            cell = cell_bytes.decode("utf-8", errors="surrogateescape")
            _require(
                split_multivalue_comma_only(cell).count(rule.source_token) == 1,
                "reviewed token must occur exactly once in the complete source cell",
            )
            self._rules[rule.key] = rule
            rule_ids.add(rule.rule_id)
            self._by_record[rule.source_record].append(rule)
        _require(len(self._rules) == policy.decisions_rows, "decision count differs from policy")
        evidence = _json(evidence_text)
        _require(
            {"version", "source_sha256", "authorities", "witnesses", "objects"} <= set(evidence)
            and type(evidence["version"]) is int
            and evidence["version"] == 1
            and evidence["source_sha256"] == policy.source_sha256,
            "invalid witness envelope",
        )
        authorities, witnesses = evidence["authorities"], evidence["witnesses"]
        _require(isinstance(authorities, dict) and isinstance(witnesses, dict), "invalid authority/witness collection")
        _require(bool(authorities) or not self._rules, "quarantines require independently reviewed authority witnesses")
        for authority in authorities.values():
            _require(
                isinstance(authority, dict)
                and isinstance(authority.get("path_or_uri"), str)
                and bool(authority["path_or_uri"])
                and _digest(authority.get("sha256")),
                "malformed pinned authority evidence",
            )
        _require(set(witnesses) == {rule.witness_id for rule in self._rules.values()}, "missing/unconsumed witness IDs")
        objects = WitnessObjects(evidence["objects"])
        taxonomy = HistoricalTaxonomy(evidence) if self._rules else None
        expanded_witnesses = {}
        for rule in self._rules.values():
            witness = objects.expand(witnesses[rule.witness_id])
            _require(
                isinstance(witness, dict)
                and witness.get("classification") == "authority_contradiction"
                and _uri(witness.get("evidence_uri")),
                "unreviewed or malformed contradiction witness",
            )
            for field in ("source_record", "source_column", "source_token", "object", "subject"):
                _require(witness.get(field) == getattr(rule, field), f"witness binding differs: {field}")
            validate_witness(witness, rule, taxonomy)
            expanded_witnesses[rule.witness_id] = witness
        self._witnesses = expanded_witnesses
        self._preflight_done = False
        self._used = set()

    def _validate_record(self, source_record: str, row: Mapping[str, Any], subject: str) -> None:
        rules = self._by_record.get(source_record, ())
        if not rules:
            return
        actual_hash = crosswalk_raw_record_sha256(row)
        for rule in rules:
            _require(
                actual_hash == rule.raw_record_sha256
                and row.get("LPSN_ID") == rule.raw_lpsn_id
                and subject == rule.subject,
                "reviewed complete record or effective LPSN subject changed",
            )
            value = row.get(rule.source_column)
            _require(
                isinstance(value, str)
                and base64.b64encode(value.encode("utf-8", errors="surrogateescape")).decode("ascii")
                == rule.source_cell_base64,
                "reviewed complete source field changed",
            )
            bacdive = self._witnesses[rule.witness_id]["context"]["bacdive_support"]["record"]["General"]
            _require(
                row.get("BacDive_ID") == str(bacdive.get("BacDive-ID")),
                "raw BacDive record differs from reviewed independent support",
            )

    def preflight(self, stream: TextIO, source_sha256: str, accepted_lpsn: Mapping[str, str]) -> None:
        """Check the full immutable raw snapshot before any graph output is opened."""
        self._preflight_done = False
        self._used.clear()
        _require(source_sha256 == self.policy.source_sha256, "raw source snapshot requires a newly reviewed policy")
        stream.seek(0)
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        required = {"LPSN_ID", *[rule.source_column for rule in self._rules.values()]}
        _require(
            header and len(header) == len(set(header)) and all(header) and required <= set(header),
            "missing/duplicate raw CSV header",
        )
        seen, count = set(), 0
        for count, row in enumerate(reader, start=1):
            _require(None not in row and all(isinstance(value, str) for value in row.values()), "ragged raw CSV row")
            source_record = f"sha256:{source_sha256}#record={count}"
            raw_lpsn = row["LPSN_ID"].strip()
            subject = LPSN_PREFIX + accepted_lpsn.get(raw_lpsn, raw_lpsn)
            self._validate_record(source_record, row, subject)
            if source_record in self._by_record:
                seen.add(source_record)
        _require(
            count == self.policy.source_records and seen == set(self._by_record),
            "missing reviewed records or unexpected source record count",
        )
        stream.seek(0)
        self._preflight_done = True

    def match(
        self,
        source_record: str,
        row: Mapping[str, Any],
        subject: str,
        source_column: str,
        token: str,
        original_object: str,
    ) -> CrosswalkDecision | None:
        """Return only the exact reviewed pre-fold claim, never another field or target."""
        _require(self._preflight_done, "raw preflight is required before crosswalk dispatch")
        self._validate_record(source_record, row, subject)
        rule = self._rules.get((source_record, source_column, token))
        if rule is None:
            return None
        _require(original_object == rule.object and subject == rule.subject, "original claim differs from review")
        _require(rule.rule_id not in self._used, "duplicate quarantine dispatch")
        self._used.add(rule.rule_id)
        return rule

    def require_complete(self) -> None:
        """Missing emission calls must not publish a partially applied reviewed policy."""
        _require(
            self._preflight_done and self._used == {rule.rule_id for rule in self._rules.values()},
            "reviewed quarantine decisions were not all dispatched",
        )

    def audit_row(
        self, rule: CrosswalkDecision, raw_row: Mapping[str, Any], claim: Mapping[str, Any]
    ) -> dict[str, str]:
        """Retain the entire rejected original edge and raw record reversibly, outside the KG."""
        claim_json, raw_json = canonical_record_json(claim), canonical_record_json(raw_row)
        for field in (
            "subject",
            "object",
            "predicate",
            "relation",
            "primary_knowledge_source",
            "knowledge_level",
            "agent_type",
        ):
            _require(claim.get(field) == getattr(rule, field), f"audited original claim differs: {field}")
        _require(claim.get("source_record") == rule.source_record, "audited source record differs")
        _require(crosswalk_raw_record_sha256(raw_row) == rule.raw_record_sha256, "audited raw evidence differs")
        return {
            "rule_id": rule.rule_id,
            "witness_id": rule.witness_id,
            "source_record": rule.source_record,
            "raw_record_sha256": rule.raw_record_sha256,
            "source_column": rule.source_column,
            "source_cell_base64": rule.source_cell_base64,
            "source_token": rule.source_token,
            "subject": rule.subject,
            "object": rule.object,
            "disposition": rule.disposition,
            "original_claim_json": claim_json,
            "original_claim_base64": base64.b64encode(claim_json.encode()).decode(),
            "raw_record_json": raw_json,
            "raw_record_base64": base64.b64encode(raw_json.encode()).decode(),
            "evidence_uri": self._witnesses[rule.witness_id]["evidence_uri"],
            "rationale": rule.rationale,
            "decisions_sha256": self.policy.decisions_sha256,
            "evidence_sha256": self.policy.evidence_sha256,
            "evidence_uncompressed_sha256": self.policy.evidence_uncompressed_sha256 or self.policy.evidence_sha256,
            "evidence_uncompressed_bytes": str(
                self.policy.evidence_uncompressed_bytes or self._evidence_uncompressed_bytes
            ),
        }
