"""
Own literal native-statement queries for BacDive taxon inference (#1364).

This reuses1361's owned-connection/locator/code/sidecar admission design by
subclassing it into a NEW instance, never borrowing a deposit child's session.
The base ancestry ledger remains empty; this child's direct native statement
queries have a separate contract composed into source-local taxonomy admission.
"""

import hashlib
import json
from pathlib import Path

from kg_microbe.transform_utils.bacdive.ancestry_authority import FreshAncestryAuthority
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

_SQL = {
    "label_batch": "SELECT * FROM statements WHERE predicate='rdfs:label'",
    "declaration": "SELECT * FROM statements WHERE subject=?",
}
_SYNONYM_PREDICATES = frozenset(
    {
        "oio:hasExactSynonym",
        "oio:hasRelatedSynonym",
        "oio:hasBroadSynonym",
        "oio:hasNarrowSynonym",
    }
)


def _encoded(value):
    """Canonicalize literal statement multisets without dropping duplicate native rows."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class FreshFallbackAuthority(FreshAncestryAuthority):
    """Own a distinct actual-read connection and an independent native-query ledger."""

    def __init__(self, selected_path, *, admission=None):
        """Initialize reviewed connection guards before making any native fallback query."""
        super().__init__(selected_path, admission=admission)
        implementation = Path(__file__).absolute()
        self._fallback_implementation = {"path": str(implementation), **self.admission.capture(implementation)}
        implementation_identity = _encoded(self._fallback_implementation)
        implementation_resolved = implementation.resolve()
        implementation_cache = _encoded(self.admission.identities[implementation_resolved])
        implementation_stamp = self.admission.stamps[implementation_resolved]
        sql_identity = _encoded(_SQL)
        native_sql = json.loads(sql_identity)
        cache, physical, demand = {}, [], []
        label_batch = None
        closed = False
        sealed = None

        def query(kind, value):
            """Keep cache bodies/physical reads hidden from mutable consumer-returned facts."""
            nonlocal closed
            try:
                if closed or self._failed or self._finished or self._closed:
                    raise SourceFinalizationRequired("BacDive native fallback query phase is not open")
                self._verify_files()
                if self._read_database_list() != self._database_list:
                    raise SourceFinalizationRequired("BacDive native fallback database attachments changed")
                self._verify_fallback_methods()
                if kind not in {"exact_label", "declaration"} or not isinstance(value, str) or not value:
                    raise SourceFinalizationRequired("BacDive native fallback query is unreviewed")
                key = (kind, value)
                cached = key in cache
                if kind == "exact_label" and not cached:
                    raise SourceFinalizationRequired("Native label query was not bound in the finite source-name batch")
                if not cached:
                    rows = [
                        dict(row) for row in self._connection.exec_driver_sql(native_sql[kind], (value,)).mappings()
                    ]
                    literal = _encoded(sorted(rows, key=_encoded))
                    cache[key] = literal
                    physical.append(
                        {
                            "kind": kind,
                            "parameter": value,
                            "sql": native_sql[kind],
                            "literal_rows": json.loads(literal),
                            "rows_sha256": hashlib.sha256(literal.encode()).hexdigest(),
                        }
                    )
                literal = cache[key]
                demand.append(
                    {
                        "kind": kind,
                        "parameter": value,
                        "cached": cached,
                        "rows_sha256": hashlib.sha256(literal.encode()).hexdigest(),
                    }
                )
                self._verify_files()
                return json.loads(literal)
            except BaseException:
                closed = True
                self._poison()
                raise

        def prime_labels(names):
            """
            Read native labels once, retaining only the exact admitted source query universe.

            The caller derives this finite string set from original source data
            and existing parser routes. It must be independently rederived at recorded
            admission, not accepted merely because this contract declares it.
            No full native name dictionary or database/index mutation is made.
            """
            nonlocal closed, label_batch
            try:
                self._verify_fallback_methods()
                if label_batch is not None or closed or self._failed or self._finished or self._closed:
                    raise SourceFinalizationRequired("Native fallback label batch cannot be prepared again")
                if not isinstance(names, (list, tuple)) or any(not isinstance(name, str) or not name for name in names):
                    raise SourceFinalizationRequired("Native label batch must contain actual nonempty text queries")
                wanted = tuple(sorted(set(names)))
                gathered = {name: [] for name in wanted}
                scanned = 0
                self._verify_files()
                if self._read_database_list() != self._database_list:
                    raise SourceFinalizationRequired("Native fallback database attachment changed")
                if wanted:
                    for row in self._connection.exec_driver_sql(native_sql["label_batch"]).mappings():
                        scanned += 1
                        if row["value"] in gathered:
                            gathered[row["value"]].append(dict(row))
                for name, rows in gathered.items():
                    cache[("exact_label", name)] = _encoded(sorted(rows, key=_encoded))
                label_batch = _encoded(
                    {
                        "queries": wanted,
                        "native_statements_scanned": scanned,
                        "sql": native_sql["label_batch"],
                        "literal_matches": {name: json.loads(cache[("exact_label", name)]) for name in wanted},
                    }
                )
                self._verify_files()
            except BaseException:
                closed = True
                self._poison()
                raise

        def snapshot():
            """Expose detached evidence only; the native memo bodies are closure-owned."""
            return {
                "physical_queries": json.loads(_encoded(physical)),
                "demands": json.loads(_encoded(demand)),
                "exact_label_batch": json.loads(label_batch) if label_batch is not None else None,
            }

        def finish_native():
            """Seal native-query evidence before retiring this child's owned connection."""
            nonlocal closed, sealed
            if closed or sealed is not None:
                raise SourceFinalizationRequired("BacDive native fallback batch already closed")
            self._verify_fallback_methods()
            closed = True
            connection = super(FreshFallbackAuthority, self).finish()
            if connection["computed_queries"]:
                raise SourceFinalizationRequired("Deposit-style computed queries entered the native fallback child")
            sealed = _encoded(
                {
                    "version": 1,
                    "connection": connection,
                    "native_query_implementation": self._fallback_implementation,
                    "query_mode": "literal_native_statements_not_materialized_entailment",
                    **snapshot(),
                }
            )
            self.admission.capture_resolution(lambda: (closed, sealed, _encoded(snapshot())))
            return json.loads(sealed)

        self._native_query = query
        self._prime_native_labels = prime_labels
        self._native_snapshot = snapshot
        self._finish_native = finish_native
        methods = (query, prime_labels, snapshot, finish_native)

        def verify_methods():
            """Clearing/replacing a query child cannot erase the originally owned obligations."""
            if (self._native_query, self._prime_native_labels, self._native_snapshot, self._finish_native) != methods:
                raise SourceFinalizationRequired("BacDive fallback native query methods were replaced")
            if _encoded(self._fallback_implementation) != implementation_identity:
                raise SourceFinalizationRequired("BacDive fallback native implementation binding changed")
            if (
                self.admission.bindings.get(implementation) != implementation_resolved
                or _encoded(self.admission.identities.get(implementation_resolved)) != implementation_cache
                or self.admission.stamps.get(implementation_resolved) != implementation_stamp
            ):
                raise SourceFinalizationRequired("Original fallback-reader implementation admission was lost")
            if _encoded(_SQL) != sql_identity:
                raise SourceFinalizationRequired("BacDive fallback native SQL definitions changed")
            return tuple(id(method) for method in methods), implementation_identity

        self._verify_fallback_methods = verify_methods
        original_verify = verify_methods
        self.admission.capture_resolution(lambda: (id(self._verify_fallback_methods), original_verify()))

    def declaration(self, identifier):
        """Return every literal statement about a requested candidate or asserted ancestor."""
        self._verify_fallback_methods()
        return self._native_query("declaration", identifier)

    def prime_exact_labels(self, names):
        """Prepare at most one exact-name label stream for this independently owned batch."""
        self._verify_fallback_methods()
        return self._prime_native_labels(names)

    def exact_label_candidates(self, label):
        """Retain all exact native labels, not OAK first-result order or synonym guesses."""
        self._verify_fallback_methods()
        rows = self._native_query("exact_label", label)
        return sorted({row["subject"] for row in rows if not row["subject"].startswith("_:")})

    def candidate_facts(self, identifier):
        """Rejoin class/rank and asserted native ancestry, not a generic computed closure."""
        try:
            return self._candidate_facts(identifier)
        except BaseException:
            self._poison()
            raise

    def _candidate_facts(self, identifier):
        """Require complete live class/parent witnesses before deriving eligibility."""
        seen, stack, declarations = set(), [identifier], {}
        while stack:
            subject = stack.pop()
            if subject in seen:
                continue
            seen.add(subject)
            rows = self.declaration(subject)
            if not rows or {row["object"] for row in rows if row["predicate"] == "rdf:type"} != {"owl:Class"}:
                raise SourceFinalizationRequired("Native fallback ancestor lacks its actual class declaration")
            declarations[subject] = rows
            stack.extend(
                row["object"]
                for row in rows
                if row["predicate"] == "rdfs:subClassOf"
                and isinstance(row["object"], str)
                and row["object"].startswith("NCBITaxon:")
            )
        active, complete = set(), set()

        def validate_ancestry(subject):
            """Allow a repeated DAG ancestor, but reject a directed cycle as lineage proof."""
            if subject in active:
                raise SourceFinalizationRequired("Native fallback asserted parent graph contains a cycle")
            if subject in complete:
                return
            active.add(subject)
            for row in declarations[subject]:
                if row["predicate"] == "rdfs:subClassOf":
                    parent = row["object"]
                    if not isinstance(parent, str) or not parent.startswith("NCBITaxon:"):
                        raise SourceFinalizationRequired("Native fallback parent is not a named NCBI class")
                    validate_ancestry(parent)
            active.remove(subject)
            complete.add(subject)

        validate_ancestry(identifier)
        rows = declarations[identifier]
        labels = sorted({row["value"] for row in rows if row["predicate"] == "rdfs:label" and row["value"] is not None})
        ranks = sorted(
            {
                row["object"].split(":", 1)[-1]
                for row in rows
                if row["predicate"] == "obo:ncbitaxon#has_rank" and row["object"]
            }
        )
        types = sorted({row["object"] for row in rows if row["predicate"] == "rdf:type"})
        obsolete = [row for row in rows if row["predicate"] == "owl:deprecated"]
        if any(str(row["value"]).lower() not in {"true", "false", "1", "0"} for row in obsolete):
            raise SourceFinalizationRequired("Malformed native deprecation statement")
        return {
            "id": identifier,
            "labels": labels,
            "ranks": ranks,
            "types": types,
            "deprecated": any(str(row["value"]).lower() in {"true", "1"} for row in obsolete),
            "synonyms": sorted(
                {
                    row["value"]
                    for row in rows
                    if row["predicate"] in _SYNONYM_PREDICATES and isinstance(row["value"], str)
                }
            ),
            "ancestors": sorted(seen - {identifier}),
            "complete_native_declarations": declarations,
        }

    def finish_fallback(self):
        """Return this child's independent complete query contract, not a deposit contract."""
        self._verify_fallback_methods()
        return self._finish_native()
