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
the SemSQL version (as its own interpreter reports it, through an absolute, `env`
or pip-trampoline shebang), the `rdftab` binary's SHA-256 (it reports no version),
the `relation-graph` version with a digest of every jar it runs (which covers its
bundled Whelk reasoner), the pinned ROBOT's `robot.jar` SHA-256 (only when its
`robot` wrapper is beside it, since that is what puts it on `PATH`), and, for
provenance only, the first line of `java -version`. Paths and Java are recorded
but not compared.

The record also names the database file it describes (size, modification time,
inode). A database copied in, replaced by hand or restored from `.prev` is
therefore another file, and the record no longer vouches for it; there is no need
to delete the record when replacing a database. A tool whose version or digest
cannot be read (a `relation-graph` wrapper with no release `lib/` beside it, or a
`semsql` whose interpreter cannot be found) cannot vouch for a database either. A
build that produces no usable database removes the old record, and a record that
cannot be written is reported without discarding the build.

When a database is reused at the right release, its record is compared with this
machine's toolchain:

- **`go.db` is strict.** GO's restriction policy refuses a quarantined restriction
  once `entailed_edge` supports it, and `entailed_edge` comes from relation-graph,
  so the same GO release built by another relation-graph can change outcomes. A
  missing or different record rebuilds `go.db` (about a minute on the M1). If this
  machine lacks `semsql`, `rdftab`, `relation-graph` or the pinned ROBOT, or cannot
  identify one of them, the database can be neither rebuilt nor vouched for, so it
  is not used and the message names what is missing. GO's consumers then raise
  `OntologyDbUnavailableError`, a `FatalOntologyError`, so the whole `kg transform`
  run stops at the first source that needs GO. Databases built before #1524 have
  no record, so each machine rebuilds `go.db` once.
- **The others warn.** `chebi.db`, `ncbitaxon.db` and `ec.db` take far longer to
  rebuild, so a missing or different record prints one warning per database per
  process and the database is used.
- **Readers that open a database directly check it too, and never rebuild it**
  (#1641). UPA (`kg transform -s upa`) and Rhea mappings read `go.db`, and Rhea
  also reads `chebi.db` and `ec.db`, without going through `_ensure_go_db`. A
  `go.db` this toolchain did not build is refused there with
  `OntologyDbUnavailableError`; run the go ontology (`kg transform -s go`) to
  rebuild it. The others warn, as above. A reader does not rebuild, so that it
  cannot race a build another process holds the lock for.
- **`KG_SEMSQL_BUILD=off`** skips both: it accepts the prebuilt databases and
  whatever toolchain made them. It also stops every SemSQL database from being
  rebuilt on release drift.

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
