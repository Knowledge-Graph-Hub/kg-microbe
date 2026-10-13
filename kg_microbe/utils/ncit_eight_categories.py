"""Twenty-two finite NCIT projections; historical contract names remain stable."""

import hashlib
import io
import json
import sqlite3
from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    CELLULAR_ORGANISM_CATEGORY,
    CHEMICAL_CATEGORY,
    FOOD_CATEGORY,
    ID_COLUMN,
    MATERIAL_SAMPLE_CATEGORY,
    NAMED_THING_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
    PHENOTYPIC_FEATURE_CATEGORY,
    PHYSICAL_ENTITY_CATEGORY,
    SOLUTION_CATEGORY,
)
from kg_microbe.transform_utils.ontologies_stubs.ncit_category_projection import native_contract
from kg_microbe.utils.atomic_io import gunzip_beside
from kg_microbe.utils.release_binding import semsql_release

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/ncit_eight_categories.json"
POLICY_SHA256 = "aeee20a68b51a94353eb86fa0a97d422cfe4f39b0fce3a288e9cffeee5fd2b8e"
CONTRACT_KEY = "ncit_eight_category_authority"
NATIVE_ROLE = "category_authority_ncit"
POLICY_ROLE = "category_authority_ncit_eight_categories"
MODEL_ROLE = "category_authority_biolink-model"
_CATEGORIES = {
    **dict.fromkeys(
        ("NCIT:C66725", "NCIT:C71932", "NCIT:C71971", "NCIT:C72000", "NCIT:C72005", "NCIT:C84877"),
        FOOD_CATEGORY,
    ),
    **dict.fromkeys(("NCIT:C14191", "NCIT:C14212", "NCIT:C77916"), CELLULAR_ORGANISM_CATEGORY),
    **dict.fromkeys(
        (
            "NCIT:C113696",
            "NCIT:C120264",
            "NCIT:C120561",
            "NCIT:C29298",
            "NCIT:C29321",
            "NCIT:C77500",
            "NCIT:C77524",
            "NCIT:C85253",
            "NCIT:C87343",
        ),
        CHEMICAL_CATEGORY,
    ),
    "NCIT:C13347": MATERIAL_SAMPLE_CATEGORY,
    "NCIT:C28176": PHYSICAL_ENTITY_CATEGORY,
    "NCIT:C85509": SOLUTION_CATEGORY,
    "NCIT:C3824": PHENOTYPIC_FEATURE_CATEGORY,
}
FINITE_IDS = frozenset(_CATEGORIES)
# These are individually reviewed supporting paths, not propagation roots.
# In particular Industrial Aid and Other Organism Groupings do not themselves
# authorize a chemical or cellular/taxonomic category for every descendant.
_NATIVE_ROOTS = {
    **dict.fromkeys(
        ("NCIT:C66725", "NCIT:C71932", "NCIT:C71971", "NCIT:C72000", "NCIT:C72005", "NCIT:C84877"),
        "NCIT:C62695",
    ),
    **dict.fromkeys(("NCIT:C14191", "NCIT:C14212"), "NCIT:C14234"),
    "NCIT:C113696": "NCIT:C802",
    "NCIT:C120264": "NCIT:C48807",
    "NCIT:C120561": "NCIT:C29730",
    "NCIT:C13347": "NCIT:C19157",
    "NCIT:C28176": "NCIT:C14376",
    "NCIT:C29298": "NCIT:C29639",
    "NCIT:C29321": "NCIT:C802",
    "NCIT:C77500": "NCIT:C45678",
    "NCIT:C77524": "NCIT:C45678",
    "NCIT:C77916": "NCIT:C25796",
    "NCIT:C85253": "NCIT:C735",
    "NCIT:C85509": "NCIT:C85504",
    "NCIT:C87343": "NCIT:C1505",
    "NCIT:C3824": "NCIT:C3367",
}
_MODEL_CATEGORIES = {
    FOOD_CATEGORY: "food",
    CELLULAR_ORGANISM_CATEGORY: "cellular organism",
    CHEMICAL_CATEGORY: "chemical entity",
    MATERIAL_SAMPLE_CATEGORY: "material sample",
    PHYSICAL_ENTITY_CATEGORY: "physical entity",
    SOLUTION_CATEGORY: "chemical mixture",
    PHENOTYPIC_FEATURE_CATEGORY: "phenotypic feature",
}


