# Ontology cache and failure runbook

Ontology adapters are resolved lazily. The first lookup may build or refresh a
SemSQL database from its pinned OWL input. Typical outputs and approximate costs
are:

| Database | Input | Approximate cost |
|---|---|---|
| `chebi.db` | `chebi.owl` | 30 minutes, 4 GB |
| `go.db` | `go.owl` | 10–30 minutes, 400 MB |
| `ec.db` | `ec.owl` | several minutes, 300 MB |
| `ncbitaxon.db` | `ncbitaxon.owl` | hours, 13 GB |

NCBITaxon can temporarily need roughly twice the database size plus the
decompressed OWL and relation graph. See [data hosting](../DATA_HOSTING.md) for
storage locations and build operations.

## Failure semantics

`OntologyDbUnavailableError` and `OntologyVersionMismatchError` derive from
`FatalOntologyError`, which derives from `BaseException`, not `Exception`. This
prevents broad per-record handlers from turning a missing or incompatible
ontology into a plausible-looking but systematically incorrect graph with exit
code zero.

Do not resolve an ontology proxy for the first time inside a
`multiprocessing.Pool` worker. A `BaseException` bypasses the pool's normal
worker exception path and can hang the pool. Perform readiness checks in the
parent process first; MetaTraits' NCBITaxon preflight is the reference pattern.

A failed GO rebuild does not reuse a release-mismatched database. Explicitly
setting `KG_SEMSQL_BUILD=off` is the operator-controlled exception: it skips
builds and permits an existing database with warnings. Corrupt SQLite files are
rebuilt even if they exceed the normal size floor.

## Recovery

1. Confirm the pinned OWL file exists and has enough free disk for a parallel
   temporary database.
2. Leave `KG_SEMSQL_BUILD` enabled and rerun the affected transform.
3. For a deliberate offline run using prebuilt databases, set
   `KG_SEMSQL_BUILD=off` and review every version warning.
4. Use `KG_GO_VERSION_CHECK`, `KG_NCBITAXON_VERSION_CHECK`, or
   `KG_CHEBI_VERSION_CHECK` to select `strict` or `warn` as documented in
   `.env.example`.

Derived caches whose existence signals completion must use
`kg_microbe/utils/atomic_io.py:atomic_write`. Never leave a partial cache at its
final path.
