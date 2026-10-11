"""
Refuse six reviewed joins and retain their snapshots on unresolved source records.

Only the approved finite snapshot subjects move; literals, attribute objects,
source context and independent metabolism/FAPROTAX observations remain intact.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    ID_COLUMN,
    INFORMATION_CONTENT_ENTITY_CATEGORY,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    LPSN_PREFIX,
    MANUAL_AGENT,
    MICROBEDECODER,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SOURCE_ATTRIBUTE_PREFIX,
    SOURCE_COLUMN,
    SOURCE_RECORD_COLUMN,
    SOURCE_RECORD_PREFIX,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    VALUE_COLUMN,
    VALUE_ENCODING_COLUMN,
)
from kg_microbe.transform_utils.microbedecoder.utils import (
    BACDIVE_CROSSWALK_COLUMN,
    BACDIVE_SNAPSHOT_COLUMNS,
    LPSN_ID_COLUMN,
    crosswalk_curie,
    is_empty_cell,
    slugify_label,
    split_multivalue_comma_only,
    split_snapshot_values,
)
from kg_microbe.utils.lpsn_utils import resolve_accepted_records
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

DEFAULT_POLICY = (
    Path(__file__).resolve().parents[3] / "mappings/canonical/microbedecoder_bacdive_join_dispositions.json"
)
POLICY_SHA256 = "30eaf4f30095a70e47a416763f3782dff963b8fabaacfcd3607eee11c28c1bb0"
EVIDENCE_SHA256 = "919a2c85ace14d93e630b264c37638920fec9a3c80e9e0d64f866601a4324516"
DECISIONS_SHA256 = "70a4563e13d1c456423cd4abdbce29d9f57c9916ebd0ebcf11e00ddf3140e42b"
CONTRACT_KEY = "bacdive_join_dispositions"
AUDIT_FILE = "bacdive_join_dispositions.tsv"
ROLE_POLICY = "bacdive_join_policy"
ROLE_EVIDENCE = "bacdive_join_evidence"
ROLE_GSS = "bacdive_join_lpsn_gss"
ROLE_RAW = "crosswalk_raw"
REQUIRED_INPUTS = (ROLE_POLICY, ROLE_EVIDENCE, ROLE_GSS, ROLE_RAW)
AUDIT_FIELDS = (
    "source_record",
    "source_column",
    "source_cell_json",
    "source_token_json",
    "native_record_json",
    "original_claim_json",
    "emitted_claim_json",
    "witness_json",
    "policy_sha256",
    "evidence_sha256",
    "disposition",
    "snapshot_disposition",
    "snapshot_node_json",
    "snapshot_original_claims_json",
    "snapshot_emitted_claims_json",
)
_DISPOSITION = "quarantine_contradicted_record_join"
SNAPSHOT_DISPOSITION = "retain_on_record_scoped_source_node_without_taxon_identity"
_RECORD_PREFIX = SOURCE_RECORD_PREFIX + "microbedecoder_bacdive_"
_SCOPE = "finite_link_refusals_and_record_scoped_snapshot_observations"
_STRAIN = f"{STRAIN_PREFIX}bacdive_"
_CORE = {
    PREDICATE_COLUMN: SUBCLASS_PREDICATE,
    RELATION_COLUMN: RDFS_SUBCLASS_OF,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN: MICROBEDECODER_KNOWLEDGE_SOURCE,
    KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
    AGENT_TYPE_COLUMN: MANUAL_AGENT,
}


def _fail(message):
    """Refuse incomplete scientific or actual-read evidence."""
    raise SourceFinalizationRequired("MicrobeDecoder BacDive join: " + message)


def _json(value):
    """Keep every original decoded value, including non-UTF8 source byte surrogates."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(payload):
    """Hash literal bytes, not a filesystem filename or receipt's self-claim."""
    return hashlib.sha256(payload).hexdigest()


def _parsed(payload):
    """Reject contradictory duplicate keys at every witness/policy nesting level."""

    def unique(pairs):
        """Reject repeated JSON object keys instead of accepting a last value."""
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=unique)


