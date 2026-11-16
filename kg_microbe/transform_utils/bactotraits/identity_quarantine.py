"""Withhold only reviewed BactoTraits rows with incompatible strain identities."""

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

POLICY_PATH = "mappings/canonical/bactotraits_identity_quarantine.json"
DEFAULT_POLICY = Path(__file__).resolve().parents[3] / POLICY_PATH
AUDIT_FILE = "bactotraits_identity_quarantine.tsv"
POLICY_ROLE = "bactotraits_identity_policy"
SOURCE_ROLE = "bactotraits_source"
AUDIT_FIELDS = (
    "rule_id",
    "source_data_row",
    "reviewed_source_data_row",
    "bacdive_id",
    "ncbitaxon_id",
    "full_name",
    "culture_collection_codes",
    "disposition",
    "row_sha256",
    "source_sha256",
    "reviewed_source_sha256",
    "policy_sha256",
    "evidence_urls",
    "rationale",
    "raw_row_json",
)
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_DECISION_FIELDS = {
    "rule_id",
    "reviewed_source_data_row",
    "bacdive_id",
    "ncbitaxon_id",
    "full_name",
    "culture_collection_codes",
    "disposition",
    "row_sha256",
    "evidence_urls",
    "rationale",
}


def _require(condition, message):
    if not condition:
        raise ValueError("BactoTraits identity quarantine: " + message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate policy JSON key")
        result[key] = value
    return result


def raw_row_sha256(row):
    """Replay EdgeMech's complete Latin-1-decoded source-record-json-canonical/v1 row."""
    text = json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IdentityQuarantine:
    """Validate a finite policy and identify its exact rows before graph emission."""

    def __init__(self, policy_text):
        """Reject malformed, duplicate or permissive policy declarations."""
        data = json.loads(policy_text, object_pairs_hook=_unique_pairs)
        _require(
            isinstance(data, dict)
            and set(data)
            == {
                "format",
                "reviewed_source_sha256",
                "decisions",
            },
            "invalid policy fields",
        )
        _require(data["format"] == "kg-microbe-bactotraits-quarantine/v1", "unsupported policy format")
        _require(_sha(data["reviewed_source_sha256"]), "invalid reviewed source digest")
        decisions = data["decisions"]
        _require(isinstance(decisions, list), "decisions must be a list")
        self.decisions = {}
        rules, ordinals = set(), set()
        for decision in decisions:
            _require(isinstance(decision, dict) and set(decision) == _DECISION_FIELDS, "invalid decision fields")
            bid = decision["bacdive_id"]
            _require(isinstance(bid, str) and re.fullmatch(r"[1-9][0-9]*", bid), "invalid BacDive selector")
            _require(bid not in self.decisions, "duplicate BacDive selector")
            rule = decision["rule_id"]
            _require(isinstance(rule, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", rule), "invalid rule ID")
            _require(rule not in rules, "duplicate rule ID")
            ordinal = decision["reviewed_source_data_row"]
            _require(type(ordinal) is int and ordinal > 0 and ordinal not in ordinals, "invalid reviewed row ordinal")
            _require(_sha(decision["row_sha256"]), "invalid reviewed row digest")
            taxon = decision["ncbitaxon_id"]
            _require(isinstance(taxon, str) and re.fullmatch(r"NCBITaxon:[1-9][0-9]*", taxon), "invalid original taxon")
            _require(
                all(_text(decision[key]) for key in ("full_name", "culture_collection_codes", "rationale")),
                "empty reviewed identity or rationale",
            )
            _require(decision["disposition"] == "quarantine_mixed_strain_row", "invalid disposition")
            urls = decision["evidence_urls"]
            _require(isinstance(urls, list) and urls and all(_text(url) for url in urls), "missing evidence URLs")
            for url in urls:
                parsed = urlsplit(url)
                _require(
                    parsed.scheme == "https"
                    and parsed.hostname
                    and parsed.username is None
                    and parsed.password is None
                    and not any(c.isspace() for c in url),
                    "invalid evidence URL",
                )
            _require(len(set(urls)) == len(urls), "duplicate evidence URL")
            self.decisions[bid] = decision
            rules.add(rule)
            ordinals.add(ordinal)
        self.reviewed_source_sha256 = data["reviewed_source_sha256"]
        self.policy_sha256 = hashlib.sha256(policy_text.encode("utf-8")).hexdigest()
        self.rows = None

    def preflight(self, raw):
        """Find each reviewed row exactly once; an altered or absent row needs new review."""
        _require(len(raw) <= MAX_SOURCE_BYTES, "source exceeds bounded input size")
        self.rows = None
        reader = csv.reader(io.StringIO(raw.decode("ISO-8859-1"), newline=""), delimiter=";")
        next(reader, None)
        next(reader, None)
        header = next(reader, None)
        _require(
            header and len(header) == len(set(header)) and "Bacdive_ID" in header, "missing or duplicate source header"
        )
        bid_column = header.index("Bacdive_ID")
        _require(bid_column == 1, "BacDive selector is not in the transform's declared column")
        matches, rows = set(), {}
        source_sha256 = hashlib.sha256(raw).hexdigest()
        for ordinal, values in enumerate(reader, 1):
            if len(values) <= bid_column:
                continue
            bid = values[bid_column]
            if bid not in self.decisions:
                continue
            _require(bid not in matches, "duplicate reviewed source selector")
            _require(len(values) == len(header), "reviewed source row has malformed field count")
            decision = self.decisions[bid]
            row = dict(zip(header, values, strict=True))
            _require(raw_row_sha256(row) == decision["row_sha256"], "reviewed source row changed")
            _require(
                row.get("Full_name") == decision["full_name"]
                and row.get("culture collection codes") == decision["culture_collection_codes"],
                "reviewed identity fields differ",
            )
            rows[ordinal] = {
                **decision,
                "source_data_row": ordinal,
                "source_sha256": source_sha256,
                "reviewed_source_sha256": self.reviewed_source_sha256,
                "policy_sha256": self.policy_sha256,
                "evidence_urls": "|".join(decision["evidence_urls"]),
                "raw_row_json": json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            }
            matches.add(bid)
        _require(matches == set(self.decisions), "reviewed source selector missing")
        self.rows = rows

    def verify_lookup(self, lookup):
        """Do not silently reinterpret the reviewed row after its mapped taxon changes."""
        _require(self.rows is not None, "source preflight is required")
        for decision in self.decisions.values():
            _require(
                lookup.get("bacdive:" + decision["bacdive_id"]) == decision["ncbitaxon_id"],
                "reviewed BacDive-to-taxon mapping changed or is missing",
            )

    def write_audit(self, stream):
        """Preserve original source identities and raw rows, including an empty audit header."""
        _require(self.rows is not None, "source preflight is required")
        writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows.values())
