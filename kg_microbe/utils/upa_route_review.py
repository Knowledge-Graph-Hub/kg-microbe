"""UPA-local complete evidence; unverified computed GO substitutions stay audit-only."""

import csv
import hashlib
import io
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    GO_REFERENCE_CONTEXT_COLUMN,
    KNOWLEDGE_ASSERTION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    OBJECT_COLUMN,
    PART_OF_PREDICATE,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATED_TO_PREDICATE,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.go_authority import GoAuthority, GoReferenceError
from kg_microbe.utils.release_binding import graph_release, is_release_source, semsql_go_release
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/upa_reaction_projection_dispositions.json"
POLICY_SHA256 = "6cffa6d569ae82f4c5f4ea3aaf4bca5b495e2915ebf89ddff8fa98343a6bedf2"
AUDIT_FILE = "upa_route_review.tsv"
POLICY_ROLE = "upa_route_policy"
JSON_ROLE = "upa_route_native_json"
OWL_ROLE = "upa_route_native_owl"
GO_ROLE = "upa_route_go_database"
# The go.owl release the locally built go.db comes from; its bytes are pinned, the database's are not (#1420).
GO_SOURCE_ROLE = "upa_route_go_release"
PROCESSED_ROLE = "ontology_metadata_upa"
INTERMEDIATE_ROLE = "upa_route_intermediate_rows"
GENERATED_ROLE = "upa_route_generated_rows"
GRAPH_ROLE = "upa_route_pre_finalization_rows"
ROLES = (
    POLICY_ROLE,
    JSON_ROLE,
    OWL_ROLE,
    GO_ROLE,
    GO_SOURCE_ROLE,
    PROCESSED_ROLE,
    INTERMEDIATE_ROLE,
    GENERATED_ROLE,
    GRAPH_ROLE,
)
AUDIT_FIELDS = ("record_kind", "evidence_json")
MEMBERS = ("upa_nodes.tsv", "upa_edges.tsv")
RULE_KEYS = frozenset(
    {
        ("UPA:UER00367", "UPA:ULS00165", "UPA:UPA00257", "GO:0004420"),
        ("UPA:UER00879", "UPA:ULS00434", "UPA:UPA00904", "GO:0004084"),
        ("UPA:UER00846", "UPA:ULS00420", "UPA:UPA00869", "GO:0102810"),
        ("UPA:UER00712", "UPA:ULS00393", "UPA:UPA00834", "GO:0052622"),
        ("UPA:UER00448", "UPA:ULS00213", "UPA:UPA00051", "GO:0052622"),
        ("UPA:UER00587", "UPA:ULS00278", "UPA:UPA00529", "GO:0033709"),
        ("UPA:UER00134", "UPA:ULS00055", "UPA:UPA00074", "GO:0004077"),
    }
)


def canonical(value):
    """Serialize complete evidence without changing list order or occurrence multiplicity."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    """Hash exact bytes or a complete structured value."""
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def unique_object(pairs):
    """Refuse contradictory native keys rather than silently choosing the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceFinalizationRequired(f"Duplicate UPA evidence key: {key}")
        result[key] = value
    return result


def decode(payload):
    """Read finite JSON evidence strictly, including duplicate outer keys."""

    def invalid(value):
        """Reject non-finite constants in the supplied JSON evidence."""
        raise SourceFinalizationRequired(f"Non-finite UPA evidence value: {value}")

    return json.loads(payload, object_pairs_hook=unique_object, parse_constant=invalid)


def compact(identifier):
    """Normalize only the producer's known identifier spellings, not biological identities."""
    if not isinstance(identifier, str):
        raise SourceFinalizationRequired("UPA identifier must be a string")
    for prefix, replacement in (
        ("http://purl.obolibrary.org/obo/UPa_", "UPA:"),
        ("OBO:UPa_", "UPA:"),
        ("http://purl.obolibrary.org/obo/GO_", "GO:"),
        ("http://purl.obolibrary.org/obo/BFO_", "BFO:"),
    ):
        if identifier.startswith(prefix):
            return replacement + identifier[len(prefix) :]
    return identifier