def canonical(value):
    """Preserve native structured evidence while disregarding only JSON presentation."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    """Hash exact consumed or canonical evidence bytes."""
    return hashlib.sha256(value).hexdigest()


def unique_object(pairs):
    """Never treat repeated policy keys as an override."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate finite NCIT evidence key: {key}")
        result[key] = value
    return result


def load_policy(stream):
    """Bind the complete reviewed decisions and witnesses independently of mutable receipts."""
    policy = json.load(stream, object_pairs_hook=unique_object)
    if digest(canonical(policy).encode()) != POLICY_SHA256:
        raise ValueError("Unreviewed finite NCIT category policy")
    if (
        type(policy["version"]) is not int
        or policy["version"] != 2
        or {key: value["category"] for key, value in policy["records"].items()} != _CATEGORIES
        or policy["native_file"] != "ncit.db"
        or policy["model_file"] != "biolink-model.yaml"
    ):
        raise ValueError("Invalid finite NCIT category routes")
    return policy


def validate_statements(statements, policy):
    """Check full selected declarations and asserted ancestry, preserving absent definitions."""
    if statements != policy["native_statements"]:
        raise ValueError("Finite NCIT native statements changed")
    for identifier, rows in statements.items():
        types = [row["object"] for row in rows if row["predicate"] == "rdf:type"]
        labels = [row["value"] for row in rows if row["predicate"] == "rdfs:label"]
        if types != ["owl:Class"] or len(labels) != 1 or not labels[0]:
            raise ValueError(f"Finite NCIT declaration is missing, duplicated or not a class: {identifier}")
        if len(rows) != len({canonical(row) for row in rows}):
            raise ValueError(f"Duplicated finite NCIT statement: {identifier}")
        if any(
            (row["predicate"] == "owl:deprecated" and str(row["value"]).lower() not in {"false", "0"})
            or (row["predicate"] == "NCIT:P310" and "retir" in (row["value"] or "").lower())
            for row in rows
        ):
            raise ValueError(f"Deprecated finite NCIT ancestor: {identifier}")
    for identifier, decision in policy["records"].items():
        pending, visited = [identifier], set()
        while pending:
            current = pending.pop()
            if current in visited or current == "owl:Thing":
                continue
            if current not in statements:
                raise ValueError("Finite NCIT asserted ancestor lacks a native declaration")
            visited.add(current)
            pending.extend(row["object"] for row in statements[current] if row["predicate"] == "rdfs:subClassOf")
        if sorted(visited) != decision["native_complete_ancestor_ids"]:
            raise ValueError("Finite NCIT complete ancestor inventory changed")
        root = _NATIVE_ROOTS[identifier]
        path = decision["root_path"]
        if path[0] != identifier or path[-1] != root:
            raise ValueError("Finite NCIT reviewed root path changed")
        for child, parent in zip(path, path[1:], strict=False):
            if not any(row["predicate"] == "rdfs:subClassOf" and row["object"] == parent for row in statements[child]):
                raise ValueError("Finite NCIT category has no asserted root path")
        for predicate, field in (("IAO:0000115", "native_definitions"), ("NCIT:P106", "native_semantic_types")):
            if sorted(row["value"] for row in statements[identifier] if row["predicate"] == predicate) != sorted(
                decision[field]
            ):
                raise ValueError("Finite NCIT native annotation presence/absence changed")
        if (
            "native_additional_definitions" in decision
            and sorted(row["value"] for row in statements[identifier] if row["predicate"] == "NCIT:P325")
            != decision["native_additional_definitions"]
        ):
            raise ValueError("Finite NCIT additional definition presence/absence changed")


