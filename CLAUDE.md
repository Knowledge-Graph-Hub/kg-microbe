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

Supported Python versions are 3.10 through 3.12. Python 3.13 is blocked by the
KGX/pyarrow dependency chain; see issue #871.

## Pipeline commands

```bash
poetry run kg download
poetry run kg download -t ontologies -t gtdb
poetry run kg download -i -t mediadive
poetry run kg transform
poetry run kg transform -s bacdive -s mediadive
poetry run kg merge -y merge.yaml
make run-summary
```

`kg download` skips existing files; `-i` invalidates every selected entry, so
always combine it with one or more `-t` tags. MediaDive invalidation also clears
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

For this graph, a named strain or isolate beneath an NCBITaxon is typed
`biolink:OrganismTaxon` and linked with `biolink:subclass_of`. This deliberate
house convention means “sits under this taxon” and keeps the taxonomic backbone
traversable; it is not a claim that the isolate is an ontology class. Biolink
4.4.2 still gives `subclass_of` an `OntologyClass` domain/range, so strict
validators will report it; do not silently change the convention. See issue
#834 and [the 4.4.2 revalidation](docs/BIOLINK_4_4_2_REVALIDATION.md).

A `kgmicrobe.strain:<code>` node minted from a culture-collection deposit number
is shared: several source records can cite the same deposit, and they do not
always agree on the taxon. Such a node gets the one claimed parent that every
claimant entails — the claim itself when they agree, the shared ancestor when
they differ only in depth along one lineage. Never a computed common ancestor
nobody claimed, and never one of two disjoint claims: those get no parent at all
and go to the source's deposit-conflict report, because picking one would make
the answer depend on file order. Every record that cites a deposit links to it
with `biolink:close_match`, so the deposit's provenance is in the graph and its
taxonomy stays reachable through the record even when no parent is asserted.
See issues #892 and #894.

## Operational traps

- PREGO defaults to `PREGO_SHAPES=habitat` and `PREGO_MIN_CONFIDENCE=0`.
  `PREGO_SHAPES=all` changes the output directory and graph size;
  `PREGO_MIN_CONFIDENCE` is a global cutoff, not a substitute for per-shape
  curation. Use `merge.noprego.yaml` when PREGO's size is not acceptable; see
  [the measured tradeoffs](docs/PREGO_SCORE_VALIDATION.md).
- GOLD applies the microbial NCBITaxon scope by default. Only set
  `GOLD_APPLY_TAXON_TRIM=false` for explicit debugging: it restores viral,
  plant, and animal branches that the ontology transform intentionally drops.
- MediaDive rejects stale response caches by default. Setting
  `KG_MEDIADIVE_ALLOW_STALE_CACHE=true` is an explicit reproducibility waiver;
  outputs may no longer match the current recipe list.
- `KG_SEMSQL_BUILD=on` is the safe default. Turning it off reuses prebuilt
  ontology databases and accepts their version risk; follow the
  [ontology-cache runbook](docs/runbooks/ontology-caches.md).
- Cache existence must imply completeness. Use `atomic_write` from
  `kg_microbe.utils.atomic_io`, including completion markers where the helper
  requires them; never publish a partially written cache path.
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
`data/raw/biolink-model.yaml` and `data/raw/predicate_mapping.yaml`. Updating the
Biolink version requires changing `download.yaml`, the lock file, fixtures, and
tests together.

## Operational references

- [Data hosting and ontology build costs](docs/DATA_HOSTING.md)
- [Ontology cache and failure runbook](docs/runbooks/ontology-caches.md)
- [PREGO score measurements](docs/PREGO_SCORE_VALIDATION.md)
- [PREGO acquisition and schema](docs/PREGO_INGEST_PLAN.md)
- [MetaTraits operations](docs/METATRAITS_TRANSFORM_RUNBOOK.md)
- [MicrobeDecoder operations](docs/MICROBEDECODER_TRANSFORM_RUNBOOK.md)

When a new invariant needs substantial history, measurements, or recovery
steps, add or update a versioned runbook and leave only the short rule here.
