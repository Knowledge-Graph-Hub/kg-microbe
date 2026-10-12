"""Three definition-backed native category decisions; never a general Occurrent rule."""

import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from kg_microbe.transform_utils.constants import (
    CATEGORY_COLUMN,
    ENVIRONMENTAL_PROCESS_CATEGORY,
    ID_COLUMN,
    LIFE_STAGE_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
)
from kg_microbe.utils.graph_canonicalization import compact_identifier as compact
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/finite_envo_po_category_dispositions.json"
POLICY_SHA256 = "eb622aea6bc3b291dafe0746e797b8dc01b1409c186c2b3a36f3a3f54717dd96"
_ROUTES = {
    "ENVO:01001254": ("envo.json", ENVIRONMENTAL_PROCESS_CATEGORY),
    "ENVO:01001255": ("envo.json", ENVIRONMENTAL_PROCESS_CATEGORY),
    "PO:0007033": ("po.owl", LIFE_STAGE_CATEGORY),
}
FINITE_IDS = frozenset(_ROUTES)
CONTRACT_KEY = "finite_envo_po_category_authority"
POLICY_ROLE = "category_authority_finite_envo_po_category_dispositions"
_OWL = "{http://www.w3.org/2002/07/owl#}"
_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
_SUBCLASS = {"is_a", "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf"}


def canonical(value):
    """Keep native structured values while ignoring only JSON serialization formatting."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    """Digest exact bytes, including independently captured native source bytes."""
    return hashlib.sha256(value).hexdigest()


def unique_object(pairs):
    """Never accept last-key-wins changes to curated or native evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate finite ENVO/PO evidence key: {key}")
        result[key] = value
    return result


def load_policy(stream):
    """Require the independently reviewed complete three-ID policy and native evidence pins."""
    policy = json.load(stream, object_pairs_hook=unique_object)
    if digest(canonical(policy).encode()) != POLICY_SHA256:
        raise ValueError("Unreviewed finite ENVO/PO category policy")
    if set(policy["records"]) != FINITE_IDS or set(policy["authorities"]) != {"envo.json", "po.owl"}:
        raise ValueError("Incomplete finite ENVO/PO category cohort")
    for identifier, (authority, category) in _ROUTES.items():
        record = policy["records"][identifier]
        if (record["authority"], record["category"]) != (authority, category):
            raise ValueError("Unreviewed finite ENVO/PO authority or category route")
    return policy


def _json_evidence(content, contract):
    """Read complete selected native declarations and all their named parents from one graph."""
    document = json.loads(content, object_pairs_hook=unique_object)
    graphs = document.get("graphs")
    if (
        not isinstance(graphs, list)
        or len(graphs) != 1
        or graphs[0].get("id") != contract["ontology_id"]
        or graphs[0].get("meta", {}).get("version") != contract["version"]
    ):
        raise ValueError("Finite ENVO native authority identity/version changed")
    graph = graphs[0]
    selected = set(contract["selected_ids"])
    declarations, parents = {}, {identifier: [] for identifier in selected}
    for node in graph["nodes"]:
        identifier = compact(node["id"])
        if identifier not in selected:
            continue
        if identifier in declarations or node.get("type") != "CLASS" or obograph_is_deprecated(node):
            raise ValueError(f"Finite ENVO declaration is duplicate, deprecated or not a class: {identifier}")
        declarations[identifier] = node
    if set(declarations) != selected:
        raise ValueError("Finite ENVO native declarations are incomplete")
    for edge in graph.get("edges", []):
        subject = compact(edge["sub"])
        if subject in selected and edge["pred"] in _SUBCLASS:
            parents[subject].append(compact(edge["obj"]))
    return {
        "declarations": declarations,
        "named_parents": {identifier: sorted(values) for identifier, values in parents.items()},
        "restrictions": {},
    }


