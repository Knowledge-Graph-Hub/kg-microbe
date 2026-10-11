"""Seventeen finite MeSH category projections grounded in complete native RDF records."""

import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    CHEMICAL_CATEGORY,
    FOOD_CATEGORY,
    ID_COLUMN,
    NCBI_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
    PHYSICAL_ENTITY_CATEGORY,
    SOLUTION_CATEGORY,
)
from kg_microbe.utils.native_rdf import decoded_iri_subject

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/mesh_finite_category_dispositions.json"
POLICY_SHA256 = "68134819099fc24e7d011d2e725e62f042bbeeafd6b673640e95d6ac9d4550c0"
CONTRACT_KEY = "mesh_finite_category_authority"
NATIVE_ROLE = "category_authority_mesh2026.nt"
POLICY_ROLE = "category_authority_mesh_finite_category_dispositions"
MODEL_ROLE = "category_authority_biolink-model"
_CATEGORIES = {
    **dict.fromkeys(
        (
            "mesh:C008328",
            "mesh:C013216",
            "mesh:C016600",
            "mesh:C017029",
            "mesh:C028805",
            "mesh:C039460",
            "mesh:C514290",
            "mesh:C521980",
            "mesh:D014131",
        ),
        CHEMICAL_CATEGORY,
    ),
    **dict.fromkeys(("mesh:D000076624", "mesh:D000083422", "mesh:D015048", "mesh:D062611"), PHYSICAL_ENTITY_CATEGORY),
    **dict.fromkeys(("mesh:D011136", "mesh:D012623"), SOLUTION_CATEGORY),
    "mesh:D004531": FOOD_CATEGORY,
    "mesh:D044003": NCBI_CATEGORY,
}
FINITE_IDS = frozenset(_CATEGORIES)
_VOCAB = "http://id.nlm.nih.gov/mesh/vocab#"
_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


def canonical(value):
    """Retain native structured values independently of JSON presentation."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    """Hash literal bytes, never label-derived identity or an inferred ontology assertion."""
    return hashlib.sha256(value).hexdigest()


def unique_object(pairs):
    """Refuse last-key-wins changes to the finite policy or cached evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate finite MeSH policy key: {key}")
        result[key] = value
    return result


def load_policy(stream):
    """Require the complete reviewed cohort, categories, definitions and independent byte pins."""
    policy = json.load(stream, object_pairs_hook=unique_object)
    if digest(canonical(policy).encode()) != POLICY_SHA256:
        raise ValueError("Unreviewed finite MeSH category policy")
    if (
        type(policy["version"]) is not int
        or policy["version"] != 1
        or {identifier: row["category"] for identifier, row in policy["records"].items()} != _CATEGORIES
        or policy["native_file"] != "mesh2026.nt.gz"
        or policy["native_namespace"] != "http://id.nlm.nih.gov/mesh/2026/"
        or policy["model_file"] != "biolink-model.yaml"
    ):
        raise ValueError("Invalid finite MeSH native/category routes")
    return policy


def _subjects(policy):
    return {
        iri
        for identifier, row in policy["records"].items()
        for iri in (policy["native_namespace"] + identifier.split(":", 1)[1], row["preferred_concept"])
    }


def validate_evidence(records, policy):
    """Verify every literal statement and the preferred meaning, never a nonpreferred genus note."""
    lines = [line for rows in records.values() for line in rows]
    if (
        set(records) != _subjects(policy)
        or len(lines) != policy["native_statement_count"]
        or len(lines) != len(set(lines))
        or digest(("\n".join(sorted(lines)) + "\n").encode()) != policy["native_statements_sha256"]
    ):
        raise ValueError("Finite MeSH native statements changed, missing or duplicated")

    def values(iri, predicate):
        """Extract sorted native objects only from structurally matching statements."""
        result = []
        for line in records[iri]:
            subject, pred, obj = line.split(" ", 2)
            if subject != f"<{iri}>" or not obj.endswith(" ."):
                raise ValueError("Finite MeSH native literal statement changed")
            if pred == f"<{predicate}>":
                result.append(obj[:-2])
        return sorted(result)

    for identifier, decision in policy["records"].items():
        local = identifier.split(":", 1)[1]
        iri, concept = policy["native_namespace"] + local, decision["preferred_concept"]
        expected = {
            _TYPE: [f"<{_VOCAB}{decision['native_type']}>"],
            _LABEL: [decision["native_label_token"]],
            _VOCAB + "identifier": [f'"{local}"'],
            _VOCAB + "preferredConcept": [f"<{concept}>"],
            _VOCAB + "note": sorted(decision["native_notes"]),
        }
        if any(values(iri, pred) != target for pred, target in expected.items()):
            raise ValueError("Finite MeSH native descriptor/SCR context changed")
        if (
            values(concept, _TYPE) != [f"<{_VOCAB}Concept>"]
            or values(concept, _LABEL) != [decision["native_label_token"]]
            or values(concept, _VOCAB + "scopeNote") != sorted(decision["preferred_scope_notes"])
        ):
            raise ValueError("Finite MeSH preferred concept meaning changed")


