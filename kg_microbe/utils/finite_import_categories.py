"""
Finite native import categories; no namespace-wide or strict-model waiver.

The two PCO qualities use Attribute's property semantics. This projection does
not supply its required ``has attribute type`` slot or certify incident edges.
The existing OBO:COB graph identifiers are preserved, not equated with ChEBI.
"""

import hashlib
import io
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    ATTRIBUTE_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
    PHYSICAL_ENTITY_CATEGORY,
)
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated
from kg_microbe.utils.release_binding import (
    canonical_digest,
    graph_release,
    is_release_source,
    read_bound_authority,
)

IMPORT_DISPOSITIONS_FILE = Path(__file__).resolve().parents[2] / "mappings/finite_import_category_dispositions.json"
FINITE_ID_SET_SHA256 = "ae53a95abe9bcf5f9298f02e4f6ae93d7d39233462619e122c873951628d56cb"
# Version 2 binds each authority to its release and reviewed decisions, not its file bytes (#1420).
POLICY_VERSION = 2
_OBO = "http://purl.obolibrary.org/obo/"
_COB_IDS = {"OBO:COB_0000011", "OBO:COB_0000013", "OBO:COB_0000080"}
_PCO_IDS = {"PCO:0000003", "PCO:0000004"}
_SUBCLASS = {"is_a", "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf"}
_AUTHORITIES = {"foodon.json", "uberon.json", "pato.json"}


def _unique_object(pairs):
    """Reject ambiguous JSON policy and native evidence objects."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate finite import authority key: {key}")
        result[key] = value
    return result


def _digest(value):
    """Use a deterministic digest of a complete native node, including all annotations."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def load_import_category_policy(stream):
    """Require the exact reviewed cohort, module routes, semantic roots and complete witnesses."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    if (
        not isinstance(policy, dict)
        or set(policy) != {"version", "finite_id_set_sha256", "authorities", "records"}
        or policy.get("version") != POLICY_VERSION
        or policy.get("finite_id_set_sha256") != FINITE_ID_SET_SHA256
        or not isinstance(policy.get("records"), dict)
        or len(policy["records"]) != 80
        or not isinstance(policy.get("authorities"), dict)
        or set(policy["authorities"]) != _AUTHORITIES
    ):
        raise ValueError("Invalid finite import category policy")
    identifiers = "".join(identifier + "\n" for identifier in sorted(policy["records"]))
    if hashlib.sha256(identifiers.encode()).hexdigest() != FINITE_ID_SET_SHA256:
        raise ValueError("Unreviewed finite import identifier cohort")
    for filename, authority in policy["authorities"].items():
        if (
            not isinstance(authority, dict)
            or set(authority) != {"graph_id", "release", "source", "decisions_sha256"}
            or authority.get("graph_id") != _OBO + filename.replace(".json", ".owl")
            or not isinstance(authority.get("release"), str)
            or not authority["release"].startswith(_OBO)
            or not is_release_source(authority.get("source"))
            or not re.fullmatch(r"[0-9a-f]{64}", authority.get("decisions_sha256", ""))
        ):
            raise ValueError(f"Invalid finite import native authority: {filename}")
    for identifier, record in policy["records"].items():
        filename = "pato.json" if identifier in _PCO_IDS else "uberon.json" if identifier in _COB_IDS else "foodon.json"
        category = ATTRIBUTE_CATEGORY if identifier in _PCO_IDS else PHYSICAL_ENTITY_CATEGORY
        native_iri = _OBO + (identifier[4:] if identifier in _COB_IDS else identifier.replace(":", "_", 1))
        root = _OBO + ("PATO_0000001" if identifier in _PCO_IDS else "BFO_0000040")
        if (
            not isinstance(record, dict)
            or set(record)
            != {"authority_file", "category", "native_iri", "native_label", "native_node_sha256", "ancestor_paths"}
            or record.get("authority_file") != filename
            or record.get("category") != category
            or record.get("native_iri") != native_iri
            or not isinstance(record.get("native_label"), str)
            or not record["native_label"].strip()
            or not re.fullmatch(r"[0-9a-f]{64}", record.get("native_node_sha256", ""))
            or not isinstance(record.get("ancestor_paths"), dict)
            or root not in record["ancestor_paths"]
            or record["ancestor_paths"].get(native_iri) != [native_iri]
        ):
            raise ValueError(f"Invalid finite import category record: {identifier}")
        for ancestor, path in record["ancestor_paths"].items():
            if (
                not isinstance(path, list)
                or not path
                or path[0] != native_iri
                or path[-1] != ancestor
                or any(not isinstance(value, str) or not value.startswith(_OBO) for value in path)
                or len(path) != len(set(path))
            ):
                raise ValueError(f"Invalid finite import ancestor witness: {identifier}")
    return policy


@dataclass(frozen=True)
class ImportCategoryEvidence:
    """Native category projection, not chemical identity or strict model acceptance."""

    identifier: str
    category: str
    authority: str
    authority_sha256: str
    root_paths: tuple[tuple[str, ...], ...]
    supporting_axioms: tuple[tuple[str, str, str], ...]
    disposition: str = "finite_asserted_native_import"


def decisions_digest(decisions):
    """Digest the reviewed decisions: each record's category, root paths and supporting axioms."""
    return canonical_digest(
        [
            [identifier, evidence.category, evidence.root_paths, evidence.supporting_axioms]
            for identifier, evidence in sorted(decisions.items())
        ]
    )


