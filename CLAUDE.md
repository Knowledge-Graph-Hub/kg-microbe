# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KG-Microbe is a knowledge graph construction project for microbial traits and beyond. It integrates multiple data sources (BacDive, MediaDive, UniProt, CTD, etc.) with ontologies (NCBITaxon, ChEBI, GO, ENVO, etc.) to create a comprehensive knowledge graph of microbial organisms, their traits, growth media, metabolic pathways, and associated chemical compounds.

The project follows a three-stage pipeline: **Download → Transform → Merge**

## Core Commands

### Development Setup
```bash
pip install poetry
poetry install
```

### Main Pipeline Commands
```bash
# Download all data sources (configured in download.yaml)
poetry run kg download

# Download only selected source groups (tags are listed in download.yaml's header)
poetry run kg download -t ontologies -t gtdb

# Re-download a single file: delete it and re-run. `kg download` only fetches
# files that are absent — it never checks whether the remote copy is newer.
# `-i` ignores the cache for EVERY entry, so scope it with -t. Note that for
# mediadive this also clears the HTTP response cache and re-runs the full
# ~1h bulk API crawl, so it is not a cheap single-file refresh:
poetry run kg download -i -t mediadive

# Transform downloaded data into KG format (TSV: nodes.tsv, edges.tsv)
poetry run kg transform

# Transform specific sources only
poetry run kg transform -s bacdive -s mediadive

# Merge all transformed graphs (configured in merge.yaml or merge.minimal.yaml)
poetry run kg merge -y merge.yaml
```

### Testing and Quality Checks
```bash
# Run all quality checks before committing (REQUIRED before every commit)
poetry run tox

# Run specific test suites
poetry run pytest                    # Run all tests
poetry run pytest tests/test_file.py # Run specific test file

# Individual quality checks
poetry run tox -e format             # Format code (black + ruff --fix)
poetry run tox -e lint               # Check code style
poetry run tox -e codespell-write    # Fix spelling errors
poetry run tox -e docstr-coverage    # Check documentation coverage
```

### Summary Statistics
```bash
make run-summary  # Generate node and edge counts by category
```

### Machine Learning and Queries
```bash
# Generate holdout sets for ML training (splits graph into train/test/validation)
poetry run kg holdouts -n data/merged/nodes.tsv -e data/merged/edges.tsv -o data/holdouts/

# Run SPARQL queries against the knowledge graph
poetry run kg query -y queries/sparql/example_query.yaml -o data/queries/
```

### Neo4j Upload (optional)
```bash
make neo4j-upload  # Upload merged KG to local Neo4j instance
```

## Architecture

### Pipeline Stages

1. **Download** (`kg_microbe/download.py`)
   - Downloads resources defined in `download.yaml`
   - Sources stored in `data/raw/`
   - Uses `kghub-downloader` library

2. **Transform** (`kg_microbe/transform.py`)
   - Each data source has its own transform class in `kg_microbe/transform_utils/[source_name]/`
   - All transform classes inherit from `Transform` base class (`transform_utils/transform.py`)
   - Each transform produces `nodes.tsv` and `edges.tsv` in `data/transformed/[source_name]/`
   - Node/edge headers defined in base `Transform` class using constants from `constants.py`

3. **Merge** (`kg_microbe/merge_utils/merge_kg.py`)
   - Uses KGX library to merge transformed graphs
   - Configuration in `merge.yaml` or `merge.minimal.yaml`
   - Outputs to `data/merged/` as TSV (optionally tar.gz compressed)
   - Generates graph statistics in `merged_graph_stats.yaml`

### Transform Architecture

All transform classes follow this pattern:
- Located in `kg_microbe/transform_utils/[source_name]/`
- Class name: `[SourceName]Transform` (e.g., `BacDiveTransform`, `MediaDiveTransform`)
- Registered in `DATA_SOURCES` dict in `kg_microbe/transform.py`
- Implement `run()` method from base `Transform` class
- Output standard KGX TSV format (nodes.tsv, edges.tsv)