def load_policy(payload):
    """Require the complete reviewed finite policy; partial/header-only policy is not zero."""
    policy = decode(payload)
    if (
        digest(policy) != POLICY_SHA256
        or policy.get("version") != 3
        or policy.get("computed_projection_disposition") != "audit_only_unverified_xref_substitution"
    ):
        raise SourceFinalizationRequired("UPA reviewed policy changed")
    sources = policy.get("sources")
    if (
        not isinstance(sources, dict)
        or set(sources) != {"upa.json", "upa.owl", "go.db"}
        or set(sources["upa.json"]) != {"release", "sha256"}
        or not isinstance(sources["upa.json"]["release"], str)
        or re.fullmatch(
            r"http://purl\.obolibrary\.org/obo/upa/releases/\d{4}-\d{2}-\d{2}/upa\.owl", sources["upa.json"]["release"]
        )
        is None
        or not isinstance(sources["upa.json"]["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", sources["upa.json"]["sha256"]) is None
        or not isinstance(sources["upa.owl"], str)
        or re.fullmatch(r"[0-9a-f]{64}", sources["upa.owl"]) is None
        or set(sources["go.db"]) != {"release", "source"}
        or not isinstance(sources["go.db"]["release"], str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", sources["go.db"]["release"]) is None
        or not is_release_source(sources["go.db"]["source"])
        or sources["go.db"]["source"]["file"] != "go.owl"
    ):
        raise SourceFinalizationRequired("UPA reviewed source bindings changed")
    keys = [(rule["reaction"], rule["step"], rule["pathway"], rule["canonical_go"]) for rule in policy["rules"]]
    if len(keys) != 7 or set(keys) != RULE_KEYS:
        raise SourceFinalizationRequired("UPA reviewed seven-rule cohort changed")
    return policy


def contract(members=()):
    """Bind the exact selected UPA member pair, including truthful scoped zero."""
    selected = tuple(name for name in MEMBERS if name in members)
    if selected and selected != MEMBERS:
        raise SourceFinalizationRequired("UPA route review requires its exact node/edge member pair")
    return {
        "version": 2,
        "members": list(selected),
        "policy_sha256": POLICY_SHA256,
        "mode": "computed_go_projections_audit_only_no_promotion",
    }


def _resolve(authority, identifier):
    """Preserve unresolved candidate identity as evidence; selected claims still fail closed."""
    try:
        value = authority.resolve(identifier)
    except GoReferenceError as error:
        return {"original_id": identifier, "canonical_id": None, "reason": str(error)}
    return {
        "original_id": value.original_id,
        "canonical_id": value.canonical_id,
        "replacement_chain": list(value.replacement_chain),
        "disposition": value.disposition,
        "definition": value.definition,
        "deprecated": value.deprecated,
        "consider": list(value.consider),
    }


def _authority(connection, identity):
    """Construct the existing GO resolver from the actual read-only admitted SQL snapshot."""
    rows = connection.execute("SELECT subject,predicate,object,value FROM statements WHERE subject LIKE 'GO:%'")
    return GoAuthority.from_statements(rows, authority_path=identity["path"], authority_sha256=identity["sha256"])


def _verify_finite(policy, document, owl_payload, connection, authority):
    """Rejoin complete selected native declarations, premises and GO rows, not just IDs."""
    graph = document["graphs"][0]
    nodes = {compact(node["id"]): node for node in graph["nodes"]}
    finite_ids = {rule["reaction"] for rule in policy["rules"]}
    present = finite_ids & nodes.keys()
    if not present:
        return False
    if present != finite_ids:
        raise SourceFinalizationRequired("UPA finite reaction cohort is incomplete")
    for rule in policy["rules"]:
        for witness in rule["native_nodes"]:
            expected = witness["record"]
            if nodes.get(compact(expected["id"])) != expected:
                raise SourceFinalizationRequired("UPA complete finite native declaration changed")
        for witness in rule["native_edges"]:
            if graph["edges"].count(witness["record"]) != 1:
                raise SourceFinalizationRequired("UPA finite native path changed or duplicated")
        for witness in rule["native_owl"]:
            literal = witness["literal_xml"].encode()
            if digest(literal) != witness["sha256"] or owl_payload.count(literal) != 1:
                raise SourceFinalizationRequired("UPA complete native OWL witness changed")
        if authority.resolve(rule["original_go"]).canonical_id != rule["canonical_go"]:
            raise SourceFinalizationRequired("UPA finite GO identity or alternative-ID history changed")
    identifiers = policy["finite_go_identifiers"]
    placeholders = ",".join("?" for _ in identifiers)
    actual = [
        list(row)
        for row in connection.execute(
            f"SELECT subject,predicate,object,value FROM statements WHERE subject IN ({placeholders})",  # noqa: S608
            identifiers,
        )
    ]
    if Counter(map(canonical, actual)) != Counter(map(canonical, policy["finite_go_statements"])):
        raise SourceFinalizationRequired("UPA complete finite GO authority evidence changed")
    return True


def enumerate_candidates(document, authority, policy):
    """Preserve all native annotation/path occurrences; never promote a candidate to the KG."""
    graphs = document.get("graphs")
    if not isinstance(graphs, list) or len(graphs) != 1:
        raise SourceFinalizationRequired("UPA route review requires one complete native graph")
    graph = graphs[0]
    nodes, positions, xrefs = {}, {}, {}
    for position, node in enumerate(graph["nodes"]):
        identifier = compact(node["id"])
        if identifier in nodes:
            raise SourceFinalizationRequired("UPA native declaration ID is duplicated")
        nodes[identifier], positions[identifier] = node, position
        entries = node.get("meta", {}).get("xrefs", [])
        if not isinstance(entries, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("val"), str) for item in entries
        ):
            raise SourceFinalizationRequired("UPA native xrefs are not complete annotation occurrences")
        xrefs[identifier] = entries
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for position, edge in enumerate(graph["edges"]):
        subject, relation, obj = (compact(edge[field]) for field in ("sub", "pred", "obj"))
        if relation != "BFO:0000050":
            continue
        if subject.startswith("UPA:UER") and obj.startswith("UPA:ULS"):
            incoming[obj].append((position, subject, edge))
        if subject.startswith("UPA:ULS") and obj.startswith("UPA:UPA"):
            outgoing[subject].append((position, obj, edge))
    rules = {(rule["reaction"], rule["step"], rule["pathway"], rule["canonical_go"]): rule for rule in policy["rules"]}
    grouped = defaultdict(list)

    def add(node, pathway, position, *, step=None, premises=()):
        """Retain one native annotation occurrence with its complete route witnesses."""
        value = compact(xrefs[node][position]["val"])
        if not value.startswith("GO:"):
            return
        resolution = _resolve(authority, value)
        predicate = PART_OF_PREDICATE if step else RELATED_TO_PREDICATE
        rule = rules.get((node, step, pathway, resolution["canonical_id"]))
        names = (node, step, pathway) if step else (node,)
        witness = {
            "route": "enzyme_xref_two_hop" if step else "pathway_xref",
            "node": node,
            "step": step,
            "pathway": pathway,
            "xref_position": position,
            "xref": xrefs[node][position],
            "native_nodes": [{"position": positions[name], "record": nodes[name]} for name in dict.fromkeys(names)],
            "native_edges": [{"position": index, "record": edge} for index, edge in premises],
            "go_identity": resolution,
            "exclusion_rule": rule["id"] if rule else None,
        }
        grouped[(value, predicate, pathway)].append(witness)

    for identifier, entries in xrefs.items():
        if identifier.startswith("UPA:UPA"):
            for position in range(len(entries)):
                add(identifier, identifier, position)
    for step, claims in incoming.items():
        for first_position, reaction, first in claims:
            for second_position, pathway, second in outgoing.get(step, ()):
                if any(identifier not in nodes for identifier in (reaction, step, pathway)):
                    raise SourceFinalizationRequired("UPA route endpoint lacks a complete native declaration")
                for position in range(len(xrefs[reaction])):
                    add(
                        reaction,
                        pathway,
                        position,
                        step=step,
                        premises=((first_position, first), (second_position, second)),
                    )
    return [{"key": list(key), "witnesses": grouped[key]} for key in sorted(grouped)]


def _key(row):
    return (compact(row[SUBJECT_COLUMN]), row[PREDICATE_COLUMN], compact(row[OBJECT_COLUMN]))


def _family(row):
    return compact(row.get(SUBJECT_COLUMN, "")).startswith("GO:") and compact(row.get(OBJECT_COLUMN, "")).startswith(
        "UPA:UPA"
    )


def _rows(path, *, quoting=csv.QUOTE_NONE):
    """Read the actual producer/finalized member with strict width and unique columns."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=quoting)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise SourceFinalizationRequired("UPA graph header is invalid")
        for row in reader:
            if None in row or None in row.values():
                raise SourceFinalizationRequired("UPA graph row width is invalid")
            yield row


def _row_counter(rows):
    """Compare complete nonempty graph fields, allowing only absent canonical blank padding."""
    return Counter(canonical({key: value for key, value in row.items() if value != ""}) for row in rows)


def _owned(snapshots):
    """Include the distinct actual converter input without relabelling it as pristine native JSON."""
    return {key: value for key, value in snapshots.items() if key.startswith("upa_route_") or key == PROCESSED_ROLE}


def _processed_locator(identity, native_sha):
    """Require the producer-owned processed member, distinct from the original native file."""
    path = Path(identity["path"])
    if path.name != "upa.json" or path.parent.name != native_sha or path.parent.parent.name != ".ontology-inputs":
        raise SourceFinalizationRequired("UPA processed converter input locator changed")


def _legacy_generated(document, intermediate):
    """Reproduce existing selection only for conservation, never scientific admission."""
    graph = document["graphs"][0]
    native_premises = set()
    for edge in graph["edges"]:
        subject, relation, obj = (compact(edge[field]) for field in ("sub", "pred", "obj"))
        if relation == "BFO:0000050" and (
            (subject.startswith("UPA:UER") and obj.startswith("UPA:ULS"))
            or (subject.startswith("UPA:ULS") and obj.startswith("UPA:UPA"))
        ):
            native_premises.add((subject, PART_OF_PREDICATE, obj, relation))
    observed = set()
    for row in intermediate:
        subject, predicate, obj = _key(row)
        if predicate == PART_OF_PREDICATE and (
            (subject.startswith("UPA:UER") and obj.startswith("UPA:ULS"))
            or (subject.startswith("UPA:ULS") and obj.startswith("UPA:UPA"))
        ):
            observed.add((subject, predicate, obj, compact(row[RELATION_COLUMN])))
    if observed != native_premises:
        raise SourceFinalizationRequired("UPA intermediate path premises do not rejoin the complete native input")
    xrefs = {}
    for node in graph["nodes"]:
        identifier = compact(node["id"])
        values = [item["val"] for item in node.get("meta", {}).get("xrefs", [])]
        if values and identifier not in {compact(value) for value in values}:
            # Existing post_process compacts pathway/UCR keys but leaves UER/ULS as OBO:UPa_.
            key = (
                identifier if identifier.startswith(("UPA:UPA", "UPA:UCR")) else identifier.replace("UPA:", "OBO:UPa_")
            )
            xrefs[key] = values[-1]
    unique_rows = list({canonical(row): row for row in intermediate}.values())
    owners = {}
    for row in sorted(unique_rows, key=lambda value: value[SUBJECT_COLUMN]):
        if (
            row[PREDICATE_COLUMN] == PART_OF_PREDICATE
            and compact(row[SUBJECT_COLUMN]).startswith("UPA:UER")
            and compact(row[OBJECT_COLUMN]).startswith("UPA:ULS")
        ):
            owners[row[OBJECT_COLUMN]] = row[SUBJECT_COLUMN]
    computed = []
    for row in unique_rows:
        if (
            row[PREDICATE_COLUMN] != PART_OF_PREDICATE
            or row[SUBJECT_COLUMN] not in owners
            or not compact(row[OBJECT_COLUMN]).startswith("UPA:UPA")
        ):
            continue
        copied = {**row, SUBJECT_COLUMN: owners[row[SUBJECT_COLUMN]]}
        copied = {key: xrefs.get(value, value) for key, value in copied.items()}
        if str(copied[SUBJECT_COLUMN]).startswith("GO:"):
            computed.append(copied)
    direct = [
        {
            SUBJECT_COLUMN: value,
            PREDICATE_COLUMN: RELATED_TO_PREDICATE,
            OBJECT_COLUMN: identifier,
            RELATION_COLUMN: RELATED_TO_PREDICATE,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: "infores:upa",
            KNOWLEDGE_LEVEL_COLUMN: KNOWLEDGE_ASSERTION,
            AGENT_TYPE_COLUMN: MANUAL_AGENT,
        }
        for identifier, value in xrefs.items()
        if identifier.startswith("UPA:UPA") and value.startswith("GO:")
    ]
    return {"computed": computed, "direct": direct}


def _retained_graph(generated):
    """Model only the existing tail's known identifier/source normalization and full-row dedup."""
    expected = []
    for item in generated:
        for position in item["keep"]:
            row = dict(item["rows"][position])
            for field in (SUBJECT_COLUMN, OBJECT_COLUMN, RELATION_COLUMN):
                row[field] = compact(row[field])
            if row.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN, "") in {"", "upa.json", "upa_removed_subset.json"}:
                row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] = "infores:upa"
            expected.append(row)
    # Equality is full-field equality after canonical blank padding, not triple-only dedup.
    return list(
        {canonical({key: value for key, value in row.items() if value != ""}): row for row in expected}.values()
    )


