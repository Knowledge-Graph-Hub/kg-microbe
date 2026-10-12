"""Conserve complete native observations of the finite selected-alias GOLD cohort (#1340)."""

import json
from collections import Counter

from kg_microbe.transform_utils.constants import IN_TAXON_PREDICATE, KNOWLEDGE_ASSERTION, MANUAL_AGENT
from kg_microbe.transform_utils.gold import selected_taxon_aliases
from kg_microbe.utils.source_finalization import SourceFinalizationRequired


class AliasObservations:
    """Retain the exact independently projected native assertions, without graph edits."""

    def __init__(self, index):
        """Rejoin pinned complete incidents to actual native declarations and all parent edges."""
        from kg_microbe.transform_utils.gold.gold import _DROP_CATEGORIES, _UNINFORMATIVE_ECOSYSTEM_LABELS
        from kg_microbe.transform_utils.gold.taxon_dispositions import EDGE_HEADER, _association, _json, _rows

        records, incidents = set(), {}
        if index.resolver is not None:
            for original in selected_taxon_aliases.FINITE_IDS:
                evidence = index.resolver.evidence_for(original)
                if evidence is None:
                    continue
                records.update(json.loads(evidence["native_records_json"]))
                for item in json.loads(evidence["native_incident_rows_json"]):
                    incidents[_json(item)] = item["row"]
        expected = Counter()
        if records:
            needed = {identifier for row in incidents.values() for identifier in (row["subject"], row["object"])}
            parents = {}
            for item in _rows(index.native_edges, ("subject", "predicate", "object")):
                row = item["row"]
                if row["subject"].startswith("gold.ecosystem:") and row["predicate"] == "biolink:subclass_of":
                    parents.setdefault(row["subject"], []).append(row["object"])
            frontier = {identifier for identifier in needed if identifier.startswith("gold.ecosystem:")}
            visited = set()
            while frontier:
                identifier = frontier.pop()
                if identifier in visited:
                    continue
                visited.add(identifier)
                for parent in parents.get(identifier, []):
                    needed.add(parent)
                    frontier.add(parent)
            declarations = {}
            for item in _rows(index.native_nodes, ("id", "category", "name")):
                row = item["row"]
                if row["id"] in needed:
                    if row["id"] in declarations:
                        raise SourceFinalizationRequired("Duplicate selected-alias observation context")
                    declarations[row["id"]] = row
            if declarations.keys() != needed:
                raise SourceFinalizationRequired("Selected-alias observation context is incomplete")
            excluded = {
                identifier
                for identifier, row in declarations.items()
                if set(row["category"].split("|")) & set(_DROP_CATEGORIES)
            }
            for row in incidents.values():
                if {row["subject"], row["object"]} & excluded:
                    continue  # The five native Study links remain audited, not emitted.
                if row["subject"] not in records:
                    raise SourceFinalizationRequired("Unreviewed selected-alias incoming observation")
                if row["predicate"] == IN_TAXON_PREDICATE:
                    emitted = _association(row, index.resolver.resolve(row["object"]))
                elif row["predicate"] == "biolink:occurs_in":
                    target, seen = row["object"], set()
                    while target is not None and declarations[target]["name"].strip().lower() in (
                        _UNINFORMATIVE_ECOSYSTEM_LABELS
                    ):
                        if target in seen or len(parents.get(target, [])) > 1:
                            raise SourceFinalizationRequired("Ambiguous selected-alias environment ancestry")
                        seen.add(target)
                        target = next(iter(parents.get(target, [])), None)
                    if target is None:
                        continue  # The four root-only native observations remain excluded.
                    emitted = dict(
                        zip(
                            EDGE_HEADER,
                            (
                                row["subject"],
                                "biolink:located_in",
                                target,
                                "RO:0001025",
                                row.get("primary_knowledge_source", "") or "infores:gold",
                                KNOWLEDGE_ASSERTION,
                                MANUAL_AGENT,
                                row["object"] if target != row["object"] else "",
                            ),
                            strict=True,
                        )
                    )
                else:
                    raise SourceFinalizationRequired("Unreviewed selected-alias native observation")
                expected[_json(emitted)] += 1
        sealed_records, sealed_expected = frozenset(records), _json(expected)
        failed = False

        def verify_graph(path, *, quoting):
            """Compare every finite incident output against native projection and retain refusal."""
            nonlocal failed
            if failed or self.verify_graph is not verify_graph:
                failed = True
                raise SourceFinalizationRequired("Selected-alias observation guard was changed or failed")
            if not sealed_records:
                return
            try:
                observed = Counter()
                for item in _rows(path, ("subject", "predicate", "object"), quoting=quoting):
                    row = item["row"]
                    if {row["subject"], row["object"]} & sealed_records:
                        if any(value for key, value in row.items() if key not in EDGE_HEADER):
                            raise SourceFinalizationRequired(
                                "Selected-alias observation has unsupported additional assertion evidence"
                            )
                        observed[_json({key: row.get(key, "") for key in EDGE_HEADER})] += 1
                if _json(observed) != sealed_expected:
                    raise SourceFinalizationRequired("Selected-alias native observation output changed")
            except Exception:
                failed = True
                raise

        self.verify_graph = verify_graph
