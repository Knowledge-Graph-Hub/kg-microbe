"""Preserve native recipe referents and six reviewed material observations (#1317–1319)."""

import csv
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    CATEGORY_COLUMN,
    HAS_PART,
    ID_COLUMN,
    INGREDIENT_CATEGORY,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    MEDIADIVE,
    MEDIADIVE_SOLUTION_PREFIX,
    MEDIUM_TO_INGREDIENT_EDGE,
    NAME_COLUMN,
    NAMED_THING_CATEGORY,
    OBJECT_COLUMN,
    OBSERVATION,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBLICATIONS_COLUMN,
    RELATION_COLUMN,
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
    SUBJECT_COLUMN,
    TRANSLATION_TABLE_FOR_LABELS,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_dict_writer

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "mappings/mediadive_recipe_identity_policy.json"
EVIDENCE = ROOT / "mappings/mediadive_recipe_identity_evidence.json"
POLICY_ROLE = "mediadive_recipe_identity_policy"
EVIDENCE_ROLE = "mediadive_recipe_identity_evidence"
POLICY_SHA256 = "9f590b55a9183b5dfec6cc9082c6193db79b2fd7b6bd8e938a5c4a35126e059f"
EVIDENCE_SHA256 = "5ec6fc063a5c0c10a77392b20e9f3fe70272479d1ba0a3396dd49a472645ab92"
AUDITS = {
    "nested": "mediadive_nested_solution_identity.tsv",
    "missing": "mediadive_missing_solution_references.tsv",
    "oatmeal": "mediadive_oatmeal_identity.tsv",
    "substrate": "mediadive_substrate_identity.tsv",
}
HEADER = (
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
    "source_record_sha256",
    "retained_identifier",
    "disposition",
    "reason",
    "child_status",
    "historical_target",
    "source_input_path",
    "source_input_sha256",
    "policy_input_sha256",
    "evidence_input_sha256",
)
RAW_ROLES = ("mediadive_media_list", "mediadive_media_detailed", "mediadive_solutions", "mediadive_compounds")