Key transform sources (currently active in DATA_SOURCES):
- **bacdive**: Bacterial diversity data (taxon traits, growth media, metabolic properties)
- **mediadive**: Growth media composition data
- **madin_etal**: Condensed bacterial/archaeal traits from literature
- **bactotraits**: Bacterial trait data
- **microbedecoder**: Bergey / VPI / literature-curated / FAPROTAX fermentation profiles per LPSN strain, plus a pre-joined LPSN ↔ GTDB ↔ NCBI ↔ GOLD ↔ IMG ↔ BacDive identity crosswalk (Hackmann & Zhang, Sci Adv 2023; CC BY 4.0). Emits edges only against existing `lpsn:<LPSN_ID>` nodes — needs the `lpsn` transform present alongside for organism identity.
- **ontologies**: OBO ontologies (ENVO, ChEBI, GO, NCBITaxon, MONDO, HP, EC)
- **rhea_mappings**: Rhea reaction mappings to GO and EC

Additional available transforms (commented out in DATA_SOURCES):
- **uniprot_functional_microbes**: Protein data for functional microbes
- **ctd**: Comparative Toxicogenomics Database
- **disbiome**: Microbiome-disease associations
- **wallen_etal**: Additional bacterial trait data
- **uniprot_human**: Human protein data

### Key Files

- `kg_microbe/run.py`: CLI entry point with Click commands
- `kg_microbe/transform_utils/constants.py`: Standard column names (ID_COLUMN, CATEGORY_COLUMN, etc.) and entity-type translation tables (`TRANSLATION_TABLE_FOR_IDS` / `TRANSLATION_TABLE_FOR_LABELS`, applied via `str.maketrans`)
- `kg_microbe/transform_utils/custom_curies.yaml`: Custom CURIE prefix mappings
- `pyproject.toml`: Poetry configuration, ruff/black settings

### Data Flow

```
download.yaml → data/raw/[source].json/csv/owl
                      ↓
              Transform Classes
                      ↓
        data/transformed/[source]/nodes.tsv
        data/transformed/[source]/edges.tsv
                      ↓
                merge.yaml
                      ↓
            data/merged/merged-kg.tar.gz
```

## Important Notes

### Memory Requirements
The KG construction process is computationally intensive, particularly:
- Trimming NCBI Taxonomy
- Processing microbial UniProt datasets (for KG-Microbe-Function and KG-Microbe-Biomedical-Function)

Successful execution may require significant memory resources (e.g., >500 GB RAM for certain operations).

### Multiprocessing Support

**MetaTraits transforms** (both `metatraits` and `metatraits_gtdb`) now support parallel processing to significantly reduce runtime:

**Performance:**
- **Sequential mode**: 5-8 hours for GTDB metatraits (85K taxa)
- **Parallel mode**: 1.5-2.5 hours (2-3x speedup)

**Configuration:**
- **Auto-enabled**: Multiprocessing is ON by default when either (a) 2+ input files exist, or (b) a single large input file is internally chunk-split
- **Auto-scaled**: Worker count automatically adjusted based on CPU cores and available memory (3GB per worker)
- **Environment variables**:
  ```bash
  # Disable multiprocessing
  METATRAITS_MULTIPROCESSING=false poetry run kg transform -s metatraits

  # Override worker count
  METATRAITS_WORKERS=4 poetry run kg transform -s metatraits
  ```

**Resource requirements:**
- Each worker needs ~3GB RAM (for OAK adapter + processing)
- Uses N-1 CPU cores by default (leaves 1 for system)
- Example: 8-core system with 24GB RAM → 4 parallel workers

### Pre-commit Requirement
**ALWAYS run `poetry run tox` before every commit** to ensure code quality. This runs all quality checks: format, lint, codespell, docstr-coverage, and tests.