def validate_model(model, policy):
    """Use active concrete categories in the selected pinned model, never deprecated Mammal."""
    if (
        model.get("version") != policy["model_version"]
        or {key: model.get("classes", {}).get(key) for key in policy["model_classes"]} != policy["model_classes"]
    ):
        raise ValueError("Finite NCIT selected Biolink category evidence changed")
    for key in _MODEL_CATEGORIES.values():
        if any(model["classes"][key].get(flag) for flag in ("deprecated", "abstract", "mixin")):
            raise ValueError("Finite NCIT projection requires active concrete categories")


def _select_native(raw_dir, admission):
    """Bind the chosen raw locator and absent SQLite state without any cache fallback."""
    raw = Path(raw_dir).resolve()
    selected = Path(raw_dir).absolute() / "ncit.db"
    resolved = selected.resolve()
    if not resolved.is_relative_to(raw):
        raise ValueError("Finite NCIT authority is outside the selected raw directory")
    authority = native_contract(selected, resolved, "pending")["authority"]
    for name in authority["absent_sqlite_sidecars"]:
        path = Path(name)
        if path.exists() or path.is_symlink():
            raise ValueError(f"Finite NCIT SQLite sidecar exists: {path}")
        admission.capture(path, optional=True)
    observed = admission.capture(selected)
    authority["sha256"] = observed["sha256"]
    admission.capture_resolution(_verify_sqlite_state, canonical(authority), admission)
    return authority


def _verify_sqlite_state(authority_json, admission):
    """Derive mandatory absence from the native locator, not a mutable optional-input cache."""
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    authority = json.loads(authority_json)
    selected = Path(authority["selected_path"])
    resolved = Path(authority["resolved_path"])
    expected = native_contract(selected, resolved, authority["sha256"])["authority"]
    if authority != expected or selected.resolve() != resolved or resolved.resolve() != resolved:
        raise SourceFinalizationRequired("Finite NCIT SQLite original locator or absence contract changed")
    for name in expected["absent_sqlite_sidecars"]:
        path = Path(name)
        if path.exists() or path.is_symlink():
            raise SourceFinalizationRequired(f"Finite NCIT SQLite sidecar exists: {path}")
        if path.resolve() not in admission.absent or admission.bindings.get(path.absolute()) != path.resolve():
            raise SourceFinalizationRequired("Finite NCIT SQLite mandatory absence guard is incomplete")
    return authority_json


