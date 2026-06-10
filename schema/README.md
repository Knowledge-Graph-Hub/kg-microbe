# Schemas

LinkML schemas for KG-Microbe data sources, bootstrapped with
[schema-automator](https://github.com/linkml/schema-automator).

## KG-Microbe merged KG (`kg_microbe_merged.yaml`)

LinkML schema for the **merged knowledge graph** in KGX TSV format
(`data/merged/<build>/{*_nodes.tsv,*_edges.tsv}`). Generated from the
2026-06-10 build (**2,438,443 nodes; 12,900,316 edges**).

- `Node` (id, category, name, description, xref, provided_by, synonym,
  deprecated, same_as) and `Edge` (subject, predicate, object, relation,
  primary_knowledge_source, knowledge_level, agent_type, has_percentage, unit,
  value), wrapped by a `KnowledgeGraph` container.
- Enums populated from the build's distinct values: `NodeCategoryEnum` (22),
  `PredicateEnum` (88), `KnowledgeLevelEnum` (3), `AgentTypeEnum` (3); each
  permissible value carries its occurrence count and (for CURIEs) a `meaning`.
- List-valued node columns (`category`, `xref`, `provided_by`, `synonym`,
  `same_as`) are `|`-delimited in the TSV → modelled `multivalued`.

`scripts/generate_merged_kg_schema.py` streams the two TSVs once each and emits
the schema, so it can be regenerated for any build:

```bash
python scripts/generate_merged_kg_schema.py --merged-dir data/merged/20260610 \
  -o schema/kg_microbe_merged.yaml   # ~25s
gen-linkml --format yaml schema/kg_microbe_merged.yaml
linkml-validate -s schema/kg_microbe_merged.yaml schema/examples/kg_microbe_merged_sample.yaml
```

A referentially-consistent 116-node / 100-edge sample drawn from the real build
is committed at `schema/examples/kg_microbe_merged_sample.yaml` and validates
cleanly.

**Data-quality notes** surfaced while building the schema (left as strings, not
enums): `primary_knowledge_source` mixes clean `infores:` CURIEs, Python-list
strain-provenance literals (`['infores:bacdive', 'bacdive:NNN']`) and raw source
filenames (`chebi.json`); `unit` carries mojibake (`ï¿½g` for µg);
`knowledge_level`/`agent_type` carry a few `|`-joined merge-dedup artifacts; and
the `deprecated` node column holds malformed URI values on a few UPA rows.

## BacDive isolation sources

Source: the BacDive **Isolation sources** table (`download.yaml` ->
`data/raw/bacdive_isolation_sources.csv`, from
<https://bacdive.dsmz.de/isolation-sources/csv>). One row per *strain x
isolation-source category path*, with a three-level classification
(`category_1/2/3`) that forms BacDive's controlled isolation-source vocabulary
(the "ontology").

Three schema files (enums shared via `imports`):

| File | Purpose |
| --- | --- |
| `bacdive_isolation_source_enums.yaml` | Shared enums: `continent_enum` + `category_1/2/3_enum`, annotated with ENVO `meaning:` CURIEs. |
| `bacdive_isolation_sources.yaml` | **Flat** schema — one `IsolationSource` row, faithful to the CSV export. |
| `bacdive_strain.yaml` | **Normalized** schema — one `Strain` record with a multivalued list of `IsolationSourceCategoryPath`. |

Helper scripts:

- `scripts/reshape_isolation_sources.py` — collapse the flat CSV into per-strain
  records (full JSONL + a validated YAML sample under `schema/examples/`).
- `scripts/annotate_isolation_enums_envo.py` — annotate the enums against ENVO
  from the local `data/raw/envo.json`.

## `bacdive_isolation_sources.yaml`

### How it was generated

schema-automator's `generalize-tsv` does a naive delimiter split, so the
raw CSV (quoted headers, commas inside `culture_collection_number` and
`isolation_source`) is first normalized to a clean snake_cased TSV with a
real CSV parser, then generalized:

```bash
# 1. CSV -> clean snake_cased TSV (proper CSV parsing)
python -c "
import pandas as pd
df = pd.read_csv('data/raw/bacdive_isolation_sources.csv', dtype=str)
df.columns = ['id','species','culture_collection_number','isolation_source',
              'country','continent','category_1','category_2','category_3']
df.to_csv('/tmp/bacdive_isolation_sources_clean.tsv', sep='\t', index=False)
"

# 2. Generalize to LinkML, forcing the ontology columns to enums
uvx --from schema-automator schemauto generalize-tsv \
  -s $'\t' \
  -c IsolationSource -n BacDiveIsolationSources \
  -E continent -E category_1 -E category_2 -E category_3 \
  --max-enum-size 400 --infer-optional \
  -o schema/bacdive_isolation_sources.yaml \
  /tmp/bacdive_isolation_sources_clean.tsv
```

Validate: `gen-linkml --format yaml schema/bacdive_isolation_sources.yaml`.

### Refinements applied (post-generation)

The raw schema-automator draft was then hand/script-refined:

- **`###` multi-value delimiter** — BacDive joins multiple values with `###`.
  The three columns that carry it (`isolation_source`, `country`, `continent`)
  are now `multivalued: true`. `continent_enum` was rebuilt from the **8 base
  continents** (the raw 33-value enum was unsplit `###` combinations such as
  `Asia###Antarctica`). The `category_*` columns contain no `###` and stay
  single-valued.
- **Enums verified against the full data** — every `continent` (8), `category_1`
  (8), `category_2` (59) and `category_3` (283) value in the 144,199-row export
  is covered by its enum (0 missing).
- **Dropped the bogus `unique_keys`** on `culture_collection_number` (it is null
  on the follow-on rows of each multi-row strain record).
- Added slot/class/enum **descriptions** documenting the `#` value prefix, the
  `###` delimiter, and the multi-row-per-strain structure.

## Per-strain reshape (`bacdive_strain.yaml`)

The flat export is denormalized (mean ~2.5 rows/strain: strain-level fields on
the first row, one category path per row). `bacdive_strain.yaml` models the
entity directly — one `Strain` (keyed by the BacDive `id`) holding the strain's
`isolation_source` / `country` / `continent` lists and a multivalued
`isolation_source_categories` list of `IsolationSourceCategoryPath`
(`category_1 > category_2 > category_3`).

```bash
python scripts/reshape_isolation_sources.py        # 144,199 rows -> 56,700 strains
linkml-validate -s schema/bacdive_strain.yaml schema/examples/bacdive_strains_sample.yaml
```

The full set is written to `data/processed/bacdive_strains.jsonl` (gitignored);
a 50-strain sample is committed at `schema/examples/bacdive_strains_sample.yaml`
and validates cleanly.

## ENVO annotation

`scripts/annotate_isolation_enums_envo.py` grounds the enum values in ENVO using
the local `data/raw/envo.json` (no network). Matching is conservative — a value
matches only a **non-obsolete** ENVO term's **primary label** or an **exact**
synonym (broad/related synonyms are ignored, since they produced homonym errors
such as the body-site "mouth" matching the river-mouth synonym of *estuary*).

Coverage: **56** values annotated (`category_1` 1/8, `category_2` 7/59,
`category_3` 48/283; `continent` 0/8). The matches concentrate in the
environmental level-3 terms; host / medical / condition categories have no ENVO
equivalent and are intentionally left unmapped.

```bash
python scripts/annotate_isolation_enums_envo.py
```

### Known refinements (TODO)

- Extend grounding beyond ENVO: host body sites -> UBERON, medical/clinical
  categories -> OBI/MONDO, continents -> GAZ.
- Reuse these enums/`meaning:` CURIEs when wiring an isolation-sources transform
  into the KG (BacDive isolation-source mapper).