def _rows(stream, required):
    """Validate complete headers/row widths before a native record becomes evidence."""
    reader = csv.DictReader(stream)
    if (
        reader.fieldnames is None
        or len(set(reader.fieldnames)) != len(reader.fieldnames)
        or not set(required) <= set(reader.fieldnames)
    ):
        _fail("missing or duplicate native columns")
    for row in reader:
        if None in row or any(value is None or "\0" in value for value in row.values()):
            _fail("malformed complete native row")
        yield row


def _stream_hash(stream):
    """Hash the exact already-consumed immutable CSV payload without buffering it."""
    stream.seek(0)
    digest = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block.encode("utf-8", errors="surrogateescape"))
    stream.seek(0)
    return digest.hexdigest()


def _expected_claim(fields, source_record, subject, target):
    """Reproduce only the existing BacDive link's complete blank-extension row shape."""
    mandatory = {*_CORE, SUBJECT_COLUMN, OBJECT_COLUMN, SOURCE_RECORD_COLUMN}
    if len(fields) != len(set(fields)) or not mandatory <= set(fields):
        _fail("incomplete original edge schema")
    return {
        **dict.fromkeys(fields, ""),
        **_CORE,
        SUBJECT_COLUMN: subject,
        OBJECT_COLUMN: target,
        SOURCE_RECORD_COLUMN: source_record,
    }


def _snapshot_projection(fields, source_record, subject, native):
    """Reconstruct literal snapshot assertions independently of the producer writer."""
    from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform

    rows = []
    for column in BACDIVE_SNAPSHOT_COLUMNS:
        for label in split_snapshot_values(column, native.get(column)):
            identity = json.dumps([MICROBEDECODER, column, label], ensure_ascii=False, separators=(",", ":"))
            target = (
                SOURCE_ATTRIBUTE_PREFIX
                + MICROBEDECODER
                + "_"
                + slugify_label(column)
                + "_"
                + _hash(identity.encode("utf-8", errors="surrogateescape"))
            )
            rows.append(
                {
                    **dict.fromkeys(fields, ""),
                    **_CORE,
                    SUBJECT_COLUMN: subject,
                    PREDICATE_COLUMN: HAS_ATTRIBUTE_PREDICATE,
                    OBJECT_COLUMN: target,
                    RELATION_COLUMN: HAS_ATTRIBUTE_RELATION,
                    DESCRIPTION_COLUMN: column.replace("BacDive_", "").replace("_", " "),
                    SOURCE_RECORD_COLUMN: source_record,
                    SOURCE_COLUMN: column,
                    VALUE_COLUMN: MicrobeDecoderTransform._escape_literal(label),
                    VALUE_ENCODING_COLUMN: "backslash",
                }
            )
    return rows


def _snapshot_node(source_record, rows):
    """Declare the source record, not an organism or either contradicted taxon."""
    if not rows:
        return None
    return {
        ID_COLUMN: _RECORD_PREFIX + _hash(source_record.encode()),
        CATEGORY_COLUMN: INFORMATION_CONTENT_ENTITY_CATEGORY,
        NAME_COLUMN: "MicrobeDecoder unresolved BacDive snapshot record " + source_record.rsplit("=", 1)[1],
        DESCRIPTION_COLUMN: (
            "Source observation record for " + source_record + "; the reported BacDive/LPSN join is contradicted. "
            "Values are preserved without assigning this record to either organism or asserting taxon identity."
        ),
        PROVIDED_BY_COLUMN: MICROBEDECODER_KNOWLEDGE_SOURCE,
    }