def _xml_record(element):
    """Preserve class structure/literals, independent of namespace prefixes and indentation."""
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": (element.text or "").strip(),
        "children": [_xml_record(child) for child in element if isinstance(child.tag, str)],
    }


def _owl_evidence(content, contract):
    """Read primary PO class/restriction evidence; do not resolve imports or invent BFO declarations."""
    tree = etree.parse(
        io.BytesIO(content), etree.XMLParser(resolve_entities="internal", no_network=True, load_dtd=False)
    )
    ontologies = list(tree.iter(_OWL + "Ontology"))
    if len(ontologies) != 1 or ontologies[0].get(_RDF + "about") != contract["ontology_id"]:
        raise ValueError("Finite PO native ontology identity changed")
    versions = ontologies[0].findall(_OWL + "versionIRI")
    if len(versions) != 1 or versions[0].get(_RDF + "resource") != contract["version"]:
        raise ValueError("Finite PO native ontology version changed")
    selected = set(contract["selected_ids"])
    declarations, parents, restrictions = {}, {}, {}
    for element in tree.iter():
        # XML comments and anonymous axiom/restriction structures are not
        # declarations. lxml comments return None even with a .get default.
        if not isinstance(element.tag, str) or not element.get(_RDF + "about"):
            continue
        identifier = compact(element.get(_RDF + "about"))
        if identifier not in selected:
            continue
        # An empty rdf:Description is a named reference (for example an
        # intersection operand), not an additional class/type assertion.
        # Nonempty descriptions still fail closed instead of hiding triples.
        if (
            element.tag == _RDF + "Description"
            and set(element.attrib) == {_RDF + "about"}
            and not len(element)
            and not (element.text or "").strip()
        ):
            continue
        if element.tag != _OWL + "Class":
            raise ValueError(f"Finite PO selected identifier has a nonclass declaration: {identifier}")
        deprecated = [(child.text or "").strip().lower() for child in element.findall(_OWL + "deprecated")]
        if identifier in declarations or any(value not in {"false", "0"} for value in deprecated):
            raise ValueError(f"Finite PO selected class is duplicate or deprecated: {identifier}")
        declarations[identifier] = _xml_record(element)
        parents[identifier] = sorted(
            compact(parent.get(_RDF + "resource"))
            for parent in element.findall(_RDFS + "subClassOf")
            if parent.get(_RDF + "resource")
        )
        values = []
        for restriction in element.iter(_OWL + "Restriction"):
            prop, target = restriction.find(_OWL + "onProperty"), restriction.find(_OWL + "someValuesFrom")
            if (
                prop is not None
                and target is not None
                and prop.get(_RDF + "resource")
                and target.get(_RDF + "resource")
            ):
                values.append([compact(prop.get(_RDF + "resource")), compact(target.get(_RDF + "resource"))])
        restrictions[identifier] = sorted(values)
    if set(declarations) != selected:
        raise ValueError("Finite PO primary declarations are incomplete")
    return {"declarations": declarations, "named_parents": parents, "restrictions": restrictions}


@dataclass(frozen=True)
class FiniteCategoryEvidence:
    """Immutable finite decision with a complete sealed native witness, not an asserted-root claim."""

    identifier: str
    category: str
    disposition: str
    authority_file: str
    authority_sha256: str
    native_witness_json: str
    decision_json: str


