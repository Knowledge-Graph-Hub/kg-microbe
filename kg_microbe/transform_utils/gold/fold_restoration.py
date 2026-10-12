"""Audit restored source-owned observations without treating lexical equality as identity (#1316)."""

import hashlib
import json
import sqlite3
from collections import Counter

from kg_microbe.transform_utils.constants import (
    IN_TAXON_PREDICATE,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

AUDIT_FILE = "gold_lexical_fold_restorations.tsv"
AUDIT_HEADER = (
    "id",
    "disposition",
    "historical_fold_target",
    "native_node_json",
    "selected_taxon_declaration_json",
    "native_incident_assertions_json",
    "native_context_declarations_json",
    "native_ecosystem_hierarchy_json",
    "historical_emitted_claims_json",
    "restored_emitted_claims_json",
    "claim_dispositions_json",
    "native_inputs_json",
)


class FoldRestoration:
    """Disk-backed complete native witnesses for diagnostic historical folds, never active aliases."""

    def __init__(self, index, nodes, edges, ncbi):
        """Read every relevant incident and complete context from the already consumed native snapshots."""
        from kg_microbe.transform_utils.gold.gold import _DROP_CATEGORIES, _UNINFORMATIVE_ECOSYSTEM_LABELS
        from kg_microbe.transform_utils.gold.taxon_dispositions import _json, _rows

        self.index, self.db = index, index.db
        self.historical = index.historical_folds
        self.db.execute("CREATE TABLE fold_incidents(id TEXT,native TEXT)")
        self.db.execute("CREATE INDEX fold_incident_ids ON fold_incidents(id)")
        self.db.execute("CREATE TABLE fold_context(id TEXT PRIMARY KEY,native TEXT)")
        self.db.execute("CREATE TABLE fold_taxa(id TEXT PRIMARY KEY,native TEXT)")
        self.hierarchy, self.labels, self.resolution = {}, {}, {}
        self.excluded_context = set()
        self.excluded = set(index.dropped)
        self.independent_taxon_locations = set()
        if not self.historical:
            self._seal_native_context()
            return
        needed = set(self.historical)
        direct_locations = []
        for item in _rows(edges, ("subject", "predicate", "object")):
            row = item["row"]
            endpoints = {row["subject"], row["object"]}
            selected = endpoints & self.historical.keys()
            if selected:
                needed.update(endpoints)
                self.db.executemany(
                    "INSERT INTO fold_incidents VALUES (?,?)", ((identifier, _json(item)) for identifier in selected)
                )
            if row["subject"].startswith("gold.ecosystem:") and row["predicate"] == "biolink:subclass_of":
                self.hierarchy.setdefault(row["subject"], []).append(item)
            if row["subject"].startswith("NCBITaxon:") and row["predicate"] in {
                "biolink:occurs_in",
                "biolink:located_in",
            }:
                direct_locations.append(row)
        # All ancestor declarations and all parent edges are retained, not a
        # single chosen context path or one copied parent label.
        frontier = {identifier for identifier in needed if identifier.startswith("gold.ecosystem:")}
        visited = set()
        while frontier:
            identifier = frontier.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            for item in self.hierarchy.get(identifier, []):
                parent = item["row"]["object"]
                needed.add(parent)
                frontier.add(parent)
        for item in _rows(nodes, ("id", "category", "name")):
            row = item["row"]
            if row["id"].startswith("gold.ecosystem:"):
                self.labels[row["id"]] = row["name"].strip()
            if any(category in row["category"].split("|") for category in _DROP_CATEGORIES):
                self.excluded_context.add(row["id"])
            if row["id"] in needed:
                self.db.execute("INSERT INTO fold_context VALUES (?,?)", (row["id"], _json(item)))
                needed.remove(row["id"])
        if needed:
            raise SourceFinalizationRequired(
                "Restored GOLD source assertions lack complete native context declarations"
            )
        self.excluded.update(self.excluded_context)
        targets = set(self.historical.values())
        for item in _rows(ncbi if ncbi is not None else nodes, ("id", "name")):
            if item["row"]["id"] in targets:
                self.db.execute("INSERT INTO fold_taxa VALUES (?,?)", (item["row"]["id"], _json(item)))
        # Only contexts actually touched by the restored records are reviewed
        # here; unrelated source ecosystems retain their existing policy.
        for identifier in visited:
            label = self.labels.get(identifier, "")
            if label.lower() not in _UNINFORMATIVE_ECOSYSTEM_LABELS:
                continue
            cursor, seen = identifier, set()
            while cursor is not None and self.labels.get(cursor, "").lower() in _UNINFORMATIVE_ECOSYSTEM_LABELS:
                if cursor in seen:
                    raise SourceFinalizationRequired("Cyclic native GOLD environment context requires review")
                seen.add(cursor)
                parents = self.hierarchy.get(cursor, [])
                if len(parents) > 1:
                    raise SourceFinalizationRequired("Ambiguous native GOLD environment context requires review")
                cursor = parents[0]["row"]["object"] if parents else None
            self.resolution[identifier] = cursor
        for row in direct_locations:
            target = self.resolution.get(row["object"], row["object"])
            if target is not None:
                self.independent_taxon_locations.add(
                    (index.merges.get(row["subject"], row["subject"]), "biolink:located_in", target)
                )
        self.db.commit()
        self._seal_native_context()

    def _seal_native_context(self):
        """Retain an independent original native interpretation, never a restampable zero cache (#1337)."""
        from kg_microbe.transform_utils.gold.taxon_dispositions import _json

        original_index, original_db, original_historical = self.index, self.db, self.historical
        original_mapping = _json(original_historical)

        def context_digest():
            """Digest the complete parsed native context at a lifecycle checkpoint."""
            digest = hashlib.sha256()
            digest.update(
                _json(
                    {
                        "hierarchy": self.hierarchy,
                        "labels": self.labels,
                        "resolution": self.resolution,
                        "excluded_context": sorted(self.excluded_context),
                        "excluded": sorted(self.excluded),
                        "independent_taxon_locations": sorted(self.independent_taxon_locations),
                        "merges": original_index.merges,
                    }
                ).encode()
            )
            for query in (
                "SELECT id,native FROM fold_incidents ORDER BY id,native",
                "SELECT id,native FROM fold_context ORDER BY id",
                "SELECT id,native FROM fold_taxa ORDER BY id",
            ):
                for row in original_db.execute(query):
                    digest.update((_json(row) + "\n").encode())
            return digest.hexdigest()

        original_context = context_digest()
        failed = False

        def verify():
            """Reject changed native cohort bindings or evidence with sticky failure."""
            nonlocal failed
            if failed:
                raise SourceFinalizationRequired("GOLD restoration native context previously changed")
            try:
                unchanged = (
                    self.index is original_index
                    and self.db is original_db
                    and original_index.db is original_db
                    and self.historical is original_historical
                    and original_index.historical_folds is original_historical
                    and _json(original_historical) == original_mapping
                    and context_digest() == original_context
                )
            except (sqlite3.Error, TypeError, ValueError, AttributeError) as exc:
                failed = True
                raise SourceFinalizationRequired("GOLD restoration native context is no longer available") from exc
            if not unchanged:
                failed = True
                raise SourceFinalizationRequired("GOLD restoration native cohort or context changed")

        self.verify_native_context = verify

    def evidence(self, identifier):
        """Rejoin each full source observation and record its old and restored projections."""
        from kg_microbe.transform_utils.gold.taxon_dispositions import EDGE_HEADER, _association, _json

        if identifier not in self.historical:
            return None
        native_node = json.loads(
            self.db.execute("SELECT native FROM fold_context WHERE id=?", (identifier,)).fetchone()[0]
        )
        target = self.historical[identifier]
        selected_taxon = self.db.execute("SELECT native FROM fold_taxa WHERE id=?", (target,)).fetchone()
        if selected_taxon is None:
            raise SourceFinalizationRequired("Historical GOLD equality lacks its selected taxon declaration")
        incidents = [
            json.loads(row[0])
            for row in self.db.execute("SELECT native FROM fold_incidents WHERE id=? ORDER BY native", (identifier,))
        ]
        needed = {identifier}
        hierarchy = {}
        for item in incidents:
            needed.update((item["row"]["subject"], item["row"]["object"]))
        frontier = {node for node in needed if node.startswith("gold.ecosystem:")}
        visited = set()
        while frontier:
            node = frontier.pop()
            if node in visited:
                continue
            visited.add(node)
            for item in self.hierarchy.get(node, []):
                hierarchy[_json(item)] = item
                parent = item["row"]["object"]
                needed.add(parent)
                frontier.add(parent)
        context = {
            node: json.loads(self.db.execute("SELECT native FROM fold_context WHERE id=?", (node,)).fetchone()[0])
            for node in sorted(needed)
        }
        historical, restored, dispositions = [], [], []
        for item in incidents:
            row = item["row"]
            subject = self.index.merges.get(row["subject"], row["subject"])
            obj = self.index.merges.get(row["object"], row["object"])
            predicate, relation, original_object = row["predicate"], row.get("relation", ""), ""
            if {subject, obj, row["subject"], row["object"]} & self.excluded:
                dispositions.append({"native": item, "disposition": "unchanged_excluded_sample_study_or_trim_context"})
                continue
            if predicate == IN_TAXON_PREDICATE:
                emitted = _association(row, obj)
                restored.append(emitted)
                dispositions.append(
                    {
                        "native": item,
                        "disposition": "restore_source_taxon_association_without_identity",
                        "emitted": emitted,
                        "historical_emitted": None,
                    }
                )
                continue
            if predicate == "biolink:occurs_in":
                if obj in self.resolution:
                    original_object, obj = obj, self.resolution[obj]
                    if obj is None:
                        dispositions.append(
                            {"native": item, "disposition": "unchanged_root_only_environment_exclusion"}
                        )
                        continue
                predicate, relation = "biolink:located_in", "RO:0001025"
            emitted = dict(
                zip(
                    EDGE_HEADER,
                    (
                        subject,
                        predicate,
                        obj,
                        relation,
                        row.get("primary_knowledge_source", "") or "infores:gold",
                        KNOWLEDGE_ASSERTION,
                        MANUAL_AGENT,
                        original_object,
                    ),
                    strict=True,
                )
            )
            old = {**emitted, "subject": self.historical.get(subject, subject), "object": self.historical.get(obj, obj)}
            restored.append(emitted)
            historical.append(old)
            dispositions.append(
                {
                    "native": item,
                    "disposition": "restore_record_owned_observation",
                    "emitted": emitted,
                    "historical_emitted": old,
                }
            )
        return {
            "id": identifier,
            "disposition": "restore_source_referent_no_lexical_identity",
            "historical_fold_target": target,
            "native_node_json": _json(native_node),
            "selected_taxon_declaration_json": selected_taxon[0],
            "native_incident_assertions_json": _json(incidents),
            "native_context_declarations_json": _json(context),
            "native_ecosystem_hierarchy_json": _json([hierarchy[key] for key in sorted(hierarchy)]),
            "historical_emitted_claims_json": _json(historical),
            "restored_emitted_claims_json": _json(restored),
            "claim_dispositions_json": _json(dispositions),
        }

    def verify_graph(self, edges, *, quoting):
        """Conserve all restored source observations and remove only fold-generated taxon projections."""
        from kg_microbe.transform_utils.gold.taxon_dispositions import EDGE_HEADER, _json, _rows

        self.verify_native_context()

        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS restored_expected(id TEXT,row TEXT,PRIMARY KEY(id,row))")
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS restored_observed(id TEXT,row TEXT,PRIMARY KEY(id,row))")
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS restored_legacy("
            "subject TEXT,predicate TEXT,object TEXT,PRIMARY KEY(subject,predicate,object))"
        )
        self.db.execute("DELETE FROM restored_expected")
        self.db.execute("DELETE FROM restored_observed")
        self.db.execute("DELETE FROM restored_legacy")
        for identifier in sorted(self.historical):
            evidence = self.evidence(identifier)
            for row in json.loads(evidence["restored_emitted_claims_json"]):
                self.db.execute("INSERT OR IGNORE INTO restored_expected VALUES (?,?)", (identifier, _json(row)))
            for row in json.loads(evidence["historical_emitted_claims_json"]):
                triple = (row["subject"], row["predicate"], row["object"])
                if triple not in self.independent_taxon_locations and row["predicate"] == "biolink:located_in":
                    self.db.execute("INSERT OR IGNORE INTO restored_legacy VALUES (?,?,?)", triple)
        for item in _rows(edges, ("subject", "predicate", "object"), quoting=quoting):
            row = item["row"]
            if self.db.execute(
                "SELECT 1 FROM restored_legacy WHERE subject=? AND predicate=? AND object=?",
                (row["subject"], row["predicate"], row["object"]),
            ).fetchone():
                raise SourceFinalizationRequired("Fold-generated GOLD taxon environment assertion remains")
            for identifier in {row["subject"], row["object"]} & self.historical.keys():
                value = _json({key: row.get(key, "") for key in EDGE_HEADER})
                if not self.db.execute(
                    "SELECT 1 FROM restored_expected WHERE id=? AND row=?", (identifier, value)
                ).fetchone():
                    raise SourceFinalizationRequired("Unaudited restored GOLD source assertion")
                try:
                    self.db.execute("INSERT INTO restored_observed VALUES (?,?)", (identifier, value))
                except sqlite3.IntegrityError as error:
                    raise SourceFinalizationRequired("Duplicate restored GOLD source assertion") from error
        if self.db.execute(
            "SELECT id,row FROM restored_expected EXCEPT SELECT id,row FROM restored_observed"
        ).fetchone():
            raise SourceFinalizationRequired("Missing restored GOLD source observation")

    def counts(self):
        """Summarize native evidence separately from emitted graph multiplicity."""
        counts = Counter()
        for identifier in sorted(self.historical):
            evidence = self.evidence(identifier)
            for item in json.loads(evidence["claim_dispositions_json"]):
                counts[item["disposition"]] += 1
        return dict(counts)