class BacDiveJoinGuard:
    """Bind actual source reads, six refusals, and the complete retained BacDive-link family."""

    def __init__(self, policy_payload, evidence_payload, raw_stream, gss_stream, *, fields, bindings, admission):
        """Parse only already admitted bytes and seal the original selection evidence."""
        if _hash(policy_payload) != POLICY_SHA256 or _hash(evidence_payload) != EVIDENCE_SHA256:
            _fail("curated policy/evidence differs from reviewed immutable bytes")
        self.admission = admission
        self.fields = tuple(fields)
        self.bindings = _parsed(_json(bindings))
        self.policy = _parsed(policy_payload)
        self.evidence = _parsed(evidence_payload)
        if (
            self.policy.get("version") != 1
            or self.evidence.get("version") != 1
            or self.policy.get("evidence_sha256") != EVIDENCE_SHA256
            or _hash(_json(self.policy.get("decisions")).encode()) != DECISIONS_SHA256
        ):
            _fail("finite witness set changed")
        if (
            set(bindings) != set(REQUIRED_INPUTS)
            or bindings[ROLE_POLICY]["sha256"] != POLICY_SHA256
            or bindings[ROLE_EVIDENCE]["sha256"] != EVIDENCE_SHA256
            or bindings[ROLE_RAW]["sha256"] != self.policy["source_sha256"]
            or bindings[ROLE_GSS]["sha256"] != self.policy["lpsn_gss_sha256"]
            or _stream_hash(raw_stream) != self.policy["source_sha256"]
            or _stream_hash(gss_stream) != self.policy["lpsn_gss_sha256"]
        ):
            _fail("actual source/GSS read differs from finite policy")
        gss = {}
        for row in _rows(gss_stream, ("record_no", "record_lnk", "status")):
            identifier = row["record_no"].strip()
            if identifier:
                if identifier in gss:
                    _fail("duplicate GSS record identifier")
                gss[identifier] = row
        self.accepted = resolve_accepted_records(gss)
        self.rules = {item["ordinal"]: item for item in self.policy["decisions"]}
        self.witnesses = {item["ordinal"]: item for item in self.evidence["cases"]}
        if (
            len(self.rules) != len(self.policy["decisions"])
            or set(self.rules) != set(self.witnesses)
            or len(self.witnesses) != len(self.evidence["cases"])
        ):
            _fail("missing, duplicated or extra finite witness")
        self.selected = {}
        self.retained_links = set()
        observed = 0
        for observed, row in enumerate(_rows(raw_stream, (LPSN_ID_COLUMN, BACDIVE_CROSSWALK_COLUMN)), 1):
            original_id = row[LPSN_ID_COLUMN].strip()
            accepted = self.accepted.get(original_id, original_id)
            record = f"sha256:{self.policy['source_sha256']}#record={observed}"
            tokens = list(split_multivalue_comma_only(row[BACDIVE_CROSSWALK_COLUMN]))
            rule = self.rules.get(observed)
            if rule is not None:
                witness = self.witnesses[observed]
                if (
                    row != witness["native_md_row"]
                    or _hash(_json(row).encode()) != rule["raw_record_sha256"]
                    or original_id != rule["raw_lpsn_id"]
                    or accepted != rule["accepted_lpsn_id"]
                    or row[BACDIVE_CROSSWALK_COLUMN] != rule["source_cell"]
                    or tokens != [rule["source_token"]]
                    or rule["disposition"] != _DISPOSITION
                    or gss.get(accepted) != witness["md_accepted_gss_row"]["full_row"]
                    or rule["witness_family"] != witness["primary_witness"]["witness_family"]
                    or rule["witness_family"]
                    not in {"incorrect_deposit_number", "documented_non_equivalent_historical_deposits"}
                ):
                    _fail("complete finite native record/accepted-name witness drift")
                bd = witness["bacdive_complete_decoded_record"]
                if (
                    _hash(_json(bd["record"]).encode()) != bd["canonical_record_sha256"]
                    or str(bd["bacdive_id"]) != rule["bacdive_id"]
                ):
                    _fail("complete frozen BacDive native evidence differs")
                claim = _expected_claim(self.fields, record, _STRAIN + rule["bacdive_id"], LPSN_PREFIX + accepted)
                original = _snapshot_projection(self.fields, record, LPSN_PREFIX + accepted, row)
                projection = witness.get("snapshot_projection", {})
                keys = [[item[SOURCE_COLUMN], item[VALUE_COLUMN]] for item in original]
                if (
                    self.policy.get("snapshot_observation_disposition") != SNAPSHOT_DISPOSITION
                    or self.evidence.get("snapshot_observation_disposition") != SNAPSHOT_DISPOSITION
                    or Counter(map(tuple, keys)) != Counter(map(tuple, projection.get("source_values", [])))
                    or not isinstance(projection.get("phenotype_audits"), list)
                ):
                    _fail("approved snapshot disposition or complete occurrence witness changed")
                node = _snapshot_node(record, original)
                emitted = [{**item, SUBJECT_COLUMN: node[ID_COLUMN]} for item in original] if node else []
                audits = []
                for item in projection["phenotype_audits"]:
                    if item[SUBJECT_COLUMN] != LPSN_PREFIX + accepted:
                        _fail("phenotype witness does not retain the original accepted subject")
                    audit = {**item, SOURCE_RECORD_COLUMN: record}
                    if item[SOURCE_COLUMN] in BACDIVE_SNAPSHOT_COLUMNS:
                        if [item[SOURCE_COLUMN], item[VALUE_COLUMN]] not in keys or node is None:
                            _fail("dependent phenotype witness has no snapshot occurrence")
                        audit[SUBJECT_COLUMN] = node[ID_COLUMN]
                    elif item[SOURCE_COLUMN] != "FAPROTAX_Type_of_metabolism":
                        _fail("unexpected phenotype witness outside reviewed snapshot/FAPROTAX scope")
                    audits.append(audit)
                self.selected[record] = {
                    "rule": rule,
                    "native": row,
                    "claim": claim,
                    "witness": witness,
                    "snapshot_node": node,
                    "snapshot_original": original,
                    "snapshot_emitted": emitted,
                    "phenotype_audits": audits,
                }
            if is_empty_cell(original_id):
                continue
            for token in tokens:
                target = crosswalk_curie(token, _STRAIN, "bacdive:")
                claim = _expected_claim(self.fields, record, target, LPSN_PREFIX + accepted)
                if rule is None:
                    self.retained_links.add(_json(claim))
                elif claim != self.selected[record]["claim"]:
                    _fail("finite token does not emit the reviewed reversed link")
        if observed != self.policy["source_records"] or len(self.selected) != len(self.rules):
            _fail("complete native cohort changed or finite decision disappeared")
        raw_stream.seek(0)
        self._dispatches = set()
        self._snapshot_dispatches = set()
        self._sealed = None
        self._failed = False
        self._read_cache = tuple(
            (
                str(Path(item["path"])),
                _json(admission.identities[Path(item["path"])]),
                admission.stamps[Path(item["path"])],
            )
            for item in self.bindings.values()
        )
        self._evidence_anchor = self._state()
        admission.capture_resolution(self._state)
        admission.capture_resolution(self._binding_state)

    def _state(self):
        """Bind parsed caches to prevent changed scientific decisions after actual reads."""
        return _hash(
            _json(
                [
                    self.fields,
                    self.bindings,
                    self.policy,
                    self.evidence,
                    self.accepted,
                    self.selected,
                    sorted(self.retained_links),
                ]
            ).encode()
        )

    def _binding_state(self):
        """Retain original roles, lexical locators and mandatory admission cache membership."""
        for role, item in self.bindings.items():
            path, lexical = Path(item["path"]), Path(item["lexical_path"])
            if (
                self.admission.bindings.get(lexical) != path
                or lexical.resolve() != path
                or self.admission.identities.get(path, {}).get("sha256") != item["sha256"]
            ):
                _fail("original " + role + " read binding was lost or rebound")
        for name, expected, stamp in self._read_cache:
            path = Path(name)
            if _json(self.admission.identities.get(path)) != expected or self.admission.stamps.get(path) != stamp:
                _fail("mandatory source admission cache changed")
        return _json(self.bindings), self._read_cache

    def _poison(self):
        """Keep a caught failure from becoming a certified partial success."""
        self._failed = True
        self.admission.capture_resolution(lambda: self._failed)

    def _inputs(self, snapshots, *, verify_admission=True):
        """Verify original named consumed inputs, not only hashes appearing elsewhere."""
        if self._failed or self._state() != self._evidence_anchor:
            _fail("failed or changed parsed native state")
        for role, expected in self.bindings.items():
            if snapshots.get(role) != {key: expected[key] for key in ("path", "sha256")}:
                _fail("missing or rebound original consumed role: " + role)
        self._binding_state()
        if verify_admission:
            self.admission.verify(metadata_only=True)

    def dispatch(self, source_record, native_row, accepted_subject, token, claim):
        """Return an audit row only for the exact would-be strain-to-LPSN assertion."""
        try:
            if self._failed or self._sealed is not None:
                _fail("dispatch requires unchanged unfinished source evidence")
            selected = self.selected.get(source_record)
            if selected is None:
                return None
            # Only six selected calls need a full parsed-witness recheck. The
            # complete state is checked again before file handles publish;
            # never hash the whole retained-link set for every native record.
            if self._state() != self._evidence_anchor:
                _fail("finite parsed witness changed during emission")
            expected = selected["claim"]
            normalized = {key: "" if value is None else value for key, value in claim.items()}
            if (
                native_row != selected["native"]
                or normalized != expected
                or accepted_subject != expected[OBJECT_COLUMN]
                or token != selected["rule"]["source_token"]
                or source_record in self._dispatches
            ):
                _fail("wrong, changed or duplicate finite link dispatch")
            self._dispatches.add(source_record)
            return self._audit(source_record)
        except BaseException:
            self._poison()
            raise

    def _audit(self, source_record):
        """Describe the real omitted row and complete native/primary witness without fiction."""
        selected = self.selected[source_record]
        return {
            "source_record": source_record,
            "source_column": BACDIVE_CROSSWALK_COLUMN,
            "source_cell_json": _json(selected["native"][BACDIVE_CROSSWALK_COLUMN]),
            "source_token_json": _json(selected["rule"]["source_token"]),
            "native_record_json": _json(selected["native"]),
            "original_claim_json": _json(selected["claim"]),
            "emitted_claim_json": "null",
            "witness_json": _json(selected["witness"]),
            "policy_sha256": POLICY_SHA256,
            "evidence_sha256": EVIDENCE_SHA256,
            "disposition": _DISPOSITION,
            "snapshot_disposition": SNAPSHOT_DISPOSITION,
            "snapshot_node_json": _json(selected["snapshot_node"]),
            "snapshot_original_claims_json": _json(selected["snapshot_original"]),
            "snapshot_emitted_claims_json": _json(selected["snapshot_emitted"]),
        }

    def snapshot_node(self, source_record, native_row, accepted_subject):
        """Select an admitted record subject once, after its contradicted link was audited."""
        try:
            selected = self.selected.get(source_record)
            if selected is None:
                return None
            if (
                self._failed
                or self._sealed is not None
                or self._state() != self._evidence_anchor
                or source_record not in self._dispatches
                or source_record in self._snapshot_dispatches
                or native_row != selected["native"]
                or accepted_subject != selected["claim"][OBJECT_COLUMN]
            ):
                _fail("wrong, changed or duplicate finite snapshot dispatch")
            self._snapshot_dispatches.add(source_record)
            return dict(selected["snapshot_node"]) if selected["snapshot_node"] else None
        except BaseException:
            self._poison()
            raise

    def require_complete(self):
        """Run before atomic source file handles publish any newly written members."""
        if (
            self._failed
            or self._state() != self._evidence_anchor
            or self._dispatches != set(self.selected)
            or self._snapshot_dispatches != set(self.selected)
        ):
            self._poison()
            _fail("not every finite decision was dispatched exactly once")

    def _verify_output(self, directory, *, edge_member="edges.tsv"):
        """Rejoin the complete source link family and exact audit, with no post-merge edits."""
        directory = Path(directory)
        if edge_member != "edges.tsv":
            _fail("unexpected producer edge member scope")
        audit_path, edge_path = directory / AUDIT_FILE, directory / edge_member
        for path in (audit_path, edge_path):
            if path.is_symlink() or not path.is_file():
                _fail("missing or symlinked source output/audit")
        with audit_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if reader.fieldnames != list(AUDIT_FIELDS):
                _fail("audit header changed")
            actual_audit = Counter(_json(row) for row in reader)
        expected_audit = Counter(_json(self._audit(key)) for key in self.selected)
        if actual_audit != expected_audit:
            _fail("original native/audit rows lost, changed or duplicated")
        actual_links, actual_snapshots = Counter(), Counter()
        with edge_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
                _fail("source edge header changed")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    _fail("malformed source edge row")
                # This producer emits BacDive-strain endpoints only for the
                # native BacDive_ID link family. Inspect either orientation,
                # without trusting predicate/relation to identify that family:
                # an added inverse or relabelled claim must not escape the
                # complete row/occurrence rejoin below.
                if any(row.get(column, "").startswith(_STRAIN) for column in (SUBJECT_COLUMN, OBJECT_COLUMN)):
                    if any(value and key not in self.fields for key, value in row.items()):
                        _fail("unreviewed nonblank extension on BacDive link")
                    actual_links[_json({field: row.get(field, "") for field in self.fields})] += 1
                if (
                    row.get(SOURCE_RECORD_COLUMN) in self.selected
                    and row.get(SOURCE_COLUMN) in BACDIVE_SNAPSHOT_COLUMNS
                ) or any(row.get(column, "").startswith(_RECORD_PREFIX) for column in (SUBJECT_COLUMN, OBJECT_COLUMN)):
                    if any(value and key not in self.fields for key, value in row.items()):
                        _fail("unreviewed snapshot extension")
                    actual_snapshots[_json({field: row.get(field, "") for field in self.fields})] += 1
        if actual_links != Counter(dict.fromkeys(self.retained_links, 1)):
            _fail("retained native BacDive links differ from exact reviewed six removals")
        expected_snapshots = {_json(row) for item in self.selected.values() for row in item["snapshot_emitted"]}
        if actual_snapshots != Counter(dict.fromkeys(expected_snapshots, 1)):
            _fail("snapshot subjects or complete source assertions changed")
        self._verify_snapshot_nodes_and_audits(directory)

    def _verify_snapshot_nodes_and_audits(self, directory):
        """Verify five record declarations and dependent-only phenotype audit projection."""
        nodes, audits = Counter(), Counter()
        for name in ("nodes.tsv", "phenotype_normalizations.tsv"):
            path = directory / name
            if path.is_symlink() or not path.is_file():
                _fail("missing snapshot node/phenotype member")
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                    _fail("invalid snapshot node/phenotype header")
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        _fail("malformed snapshot node/phenotype row")
                    if name == "nodes.tsv" and row.get(ID_COLUMN, "").startswith(_RECORD_PREFIX):
                        nodes[_json({key: value for key, value in row.items() if value})] += 1
                    elif name == "phenotype_normalizations.tsv" and (
                        row.get(SOURCE_RECORD_COLUMN) in self.selected
                        or row.get(SUBJECT_COLUMN, "").startswith(_RECORD_PREFIX)
                    ):
                        audits[_json(row)] += 1
        expected_nodes = Counter(
            _json(item["snapshot_node"]) for item in self.selected.values() if item["snapshot_node"]
        )
        expected_audits = Counter(_json(row) for item in self.selected.values() for row in item["phenotype_audits"])
        if nodes != expected_nodes or audits != expected_audits:
            _fail("record declarations or dependent/independent phenotype audit conservation failed")

    def finish(self, transform):
        """Seal the completed audit and finite contract after existing source deduplication."""
        try:
            self.require_complete()
            self._inputs(transform.consumed_input_snapshots)
            self._verify_output(transform.output_dir)
            self._sealed = _json(
                {
                    "version": 1,
                    "bindings": self.bindings,
                    "policy_sha256": POLICY_SHA256,
                    "evidence_sha256": EVIDENCE_SHA256,
                    "edge_fields": list(self.fields),
                    "edge_members": ["edges.tsv"],
                    "source_records": self.policy["source_records"],
                    "quarantined_links": len(self.selected),
                    "retained_link_assertions": len(self.retained_links),
                    "scope": _SCOPE,
                    "snapshot_nodes": sum(item["snapshot_node"] is not None for item in self.selected.values()),
                    "snapshot_occurrences": sum(len(item["snapshot_original"]) for item in self.selected.values()),
                }
            )
            self.admission.capture_resolution(lambda: self._sealed)
            self.admission.capture_resolution(lambda: tuple(sorted(self._dispatches)))
            self.admission.capture_resolution(lambda: tuple(sorted(self._snapshot_dispatches)))
            return self.contract()
        except BaseException:
            self._poison()
            raise

    def contract(self):
        """Expose a copied completion contract, never a mutable cache or implicit acceptance."""
        if self._sealed is None or self._failed:
            _fail("source run has no completed finite disposition contract")
        return _parsed(self._sealed)

    def verify(self, snapshots, contract, *, output_dir, configured_selectors=None):
        """Keep mandatory read/audit/output guards live through staging, repeat and publication."""
        try:
            # Live producer selectors belong inside the existing sticky
            # boundary, just like parsed state, named roles and output bytes.
            # Recorded reconstruction has no mutable producer configuration;
            # it independently rejoins its saved original lexical locators.
            if configured_selectors is not None:
                policy, raw_directory = configured_selectors
                if (
                    policy is None
                    or raw_directory is None
                    or Path(policy).absolute() != Path(self.bindings[ROLE_POLICY]["lexical_path"])
                    or (Path(raw_directory) / "lpsn_gss.csv").absolute()
                    != Path(self.bindings[ROLE_GSS]["lexical_path"])
                ):
                    _fail("configured producer policy/GSS locator differs from the original read")
            self._inputs(snapshots)
            if contract != self.contract():
                _fail("source native contract missing or changed")
            self.require_complete()
            self._verify_output(output_dir)
        except BaseException:
            self._poison()
            raise