### Environment Variables
Copy `.env.example` to `.env` and configure:
- `BACDIVE_USERNAME`: BacDive API email
- `BACDIVE_PASSWORD`: BacDive API password

Optional, for the mediadive transform:
- `KG_MEDIADIVE_ALLOW_STALE_CACHE=true`: run mediadive even when the bulk
  download in `data/raw/mediadive/` is absent or incomplete. Off by default:
  without the bulk JSONs the transform falls back to the YAML medium cache
  under `transform_utils/mediadive/tmp/medium_yaml` and to `requests_cache`,
  neither of which has an expiry, so a run started before `kg download`
  finishes exits 0 having built the graph from years-old recipes. Set this only
  for deliberate offline / cache-only work. It must be a **shell** variable —
  `load_dotenv()` is not guaranteed to have run on the transform path, so an
  `.env` entry is not reliable here.

Optional, for the ontology transforms:
- `KG_SEMSQL_BUILD=off`: skip building the SemSQL lookup DBs. Any transform that
  looks something up in an ontology resolves its adapter through
  `ontology_utils.get_*_adapter()`, which builds the DB from the OWL if it is
  missing or has drifted from the OWL's release:

  | DB | built from | rough cost | triggered by |
  |---|---|---|---|
  | `chebi.db` | `chebi.owl` | ~30 min, ~4 GB | ontologies, bacdive, madin_etal, rhea_mappings, NER |
  | `go.db` | `go.owl` | 10-30 min, ~400 MB | ontologies, bacdive, rhea_mappings, bakta, uniprot_*, NER |
  | `ec.db` | `ec.owl` | a few min, ~300 MB | rhea_mappings |
  | `ncbitaxon.db` | `ncbitaxon.owl` | hours, ~13 GB | metatraits, bacdive, bactotraits, lpsn |

  Resolution is lazy — constructing a transform costs nothing; the build happens
  on first lookup. With the opt-out set, whatever DB is already on disk is used
  and the version gate warns about any mismatch. Peak disk for the NCBITaxon
  build is roughly old + new (~28 GB) plus the decompressed `ncbitaxon.owl`
  (~2 GB) and a relation-graph intermediate.

  The NCBITaxon drift rebuild runs from the metatraits pre-flight regardless of
  MP mode — sequential runs (`METATRAITS_MULTIPROCESSING=false` or a single
  unsplit input) invoke the same pre-flight, so #614's warn-and-continue on
  release drift is closed there too. Other transforms resolve NCBITaxon on
  demand and will build it if it is absent.

- `KG_GO_VERSION_CHECK` / `KG_NCBITAXON_VERSION_CHECK` / `KG_CHEBI_VERSION_CHECK`:
  `strict` (raise) or `warn`. GO defaults to strict because a mismatch silently
  miscategorises terms; the other two default to warn.

