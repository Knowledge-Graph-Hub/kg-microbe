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

### Known refinements (TODO)

- BacDive uses `###` as a multi-value delimiter. `isolation_source` was
  inferred as multivalued, but `continent_enum` still holds `###`-joined
  combinations (e.g. `Asia###Antarctica`) instead of ~8 base continents.
  Split `continent` (and re-check `category_*`) on `###` in a refinement.
- `id` is the BacDive ID and repeats across the multi-row records; consider
  reshaping to one record per strain with multivalued category paths.