def _bind(admission, role, path, snapshots):
    """Preserve lexical selection as well as actual consumed resolved-path/byte identity."""
    lexical = Path(path).absolute()
    actual = admission.capture(lexical)
    resolved = lexical.resolve()
    expected = snapshots.get(role)
    if expected != {"path": str(resolved), "sha256": actual["sha256"]}:
        _fail("named role does not identify the actual parsed input: " + role)
    return {**expected, "lexical_path": str(lexical)}


def prepare(transform, raw_snapshot, raw_path, policy_path):
    """Use actual immutable CSV/GSS reads before the existing source output transaction."""
    admission = SourceAdmission()
    bindings = {ROLE_RAW: _bind(admission, ROLE_RAW, raw_path, transform.consumed_input_snapshots)}
    with transform.consume_input(ROLE_POLICY, policy_path) as stream:
        policy_payload = stream.read().encode()
        bindings[ROLE_POLICY] = _bind(admission, ROLE_POLICY, policy_path, transform.consumed_input_snapshots)
    if _hash(policy_payload) != POLICY_SHA256:
        _fail("finite policy changed before native preflight")
    policy = _parsed(policy_payload)
    evidence_name = policy["evidence_file"]
    if Path(evidence_name).name != evidence_name or "\\" in evidence_name:
        _fail("unsafe witness filename")
    evidence_path = Path(policy_path).parent / evidence_name
    with transform.consume_input(ROLE_EVIDENCE, evidence_path) as stream:
        evidence_payload = stream.read().encode()
        bindings[ROLE_EVIDENCE] = _bind(admission, ROLE_EVIDENCE, evidence_path, transform.consumed_input_snapshots)
    gss_path = Path(transform.input_base_dir) / "lpsn_gss.csv"
    with transform.consume_input(ROLE_GSS, gss_path) as gss_stream:
        bindings[ROLE_GSS] = _bind(admission, ROLE_GSS, gss_path, transform.consumed_input_snapshots)
        guard = BacDiveJoinGuard(
            policy_payload,
            evidence_payload,
            raw_snapshot,
            gss_stream,
            fields=transform.edge_header,
            bindings=bindings,
            admission=admission,
        )
    guard._inputs(transform.consumed_input_snapshots)
    return guard


