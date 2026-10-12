"""Quarantine seven unsupported label-derived identities without deleting GOLD observations (#1294)."""

import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    EXACT_MATCH,
    EXACT_MATCH_PREDICATE,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.native_rdf import decoded_iri_subject
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "mappings/gold_abscess_crosswalk_policy.json"
CURATION_PATH = ROOT / "mappings/gold_ecosystem_mesh_sites.tsv"
POLICY_SHA256 = "5eeb77a664b26704bc2b60f239dd72b97baea1e4684fa50db205e947b9b02ab3"
NATIVE_SELECTION_SHA256 = "8d0e356858c05093bd150bee2f69a9b99e4bb2b136f2b69bd0440d3f4bcb79d6"
MESH_STATEMENTS_SHA256 = "3a96fde4801dd9b6e4018dc38ff0b0adde0b73972ca26b64828237380670ea3a"
REQUIRED_INPUTS = ("gold_crosswalk_policy", "gold_mesh_site_curation", "gold_native_nodes", "gold_native_edges")
ACTIVE_INPUTS = ("gold_crosswalk_mesh_native", "gold_crosswalk_mesh_declarations")
ONTOLOGY_INPUT = "gold_crosswalk_ontology"
AUDIT_FILE = "gold_label_crosswalk_quarantine.tsv"
AUDIT_HEADER = (
    "ecosystem_id",
    "target_id",
    "disposition",
    "reason",
    "proposed_edge_json",
    "historical_crosswalk_json",
    "original_mapping_json",
    "current_mapping_json",
    "native_declaration_json",
    "native_context_nodes_json",
    "native_hierarchy_json",
    "native_assignments_json",
    "retained_location_edges_json",
    "historical_location_edges_json",
    "mesh_native_evidence_json",
    "mesh_target_declaration_json",
    "consumed_inputs_json",
)
NODE_FIELDS = {"id", "category", "name", "provided_by", "xref"}
EDGE_FIELDS = {"id", "subject", "predicate", "object", "relation", "primary_knowledge_source"}


