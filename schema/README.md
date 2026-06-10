# Schemas

LinkML schemas for KG-Microbe data sources, bootstrapped with
[schema-automator](https://github.com/linkml/schema-automator).

## `bacdive_isolation_sources.yaml`

First schema-automator target: the BacDive **Isolation sources** table
(`download.yaml` -> `data/raw/bacdive_isolation_sources.csv`, from
<https://bacdive.dsmz.de/isolation-sources/csv>).

The table is one row per *strain x isolation-source assignment* with a
three-level isolation-source classification (`category_1/2/3`) that forms
BacDive's controlled isolation-source vocabulary (the "ontology").

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

### Known refinements (TODO)

- `id` is the BacDive strain ID and repeats across the multi-row records
  (mean ~2.5 rows/strain). Consider reshaping to one record per strain with a
  multivalued list of category paths (`category_1 > category_2 > category_3`).
- Annotate the `category_*` enums against an environment ontology (ENVO) — e.g.
  `schemauto annotate-schema -A envo` — to ground the BacDive vocabulary.