def read_native_evidence(binary, policy):
    """Stream the actual admitted gzip once, retaining only 34 complete native subject records."""
    subjects = _subjects(policy)
    wanted = {iri.rsplit("/", 1)[-1] for iri in subjects}
    records = {iri: [] for iri in subjects}
    with gzip.GzipFile(fileobj=binary, mode="rb") as stream:
        for raw in stream:
            tokens = raw.split(None, 1)
            if not tokens:
                continue
            subject = decoded_iri_subject(tokens[0], authority="Finite MeSH")
            token = subject.rsplit(b"/", 1)[-1].rstrip(b">").decode("ascii", errors="replace")
            if token not in wanted:
                continue
            iri = subject[1:-1].decode("utf-8")
            if subject != f"<{policy['native_namespace']}{token}>".encode() or iri not in records:
                raise ValueError("Finite MeSH native release namespace changed")
            records[iri].append(raw.decode("utf-8").rstrip("\n"))
    validate_evidence(records, policy)
    return records


def validate_model(model, policy):
    """Use active concrete classes; do not pretend built elements are natural environmental features."""
    if (
        model.get("version") != policy["model_version"]
        or {key: model.get("classes", {}).get(key) for key in policy["model_classes"]} != policy["model_classes"]
    ):
        raise ValueError("Finite MeSH selected model definitions changed")
    for key in ("physical entity", "chemical entity", "chemical mixture", "food", "organism taxon"):
        if any(model["classes"][key].get(flag) for flag in ("deprecated", "abstract", "mixin")):
            raise ValueError("Finite MeSH category is not active and concrete")


def _selected_native(raw_dir, admission, policy):
    selected = Path(raw_dir).absolute() / policy["native_file"]
    if not selected.resolve().is_relative_to(Path(raw_dir).resolve()):
        raise ValueError("Finite MeSH native authority is outside the selected raw directory")
    observed = admission.capture(selected)
    if observed != {"sha256": policy["native_sha256"], "bytes": policy["native_bytes"]}:
        raise ValueError("Finite MeSH selected native export differs from the reviewed pin")
    return {"selected_path": str(selected), "resolved_path": str(selected.resolve()), **observed}


def _output_counts(paths):
    from kg_microbe.utils.source_finalization import graph_rows

    counts = Counter()
    for path in paths:
        for row in graph_rows(path):
            identifier = row[ID_COLUMN]
            if identifier in FINITE_IDS:
                if row[CATEGORY_COLUMN] != _CATEGORIES[identifier]:
                    raise ValueError("Finite MeSH category is not finalized")
                counts[identifier] += 1
    return dict(sorted(counts.items()))


