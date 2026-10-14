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

### Toolchain records (#1524)

Every successful `semsql make` writes `<db>.toolchain.json` beside the database:
the SemSQL version (as its own interpreter reports it), the `rdftab` binary's
SHA-256 (it reports no version), the `relation-graph` version with a digest of
every jar it runs (which covers its bundled Whelk reasoner), the pinned
`robot.jar` SHA-256, and, for provenance only, the first line of `java -version`.
Paths and Java are recorded but not compared. A build that produces no usable
database removes the old record; a failed build that restores the old database
keeps it.

When a database is reused at the right release, its record is compared with this
machine's toolchain:

- **`go.db` is strict.** GO's restriction policy refuses a quarantined restriction
  once `entailed_edge` supports it, and `entailed_edge` comes from relation-graph,
  so the same GO release built by another relation-graph can change outcomes. A
  missing or different record rebuilds `go.db` (about a minute). If this machine
  lacks `semsql`, `rdftab`, `relation-graph` or the pinned `robot.jar`, the
  database can be neither rebuilt nor vouched for, so it is not used and the
  message names what is missing. Databases built before #1524 have no record, so
  each machine rebuilds `go.db` once.
- **The others warn.** `chebi.db`, `ncbitaxon.db` and `ec.db` take far longer to
  rebuild, so a missing or different record prints one warning per database per
  process and the database is used.
- **`KG_SEMSQL_BUILD=off`** skips both: it accepts the prebuilt databases and
  whatever toolchain made them.

The release binaries used on the M1 build recorded in #1524 are `rdftab` v0.1.1
(`rdftab-x86_64-apple-darwin`, SHA-256 `4087e519…`, which needs Rosetta on Apple
silicon) and `relation-graph` 2.3.2 (`relation-graph-cli-2.3.2.tgz`, put its `bin/`
on `PATH`). Matching them keeps one machine's `go.db` record valid on another.

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
