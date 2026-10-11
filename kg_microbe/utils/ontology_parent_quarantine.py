"""
Quarantine fourteen reviewed native named parents, without changing node categories.

The unrelated one-parent FOODON kernel policy remains a separate authority. This
module's converter receipt is a byte-bound trace, not an independent ontology.
"""

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

from lxml import etree

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import compact_identifier

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/ontology_parent_dispositions.json"
POLICY_SHA256 = "3ca87a061038361b48541bc33c33ee72c1ed4baf421b891886274dfbc02c1552"
POLICY_ROLE = "ontology_parent_disposition_policy"
AUDIT_FILE = "ontology_parent_dispositions.tsv"
SUPPLIERS = frozenset({"foodon", "envo"})
CORE = (
    SUBJECT_COLUMN,
    PREDICATE_COLUMN,
    OBJECT_COLUMN,
    RELATION_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    KNOWLEDGE_LEVEL_COLUMN,
    AGENT_TYPE_COLUMN,
)
KEYS = CORE[:4]
AUDIT_FIELDS = (
    "ontology",
    "source_file",
    "normalization_input_row_json",
    "canonical_prior_row_json",
    "disposition",
    "rationale",
    "category_action",
    "remaining_native_expression_caveat",
    "native_assertion_json",
    "native_context_json",
    "policy_sha256",
    "consumed_inputs_json",
)
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_OWL = "{http://www.w3.org/2002/07/owl#}"
_RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"


