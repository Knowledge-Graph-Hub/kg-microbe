"""Retain a finite native RO cohort upstream without claiming strict Biolink conformance."""

import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/native_ro_predicate_dispositions.json"
POLICY_ROLE = "ontology_native_relation_policy"
AUDIT_FILE = "native_relation_dispositions.tsv"
FINITE_COHORT_SHA256 = "782027979cacfca38d615321ae8849d094e06fe2c03b4f024e988d3bf8fecde7"
# Version 3 binds each authority to its release and reviewed content, not its file bytes (#1420).
POLICY_VERSION = 3
REVIEWED_POLICY_SHA256 = "31575dbca6d691091a928e825a80cbc38e92593608dec2448e9abb1441919ed7"
STRICT_DISPOSITION = "native_predicate_retained_not_strict_biolink_conformant"
_OBO = "http://purl.obolibrary.org/obo/"
_RELATIONS = frozenset(
    {
        "RO:0002216",
        "RO:0002503",
        "RO:0002285",
        "RO:0002488",
        "RO:0002489",
        "RO:0002492",
        "RO:0002493",
        "RO:0002496",
        "RO:0002497",
        "RO:0002082",
        "RO:0002087",
        "RO:0002223",
        "RO:0002229",
        "RO:0002230",
    }
)
_SUPPLIERS = frozenset({"pato", "uberon", "envo", "mondo"})
_AUTHORITY_GRAPHS = {
    "pato.json": _OBO + "pato.owl",
    "uberon.json": _OBO + "uberon.owl",
    "ro.json": _OBO + "ro.owl",
    "envo.json": _OBO + "envo.json",
    "mondo.json": _OBO + "mondo.owl",
}
AUDIT_FIELDS = (
    "ontology",
    "source_file",
    "normalization_input_row_json",
    "canonical_prior_row_json",
    "retained_row_json",
    "native_assertion_json",
    "native_authority",
    "native_authority_sha256",
    "ro_declaration_json",
    "ro_authority",
    "ro_authority_sha256",
    "policy_sha256",
    "projection_action",
    "strict_biolink_disposition",
)


def native_input_contract():
    """Persist the interpretation contract; the immutable audit determines active suppliers."""
    return {"version": 2, "contract": "native_ro_retention_audit", "audit": AUDIT_FILE}


def _unique_object(pairs):
    """Refuse ambiguous native and policy JSON declarations."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate native RO retention JSON key: {key}")
        result[key] = value
    return result


def _json(value):
    """Serialize complete evidence deterministically without changing its values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def selected_content_sha256(name, graph):
    """
    Digest exactly the native content this policy reviewed in one authority graph.

    For RO, that is the 14 reviewed property declarations. For a supplier, it is every
    assertion that uses a reviewed relation: the retained records and the unchanged
    controls. A whole-file digest also bound serialization, and an in-place rewrite
    no release URL can reproduce; this binds the reviewed content itself (#1420).
    """
    if name == "ro":
        nodes = {node["id"]: node for node in graph["nodes"]}
        declarations = [nodes.get(_OBO + relation.replace(":", "_", 1)) for relation in sorted(_RELATIONS)]
        return _digest(_json(declarations).encode())
    edges = [edge for edge in graph["edges"] if compact_identifier(edge["pred"]) in _RELATIONS]
    return _digest(_json(sorted(edges, key=_json)).encode())


def _cohort(policy, name, field="records"):
    """Select exact supplier/SRO membership, never a relation-wide mutation rule."""
    return {(row["subject"], row["relation"], row["object"]): row for row in policy[field] if row["ontology"] == name}