def restore(report, report_path, *, admission=None):
    """Independently reconstruct from mandatory actual input roles, not mutable audit claims."""
    admission = admission or SourceAdmission()
    contract = report.get("producer_native_inputs", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict) or set(contract.get("bindings", {})) != set(REQUIRED_INPUTS):
        _fail("mandatory recorded finite contract is absent")
    snapshots = report.get("consumed_inputs", {})
    bindings = {}
    for role, saved in contract["bindings"].items():
        bindings[role] = _bind(admission, role, saved["lexical_path"], snapshots)
        if bindings[role] != saved:
            _fail("recorded original role locator changed")
    policy_payload = admission.capture(Path(bindings[ROLE_POLICY]["path"]), retain=True)
    evidence_payload = admission.capture(Path(bindings[ROLE_EVIDENCE]["path"]), retain=True)
    raw_path, gss_path = Path(bindings[ROLE_RAW]["path"]), Path(bindings[ROLE_GSS]["path"])
    if gss_path != (Path(report["raw_input_directory"]) / "lpsn_gss.csv").resolve():
        _fail("recorded GSS authority is not the original selected raw directory")
    with (
        raw_path.open(encoding="utf-8", errors="surrogateescape", newline="") as raw_stream,
        gss_path.open(encoding="utf-8", newline="") as gss_stream,
    ):
        guard = BacDiveJoinGuard(
            policy_payload,
            evidence_payload,
            raw_stream,
            gss_stream,
            fields=contract["edge_fields"],
            bindings=bindings,
            admission=admission,
        )
    directory = Path(report_path).parent
    if contract.get("edge_members") != ["edges.tsv"] or "edges.tsv" not in report.get("members", {}):
        _fail("original producer edge scope missing or changed")
    for name, collection in (
        (AUDIT_FILE, "producer_audit_members"),
        ("phenotype_normalizations.tsv", "producer_audit_members"),
        ("edges.tsv", "members"),
        ("nodes.tsv", "members"),
    ):
        path = directory / name
        if path.is_symlink() or admission.capture(path) != report.get(collection, {}).get(name):
            _fail("recorded source output/audit identity changed")
    # Reconstruction is a read-only native/audit rejoin, not producer dispatch.
    # The exact original audit must establish every completed finite occurrence.
    guard._verify_output(directory)
    guard._dispatches = set(guard.selected)
    guard._snapshot_dispatches = set(guard.selected)
    guard._sealed = _json(
        {
            "version": 1,
            "bindings": guard.bindings,
            "policy_sha256": POLICY_SHA256,
            "evidence_sha256": EVIDENCE_SHA256,
            "edge_fields": list(guard.fields),
            "edge_members": ["edges.tsv"],
            "source_records": guard.policy["source_records"],
            "quarantined_links": len(guard.selected),
            "retained_link_assertions": len(guard.retained_links),
            "scope": _SCOPE,
            "snapshot_nodes": sum(item["snapshot_node"] is not None for item in guard.selected.values()),
            "snapshot_occurrences": sum(len(item["snapshot_original"]) for item in guard.selected.values()),
        }
    )
    admission.capture_resolution(lambda: guard._sealed)
    admission.capture_resolution(lambda: tuple(sorted(guard._dispatches)))
    admission.capture_resolution(lambda: tuple(sorted(guard._snapshot_dispatches)))
    # Bind original report role membership/contract even if caller later edits its dictionary.
    admission.capture_resolution(
        lambda: _json(
            [
                report.get("consumed_inputs"),
                report.get("producer_native_inputs"),
                report.get("raw_input_directory"),
                report.get("producer_audit_members"),
                report.get("members"),
            ]
        )
    )
    guard.verify(snapshots, contract, output_dir=directory)
    admission.verify(metadata_only=True)
    return guard


def verify_recorded_inputs(report, report_path, *, admission=None):
    """Retain the native/read guard on the caller's admission until final publication."""
    guard = restore(report, report_path, admission=admission)
    guard.admission.capture_resolution(lambda: guard._inputs(report.get("consumed_inputs", {}), verify_admission=False))
    return guard.admission


def verify_transform(transform, *, output_dir=None):
    """Restore a fresh object's read-only guard on repeat; do not invent producer completion."""
    guard = getattr(transform, "_bacdive_join_guard", None)
    if guard is None:
        path = Path(transform.output_dir) / "source_finalization.json"
        if not path.is_file():
            _fail("producer did not complete the mandatory link disposition")
        admission = SourceAdmission()
        report = admission.read_json(path)
        guard = restore(report, path, admission=admission)
        transform._bacdive_join_guard = guard
    native = getattr(transform, "producer_native_inputs", None)
    contract = native.get(CONTRACT_KEY) if isinstance(native, dict) else None
    guard.verify(
        transform.consumed_input_snapshots,
        contract,
        output_dir=Path(output_dir) if output_dir is not None else transform.output_dir,
        configured_selectors=(
            getattr(transform, "bacdive_join_policy", None),
            getattr(transform, "input_base_dir", None),
        ),
    )