def load_import_category_evidence(policy, filename, native_stream):
    """
    Inspect all live same-module ancestors of the reviewed records in one native authority.

    The JSON must declare the reviewed release, and the decisions it yields must be the
    reviewed ones. Its own bytes are not pinned: the caller binds the release file it was
    converted from (#1420).
    """
    authority = policy["authorities"][filename]
    payload = native_stream.buffer.read() if hasattr(native_stream, "buffer") else native_stream.read()
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    document = json.loads(payload, object_pairs_hook=_unique_object)
    graphs = document.get("graphs")
    if not isinstance(graphs, list) or len(graphs) != 1 or graphs[0].get("id") != authority["graph_id"]:
        raise ValueError(f"Missing or unexpected finite import native graph: {filename}")
    graph = graphs[0]
    if graph_release(graph) != authority["release"]:
        raise ValueError(f"Unreviewed finite import native release: {filename}")
    nodes, parents, axioms = {}, defaultdict(set), defaultdict(set)
    for node in graph["nodes"]:
        identifier = node["id"]
        if identifier in nodes:
            raise ValueError(f"Duplicate finite import native declaration: {identifier}")
        nodes[identifier] = node
    for edge in graph["edges"]:
        if edge["pred"] in _SUBCLASS:
            parents[edge["sub"]].add(edge["obj"])
            axioms[edge["sub"], edge["obj"]].add(edge["pred"])
    decisions = {}
    for identifier, record in policy["records"].items():
        if record["authority_file"] != filename:
            continue
        iri = record["native_iri"]
        visited, pending = set(), deque([iri])
        while pending:
            current = pending.popleft()
            if current in visited:
                continue
            node = nodes.get(current)
            if node is None or node.get("type") != "CLASS" or obograph_is_deprecated(node):
                raise ValueError(f"Finite import ancestor is missing, obsolete or not a class: {current}")
            visited.add(current)
            pending.extend(parents[current])
        if nodes[iri].get("lbl") != record["native_label"] or _digest(nodes[iri]) != record["native_node_sha256"]:
            raise ValueError(f"Finite import native declaration changed: {identifier}")
        if visited != set(record["ancestor_paths"]):
            raise ValueError(f"Finite import complete ancestry changed: {identifier}")
        for path in record["ancestor_paths"].values():
            if any(parent not in parents[child] for child, parent in zip(path, path[1:], strict=False)):
                raise ValueError(f"Missing asserted finite import ancestor witness: {identifier}")
        material = _OBO + "BFO_0000040" in visited
        quality = _OBO + "PATO_0000001" in visited
        process = bool({_OBO + "BFO_0000003", _OBO + "BFO_0000015", _OBO + "GO_0008150"} & visited)
        population = bool({_OBO + "PCO_0000001", _OBO + "PCO_0000002"} & visited)
        if process or population or material == quality or (record["category"] == ATTRIBUTE_CATEGORY) != quality:
            raise ValueError(f"Contradictory finite import native ancestry: {identifier}")
        required = (
            {"PATO_0002003", "PATO_0001241"} if quality else {"ENVO_01000813"} if filename == "foodon.json" else set()
        )
        if not {_OBO + value for value in required} <= visited:
            raise ValueError(f"Missing reviewed finite import ancestry: {identifier}")
        paths = tuple(tuple(path) for _, path in sorted(record["ancestor_paths"].items()))
        supporting = tuple(
            sorted(
                (child, predicate, parent)
                for child in visited
                for parent in parents[child]
                for predicate in axioms[child, parent]
            )
        )
        decisions[identifier] = ImportCategoryEvidence(
            identifier, record["category"], filename, authority["source"]["sha256"], paths, supporting
        )
    if decisions_digest(decisions) != authority["decisions_sha256"]:
        raise ValueError(f"Finite import decisions differ from the reviewed release content: {filename}")
    return decisions


def apply_import_category(category, evidence):
    """Replace only reviewed generic/redundant typing, never silently erase a substantive type."""
    if set(category.split("|")) - {"", ONTOLOGY_CLASS_CATEGORY, "biolink:NamedThing", evidence.category}:
        raise ValueError(f"Unexpected substantive category for finite import {evidence.identifier}: {category}")
    return evidence.category


class FiniteImportCategoryAuthority:
    """Run-owned lazy finite policy and native snapshots, without cross-run caches."""

    def __init__(self, raw_dir, *, opener):
        """Use only the caller's selected raw files and consumed-input snapshot hook."""
        self.raw_dir = Path(raw_dir)
        self.opener = opener
        self.source_paths = set()
        self._policy = None
        self._decisions = {}

    def evidence_for(self, identifier):
        """Return no override outside the exact finite reviewed set."""
        if not identifier.startswith("GAZ:") and identifier not in _PCO_IDS | _COB_IDS:
            return None
        if self._policy is None:
            self.source_paths.add(IMPORT_DISPOSITIONS_FILE)
            with self.opener(IMPORT_DISPOSITIONS_FILE) as stream:
                self._policy = load_import_category_policy(stream)
        record = self._policy["records"].get(identifier)
        if record is None:
            return None
        filename = record["authority_file"]
        if filename not in self._decisions:
            source = self._policy["authorities"][filename]["source"]
            payload = read_bound_authority(self.raw_dir, filename, source, self.opener, self.source_paths)
            self._decisions[filename] = load_import_category_evidence(self._policy, filename, io.BytesIO(payload))
        return self._decisions[filename][identifier]
