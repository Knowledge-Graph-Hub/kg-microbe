# MicrobeDecoder Transform: Runbook

The MicrobeDecoder transform ingests the wide per-LPSN-strain CSV that
[Hackmann & Zhang (Sci Adv 2023)](https://www.science.org/doi/10.1126/sciadv.adg8687)
publish on GitHub and turns it into KGX-format nodes and edges. The
database is the actively-maintained successor to FermentationExplorer
(CC BY 4.0) and pre-joins four curated fermentation-metabolism sources
KG-Microbe does not otherwise cover:

- **Bergey's Manual of Systematics of Archaea and Bacteria** — expert
  curation of `Type_of_metabolism` / `Major_end_products` /
  `Minor_end_products` / `Substrates_for_end_products`
- **VPI Anaerobe Laboratory Manual** — independent second-opinion
  fermentation profiles for anaerobes
- **Primary literature** — hand-curated end-products with DOI/PMID
  citations
- **FAPROTAX** — functional labels joined at strain granularity

Plus a **pre-joined LPSN ↔ NCBITaxon ↔ GTDB ↔ GOLD ↔ IMG ↔ BacDive
identity crosswalk** — ~80 K `biolink:close_match` edges the transform
emits without further mapping work.

## Prerequisites

### Environment

Follows the standard repo setup — see the top-level `README` /
`CLAUDE.md`. No credentials or authentication required (CC BY 4.0
source, plain HTTPS download).

### Input file

```bash
poetry run kg download -t microbedecoder
```

Fetches `https://github.com/thackmann/MicrobeDecoder/raw/main/Shiny/MicrobeDecoder/data/database/database.zip`
into `data/raw/microbedecoder_database.zip`. On first `kg transform`
run the transform extracts the archive into
`data/raw/microbedecoder/database.csv` (~57 MB, ~27 K rows).

### LPSN dependency

Every emitted edge is keyed on `lpsn:<LPSN_ID>` — the MicrobeDecoder
transform **does not stub LPSN taxon nodes** (the `lpsn` transform is
their authoritative source, per the add-transform skill's
"don't stub cross-refs" rule). Run `-s lpsn` alongside for a coherent
merged KG.

## Running the transform

```bash
poetry run kg transform -s microbedecoder
```

Wall-clock: ~20–30 seconds on a MacBook (single-CSV parse, no ontology
adapter loads). Default paths:

- **Input:** `data/raw/microbedecoder_database.zip` (auto-extracted)
- **Output:** `data/transformed/microbedecoder/`

## Output files

| File | Description |
|------|-------------|
| `nodes.tsv` | Terminal-node stubs for **placeholder** CURIEs only — resolved cross-ref targets (NCBITaxon, GTDB, bacdive, GOLD, IMG, CHEBI) come from their owner transforms. Typical size: ~5 K nodes. |
| `edges.tsv` | All emitted edges: crosswalk (`biolink:close_match`), metabolism (`biolink:capable_of` / `biolink:produces` / `biolink:consumes`), BacDive-snapshot replay (`biolink:has_phenotype`). Typical size: ~510 K edges. |
| `unmapped_labels.tsv` | Per-run curation queue — every raw label that fell through the mapping chain and landed as a `kgmicrobe.{pathway,compound,trait}:<slug>` placeholder, sorted by occurrence descending. See "Curation loop" below. |

The transform prints a one-line summary at end of run:

```
[microbedecoder] rows=27010, crosswalk_edges=80971, metabolism_edges=69962,
                 bacdive_snapshot_edges=366298, unmatched_labels=428305
```

`unmatched_labels` is the count of *edge* placeholder attempts, not
distinct labels — the report dedupes them into `unmapped_labels.tsv`
rows.

## Mapping resolution

Labels are resolved through the same canonical mapping infrastructure
the add-transform skill mandates for every transform:

| Facet | Resolver | Placeholder prefix on miss |
|---|---|---|
| Chemical (end-products, substrates) | `ChemicalMappingLoader.find_chebi_by_name()` | `kgmicrobe.compound:<slug>` |
| Pathway (`Type_of_metabolism` from Bergey/VPI/Literature/FAPROTAX) | (not yet integrated — see follow-up below) | `kgmicrobe.pathway:<slug>` |
| BacDive trait snapshot | (v1: always placeholder — fresher `bacdive` transform is authoritative) | `kgmicrobe.trait:<slug>` |

The `unmapped_labels.tsv` report shows where each facet is landing. On
a fresh run against the live database, mapping rate is ~54 % (~511 K
mapped edges vs ~428 K unmapped occurrences); see
[issue #650](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/650)
for the curation gap.

## Curation loop

The **per-run `unmapped_labels.tsv` → tracked curation TSV → target
tool → next run** loop:

```bash
# 1. Refresh the tracked curation TSV from the latest run (defaults to
#    labels with 10+ occurrences — filters per-strain literal tail).
poetry run python scripts/dump_unmapped_microbedecoder_labels.py

# 2. Or split by facet so each batch hands to the right target tool:
poetry run python scripts/dump_unmapped_microbedecoder_labels.py --prefix pathway
poetry run python scripts/dump_unmapped_microbedecoder_labels.py --prefix compound
poetry run python scripts/dump_unmapped_microbedecoder_labels.py --prefix trait
```

Output lands at `mappings/microbedecoder_unmapped_labels_to_curate.tsv`
(tracked in git — mirrors the `mappings/mediadive_unmapped_ingredients_to_curate.tsv`
pattern). Columns:

| Column | Meaning |
|---|---|
| `placeholder_curie` | The `kgmicrobe.{pathway,compound,trait}:<slug>` from the last run |
| `category` | Biolink category the placeholder carried |
| `label` | Raw source label |
| `source_columns` | Pipe-set of source columns this label appeared under |
| `occurrences` | Edges this placeholder anchored last run |
| `target_curie` | *(empty, curator fills)* — CHEBI / METPO / GO / EC |
| `target_label` | *(empty)* — human-readable target name |
| `mapping_status` | `UNMAPPED` at emit; curator sets `MAPPED` / `PROPOSED` / `SKIP` |
| `curator_notes` | Free-text |

Curator workflow by facet:

- **pathway** — file a METPO PR adding a `"microbedecoder synonym"`
  column to `berkeleybop/metpo`'s `src/templates/metpo_sheet.tsv` and
  pre-populate the top labels. Once merged, the transform's
  METPO-alias hookup (currently marked as a v2 follow-up in
  `_resolve_metabolism_curie`) will promote these placeholders.
- **compound** — add rows to `mappings/canonical/chemical_mappings.tsv`
  or `mappings/canonical/special_chemical_mappings.tsv` targeting the
  right CHEBI CURIE. Next run promotes them automatically via
  `ChemicalMappingLoader.find_chebi_by_name()`.
- **trait** — the BacDive-snapshot column values (24 columns × per-strain
  literals). Most belong in `kgmicrobe.trait` yaml under
  `custom_curies.yaml` if they're stable phenotype tokens; the
  long tail (numeric temperatures, free-text) is genuinely per-strain
  data and stays as placeholders.

## Verification

```bash
# Quick shape check
wc -l data/transformed/microbedecoder/nodes.tsv \
      data/transformed/microbedecoder/edges.tsv \
      data/transformed/microbedecoder/unmapped_labels.tsv

# Coverage report (parametrized script; add `-s microbedecoder`)
poetry run python scripts/generate_coverage_report.py -s microbedecoder

# Category / predicate / prefix validation
poetry run python .claude/skills/kg-model-review/kg_model_review.py \
    --transform microbedecoder
```

## Merge

Included in `merge.yaml` by default. To rebuild the merged KG:

```bash
poetry run kg merge -y merge.yaml
```

The MicrobeDecoder edges attach to `lpsn:<LPSN_ID>` subjects, which are
provided by the `lpsn` transform's `nodes.tsv`. Merge-time dedup on
`id` collapses any incidental overlap.

## Follow-ups (out of scope for the initial ingest)

- `gene_functions_database.rds` (R-serialized KEGG-KO gene→function)
  — its own transform if KEGG is re-activated in `merge.yaml`.
- 16S rRNA sequences (`LPSN_16S_Ribosomal_sequence`) — sequence-oriented
  transform (BLAST-able) can pull them later.
- FAPROTAX as its own full transform — this ingest only carries the
  joined `FAPROTAX_Type_of_metabolism` label per strain.
- Bergey as its own full ingest — this ingest only carries the
  Bergey-derived edges MicrobeDecoder pre-joins.
- METPO alias hookup — see `_resolve_metabolism_curie`; blocked on the
  METPO ROBOT template getting a `"microbedecoder synonym"` column.
- Smarter multi-value splitter (currently over-splits chemical names
  containing embedded commas like `2,3-butanediol`; same limitation as
  `madin_etal`).

## Related

- Add-transform skill: `.claude/skills/add-transform/SKILL.md`
- Postprocess-report skill: `.claude/skills/kg-postprocess-report/`
- Original PR: [#648](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/648)
- Encoding fix: [#649](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/649)
- Unmapped-labels report: [#652](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/652)
- Curation-gap tracking: [#650](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/650)
- Row-grain confirmation: [#651](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/651)
