# KG-Microbe agent guide

KG-Microbe builds a microbial knowledge graph with a three-stage pipeline:
download, transform, then merge. This file contains only repository-wide rules.
Use the linked runbooks for operational history and source-specific details.

## Setup and checks

```bash
poetry install --with docs
poetry run kg --help
poetry run pytest
poetry run tox
poetry check --lock
python scripts/generate_merge_configs.py --check
```

Tox uses Ruff for formatting and linting. Run the relevant tests while editing
and the full `poetry run tox` suite before committing. Unit tests must not need
network access or modify `data/raw`; put small immutable inputs under
`tests/resources` and use `tmp_path` for output. Mark intentional live-service
coverage with `@pytest.mark.integration`.

The ontology transforms run the ROBOT pinned in `download.yaml`
(`kg download -t tools` puts `robot` and `robot.jar` in the raw directory)
rather than one from `PATH`, and need a working `java`; `kg transform` checks
both before running `ontologies_stubs`. SemSQL builds, whose Makefile calls
`robot` from `PATH`, get the pinned wrapper through a `PATH` shim
(`robot_utils.pinned_robot_on_path`). Every such call gets
`robot_utils.robot_java_args()`, which restores the seven JAXP limits JDK 24
lowered (they reject ChEBI and MicrO's imports, #325) unless the user sets them.
`rdftab` and `relation-graph`, which SemSQL also runs, are separate prerequisites.
Each build records its toolchain in `<db>.toolchain.json`; a reused `go.db` that
this machine's toolchain did not build is rebuilt, or refused when a tool is
missing (readers that open it directly refuse it, #1641), and other databases
only warn. See #1524 and the
[ontology-cache runbook](docs/runbooks/ontology-caches.md).

Supported Python versions are 3.10 through 3.12. Python 3.13 is blocked by the
KGX/pyarrow dependency chain; see issue #871.

## Pipeline commands

```bash
poetry run kg download
poetry run kg download -t ontologies -t gtdb
poetry run kg download -i -t mediadive
poetry run kg transform
poetry run kg transform -s bacdive -s mediadive
poetry run kg transform -s ec          # one ontology; withdraws the ontologies marker until a full rebuild
poetry run kg merge -y merge.yaml
make run-summary
```

`kg transform` checks every selected source's declared `DATA_INPUTS` before
running anything, isolates a failure to its source (later sources still run;
those that declare the failed one in `TRANSFORM_INPUTS` are skipped rather
than built on stale upstream output), and exits non-zero with a per-source
summary. `FatalOntologyError` and Ctrl-C still abort at once. See #685, #690.
An optional source with no input (Bakta without a `bakta/SAMN*` dataset under
`data/raw/bakta/`) is skipped in the default batch, along with anything that
depends on it through `TRANSFORM_INPUTS`, and its earlier fingerprint is
withdrawn so the merge refuses what a previous run left. Named with `-s`, it
fails preflight, since the requested output cannot be created, and its
fingerprint is withdrawn too. A raw directory that cannot be read is not a
skip: the source runs and fails in isolation.

`kg download` skips existing files, but a pin change now takes effect on its own: the URL behind each artifact is recorded in `data/raw/.download_manifest.json`, and a file whose declared URL has moved is re-fetched. A file with no record is left alone — unknown provenance is not wrong provenance (#911). `-i` still invalidates every selected entry, so always combine it with one or more `-t` tags. MediaDive invalidation also clears
its response cache and can trigger an approximately one-hour crawl.

The normal merge creates `data/merged/merged-kg.tar.gz` and removes the loose
TSVs. `make run-summary` accepts either that archive or extracted
`merged-kg_nodes.tsv` and `merged-kg_edges.tsv` files.

## Data flow and ownership

```text
download.yaml -> data/raw/
transform classes -> data/transformed/<source>/{nodes,edges}.tsv
merge.yaml -> data/merged/merged-kg.tar.gz + merged_graph_stats.yaml
```

`merged_graph_stats.yaml` carries a `provenance` block (when, commit, merge
config, each source's fingerprint digest, and a surviving artifact locator) and
`edge_stats.count_by_raw_predicate`, the predicate column counted as
written. KGX's own `count_by_predicates` resolves through Biolink and records
every METPO predicate as `None`. In the merged graph reviewed in #1055,
METPO predicates accounted for 50.09% of edges, not the roughly two-thirds
share measured before merging. The fraction is build-dependent; compare
predicates with the raw block. See #993, #1013 and #1055.
Compressed outputs use `edges_archive` plus `edges_archive_member`; only
uncompressed outputs use `edges_file`. The extracted working TSV is not a
published artifact.

- `download.yaml` owns upstream URLs and pinned versions.
- `kg_microbe/transform_utils/<source>/` owns source parsing and normalization.
- `kg_microbe/transform_utils/transform.py` owns the standard TSV headers.
- `merge.yaml` is the canonical merge specification.
- `config/merge_variants.yaml` contains only variant deltas. Never hand-edit a
  generated `merge*.yaml`; edit the canonical inputs and run
  `python scripts/generate_merge_configs.py`.
- Generated data belongs under `data/raw`, `data/transformed`, or `data/merged`
  and must not be committed. Curated mappings belong under `mappings/`.

## Transform contract

New transforms inherit from `Transform`, implement `run()`, use column and
source constants from `transform_utils/constants.py`, register lazily in
`kg_microbe/transform.py`, and add download and merge entries where applicable.
Imports used only by one CLI command must remain command-local so `kg --help`
and unrelated commands work offline.

Standard node columns are `id`, `category`, `name`, `description`, `xref`,
`provided_by`, `synonym`, `deprecated`, and `same_as`.

Standard edge columns are `subject`, `predicate`, `object`, `relation`,
`primary_knowledge_source`, `knowledge_level`, and `agent_type`. Source-specific
extension columns are allowed when the merge preserves them.

Finalization resolves the NCBITaxon and CHEBI nodes that a source references
but does not declare, unless the `ontologies` output already declares them.
- It declares them from the pinned taxdump or `chebi.db`.
- It rewrites merged taxids and replaced CHEBI terms.
- It drops edges to taxa outside the prokaryote trim and to obsolete CHEBI terms
  with no replacement.
- Two named MICRO and OBI terms come from `micro.owl` and `metpo.owl`.

Finalization reads the `ontologies` output only for a source that lists
`ontologies` in `TRANSFORM_INPUTS`. A source whose edges reference ontology terms
must therefore declare it; before #1511, its output depended on what else had
been built beside it. Completeness is checked where runs and publication happen.
`kg transform` refuses to start any source whose declared upstream has no
completion marker, unless the same run builds it. A single ontology removes the
ontologies marker until a full rebuild. The merge and `kgm-freshness-check` reject
output built without a completed upstream.

For this graph, a named strain or isolate beneath an NCBITaxon is typed
`biolink:OrganismTaxon` and linked with `biolink:subclass_of`. This deliberate
house convention means “sits under this taxon” and keeps the taxonomic backbone
traversable; it is not a claim that the isolate is an ontology class. Biolink
4.4.2 still gives `subclass_of` an `OntologyClass` domain/range, so strict
validators will report it; do not silently change the convention. See issue
#834 and [the 4.4.2 revalidation](docs/BIOLINK_4_4_2_REVALIDATION.md).

Cross-source organism joins use the **GTDB identifier**, not `ncbi_taxon_id`.
NCBI carries coarse placeholder taxa (`bacterium`, `uncultured bacterium`,
`Pseudomonadota bacterium`) that park unclassified sequence; GTDB names every
genome, so the bridge is many-to-one and pathologically concentrated — 0.3% of
NCBI taxa absorb 42.7% of the links, one of them 3,695 GTDB taxa. Joining
through NCBI pools unrelated species and produces fan-out that looks like
signal. A mapping edge onto a shared NCBI taxon is `biolink:broad_match`, not
`close_match`, and every shared taxon is listed worst-first in
`data/transformed/gtdb/gtdb_ncbi_pooling_report.tsv` — the deny-list to exclude
them deliberately rather than discovering them in a result set. See #883.

A `kgmicrobe.strain:<code>` node minted from a culture-collection deposit number
is shared: several source records can cite the same deposit, and they do not
always agree on the taxon. Such a node gets the one claimed parent that every
claimant entails — the claim itself when they agree, the shared ancestor when
they differ only in depth along one lineage. Never a computed common ancestor
nobody claimed, and never one of two disjoint claims: those get no parent at all
and go to the source's deposit-claim report, because picking one would make
the answer depend on file order. That report carries every deposit whose
claimants disagreed, whichever way it went, so a coarsened taxonomy and a
suppressed one are both visible and neither is confused with an ontology
lookup that failed. A record that cites a deposit links to it with
`biolink:close_match`, so the deposit's provenance is in the graph — but only
where the deposit kept a parent. `close_match` is symmetric and maps to
`SEMMEDDB:same_as`, so on a deposit whose claimants proved to be unrelated
organisms it would assert an equivalence between them; those citations stay in
the claims report, and the node carries a description saying so. See issues
#892, #894, #899 and #907. A deposit cited by a single record keeps that record's
link even with no parent, because one citer cannot equate two organisms. A
BacDive record whose ambiguous supplied taxids were withheld claims no parent, but
its candidates still contest one. A deposit it shares with any other record keeps
a parent only if every candidate is that taxon or lies beneath it. Otherwise the
deposit gets no parent and no record links (#1421).

## Operational traps

- PREGO defaults to `PREGO_SHAPES=habitat` and `PREGO_MIN_CONFIDENCE=0`.
  `PREGO_SHAPES=all` changes the output directory and graph size;
  `PREGO_MIN_CONFIDENCE` is a global cutoff, not a substitute for per-shape
  curation. Use `merge.noprego.yaml` when PREGO's size is not acceptable; see
  [the measured tradeoffs](docs/PREGO_SCORE_VALIDATION.md).
- GOLD applies the microbial NCBITaxon scope by default. Only set
  `GOLD_APPLY_TAXON_TRIM=false` for explicit debugging: it restores viral,
  plant, and animal branches that the ontology transform intentionally drops.
- MediaDive requires the selected media-list JSON (normally `mediadive.json`)
  and `mediadive/{media_detailed,media_strains,solutions,compounds}.json` under
  its selected raw directory. Missing, malformed, or changed inputs fail;
  YAML/HTTP caches are not a transform fallback. The old
  `KG_MEDIADIVE_ALLOW_STALE_CACHE` option no longer bypasses this requirement.
  Refresh the download and use a new producer instance after input changes.
  Deliberate API helper calls use an owned uncached `requests.Session`; old
  YAML/SQLite files are left untouched, never read or adopted. These live
  diagnostic calls do not authorize cache-only or API-only graph production.
- `KG_SEMSQL_BUILD=on` is the safe default. Turning it off reuses prebuilt
  ontology databases and accepts their version risk; follow the
  [ontology-cache runbook](docs/runbooks/ontology-caches.md).
- Cache existence must imply completeness. Use `atomic_write` from
  `kg_microbe.utils.atomic_io`, including completion markers where the helper
  requires them; never publish a partially written cache path.
- The merge checks invariants that no single transform can. A transform only
  polices the edges it writes, and `kgmicrobe.strain:*` is minted by several
  sources, so `merge_utils/invariants.py` re-checks after the merge and writes
  `merged_strain_parent_violations.tsv` beside the merged TSVs — empty on a
  clean run, because an absent report cannot be told from a check that never
  ran. It also writes `merged_stub_nodes.tsv`: KGX invents a node for any
  endpoint no source declared, so after a merge the question is not what is
  missing but what arrived as an invention. Expected exceptions are checked
  by identifier shape, not by a blanket GOLD/GTDB prefix exemption: a missing
  assembly or GOLD organism is unexpected even if other references in the
  same namespace are intentional. See #892, #896, #918, #1050 and #1051.
- GOLD no longer folds organism IDs onto taxa by normalized label (#1316).
  Unresolved native referents stay `biolink:NamedThing` with
  `biolink:related_to` taxon associations, backed by the mandatory
  `gold_taxon_dispositions.tsv`, `gold_lexical_fold_restorations.tsv` and
  `gold_selected_taxon_aliases.tsv` audits. MicrobeDecoder joins only the
  declarations admitted by the selected sibling GOLD's finalized bundle;
  `organism_folds.tsv` is header-only compatibility output and is not
  consumed. Regenerate GOLD before MicrobeDecoder; a missing or unfinalized
  GOLD bundle is an error, not permission to guess. See
  [GOLD unresolved referents](docs/GOLD_UNRESOLVED_REFERENTS.md).
- Merge assertion identity includes `relation` as well as subject, predicate,
  and object. Different original relations must retain separate source
  evidence; never split a merged relation list and copy its pooled provenance
  onto every resulting assertion. See #1054 and
  [merge integrity repairs](docs/MERGE_INTEGRITY_REPAIRS.md).
- Never assert a METPO term the pinned release has deprecated. A hardcoded CURIE
  keeps being emitted long after the ontology retires it — nothing errors, and
  `METPO:2000511` reached 706,765 edges that way. `tests/test_no_deprecated_metpo_terms.py`
  checks live code and transform output against the pinned `metpo.json`;
  `KNOWN_DEPRECATED` in `utils/metpo_liveness.py` is for terms with no live
  successor and every entry needs a tracking issue. See #909.
- Ontology acquisition or adapter failures abort the run. Do not catch them as
  per-row lookup failures, and construct/resolve adapters in the parent process
  before creating a `Pool`; adapters are large and generally not picklable.

## Adding a new transform

1. Create a `Transform` subclass with `run()`, standard headers, and declared
   `DATA_INPUTS` for every tracked curation file it reads.
2. Register it lazily in `kg_microbe/transform.py`; importing the CLI must not
   import its heavy or network-aware dependencies.
3. Add pinned downloads to `download.yaml`, merge inputs to the canonical merge
   specification, and regenerate all variants.
4. Add immutable unit fixtures, assert produced artifacts and CLI exit codes,
   and keep live upstream checks in marked integration tests.

## Reliability and safety rules

- Never put a token in a Git remote, generated file, command argument, or log.
  GitHub CLI reads `GH_TOKEN` from the environment.
- Fail commands with a nonzero exit code when requested output was not created.
- Write large derived databases and caches to a sibling temporary path, validate
  them, then replace the destination atomically.
- Fingerprint source inputs before reusing a derived database.
- Do not materialize graph-scale TSVs in Pandas; stream them or use DuckDB's
  direct CSV reader with explicit schemas.
- Do not catch ontology infrastructure failures as ordinary per-row lookup
  errors. `FatalOntologyError` subclasses `BaseException` intentionally.
- Resolve ontology adapters in the parent before starting process pools.
- Use `kg_microbe/utils/atomic_io.py` for caches whose existence implies they
  are complete.
- Preserve unrelated working-tree changes and never delete broad globs.

## Environment and model pins

Copy `.env.example` to `.env`. It is the canonical inventory of supported
environment variables, defaults, and risk warnings. Do not duplicate that
inventory here.

KGX/BMT must use the pinned local Biolink files downloaded to
`data/raw/biolink-model.yaml`, `data/raw/predicate_mapping.yaml`, and
`data/raw/attributes.yaml`. The last of these is not optional: the model
declares `imports: [linkml:types, attributes]` and linkml resolves `attributes`
as a sibling file, so without it the pinned model cannot be loaded at all. All
three move together — half a schema at one version is worse than either version
alone — and `tests/test_biolink_schema_pin.py` checks that `download.yaml`
fetches every file the shipped model imports, at one pinned tag. Updating the
Biolink version requires changing `download.yaml`, the lock file, fixtures, and
tests together. Each transform's `source_fingerprint.json` records the schema
it was built against, and `kgm-freshness-check` reports `STALE_VS_SCHEMA` when
the pinned model has moved since (#943). The marker also covers the shared
code every transform runs through (`kg_microbe/utils/`, `constants.py`,
`transform.py`), not only the transform's own package, and hashes by
repo-relative name so a marker reads the same from any checkout (#1002,
#983). When the fingerprint scheme changes, run
`poetry run python scripts/migrate_fingerprints.py` before trusting the table:
it rewrites markers that still hold and leaves stale ones for a real rerun.

A pin bump alone does not refresh `data/raw`. The 4.4.2 bump landed in August
2026 and the 4.3.6 file already on disk was never replaced, so every run since
validated against a version nothing declared; the download manifest then
recorded the 4.4.2 URL for it, which made the skew self-perpetuating. After
changing a pin, confirm the file on disk actually moved. See issues #937, #939
and #940.

METPO is pinned the same way. `METPO_VERSION` in `transform_utils/constants.py`
is the single source of truth, and the ontology (`metpo.owl`, `metpo.json`) and
the two ROBOT templates built from it must all move to the same tag together.
Never fetch METPO from `refs/heads/main`: an upstream obsoletion then arrives
with a download and changes nothing observable, which is how a deprecated
predicate reached 706,765 shipped edges. `tests/test_metpo_version_pin.py`
enforces this against `download.yaml`. See issues #900 and #909.

MicrO has no releases, so it is pinned to a commit (`MICRO_COMMIT` in
`constants.py`) together with the 20 modules `MicrO.owl` imports. PO is
pinned to a dated release (`PO_RELEASE`), downloaded with its two modules from
the commit the release tag points at (`PO_COMMIT`), and preflight checks that
`po.owl` declares that release.
`ontologies_stubs` resolves those imports through a generated ROBOT catalog
and runs ROBOT with HTTP(S) and SOCKS sent to a closed local port (no host
exempt, `_JAVA_OPTIONS` folded in first), so an unmapped import fails rather
than being fetched; preflight checks the modules are present and match what
each ontology imports. `tests/test_micro_version_pin.py` and
`tests/test_po_version_pin.py` check `download.yaml` against the constants.
The PO release must also be the one
`mappings/finite_envo_po_category_dispositions.json` was reviewed against, so
a PO bump means re-reviewing that policy.

Inputs that reviewed policies pin by their bytes are fetched the same way: from
a URL that names exactly one release (a dated release directory, a release asset
or a commit), never a rolling PURL or branch. `tests/test_reviewed_release_urls.py`
lists them, and each listed URL was checked to serve the bytes the policies pin.
Moving one to a newer release means re-reviewing every policy that binds it. Rhea
comes from its archived release tarball, whose two reviewed members keep their
byte pins. Some policy-bound inputs have no such URL (MeSH, NCIT, the LPSN GSS,
and the GOLD and BacDive files on Google Drive); this rule does not cover them.
Their policies bind only the records they reviewed (statements, GSS rows or
selected records): any export or release with those records unchanged is
accepted, and each run's receipt records the one it read. Before the
`ontologies` source starts, `kg transform` checks the release files the ontology
policies pin and the Biolink model; that an existing `ncit.db` has a SQLite header
and the unpacked size and CRC-32 of any `ncit.db.gz` beside it (no run replaces
it), or else that the archive unpacks to one; and that an existing `upa.json` is
the pinned conversion. A stale download then fails in seconds. A single ontology
(`-s go`) is checked for the pinned files its own run reads, `ontologies_stubs` and MediaDive for
`ncit.db`, and `python -m kg_microbe.utils.release_preflight data/raw` runs the check
alone. The other pins (Rhea's, MicrobeDecoder's, and the category pins MediaDive
and other sources meet) are checked when those sources run. See #1420 and the
[reviewed release inputs runbook](docs/runbooks/reviewed-release-inputs.md).

## Operational references

- [Data hosting and ontology build costs](docs/DATA_HOSTING.md)
- [Ontology cache and failure runbook](docs/runbooks/ontology-caches.md)
- [Reviewed release inputs and staging](docs/runbooks/reviewed-release-inputs.md)
- [PREGO score measurements](docs/PREGO_SCORE_VALIDATION.md)
- [PREGO acquisition and schema](docs/PREGO_INGEST_PLAN.md)
- [MetaTraits operations](docs/METATRAITS_TRANSFORM_RUNBOOK.md)
- [MicrobeDecoder operations](docs/MICROBEDECODER_TRANSFORM_RUNBOOK.md)

When a new invariant needs substantial history, measurements, or recovery
steps, add or update a versioned runbook and leave only the short rule here.