class FiniteNcitCategoryAuthority:
    """Read one immutable native snapshot, then retain interpreted evidence and locator guards."""

    def __init__(self, raw_dir, *, opener):
        """Stay inert until one of the exact reviewed IDs is encountered."""
        self.raw_dir = Path(raw_dir)
        self.opener = opener
        self.source_paths = set()
        self._policy_json = None
        self._evidence_json = None
        self._contract_json = None
        self._admission = None
        self._seen = set()
        self._members = None
        self._release_json = None

    def bind_members(self, names):
        """Bind only the selected source bundle, never all nearby ontology files."""
        names = tuple(sorted(names))
        if (
            not names
            or len(names) != len(set(names))
            or any(Path(name).name != name or not name.endswith("nodes.tsv") for name in names)
            or (self._members is not None and self._members != names)
            or (self._policy_json is not None and self._members is None)
        ):
            raise ValueError("Finite NCIT node-member selection is missing, malformed or rebound")
        self._members = names

    def _prepare(self):
        """Parse only the consumed private SQLite copy, never reopen the mutable native locator."""
        self.verify()
        if self._policy_json is not None:
            return
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        admission = SourceAdmission()
        policy_bytes = admission.capture(POLICY_FILE, retain=True)
        with self.opener(POLICY_FILE) as stream:
            consumed = stream.read()
        if consumed.encode() != policy_bytes:
            raise ValueError("Finite NCIT policy changed while consuming it")
        policy = load_policy(io.StringIO(consumed))
        # Policy version 2 binds the reviewed statements, not ncit.db's bytes (#1420).
        # SemanticSQL republishes ncit.db.gz at one URL, so any release whose reviewed
        # statements are unchanged is accepted. The bytes and the release actually read
        # are recorded in the receipt, and every later check compares against that record.
        # ncit.db is downloaded gzipped. FOODON's NCIT ids reach this authority while the
        # ontologies source finalizes, before ontologies_stubs would unpack it (#1526).
        gunzip_beside(Path(self.raw_dir) / "ncit.db", root=self.raw_dir)
        authority = _select_native(self.raw_dir, admission)
        selected = Path(authority["selected_path"])
        with self.opener(selected) as stream:
            if Path(stream.name).resolve() == selected.resolve():
                raise ValueError("Finite NCIT SQLite reader requires a consumed immutable private snapshot")
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.buffer.read(1024 * 1024), b""):
                hasher.update(block)
            if hasher.hexdigest() != authority["sha256"]:
                raise ValueError("Finite NCIT consumed snapshot differs from the native selection")
            with sqlite3.connect(Path(stream.name).as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
                connection.row_factory = sqlite3.Row
                statements = {
                    identifier: sorted(
                        (
                            dict(row)
                            for row in connection.execute(
                                "SELECT predicate,object,value,datatype,language FROM statements WHERE subject=?",
                                (identifier,),
                            )
                        ),
                        key=lambda row: json.dumps(row, sort_keys=True),
                    )
                    for identifier in policy["native_statements"]
                }
                release = semsql_release(connection, "ncit")
        validate_statements(statements, policy)
        model_path = self.raw_dir / policy["model_file"]
        model_identity = admission.capture(model_path)
        with self.opener(model_path) as stream:
            model_bytes = stream.read().encode()
        if digest(model_bytes) != model_identity["sha256"] or digest(model_bytes) != policy["model_sha256"]:
            raise ValueError("Finite NCIT selected model bytes differ from the reviewed pin")
        validate_model(yaml.safe_load(model_bytes), policy)
        admission.verify(metadata_only=True)
        contract = {
            "version": 1,
            "authority": authority,
            "policy": {"path": str(POLICY_FILE.resolve()), "sha256": digest(policy_bytes)},
            "model": {"path": str(model_path.resolve()), "sha256": digest(model_bytes)},
            "native_evidence_sha256": digest(canonical(statements).encode()),
            "native_release": release,
            "node_members": list(self._members) if self._members is not None else None,
        }
        self.source_paths.update((POLICY_FILE, selected, model_path))
        self._policy_json = canonical(policy)
        self._evidence_json = canonical(statements)
        self._contract_json = canonical(contract)
        self._release_json = canonical(release)
        self._admission = admission

    def category_for(self, identifier):
        """Return only a reviewed finite target, with no label/semantic-type propagation."""
        if identifier not in FINITE_IDS:
            return None
        self._prepare()
        self._seen.add(identifier)
        return _CATEGORIES[identifier]

    def contract(self):
        """Return a detached receipt, not the mutable state defining original admission."""
        self.verify()
        if self._contract_json is None:
            return {"version": 1, "authority": None}
        return {**json.loads(self._contract_json), "identifiers": sorted(self._seen)}

    def verify(self, snapshots=None, *, output_dir=None):
        """Retain byte/locator/sidecar and interpreted-evidence guards until publication."""
        observed = None
        if output_dir is not None:
            from kg_microbe.utils.source_finalization import graph_rows

            observed = set()
            if not self._members:
                raise ValueError("Finite NCIT verification requires its selected node members")
            for name in self._members:
                path = Path(output_dir) / name
                for row in graph_rows(path):
                    if row[ID_COLUMN] in FINITE_IDS:
                        if row[CATEGORY_COLUMN] != _CATEGORIES[row[ID_COLUMN]]:
                            raise ValueError("Finite NCIT finalized category changed before publication")
                        observed.add(row[ID_COLUMN])
        if self._policy_json is None:
            if (
                self._evidence_json is not None
                or self._contract_json is not None
                or self._admission is not None
                or self._seen
                or observed
                or (snapshots is not None and {NATIVE_ROLE, POLICY_ROLE} & snapshots.keys())
            ):
                raise ValueError("Finite NCIT consumed evidence cannot become a truthful zero cohort")
            return
        policy = load_policy(io.StringIO(self._policy_json))
        if self._evidence_json != canonical(policy["native_statements"]):
            raise ValueError("Finite NCIT interpreted native witness changed")
        contract = json.loads(self._contract_json)
        _verify_sqlite_state(canonical(contract["authority"]), self._admission)
        self._admission.verify(metadata_only=True)
        selected = self.raw_dir.absolute() / "ncit.db"
        native_sha256 = self._admission.identities.get(selected.resolve(), {}).get("sha256")
        if contract["authority"] != native_contract(selected, selected.resolve(), native_sha256)["authority"]:
            raise ValueError("Finite NCIT original native binding changed")
        expected_policy = {
            "path": str(POLICY_FILE.resolve()),
            "sha256": self._admission.identities[POLICY_FILE.resolve()]["sha256"],
        }
        expected_model = {
            "path": str((self.raw_dir / policy["model_file"]).resolve()),
            "sha256": policy["model_sha256"],
        }
        if (
            contract
            != {
                "version": 1,
                "authority": native_contract(selected, selected.resolve(), native_sha256)["authority"],
                "policy": expected_policy,
                "model": expected_model,
                "native_evidence_sha256": digest(self._evidence_json.encode()),
                "native_release": json.loads(self._release_json),
                "node_members": list(self._members) if self._members is not None else None,
            }
            or not self._seen <= FINITE_IDS
        ):
            raise ValueError("Finite NCIT interpreted evidence or original receipt changed")
        expected = {
            NATIVE_ROLE: {"path": contract["authority"]["resolved_path"], "sha256": native_sha256},
            POLICY_ROLE: contract["policy"],
            MODEL_ROLE: contract["model"],
        }
        if snapshots is not None and any(snapshots.get(role) != identity for role, identity in expected.items()):
            raise ValueError("Finite NCIT original consumed-input binding changed")
        if observed is not None and observed != self._seen:
            raise ValueError("Finite NCIT source declaration inventory changed before publication")


def apply_category(existing, category):
    """Replace only generic fallback categories or an idempotent reviewed category."""
    if category is None:
        return existing
    if category not in _MODEL_CATEGORIES:
        raise ValueError("Unreviewed finite NCIT category")
    if set(existing.split("|")) - {"", ONTOLOGY_CLASS_CATEGORY, NAMED_THING_CATEGORY, category}:
        raise ValueError("Conflicting substantive finite NCIT category")
    return category


def verify_recorded_inputs(report, report_path, *, admission=None):
    """Validate finite source categories and original native guards; never rewrite graph data."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

    guard = admission if admission is not None else SourceAdmission()
    contract = report.get(CONTRACT_KEY)
    if not isinstance(contract, dict) or type(contract.get("version")) is not int or contract["version"] != 1:
        raise SourceFinalizationRequired("Missing or malformed finite NCIT category contract")
    observed = set()
    for name in report.get("members", {}):
        if not name.endswith("nodes.tsv"):
            continue
        path = Path(report_path).parent / name
        guard.capture(path)
        for row in graph_rows(path):
            if row[ID_COLUMN] in FINITE_IDS:
                if row[CATEGORY_COLUMN] != _CATEGORIES[row[ID_COLUMN]]:
                    raise SourceFinalizationRequired("Finite NCIT output category is not finalized")
                observed.add(row[ID_COLUMN])
    snapshots = report.get("consumed_inputs", {})
    if contract.get("authority") is None:
        if contract != {"version": 1, "authority": None} or observed or {NATIVE_ROLE, POLICY_ROLE} & snapshots.keys():
            raise SourceFinalizationRequired("Finite NCIT null authority contradicts source evidence")
    else:
        try:
            if (
                set(contract)
                != {
                    "version",
                    "authority",
                    "policy",
                    "model",
                    "native_evidence_sha256",
                    "native_release",
                    "identifiers",
                    "node_members",
                }
                or contract["identifiers"] != sorted(observed)
                or not observed
            ):
                raise ValueError("finite identifier inventory changed")
            if contract["native_release"] is not None and not isinstance(contract["native_release"], str):
                raise ValueError("finite native release provenance is malformed")
            if contract["node_members"] != sorted(name for name in report["members"] if name.endswith("nodes.tsv")):
                raise ValueError("finite node-member selection changed")
            policy_identity = contract["policy"]
            if (
                snapshots.get(POLICY_ROLE) != policy_identity
                or Path(policy_identity["path"]).resolve() != POLICY_FILE.resolve()
            ):
                raise ValueError("finite policy binding changed")
            policy_bytes = guard.capture(policy_identity["path"], retain=True)
            if digest(policy_bytes) != policy_identity["sha256"]:
                raise ValueError("finite policy bytes changed")
            policy = load_policy(io.StringIO(policy_bytes.decode()))
            selected = Path(contract["authority"]["selected_path"])
            if (
                not selected.is_absolute()
                or ".." in selected.parts
                or selected.name != "ncit.db"
                or selected.parent.resolve() != Path(report["raw_input_directory"]).resolve()
            ):
                raise ValueError("finite native selected locator changed")
            authority = _select_native(selected.parent, guard)
            if authority != contract["authority"]:
                raise ValueError("finite native binding changed")
            if snapshots.get(NATIVE_ROLE) != {"path": authority["resolved_path"], "sha256": authority["sha256"]}:
                raise ValueError("finite native consumed snapshot changed")
            # The recorded release is provenance, but it must be the bound database's (#1531).
            database = Path(authority["resolved_path"]).as_uri() + "?mode=ro&immutable=1"
            with sqlite3.connect(database, uri=True) as connection:
                if semsql_release(connection, "ncit") != contract["native_release"]:
                    raise ValueError("finite native release provenance changed")
            model_path = Path(report["raw_input_directory"]) / policy["model_file"]
            model = {"path": str(model_path.resolve()), "sha256": policy["model_sha256"]}
            if contract["model"] != model or snapshots.get(MODEL_ROLE) != model:
                raise ValueError("finite model binding changed")
            model_bytes = guard.capture(model_path, retain=True)
            if digest(model_bytes) != model["sha256"]:
                raise ValueError("finite model bytes changed")
            validate_model(yaml.safe_load(model_bytes), policy)
            if contract["native_evidence_sha256"] != digest(canonical(policy["native_statements"]).encode()):
                raise ValueError("finite native statement inventory changed")
        except (ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            raise SourceFinalizationRequired("Invalid finite NCIT category authority contract") from exc
    guard.verify(metadata_only=True)
    return guard


class RecordedNcitCategoryGuard:
    """Keep the original verified native/sidecar guards on a newly constructed repeat producer."""

    def __init__(self, report, report_path):
        """Restore prior evidence only after actual public admission, never substitute current bytes."""
        self._admission = verify_recorded_inputs(report, report_path)
        encoded = self._admission.capture(report_path, retain=True)
        if canonical(json.loads(encoded)) != canonical(report):
            raise ValueError("Finite NCIT completion record changed during repeated admission")
        self._bindings = canonical(
            {role: report["consumed_inputs"][role] for role in (NATIVE_ROLE, POLICY_ROLE, MODEL_ROLE)}
        )
        self._authority_json = canonical(report[CONTRACT_KEY]["authority"])

    def verify(self, snapshots=None, *, output_dir=None):
        """Completion-marker callbacks retain SQLite absence and original locator checks."""
        if (
            snapshots is not None
            and canonical({role: snapshots.get(role) for role in (NATIVE_ROLE, POLICY_ROLE, MODEL_ROLE)})
            != self._bindings
        ):
            raise ValueError("Repeated finite NCIT consumed-input bindings changed")
        _verify_sqlite_state(self._authority_json, self._admission)
        self._admission.verify(metadata_only=True)


def restore_recorded_guard(transform, report, report_path):
    """Repeat finalization must not discard source-selection safeguards before later completion."""
    if report.get(CONTRACT_KEY, {}).get("authority") is not None:
        if getattr(transform, "_ncit_eight_category_guard", None) is None:
            transform._ncit_eight_category_guard = RecordedNcitCategoryGuard(report, report_path)