def _project_go(row, authority):
    """Match only the existing source-finalizer's explicit GO identity/history projection."""
    result = dict(row)
    for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
        identifier = row[column]
        if not compact(identifier).startswith("GO:"):
            continue
        decision = authority.resolve(identifier)
        if identifier == decision.canonical_id:
            continue
        result[column] = decision.canonical_id
        result["original_" + column] = result.get("original_" + column) or identifier
        history = decode(result.get(GO_REFERENCE_CONTEXT_COLUMN) or "[]")
        if not isinstance(history, list):
            raise SourceFinalizationRequired("UPA GO history is not an occurrence list")
        history.append(
            {
                "column": column,
                "original_id": identifier,
                "canonical_id": decision.canonical_id,
                "replacement_chain": list(decision.replacement_chain),
                "authority": authority.authority_path,
                "authority_sha256": authority.authority_sha256,
            }
        )
        result[GO_REFERENCE_CONTEXT_COLUMN] = canonical(history)
    return result


def _screen(records, candidates):
    """Withhold computed xref substitutions, preserving every selected row and native witness."""
    by_key = {tuple(item["key"]): item for item in candidates}
    result, dispositions = [], []
    for position, row in enumerate(records):
        key = _key(row)
        if key not in by_key:
            raise SourceFinalizationRequired(f"UPA generated GO row lacks native route evidence: {key}")
        witnesses = by_key[key]["witnesses"]
        if any(item["go_identity"]["canonical_id"] is None for item in witnesses):
            raise SourceFinalizationRequired("UPA selected GO projection lacks an exact authority identity")
        excluded = [item for item in witnesses if item["exclusion_rule"]]
        if excluded and len(excluded) != len(witnesses):
            raise SourceFinalizationRequired("UPA selected tuple has mixed contradicted/unreviewed routes")
        expected_relation = "BFO:0000050" if key[1] == PART_OF_PREDICATE else RELATED_TO_PREDICATE
        if compact(row[RELATION_COLUMN]) != expected_relation:
            raise SourceFinalizationRequired("UPA generated relation differs from its bounded writer route")
        if excluded:
            disposition = "quarantined_reaction_context"
        elif key[1] == PART_OF_PREDICATE:
            disposition = "audit_only_unverified_xref_substitution"
        else:
            disposition = "retained_direct_weak_xref"
        dispositions.append(
            {
                "position": position,
                "original_row": row,
                "candidate_key": list(key),
                "disposition": disposition,
                "witnesses": witnesses,
            }
        )
        if disposition == "retained_direct_weak_xref":
            result.append(position)
    return result, dispositions


