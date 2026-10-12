"""Retain four reviewed native leaf observations without unsupported NCIT site identity."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import ijson

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import isolation_categories
from kg_microbe.transform_utils.constants import (
    ATTRIBUTE_CATEGORY,
    CATEGORY_COLUMN,
    DEPRECATED_COLUMN,
    DESCRIPTION_COLUMN,
    HAS_ATTRIBUTE_PREDICATE,
    HAS_ATTRIBUTE_RELATION,
    HAS_ATTRIBUTE_TYPE_COLUMN,
    ID_COLUMN,
    ISOLATION_SAMPLING_ENV_INFO,
    ISOLATION_SOURCE_CATEGORIES,
    NAME_COLUMN,
    OBJECT_COLUMN,
    ONTOLOGY_CLASS_CATEGORY,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SAME_AS_COLUMN,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
    TRANSLATION_TABLE_FOR_IDS,
    XREF_COLUMN,
)
from kg_microbe.utils.isolation_source_mapping_utils import normalize_isolation_source_label
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

POLICY_RELATIVE = "mappings/bacdive_ncit_category_claims.json"
POLICY_PATH = Path(__file__).resolve().parents[3] / POLICY_RELATIVE
POLICY_SHA256 = "e8450c0f01b05bea9dd8436c7833701da0b054e80bfe1c4b2680fc0d2909c4ac"
REQUIRED_INPUTS = ("bacdive_ncit_category_claim_policy",)
ROLES = (*REQUIRED_INPUTS, isolation_categories.REQUIRED_INPUTS[1], isolation_categories.RAW_INPUT)
AUDIT_FILE = "ncit_isolation_category_dispositions.tsv"
AUDIT_FIELDS = (
    "status",
    "record_id",
    "source_record_coordinate_json",
    "source_path_json",
    "source_category_json",
    "source_record_json",
    "original_mapping_json",
    "original_edge_json",
    "emitted_node_json",
    "emitted_edge_json",
    "reason",
    "consumed_inputs_json",
)
_SCOPE = frozenset({"lesion incl. necrosis", "parasite"})
_SOURCE = "bacdive_strains.json"
_MEMBERS = {"nodes": ["nodes.tsv"], "edges": ["edges.tsv"]}


def _json(value):
    """Retain literal evidence reversibly within TSV cells and immutable in-memory seals."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value):
    """Hash structured native records without depending on JSON whitespace or object ordering."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _fail(message):
    raise SourceFinalizationRequired("BacDive finite NCIT claims: " + message)


def _unique(pairs):
    """Reject duplicate policy keys instead of last-row-wins scientific decisions."""
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate policy key")
        result[key] = value
    return result


def load_policy(stream):
    """Require all four reviewed records and both complete original mapping claims."""
    policy = json.load(stream, object_pairs_hook=_unique)
    if _sha(policy) != POLICY_SHA256:
        _fail("policy differs from the independently reviewed finite decision")
    return policy


def _eligible(value):
    if not isinstance(value, str):
        return False
    normalized = normalize_isolation_source_label(value.lstrip("#"))
    sanitized = normalize_isolation_source_label(value.strip().translate(str.maketrans(TRANSLATION_TABLE_FOR_IDS)))
    return normalized in _SCOPE or sanitized in _SCOPE


def _selected(records, policy):
    """Scan every actual record; new, changed, duplicate or relocated eligible claims fail closed."""
    rules = {rule["record_id"]: rule for rule in policy["rules"]}
    selected, seen = [], set()
    for coordinate, record in records:
        if not isinstance(record, dict):
            _fail("source record is not an object")
        identifier = str(record.get("General", {}).get("BacDive-ID", ""))
        rule = rules.get(identifier)
        categories = record.get(ISOLATION_SAMPLING_ENV_INFO, {}).get(ISOLATION_SOURCE_CATEGORIES)
        entries = list(enumerate(categories)) if isinstance(categories, list) else [(None, categories)]
        occurrences = []
        for index, category in entries:
            if not isinstance(category, dict):
                if _eligible(category):
                    _fail("eligible category has an unreviewed container")
                continue
            for field, value in category.items():
                if _eligible(value):
                    path = [ISOLATION_SAMPLING_ENV_INFO, ISOLATION_SOURCE_CATEGORIES]
                    if index is not None:
                        path.append(index)
                    occurrences.append(([*path, field], category, value))
        if rule is not None:
            if identifier in seen or _sha(record) != rule["native_record_sha256"]:
                _fail("reviewed native record changed or duplicated")
            seen.add(identifier)
        if not occurrences:
            if rule is not None:
                _fail("reviewed native record lost its source occurrence")
            continue
        if rule is None or occurrences != [(rule["source_path"], rule["category"], rule["value"])]:
            _fail("new or changed eligible occurrence requires review")
        selected.append({"coordinate": coordinate, "record_id": identifier, "record": record})
    return selected


def _records(payload):
    if isinstance(payload, list):
        return enumerate(payload)
    if isinstance(payload, dict):
        return payload.items()
    _fail("source must be a record list or object")


def _native_records(stream):
    """Stream graph-scale raw evidence without retaining the full source at admission."""
    first = ""
    while not first:
        char = stream.read(1)
        if not char:
            _fail("empty native source")
        if not char.isspace():
            first = char
    stream.seek(0)
    if first in ("[", b"["):
        yield from enumerate(ijson.items(stream, "item", use_float=True))
    elif first in ("{", b"{"):
        yield from ijson.kvitems(stream, "", use_float=True)
    else:
        _fail("native source is not a record list or object")


def _mapping(stream, policy):
    """Validate source-specific nonidentity rows; no global NCIT concept blacklist is created."""
    reader = csv.DictReader(stream, delimiter="\t")
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        _fail("invalid mapping header")
    selected = []
    for row in reader:
        if None in row or None in row.values():
            _fail("malformed isolation mapping")
        if _eligible(row["subject_label_normalized"] or row["subject_label"]):
            selected.append(row)
    originals = {row["subject_label_normalized"]: row for row in policy["original_mappings"]}
    if len(selected) != 2 or {row["subject_label_normalized"] for row in selected} != set(originals):
        _fail("reviewed mapping rows missing or duplicated")
    for row in selected:
        if any(row[key] for key in ("object_id", "object_label", "object_source", "predicate_id")):
            _fail("source leaf identity reintroduced")


def _paths(raw_dir):
    return {
        REQUIRED_INPUTS[0]: POLICY_PATH,
        ROLES[1]: isolation_categories.MAPPING_PATH,
        ROLES[2]: Path(raw_dir) / _SOURCE,
    }


def _bindings(snapshots, raw_dir):
    result = {}
    for role, path in _paths(raw_dir).items():
        actual = snapshots.get(role)
        if not isinstance(actual, dict) or set(actual) != {"path", "sha256"}:
            _fail("missing original consumed role " + role)
        if actual["path"] != str(path.resolve()):
            _fail("original consumed role locator changed: " + role)
        result[role] = actual
    return result


def _audit(entry, policy, bindings):
    """Construct complete original/native/replacement evidence independently of emitter state."""
    rule = next(rule for rule in policy["rules"] if rule["record_id"] == entry["record_id"])
    organism = rule["original_edge"][OBJECT_COLUMN]
    witness = {"organism_id": organism, "source_path": rule["source_path"], "category": rule["category"]}
    identifier = "kgmicrobe.isolation_category:" + _sha(witness)
    node = {
        ID_COLUMN: identifier,
        CATEGORY_COLUMN: ATTRIBUTE_CATEGORY,
        NAME_COLUMN: "BacDive isolation source category: " + rule["value"][1:],
        DESCRIPTION_COLUMN: "Record-scoped source classification; external site identity unresolved. " + _json(witness),
        HAS_ATTRIBUTE_TYPE_COLUMN: isolation_categories.ATTRIBUTE_TYPE,
        PROVIDED_BY_COLUMN: rule["original_edge"][PRIMARY_KNOWLEDGE_SOURCE_COLUMN],
        XREF_COLUMN: "",
        SYNONYM_COLUMN: "",
        SAME_AS_COLUMN: "",
        DEPRECATED_COLUMN: "",
    }
    edge = dict(rule["original_edge"])
    edge.update(
        {
            SUBJECT_COLUMN: organism,
            PREDICATE_COLUMN: HAS_ATTRIBUTE_PREDICATE,
            OBJECT_COLUMN: identifier,
            RELATION_COLUMN: HAS_ATTRIBUTE_RELATION,
        }
    )
    original_mapping = next(row for row in policy["original_mappings"] if row["object_id"] == rule["target"])
    return {
        "status": policy["disposition"],
        "record_id": entry["record_id"],
        "source_record_coordinate_json": _json(entry["coordinate"]),
        "source_path_json": _json(rule["source_path"]),
        "source_category_json": _json(rule["category"]),
        "source_record_json": _json(entry["record"]),
        "original_mapping_json": _json(original_mapping),
        "original_edge_json": _json(rule["original_edge"]),
        "emitted_node_json": _json(node),
        "emitted_edge_json": _json(edge),
        "reason": rule["reason"],
        "consumed_inputs_json": _json(bindings),
    }


class ClaimGuard:
    """Keep immutable actual-read evidence through run, finalization and repeated publication."""

    def __init__(self, raw_dir, policy, selected, bindings, *, completed=False, admission=None):
        """Seal finite evidence separately from mutable emission progress."""
        self.raw_dir = Path(raw_dir).absolute()
        self._policy = _json(policy)
        self._selected = _json(selected)
        self._bindings = _json(bindings)
        self._contract = _json(
            {
                "version": 1,
                "raw_locator": str(self.raw_dir),
                "consumed_inputs": bindings,
                "selected_records": [
                    {
                        "record_id": row["record_id"],
                        "coordinate": row["coordinate"],
                        "record_sha256": _sha(row["record"]),
                    }
                    for row in selected
                ],
                "members": _MEMBERS,
            }
        )
        self.emitted = set(row["record_id"] for row in selected) if completed else set()
        self.completed = completed
        self._outputs_ready = completed
        self.failed = False
        self.admission = admission or SourceAdmission()
        for path in _paths(self.raw_dir).values():
            self.admission.bind_path(path)
        self.admission.capture_resolution(self._scientific_state)
        if completed:
            self.admission.capture_resolution(self._completion_state)
            self.admission.capture_resolution(self._output_state)

    def _scientific_state(self):
        """Separate captured scientific state from legitimately changing emission progress."""
        return self._policy, self._selected, self._bindings, self._contract, str(self.raw_dir)

    def _completion_state(self):
        """Retain successful finite emission as a monotonic checkpoint, not a skip flag."""
        return self.completed

    def _output_state(self):
        """Retain the independently established output-ready transition."""
        return self._outputs_ready

    @property
    def outputs_ready(self):
        """Expose a read-only phase view, checked against the retained admission observation."""
        return self._outputs_ready

    @property
    def contract(self):
        """Return a copy, not the mutable live contract or scientific policy."""
        return json.loads(self._contract)

    def verify(self, snapshots, *, output_dir=None, quoting=csv.QUOTE_NONE, output_ready=None):
        """Do not trust a deleted role, changed cached record or fabricated zero receipt."""
        if self.failed:
            _fail("a prior finite-claim check failed; rerun producer")
        try:
            if output_ready is not None and output_ready != self.outputs_ready:
                _fail("producer output checkpoint changed")
            if _bindings(snapshots, self.raw_dir) != json.loads(self._bindings):
                _fail("actual-read role bindings changed")
            policy, selected = json.loads(self._policy), json.loads(self._selected)
            if _sha(policy) != POLICY_SHA256:
                _fail("cached policy changed")
            replay = _selected(((row["coordinate"], row["record"]) for row in selected), policy)
            summary = [
                {"record_id": row["record_id"], "coordinate": row["coordinate"], "record_sha256": _sha(row["record"])}
                for row in replay
            ]
            if (
                summary != self.contract["selected_records"]
                or json.loads(self._bindings) != self.contract["consumed_inputs"]
            ):
                _fail("cached native cohort or bindings differ from original read")
            expected = {row["record_id"] for row in replay}
            if self.completed and self.emitted != expected:
                _fail("emitted finite cohort is incomplete or duplicated")
            self.admission.verify(metadata_only=True)
            if self.completed and output_dir is not None:
                self.verify_output(output_dir, quoting=quoting)
        except BaseException:
            self.failed = True
            raise

    def emit(
        self, transform, index, category, field, value, *, record, organism_id, node_writer, edge_writer, audit_writer
    ):
        """Intercept only the exact native leaf while preserving all original array indices."""
        if not _eligible(value):
            return False
        try:
            self.verify(transform.consumed_input_snapshots)
            policy = json.loads(self._policy)
            identifier = str(record.get("General", {}).get("BacDive-ID", ""))
            entries = [row for row in json.loads(self._selected) if row["record_id"] == identifier]
            if len(entries) != 1 or entries[0]["record"] != record or identifier in self.emitted:
                _fail("unreviewed, changed or duplicate emission")
            rule = next(row for row in policy["rules"] if row["record_id"] == identifier)
            if (index, category, field, value, organism_id) != (
                rule["source_path"][2],
                rule["category"],
                rule["source_path"][-1],
                rule["value"],
                rule["original_edge"][OBJECT_COLUMN],
            ):
                _fail("original source coordinate or organism changed")
            audit = _audit(entries[0], policy, json.loads(self._bindings))
            node, edge = json.loads(audit["emitted_node_json"]), json.loads(audit["emitted_edge_json"])
            if not transform._isolation_category_type_emitted:
                node_writer.writerow(
                    transform._create_node_row(
                        isolation_categories.ATTRIBUTE_TYPE,
                        ONTOLOGY_CLASS_CATEGORY,
                        "BacDive isolation source category field",
                        description="Local source-schema type for BacDive isolation source category observations; "
                        "not an external ontology identity or a physical site class.",
                    )
                )
                transform._isolation_category_type_emitted = True
            row = transform._create_node_row(
                node[ID_COLUMN], node[CATEGORY_COLUMN], node[NAME_COLUMN], description=node[DESCRIPTION_COLUMN]
            )
            row[transform.node_header.index(HAS_ATTRIBUTE_TYPE_COLUMN)] = node[HAS_ATTRIBUTE_TYPE_COLUMN]
            node_writer.writerow(row)
            edge_writer.writerow([edge.get(column, "") for column in transform.edge_header])
            audit_writer.writerow([audit[column] for column in AUDIT_FIELDS])
            self.emitted.add(identifier)
            return True
        except BaseException:
            self.failed = True
            raise

    def finish(self, snapshots):
        """Require every eligible native observation before atomic output contexts publish."""
        self.completed = True
        self.admission.capture_resolution(self._completion_state)
        self.verify(snapshots)

    def mark_output_ready(self, snapshots):
        """Seal output readiness after successful atomic writer contexts have exited."""
        self.verify(snapshots)
        if not self.completed:
            _fail("cannot mark incomplete finite emission as output-ready")
        self._outputs_ready = True
        self.admission.capture_resolution(self._output_state)

    def verify_output(self, directory, *, quoting=csv.QUOTE_NONE):
        """Rejoin the full audit and retained graph fields; preserve exact selected member scope."""
        directory = Path(directory)
        audits = [
            _audit(row, json.loads(self._policy), json.loads(self._bindings)) for row in json.loads(self._selected)
        ]
        actual = list(graph_rows(directory / AUDIT_FILE))
        with (directory / AUDIT_FILE).open(newline="") as stream:
            if next(csv.reader(stream, delimiter="\t"), None) != list(AUDIT_FIELDS):
                _fail("mandatory audit header changed")
        if actual != audits:
            _fail("mandatory audit differs from complete native claims")
        nodes = {
            json.loads(row["emitted_node_json"])[ID_COLUMN]: json.loads(row["emitted_node_json"]) for row in audits
        }
        edges = {
            json.loads(row["emitted_edge_json"])[OBJECT_COLUMN]: json.loads(row["emitted_edge_json"]) for row in audits
        }
        old = {
            (row[SUBJECT_COLUMN], row[PREDICATE_COLUMN], row[OBJECT_COLUMN])
            for row in (json.loads(item["original_edge_json"]) for item in audits)
        }
        found_nodes, found_edges = Counter(), Counter()
        type_count = 0
        for row in graph_rows(directory / "nodes.tsv", quoting=quoting):
            if row[ID_COLUMN] == isolation_categories.ATTRIBUTE_TYPE and nodes:
                if row[CATEGORY_COLUMN] != ONTOLOGY_CLASS_CATEGORY:
                    _fail("local source attribute type changed")
                type_count += 1
            expected = nodes.get(row[ID_COLUMN])
            if expected is not None:
                if any(row.get(key, "") != value for key, value in expected.items()):
                    _fail("retained observation node changed")
                found_nodes[row[ID_COLUMN]] += 1
        for row in graph_rows(directory / "edges.tsv", quoting=quoting):
            if row[SUBJECT_COLUMN] in nodes:
                _fail("unreviewed assertion from unresolved source observation")
            if (row[SUBJECT_COLUMN], row[PREDICATE_COLUMN], row[OBJECT_COLUMN]) in old:
                _fail("suppressed NCIT location claim was reintroduced")
            expected = edges.get(row[OBJECT_COLUMN])
            if expected is not None:
                if any(row.get(key, "") != value for key, value in expected.items()):
                    _fail("retained observation edge changed")
                found_edges[row[OBJECT_COLUMN]] += 1
        if found_nodes != Counter({key: 1 for key in nodes}) or found_edges != Counter({key: 1 for key in edges}):
            _fail("retained observation node/edge missing or duplicated")
        if nodes and type_count != 1:
            _fail("local source attribute type missing or duplicated")


def prepare(transform, *, native_observer=None):
    """Own the actual raw read; a caller cannot substitute cached payload for native bytes."""
    with transform.consume_input(REQUIRED_INPUTS[0], POLICY_PATH) as stream:
        policy = load_policy(stream)
    with transform.consume_input(ROLES[1], isolation_categories.MAPPING_PATH) as stream:
        _mapping(stream, policy)
    with transform.consume_input(ROLES[2], Path(transform.input_base_dir) / _SOURCE) as stream:
        payload = json.load(stream)
        selected = _selected(_records(payload), policy)
        if native_observer is not None:
            native_observer(payload)
    bindings = _bindings(transform.consumed_input_snapshots, transform.input_base_dir)
    guard = ClaimGuard(transform.input_base_dir, policy, selected, bindings)
    transform._ncit_category_claim_guard = guard
    return guard, payload


def verify_recorded(contract, snapshots, raw_dir, output_dir, *, members=None, admission=None):
    """Rebuild a finite contract from actual native bytes, never a receipt's claimed occurrence count."""
    admission = admission or SourceAdmission()
    bindings = _bindings(snapshots, raw_dir)
    for role, path in _paths(raw_dir).items():
        if admission.capture(path)["sha256"] != bindings[role]["sha256"]:
            _fail("native input no longer matches original read")
    with POLICY_PATH.open() as stream:
        policy = load_policy(stream)
    with isolation_categories.MAPPING_PATH.open(newline="") as stream:
        _mapping(stream, policy)
    with (Path(raw_dir) / _SOURCE).open("rb") as stream:
        selected = _selected(_native_records(stream), policy)
    guard = ClaimGuard(raw_dir, policy, selected, bindings, completed=True, admission=admission)
    if contract != guard.contract:
        _fail("recorded native contract missing or differs from actual source")
    if members is not None and set(members) != {"nodes.tsv", "edges.tsv"}:
        _fail("recorded graph member scope changed")
    for path in (Path(output_dir) / name for name in ("nodes.tsv", "edges.tsv", AUDIT_FILE)):
        admission.capture(path)
    guard.verify(snapshots, output_dir=output_dir)
    # Bind the already-admitted scientific scope through later metadata-only
    # checkpoints; input/output byte identities remain retained by admission.
    admission.capture_resolution(lambda: _bindings(snapshots, raw_dir))
    admission.verify(metadata_only=True)
    return guard
