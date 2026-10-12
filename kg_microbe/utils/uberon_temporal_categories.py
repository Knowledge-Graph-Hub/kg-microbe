"""
Finite native UBERON temporal categories, independent of edge-validation outcomes.

Life stages are not anatomy. The whole life cycle is projected only to the
generic Activity superclass, and instantaneous boundaries remain explicitly
unresolved ontology classes. Neither the latter fallback nor the LifeStage
projection claims strict conformance with Biolink temporal endpoint rules.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    ACTIVITY_CATEGORY,
    ANATOMICAL_ENTITY_CATEGORY,
    LIFE_STAGE_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
)
from kg_microbe.utils.graph_canonicalization import compact_identifier
from kg_microbe.utils.ontology_metadata import obograph_is_deprecated

TEMPORAL_DISPOSITIONS_FILE = Path(__file__).resolve().parents[2] / "mappings/uberon_temporal_category_dispositions.json"
_BOUNDARIES = {"UBERON:0035944", "UBERON:0035945", "UBERON:0035946"}
_CATEGORY_DISPOSITIONS = {
    LIFE_STAGE_CATEGORY: "asserted_life_stage",
    ACTIVITY_CATEGORY: "asserted_process_generic_activity",
    ONTOLOGY_CLASS_CATEGORY: "unresolved_temporal_boundary",
}
_SUBCLASS_PREDICATES = {"is_a", "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf"}


def _unique_object(pairs):
    """Reject duplicate JSON keys instead of letting a later rule overwrite evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate temporal authority key: {key}")
        result[key] = value
    return result


