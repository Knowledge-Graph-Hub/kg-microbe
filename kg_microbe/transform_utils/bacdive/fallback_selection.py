"""
Assess native candidate eligibility for BacDive name-derived taxonomy (#1364).

The caller must supply facts from the separately owned actual native reader and
retain this complete decision against the original raw record. Actual-read,
complete-source and output accounting belong to the composed fallback/taxonomy
guards; these pure scientific rules do not substitute for those contracts.
"""

import json
from dataclasses import dataclass

from kg_microbe.transform_utils.constants import CLASS, DOMAIN, FAMILY, GENUS, ORDER, PHYLUM, SPECIES

_PROKARYOTE_ROOTS = frozenset({"NCBITaxon:2", "NCBITaxon:2157"})
_SOURCE_DOMAIN = {"Bacteria": "NCBITaxon:2", "Archaea": "NCBITaxon:2157", "Eukaryota": "NCBITaxon:2759"}
_FIELDS = frozenset({SPECIES, GENUS, FAMILY, ORDER, CLASS, PHYLUM, DOMAIN})
_CONSTRUCTION_RANKS = {
    "parsed_genus": frozenset({"genus"}),
    "special_higher_rank": frozenset({"family", "order", "class", "phylum"}),
    "parsed_higher_parent": frozenset({"family", "order", "class", "phylum", "domain", "superkingdom"}),
}
_MATCH_MODES = frozenset({"native_exact_label", "selected_label_casefold", "special_selected_name_casefold"})


@dataclass(frozen=True)
class Selection:
    """Keep a rejected match distinct from an ordinary lookup miss."""

    status: str
    identifier: str | None
    terminal: bool
    evidence_json: str


def _encoded(value):
    """Use deterministic detached evidence, never caller-owned mutable dictionaries."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def assess_candidates(
    query, source_field, source_classification, candidates, *, route="ordinary_rank", match_mode="native_exact_label"
):
    """
    Assess actual native candidates without selecting an alternative synonym or parent.

    ``candidates`` must include the complete selected tier's result set, not its first member.
    A fast selected-label result does not claim a full-database homonym search.
    Native-reader and original-record bindings are separate mandatory contracts.
    Every nonempty-but-rejected set is terminal at this selector: it cannot be
    converted into a lookup miss that silently permits broader family fallthrough.
    This conservatively covers the reviewed175523 failure without hardcoding a
    replacement biological identity or trusting a source field's rank as evidence.
    """
    if not isinstance(query, str) or not query:
        raise ValueError("BacDive fallback query must be nonempty text")
    if source_field not in _FIELDS:
        raise ValueError("Unreviewed BacDive fallback source field")
    if route not in {"ordinary_rank", *_CONSTRUCTION_RANKS} or match_mode not in _MATCH_MODES:
        raise ValueError("Unreviewed BacDive native lookup/construction route")
    if match_mode == "special_selected_name_casefold" and route != "special_higher_rank":
        raise ValueError("Synonym support is limited to the existing special higher-rank route")
    if not isinstance(source_classification, dict):
        raise ValueError("BacDive fallback requires its original classification block")
    if len({candidate["id"] for candidate in candidates}) != len(candidates):
        raise ValueError("Native candidate IDs must be unique after retaining all literal query rows")
    details = []
    source_domain = source_classification.get(DOMAIN)
    expected_domain = _SOURCE_DOMAIN.get(source_domain) if isinstance(source_domain, str) else None
    for candidate in candidates:
        identifier = candidate["id"]
        labels = candidate["labels"]
        ranks = candidate["ranks"]
        ancestors = set(candidate["ancestors"]) | {identifier}
        native_domains = sorted(ancestors & _PROKARYOTE_ROOTS)
        names = labels
        if match_mode == "special_selected_name_casefold":
            names = labels + candidate["synonyms"]
        matches = (
            query in names
            if match_mode == "native_exact_label"
            else any(label.lower() == query.lower() for label in names)
        )
        reason = None
        if candidate["types"] != ["owl:Class"]:
            reason = "not_unique_native_class"
        elif candidate["deprecated"]:
            reason = "deprecated_native_candidate"
        elif not matches:
            reason = "native_label_does_not_match_actual_query"
        elif len(native_domains) != 1 or "NCBITaxon:2759" in ancestors:
            reason = "outside_or_ambiguous_prokaryote_domain"
        elif expected_domain and native_domains != [expected_domain]:
            reason = "native_domain_conflicts_with_source"
        elif len(ranks) != 1:
            reason = "missing_or_ambiguous_native_rank"
        elif route in _CONSTRUCTION_RANKS and ranks[0] not in _CONSTRUCTION_RANKS[route]:
            reason = "native_rank_cannot_support_constructed_hierarchy"
        # An ordinary source field is a search priority, not a native rank
        # assertion. In the complete813 compatibility inventory,59 genus-field
        # hits genuinely name native orders/families; retain those exact parents
        # at their actual native rank without minting a genus or species.
        rank_agrees = len(ranks) == 1 and (
            ranks[0] == source_field or source_field == DOMAIN and ranks[0] == "superkingdom"
        )
        details.append(
            {
                "candidate": candidate,
                "native_prokaryote_domains": native_domains,
                "source_field_matches_native_rank": rank_agrees,
                "rejection": reason,
            }
        )
    evidence = {
        "query": query,
        "source_field": source_field,
        "source_classification": source_classification,
        "candidates": details,
        "route": route,
        "match_mode": match_mode,
        "source_domain_status": "recognized_native_domain_label"
        if expected_domain
        else "absent"
        if not source_domain
        else "unrecognized_source_domain_not_identity_evidence",
        "automatic_replacement": False,
    }
    if not candidates:
        return Selection("no_match", None, False, _encoded(evidence))
    # Never discard an inconvenient same-label candidate and call the remaining
    # one uniquely identified; all distinct native candidates are audited.
    if len(candidates) != 1:
        return Selection("ambiguous_native_label", None, True, _encoded(evidence))
    if details[0]["rejection"]:
        return Selection(details[0]["rejection"], None, True, _encoded(evidence))
    return Selection("accepted_native_inference", candidates[0]["id"], False, _encoded(evidence))