def encoded(value):
    """Preserve exact JSON values, positions and qualifiers in source evidence."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    """Hash the canonical evidence payload, not an outer file receipt."""
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def require(condition, message):
    """Fail before publication when source identity or evidence cannot be established."""
    if not condition:
        raise SourceFinalizationRequired("MediaDive recipe identity: " + message)


def native_id(value):
    """Require an unambiguous positive source ID; booleans/floats are not identifiers."""
    require(type(value) in (str, int) and re.fullmatch(r"[1-9][0-9]*", str(value)), "malformed native ID")
    return str(value)


def nested_identifier(raw):
    """Explicit child identity precedes every lexical chemical mapping route."""
    require(raw.get("compound_id") is None, "ambiguous compound and nested solution IDs")
    return MEDIADIVE_SOLUTION_PREFIX + native_id(raw.get("solution_id"))


def _unique(pairs):
    """Reject duplicate JSON keys rather than silently discarding evidence."""
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _policy(policy_bytes, evidence_bytes):
    """Pin complete reviewed decisions and original native/owner witnesses."""
    require(hashlib.sha256(policy_bytes).hexdigest() == POLICY_SHA256, "reviewed policy bytes changed")
    require(hashlib.sha256(evidence_bytes).hexdigest() == EVIDENCE_SHA256, "reviewed evidence bytes changed")
    policy = json.loads(policy_bytes, object_pairs_hook=_unique)
    evidence = json.loads(evidence_bytes, object_pairs_hook=_unique)
    require(policy["evidence_sha256"] == EVIDENCE_SHA256, "policy/evidence binding disagrees")
    return policy, evidence


def _index(policy, media_list, media, solutions, compounds):
    """Derive selected native occurrences; never infer missing composition or identity."""
    require(isinstance(media_list, dict) and isinstance(media_list.get("data"), list), "invalid selected media list")
    parents = set()
    for entry in media_list["data"]:
        key = native_id(entry.get("id")) if str(entry.get("id", "")).isdigit() else str(entry.get("id", ""))
        require(key and key in media and isinstance(media[key], dict), "selected medium missing")
        for item in media[key].get("solutions", []):
            parent = native_id(item.get("id"))
            require(parent in solutions and isinstance(solutions[parent], dict), "selected parent solution missing")
            # Some historical exports have summary-only solution references;
            # if expanded content is supplied it must agree with the bulk record.
            if "recipe" in item or "steps" in item:
                require(item == solutions[parent], "contradictory expanded solution records")
            parents.add(parent)
    occurrences, missing = {}, {}
    dispositions = policy["compound_dispositions"]
    for parent in sorted(parents):
        solution = solutions[parent]
        if "id" in solution:
            require(native_id(solution["id"]) == parent, "parent key and native ID disagree")
        recipe = solution.get("recipe", [])
        if not isinstance(recipe, list):
            continue
        for position, raw in enumerate(recipe, 1):
            require(isinstance(raw, dict), "recipe item is not an object")
            compound, child = raw.get("compound_id"), raw.get("solution_id")
            require(compound is None or child is None, "ambiguous compound and nested solution IDs")
            if compound is None and child is None:
                continue
            assertion = f"{MEDIADIVE_SOLUTION_PREFIX}{parent}#recipe/{position}"
            record = {
                "raw": raw,
                "parent": parent,
                "target": None,
                "cohort": None,
                "child_status": "",
                "reason": "",
                "historical_target": "",
            }
            if child is not None:
                child = native_id(child)
                require(
                    isinstance(raw.get("solution"), str) and raw["solution"].strip(),
                    "nested reference lacks native name",
                )
                record.update(
                    target=nested_identifier(raw),
                    cohort="nested",
                    reason="explicit_native_solution_identity",
                    child_status="missing" if child not in solutions else "present",
                )
                if child in solutions:
                    require(isinstance(solutions[child], dict), "child solution record is malformed")
                    if "id" in solutions[child]:
                        require(native_id(solutions[child]["id"]) == child, "child key and native ID disagree")
                else:
                    require(
                        missing.setdefault(record["target"], raw["solution"]) == raw["solution"],
                        "missing child has contradictory native names",
                    )
            else:
                compound = native_id(compound)
                if compound in dispositions:
                    decision = dispositions[compound]
                    reviewed = {item["source_assertion_id"]: item for item in decision["occurrences"]}
                    require(assertion in reviewed, "unreviewed occurrence for selected compound ID")
                    witness = reviewed[assertion]
                    require(
                        raw == witness["native_occurrence"] and digest(raw) == witness["native_occurrence_sha256"],
                        "reviewed compound occurrence changed",
                    )
                    require(
                        digest(solution) == witness["native_parent_record_sha256"],
                        "reviewed preparation context changed",
                    )
                    require(
                        compounds.get(compound) == decision["native_compound_record"]
                        and digest(compounds.get(compound)) == decision["native_compound_record_sha256"],
                        "reviewed compound catalog changed",
                    )
                    record.update(
                        target=decision["retained_identifier"],
                        cohort="oatmeal" if compound == "471" else "substrate",
                        reason=decision["reason"],
                        historical_target=decision["historically_selected_target"],
                    )
            occurrences[assertion] = record
    return {"parents": sorted(parents), "occurrences": occurrences, "missing": missing}


def _audit_rows(index, snapshots):
    """Derive mandatory sidecars from native evidence, independently of observed graph rows."""
    rows = {name: [] for name in AUDITS}
    source = snapshots["mediadive_solutions"]
    for assertion, item in sorted(index["occurrences"].items()):
        cohort = item["cohort"]
        if cohort is None:
            continue
        row = dict(
            zip(
                HEADER,
                (
                    assertion,
                    encoded(item["raw"]),
                    digest(item["raw"]),
                    item["target"],
                    "native_reference_retained" if cohort == "nested" else "source_owned_material_retained",
                    item["reason"],
                    item["child_status"],
                    item["historical_target"],
                    source["path"],
                    source["sha256"],
                    POLICY_SHA256,
                    EVIDENCE_SHA256,
                ),
                strict=True,
            )
        )
        rows[cohort].append(row)
        if item["child_status"] == "missing":
            rows["missing"].append(
                {
                    **row,
                    "disposition": "unresolved_native_reference",
                    "reason": "referenced_child_absent_from_selected_export",
                }
            )
    return rows


def _read_rows(path, *, canonical):
    """Read one explicit producer member in its pre-finalization or canonical dialect."""
    require(path.is_file() and not path.is_symlink(), f"missing or symlinked member {path.name}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE if canonical else csv.QUOTE_MINIMAL)
        require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), "invalid graph header")
        for row in reader:
            require(None not in row and None not in row.values(), "malformed graph row")
            yield row


def _quantity(actual, expected):
    """Allow producer numeric TSV formatting without changing the exact JSON witness."""
    if expected is None:
        return actual == ""
    if type(expected) in (int, float):
        try:
            return Decimal(actual) == Decimal(str(expected))
        except InvalidOperation:
            return False
    return actual == str(expected)


def _verify_graph(index, directory, members, *, canonical):
    """Conserve actual recipe assertions and protected endpoints, not merely audit counts."""
    seen, missing_nodes, material_nodes = Counter(), {}, {}
    expected = index["occurrences"]
    materials = {}
    translation = str.maketrans(TRANSLATION_TABLE_FOR_LABELS)
    for item in expected.values():
        if item["cohort"] in ("oatmeal", "substrate"):
            label = item["raw"]["compound"].translate(translation).replace('""', "").strip()
            materials.setdefault(item["target"], set()).add(label)
    edge_metadata = {
        RELATION_COLUMN: HAS_PART,
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: f"infores:{MEDIADIVE}",
        KNOWLEDGE_LEVEL_COLUMN: OBSERVATION,
        AGENT_TYPE_COLUMN: MANUAL_AGENT,
        PUBLICATIONS_COLUMN: "",
    }
    for row in _read_rows(directory / members["edges"], canonical=canonical):
        assertion = row.get(SOURCE_ASSERTION_ID_COLUMN, "")
        if assertion:
            require(assertion in expected, "graph contains an unknown native recipe assertion")
            item = expected[assertion]
            require(
                row[SUBJECT_COLUMN] == MEDIADIVE_SOLUTION_PREFIX + item["parent"]
                and row[PREDICATE_COLUMN] == MEDIUM_TO_INGREDIENT_EDGE,
                "recipe assertion subject/predicate changed",
            )
            require(row.get(SOURCE_RECORD_COLUMN) == encoded(item["raw"]), "complete native source record changed")
            require(
                all(row.get(column) == value for column, value in edge_metadata.items()),
                "native recipe relation/provenance/knowledge metadata changed",
            )
            if item["target"] is not None:
                require(row[OBJECT_COLUMN] == item["target"], "source identity substitution escaped")
            for output, native in (("value", "amount"), ("unit", "unit"), ("g_l", "g_l"), ("mmol_l", "mmol_l")):
                require(_quantity(row.get(output, ""), item["raw"].get(native)), "native recipe quantity changed")
            seen[assertion] += 1
        if row.get(SUBJECT_COLUMN) in index["missing"] or row.get(SUBJECT_COLUMN) in materials:
            require(False, "source-owned unresolved reference gained unsupported outgoing claims")
    require(seen == Counter({key: 1 for key in expected}), "native recipe occurrences missing or duplicated")
    for row in _read_rows(directory / members["nodes"], canonical=canonical):
        identifier = row.get(ID_COLUMN)
        if identifier in index["missing"] or identifier in materials:
            require(row.get(PROVIDED_BY_COLUMN) == f"infores:{MEDIADIVE}", "native declaration provenance changed")
        if identifier in index["missing"]:
            require(identifier not in missing_nodes, "duplicate unresolved child declaration")
            require(
                row.get(CATEGORY_COLUMN) == NAMED_THING_CATEGORY
                and row.get(NAME_COLUMN) == index["missing"][identifier],
                "unresolved child declaration changed",
            )
            require(
                not any(row.get(key) for key in ("xref", "same_as", "synonym", "description")),
                "unresolved child acquired unsupported enrichment",
            )
            missing_nodes[identifier] = row
        if identifier in materials:
            require(identifier not in material_nodes, "duplicate source-owned material declaration")
            require(
                row.get(CATEGORY_COLUMN) == INGREDIENT_CATEGORY and row.get(NAME_COLUMN) in materials[identifier],
                "source-owned material declaration changed",
            )
            require(
                not any(row.get(key) for key in ("xref", "same_as", "synonym", "description")),
                "source-owned material acquired unsupported enrichment",
            )
            material_nodes[identifier] = row
    require(set(missing_nodes) == set(index["missing"]), "unresolved child declaration missing")
    require(set(material_nodes) == set(materials), "source-owned material declaration missing")


def _check_audits(directory, rows):
    """Check full native-derived evidence, including partial loss and same-count rewrites."""
    for cohort, name in AUDITS.items():
        actual = list(_read_rows(directory / name, canonical=True))
        require(all(tuple(row) == HEADER for row in actual), "audit header changed")
        with (directory / name).open(encoding="utf-8") as stream:
            require(stream.readline().rstrip("\r\n").split("\t") == list(HEADER), "audit header changed")
        require(actual == rows[cohort], f"complete {cohort} audit evidence changed")


class RecipeIdentityGuard:
    """One immutable source-derived conservation index for a producer epoch."""

    def __init__(self, transform, media_list):
        """Bind reviewed files through actual input reads before choosing any endpoint."""
        self.transform = transform
        self.admission = SourceAdmission()
        payloads = []
        for role, path in ((POLICY_ROLE, POLICY), (EVIDENCE_ROLE, EVIDENCE)):
            self.admission.capture(path)
            with transform.consume_input(role, path) as stream:
                payloads.append(stream.buffer.read())
        self.policy, self.evidence = _policy(*payloads)
        self._policy_digest = digest([self.policy, self.evidence])
        self.snapshots = {
            role: dict(transform.consumed_input_snapshots[role]) for role in (*RAW_ROLES, POLICY_ROLE, EVIDENCE_ROLE)
        }
        self._snapshot_digest = digest(self.snapshots)
        self.index = _index(
            self.policy, media_list, transform.media_detailed, transform.solutions_data, transform.compounds_data
        )
        self._index_digest = digest(self.index)
        self.rows = _audit_rows(self.index, self.snapshots)
        self._rows_digest = digest(self.rows)
        self.members = {"nodes": Path(transform.output_node_file).name, "edges": Path(transform.output_edge_file).name}
        self.observed = {}
        self._sealed = False
        self._contract = {
            "version": 1,
            "members": self.members,
            "inputs": self.snapshots,
            "selected_parents": self.index["parents"],
            "native_occurrences": len(self.index["occurrences"]),
            "native_index_sha256": self._index_digest,
            "audits": {
                AUDITS[key]: {"rows": len(value), "content_sha256": digest(value)} for key, value in self.rows.items()
            },
        }
        self._contract_digest = digest(self._contract)
        self.admission.verify()

    @property
    def sealed(self):
        """Expose completion without permitting caller reset of evidence verification."""
        return self._sealed

    def contract(self):
        """Return a detached record; only a sealed producer may claim completion."""
        self._verify_cache()
        return json.loads(encoded({**self._contract, "sealed": self.sealed}))

    def _verify_cache(self):
        """Never accept re-stamped mutable parsed evidence or replaced original role bindings."""
        require(digest([self.policy, self.evidence]) == self._policy_digest, "cached reviewed witness changed")
        require(digest(self.snapshots) == self._snapshot_digest, "cached original role bindings changed")
        require(
            digest(self.index) == self._index_digest and digest(self.rows) == self._rows_digest,
            "cached native conservation index changed",
        )
        require(digest(self._contract) == self._contract_digest, "cached contract changed")
        require(
            all(self.transform.consumed_input_snapshots.get(role) == value for role, value in self.snapshots.items()),
            "original consumed role binding changed",
        )

    def compound_target(self, identifier, name, raw, assertion):
        """Protect finite native compound records before unified, legacy or embedded lookup."""
        if str(identifier) not in ("471", "672"):
            return None
        item = self.index["occurrences"].get(assertion)
        require(
            item is not None and item["cohort"] in ("oatmeal", "substrate"),
            "reviewed compound requires its admitted native recipe coordinate",
        )
        require(
            raw == item["raw"] and name == raw.get("compound") and str(raw.get("compound_id")) == str(identifier),
            "reviewed compound call disagrees with source occurrence",
        )
        return item["target"]

    def observe(self, occurrence, raw):
        """Record actual producer decisions without permitting a native coordinate collision."""
        assertion = occurrence[SOURCE_ASSERTION_ID_COLUMN]
        require(assertion in self.index["occurrences"], "observed occurrence outside selected native input")
        item = self.index["occurrences"][assertion]
        require(
            raw == item["raw"] and occurrence[SOURCE_RECORD_COLUMN] == encoded(raw), "observed source evidence changed"
        )
        require(
            item["target"] is None or occurrence[ID_COLUMN] == item["target"], "observed protected endpoint changed"
        )
        payload = encoded(occurrence)
        require(self.observed.setdefault(assertion, payload) == payload, "conflicting repeated native assertion")

    def verify(self, *, output_dir=None, byte_verified=False):
        """Check the original read epoch and, after sealing, the complete published evidence."""
        self._verify_cache()
        self.admission.verify(metadata_only=byte_verified)
        if self.sealed:
            directory = Path(output_dir) if output_dir is not None else self.transform.output_dir
            canonical = output_dir is not None or (directory / "source_finalization.json").is_file()
            _verify_graph(self.index, directory, self.members, canonical=canonical)
            _check_audits(directory, self.rows)

    def write(self):
        """Seal complete writer output and mandatory audits before generic finalization."""
        self.verify()
        require(
            set(self.observed) == set(self.index["occurrences"]),
            "producer did not observe every native recipe occurrence",
        )
        _verify_graph(self.index, self.transform.output_dir, self.members, canonical=False)
        for cohort, name in AUDITS.items():
            path = self.transform.output_dir / name
            require(not path.is_symlink(), "audit output is a symlink")
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = tsv_dict_writer(stream, fieldnames=HEADER, quoting=csv.QUOTE_NONE, quotechar=None)
                writer.writeheader()
                writer.writerows(self.rows[cohort])
            self.transform.record_producer_audit(name)
        self._sealed = True
        self.verify()

    def restore(self, recorded):
        """Reuse independently verified output without claiming a fresh writer run."""
        require(
            recorded == {**self._contract, "sealed": True}, "checkpoint recipe evidence differs from actual rereads"
        )
        _verify_graph(self.index, self.transform.output_dir, self.members, canonical=True)
        _check_audits(self.transform.output_dir, self.rows)
        self._sealed = True
        self.verify()


def restore_recipe_checkpoint(transform, report_path):
    """Restore a fresh instance only through public validation and actual immutable rereads."""
    from kg_microbe.transform_utils.mediadive.bulk_inputs import (
        MEDIA_LIST_INPUT,
        load_bulk_payload,
        verify_bulk_payloads,
    )
    from kg_microbe.transform_utils.mediadive.material_scope_audit import MaterialScopeAudit
    from kg_microbe.utils.source_finalization import verify_finalized_source_files

    admission = SourceAdmission()
    report = json.loads(admission.capture(report_path, retain=True), object_pairs_hook=_unique)
    require(report.get("source") == transform.source_name, "checkpoint producer differs")
    require(
        report.get("raw_input_locator") == str(Path(transform.input_base_dir).absolute()),
        "checkpoint selected raw locator differs",
    )
    require(
        report.get("raw_input_directory") == str(Path(transform.input_base_dir).resolve()),
        "checkpoint selected raw directory differs",
    )
    require(
        set(report.get("members", {}))
        == {Path(transform.output_node_file).name, Path(transform.output_edge_file).name},
        "checkpoint graph scope differs",
    )
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    snapshots = report["consumed_inputs"]
    require(
        all(snapshots.get(role) == value for role, value in transform.consumed_input_snapshots.items()),
        "constructor reads differ from checkpoint",
    )
    inputs = report["producer_native_inputs"]
    media_list = load_bulk_payload(transform, MEDIA_LIST_INPUT, inputs["inputs"][MEDIA_LIST_INPUT]["locator"])
    verify_bulk_payloads(transform)
    transform._preflight_bulk_records(media_list)
    guard = RecipeIdentityGuard(transform, media_list)
    material = MaterialScopeAudit(transform, media_list)
    # Category/source finalization may have consumed further authority witnesses.
    # Re-read them exactly; do not install a receipt copied from the checkpoint.
    for role, snapshot in snapshots.items():
        if role not in transform.consumed_input_snapshots:
            with transform.consume_input(role, snapshot["path"]) as stream:
                for _ in iter(lambda: stream.buffer.read(1024 * 1024), b""):
                    pass
    require(transform.consumed_input_snapshots == snapshots, "actual checkpoint rereads differ")
    guard.restore(inputs["recipe_identity"])
    transform._recipe_identity_guard = guard
    transform._recipe_identity_prepared = True
    transform._material_scope_audit = material
    require(transform.producer_native_inputs == inputs, "native checkpoint contract differs from rereads")
    admission.verify()


def verify_recorded_recipe_identity(report, report_path, *, admission):
    """Independently reconstruct source decisions from retained, actually admitted native bytes."""
    contract = report.get("producer_native_inputs", {}).get("recipe_identity")
    require(
        isinstance(contract, dict) and contract.get("sealed") is True,
        "missing completed recipe identity contract; rerun producer",
    )
    snapshots = report.get("consumed_inputs", {})
    payloads = []
    for role, path, expected in ((POLICY_ROLE, POLICY, POLICY_SHA256), (EVIDENCE_ROLE, EVIDENCE, EVIDENCE_SHA256)):
        require(
            snapshots.get(role) == {"path": str(path.resolve()), "sha256": expected},
            "recorded reviewed input origin changed",
        )
        payloads.append(admission.capture(path, retain=True))
    policy, _ = _policy(*payloads)
    inputs = {}
    for role in RAW_ROLES:
        snapshot = snapshots.get(role)
        require(isinstance(snapshot, dict), "recorded native role missing")
        path = Path(snapshot["path"])
        payload = admission.capture(path, retain=True)
        require(hashlib.sha256(payload).hexdigest() == snapshot["sha256"], "recorded native bytes changed")
        inputs[role] = json.loads(payload, object_pairs_hook=_unique)
    index = _index(policy, *(inputs[role] for role in RAW_ROLES))
    rows = _audit_rows(index, snapshots)
    members = contract.get("members")
    require(isinstance(members, dict) and set(members) == {"nodes", "edges"}, "invalid recipe graph-member scope")
    require(
        set(members.values()) == set(report.get("members", {})),
        "recipe graph-member scope differs from admitted members",
    )
    require(
        all(Path(name).name == name and "\\" not in name for name in members.values()), "nonlocal recipe graph member"
    )
    expected = {
        "version": 1,
        "sealed": True,
        "members": members,
        "inputs": {role: snapshots[role] for role in (*RAW_ROLES, POLICY_ROLE, EVIDENCE_ROLE)},
        "selected_parents": index["parents"],
        "native_occurrences": len(index["occurrences"]),
        "native_index_sha256": digest(index),
        "audits": {AUDITS[key]: {"rows": len(value), "content_sha256": digest(value)} for key, value in rows.items()},
    }
    require(contract == expected, "recorded native conservation contract changed")
    directory = Path(report_path).parent
    for name in (*members.values(), *AUDITS.values()):
        admission.capture(directory / name)
    _verify_graph(index, directory, members, canonical=True)
    _check_audits(directory, rows)
    admission.verify(metadata_only=True)
    return admission