def load_temporal_category_policy(stream):
    """Validate the finite policy's identity and shape before consulting native evidence."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    if (
        not isinstance(policy, dict)
        or policy.get("version") != 1
        or policy.get("authority") != "UBERON"
        or policy.get("native_file") != "uberon.json"
        or not re.fullmatch(r"[0-9a-f]{64}", policy.get("native_sha256", ""))
        or not isinstance(policy.get("records"), dict)
        or len(policy["records"]) != 58
    ):
        raise ValueError("Invalid finite UBERON temporal category policy")
    categories = Counter()
    for identifier, record in policy["records"].items():
        if (
            not re.fullmatch(r"UBERON:[0-9]{7}", identifier)
            or not isinstance(record, dict)
            or set(record) != {"category", "disposition", "native_label", "required_paths"}
            or record.get("category") not in _CATEGORY_DISPOSITIONS
            or record.get("disposition") != _CATEGORY_DISPOSITIONS[record["category"]]
            or not isinstance(record.get("native_label"), str)
            or not record["native_label"].strip()
            or not isinstance(record.get("required_paths"), list)
            or not record["required_paths"]
        ):
            raise ValueError(f"Invalid UBERON temporal category record: {identifier}")
        for path in record["required_paths"]:
            if (
                not isinstance(path, list)
                or not path
                or path[0] != identifier
                or any(not isinstance(value, str) or not value for value in path)
                or len(path) != len(set(path))
            ):
                raise ValueError(f"Invalid UBERON temporal witness path: {identifier}")
        if (record["category"] == ACTIVITY_CATEGORY) != (identifier == "UBERON:0000104"):
            raise ValueError(f"Unreviewed generic activity projection: {identifier}")
        if (record["category"] == ONTOLOGY_CLASS_CATEGORY) != (identifier in _BOUNDARIES):
            raise ValueError(f"Unreviewed temporal boundary fallback: {identifier}")
        categories[record["category"]] += 1
    if categories != {LIFE_STAGE_CATEGORY: 54, ACTIVITY_CATEGORY: 1, ONTOLOGY_CLASS_CATEGORY: 3}:
        raise ValueError("Incomplete finite UBERON temporal category cohort")
    return policy


@dataclass(frozen=True)
class TemporalCategoryEvidence:
    """A category decision with native witness paths, not an assertion-level waiver."""

    identifier: str
    category: str
    disposition: str
    authority_sha256: str
    root_paths: tuple[tuple[str, ...], ...]


def load_temporal_category_evidence(policy, native_stream):
    """Require pinned bytes, live native classes and complete noncontradictory ancestry."""
    text = native_stream.read()
    native_bytes = text.encode("utf-8") if isinstance(text, str) else text
    if hashlib.sha256(native_bytes).hexdigest() != policy["native_sha256"]:
        raise ValueError("UBERON temporal category authority digest changed; native review required")
    document = json.loads(native_bytes, object_pairs_hook=_unique_object)
    graphs = document.get("graphs")
    if not isinstance(graphs, list) or not graphs:
        raise ValueError("Missing UBERON temporal category authority graphs")
    declarations, labels, parents = {}, {}, defaultdict(set)
    for graph in graphs:
        for node in graph["nodes"]:
            identifier = compact_identifier(node["id"])
            declaration = node.get("type"), obograph_is_deprecated(node)
            if identifier in declarations and declarations[identifier] != declaration:
                raise ValueError(f"Conflicting UBERON declarations: {identifier}")
            declarations[identifier] = declaration
            if identifier in labels and labels[identifier] != node.get("lbl", ""):
                raise ValueError(f"Conflicting UBERON labels: {identifier}")
            labels[identifier] = node.get("lbl", "")
        for edge in graph.get("edges", []):
            if edge["pred"] in _SUBCLASS_PREDICATES:
                parents[compact_identifier(edge["sub"])].add(compact_identifier(edge["obj"]))
    decisions = {}
    for identifier, record in policy["records"].items():
        visited, pending = set(), deque([identifier])
        while pending:
            current = pending.popleft()
            if current in visited:
                continue
            if declarations.get(current) != ("CLASS", False):
                raise ValueError(f"UBERON temporal ancestry is missing, obsolete or not a class: {current}")
            visited.add(current)
            pending.extend(parents[current])
        if labels[identifier] != record["native_label"]:
            raise ValueError(f"UBERON temporal native label disagrees with reviewed record: {identifier}")
        if "BFO:0000003" not in visited or "BFO:0000002" in visited or "UBERON:0001062" in visited:
            raise ValueError(f"Contradictory or absent UBERON temporal ancestry: {identifier}")
        for path in record["required_paths"]:
            if any(parent not in parents[child] for child, parent in zip(path, path[1:], strict=False)):
                raise ValueError(f"Missing asserted UBERON temporal witness: {identifier}")
        category = record["category"]
        if category == LIFE_STAGE_CATEGORY and not {"UBERON:0000105", "BFO:0000015"} <= visited:
            raise ValueError(f"Missing asserted life-stage ancestry: {identifier}")
        if category == ACTIVITY_CATEGORY and ("BFO:0000015" not in visited or "UBERON:0000105" in visited):
            raise ValueError(f"Life cycle is not the reviewed process distinct from its stages: {identifier}")
        if category == ONTOLOGY_CLASS_CATEGORY and {"BFO:0000015", "UBERON:0000105"} & visited:
            raise ValueError(f"Boundary gained process/stage ancestry requiring review: {identifier}")
        decisions[identifier] = TemporalCategoryEvidence(
            identifier,
            category,
            record["disposition"],
            policy["native_sha256"],
            tuple(tuple(path) for path in record["required_paths"]),
        )
    return decisions


def apply_temporal_category(category, evidence):
    """Remove only the reviewed legacy anatomy/fallback typing; reject unexpected types."""
    existing = set(category.split("|")) - {""}
    allowed = {ANATOMICAL_ENTITY_CATEGORY, ONTOLOGY_CLASS_CATEGORY, "biolink:NamedThing", evidence.category}
    if existing - allowed:
        raise ValueError(f"Unexpected substantive category for temporal class {evidence.identifier}: {category}")
    return evidence.category


@lru_cache(maxsize=2)
def _provisional_identifiers(path, size, mtime_ns):
    """Cache only the provisional guard; finalization independently pins consumed bytes."""
    del size, mtime_ns
    with Path(path).open(encoding="utf-8") as stream:
        return frozenset(load_temporal_category_policy(stream)["records"])


def is_reviewed_temporal_identifier(identifier):
    """Keep an early prefix fallback from reasserting anatomy for reviewed temporal IDs."""
    stat = TEMPORAL_DISPOSITIONS_FILE.stat()
    return identifier in _provisional_identifiers(str(TEMPORAL_DISPOSITIONS_FILE), stat.st_size, stat.st_mtime_ns)
