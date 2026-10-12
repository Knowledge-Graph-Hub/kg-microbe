"""
Finite native selected-taxonomy alias evidence for eleven GOLD records (#1327).

No graph is edited here. Existing taxdump behavior is retained outside the three
reviewed original IDs. New or changed eligible GOLD records require re-review;
selected aliases are never inferred from labels or a full-ontology-only target.
"""

import csv
import hashlib
import io
import json
import tarfile
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType

import ijson

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import IN_TAXON_PREDICATE, NCBI_CATEGORY
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "mappings/gold_selected_taxon_aliases.json"
POLICY_SHA256 = "4ff13e3f891c6287b041bb500d35d009eb24c2fa87d369e2408ca7a814c8ec13"
POLICY_ROLE = "gold_selected_taxon_alias_policy"
JSON_ROLE = "gold_selected_taxon_alias_native_json"
NODES_ROLE = "gold_native_nodes"
EDGES_ROLE = "gold_native_edges"
NCBI_ROLE = "gold_taxon_disposition_ncbi"
TAXDUMP_ROLE = "gold_taxon_disposition_taxdump"
REQUIRED_INPUTS = (POLICY_ROLE,)
AUDIT_FILE = "gold_selected_taxon_aliases.tsv"
REQUIRED_AUDIT = (AUDIT_FILE,)
CONTRACT_KEY = "selected_taxon_aliases"
FINITE_IDS = frozenset({"NCBITaxon:53360", "NCBITaxon:659496", "NCBITaxon:1194211"})
ALT = "http://www.geneontology.org/formats/oboInOwl#hasAlternativeId"
AUDIT_HEADER = (
    "original_id",
    "selected_target",
    "resolution_steps_json",
    "native_taxon_declaration_json",
    "native_records_json",
    "native_incident_rows_json",
    "selected_ontology_node_json",
    "selected_alias_assertions_json",
    "selected_declaration_json",
    "consumed_inputs_json",
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _fail(message):
    raise SourceFinalizationRequired("GOLD selected aliases: " + message)


def _unique_object(pairs):
    """Reject contradictory repeated policy keys before constructing a mapping (#1334)."""
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _unique_json_events(stream):
    """Validate every object while streaming; decoded keys include escaped spellings."""
    objects = []
    for prefix, event, value in ijson.parse(stream):
        if event == "start_map":
            objects.append(set())
        elif event == "map_key":
            if value in objects[-1]:
                _fail(f"duplicate JSON object key: {value!r}")
            objects[-1].add(value)
        elif event == "end_map":
            objects.pop()
        yield prefix, event, value


def _rows(path, required):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", strict=True)
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or not set(required) <= set(header):
            _fail(f"invalid header: {path}")
        for ordinal, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                _fail(f"malformed native row: {path}:{reader.line_num}")
            yield {"row": row, "record": ordinal, "ending_physical_line": reader.line_num}


def _policy(path):
    value = json.loads(Path(path).read_text(), object_pairs_hook=_unique_object)
    if _digest(value) != POLICY_SHA256 or {item["original_id"] for item in value["rules"]} != FINITE_IDS:
        _fail("finite policy changed; reviewed source refresh required")
    return value


def _cohort(nodes_path, edges_path, policy):
    """Read actual native membership, including known records whose taxid changed."""
    rules = {item["original_id"]: item for item in policy["rules"]}
    owners = {identifier: old for old, rule in rules.items() for identifier in rule["records"]}
    declarations, incidents, parents, active = {}, defaultdict(list), defaultdict(list), set()
    for item in _rows(nodes_path, ("id", "category", "name")):
        identifier = item["row"]["id"]
        if identifier in FINITE_IDS or identifier in owners:
            if identifier in declarations:
                _fail("duplicate eligible native declaration")
            declarations[identifier] = item
            active.add(owners.get(identifier, identifier))
    for item in _rows(edges_path, ("subject", "predicate", "object")):
        row = item["row"]
        for endpoint in set((row["subject"], row["object"])) & owners.keys():
            active.add(owners[endpoint])
            incidents[endpoint].append(item)
        if row["predicate"] == IN_TAXON_PREDICATE and row["object"] in FINITE_IDS:
            old = row["object"]
            active.add(old)
            if row["subject"] not in rules[old]["records"]:
                _fail("new eligible native record; finite cohort review required")
            parents[row["subject"]].append(item)
    result = {}
    for old in sorted(active):
        rule = rules[old]
        taxon = declarations.get(old)
        if taxon is None or _digest(taxon["row"]) != rule["native_taxon_sha256"]:
            _fail("missing or changed eligible native taxon declaration")
        selected_records = {}
        for identifier, expected in rule["records"].items():
            node = declarations.get(identifier)
            assertions = parents[identifier]
            incident = incidents[identifier]
            if (
                node is None
                or _digest(node["row"]) != expected["node_sha256"]
                or len(assertions) != 1
                or _digest(assertions[0]["row"]) != expected["taxon_assertion_sha256"]
                or _digest(sorted((item["row"] for item in incident), key=lambda row: json.dumps(row, sort_keys=True)))
                != expected["incident_rows_sha256"]
            ):
                _fail("changed or incomplete eligible native record/incident evidence")
            selected_records[identifier] = {"declaration": node, "taxon_assertion": assertions[0]}
        result[old] = {
            "native_taxon": taxon,
            "native_records": selected_records,
            "native_incidents": sorted(
                (item for identifier in rule["records"] for item in incidents[identifier]),
                key=lambda item: item["record"],
            ),
        }
    return result


def _merges(path):
    """Preserve one-step taxdump behavior, while binding exact selected member bytes."""
    merges, witnesses = {}, {}
    if path is None:
        return merges, witnesses
    with tarfile.open(path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name == "merged.dmp"]
        if len(members) != 1 or not members[0].isfile():
            _fail("taxdump must contain exactly one regular merged.dmp member")
        with io.TextIOWrapper(archive.extractfile(members[0]), encoding="utf-8") as stream:
            for number, literal in enumerate(stream, 1):
                fields = [part.strip() for part in literal.split("|")]
                if len(fields) != 3 or fields[2] or not fields[0].isdigit() or not fields[1].isdigit():
                    _fail("malformed native merged.dmp row")
                old, target = "NCBITaxon:" + fields[0], "NCBITaxon:" + fields[1]
                if old in merges:
                    _fail("duplicate native merged.dmp source")
                merges[old] = target
                witnesses[old] = {"member": "merged.dmp", "line": number, "literal": literal, "target": target}
    return merges, witnesses


def _authority(native_path, ncbi_path, rules, cohort, merges, remap_witnesses):
    active_rules = {item["original_id"]: item for item in rules if item["original_id"] in cohort}
    targets = {rule["target"] for rule in active_rules.values()}
    retired = set(cohort) | {rule["taxdump_target"] for rule in active_rules.values()}
    declarations, aliases = {}, defaultdict(list)
    with Path(native_path).open("rb") as stream:
        for position, node in enumerate(ijson.items(_unique_json_events(stream), "graphs.item.nodes.item")):
            identifier = compact_identifier(node["id"])
            if identifier in retired | targets:
                if identifier in declarations:
                    _fail("duplicate selected native declaration")
                declarations[identifier] = {"position": position, "row": node}
            for assertion in node.get("meta", {}).get("basicPropertyValues", []):
                if assertion.get("pred") == ALT and compact_identifier(assertion.get("val", "")) in retired | targets:
                    aliases[compact_identifier(assertion["val"])].append(
                        {"position": position, "row": node, "assertion": assertion}
                    )
    selected = {}
    for item in _rows(ncbi_path, ("id", "name", "category")):
        identifier = compact_identifier(item["row"]["id"])
        if identifier in retired | targets:
            if identifier in selected:
                _fail("duplicate selected projected declaration")
            selected[identifier] = item
    result = {}
    for old, rule in active_rules.items():
        target, middle = rule["target"], rule["taxdump_target"]
        if old in declarations or middle in declarations or old in selected or middle in selected:
            _fail("old selected identifier is still declared")
        if merges.get(old, old) != middle:
            _fail("taxdump and reviewed authority chain disagree")
        if target in retired or target in merges or aliases[target]:
            _fail("selected target is cyclic, nonterminal or contradicted")
        node = declarations.get(target)
        projected = selected.get(target)
        if node is None or node["row"].get("type") != "CLASS":
            _fail("selected target lacks an asserted native CLASS declaration")
        if node["row"].get("meta", {}).get("deprecated") not in (None, False):
            _fail("selected native target is deprecated")
        if (
            projected is None
            or projected["row"].get("category") != NCBI_CATEGORY
            or projected["row"].get("deprecated", "") not in ("", "false", "False")
            or projected["row"].get("name") != node["row"].get("lbl")
        ):
            _fail("selected target missing or inconsistent in sibling declarations")
        steps, asserted_aliases = [], []
        if old != middle:
            if middle in merges:
                _fail("unreviewed intermediate taxdump chain or cycle")
            steps.append({"authority": "selected_taxdump", "from": old, "to": middle, "witness": remap_witnesses[old]})
        for source in sorted({old, middle}):
            assertions = aliases[source]
            if len(assertions) != 1 or compact_identifier(assertions[0]["row"]["id"]) != target:
                _fail("missing, duplicate, ambiguous or divergent selected alias")
            if assertions[0]["row"].get("type") != "CLASS":
                _fail("selected alias assertion is not attached to a CLASS")
            asserted_aliases.extend(assertions)
            steps.append({"authority": "selected_ontology", "from": source, "to": target, "witness": assertions[0]})
        if _digest(node["row"]) != rule["selected_node_sha256"]:
            _fail("complete selected native target evidence changed; review required")
        result[old] = {
            "original_id": old,
            "selected_target": target,
            "resolution_steps_json": _json(steps),
            "native_taxon_declaration_json": _json(cohort[old]["native_taxon"]),
            "native_records_json": _json(cohort[old]["native_records"]),
            "native_incident_rows_json": _json(cohort[old]["native_incidents"]),
            "selected_ontology_node_json": _json(node),
            "selected_alias_assertions_json": _json(asserted_aliases),
            "selected_declaration_json": _json(projected),
        }
    return result


def _locators(raw_dir, output_base_dir):
    return {
        POLICY_ROLE: Path(POLICY_PATH).absolute(),
        NODES_ROLE: Path(raw_dir).absolute() / "gold/GOLD_nodes.tsv",
        EDGES_ROLE: Path(raw_dir).absolute() / "gold/GOLD_edges.tsv",
        NCBI_ROLE: Path(output_base_dir).absolute() / "ontologies/ncbitaxon_nodes.tsv",
        TAXDUMP_ROLE: Path(raw_dir).absolute() / "taxdump.tar.gz",
        JSON_ROLE: Path(raw_dir).absolute() / "ncbitaxon_removed_subset.json",
    }


def _bind(role, snapshot_path, locator, snapshots, admission, parse_admission):
    """Rejoin supplied private snapshots to original locators; never replace original receipts."""
    if not isinstance(snapshots, dict):
        _fail("missing consumed-input mapping")
    expected = snapshots.get(role)
    if not isinstance(expected, dict) or expected.get("path") != str(locator.resolve()):
        _fail(f"missing or rebound original consumed role: {role}")
    identity = admission.capture(locator)
    if identity["sha256"] != expected.get("sha256"):
        _fail(f"consumed original bytes changed: {role}")
    actual = parse_admission.capture(snapshot_path)
    if actual != identity:
        _fail(f"supplied snapshot differs from actual consumed bytes: {role}")
    return dict(expected)


class SelectedTaxonAliases:
    """Immutable finite resolution cache, mandatory audit and retained native input guards."""

    def __init__(self, policy, cohort, merges, evidence, bindings, optional, admission, snapshots_getter):
        """Only factories create this from validated actual-read native evidence."""
        self._baseline = MappingProxyType(dict(merges))
        self._targets = MappingProxyType({key: value["selected_target"] for key, value in evidence.items()})
        rows = [{**evidence[key], "consumed_inputs_json": _json(bindings)} for key in sorted(evidence)]
        self._evidence = MappingProxyType({row["original_id"]: _json(row) for row in rows})
        audit = io.StringIO(newline="")
        writer = tsv_writer(audit, quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(AUDIT_HEADER)
        for row in rows:
            writer.writerow([row[key] for key in AUDIT_HEADER])
        self._audit_bytes = audit.getvalue().encode()
        self._contract_json = _json(
            {
                "version": 1,
                "policy_sha256": _digest(policy),
                "eligible_original_ids": sorted(cohort),
                "eligible_record_count": sum(len(item["native_records"]) for item in cohort.values()),
                "native_incident_count": sum(len(item["native_incidents"]) for item in cohort.values()),
                "evidence_sha256": _digest(rows),
                "consumed_inputs": bindings,
                "optional_inputs": optional,
                "audit": {
                    "name": AUDIT_FILE,
                    "bytes": len(self._audit_bytes),
                    "sha256": hashlib.sha256(self._audit_bytes).hexdigest(),
                },
            }
        )
        baseline, targets, saved_evidence = self._baseline, self._targets, self._evidence
        audit_bytes, contract = self._audit_bytes, self._contract_json
        output = [None]
        failed = []
        absent_roles = frozenset(
            {POLICY_ROLE, NODES_ROLE, EDGES_ROLE, NCBI_ROLE, TAXDUMP_ROLE, JSON_ROLE} - bindings.keys()
        )

        def check_cache():
            """Check the original immutable resolution and evidence cache bindings."""
            if failed:
                _fail("previous selected-alias verification failed")
            if (
                self._baseline is not baseline
                or self._targets is not targets
                or self._evidence is not saved_evidence
                or self._audit_bytes != audit_bytes
                or self._contract_json != contract
            ):
                failed.append(True)
                _fail("parsed native resolution/witness cache changed")
            return True

        def check_role_mapping(current):
            """Require the original consumed roles and originally absent roles."""
            if not isinstance(current, dict) or any(
                current.get(role) != expected for role, expected in bindings.items()
            ):
                _fail("original consumed roles were removed or rebound")
            if absent_roles & current.keys():
                _fail("originally unconsumed selected-alias role was added")

        def check_roles():
            """Validate current role receipts and retain any failed verification."""
            try:
                check_cache()
                check_role_mapping(snapshots_getter())
            except Exception:
                failed.append(True)
                raise
            return True

        admission.capture_resolution(check_cache)
        admission.capture_resolution(check_roles)

        def checkpoint(snapshots=None, *, output_dir=None, metadata_only=False):
            """Verify native receipts, cache integrity, and the mandatory saved audit."""
            try:
                check_cache()
                check_roles()
                if snapshots is not None:
                    check_role_mapping(snapshots)
                admission.verify(metadata_only=metadata_only)
                if output[0] is not None or output_dir is not None:
                    directory = Path(output_dir) if output_dir is not None else output[0]
                    path = directory / AUDIT_FILE
                    if path.is_symlink() or not path.is_file() or path.read_bytes() != audit_bytes:
                        _fail("mandatory alias audit is missing or changed")
            except Exception:
                failed.append(True)
                raise

        def publish(directory):
            """Publish the exact native audit once and retain its output binding."""
            checkpoint(metadata_only=True)
            directory = Path(directory).absolute()
            if output[0] is not None:
                if output[0] != directory:
                    _fail("selected-alias audit output directory rebound")
                checkpoint()
                return
            with atomic_write(directory / AUDIT_FILE, mode="wb") as stream:
                stream.write(audit_bytes)
            admission.capture(directory / AUDIT_FILE)
            output[0] = directory
            checkpoint()

        def saved_contract():
            """Return a copied contract only after successful audit publication."""
            checkpoint(metadata_only=True)
            if output[0] is None:
                _fail("mandatory alias audit has not completed")
            return json.loads(contract)

        def restore(directory):
            """Bind a previously published audit after checking its exact bytes."""
            checkpoint(output_dir=directory)
            admission.capture(Path(directory) / AUDIT_FILE)
            output[0] = Path(directory).absolute()

        self._check_cache = check_cache
        self.verify = checkpoint
        self.finish = publish
        self.contract = saved_contract
        self._restore = restore
        self._expected_contract = lambda: json.loads(contract)

    def resolve(self, original_id):
        """Compose only approved finite aliases with unchanged one-step taxdump behavior."""
        self._check_cache()
        if original_id in FINITE_IDS and original_id not in self._targets:
            _fail("eligible resolution request lies outside the read native cohort")
        return self._targets.get(original_id, self._baseline.get(original_id, original_id))

    def evidence_for(self, original_id):
        """Return copied full evidence only for an admitted original eligible identifier."""
        self._check_cache()
        value = self._evidence.get(original_id)
        return json.loads(value) if value is not None else None


def _build(paths, locators, snapshots_getter, admission, consume_json=None):
    bindings, optional = {}, []
    parse_admission = SourceAdmission()
    snapshots = snapshots_getter()
    for role in (POLICY_ROLE, NODES_ROLE, EDGES_ROLE):
        bindings[role] = _bind(role, paths[role], locators[role], snapshots, admission, parse_admission)
    for role in (NCBI_ROLE, TAXDUMP_ROLE):
        lexical = locators[role]
        present = lexical.is_file()
        optional.append({"role": role, "path": str(lexical), "resolved": str(lexical.resolve()), "present": present})
        admission.capture_resolution(lambda path=lexical: (str(path.resolve()), path.is_file()))
        if (paths.get(role) is not None) != present:
            _fail(f"existing optional source locator selection disagrees: {role}")
        if present:
            bindings[role] = _bind(role, paths[role], lexical, snapshots, admission, parse_admission)
        elif role in snapshots:
            _fail("absent optional native authority has a consumed role")
    policy = _policy(paths[POLICY_ROLE])
    cohort = _cohort(paths[NODES_ROLE], paths[EDGES_ROLE], policy)
    merges, remap_witnesses = _merges(paths.get(TAXDUMP_ROLE))
    evidence = {}
    if cohort:
        if paths.get(NCBI_ROLE) is None or paths.get(TAXDUMP_ROLE) is None:
            _fail("eligible cohort requires selected sibling declarations and taxdump")
        if consume_json is not None:
            paths[JSON_ROLE] = consume_json(locators[JSON_ROLE])
        if paths.get(JSON_ROLE) is None:
            _fail("eligible cohort requires selected native JSON")
        bindings[JSON_ROLE] = _bind(
            JSON_ROLE, paths[JSON_ROLE], locators[JSON_ROLE], snapshots_getter(), admission, parse_admission
        )
        evidence = _authority(paths[JSON_ROLE], paths[NCBI_ROLE], policy["rules"], cohort, merges, remap_witnesses)
    elif JSON_ROLE in snapshots_getter():
        _fail("zero cohort must not claim a selected JSON read")
    parse_admission.verify()
    admission.verify()
    return SelectedTaxonAliases(policy, cohort, merges, evidence, bindings, optional, admission, snapshots_getter)


def prepare(transform, stack, nodes_path, edges_path, ncbi_path, taxdump_path):
    """Consume the finite policy/active JSON while retaining existing original role receipts."""
    admission = SourceAdmission()
    locators = _locators(transform.input_base_dir, transform.output_base_dir)

    def consume(role, path):
        """Capture the selected locator and consume its actual immutable snapshot."""
        admission.capture(path)
        return Path(stack.enter_context(transform.consume_input(role, path)).name)

    paths = {
        POLICY_ROLE: consume(POLICY_ROLE, locators[POLICY_ROLE]),
        NODES_ROLE: nodes_path,
        EDGES_ROLE: edges_path,
        NCBI_ROLE: ncbi_path,
        TAXDUMP_ROLE: taxdump_path,
    }
    return _build(
        paths,
        locators,
        lambda: transform.consumed_input_snapshots,
        admission,
        consume_json=lambda path: consume(JSON_ROLE, path),
    )


def restore_recorded(report, report_path, *, admission=None):
    """Reconstruct exact native evidence and audit; absence of a contract never means zero."""
    admission = admission if admission is not None else SourceAdmission()
    path = Path(report_path).absolute()
    raw_dir = report.get("raw_input_directory")
    if not raw_dir or not Path(raw_dir).is_absolute():
        _fail("recorded native source directory is missing")

    def getter():
        """Expose current recorded role receipts for retained verification."""
        return report.get("consumed_inputs", {})

    locators = _locators(raw_dir, path.parent.parent)
    paths = dict(locators)
    for role in (NCBI_ROLE, TAXDUMP_ROLE):
        if not paths[role].is_file():
            paths[role] = None
    resolver = _build(paths, locators, getter, admission)
    contract = report.get("producer_native_inputs", {}).get(CONTRACT_KEY)
    if contract != resolver._expected_contract():
        _fail("recorded finite contract disagrees with actual native evidence")
    expected = _json(contract)
    failed = []

    def verify_saved_contract():
        """Reject removal or replacement of the independently reconstructed contract."""
        current = _json(report.get("producer_native_inputs", {}).get(CONTRACT_KEY))
        if failed or current != expected:
            failed.append(True)
            _fail("recorded contract was removed or changed after native rejoin")
        return current

    admission.capture_resolution(verify_saved_contract)
    admission.capture_resolution(lambda: report.get("raw_input_directory"))
    resolver._restore(path.parent)
    if _json(report.get("producer_native_inputs", {}).get(CONTRACT_KEY)) != expected:
        _fail("recorded contract changed during native rejoin")
    return resolver