def load_policy(stream):
    """Bind all 516 retained and eight explicitly unchanged exact supplier/triples."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    if _digest(_json(policy).encode()) != REVIEWED_POLICY_SHA256:
        raise ValueError("Unreviewed native RO policy evidence; changing native pins requires independent review")
    if (
        not isinstance(policy, dict)
        or set(policy)
        != {
            "version",
            "authorities",
            "relations",
            "records",
            "reviewed_model",
            "strict_biolink_disposition",
            "finite_cohort_sha256",
            "unchanged_records",
        }
        or policy.get("version") != POLICY_VERSION
        or policy.get("finite_cohort_sha256") != FINITE_COHORT_SHA256
        or not isinstance(policy.get("records"), list)
        or len(policy["records"]) != 516
        or len(policy.get("unchanged_records", [])) != 8
        or _digest(_json(policy["records"]).encode()) != FINITE_COHORT_SHA256
        or policy.get("strict_biolink_disposition") != STRICT_DISPOSITION
        or set(policy.get("authorities", {})) != set(_AUTHORITY_GRAPHS)
        or set(policy.get("relations", {})) != _RELATIONS
    ):
        raise ValueError("Unreviewed native RO retention policy/cohort")
    for filename, authority in policy["authorities"].items():
        source = authority.get("source") if isinstance(authority, dict) else None
        if (
            not isinstance(authority, dict)
            or set(authority) != {"graph_id", "release", "source", "selected_sha256"}
            or authority.get("graph_id") != _AUTHORITY_GRAPHS[filename]
            or not isinstance(authority.get("release"), str)
            or not authority["release"].startswith(_OBO)
            or not re.fullmatch(r"[0-9a-f]{64}", authority.get("selected_sha256", ""))
            or not isinstance(source, dict)
            or set(source) != {"file", "sha256"}
            or not re.fullmatch(r"[a-z]+\.(json|owl)", source.get("file", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", ""))
        ):
            raise ValueError(f"Invalid native RO authority: {filename}")
    for relation, declaration in policy["relations"].items():
        expected = {row["prior_predicate"] for row in policy["records"] if row["relation"] == relation}
        if (
            not isinstance(declaration, dict)
            or set(declaration) != {"prior_predicate", "label", "native_node_sha256"}
            or expected != {declaration.get("prior_predicate")}
            or not isinstance(declaration.get("label"), str)
            or not declaration["label"].strip()
            or not re.fullmatch(r"[0-9a-f]{64}", declaration.get("native_node_sha256", ""))
        ):
            raise ValueError(f"Invalid native RO property contract: {relation}")
    # This identifies the model reviewed when the defect was established, not
    # an assertion that a runtime Toolkit consumed a particular schema file.
    if policy["reviewed_model"] != {
        "version": "4.4.2",
        "sha256": "b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e",
    }:
        raise ValueError("Native RO reviewed-model attribution changed")
    return policy


class NativeROPredicateRetention:
    """Own immutable native evidence and one mandatory producer-wide retention audit."""

    def __init__(self, transform, audit_stream):
        """Consume the real policy even for an invocation with no selected RO assertions."""
        self.transform = transform
        with transform.consume_input(POLICY_ROLE, POLICY_FILE) as stream:
            self.policy = load_policy(stream)
        self._policy_identity = transform.consumed_input_snapshots[POLICY_ROLE]
        # Keep the original binding contract through source finalization, even
        # after the run-owned writer/normalizer has been cleared.
        transform._native_relation_input_contract = self
        self.writer = csv.DictWriter(audit_stream, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        self.writer.writeheader()
        self._native = {}
        self._native_digests = {}
        self._identities = {}
        self._source_identities = {}
        self._ro = None
        self._projected = {}
        self._unchanged_projected = {}

    def _read_native(self, name, path):
        """Parse the exact admitted snapshot, never reopen mutable native bytes."""
        filename = name + ".json"
        role = "ontology_native_relation_" + name
        with self.transform.consume_input(role, path) as stream:
            content = stream.buffer.read()
        expected = self.policy["authorities"][filename]
        document = json.loads(content, object_pairs_hook=_unique_object)
        graphs = document.get("graphs")
        if not isinstance(graphs, list) or len(graphs) != 1 or graphs[0].get("id") != expected["graph_id"]:
            raise ValueError(f"Unexpected native RO authority graph: {path}")
        graph = graphs[0]
        if (graph.get("meta") or {}).get("version") != expected["release"]:
            raise ValueError(f"Unreviewed native RO authority release: {path}")
        self._bind_source(name, Path(path), content)
        nodes = {}
        for node in graph["nodes"]:
            if node["id"] in nodes:
                raise ValueError(f"Duplicate native RO authority node: {node['id']}")
            nodes[node["id"]] = node
        self._identities[name] = self.transform.consumed_input_snapshots[role]
        return graph, nodes, content

    def _bind_source(self, name, path, content):
        """
        Bind the upstream release file this authority is, or was converted from (#1420).

        MONDO and ENVO publish JSON, so the read itself is the release file. RO, PATO
        and UBERON are converted from their OWL release beside it, which is read as
        its own consumed input so a different release cannot hide behind a JSON
        whose reviewed content happens to match.
        """
        source = self.policy["authorities"][name + ".json"]["source"]
        if source["file"] == path.name:
            digest = _digest(content)
        else:
            role = "ontology_native_relation_" + name + "_source"
            with self.transform.consume_input(role, path.with_name(source["file"])) as stream:
                stream.buffer.read()
            self._source_identities[name] = self.transform.consumed_input_snapshots[role]
            digest = self._source_identities[name]["sha256"]
        if digest != source["sha256"]:
            raise ValueError(f"Unreviewed native RO release file: {path.with_name(source['file'])}")

    def _prepare_ro(self, path=None):
        """Require a prepared pinned RO export; absence is not an optional authority."""
        if self._ro is not None:
            if path is not None and Path(path).resolve() != Path(self._identities["ro"]["path"]):
                raise ValueError("Native RO authority path changed within invocation")
            return self._ro
        path = Path(path) if path is not None else self.transform.input_base_dir / "ro.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Native RO retention requires prepared pinned {path}; run the RO ontology transform first"
            )
        graph, nodes, content = self._read_native("ro", path)
        declarations = {}
        for relation, contract in self.policy["relations"].items():
            iri = _OBO + relation.replace(":", "_", 1)
            node = nodes.get(iri)
            if (
                node is None
                or node.get("type") != "PROPERTY"
                or node.get("propertyType") != "OBJECT"
                or obograph_is_deprecated(node)
                or node.get("lbl") != contract["label"]
                or _digest(_json(node).encode()) != contract["native_node_sha256"]
            ):
                raise ValueError(f"Missing or changed native RO property declaration: {relation}")
            declarations[relation] = node
        if any(compact_identifier(edge["pred"]) in _RELATIONS for edge in graph["edges"]):
            raise ValueError("Unreviewed RO supplier entity assertion")
        if selected_content_sha256("ro", graph) != self.policy["authorities"]["ro.json"]["selected_sha256"]:
            raise ValueError("Native RO property declarations differ from the reviewed release content")
        self._ro = declarations, content
        return self._ro

    def prepare_source(self, name, path):
        """Validate complete native membership and preprocess only an admitted private copy."""
        if name == "ro":
            _, content = self._prepare_ro(path)
        else:
            if name not in _SUPPLIERS or name in self._native:
                raise ValueError(f"Unexpected or repeated native RO supplier: {name}")
            self._prepare_ro()
            graph, nodes, content = self._read_native(name, path)
            selected = {}
            for edge in graph["edges"]:
                relation = compact_identifier(edge["pred"])
                if relation not in _RELATIONS:
                    continue
                key = compact_identifier(edge["sub"]), relation, compact_identifier(edge["obj"])
                if key in selected:
                    raise ValueError(f"Duplicate native RO assertion: {name}:{key}")
                for endpoint in (edge["sub"], edge["obj"]):
                    node = nodes.get(endpoint)
                    if node is None or node.get("type") != "CLASS" or obograph_is_deprecated(node):
                        raise ValueError(f"Native RO endpoint is missing, obsolete or not a class: {endpoint}")
                selected[key] = edge
            expected = set(_cohort(self.policy, name))
            controls = set(_cohort(self.policy, name, "unchanged_records"))
            if set(selected) != expected | controls:
                raise ValueError(f"Native RO supplier assertion cohort changed: {name}")
            if selected_content_sha256(name, graph) != self.policy["authorities"][name + ".json"]["selected_sha256"]:
                raise ValueError(f"Native RO supplier assertions differ from the reviewed release content: {name}")
            self._native[name] = {key: row for key, row in selected.items() if key in expected}
            self._native_digests[name] = _digest(_json(sorted(self._native[name].values(), key=_json)).encode())
        identity = self._identities[name]
        target = self.transform.output_dir / ".ontology-inputs" / identity["sha256"] / (name + ".json")
        with atomic_write(target, "wb") as destination:
            destination.write(content)
        return target

    def project(self, name, edges, normalization_input, source_file):
        """Verify the final emitted cohort and change only its misleading projected predicate."""
        self.verify_bindings()
        self.transform.verify_consumed_inputs()
        protected = edges[RELATION_COLUMN].map(compact_identifier).isin(_RELATIONS)
        records = edges.loc[protected].to_dict("index")
        if name not in self._native:
            if records:
                raise ValueError(f"Native RO assertions lack prepared supplier evidence: {name}")
            return edges
        native = self._native[name]
        observed = Counter((row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN]) for row in records.values())
        controls = _cohort(self.policy, name, "unchanged_records")
        if observed != Counter({key: 1 for key in native.keys() | controls.keys()}):
            raise ValueError(f"Emitted native RO assertion multiplicity/cohort changed: {name}")
        untouched = {}
        for row in records.values():
            key = row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN]
            if key in controls:
                if (
                    row[PREDICATE_COLUMN] != controls[key]["prior_predicate"]
                    or row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] != "infores:" + name
                ):
                    raise ValueError(f"Unchanged native RO control projection changed: {name}:{key}")
                untouched[key] = row
        records = {
            index: row
            for index, row in records.items()
            if (row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN]) in native
        }
        selected = edges.index.isin(records)
        retained = {}
        audits = []
        for index, row in records.items():
            key = row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN]
            relation = row[RELATION_COLUMN]
            contract = self.policy["relations"][relation]
            if row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] != "infores:" + name:
                raise ValueError(f"Unexpected native RO supplier provenance: {row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN]}")
            if row[PREDICATE_COLUMN] not in {contract["prior_predicate"], relation}:
                raise ValueError(f"Unexpected native RO prior projection: {row[PREDICATE_COLUMN]}")
            result = {**row, PREDICATE_COLUMN: relation}
            retained[key] = result
            audits.append(
                {
                    "ontology": name,
                    "source_file": Path(source_file).name,
                    "normalization_input_row_json": _json(normalization_input.loc[index].to_dict()),
                    "canonical_prior_row_json": _json(row),
                    "retained_row_json": _json(result),
                    "native_assertion_json": _json(native[key]),
                    "native_authority": self._identities[name]["path"],
                    "native_authority_sha256": self._identities[name]["sha256"],
                    "ro_declaration_json": _json(self._ro[0][relation]),
                    "ro_authority": self._identities["ro"]["path"],
                    "ro_authority_sha256": self._identities["ro"]["sha256"],
                    "policy_sha256": self.transform.consumed_input_snapshots[POLICY_ROLE]["sha256"],
                    "projection_action": "already_native"
                    if row[PREDICATE_COLUMN] == relation
                    else "restore_native_predicate",
                    "strict_biolink_disposition": STRICT_DISPOSITION,
                }
            )
        if name in self._projected:
            if (
                retained != self._projected[name]
                or untouched != self._unchanged_projected[name]
                or any(row[PREDICATE_COLUMN] != row[RELATION_COLUMN] for row in records.values())
            ):
                raise ValueError(f"Repeated native RO normalization changed certified rows: {name}")
            return edges  # Preserve the first original normalization-input audit, not a re-stamped copy.
        self.transform.verify_consumed_inputs()
        for record in audits:
            self.writer.writerow(record)
        result = edges.copy()
        result.loc[selected, PREDICATE_COLUMN] = result.loc[selected, RELATION_COLUMN]
        self._projected[name] = retained
        self._unchanged_projected[name] = untouched
        return result

    def verify_complete(self):
        """Require every prepared module to emit its complete retained assertion set."""
        self.verify_bindings()
        if set(self._native) != set(self._projected):
            raise ValueError("Native RO prepared modules were not completely emitted")
        self.transform.verify_consumed_inputs()

    def verify_bindings(self):
        """Retain mandatory read-time role identities, never accept a rebound current receipt."""
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        if _digest(_json(self.policy).encode()) != REVIEWED_POLICY_SHA256:
            raise SourceFinalizationRequired("Native RO cached policy changed after admission")
        if set(self._native) != set(self._native_digests) or any(
            _digest(_json(sorted(rows.values(), key=_json)).encode()) != self._native_digests[name]
            or any(
                key != (compact_identifier(row["sub"]), compact_identifier(row["pred"]), compact_identifier(row["obj"]))
                for key, row in rows.items()
            )
            for name, rows in self._native.items()
        ):
            raise SourceFinalizationRequired("Native RO cached assertion witness changed after admission")
        if self._ro is not None and (
            set(self._ro[0]) != _RELATIONS
            or any(
                _digest(_json(node).encode()) != self.policy["relations"][relation]["native_node_sha256"]
                for relation, node in self._ro[0].items()
            )
        ):
            raise SourceFinalizationRequired("Native RO cached property witness changed after admission")
        expected = {POLICY_ROLE: self._policy_identity}
        expected.update({"ontology_native_relation_" + name: identity for name, identity in self._identities.items()})
        expected.update(
            {
                "ontology_native_relation_" + name + "_source": identity
                for name, identity in self._source_identities.items()
            }
        )
        actual = self.transform.consumed_input_snapshots
        for role, identity in expected.items():
            if actual.get(role) != identity:
                raise SourceFinalizationRequired(f"Native RO consumed-input binding missing or changed: {role}")


def verify_audit_input_bindings(directory, snapshots, *, members=None, admission=None):
    """
    At finalization/admission, bind every audited supplier to its original native read.

    ``members`` names the record's graph files. Supplier edge files outside it
    belong to other records in a shared ontologies directory (for example a
    full build beside a later scoped ``-s ec`` run) and are not this record's
    claims. A supplier file that is a member is always checked, so an empty
    audit can never admit protected rows the record publishes. ``None`` keeps
    the whole-directory scan.
    """
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    policy_identity = snapshots.get(POLICY_ROLE)
    if not isinstance(policy_identity, dict) or set(policy_identity) != {"path", "sha256"}:
        raise SourceFinalizationRequired("Missing native RO policy input binding")
    policy_bytes = guard.capture(policy_identity["path"], retain=True)
    if _digest(policy_bytes) != policy_identity["sha256"]:
        raise SourceFinalizationRequired("Changed native RO policy input binding")
    policy = load_policy(io.StringIO(policy_bytes.decode("utf-8")))
    audit = guard.capture(Path(directory) / AUDIT_FILE, retain=True)
    reader = csv.DictReader(io.StringIO(audit.decode("utf-8")), delimiter="\t")
    if tuple(reader.fieldnames or ()) != AUDIT_FIELDS:
        raise SourceFinalizationRequired("Malformed native RO retention audit header")
    native_graphs = {}

    def native_graph(name, identity):
        """Rejoin full witnesses to actual immutable authority bytes once per selected supplier."""
        if name not in native_graphs:
            authority = policy["authorities"][name + ".json"]
            content = guard.capture(identity["path"], retain=True)
            if _digest(content) != identity["sha256"]:
                raise SourceFinalizationRequired("Native RO audit witness authority changed")
            document = json.loads(content, object_pairs_hook=_unique_object)
            graphs = document.get("graphs")
            if (
                not isinstance(graphs, list)
                or len(graphs) != 1
                or graphs[0].get("id") != authority["graph_id"]
                or (graphs[0].get("meta") or {}).get("version") != authority["release"]
            ):
                raise SourceFinalizationRequired("Native RO audit witness graph changed")
            if selected_content_sha256(name, graphs[0]) != authority["selected_sha256"]:
                raise SourceFinalizationRequired("Native RO audit witness differs from the reviewed release content")
            assertions, declarations = {}, {}
            for edge in graphs[0]["edges"]:
                relation = compact_identifier(edge["pred"])
                if relation in _RELATIONS:
                    key = (compact_identifier(edge["sub"]), relation, compact_identifier(edge["obj"]))
                    assertions.setdefault(key, []).append(edge)
            for node in graphs[0]["nodes"]:
                identifier = compact_identifier(node["id"])
                if identifier in _RELATIONS:
                    declarations.setdefault(identifier, []).append(node)
            native_graphs[name] = assertions, declarations
        return native_graphs[name]

    seen = Counter()
    audited_rows = {}
    for row in reader:
        name = row.get("ontology")
        if None in row or None in row.values() or name not in _SUPPLIERS:
            raise SourceFinalizationRequired("Malformed native RO retention audit row")
        for role, path_key, hash_key in (
            ("ontology_native_relation_" + name, "native_authority", "native_authority_sha256"),
            ("ontology_native_relation_ro", "ro_authority", "ro_authority_sha256"),
        ):
            expected = {"path": row[path_key], "sha256": row[hash_key]}
            if snapshots.get(role) != expected:
                raise SourceFinalizationRequired(f"Audited native RO input binding missing or changed: {role}")
            supplier = "ro" if role.endswith("_ro") else name
            if guard.capture(expected["path"])["sha256"] != expected["sha256"]:
                raise SourceFinalizationRequired(f"Audited native RO authority bytes changed: {role}")
            source = policy["authorities"][supplier + ".json"]["source"]
            if source["file"] == Path(expected["path"]).name:
                if expected["sha256"] != source["sha256"]:
                    raise SourceFinalizationRequired(f"Audited native RO input differs from pinned release: {role}")
            else:
                bound = snapshots.get(role + "_source")
                if (
                    not isinstance(bound, dict)
                    or set(bound) != {"path", "sha256"}
                    or Path(bound["path"]).name != source["file"]
                    or bound["sha256"] != source["sha256"]
                ):
                    raise SourceFinalizationRequired(f"Audited native RO release binding missing or changed: {role}")
                if guard.capture(bound["path"])["sha256"] != bound["sha256"]:
                    raise SourceFinalizationRequired(f"Audited native RO release bytes changed: {role}")
        if row["policy_sha256"] != policy_identity["sha256"] or row["strict_biolink_disposition"] != STRICT_DISPOSITION:
            raise SourceFinalizationRequired("Native RO audit policy/disposition binding changed")
        try:
            retained = json.loads(row["retained_row_json"], object_pairs_hook=_unique_object)
            prior = json.loads(row["canonical_prior_row_json"], object_pairs_hook=_unique_object)
            key = (name, retained[SUBJECT_COLUMN], retained[RELATION_COLUMN], retained[OBJECT_COLUMN])
            relation = retained[RELATION_COLUMN]
            expected_prior = policy["relations"][relation]["prior_predicate"]
            if (
                retained != {**prior, PREDICATE_COLUMN: relation}
                or prior[PREDICATE_COLUMN] not in {expected_prior, relation}
                or retained[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] != "infores:" + name
                or row["source_file"] != name + "_edges.tsv"
                or row["projection_action"]
                != ("already_native" if prior[PREDICATE_COLUMN] == relation else "restore_native_predicate")
            ):
                raise ValueError("native predicate-only projection witness changed")
            original = json.loads(row["normalization_input_row_json"], object_pairs_hook=_unique_object)
            if any(original[column] != prior[column] for column in (SUBJECT_COLUMN, RELATION_COLUMN, OBJECT_COLUMN)):
                raise ValueError("native normalization-input endpoints or relation changed")
            assertion = json.loads(row["native_assertion_json"], object_pairs_hook=_unique_object)
            assertions, _ = native_graph(name, snapshots["ontology_native_relation_" + name])
            witnesses = assertions.get(key[1:], [])
            if witnesses != [assertion]:
                raise ValueError("native assertion witness differs from actual authority")
            declaration = json.loads(row["ro_declaration_json"], object_pairs_hook=_unique_object)
            _, declarations = native_graph("ro", snapshots["ontology_native_relation_ro"])
            if declarations.get(relation) != [declaration] or (
                _digest(_json(declaration).encode()) != policy["relations"][relation]["native_node_sha256"]
            ):
                raise ValueError("native property witness differs from actual authority")
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceFinalizationRequired("Malformed retained native RO audit assertion") from exc
        seen[key] += 1
        audited_rows[key] = retained
    suppliers = {key[0] for key in seen} | {
        name for name in _SUPPLIERS if "ontology_native_relation_" + name in snapshots
    }
    expected = Counter(
        (row["ontology"], row["subject"], row["relation"], row["object"])
        for row in policy["records"]
        if row["ontology"] in suppliers
    )
    if seen != expected:
        raise SourceFinalizationRequired("Native RO audited supplier cohort changed")
    # An empty audit may describe a genuinely unrelated module, never a way to
    # erase the authority requirements for retained protected graph assertions.
    emitted = Counter()
    for name in sorted(_SUPPLIERS):
        path = Path(directory) / (name + "_edges.tsv")
        if members is not None and path.name not in members:
            continue
        if not path.is_file():
            continue
        guard.capture(path)
        controls = _cohort(policy, name, "unchanged_records")
        seen_controls = Counter()
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                if row.get(RELATION_COLUMN) not in _RELATIONS and row.get(PREDICATE_COLUMN) not in _RELATIONS:
                    continue
                triple = row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN]
                if triple in controls:
                    if (
                        name not in suppliers
                        or row.get(PREDICATE_COLUMN) != controls[triple]["prior_predicate"]
                        or row.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN) != "infores:" + name
                    ):
                        raise SourceFinalizationRequired("Unchanged native RO control lost its prior projection")
                    seen_controls[triple] += 1
                    continue
                if (
                    row.get(PREDICATE_COLUMN) != row.get(RELATION_COLUMN)
                    or row.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN) != "infores:" + name
                ):
                    raise SourceFinalizationRequired("Protected native RO graph row lost its retained semantics")
                key = (name, row[SUBJECT_COLUMN], row[RELATION_COLUMN], row[OBJECT_COLUMN])
                if key not in audited_rows or any(
                    row.get(column) != value for column, value in audited_rows[key].items()
                ):
                    raise SourceFinalizationRequired("Native RO graph row differs from complete retained audit witness")
                emitted[key] += 1
        expected_controls = Counter({key: 1 for key in controls}) if name in suppliers else Counter()
        if seen_controls != expected_controls:
            raise SourceFinalizationRequired("Unchanged native RO control cohort changed")
    if emitted != seen:
        raise SourceFinalizationRequired("Native RO graph/audit assertion cohorts disagree")
    guard.verify(metadata_only=True)


def has_reviewed_relations(edges):
    """Detect protected native relations when normalization lacks a run-owned authority."""
    return edges[RELATION_COLUMN].map(compact_identifier).isin(_RELATIONS).any()