- `PREGO_MIN_CONFIDENCE`: star threshold in `[0, 4]` applied to the PREGO
  transform. Default `0` — a no-op that emits all ~44.7 M edges, so unset
  behaviour is unchanged. **This is a size lever, not a quality filter.** See
  the table below before setting it.

  PREGO's score is not one scale, so the knob does not mean the same thing in
  every channel (`docs/PREGO_SCORE_VALIDATION.md` has the measurements):

  | channel | share | what the threshold does |
  |---|---|---|
  | `environmental_samples` | ~53% | Genuine ranking. Retains about `1 - τ/4` of each resource, by within-resource empirical CDF. |
  | `annotated_genomes_isolates` | ~47% | Near all-or-nothing. Predominantly a flat 4.0 assigned by PREGO's authors, so `τ ≤ 4` keeps essentially the whole channel — but see the caveat below. |
  | `literature` | ~0.05% | All-or-nothing. Flat 3.0, so the entire channel vanishes the moment `τ > 3`. |

  The genome channel is *not* uniformly 4.0. Sampled across the real 8.68 GB
  payload, roughly 0.1% of rows carry a 3 — and not only PMID-evidenced ones;
  `Isolates` and `Single Amplified Genome` rows appear at 3 too. Because
  `star_for_row` deliberately uses each flat row's **own** score rather than its
  channel's documented constant (so a row disagreeing with its tier is kept as a
  data-quality signal instead of being silently promoted), those rows drop once
  `τ > 3` — on the order of 20k edges.

  **That 0.1% is not spread evenly, and "incidental" is the wrong reading.** It
  is a whole-channel average dominated by the 44.3M `capable_of` edges. Counted
  on the habitat shapes alone (measured 2026-08-10, full `edges.tsv`), the genome
  channel is 33.3% score-3 for ENVO (12,562 of 37,749) and 80.5% for BTO (5,360
  of 6,661) — no value other than 3 or 4 occurs. Those 17,922 rows are ~89% of
  the ~20k above, so **`τ > 3` deletes 4.0% of all habitat edges**, and the
  habitat data is where PREGO has measured enrichment (7.89x unfiltered for
  ENVO). See `docs/PREGO_SCORE_VALIDATION.md` for the habitat threshold
  recommendation, which keeps this channel whole.

  Two consequences worth internalising. Above `τ = 3` you delete the literature
  channel outright — on provenance, not on quality. And within the continuous
  channel the score tracks how *common* a GO term is rather than how well
  supported it is: measured Spearman +0.2592 of term degree against mean score,
  with mean score climbing steeply across the bottom three deciles (0.67 → 1.98)
  then flat at ~2.0 for the rest. So raising `τ` strips the rare,
  taxon-specific tail first and barely discriminates within the bulk — the
  opposite of what you want if the goal is to keep specific, informative edges.
  Full decile table in `docs/PREGO_SCORE_VALIDATION.md`; reproduce with
  `scripts/prego_validation/ubiquity_check.py`.

  An unrecognised channel is kept rather than dropped, so a newly added or
  renamed archive fails open — the transform warns when it sees one.

  Calibration is per-resource (MGnify and MG-RAST have different marginals) and
  runs as a first pass over the archives; each run writes the cutoffs it
  actually applied to `data/transformed/prego/confidence_calibration.tsv`. The
  channel is derived from the **archive filename**, not from any column.

- `PREGO_SHAPES`: `all` (default) or `habitat`. `habitat` emits only the
  `location_of` shapes (ENVO/BTO → taxon) — ~238k edges against 44.7M, a 55 MB
  `edges.tsv` instead of 12.2 GB. PREGO's taxon→GO edges are 99% of the source
  by volume and have no positive evidence in any of the four gold standards,
  while the habitat edges are 7.89x enriched against BacDive isolation and
  replicate at 2.01x against the independent Madin standard.

- `PREGO_HABITAT_MIN_SCORE`: raw-score floor for *continuous-channel* habitat
  rows, default `1.0`, applied only when `PREGO_SHAPES=habitat`. The genome
  channel is kept whole deliberately: its habitat scores are only ever 3 or 4,
  so a star threshold would delete 4% of habitat on provenance rather than
  quality. Set `0` to disable. See `docs/PREGO_SCORE_VALIDATION.md`.

  Standard merges use `merge.habitat.yaml` (habitat-only PREGO) or
  `merge.noprego.yaml` (no PREGO); `merge.yaml` keeps the full source for
  experimental builds.

  **If your goal is merge memory or graph size, reach for `merge.noprego.yaml`
  first** — it drops PREGO entirely (~76% of merge input) and needs none of this
  machinery. `PREGO_MIN_CONFIDENCE` is the finer-grained alternative for when
  you want *some* PREGO rather than none.

### Ontology failures abort; they do not degrade