class FiniteMeshCategoryAuthority:
    """Read one immutable native witness per run, retaining original input roles through publication."""

    identifiers = FINITE_IDS

    def __init__(self, raw_dir, *, opener):
        """Keep truthful zero cohorts inert, including sources using the separate clinical policy."""
        self.raw_dir, self.opener = Path(raw_dir), opener
        self.source_paths = set()
        self._policy_json = self._evidence_json = self._contract_json = None
        self._output_counts_json = None
        self._node_members = None
        self._node_members_json = None
        self._admission = None
        self._seen = set()

    def _prepare(self):
        if self._policy_json is not None:
            self.verify()
            return
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        admission = SourceAdmission()
        policy_bytes = admission.capture(POLICY_FILE, retain=True)
        with self.opener(POLICY_FILE) as stream:
            consumed = stream.read().encode()
        if consumed != policy_bytes:
            raise ValueError("Finite MeSH consumed policy differs from original bytes")
        policy = load_policy(io.StringIO(consumed.decode()))
        authority = _selected_native(self.raw_dir, admission, policy)
        selected = Path(authority["selected_path"])
        with self.opener(selected) as stream:
            if Path(stream.name).resolve() == selected.resolve():
                raise ValueError("Finite MeSH reader requires an immutable private snapshot")
            binary = stream.buffer
            hasher = hashlib.sha256()
            for block in iter(lambda: binary.read(1024 * 1024), b""):
                hasher.update(block)
            if hasher.hexdigest() != policy["native_sha256"]:
                raise ValueError("Finite MeSH consumed gzip differs from original selection")
            binary.seek(0)
            evidence = read_native_evidence(binary, policy)
        model_path = self.raw_dir / policy["model_file"]
        model_identity = admission.capture(model_path)
        with self.opener(model_path) as stream:
            model_bytes = stream.read().encode()
        if digest(model_bytes) != policy["model_sha256"] or digest(model_bytes) != model_identity["sha256"]:
            raise ValueError("Finite MeSH consumed model differs from reviewed pin")
        validate_model(yaml.safe_load(model_bytes), policy)
        admission.verify(metadata_only=True)
        self._policy_json, self._evidence_json = canonical(policy), canonical(evidence)
        self._contract_json = canonical(
            {
                "version": 1,
                "authority": authority,
                "policy": {"path": str(POLICY_FILE.resolve()), "sha256": digest(policy_bytes)},
                "model": {"path": str(model_path.resolve()), "sha256": digest(model_bytes)},
                "native_evidence_sha256": policy["native_statements_sha256"],
            }
        )
        self._admission = admission
        self.source_paths.update((POLICY_FILE, selected, model_path))

    def category_for(self, identifier):
        """Return only a reviewed exact-ID decision; no prefix, parent, label or tree propagation."""
        if identifier not in FINITE_IDS:
            return None
        self._prepare()
        self._seen.add(identifier)
        return _CATEGORIES[identifier]

    def bind_node_members(self, paths):
        """Seal this admitted bundle's scope before inspecting a shared ontology output directory."""
        members = tuple(sorted(Path(path).name for path in paths))
        if len(members) != len(set(members)) or any(not name.endswith("nodes.tsv") for name in members):
            raise ValueError("Invalid finite MeSH node member scope")
        serialized = canonical(members)
        if self._node_members_json is not None and self._node_members_json != serialized:
            raise ValueError("Finite MeSH original node member scope changed")
        self._node_members, self._node_members_json = members, serialized

    def verify(self, snapshots=None, *, output_dir=None):
        """Check original locators, parsed witnesses, roles and independently counted output rows."""
        if self._node_members_json is not None and canonical(self._node_members) != self._node_members_json:
            raise ValueError("Finite MeSH original node member scope changed")
        if self._policy_json is None:
            if self._seen or self._evidence_json is not None or self._contract_json is not None:
                raise ValueError("Finite MeSH prepared evidence was cleared")
            if snapshots is not None and POLICY_ROLE in snapshots:
                raise ValueError("Finite MeSH missing guard contradicts consumed policy")
        else:
            policy = load_policy(io.StringIO(self._policy_json))
            validate_evidence(json.loads(self._evidence_json, object_pairs_hook=unique_object), policy)
            self._admission.verify(metadata_only=True)
            contract = json.loads(self._contract_json, object_pairs_hook=unique_object)
            selected = self.raw_dir.absolute() / policy["native_file"]
            expected = {
                "version": 1,
                "authority": {
                    "selected_path": str(selected),
                    "resolved_path": str(selected.resolve()),
                    "sha256": policy["native_sha256"],
                    "bytes": policy["native_bytes"],
                },
                "policy": {
                    "path": str(POLICY_FILE.resolve()),
                    "sha256": self._admission.identities[POLICY_FILE.resolve()]["sha256"],
                },
                "model": {
                    "path": str((self.raw_dir / policy["model_file"]).resolve()),
                    "sha256": policy["model_sha256"],
                },
                "native_evidence_sha256": policy["native_statements_sha256"],
            }
            if contract != expected or not self._seen <= FINITE_IDS:
                raise ValueError("Finite MeSH original interpreted receipt changed")
            roles = {
                POLICY_ROLE: expected["policy"],
                MODEL_ROLE: expected["model"],
                NATIVE_ROLE: {"path": expected["authority"]["resolved_path"], "sha256": policy["native_sha256"]},
            }
            if snapshots is not None and any(snapshots.get(role) != value for role, value in roles.items()):
                raise ValueError("Finite MeSH original consumed-input role changed")
        if output_dir is not None:
            if self._node_members is None:
                self.bind_node_members(Path(output_dir).glob("*nodes.tsv"))
            counts = _output_counts([Path(output_dir) / name for name in self._node_members])
            if set(counts) != self._seen:
                raise ValueError("Finite MeSH source declaration inventory changed")
            serialized = canonical(counts)
            if self._output_counts_json is not None and self._output_counts_json != serialized:
                raise ValueError("Finite MeSH source declaration occurrence counts changed")
            self._output_counts_json = serialized

    def contract(self):
        """Publish a detached receipt only after actual staged row counts have been verified."""
        self.verify()
        if self._policy_json is None:
            return {"version": 1, "authority": None}
        if self._output_counts_json is None:
            raise ValueError("Finite MeSH output occurrence inventory has not been verified")
        return {
            **json.loads(self._contract_json),
            "identifiers": sorted(self._seen),
            "occurrences": json.loads(self._output_counts_json),
            "node_members": list(self._node_members),
        }