def _json(value):
    """Preserve all source fields without TSV-delimiter ambiguity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    """Bind complete reviewed structure independently of policy-supplied hashes."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _unique(pairs):
    """Reject overwritten curated evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate GOLD crosswalk policy key")
        result[key] = value
    return result


def _rows(path, required, *, comments=False):
    """Stream strict full rows with physical line coordinates, preserving all columns."""
    with path.open(encoding="utf-8", newline="") as stream:
        skipped = 0
        first = next(stream, "")
        while comments and first.startswith("#"):
            skipped += 1
            first = next(stream, "")
        from itertools import chain

        reader = csv.DictReader(chain((first,), stream), delimiter="\t", strict=True)
        fields = reader.fieldnames or ()
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise ValueError("Invalid GOLD crosswalk evidence header")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed GOLD crosswalk evidence row width")
            yield {"row": row, "ending_physical_line": skipped + reader.line_num, "full_row_sha256": _digest(row)}


def _mesh_evidence(path, policy):
    """Select and verify complete primary MeSH statements, retaining literal bytes and coordinates."""
    evidence, wanted = [], set(policy["mesh_subjects"])
    with gzip.open(path, "rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            tokens = raw.split(None, 1)
            if not tokens:
                continue
            subject = decoded_iri_subject(tokens[0], authority="GOLD MeSH")
            token = subject.rsplit(b"/", 1)[-1].rstrip(b">").decode("ascii", errors="replace")
            if token not in wanted:
                continue
            if subject != f"<{policy['mesh_namespace']}{token}>".encode():
                raise ValueError("GOLD MeSH native release namespace changed")
            evidence.append({"line": line_no, "statement": raw.decode().rstrip("\n")})
    statements = [item["statement"] for item in evidence]
    digest = hashlib.sha256(("\n".join(sorted(statements)) + "\n").encode()).hexdigest()
    if len(statements) != policy["mesh_statement_count"] or digest != MESH_STATEMENTS_SHA256:
        raise ValueError("Reviewed native MeSH Abscess evidence changed or incomplete")
    return evidence


class CrosswalkQuarantine:
    """Bind the finite source cohort before graph output and audit each withheld proposal."""

    def __init__(self, transform, stack, nodes_in, edges_in, *, policy_path=None, curation_path=None):
        """Keep actual immutable parser snapshots alive across GOLD's repeated source passes."""
        self.transform, self.stack = transform, stack
        self.guard = SourceAdmission()
        self.read_snapshots = {}
        self.proposals, self.locations = {}, []
        self.mesh_evidence, self.mesh_declaration = [], None
        self.mesh_path, self.ontology_path = None, None
        self.policy_path = self.consume(REQUIRED_INPUTS[0], policy_path or POLICY_PATH)
        with self.policy_path.open() as stream:
            self.policy = json.load(stream, object_pairs_hook=_unique)
        if _digest(self.policy) != POLICY_SHA256:
            raise ValueError("GOLD Abscess policy changed; complete native review required")
        self.curation_path = self.consume(REQUIRED_INPUTS[1], curation_path or CURATION_PATH)
        rows = list(_rows(self.curation_path, set(self.policy["current_mapping"]), comments=True))
        ids = [item["row"]["mesh_id"] for item in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate GOLD MeSH curation decision")
        selected = [item for item in rows if item["row"]["mesh_id"] == self.policy["target"]]
        if len(selected) != 1 or selected[0]["row"] != self.policy["current_mapping"]:
            raise ValueError("Reviewed GOLD Abscess crosswalk disposition changed or missing")
        self.curation = selected[0]
        self.allowed_mesh = {item["row"]["mesh_id"] for item in rows if item["row"]["decision"] == "SITE"}
        self.nodes_path = self.consume(REQUIRED_INPUTS[2], nodes_in)
        self.edges_path = self.consume(REQUIRED_INPUTS[3], edges_in)
        self.ecosystem_ids = set(self.policy["ecosystem_ids"])
        self.context_ids = set(self.policy["context_ids"])
        self.descendant_ids = set(self.policy["descendant_ids"])
        self.nodes = {}
        found = set()
        for item in _rows(self.nodes_path, {"id", "category", "name"}):
            row = item["row"]
            identifier = row["id"]
            if identifier in self.ecosystem_ids or (
                identifier.startswith("gold.ecosystem:") and row["name"].strip().casefold() == "abscess"
            ):
                found.add(identifier)
            if identifier in self.context_ids:
                if identifier in self.nodes:
                    raise ValueError("Duplicate reviewed GOLD ecosystem declaration")
                self.nodes[identifier] = item
        self.active = bool(found)
        self.hierarchy, self.assignments = [], []
        if not self.active:
            return
        if found != self.ecosystem_ids:
            raise ValueError("Reviewed GOLD Abscess ID cohort changed or incomplete")
        # Retain the entire reviewed multi-parent context, never select one parent.
        all_hierarchy = []
        for item in _rows(self.edges_path, EDGE_FIELDS):
            row = item["row"]
            if row["subject"].startswith("gold.ecosystem:") and row["predicate"] == "biolink:subclass_of":
                all_hierarchy.append(item)
            if row["object"] in self.descendant_ids and row["predicate"] == "biolink:occurs_in":
                self.assignments.append(item)
        ancestors, descendants = set(self.ecosystem_ids), set(self.ecosystem_ids)
        while True:
            following = ancestors | {
                item["row"]["object"] for item in all_hierarchy if item["row"]["subject"] in ancestors
            }
            if following == ancestors:
                break
            ancestors = following
        while True:
            following = descendants | {
                item["row"]["subject"] for item in all_hierarchy if item["row"]["object"] in descendants
            }
            if following == descendants:
                break
            descendants = following
        if ancestors | descendants != self.context_ids or descendants != self.descendant_ids:
            raise ValueError("Reviewed GOLD Abscess ancestry/descendant context changed")
        self.hierarchy = [item for item in all_hierarchy if item["row"]["subject"] in self.context_ids]
        selection = {
            "nodes": sorted((item["row"] for item in self.nodes.values()), key=_json),
            "hierarchy": sorted((item["row"] for item in self.hierarchy), key=_json),
            "assignments": sorted((item["row"] for item in self.assignments), key=_json),
        }
        if _digest(selection) != NATIVE_SELECTION_SHA256 or len(self.assignments) != self.policy["expected_locations"]:
            raise ValueError("Reviewed GOLD selected native rows changed, missing or duplicated")
        self.native_mesh_path = self.consume(ACTIVE_INPUTS[0], transform.input_base_dir / "mesh2026.nt.gz")
        self.mesh_evidence = _mesh_evidence(self.native_mesh_path, self.policy)
        self.mesh_path = self.consume(ACTIVE_INPUTS[1], transform.output_base_dir / "ontologies_stubs/mesh_nodes.tsv")
        declarations = [
            item for item in _rows(self.mesh_path, {"id", "name"}) if item["row"]["id"] == self.policy["target"]
        ]
        if len(declarations) != 1 or declarations[0]["row"]["name"] != "Abscess":
            raise ValueError("Reviewed MeSH Abscess label declaration changed or ambiguous")
        self.mesh_declaration = declarations[0]
        ontology = transform.input_base_dir / "gold_ontology.owl"
        self.guard.capture(ontology, optional=True)
        if ontology.is_file():
            self.ontology_path = self.consume(ONTOLOGY_INPUT, ontology)

    def contract(self):
        """Distinguish the exact reviewed current cohort from a genuinely absent cohort."""
        return {
            "version": 1,
            "policy_sha256": POLICY_SHA256,
            "selected_native_sha256": NATIVE_SELECTION_SHA256 if self.active else None,
            "ecosystem_ids": sorted(self.ecosystem_ids) if self.active else [],
            "expected_locations": 34 if self.active else 0,
            "actual_roles": sorted(self.read_snapshots),
        }

    def consume(self, role, path):
        """Bind the original lexical locator and return the immutable parser path."""
        self.guard.capture(path)
        stream = self.stack.enter_context(self.transform.consume_input(role, path))
        self.read_snapshots[role] = dict(self.transform.consumed_input_snapshots[role])
        return Path(stream.name)

    def verify_bindings(self, *, byte_verified=False):
        """Do not let lost/restamped live receipts erase any actual finite authority read (#1301)."""
        snapshots = self.transform.consumed_input_snapshots
        for role, expected in self.read_snapshots.items():
            if snapshots.get(role) != expected:
                raise SourceFinalizationRequired(f"GOLD consumed native role missing or changed: {role}")
        self.guard.verify(metadata_only=byte_verified)

    def intercept(self, identifier, label, target, proposal):
        """Withhold only the seven reviewed label-derived exact-match proposals."""
        if identifier not in self.ecosystem_ids:
            return False
        if not self.active or label != "Abscess" or target != self.policy["target"]:
            raise ValueError("Reviewed GOLD label-derived crosswalk proposal changed")
        if proposal["predicate"] != EXACT_MATCH_PREDICATE or proposal["relation"] != EXACT_MATCH:
            raise ValueError("Reviewed GOLD crosswalk predicate changed")
        if identifier in self.proposals:
            raise ValueError("Duplicate reviewed GOLD crosswalk proposal")
        self.proposals[identifier] = proposal
        return True

    def observe_location(self, native, emitted):
        """Track the actual emitted current-stage assertion, including descendant source targets."""
        if self.active and native["predicate"] == "biolink:occurs_in" and native["object"] in self.descendant_ids:
            self.locations.append(emitted)

    def _record_owned_locations(self):
        """Reconstruct the reviewed native sites without replacing source referents by taxa."""
        from kg_microbe.transform_utils.gold.gold import _UNINFORMATIVE_ECOSYSTEM_LABELS

        parents = {}
        for item in self.hierarchy:
            parents.setdefault(item["row"]["subject"], []).append(item["row"]["object"])
        result = []
        for item in self.assignments:
            row = item["row"]
            target, original, visited = row["object"], "", set()
            while self.nodes[target]["row"]["name"].strip().lower() in _UNINFORMATIVE_ECOSYSTEM_LABELS:
                if target in visited or len(parents.get(target, [])) != 1:
                    raise ValueError("Reviewed GOLD Abscess environment resolution changed")
                visited.add(target)
                original, target = row["object"], parents[target][0]
            result.append(
                {
                    "subject": row["subject"],
                    "predicate": "biolink:located_in",
                    "object": target,
                    "relation": "RO:0001025",
                    "primary_knowledge_source": row["primary_knowledge_source"],
                    "knowledge_level": KNOWLEDGE_ASSERTION,
                    "agent_type": MANUAL_AGENT,
                    "original_object": original,
                }
            )
        return result

    def finish(self):
        """Require conservation before recording the mandatory audit or completed native contract."""
        if self.active:
            if set(self.proposals) != self.ecosystem_ids:
                raise ValueError("GOLD Abscess run did not intercept exactly seven reviewed proposals")
            fields = [*self.transform.edge_header, "original_object"]
            historical = [
                {key: item["row"].get(key, "") for key in fields} for item in self.policy["historical_locations"]
            ]
            expected = self._record_owned_locations()
            # Preserve the independently pinned previous-stage projection as
            # evidence; only its source-record ownership changes under #1316.
            taxonomy = self.transform._taxon_dispositions
            if taxonomy is None:
                raise ValueError("GOLD Abscess restoration lacks independently reviewed taxonomy context")
            old = [
                {**row, "subject": taxonomy.index.historical_folds.get(row["subject"], row["subject"])}
                for row in expected
            ]
            if Counter(map(_json, old)) != Counter(map(_json, historical)):
                raise ValueError("GOLD Abscess historical fold reconstruction changed")
            if len(self.locations) != 34 or Counter(map(_json, self.locations)) != Counter(map(_json, expected)):
                raise ValueError("GOLD Abscess location assertions were not exactly conserved at transform stage")
            _verify_actual_locations(self.transform.output_edge_file, expected, self.descendant_ids, self.ecosystem_ids)
            emitted = {
                item["row"]["id"]: item["row"]
                for item in _rows(self.transform.output_node_file, {"id", "name"})
                if item["row"]["id"] in self.ecosystem_ids
            }
            if set(emitted) != self.ecosystem_ids or any(row["name"] != "Abscess" for row in emitted.values()):
                raise ValueError("GOLD Abscess native ecosystem nodes were not conserved")
        self.verify_bindings()
        self.transform.verify_consumed_inputs()
        path = self.transform.output_dir / AUDIT_FILE
        if path.is_symlink():
            raise SourceFinalizationRequired("GOLD crosswalk audit must not be a symlink")
        with atomic_write(path, encoding="utf-8", newline="") as stream:
            writer = tsv_writer(stream, quoting=csv.QUOTE_NONE, quotechar=None)
            writer.writerow(AUDIT_HEADER)
            for identifier in sorted(self.proposals):
                historical = next(
                    item for item in self.policy["historical_crosswalks"] if item["row"]["subject"] == identifier
                )
                writer.writerow(
                    [
                        identifier,
                        self.policy["target"],
                        "quarantined_label_based_exact_identity",
                        "native_site_context_does_not_establish_generic_descriptor_identity",
                        _json(self.proposals[identifier]),
                        _json(historical),
                        _json(self.policy["original_mapping"]),
                        _json(self.curation),
                        _json(self.nodes[identifier]),
                        _json(self.nodes),
                        _json(self.hierarchy),
                        _json(self.assignments),
                        _json(self.locations),
                        _json(self.policy["historical_locations"]),
                        _json(self.mesh_evidence),
                        _json(self.mesh_declaration),
                        _json(self.transform.consumed_input_snapshots),
                    ]
                )
        self.verify_bindings()
        self.transform.record_producer_audit(AUDIT_FILE)


def _verify_actual_locations(path, expected, descendants, ecosystems):
    """Check output bytes rather than trusting a previously observed emitter callback."""
    from kg_microbe.transform_utils.gold.taxon_dispositions import _identity_strength

    actual = []
    subjects = {row["subject"] for row in expected}
    fields = list(expected[0])
    for item in _rows(path, {"subject", "predicate", "object"}):
        row = item["row"]
        endpoints = {compact_identifier(row["subject"]), compact_identifier(row["object"])}
        if "mesh:D000038" in endpoints and endpoints & ecosystems and _identity_strength(row):
            raise SourceFinalizationRequired("GOLD Abscess quarantined identity bridge reappeared in actual output")
        if row["predicate"] == "biolink:located_in" and (row["object"] in descendants or row["subject"] in subjects):
            actual.append({key: row.get(key, "") for key in fields})
    if Counter(map(_json, actual)) != Counter(map(_json, expected)):
        raise SourceFinalizationRequired("GOLD Abscess actual source-owned location observations changed")


def verify_record_owned_locations(index, directory, *, report, admission):
    """Rejoin pinned native contexts and old/current projections on saved admission, without edits."""
    policy = json.loads(POLICY_PATH.read_text())
    if _digest(policy) != POLICY_SHA256:
        raise SourceFinalizationRequired("GOLD Abscess policy changed during native restoration rejoin")
    context, ecosystems, descendants = map(
        set, (policy["context_ids"], policy["ecosystem_ids"], policy["descendant_ids"])
    )
    nodes, found = {}, set()
    for item in _rows(index.native_nodes, {"id", "name"}):
        row = item["row"]
        if row["id"] in ecosystems or (
            row["id"].startswith("gold.ecosystem:") and row["name"].strip().casefold() == "abscess"
        ):
            found.add(row["id"])
        if row["id"] in context:
            if row["id"] in nodes:
                raise SourceFinalizationRequired("Duplicate GOLD Abscess context declaration")
            nodes[row["id"]] = item
    if not found:
        return
    if found != ecosystems:
        raise SourceFinalizationRequired("GOLD Abscess native restoration cohort changed")
    verify_recorded_inputs(report, Path(directory) / "source_finalization.json")
    snapshots = report.get("consumed_inputs", {})
    # Reconstruct producer-only receipts from independently required native
    # contracts; finalizer reads added later do not belong to the producer audit.
    roles = set(report["producer_native_inputs"]["actual_roles"])
    roles.update(report["producer_native_inputs"]["taxonomy_dispositions"]["native_inputs"])
    roles.update(report["producer_native_inputs"]["selected_taxon_aliases"]["consumed_inputs"])
    consumed = {}
    for role in sorted(roles):
        receipt = snapshots.get(role)
        if not isinstance(receipt, dict) or not receipt.get("path"):
            raise SourceFinalizationRequired("GOLD Abscess complete producer receipt missing")
        identity = admission.capture(receipt["path"])
        if identity["sha256"] != receipt.get("sha256"):
            raise SourceFinalizationRequired("GOLD Abscess consumed native bytes changed")
        consumed[role] = receipt
    curation = [
        item
        for item in _rows(CURATION_PATH, set(policy["current_mapping"]), comments=True)
        if item["row"]["mesh_id"] == policy["target"]
    ]
    if len(curation) != 1 or curation[0]["row"] != policy["current_mapping"]:
        raise SourceFinalizationRequired("GOLD Abscess current curation evidence changed")
    mesh_evidence = _mesh_evidence(Path(consumed[ACTIVE_INPUTS[0]]["path"]), policy)
    mesh_declaration = [
        item
        for item in _rows(Path(consumed[ACTIVE_INPUTS[1]]["path"]), {"id", "name"})
        if item["row"]["id"] == policy["target"]
    ]
    if len(mesh_declaration) != 1 or mesh_declaration[0]["row"]["name"] != "Abscess":
        raise SourceFinalizationRequired("GOLD Abscess selected MeSH declaration changed")
    audit_path = Path(directory) / AUDIT_FILE
    if audit_path.is_symlink():
        raise SourceFinalizationRequired("GOLD Abscess audit is symlinked")
    identity = admission.capture(audit_path)
    if any(
        report.get(collection, {}).get(AUDIT_FILE) != identity
        for collection in ("audit_members", "producer_audit_members")
    ):
        raise SourceFinalizationRequired("GOLD Abscess audit absent from mandatory native restoration inventory")
    hierarchy, assignments = [], []
    for item in _rows(index.native_edges, EDGE_FIELDS):
        row = item["row"]
        if row["subject"] in context and row["predicate"] == "biolink:subclass_of":
            hierarchy.append(item)
        if row["object"] in descendants and row["predicate"] == "biolink:occurs_in":
            assignments.append(item)
    selection = {
        "nodes": sorted((item["row"] for item in nodes.values()), key=_json),
        "hierarchy": sorted((item["row"] for item in hierarchy), key=_json),
        "assignments": sorted((item["row"] for item in assignments), key=_json),
    }
    if _digest(selection) != NATIVE_SELECTION_SHA256:
        raise SourceFinalizationRequired("GOLD Abscess restored observations lack complete pinned native context")
    # Reuse only the deterministic projection, not a constructor's receipt or
    # emitter cache. Every input above was independently rejoined to native bytes.
    from types import SimpleNamespace

    expected = CrosswalkQuarantine._record_owned_locations(
        SimpleNamespace(nodes=nodes, hierarchy=hierarchy, assignments=assignments)
    )
    old = [{**row, "subject": index.historical_folds.get(row["subject"], row["subject"])} for row in expected]
    historical = [{key: item["row"].get(key, "") for key in expected[0]} for item in policy["historical_locations"]]
    if Counter(map(_json, old)) != Counter(map(_json, historical)):
        raise SourceFinalizationRequired("GOLD Abscess historical restoration projection changed")
    observed = set()
    for item in _rows(audit_path, set(AUDIT_HEADER)):
        row = item["row"]
        if row["ecosystem_id"] not in ecosystems or row["ecosystem_id"] in observed:
            raise SourceFinalizationRequired("GOLD Abscess quarantine audit cohort changed")
        observed.add(row["ecosystem_id"])
        identifier = row["ecosystem_id"]
        evidence = {
            "proposed_edge_json": {
                "subject": identifier,
                "predicate": EXACT_MATCH_PREDICATE,
                "object": policy["target"],
                "relation": EXACT_MATCH,
                "primary_knowledge_source": "infores:gold",
                "knowledge_level": KNOWLEDGE_ASSERTION,
                "agent_type": MANUAL_AGENT,
                "original_object": "",
            },
            "historical_crosswalk_json": next(
                item for item in policy["historical_crosswalks"] if item["row"]["subject"] == identifier
            ),
            "original_mapping_json": policy["original_mapping"],
            "current_mapping_json": curation[0],
            "native_declaration_json": nodes[identifier],
            "native_context_nodes_json": nodes,
            "native_hierarchy_json": hierarchy,
            "native_assignments_json": assignments,
            "historical_location_edges_json": policy["historical_locations"],
            "mesh_native_evidence_json": mesh_evidence,
            "mesh_target_declaration_json": mesh_declaration[0],
            "consumed_inputs_json": consumed,
        }
        if (
            row["target_id"] != policy["target"]
            or row["disposition"] != "quarantined_label_based_exact_identity"
            or row["reason"] != "native_site_context_does_not_establish_generic_descriptor_identity"
            or any(json.loads(row[key]) != value for key, value in evidence.items())
        ):
            raise SourceFinalizationRequired(
                "GOLD Abscess audit lost complete native or historical restoration evidence"
            )
        if Counter(map(_json, json.loads(row["retained_location_edges_json"]))) != Counter(map(_json, expected)):
            raise SourceFinalizationRequired("GOLD Abscess audit source-owned observations changed")
    if observed != ecosystems:
        raise SourceFinalizationRequired("GOLD Abscess quarantine audit incomplete")
    _verify_actual_locations(Path(directory) / "edges.tsv", expected, descendants, ecosystems)


def verify_recorded_inputs(report, report_path=None):
    """Require canonical evidence roles/origins, not substitute current files for missing consumption."""
    snapshots = report.get("consumed_inputs", {})
    for role, path in ((REQUIRED_INPUTS[0], POLICY_PATH), (REQUIRED_INPUTS[1], CURATION_PATH)):
        if Path(snapshots.get(role, {}).get("path", "")).resolve() != path.resolve():
            raise SourceFinalizationRequired("GOLD crosswalk consumed policy/curation origin missing or changed")
    nodes = Path(snapshots.get(REQUIRED_INPUTS[2], {}).get("path", ""))
    edges = Path(snapshots.get(REQUIRED_INPUTS[3], {}).get("path", ""))
    if nodes.name != "GOLD_nodes.tsv" or edges.name != "GOLD_edges.tsv" or nodes.parent != edges.parent:
        raise SourceFinalizationRequired("GOLD crosswalk native input pair missing or inconsistent")
    raw = report.get("raw_input_directory")
    if not isinstance(raw, str) or not raw:
        raise SourceFinalizationRequired("GOLD recorded raw input directory missing")
    if (
        nodes.resolve() != (Path(raw) / "gold/GOLD_nodes.tsv").resolve()
        or edges.resolve() != (Path(raw) / "gold/GOLD_edges.tsv").resolve()
    ):
        raise SourceFinalizationRequired("GOLD native input pair differs from selected raw directory")
    with POLICY_PATH.open() as stream:
        policy = json.load(stream, object_pairs_hook=_unique)
    if _digest(policy) != POLICY_SHA256:
        raise SourceFinalizationRequired("Reviewed GOLD policy pin changed")
    found = {
        item["row"]["id"]
        for item in _rows(nodes, {"id", "name"})
        if item["row"]["id"] in policy["ecosystem_ids"]
        or (item["row"]["id"].startswith("gold.ecosystem:") and item["row"]["name"].strip().casefold() == "abscess")
    }
    active = bool(found)
    required_roles = set(REQUIRED_INPUTS)
    ontology = Path(raw) / "gold_ontology.owl"
    if active:
        required_roles.update(ACTIVE_INPUTS)
        if ontology.is_file():
            required_roles.add(ONTOLOGY_INPUT)
    expected = {
        "version": 1,
        "policy_sha256": POLICY_SHA256,
        "selected_native_sha256": NATIVE_SELECTION_SHA256 if active else None,
        "ecosystem_ids": sorted(policy["ecosystem_ids"]) if active else [],
        "expected_locations": 34 if active else 0,
        "actual_roles": sorted(required_roles),
    }
    supplied = dict(report.get("producer_native_inputs") or {})
    # GOLD's independent taxonomy policy is composed by GOLDTransform, not
    # interpreted or waived by this finite seven-bridge verifier.
    supplied.pop("taxonomy_dispositions", None)
    supplied.pop("selected_taxon_aliases", None)
    if (active and found != set(policy["ecosystem_ids"])) or supplied != expected:
        raise SourceFinalizationRequired("GOLD reviewed cohort native contract missing or changed")
    if active:
        if not set(ACTIVE_INPUTS).issubset(snapshots):
            raise SourceFinalizationRequired("GOLD active crosswalk native evidence incomplete")
        if (
            ONTOLOGY_INPUT in required_roles
            and Path(snapshots.get(ONTOLOGY_INPUT, {}).get("path", "")).resolve() != ontology.resolve()
        ):
            raise SourceFinalizationRequired("GOLD consumed ontology role missing or changed")
        if Path(snapshots[ACTIVE_INPUTS[0]]["path"]) != nodes.parent.parent / "mesh2026.nt.gz":
            raise SourceFinalizationRequired("GOLD active crosswalk MeSH native origin changed")
        declaration = Path(snapshots[ACTIVE_INPUTS[1]]["path"])
        if declaration.name != "mesh_nodes.tsv" or declaration.parent.name != "ontologies_stubs":
            raise SourceFinalizationRequired("GOLD active crosswalk MeSH declaration origin changed")
        if (
            report_path is not None
            and declaration.resolve() != (Path(report_path).parent.parent / "ontologies_stubs/mesh_nodes.tsv").resolve()
        ):
            raise SourceFinalizationRequired("GOLD MeSH declaration differs from selected transformed authority")