def canonical(value):
    """Serialize the whole claim, preserving every original field and multiplicity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    """Return a formatting-independent hash of complete interpreted evidence."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unique_object(pairs):
    """Reject overwritten native or policy evidence rather than taking the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate ontology parent-disposition JSON key")
        result[key] = value
    return result


def _identifier(value):
    compact = compact_identifier(value)
    # KGX's historical COB contraction is finite, not a new graph-ID rewrite.
    if compact == "OBO:COB_0000022":
        return "COB:0000022"
    return compact


def _key(row):
    return tuple(_identifier(row[column]) for column in KEYS)


def _native_key(row):
    relation = "rdfs:subClassOf" if row["pred"] == "is_a" else _identifier(row["pred"])
    return _identifier(row["sub"]), relation, _identifier(row["obj"])


def _role(name, kind):
    return f"ontology_parent_{name}_{kind}"


def native_input_contract(members=()):
    """Compose this sibling contract without widening native-RO or kernel semantics."""
    return {
        "version": 1,
        "audit": AUDIT_FILE,
        "policy_sha256": POLICY_SHA256,
        "category_action": "unchanged",
        "members": sorted(members),
    }


def load_policy(stream):
    """Bind all fourteen exact source claims and the independently reviewed native contexts."""
    policy = json.load(stream, object_pairs_hook=unique_object)
    if digest(policy) != POLICY_SHA256 or set(policy["sources"]) != SUPPLIERS:
        raise ValueError("Unreviewed ontology parent disposition policy")
    if [len(policy["sources"][name]["quarantines"]) for name in ("foodon", "envo")] != [13, 1]:
        raise ValueError("Ontology parent disposition scope is not thirteen FOODON plus one ENVO")
    return policy


def _descendants(children, starts):
    found, todo = set(starts), list(starts)
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def json_context(document, spec):
    """Reconstruct complete selected declarations, parents, axioms and native descendant scope."""
    graphs = document.get("graphs")
    if not isinstance(graphs, list) or not graphs:
        raise ValueError("Missing ontology parent-disposition native graph")
    roots = {row["subject"] for row in spec["quarantines"]}
    nodes = [node for graph in graphs for node in graph.get("nodes", [])]
    edges = [edge for graph in graphs for edge in graph.get("edges", [])]
    present = {_identifier(node["id"]) for node in nodes} & roots
    touched = any(_native_key(edge)[0] in roots or _native_key(edge)[2] in roots for edge in edges)
    if not present and not touched:
        return None
    if present != roots:
        raise ValueError("Partial ontology parent-disposition native cohort")
    selected, cohort = set(spec["context_ids"]), set(spec["incident_ids"])
    context = {
        "graphs": [{key: graph[key] for key in ("id", "meta") if key in graph} for graph in graphs],
        "nodes": sorted((node for node in nodes if _identifier(node["id"]) in selected), key=canonical),
        "edges": sorted(
            (
                edge
                for edge in edges
                if _native_key(edge)[0] in selected or _native_key(edge)[0] in cohort or _native_key(edge)[2] in cohort
            ),
            key=canonical,
        ),
        "logical_definitions": sorted(
            (
                axiom
                for graph in graphs
                for axiom in graph.get("logicalDefinitionAxioms", [])
                if _identifier(axiom["definedClassId"]) in selected
            ),
            key=canonical,
        ),
    }
    if digest(context) != spec["json_context_sha256"]:
        raise ValueError("Ontology parent native declarations/axioms changed or duplicated")
    children = defaultdict(set)
    for edge in edges:
        subject, relation, target = _native_key(edge)
        if relation == "rdfs:subClassOf":
            children[target].add(subject)
    if _descendants(children, roots) != set(spec["descendant_ids"]):
        raise ValueError("Ontology parent native descendant/alternate-ancestry scope changed")
    expected = Counter((row["subject"], "rdfs:subClassOf", row["parent"]) for row in spec["quarantines"])
    actual = Counter(_native_key(edge) for edge in edges if _native_key(edge) in expected)
    if actual != expected:
        raise ValueError("Ontology parent native assertion multiplicity changed")
    native_incidence = Counter(
        _native_key(edge) for edge in edges if _native_key(edge)[0] in cohort or _native_key(edge)[2] in cohort
    )
    projected_incidence = Counter(
        (_identifier(row[SUBJECT_COLUMN]), _identifier(row[RELATION_COLUMN]), _identifier(row[OBJECT_COLUMN]))
        for row in spec["source_incidence"]
    )
    if native_incidence != projected_incidence:
        raise ValueError("Ontology parent source incidence is not the complete literal native relation cohort")
    return context


def _xml_record(element):
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": (element.text or "").strip(),
        "children": [_xml_record(child) for child in element if isinstance(child.tag, str)],
    }


def owl_context(stream, spec):
    """Keep complete class expressions and annotated axioms, including unsolved intersections."""
    binary = getattr(stream, "buffer", stream)
    tree = etree.parse(binary, etree.XMLParser(resolve_entities="internal", no_network=True, load_dtd=False))
    selected = set(spec["context_ids"])
    classes, axioms, children = [], [], defaultdict(set)
    for element in tree.iter(_OWL + "Class"):
        identifier = _identifier(element.get(_RDF + "about", ""))
        if not identifier or not len(element):
            continue
        if identifier in selected:
            classes.append(_xml_record(element))
        for parent in element.findall(_RDFS + "subClassOf"):
            target = parent.get(_RDF + "resource")
            if target:
                children[_identifier(target)].add(identifier)
    for element in tree.iter(_OWL + "Axiom"):
        source = element.find(_OWL + "annotatedSource")
        if source is not None and _identifier(source.get(_RDF + "resource", "")) in selected:
            axioms.append(_xml_record(element))
    result = {"classes": sorted(classes, key=canonical), "annotated_axioms": sorted(axioms, key=canonical)}
    roots = {row["subject"] for row in spec["quarantines"]}
    if digest(result) != spec["owl_context_sha256"]:
        raise ValueError("Ontology parent native OWL class/annotation evidence changed")
    if _descendants(children, roots) != set(spec["descendant_ids"]):
        raise ValueError("Ontology parent native OWL descendant scope changed")
    return result


def _payload(row):
    # Canonical schema may append blank columns. No nonempty field is discarded.
    if any(not isinstance(value, str) for value in row.values()) or not set(CORE) <= set(row):
        raise ValueError("Malformed ontology parent canonical assertion")
    return canonical({key: value for key, value in row.items() if value != ""})


def _counter(rows):
    return Counter(_payload(row) for row in rows)


def _incident(row, spec):
    cohort = set(spec["incident_ids"])
    return _identifier(row[SUBJECT_COLUMN]) in cohort or _identifier(row[OBJECT_COLUMN]) in cohort


def _reject_key(record):
    return record["subject"], "biolink:subclass_of", record["parent"], "rdfs:subClassOf"


def _expected_rows(spec, retained=False):
    rejected = {_reject_key(row) for row in spec["quarantines"]}
    return [row for row in spec["source_incidence"] if not retained or _key(row) not in rejected]


def _read_tsv(payload, *, fields=None, quoting=csv.QUOTE_NONE):
    previous_limit = csv.field_size_limit()
    try:
        # Complete native context exceeds CSV's 128 KiB default. Bound the parser
        # to this already captured receipt, then restore the caller's global limit.
        csv.field_size_limit(max(previous_limit, len(payload)))
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8"), newline=""), delimiter="\t", quoting=quoting)
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or (fields is not None and tuple(header) != tuple(fields)):
            raise ValueError("Malformed ontology parent TSV header")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError("Malformed ontology parent TSV row width")
        return rows
    finally:
        csv.field_size_limit(previous_limit)


def _validate_original(original, prior, name):
    """Independently check every raw assertion field; only generated UUID is non-native trace."""
    candidate = dict(original)
    converter_id = candidate.pop("id", "")
    if converter_id:
        UUID(converter_id)
    source = candidate.pop("knowledge_source", "")
    aliases = {"", f"{name}.json", f"{name}_removed_subset.json", f"infores:{name}"}
    if source not in aliases:
        raise ValueError("Ontology parent original converter provenance is unsupported")
    primary = candidate.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN, source)
    if primary not in aliases:
        raise ValueError("Ontology parent original primary provenance is unsupported")
    candidate[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = f"infores:{name}"
    for column in CORE:
        candidate.setdefault(column, "")
    if _payload(candidate) != _payload(prior):
        raise ValueError("Ontology parent original claim contains unproved scientific/evidence fields")


def _audit_row(policy, name, record, original, prior, evidence, identities):
    return {
        "ontology": name,
        "source_file": f"{name}_edges.tsv",
        "normalization_input_row_json": canonical(original),
        "canonical_prior_row_json": canonical(prior),
        "disposition": "quarantined_contradictory_native_named_parent",
        "rationale": record["rationale"],
        "category_action": "unchanged_by_parent_edge_policy",
        "remaining_native_expression_caveat": record["remaining_native_expression_caveat"],
        "native_assertion_json": canonical(record["native_assertion"]),
        "native_context_json": canonical(evidence),
        "policy_sha256": digest(policy),
        "consumed_inputs_json": canonical(identities),
    }


def _identities_for(snapshots, name, active):
    roles = [POLICY_ROLE, _role(name, "json"), _role(name, "converter_rows")]
    if active and name == "foodon":
        roles.append(_role(name, "owl"))
    return {role: snapshots[role] for role in roles}


def requires_authority(name, frame):
    """Refuse unguarded finite normalization; this read never grants scientific authority."""
    with POLICY_FILE.open(encoding="utf-8") as stream:
        spec = load_policy(stream)["sources"][name]
    return any(_incident(row, spec) for row in frame.to_dict("records"))


class OntologyParentQuarantine:
    """Own original native reads, converter traces and a finite edge-only quarantine."""

    def __init__(self, transform, audit_stream):
        """Consume the policy for every invocation, including a truthful unrelated-source run."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        self.transform = transform
        self._inputs = SourceAdmission()
        with transform.consume_input(POLICY_ROLE, POLICY_FILE) as stream:
            self.policy = load_policy(stream)
        self.identities = {POLICY_ROLE: transform.consumed_input_snapshots[POLICY_ROLE]}
        if self._inputs.capture(POLICY_FILE)["sha256"] != self.identities[POLICY_ROLE]["sha256"]:
            raise ValueError("Ontology parent policy changed between immutable read and locator admission")
        self.prepared = {}
        self.receipts = {}
        self.projected = set()
        self.writer = csv.DictWriter(audit_stream, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        self.writer.writeheader()
        # Capture object linkage as well as contents; an emptied cache is not a new empty run.
        objects = (self.policy, self.identities, self.prepared, self.receipts, self.projected, self._inputs)
        sealed = None
        failed = False

        def state():
            """Seal both interpreted evidence and original input locator admission."""
            admitted = [
                sorted((str(path), value) for path, value in self._inputs.identities.items()),
                sorted((str(path), value) for path, value in self._inputs.stamps.items()),
                sorted((str(path), str(value)) for path, value in self._inputs.bindings.items()),
            ]
            return canonical(
                [self.policy, self.identities, self.prepared, self.receipts, sorted(self.projected), admitted]
            )

        def check():
            """Reject cached-state mutation permanently rather than accepting a new baseline."""
            nonlocal failed
            if (
                failed
                or any(
                    current is not original
                    for current, original in zip(
                        (self.policy, self.identities, self.prepared, self.receipts, self.projected, self._inputs),
                        objects,
                        strict=True,
                    )
                )
                or state() != sealed
            ):
                failed = True
                raise ValueError("Ontology parent cached scope/evidence changed after admission")

        def seal():
            """Advance expected state only after the next successful original read or projection."""
            nonlocal sealed
            sealed = state()

        def fail(message):
            """Keep scientific admission failures sticky through later lifecycle checks."""
            nonlocal failed
            failed = True
            raise ValueError(message)

        self._check_state, self._seal_state = check, seal
        self._fail = fail
        seal()
        transform._ontology_parent_input_contract = self

    def _remember(self, role, path):
        identity = self.transform.consumed_input_snapshots[role]
        if self._inputs.capture(path)["sha256"] != identity["sha256"]:
            self._fail("Ontology parent input changed after its actual read")
        self.identities[role] = identity

    def prepare_source(self, name, path):
        """Prove the original authority before existing private-copy sanitation touches it."""
        self.verify_bindings()
        if name not in SUPPLIERS or name in self.prepared:
            raise ValueError("Ontology parent supplier selected more than once or unsupported")
        role = _role(name, "json")
        with self.transform.consume_input(role, path) as stream:
            document = json.load(stream, object_pairs_hook=unique_object)
        evidence = json_context(document, self.policy["sources"][name])
        self._remember(role, path)
        if evidence is not None:
            context = {"json": evidence, "owl": None}
            if name == "foodon":
                role = _role(name, "owl")
                with self.transform.consume_input(role, self.transform.input_base_dir / "foodon.owl") as stream:
                    context["owl"] = owl_context(stream, self.policy["sources"][name])
                self._remember(role, self.transform.input_base_dir / "foodon.owl")
            self.prepared[name] = context
        else:
            self.prepared[name] = None
        self._seal_state()

    def prepare_normalization(self, name, path):
        """Keep actual full converter rows under an immutable derived-input receipt."""
        self.verify_bindings()
        if name not in self.prepared or name in self.receipts:
            raise ValueError("Ontology parent normalization has no unique original native read")
        payload = Path(path).read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        private = self.transform.output_dir / ".ontology-inputs" / "parent-converter" / sha / Path(path).name
        with atomic_write(private, "wb") as stream:
            stream.write(payload)
        role = _role(name, "converter_rows")
        with self.transform.consume_input(role, private) as stream:
            rows = _read_tsv(stream.buffer.read(), quoting=csv.QUOTE_MINIMAL)
        self._remember(role, private)
        spec = self.policy["sources"][name]
        self.receipts[name] = [row for row in rows if _incident(row, spec)]
        self._seal_state()

    def project(self, name, frame, originals):
        """Remove precisely reviewed full claim rows, returning all other values untouched."""
        self.verify_bindings()
        if name not in self.receipts or name in self.projected:
            raise ValueError("Ontology parent projection lacks unique native/converter receipts")
        spec = self.policy["sources"][name]
        selected = [(index, row) for index, row in frame.iterrows() if _incident(row, spec)]
        active = self.prepared[name] is not None
        expected = _counter(_expected_rows(spec)) if active else Counter()
        if _counter(row.to_dict() for _, row in selected) != expected:
            raise ValueError("Ontology parent full emitted finite incidence changed")
        source_rows = [originals.loc[index].to_dict() for index, _ in selected]
        if Counter(map(canonical, source_rows)) != Counter(map(canonical, self.receipts[name])):
            raise ValueError("Ontology parent original rows/multiplicity differ from converter receipt")
        rejected = {_reject_key(row): row for row in spec["quarantines"]}
        dropping = []
        identities = _identities_for(self.identities, name, active)
        for index, prior_series in selected:
            original, prior = originals.loc[index].to_dict(), prior_series.to_dict()
            _validate_original(original, prior, name)
            record = rejected.get(_key(prior))
            if record is not None:
                self.writer.writerow(
                    _audit_row(self.policy, name, record, original, prior, self.prepared[name], identities)
                )
                dropping.append(index)
        if len(dropping) != (len(rejected) if active else 0):
            raise ValueError("Ontology parent quarantine count differs from native claims")
        self.projected.add(name)
        self._seal_state()
        return frame.drop(index=dropping)

    def verify_bindings(self):
        """Refuse cache/role mutation without rebaselining any selected native authority."""
        self._check_state()
        if digest(self.policy) != POLICY_SHA256:
            self._fail("Ontology parent interpreted policy changed")
        for role, identity in self.identities.items():
            if self.transform.consumed_input_snapshots.get(role) != identity:
                self._fail(f"Ontology parent consumed role changed: {role}")
        try:
            self._inputs.verify(metadata_only=True)
        except ValueError:
            self._fail("Ontology parent original input admission changed")

    def member_names(self):
        """Return only this invocation's native-selected pair names, never directory-glob scope."""
        self.verify_bindings()
        return tuple(sorted(f"{name}_{kind}.tsv" for name in self.prepared for kind in ("nodes", "edges")))

    def verify_complete(self):
        """Require every prepared supplier, and check retained full rows before publication."""
        self.verify_bindings()
        if set(self.prepared) != self.projected or set(self.receipts) != self.projected:
            raise ValueError("Ontology parent supplier was not completely projected")
        for name, evidence in self.prepared.items():
            rows = _read_tsv((self.transform.output_dir / f"{name}_edges.tsv").read_bytes(), quoting=csv.QUOTE_MINIMAL)
            actual = _counter(row for row in rows if _incident(row, self.policy["sources"][name]))
            expected = _counter(_expected_rows(self.policy["sources"][name], True)) if evidence else Counter()
            if actual != expected:
                raise ValueError("Ontology parent actual retained graph differs from exact finite projection")
        self.transform.verify_consumed_inputs()


def verify_audit_bindings(directory, snapshots, *, members, admission=None, graph_quoting=csv.QUOTE_NONE):
    """Rejoin explicit published members, original authorities and every full audit cell."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    guard = admission if admission is not None else SourceAdmission()
    original_snapshots = canonical(snapshots)
    original_members = tuple(sorted(members))

    def bound_state():
        """Retain caller-owned original role and explicit selected-member bindings."""
        return canonical(snapshots), tuple(sorted(members))

    guard.capture_resolution(bound_state)
    if any(Path(name).name != name for name in original_members):
        raise ValueError("Ontology parent source members must be exact local basenames")

    def read(role):
        """Read exactly the previously consumed role, with no substitute authority lookup."""
        identity = snapshots.get(role)
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256"}:
            raise ValueError(f"Missing ontology parent input role: {role}")
        payload = guard.capture(identity["path"], retain=True)
        if hashlib.sha256(payload).hexdigest() != identity["sha256"]:
            raise ValueError(f"Changed ontology parent input role: {role}")
        return payload

    policy = load_policy(io.StringIO(read(POLICY_ROLE).decode()))
    audit = _read_tsv(
        guard.capture(Path(directory) / AUDIT_FILE, retain=True), fields=AUDIT_FIELDS, quoting=csv.QUOTE_MINIMAL
    )
    expected_audit = []
    for name in sorted(SUPPLIERS):
        edge_name, node_name = f"{name}_edges.tsv", f"{name}_nodes.tsv"
        selected = edge_name in original_members or node_name in original_members
        consumed = _role(name, "json") in snapshots
        if selected != consumed or (selected and not {edge_name, node_name} <= set(original_members)):
            raise ValueError("Ontology parent selected members/native role scope differ")
        if not selected:
            if any(_role(name, suffix) in snapshots for suffix in ("owl", "converter_rows")):
                raise ValueError("Unselected ontology parent supplier has active receipts")
            continue
        spec = policy["sources"][name]
        evidence = json_context(json.loads(read(_role(name, "json")), object_pairs_hook=unique_object), spec)
        if evidence is not None:
            evidence = {"json": evidence, "owl": None}
            if name == "foodon":
                evidence["owl"] = owl_context(io.BytesIO(read(_role(name, "owl"))), spec)
        elif _role(name, "owl") in snapshots:
            raise ValueError("Empty ontology parent source has an unexpected active OWL role")
        raw_rows = _read_tsv(read(_role(name, "converter_rows")), quoting=csv.QUOTE_MINIMAL)
        originals = [row for row in raw_rows if _incident(row, spec)]
        expected = _expected_rows(spec) if evidence else []
        expected_by_key = {_key(row): row for row in expected}
        if len(expected_by_key) != len(expected) or Counter(map(_key, originals)) != Counter(map(_key, expected)):
            raise ValueError("Ontology parent converter receipt differs from complete native finite incidence")
        originals_by_key = {_key(row): row for row in originals}
        for original in originals:
            _validate_original(original, expected_by_key[_key(original)], name)
        identities = _identities_for(snapshots, name, evidence is not None)
        for record in spec["quarantines"] if evidence else []:
            key = _reject_key(record)
            # Reconstruct canonical pre-normalization schema from the exact converter
            # header and producer CORE; blank finalizer-added columns are not invented.
            prior = {column: expected_by_key[key].get(column, "") for column in CORE}
            expected_audit.append(_audit_row(policy, name, record, originals_by_key[key], prior, evidence, identities))
        rows = _read_tsv(guard.capture(Path(directory) / edge_name, retain=True), quoting=graph_quoting)
        retained = _counter(row for row in rows if _incident(row, spec))
        if retained != (_counter(_expected_rows(spec, True)) if evidence else Counter()):
            raise ValueError("Ontology parent retained graph/authority full-row mismatch")
        nodes = _read_tsv(guard.capture(Path(directory) / node_name, retain=True), quoting=graph_quoting)
        present = {_identifier(row["id"]) for row in nodes} & set(spec["incident_ids"])
        if present != (set(spec["incident_ids"]) if evidence else set()):
            raise ValueError("Ontology parent retained node declaration scope changed")
    if Counter(map(canonical, audit)) != Counter(map(canonical, expected_audit)):
        raise ValueError("Ontology parent mandatory audit differs from complete native/converter evidence")
    if original_snapshots != canonical(snapshots):
        raise ValueError("Ontology parent receipt mutated during native rejoin")
    guard.verify(metadata_only=True)
    return guard


class RecordedParentBinding:
    """Retain the original selected roles/scope after a genuine fresh-instance repeat."""

    def __init__(self, transform, contract):
        """Capture immutable expected state only after the public recorded verifier has passed."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        members = tuple(contract.get("members", ()))
        allowed = {f"{name}_{kind}.tsv" for name in SUPPLIERS for kind in ("nodes", "edges")}
        if contract != native_input_contract(members) or len(members) != len(set(members)) or set(members) - allowed:
            raise ValueError("Ontology parent recorded contract changed")
        selected = {name for name in SUPPLIERS if f"{name}_edges.tsv" in members}
        if set(members) != {f"{name}_{kind}.tsv" for name in selected for kind in ("nodes", "edges")}:
            raise ValueError("Ontology parent recorded supplier member pair incomplete")
        snapshots = transform.consumed_input_snapshots
        roles = {
            role: value
            for role, value in snapshots.items()
            if role == POLICY_ROLE or role.startswith("ontology_parent_")
        }
        expected_roles = {POLICY_ROLE} | {_role(name, kind) for name in selected for kind in ("json", "converter_rows")}
        optional = {_role("foodon", "owl")} if "foodon" in selected else set()
        if not expected_roles <= set(roles) or set(roles) - expected_roles - optional:
            raise ValueError("Ontology parent recorded original role scope changed")
        sealed_roles = canonical(roles)
        sealed_contract = canonical(contract)
        inputs = SourceAdmission()
        for identity in roles.values():
            if inputs.capture(identity["path"])["sha256"] != identity["sha256"]:
                raise ValueError("Ontology parent restored original input changed")

        def input_state():
            """Keep complete input-only locator/stamp guards after fresh-instance restoration."""
            return canonical(
                [
                    sorted((str(path), value) for path, value in inputs.identities.items()),
                    sorted((str(path), value) for path, value in inputs.stamps.items()),
                    sorted((str(path), str(value)) for path, value in inputs.bindings.items()),
                ]
            )

        sealed_inputs = input_state()
        self.transform, self.contract = transform, json.loads(sealed_contract)
        original_contract = self.contract
        failed = False

        def check():
            """Recheck original role, scope and input-only admission without rebaselining."""
            nonlocal failed
            current = {
                role: value
                for role, value in transform.consumed_input_snapshots.items()
                if role == POLICY_ROLE or role.startswith("ontology_parent_")
            }
            if (
                failed
                or self.contract is not original_contract
                or canonical(self.contract) != sealed_contract
                or canonical(current) != sealed_roles
                or input_state() != sealed_inputs
            ):
                failed = True
                raise ValueError("Ontology parent restored role/contract binding changed")
            try:
                inputs.verify(metadata_only=True)
            except ValueError:
                failed = True
                raise

        self._check = check
        self._members = members

    def verify_bindings(self):
        """Refuse changed cached contract or selected role identities without rebaselining."""
        self._check()
        if list(self._members) != self.contract["members"]:
            raise ValueError("Ontology parent restored member scope changed")

    def member_names(self):
        """Keep exact recorded selected members through publication and repeated finalization."""
        self.verify_bindings()
        return self._members