def apply_category(existing, category):
    """Replace only generic fallback typing; do not erase any conflicting substantive category."""
    if category is None:
        return existing
    if category not in set(_CATEGORIES.values()):
        raise ValueError("Unreviewed finite MeSH category")
    if set(existing.split("|")) - {"", ONTOLOGY_CLASS_CATEGORY, "biolink:NamedThing", category}:
        raise ValueError("Conflicting substantive finite MeSH category")
    return category


def verify_recorded_inputs(report, report_path, *, admission=None):
    """Admit exact categories and native bindings without modifying any source or merged graph."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    try:
        contract = report.get(CONTRACT_KEY)
        if not isinstance(contract, dict) or type(contract.get("version")) is not int or contract["version"] != 1:
            raise ValueError("missing versioned contract")
        members = sorted(name for name in report.get("members", {}) if name.endswith("nodes.tsv"))
        if any(Path(name).name != name for name in members):
            raise ValueError("nonlocal finite source member")
        paths = [Path(report_path).parent / name for name in members]
        for path in paths:
            guard.capture(path)
        counts = _output_counts(paths)
        snapshots = report.get("consumed_inputs", {})
        if contract.get("authority") is None:
            # The clinical policy may independently consume the same MeSH file.
            if contract != {"version": 1, "authority": None} or counts or POLICY_ROLE in snapshots:
                raise ValueError("null authority contradicts finite source evidence")
        else:
            if (
                set(contract)
                != {
                    "version",
                    "authority",
                    "policy",
                    "model",
                    "native_evidence_sha256",
                    "identifiers",
                    "occurrences",
                    "node_members",
                }
                or contract["identifiers"] != sorted(counts)
                or contract["occurrences"] != counts
                or contract["node_members"] != members
                or any(type(value) is not int for value in contract["occurrences"].values())
                or not counts
            ):
                raise ValueError("finite source declaration inventory changed")
            identity = contract["policy"]
            if snapshots.get(POLICY_ROLE) != identity or Path(identity["path"]).resolve() != POLICY_FILE.resolve():
                raise ValueError("finite policy role changed")
            content = guard.capture(identity["path"], retain=True)
            if digest(content) != identity["sha256"]:
                raise ValueError("finite policy bytes changed")
            policy = load_policy(io.StringIO(content.decode()))
            authority = _selected_native(report["raw_input_directory"], guard, policy)
            if authority != contract["authority"]:
                raise ValueError("finite native locator changed")
            if snapshots.get(NATIVE_ROLE) != {"path": authority["resolved_path"], "sha256": policy["native_sha256"]}:
                raise ValueError("finite native role changed")
            model_path = Path(report["raw_input_directory"]) / policy["model_file"]
            expected_model = {"path": str(model_path.resolve()), "sha256": policy["model_sha256"]}
            if contract["model"] != expected_model or snapshots.get(MODEL_ROLE) != expected_model:
                raise ValueError("finite model role changed")
            model_bytes = guard.capture(model_path, retain=True)
            if digest(model_bytes) != policy["model_sha256"]:
                raise ValueError("finite model bytes changed")
            validate_model(yaml.safe_load(model_bytes), policy)
            if contract["native_evidence_sha256"] != policy["native_statements_sha256"]:
                raise ValueError("finite native statement witness changed")
        guard.verify(metadata_only=True)
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceFinalizationRequired("Invalid finite MeSH category authority contract") from exc
    return guard


def restore_recorded_guard(transform, report, report_path):
    """Restore a live immutable guard on repeated finalization, without replaying graph edits."""
    verify_recorded_inputs(report, report_path)

    def opener(path):
        """Rebind each original authority file to its named immutable input role."""
        return transform.consume_input(f"category_authority_{Path(path).stem}", path)

    authority = FiniteMeshCategoryAuthority(transform.input_base_dir, opener=opener)
    for identifier in report[CONTRACT_KEY].get("identifiers", ()):
        authority.category_for(identifier)
    authority.bind_node_members(name for name in report["members"] if name.endswith("nodes.tsv"))
    authority.verify(transform.consumed_input_snapshots, output_dir=Path(report_path).parent)
    if authority.contract() != report[CONTRACT_KEY]:
        raise ValueError("Finite MeSH restored authority differs from recorded contract")
    transform._mesh_finite_category_guard = authority
    return authority