class UPARouteReview:
    """One source-owned run: immutable actual input evidence, audit and sticky validation."""

    def __init__(self, transform, audit_stream):
        """Admit policy for every selected-source run, including a genuine scoped zero."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        self.transform = transform
        self._admission = SourceAdmission()
        self._policy_locator = self._admission.capture_resolution(lambda: str(POLICY_FILE.absolute()))
        self.identities = {}
        self._failure = None
        self._prepared_seal = None
        self._final_seal = None
        self._generated = []
        self._candidate_records = []
        self._document = None
        self._authority = None
        self._intermediate = None
        self._members = ()
        self._writer = csv.DictWriter(audit_stream, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        self._writer.writeheader()
        self.policy = load_policy(self._read(POLICY_ROLE, POLICY_FILE))
        transform._upa_route_input_contract = self

    def _read(self, role, path):
        expected = self._admission.capture(path)
        with self.transform.consume_input(role, path) as stream:
            payload = stream.buffer.read()
        if digest(payload) != expected["sha256"]:
            raise SourceFinalizationRequired("UPA native input changed between binding and consumption")
        self.identities[role] = dict(self.transform.consumed_input_snapshots[role])
        return payload

    def _emit(self, kind, payload):
        self._writer.writerow({"record_kind": kind, "evidence_json": canonical(payload)})

    def _retain(self, role, payload):
        path = self.transform.output_dir / ".upa-route-inputs" / f"{digest(payload)}.json"
        if path.exists() and path.read_bytes() != payload:
            raise SourceFinalizationRequired("UPA owned input hash collision or changed artifact")
        if not path.exists():
            with atomic_write(path, "wb") as stream:
                stream.write(payload)
        if self._read(role, path) != payload:
            raise SourceFinalizationRequired("UPA generated input changed while admitted")

    def member_names(self):
        """Return only the invocation's bound UPA pair after checking original inputs."""
        self.verify_bindings()
        return self._members

    def prepare_source(self, path):
        """Consume original native authority; preprocessing may mutate only the private copy."""
        try:
            self.verify_bindings()
            if self._members:
                raise SourceFinalizationRequired("UPA source selected twice in one invocation")
            payload = self._read(JSON_ROLE, path)
            self._document = decode(payload)
            owl = self._read(OWL_ROLE, self.transform.input_base_dir / "upa.owl")
            # upa.json is converted from the pinned upa.owl by the pinned ROBOT, which reproduces
            # it byte for byte, so its bytes stay pinned as well as its release (#1420, #1516).
            if (
                self.identities[OWL_ROLE]["sha256"] != self.policy["sources"]["upa.owl"]
                or self.identities[JSON_ROLE]["sha256"] != self.policy["sources"]["upa.json"]["sha256"]
                or graph_release(self._document["graphs"][0]) != self.policy["sources"]["upa.json"]["release"]
            ):
                raise SourceFinalizationRequired("UPA selected native source epoch changed")
            go_source = self.policy["sources"]["go.db"]["source"]
            release = self._read(GO_SOURCE_ROLE, self.transform.input_base_dir / go_source["file"])
            if digest(release) != go_source["sha256"]:
                raise SourceFinalizationRequired("UPA GO release file differs from the reviewed release")
            database = self.transform.input_base_dir / "go.db"
            # Read directly, so never rebuilt here; one this toolchain did not build is refused (#1641).
            from kg_microbe.utils.ontology_utils import check_reused_semsql_db

            check_reused_semsql_db(database, self.transform.input_base_dir, strict=True)
            database_identity = self._admission.capture(database)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(database) + suffix)
                if sidecar.exists():
                    raise SourceFinalizationRequired("UPA selected GO database has a live sidecar")
                self._admission.capture(sidecar, optional=True)
            with self.transform.consume_input(GO_ROLE, database) as stream:
                self.identities[GO_ROLE] = dict(self.transform.consumed_input_snapshots[GO_ROLE])
                if database_identity["sha256"] != self.identities[GO_ROLE]["sha256"]:
                    raise SourceFinalizationRequired("UPA selected GO epoch changed")
                with sqlite3.connect(Path(stream.name).as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
                    if semsql_go_release(connection) != self.policy["sources"]["go.db"]["release"]:
                        raise SourceFinalizationRequired("UPA selected GO database is not the reviewed release")
                    self._authority = _authority(connection, self.identities[GO_ROLE])
                    _verify_finite(self.policy, self._document, owl, connection, self._authority)
            self._candidate_records = enumerate_candidates(self._document, self._authority, self.policy)
            self._prepared_seal = digest({"document": self._document, "candidates": self._candidate_records})
            self._members = MEMBERS
            private = self.transform.output_dir / ".ontology-inputs" / digest(payload) / "upa.json"
            with atomic_write(private, "wb") as stream:
                stream.write(payload)
            for candidate in self._candidate_records:
                self._emit("candidate", candidate)
            self.verify_bindings()
            return private
        except BaseException as error:
            self._failure = str(error)
            raise

    def capture_intermediate(self, rows):
        """Bind actual pre-GO writer rows before the legacy helper rewrites its file."""
        try:
            # The enclosing existing consume_input context admitted this file before KGX read it.
            # Preserve that actual receipt; do not relabel the later path check as its first read.
            processed = self.transform.consumed_input_snapshots.get(PROCESSED_ROLE)
            if processed is None or PROCESSED_ROLE in self.identities:
                raise SourceFinalizationRequired("UPA actual converter input is missing or reused")
            _processed_locator(processed, self.identities[JSON_ROLE]["sha256"])
            if self._admission.capture(processed["path"])["sha256"] != processed["sha256"]:
                raise SourceFinalizationRequired("UPA processed input changed since the converter read")
            self.identities[PROCESSED_ROLE] = dict(processed)
            self.verify_bindings()
            if not self._members or self._intermediate is not None:
                raise SourceFinalizationRequired("UPA intermediate capture lacks a unique prepared source")
            self._intermediate = decode(canonical(rows))
            self._retain(INTERMEDIATE_ROLE, canonical(rows).encode())
        except BaseException as error:
            self._failure = str(error)
            raise

    def keep_generated(self, records, kind):
        """Screen an existing writer result; never enumerate candidates into new graph rows."""
        try:
            self.verify_bindings()
            if self._intermediate is None or kind not in {"computed", "direct"}:
                raise SourceFinalizationRequired("UPA generated rows lack their actual intermediate input")
            if any(item["kind"] == kind for item in self._generated):
                raise SourceFinalizationRequired("UPA generated family was submitted twice")
            records = decode(canonical(records))
            expected = _legacy_generated(self._document, self._intermediate)[kind]
            if _row_counter(records) != _row_counter(expected):
                raise SourceFinalizationRequired("UPA original generated family differs from the actual writer inputs")
            keep, dispositions = _screen(records, self._candidate_records)
            self._generated.append({"kind": kind, "rows": records, "keep": keep, "dispositions": dispositions})
            for disposition in dispositions:
                self._emit(
                    "generated",
                    {
                        "kind": kind,
                        **disposition,
                        "expected_normalized_candidate": _project_go(disposition["original_row"], self._authority),
                    },
                )
            return keep
        except BaseException as error:
            self._failure = str(error)
            raise

    def finish_source(self, nodes_path, edges_path):
        """Seal the actual pre-finalization source family without altering any graph row."""
        try:
            self.verify_bindings()
            if self._final_seal is not None or {item["kind"] for item in self._generated} != {"computed", "direct"}:
                raise SourceFinalizationRequired("UPA source completion lacks both original writer families")
            if (Path(nodes_path).name, Path(edges_path).name) != MEMBERS:
                raise SourceFinalizationRequired("UPA source completion member scope changed")
            expected = _retained_graph(self._generated)
            actual = [row for row in _rows(edges_path, quoting=csv.QUOTE_MINIMAL) if _family(row)]
            if _row_counter(actual) != _row_counter(expected):
                raise SourceFinalizationRequired("UPA tail lost, changed or reintroduced a generated source claim")
            self._retain(GENERATED_ROLE, canonical(self._generated).encode())
            self._retain(GRAPH_ROLE, canonical(actual).encode())
            self._final_seal = digest(
                {"generated": self._generated, "graph": actual, "intermediate": self._intermediate}
            )
            self.verify_bindings()
        except BaseException as error:
            self._failure = str(error)
            raise

    def verify_bindings(self, *, staged_members=None):
        """Keep observed failures sticky and original roles/selectors fixed through publication."""
        try:
            if self._failure:
                raise SourceFinalizationRequired(f"UPA route review previously failed: {self._failure}")
            if staged_members is not None and contract(staged_members) != contract(self._members):
                raise SourceFinalizationRequired(
                    "UPA explicitly staged member scope differs from the original invocation"
                )
            self._admission.verify(metadata_only=True)
            if hasattr(self, "policy") and digest(self.policy) != POLICY_SHA256:
                raise SourceFinalizationRequired("UPA cached finite policy changed")
            actual = _owned(self.transform.consumed_input_snapshots)
            if actual != self.identities:
                raise SourceFinalizationRequired("UPA original consumed roles disappeared or were rebound")
            if self._members != (MEMBERS if JSON_ROLE in self.identities else ()):
                raise SourceFinalizationRequired("UPA original selected member scope changed")
            if (
                self._prepared_seal is not None
                and digest({"document": self._document, "candidates": self._candidate_records}) != self._prepared_seal
            ):
                raise SourceFinalizationRequired("UPA cached native route evidence changed")
            if self._final_seal is not None:
                graph = decode(Path(self.identities[GRAPH_ROLE]["path"]).read_bytes())
                if (
                    digest({"generated": self._generated, "graph": graph, "intermediate": self._intermediate})
                    != self._final_seal
                ):
                    raise SourceFinalizationRequired("UPA completed producer evidence changed")
        except BaseException as error:
            self._failure = str(error)
            raise

    def verify_complete(self):
        """Write an auditable exact zero or complete source contract before audit publication."""
        try:
            self.verify_bindings()
            if bool(self._members) != bool(self._final_seal):
                raise SourceFinalizationRequired("UPA prepared source was not completely emitted")
            self._emit(
                "checkpoint",
                {
                    "contract": contract(self._members),
                    "inputs": self.identities,
                    "candidate_count": len(self._candidate_records),
                    "generated_count": sum(len(item["rows"]) for item in self._generated),
                },
            )
            # This guard certifies its own actual reads. The producer/finalizer separately enforces all policies.
            self._admission.verify(metadata_only=True)
        except BaseException as error:
            self._failure = str(error)
            raise


def verify_audit_bindings(directory, snapshots, *, members, raw_dir, admission=None, graph_quoting=csv.QUOTE_NONE):
    """Independently reconstruct native candidates/audit and preserve exact late admission guards."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    guard = admission if admission is not None else SourceAdmission()
    selected = contract(members)["members"]
    expected_roles = set(ROLES if selected else (POLICY_ROLE,))
    owned = _owned(snapshots)
    if set(owned) != expected_roles:
        raise SourceFinalizationRequired("UPA recorded consumed-role cohort is missing or enlarged")
    if Path(owned[POLICY_ROLE]["path"]) != POLICY_FILE.resolve():
        raise SourceFinalizationRequired("UPA policy original locator changed")
    guard.capture_resolution(lambda: str(POLICY_FILE.resolve()))

    def read(role):
        """Read and bind the exact admitted bytes for one recorded input role."""
        identity = owned[role]
        if set(identity) != {"path", "sha256"}:
            raise SourceFinalizationRequired("UPA consumed-input identity is invalid")
        payload = guard.capture(identity["path"], retain=True)
        if digest(payload) != identity["sha256"]:
            raise SourceFinalizationRequired("UPA consumed authority bytes changed")
        return payload

    policy = load_policy(read(POLICY_ROLE))
    audit_payload = guard.capture(Path(directory) / AUDIT_FILE, retain=True)
    reader = csv.DictReader(io.StringIO(audit_payload.decode()), delimiter="\t")
    records = list(reader)
    if tuple(reader.fieldnames or ()) != AUDIT_FIELDS or any(None in row or None in row.values() for row in records):
        raise SourceFinalizationRequired("UPA producer audit is malformed")
    candidates, generated = [], []
    authority = None
    if selected:
        if raw_dir is None:
            raise SourceFinalizationRequired("UPA admission requires the selected raw directory")
        roles = ((JSON_ROLE, "upa.json"), (OWL_ROLE, "upa.owl"), (GO_ROLE, "go.db"), (GO_SOURCE_ROLE, "go.owl"))
        for role, filename in roles:
            if str(guard.bind_path(Path(raw_dir) / filename)) != owned[role]["path"]:
                raise SourceFinalizationRequired("UPA original native locator/epoch changed")
        if (
            owned[OWL_ROLE]["sha256"] != policy["sources"]["upa.owl"]
            or owned[JSON_ROLE]["sha256"] != policy["sources"]["upa.json"]["sha256"]
            or owned[GO_SOURCE_ROLE]["sha256"] != policy["sources"]["go.db"]["source"]["sha256"]
            or guard.capture(owned[GO_SOURCE_ROLE]["path"])["sha256"] != owned[GO_SOURCE_ROLE]["sha256"]
        ):
            raise SourceFinalizationRequired("UPA original native locator/epoch changed")
        document = decode(read(JSON_ROLE))
        if graph_release(document["graphs"][0]) != policy["sources"]["upa.json"]["release"]:
            raise SourceFinalizationRequired("UPA admitted native JSON is not the reviewed release")
        owl = read(OWL_ROLE)
        _processed_locator(owned[PROCESSED_ROLE], owned[JSON_ROLE]["sha256"])
        decode(read(PROCESSED_ROLE))
        read(GO_ROLE)
        database = Path(owned[GO_ROLE]["path"])
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                raise SourceFinalizationRequired("UPA admitted GO database has a sidecar")
            guard.capture(sidecar, optional=True)
        # The original file remains bound before and after this read-only SQL operation.
        # A file SQLite cannot read is refused like any other contract failure (#1552).
        try:
            with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
                if semsql_go_release(connection) != policy["sources"]["go.db"]["release"]:
                    raise SourceFinalizationRequired("UPA admitted GO database is not the reviewed release")
                authority = _authority(connection, owned[GO_ROLE])
                _verify_finite(policy, document, owl, connection, authority)
        except sqlite3.Error as error:
            raise SourceFinalizationRequired("UPA admitted GO database cannot be read") from error
        candidates = enumerate_candidates(document, authority, policy)
        generated = decode(read(GENERATED_ROLE))
        intermediate = decode(read(INTERMEDIATE_ROLE))
        if (
            not isinstance(intermediate, list)
            or len(generated) != 2
            or {item["kind"] for item in generated} != {"computed", "direct"}
        ):
            raise SourceFinalizationRequired("UPA original writer input/family is incomplete")
        expected_generated = _legacy_generated(document, intermediate)
        for item in generated:
            if _row_counter(item["rows"]) != _row_counter(expected_generated[item["kind"]]):
                raise SourceFinalizationRequired("UPA original generated rows no longer match their actual inputs")
            keep, dispositions = _screen(item["rows"], candidates)
            if item["keep"] != keep or item["dispositions"] != dispositions:
                raise SourceFinalizationRequired("UPA generated evidence does not rejoin native candidates")
        prior = decode(read(GRAPH_ROLE))
        if _row_counter(prior) != _row_counter(_retained_graph(generated)):
            raise SourceFinalizationRequired("UPA retained original graph lost or reintroduced screened claims")
        actual_path = Path(directory) / "upa_edges.tsv"
        guard.capture(actual_path)
        actual = [row for row in _rows(actual_path, quoting=graph_quoting) if _family(row)]
        actual_counter = _row_counter(actual)
        if actual_counter not in (_row_counter(prior), _row_counter(_project_go(row, authority) for row in prior)):
            raise SourceFinalizationRequired("UPA current graph differs from its original/identity-only projected rows")
    expected = [{"record_kind": "candidate", "evidence_json": canonical(row)} for row in candidates]
    for item in generated:
        expected.extend(
            {
                "record_kind": "generated",
                "evidence_json": canonical(
                    {
                        "kind": item["kind"],
                        **row,
                        "expected_normalized_candidate": _project_go(row["original_row"], authority),
                    }
                ),
            }
            for row in item["dispositions"]
        )
    expected.append(
        {
            "record_kind": "checkpoint",
            "evidence_json": canonical(
                {
                    "contract": contract(members),
                    "inputs": owned,
                    "candidate_count": len(candidates),
                    "generated_count": sum(len(item["rows"]) for item in generated),
                }
            ),
        }
    )
    if records != expected:
        raise SourceFinalizationRequired("UPA complete audit differs from actual native/writer evidence")
    guard.verify(metadata_only=True)


class RecordedUPABinding:
    """Restore fixed input-only guards after public validation of a genuine repeat."""

    def __init__(self, transform, recorded):
        """Capture original roles, policy selector, scope and absent SQLite sidecars once."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        if not isinstance(recorded, dict) or recorded != contract(recorded.get("members", ())):
            raise SourceFinalizationRequired("UPA restored contract is missing or changed")
        members = tuple(recorded["members"])
        roles = _owned(transform.consumed_input_snapshots)
        if set(roles) != set(ROLES if members else (POLICY_ROLE,)):
            raise SourceFinalizationRequired("UPA restored original role cohort is incomplete")
        sealed_roles = canonical(roles)
        inputs = SourceAdmission()
        inputs.capture_resolution(lambda: str(POLICY_FILE.resolve()))
        if roles[POLICY_ROLE]["path"] != str(POLICY_FILE.resolve()):
            raise SourceFinalizationRequired("UPA restored policy selector changed")
        for identity in roles.values():
            if inputs.capture(identity["path"])["sha256"] != identity["sha256"]:
                raise SourceFinalizationRequired("UPA restored original authority changed")
        if members:
            for role, filename in ((JSON_ROLE, "upa.json"), (OWL_ROLE, "upa.owl"), (GO_ROLE, "go.db")):
                if str(inputs.bind_path(transform.input_base_dir / filename)) != roles[role]["path"]:
                    raise SourceFinalizationRequired("UPA restored original native locator changed")
            for base in {str(transform.input_base_dir / "go.db"), roles[GO_ROLE]["path"]}:
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(base + suffix)
                    if sidecar.exists():
                        raise SourceFinalizationRequired("UPA restored SQLite sidecar appeared")
                    inputs.capture(sidecar, optional=True)
        failed = False

        def verify(staged_members):
            """Never recapture a changed consumed role or recover an observed failure by restore."""
            nonlocal failed
            try:
                current = _owned(transform.consumed_input_snapshots)
                if failed or canonical(current) != sealed_roles:
                    raise SourceFinalizationRequired("UPA restored original roles changed")
                if staged_members is not None and contract(staged_members) != contract(members):
                    raise SourceFinalizationRequired(
                        "UPA explicitly staged member scope differs from the restored invocation"
                    )
                inputs.verify(metadata_only=True)
            except BaseException:
                failed = True
                raise

        self._verify = verify
        self._members = members

    def member_names(self):
        """Retain exact selected members, not a directory-wide rediscovery."""
        self.verify_bindings()
        return self._members

    def verify_bindings(self, *, staged_members=None):
        """Retain original read guards throughout repeated finalization and late publication."""
        self._verify(staged_members)