`OntologyDbUnavailableError` (no usable DB) and `OntologyVersionMismatchError` (a
strict gate tripping) both derive from `FatalOntologyError`, which derives from
**`BaseException`, not `Exception`**. This is deliberate. Adapters resolve
lazily, so the failure surfaces wherever a transform first touches the adapter —
almost always inside a `try` whose `except Exception` was written to absorb a
per-item lookup miss. Swallowed, that produced a systematically wrong graph with
a zero exit code: every ChEBI node `biolink:ChemicalEntity`, every GO term
`molecular_function`, every label a bare numeric ID, every protein→GO edge
dropped.

Consequences to know:

- **Do not wrap adapter use in `except Exception` expecting to degrade.** You
  cannot catch these that way, by design. Catch the specific class if a fallback
  is genuinely correct — `get_chebi_category` does this for the standalone
  no-DB case, and only for that case.
- **Never resolve one of these proxies inside a `multiprocessing.Pool` worker.**
  A `BaseException` is not caught by the worker loop and can hang the pool.
  Metatraits resolves NCBITaxon eagerly in the parent
  (`_ensure_ncbitaxon_db_ready`) via its own module-local adapter for exactly
  this reason; that is a documented exception to "everything goes through
  `get_ontology_adapter`", not an oversight.
- **A GO rebuild that fails now refuses the old DB.** GO passes
  `reuse_on_failure=False`, so with no `semsql` on PATH and a `go.db` that has
  drifted from `go.owl`, GO-dependent transforms abort instead of running on
  stale categories. An explicit `KG_SEMSQL_BUILD=off` is exempt — a deliberate
  opt-out always reuses what is on disk.
- **A DB that clears its size floor but is not openable SQLite is rebuilt**, not
  reused, for all four ontologies.

Derived caches guarded by a bare `path.exists()` are written through
`kg_microbe/utils/atomic_io.py:atomic_write` (temp file + `os.replace`), so a
failed run leaves no truncated file for the next run to accept as complete. Use
it for any new cache of that shape.

## Naming Conventions

- Transform classes: `[SourceName]Transform` in `transform_utils/[source_name]/[source_name].py`
- Source name constants: Uppercase in `transform_utils/constants.py` (e.g., `BACDIVE = "bacdive"`)
- Output files: Always `nodes.tsv` and `edges.tsv` per source
- Column names: Use constants from `constants.py` (e.g., `SUBJECT_COLUMN`, `PREDICATE_COLUMN`, `OBJECT_COLUMN`)

## Code Style

- Line length: 120 characters (ruff), 100 characters (black)
- Python: ≥3.10
- Linting: ruff with pydocstyle (D), pycodestyle (E), Pyflakes (F), isort (I), flake8-bandit (S)
- Type hints required for function signatures
- Docstrings required (checked by `docstr-coverage`)

## Testing

Tests in `tests/` directory:
- `test_transform_class.py`: Transform class tests
- `test_transform_utils.py`: Transform utility tests
- `test_run.py`: CLI command tests
- `test_query.py`: SPARQL query tests

Test resources in `tests/resources/`

## Common Patterns

### Adding a New Transform

1. Create directory: `kg_microbe/transform_utils/[new_source]/`
2. Create transform class inheriting from `Transform`
3. Implement `run()` method to generate nodes.tsv and edges.tsv
4. Add constant to `constants.py`: `NEW_SOURCE = "new_source"`
5. Register in `DATA_SOURCES` dict in `kg_microbe/transform.py`
6. Add download entry to `download.yaml`
7. Add merge entry to `merge.yaml`

### Standard Edge Format

Edges must include:
- `subject`: Subject node ID (with CURIE prefix)
- `predicate`: Biolink predicate (e.g., `biolink:related_to`)
- `object`: Object node ID (with CURIE prefix)
- `relation`: RO or other relation ontology term
- `primary_knowledge_source`: Source provenance

### Standard Node Format

Nodes must include:
- `id`: Unique CURIE identifier
- `category`: Biolink category (e.g., `biolink:OrganismTaxon`, `biolink:ChemicalEntity`)
- `name`: Human-readable label
- Other optional fields: `description`, `xref`, `synonym`, `provided_by`