class FiniteEnvoPoCategoryAuthority:
    """Consume only required immutable primary inputs and retain their finite evidence through use."""

    def __init__(self, raw_dir, *, opener):
        """Reuse the source-finalization snapshot opener; never reopen an original native path."""
        self.raw_dir = Path(raw_dir)
        self.opener = opener
        self.source_paths = set()
        self._policy_json = None
        self._decisions = {}
        self._seen = set()
        self._bindings_json = "{}"
        self._locators = {}
        self._output_counts_json = None
        self._node_members = None

    def bind_output_members(self, members):
        """Bind the precise producer-finalization scope, not every TSV sharing its output directory."""
        selected = tuple(sorted(members))
        if (
            not selected
            or len(selected) != len(set(selected))
            or any(
                not isinstance(name, str) or Path(name).name != name or not name.endswith("nodes.tsv")
                for name in selected
            )
        ):
            raise ValueError("Invalid finite ENVO/PO node-member scope")
        if self._node_members is not None and self._node_members != selected:
            raise ValueError("Finite ENVO/PO original node-member scope changed")
        self._node_members = selected

    def _read(self, path, role):
        """Seal the precise bytes and lexical locator actually passed to the immutable opener."""
        path = Path(path)
        lexical, resolved = str(path.absolute()), str(path.resolve())
        with self.opener(path) as stream:
            content = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
        if isinstance(content, str):
            content = content.encode("utf-8")
        identity = {"path": resolved, "sha256": digest(content)}
        bindings = json.loads(self._bindings_json)
        if role in bindings and bindings[role] != identity:
            raise ValueError("Finite ENVO/PO consumed-input binding changed during read")
        if role in self._locators and self._locators[role] != (lexical, resolved):
            raise ValueError("Finite ENVO/PO native locator changed during read")
        bindings[role] = identity
        self._bindings_json = canonical(bindings)
        self._locators[role] = (lexical, resolved)
        return content

    def _policy(self):
        if self._policy_json is None:
            self.source_paths.add(POLICY_FILE)
            content = self._read(POLICY_FILE, POLICY_ROLE)
            self._policy_json = canonical(load_policy(io.StringIO(content.decode("utf-8"))))
        if digest(self._policy_json.encode()) != POLICY_SHA256:
            raise ValueError("Finite ENVO/PO cached policy changed after native admission")
        return json.loads(self._policy_json, object_pairs_hook=unique_object)

    def evidence_for(self, identifier):
        """Return a checked finite decision; unrelated IDs do not cause authority reads or propagation."""
        identifier = compact(identifier)
        if identifier not in FINITE_IDS:
            return None
        policy = self._policy()
        filename, category = _ROUTES[identifier]
        contract = policy["authorities"][filename]
        if identifier not in self._decisions:
            path = self.raw_dir / filename
            self.source_paths.add(path)
            content = self._read(path, native_role(filename))
            if digest(content) != contract["sha256"]:
                raise ValueError(f"Finite ENVO/PO native bytes changed; independent review required: {filename}")
            witness = _json_evidence(content, contract) if filename == "envo.json" else _owl_evidence(content, contract)
            serialized = canonical(witness)
            if digest(serialized.encode()) != contract["evidence_sha256"]:
                raise ValueError(f"Finite ENVO/PO definition/parent/restriction evidence changed: {filename}")
            for selected, record in policy["records"].items():
                if record["authority"] != filename:
                    continue
                self._decisions[selected] = FiniteCategoryEvidence(
                    selected,
                    record["category"],
                    record["disposition"],
                    filename,
                    contract["sha256"],
                    serialized,
                    canonical(record),
                )
        result = self._decisions[identifier]
        record = policy["records"][identifier]
        if (
            result.identifier != identifier
            or result.category != category
            or result.authority_file != filename
            or result.authority_sha256 != contract["sha256"]
            or result.disposition != record["disposition"]
            or result.decision_json != canonical(record)
            or digest(result.native_witness_json.encode()) != contract["evidence_sha256"]
        ):
            raise ValueError("Finite ENVO/PO cached decision or native witness changed after admission")
        self._seen.add(identifier)
        return result

    def verify(self, snapshots=None, *, output_dir=None):
        """Keep original named roles, locators, decisions and exact output cohort through publication."""
        bindings = json.loads(self._bindings_json, object_pairs_hook=unique_object)
        if not self._seen:
            if bindings or self._decisions or self._policy_json is not None or self._locators:
                raise ValueError("Finite ENVO/PO empty cohort contradicts consumed native evidence")
        else:
            if not self._seen <= FINITE_IDS:
                raise ValueError("Finite ENVO/PO unreviewed identifier inventory")
            policy = self._policy()
            filenames = {_ROUTES[identifier][0] for identifier in self._seen}
            expected_paths = {
                POLICY_ROLE: POLICY_FILE,
                **{native_role(name): self.raw_dir / name for name in filenames},
            }
            if set(bindings) != set(expected_paths) or set(self._locators) != set(expected_paths):
                raise ValueError("Finite ENVO/PO missing original consumed-input binding")
            for role, path in expected_paths.items():
                lexical, resolved = self._locators[role]
                if (
                    lexical != str(path.absolute())
                    or resolved != str(path.resolve())
                    or bindings[role]["path"] != resolved
                ):
                    raise ValueError("Finite ENVO/PO original consumed-input locator changed")
            for filename in filenames:
                if bindings[native_role(filename)]["sha256"] != policy["authorities"][filename]["sha256"]:
                    raise ValueError("Finite ENVO/PO original native byte identity changed")
            for identifier in tuple(self._seen):
                self.evidence_for(identifier)
        if snapshots is not None:
            if any(snapshots.get(role) != identity for role, identity in bindings.items()):
                raise ValueError("Finite ENVO/PO original consumed-input binding changed")
            if not self._seen and POLICY_ROLE in snapshots:
                raise ValueError("Finite ENVO/PO empty cohort contradicts policy consumption")
        if output_dir is not None:
            if self._node_members is None:
                raise ValueError("Missing finite ENVO/PO admitted node-member scope")
            counts = observed_target_counts(Path(output_dir) / name for name in self._node_members)
            if set(counts) != self._seen:
                raise ValueError("Finite ENVO/PO output identifier inventory changed before publication")
            serialized = canonical(counts)
            if self._output_counts_json is not None and self._output_counts_json != serialized:
                raise ValueError("Finite ENVO/PO output occurrence counts changed before publication")
            self._output_counts_json = serialized

    def contract(self):
        """Return a detached, explicit zero-or-finite contract with the original named read bindings."""
        self.verify()
        return {
            "version": 1,
            "identifiers": sorted(self._seen),
            "node_members": list(self._node_members) if self._node_members is not None else [],
            "occurrences": json.loads(self._output_counts_json) if self._output_counts_json is not None else {},
            "bindings": json.loads(self._bindings_json),
        }


