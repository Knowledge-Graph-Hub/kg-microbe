"""Approved finite pod/whole-tail categories, independent of the kernel Food policy."""

import json
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    ANATOMICAL_ENTITY_CATEGORY,
    FOOD_CATEGORY,
    GROSS_ANATOMICAL_STRUCTURE_CATEGORY,
    NAMED_THING_CATEGORY,
    NCBI_CATEGORY,
    ONTOLOGY_CLASS_CATEGORY,
)
from kg_microbe.utils import ontology_parent_quarantine as native
from kg_microbe.utils.graph_canonicalization import compact_identifier

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/foodon_anatomical_category_dispositions.json"
POLICY_SHA256 = "a9c1df3686f4c459fdb1b10a3d1403558a91ce7445b298bc45348135dc0cfb24"
POD_IDS = frozenset(
    "FOODON:" + local
    for local in (
        "00002763",
        "00002764",
        "00002765",
        "00002771",
        "00002782",
        "00002811",
        "00002812",
        "00003165",
        "00003308",
        "00003404",
        "00003674",
        "00003902",
        "00004236",
        "03000101",
        "03000102",
        "03000155",
        "03000156",
        "03000212",
        "03305806",
        "03309932",
        "03310435",
        "03311356",
    )
)
TAIL_IDS = frozenset({"FOODON:00002894", "FOODON:03308354"})
FINITE_IDS = POD_IDS | TAIL_IDS


def load_policy(stream):
    """Require the complete reviewed policy; altered categories or scope need new review."""
    policy = json.load(stream, object_pairs_hook=native.unique_object)
    if native.digest(policy) != POLICY_SHA256:
        raise ValueError("Unreviewed FOODON anatomical category policy")
    if (
        set(policy["bean_pod_ids"]) != POD_IDS
        or set(policy["whole_tail_ids"]) != TAIL_IDS
        or policy["category"] != GROSS_ANATOMICAL_STRUCTURE_CATEGORY
        or policy["native_evidence"]["parent_policy_canonical_sha256"] != native.POLICY_SHA256
    ):
        raise ValueError("FOODON anatomical category scope or evidence changed")
    return policy


def selected(graphs):
    """Touching an approved ID requires evidence, including an undeclared endpoint."""
    return any(
        compact_identifier(node.get("id", "")) in FINITE_IDS for graph in graphs for node in graph.get("nodes", [])
    ) or any(
        compact_identifier(edge.get(key, "")) in FINITE_IDS
        for graph in graphs
        for edge in graph.get("edges", [])
        for key in ("sub", "obj")
    )


def categories_for(graphs, *, policy=None, parent_policy=None):
    """Validate the original native context; do not classify a pruned fallback view."""
    if not selected(graphs):
        return {}
    if policy is None:
        with POLICY_FILE.open(encoding="utf-8") as stream:
            policy = load_policy(stream)
    if parent_policy is None:
        with native.POLICY_FILE.open(encoding="utf-8") as stream:
            parent_policy = native.load_policy(stream)
    # The pre-existing finite evidence includes both edamame paths, all 22 pods,
    # whole tails, culinary controls, equivalent expressions and native epoch.
    context = native.json_context({"graphs": graphs}, parent_policy["sources"]["foodon"])
    if context is None:
        raise ValueError("Missing FOODON anatomical native context")
    declarations = {compact_identifier(node["id"]): node for node in context["nodes"]}
    if not FINITE_IDS <= declarations.keys() or any(declarations[key].get("type") != "CLASS" for key in FINITE_IDS):
        raise ValueError("Missing FOODON anatomical CLASS declarations")
    return dict.fromkeys(FINITE_IDS, policy["category"])


def apply_category(identifier, incoming, categories):
    """Replace reviewed legacy projections only; reject unrelated substantive types."""
    if identifier not in categories:
        return incoming
    allowed = {
        "",
        ONTOLOGY_CLASS_CATEGORY,
        NAMED_THING_CATEGORY,
        FOOD_CATEGORY,
        NCBI_CATEGORY,
        ANATOMICAL_ENTITY_CATEGORY,
        GROSS_ANATOMICAL_STRUCTURE_CATEGORY,
    }
    if not set(incoming.split("|")) <= allowed:
        raise ValueError(f"Unreviewed FOODON anatomical substantive category: {identifier}: {incoming}")
    return categories[identifier]


def cache_signature():
    """Invalidate direct-call stat caches for both finite policies; producers bind full bytes."""
    return tuple(
        (str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (POLICY_FILE, native.POLICY_FILE)
    )
