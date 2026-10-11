"""Producer-owned quarantine of one reviewed FOODON parent, with mandatory native evidence."""

import csv
import io
import json
from collections import Counter
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils import foodon_kernel_quarantine as native
from kg_microbe.utils.atomic_io import atomic_write

KEYS = (SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN, RELATION_COLUMN)
MEMBERS = ("foodon_nodes.tsv", "foodon_edges.tsv")
AUDIT_FIELDS = (
    "source_file",
    "normalization_input_row_json",
    "canonical_prior_row_json",
    "disposition",
    "rationale",
    "native_json_evidence_json",
    "native_owl_evidence_json",
    "consumed_inputs_json",
)


def _key(row):
    return tuple(row[key] for key in KEYS)


def _expected(policy, *, retained=False):
    rejected = (native.ROOT_ID, "biolink:subclass_of", native.REJECTED_PARENT, "rdfs:subClassOf")
    return Counter(
        _key(item["row"]) for item in policy["source_incidence"] if not retained or _key(item["row"]) != rejected
    )


def _incident(row, cohort):
    return row[SUBJECT_COLUMN] in cohort or row[OBJECT_COLUMN] in cohort


def selected_members(members):
    """Select only the explicitly admitted FOODON pair, never discover sibling files."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    selected = tuple(name for name in MEMBERS if name in members)
    if selected and selected != MEMBERS:
        raise SourceFinalizationRequired("FOODON kernel requires its exact selected node/edge pair")
    return selected


def _owned_inputs(snapshots):
    return {
        role: snapshots[role] for role in (native.POLICY_ROLE, native.JSON_ROLE, native.OWL_ROLE) if role in snapshots
    }


def _check_input_scope(snapshots, members):
    """Require a real JSON read for the selected supplier and truthful zero for other suppliers."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    required = {native.POLICY_ROLE, native.JSON_ROLE} if members else {native.POLICY_ROLE}
    optional = {native.OWL_ROLE} if members else set()
    roles = set(_owned_inputs(snapshots))
    if not required <= roles or roles - required - optional:
        raise SourceFinalizationRequired("FOODON kernel selected members/native role scope differ")