def native_role(filename):
    """Match the existing source-finalization role names without conflating JSON and OWL bytes."""
    path = Path(filename)
    return "category_authority_" + path.stem + ("_owl" if path.suffix == ".owl" else "")


def observed_target_counts(paths, *, admission=None):
    """Read finite identifiers from actual graph members, not a self-declared contract inventory."""
    from kg_microbe.utils.source_finalization import graph_rows

    observed = Counter()
    for path in paths:
        if admission is not None:
            admission.capture(path)
        for row in graph_rows(path):
            identifier = row[ID_COLUMN]
            if identifier in FINITE_IDS:
                if row[CATEGORY_COLUMN] != _ROUTES[identifier][1]:
                    raise ValueError("Finite ENVO/PO output category is not finalized")
                observed[identifier] += 1
    return dict(observed)


def verify_recorded_inputs(report, report_path, *, admission=None):
    """Rejoin original named reads to immutable native evidence and actual finalized node identities."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    try:
        members = sorted(name for name in report.get("members", {}) if name.endswith("nodes.tsv"))
        paths = [Path(report_path).parent / name for name in members]
        counts = observed_target_counts(paths, admission=guard)
        observed = set(counts)
        contract = report.get(CONTRACT_KEY)
        if not isinstance(contract, dict) or set(contract) != {
            "version",
            "identifiers",
            "node_members",
            "occurrences",
            "bindings",
        }:
            raise ValueError("Missing finite ENVO/PO category contract")
        if (
            type(contract["version"]) is not int
            or contract["version"] != 1
            or contract["identifiers"] != sorted(observed)
            or contract["node_members"] != members
            or contract["occurrences"] != counts
            or any(type(value) is not int for value in contract["occurrences"].values())
        ):
            raise ValueError("Finite ENVO/PO contract inventory changed")
        snapshots = report.get("consumed_inputs", {})
        if not observed:
            if contract["bindings"] or POLICY_ROLE in snapshots:
                raise ValueError("Finite ENVO/PO zero contract contradicts consumed evidence")
        else:
            bindings = contract["bindings"]
            raw = Path(report["raw_input_directory"])
            filenames = {_ROUTES[identifier][0] for identifier in observed}
            expected_paths = {POLICY_ROLE: POLICY_FILE, **{native_role(name): raw / name for name in filenames}}
            if not isinstance(bindings, dict) or set(bindings) != set(expected_paths):
                raise ValueError("Missing finite ENVO/PO consumed-input roles")
            for role, path in expected_paths.items():
                identity = bindings[role]
                if (
                    not isinstance(identity, dict)
                    or set(identity) != {"path", "sha256"}
                    or identity["path"] != str(path.resolve())
                    or snapshots.get(role) != identity
                ):
                    raise ValueError("Finite ENVO/PO original consumed-input binding changed")
                if guard.capture(path)["sha256"] != identity["sha256"]:
                    raise ValueError("Finite ENVO/PO original consumed bytes changed")

            # Parsing these admitted bytes also rechecks the complete code-pinned
            # policy and full native definition/parent/restriction witness.
            def opener(path):
                """Expose admitted immutable bytes to the finite authority parser."""
                return io.BytesIO(guard.capture(path, retain=True))

            authority = FiniteEnvoPoCategoryAuthority(raw, opener=opener)
            authority.bind_output_members(members)
            for identifier in sorted(observed):
                authority.evidence_for(identifier)
            authority._output_counts_json = canonical(counts)
            if authority.contract() != contract:
                raise ValueError("Finite ENVO/PO native contract changed after reconstruction")
    except (ValueError, TypeError, KeyError) as exc:
        raise SourceFinalizationRequired("Invalid finite ENVO/PO category authority contract") from exc
    guard.verify(metadata_only=True)
    return guard


def restore_recorded_guard(transform, report, report_path):
    """Restore live role/locator/witness guards on repeat finalization of a newly constructed producer."""
    from kg_microbe.utils.source_finalization import snapshot_consumed_input

    verify_recorded_inputs(report, report_path)

    def opener(path):
        """Restore the original named consumed-input roles for repeat finalization."""
        role = POLICY_ROLE if path == POLICY_FILE else native_role(path.name)
        return snapshot_consumed_input(transform, role, path)

    authority = FiniteEnvoPoCategoryAuthority(transform.input_base_dir, opener=opener)
    authority.bind_output_members(report[CONTRACT_KEY]["node_members"])
    for identifier in report[CONTRACT_KEY]["identifiers"]:
        authority.evidence_for(identifier)
    authority._output_counts_json = canonical(report[CONTRACT_KEY]["occurrences"])
    authority.verify(transform.consumed_input_snapshots, output_dir=Path(report_path).parent)
    if authority.contract() != report[CONTRACT_KEY]:
        raise ValueError("Finite ENVO/PO repeat contract changed while restoring original reads")
    transform._finite_envo_po_category_guard = authority


def apply_finite_category(category, evidence):
    """Replace only reviewed generic fallbacks, preserving no conflicting substantive category."""
    if evidence is None:
        return category
    if evidence.identifier not in FINITE_IDS or evidence.category != _ROUTES[evidence.identifier][1]:
        raise ValueError("Unreviewed finite ENVO/PO category decision")
    existing = set(category.split("|")) - {""}
    if existing - {ONTOLOGY_CLASS_CATEGORY, "biolink:NamedThing", evidence.category}:
        raise ValueError(f"Unexpected substantive category for finite ENVO/PO class: {evidence.identifier}")
    return evidence.category