class FoodonKernelQuarantine:
    """Keep real read-time identities and complete source assertions until successful emission."""

    def __init__(self, transform, audit_stream):
        """Consume the reviewed policy even for an honestly empty selected-source cohort."""
        self.transform = transform
        with transform.consume_input(native.POLICY_ROLE, native.POLICY_FILE) as stream:
            self.policy = native.load_policy(stream)
        self.identities = {native.POLICY_ROLE: transform.consumed_input_snapshots[native.POLICY_ROLE]}
        self.writer = csv.DictWriter(audit_stream, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        self.writer.writeheader()
        self.prepared = False
        self.projected = False
        self.evidence = None
        self._members = ()
        self._failure = False
        transform._foodon_kernel_input_contract = self

    def prepare_source(self, path):
        """Read native JSON/OWL before sanitation; let KGX sanitize only its private copy."""
        if self.prepared:
            raise ValueError("FOODON kernel source selected more than once")
        with self.transform.consume_input(native.JSON_ROLE, path) as stream:
            payload = stream.buffer.read()
        self.identities[native.JSON_ROLE] = self.transform.consumed_input_snapshots[native.JSON_ROLE]
        document = json.loads(payload, object_pairs_hook=native.unique_object)
        graphs = document.get("graphs")
        if native.json_evidence(graphs, self.policy) is not None:
            with self.transform.consume_input(native.OWL_ROLE, self.transform.input_base_dir / "foodon.owl") as stream:
                _, self.evidence = native.reviewed_hierarchy(graphs, self.policy, native_owl=stream)
            self.identities[native.OWL_ROLE] = self.transform.consumed_input_snapshots[native.OWL_ROLE]
        self.prepared = True
        self._members = MEMBERS
        private = (
            self.transform.output_dir / ".ontology-inputs" / self.identities[native.JSON_ROLE]["sha256"] / "foodon.json"
        )
        with atomic_write(private, "wb") as stream:
            stream.write(payload)
        return private

    def project(self, frame, originals, source_file):
        """Exclude precisely one contradictory parent and preserve every other emitted field."""
        self.verify_bindings()
        if not self.prepared or self.projected:
            raise ValueError("FOODON kernel projection lacks a unique prepared native source")
        cohort = set(self.policy["cohort"])
        incident = frame[SUBJECT_COLUMN].isin(cohort) | frame[OBJECT_COLUMN].isin(cohort)
        selected = frame.loc[incident]
        if self.evidence is None:
            if not selected.empty:
                raise ValueError("FOODON kernel graph cohort lacks native authority")
            self.projected = True
            return frame
        actual = Counter(_key(row) for row in selected.to_dict("records"))
        if actual != _expected(self.policy) or set(selected[PRIMARY_KNOWLEDGE_SOURCE_COLUMN]) != {"infores:foodon"}:
            raise ValueError("FOODON kernel emitted incident cohort changed; exactly31 reviewed assertions required")
        rejected = (frame[SUBJECT_COLUMN] == native.ROOT_ID) & (frame[OBJECT_COLUMN] == native.REJECTED_PARENT)
        if int(rejected.sum()) != 1:
            raise ValueError("FOODON kernel must quarantine exactly one emitted parent")
        index = frame.index[rejected][0]
        self.verify_bindings()
        self.writer.writerow(
            {
                "source_file": str(source_file),
                "normalization_input_row_json": native.canonical(originals.loc[index].to_dict()),
                "canonical_prior_row_json": native.canonical(frame.loc[index].to_dict()),
                "disposition": self.policy["disposition"],
                "rationale": self.policy["rationale"],
                "native_json_evidence_json": native.canonical(self.evidence.json_records),
                "native_owl_evidence_json": native.canonical(self.evidence.owl_records),
                "consumed_inputs_json": native.canonical(self.identities),
            }
        )
        self.projected = True
        return frame.loc[~rejected]

    def verify_bindings(self, *, staged_members=None):
        """Do not allow an active consumed role to disappear or acquire a later identity."""
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        try:
            if self._failure:
                raise SourceFinalizationRequired("FOODON kernel original binding previously failed")
            if staged_members is not None and selected_members(staged_members) != self._members:
                raise SourceFinalizationRequired(
                    "FOODON kernel explicitly staged scope differs from original selection"
                )
            _check_input_scope(self.transform.consumed_input_snapshots, self._members)
            if _owned_inputs(self.transform.consumed_input_snapshots) != self.identities:
                raise SourceFinalizationRequired("FOODON kernel original role bindings changed")
            if native.digest(self.policy) != native.POLICY_SHA256:
                raise SourceFinalizationRequired("FOODON kernel cached policy changed after native admission")
            if self.evidence is not None and (
                self.evidence.cohort != native.COHORT_IDS
                or native.digest(self.evidence.json_records) != native.JSON_EVIDENCE_SHA256
                or native.digest(self.evidence.owl_records) != native.OWL_EVIDENCE_SHA256
            ):
                raise SourceFinalizationRequired("FOODON kernel cached native evidence changed after admission")
        except BaseException:
            self._failure = True
            raise

    def member_names(self):
        """Return the supplier bound by the actual original prepare_source read."""
        self.verify_bindings()
        return self._members

    def verify_complete(self):
        """Require each prepared FOODON supplier to emit its complete reviewed disposition."""
        self.verify_bindings()
        if self.prepared != self.projected:
            raise ValueError("FOODON kernel prepared source was not completely emitted")
        self.transform.verify_consumed_inputs()


class RecordedKernelBinding:
    """Retain the independently admitted supplier and native roles after a fresh-instance repeat."""

    def __init__(self, transform, members):
        """Restore only after public admission has validated the report's exact member selection."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        selected = selected_members(members)
        _check_input_scope(transform.consumed_input_snapshots, selected)
        roles = _owned_inputs(transform.consumed_input_snapshots)
        sealed = native.canonical(roles)
        inputs = SourceAdmission()
        for identity in roles.values():
            if inputs.capture(identity["path"])["sha256"] != identity["sha256"]:
                raise SourceFinalizationRequired("FOODON kernel restored original input changed")
        inputs.capture_resolution(lambda: str(native.POLICY_FILE.resolve()))
        if roles[native.POLICY_ROLE]["path"] != str(native.POLICY_FILE.resolve()):
            raise SourceFinalizationRequired("FOODON kernel restored original policy selector changed")
        failed = False

        def verify(staged_members):
            """Refuse observed scope/role failures even after an outer caller restores visible fields."""
            nonlocal failed
            try:
                if failed or native.canonical(_owned_inputs(transform.consumed_input_snapshots)) != sealed:
                    raise SourceFinalizationRequired("FOODON kernel restored original binding changed")
                if staged_members is not None and selected_members(staged_members) != selected:
                    raise SourceFinalizationRequired(
                        "FOODON kernel explicitly staged scope differs from restored selection"
                    )
                inputs.verify(metadata_only=True)
            except BaseException:
                failed = True
                raise

        self._verify = verify
        self._members = selected

    def verify_bindings(self, *, staged_members=None):
        """Keep the original scope and roles fixed through repeated publication checks."""
        self._verify(staged_members)

    def member_names(self):
        """Return the previously admitted selection without inspecting unrelated output files."""
        self.verify_bindings()
        return self._members


def verify_kernel_audit_bindings(directory, snapshots, *, members, admission=None):
    """Validate native input/audit/graph agreement without modifying any graph rows."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    selected = selected_members(members)
    _check_input_scope(snapshots, selected)
    guard.capture_resolution(lambda: native.canonical([_owned_inputs(snapshots), selected_members(members)]))

    def read(role):
        """Capture a required native role and verify its recorded content digest."""
        identity = snapshots.get(role)
        if not isinstance(identity, dict) or set(identity) != {"path", "sha256"}:
            raise SourceFinalizationRequired(f"Missing FOODON kernel input role: {role}")
        payload = guard.capture(identity["path"], retain=True)
        import hashlib

        if hashlib.sha256(payload).hexdigest() != identity["sha256"]:
            raise SourceFinalizationRequired(f"Changed FOODON kernel input role: {role}")
        return payload

    policy = native.load_policy(io.StringIO(read(native.POLICY_ROLE).decode()))
    payload = guard.capture(Path(directory) / native.AUDIT_FILE, retain=True)
    reader = csv.DictReader(io.StringIO(payload.decode()), delimiter="\t")
    rows = list(reader)
    if tuple(reader.fieldnames or ()) != AUDIT_FIELDS or any(None in row or None in row.values() for row in rows):
        raise SourceFinalizationRequired("Malformed FOODON kernel audit")
    evidence = None
    if native.JSON_ROLE in snapshots:
        graphs = json.loads(read(native.JSON_ROLE), object_pairs_hook=native.unique_object).get("graphs")
        if native.json_evidence(graphs, policy) is not None:
            _, evidence = native.reviewed_hierarchy(graphs, policy, native_owl=io.BytesIO(read(native.OWL_ROLE)))
        elif native.OWL_ROLE in snapshots:
            raise SourceFinalizationRequired("FOODON kernel empty native cohort has an unexpected OWL role")
    if len(rows) != int(evidence is not None):
        raise SourceFinalizationRequired("FOODON kernel audit/native cohort mismatch")
    node_path = Path(directory) / "foodon_nodes.tsv"
    if selected:
        guard.capture(node_path)
        with node_path.open(encoding="utf-8", newline="") as stream:
            declared = {
                row["id"]
                for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                if row["id"] in native.COHORT_IDS
            }
        if declared != (evidence.cohort if evidence is not None else set()):
            raise SourceFinalizationRequired("FOODON kernel graph declarations lack complete native evidence")
    if evidence is not None:
        row = rows[0]
        identities = {role: snapshots[role] for role in (native.POLICY_ROLE, native.JSON_ROLE, native.OWL_ROLE)}
        if (
            row["consumed_inputs_json"] != native.canonical(identities)
            or row["native_json_evidence_json"] != native.canonical(evidence.json_records)
            or row["native_owl_evidence_json"] != native.canonical(evidence.owl_records)
            or row["disposition"] != policy["disposition"]
            or row["rationale"] != policy["rationale"]
        ):
            raise SourceFinalizationRequired("FOODON kernel audit/native evidence changed")
        prior = json.loads(row["canonical_prior_row_json"])
        if _key(prior) != (native.ROOT_ID, "biolink:subclass_of", native.REJECTED_PARENT, "rdfs:subClassOf"):
            raise SourceFinalizationRequired("FOODON kernel quarantined assertion changed")
        original = json.loads(row["normalization_input_row_json"])
        if _key(original) != _key(prior):
            raise SourceFinalizationRequired("FOODON kernel original assertion changed")
    graph_path = Path(directory) / "foodon_edges.tsv"
    emitted = Counter()
    if selected:
        guard.capture(graph_path)
        with graph_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                if _incident(row, set(policy["cohort"])):
                    if row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] != "infores:foodon":
                        raise SourceFinalizationRequired("FOODON kernel retained assertion provenance changed")
                    emitted[_key(row)] += 1
    if emitted != (_expected(policy, retained=True) if evidence is not None else Counter()):
        raise SourceFinalizationRequired("FOODON kernel retained graph/audit cohort mismatch")
    guard.verify(metadata_only=True)
