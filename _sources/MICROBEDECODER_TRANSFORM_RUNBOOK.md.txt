# MicrobeDecoder Transform: Runbook

The MicrobeDecoder transform ingests a wide CSV keyed by LPSN name-record ID
and turns it into KGX-format nodes and edges. Microbe Decoder is described by
[Hackmann et al. (Nucleic Acids Research 2026)](https://doi.org/10.1093/nar/gkag515);
the earlier [Hackmann & Zhang (Science Advances 2023)](https://doi.org/10.1126/sciadv.adg8687)
paper describes Fermentation Explorer, one of its contributing resources.
The actively maintained database (CC BY 4.0) pre-joins four metabolism sources
KG-Microbe does not otherwise cover:

- **Bergey's Manual of Systematics of Archaea and Bacteria** — expert
  curation of `Type_of_metabolism` / `Major_end_products` /
  `Minor_end_products` / `Substrates_for_end_products`
- **VPI Anaerobe Laboratory Manual** — independent second-opinion
  fermentation profiles for anaerobes
- **Primary literature** — hand-curated end-products with DOI/PMID
  citations
- **FAPROTAX** — taxon-based functional predictions joined to the source records

Plus a **pre-joined LPSN ↔ NCBITaxon ↔ GTDB ↔ GOLD ↔ IMG ↔ BacDive
crosswalk**. Taxon/identifier links use `biolink:close_match`; the BacDive
strain links use `biolink:subclass_of`, not identity. Current counts must
be measured from the selected source output.

### Record grain and interpretation

An LPSN identifier denotes a nomenclatural name record, not a strain identifier.
The saved CSV reviewed for #650 contains 27,010 rows and 27,010 distinct
`LPSN_ID` values; its status column includes species, subspecies, varieties and
forms. A populated strain field supplies associated strain information, not
proof that the LPSN subject is a strain. The earlier 8,350-organism figure from
Fermentation Explorer does not establish the grain or size of this later input.

Microbe Decoder's methods describe joining taxonomy and trait databases to LPSN
names and preserving multiple reported trait values separately. KGM likewise
retains the source record, field, literal and evidence tier. An assertion on an
LPSN subject is not proof that every strain of that taxon shares the observation.
Do not discard conflicting values or aggregate records merely to match a paper's
historical organism count. See [observation curation](microbedecoder_observation_curation.md).

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

Metabolism and source-attribute assertions attach to `lpsn:<LPSN_ID>` subjects.
The LPSN transform supplies their authoritative declarations where available;
MicrobeDecoder emits source-backed typed stubs only for referenced LPSN IDs
absent from that dependency. BacDive strain links instead have strain subjects
and LPSN objects. Run `-s lpsn` before MicrobeDecoder for a coherent source build
and merged KG.

## Running the transform

The current producer requires finalized LPSN, GOLD and GTDB dependencies, plus
the selected ontology output's `metpo_nodes.tsv`, `go_nodes.tsv` and
`chebi_nodes.tsv`. The versioned tables
`mappings/canonical/microbedecoder_process_mappings.tsv`,
`mappings/canonical/microbedecoder_phenotype_mappings.tsv` and
`mappings/canonical/microbedecoder_process_scope_definitions.tsv` are required curation
inputs. These tables and the actual native declarations read by the producer
are fingerprinted through source finalization and admission. METPO supports
reviewed processes and Attribute node types, GO supports the reviewed
catabolic/respiratory processes, and ChEBI supports the record-scoped chemical
correction. Missing or incompatible required authority is an error, not a
reason to mint a new target stub.

```bash
poetry run kg transform -s microbedecoder
```

Runtime includes mapping validation and source finalization as well as the
single-CSV parse. Default paths:

- **Input:** `data/raw/microbedecoder_database.zip` (auto-extracted)
- **Output:** `data/transformed/microbedecoder/`

## Output files

| File | Description |
|------|-------------|
| `nodes.tsv` | Producer-owned local material/process/attribute declarations and source taxon stubs where necessary. Source finalization may also copy authoritative declarations. Resolved targets remain owned by their authority transforms; their presence here is not a new identity mapping. |
| `edges.tsv` | Crosswalk, metabolism and column-scoped BacDive source-attribute assertions. Snapshot tokens are not automatically interpreted as phenotypes. Counts depend on the source build. |
| `unmapped_labels.tsv` | Per-run curation queue — unresolved pathways/compounds and preserved source attributes, with `kgmicrobe.{pathway,compound,source_attribute}:` IDs, sorted by occurrence descending. See "Curation loop" below. |
| `phenotype_normalizations.tsv` | Reviewed field/literal types linked to original source records; **not additional phenotype graph assertions**. Types also appear in the Attribute node's `has_attribute_type` property, with separate curation evidence. This report is not a merge input. |

The transform prints a one-line summary at end of run. For example, this
historical summary is not an expected count for the current producer:

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
| Chemical (end-products, substrates) | Reviewed full-record corrections, then `ChemicalMappingLoader.find_chebi_by_name()`; the two unresolved sugar records remain protected | `kgmicrobe.compound:<slug>` |
| Pathway (`Type_of_metabolism` from Bergey/VPI/Literature/FAPROTAX) | Exact process rules require active native declarations; finite source-local definitions use field/literal-hashed IDs and retain the old locator as `original_object` | `kgmicrobe.pathway:<slug>` for unreviewed fallback |
| BacDive snapshot | Column/literal-scoped `biolink:Attribute`; reviewed `has_attribute_type` node property requires field-specific evidence | `kgmicrobe.source_attribute:microbedecoder_<column>_<sha256>` |

The `unmapped_labels.tsv` report shows where each facet is landing. Recompute
coverage from a fresh build; historical mapping rates predate the current
source-attribute model and must not be used as current acceptance evidence. See
[issue #650](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/650)
for the curation gap.

The reviewed process table contains nineteen source-field/token pairs: eight
METPO rules and eleven GO catabolic/respiratory rules. Forty-five further exact
FAPROTAX pairs have reviewed source-local definitions, not external ontology
identity mappings. Their source-scoped IDs prevent definition leakage into
same-spelled labels from other sources.
Twenty-seven separate non-process/unspecified source labels are retained as
field-scoped reporting attributes instead of process objects. None of these
rules interprets unrelated assay codes or narrower/negative process terms. See the
[curation evidence and limitations](microbedecoder_process_curation.md).
FAPROTAX assignments remain predictions, not newly established experiments.

The exact `Not reported` token in `Bergey_Substrates_for_end_products` is retained
as `has_attribute` reporting metadata with its source record and citation. It
is not a consumed chemical and does not assert an inability to use substrates.

Thirty-five exact source-column/literal rules add native METPO types to Attribute
nodes: 22 Gram-stain/oxygen-tolerance/cell-shape values, nine evidence-backed
numeric/sign codes, and four FAPROTAX trait labels. Original record-qualified
assertions and contradictory/multivalued observations remain intact; FAPROTAX
traits use `has_attribute` rather than a process relation. Other codes, units,
measurements and isolation contexts are not automatically decoded. Read the
[observation curation contract](microbedecoder_observation_curation.md) before
treating the report as organism phenotype evidence.

### Complete current-data inventory

An unmapped-report row can be a measurement, unit, isolation context or an
undecoded assay value. It is not necessarily a missing ontology mapping. The
historical 5,224-label total predates the current model and is not a current
acceptance checklist. Generate an inventory from actual source graph rows:

```bash
poetry run python -m scripts.review_microbedecoder_curation \
    --source-dir data/transformed/microbedecoder \
    --output-dir data/microbedecoder-curation-review-NEW
```

The destination must not already exist. This writes `curation_inventory.tsv`
and `summary.json`, with exact input/output hashes and a before/after input
check. It streams every source edge, separately accounts for crosswalks,
chemical mappings/local materials, reviewed/unreviewed processes, and all 27
snapshot field roles. No frequency threshold discards the long tail. Counts
are finalized source edge rows, not raw placeholder emission attempts or
distinct organisms. The report does not certify merged propagation, new
chemical identity, a complete scientific interpretation, or release readiness.

The inventory separately annotates the finite reviewed material cohort with
context, evidence and **unresolved** identity status. This is not an exact
chemical mapping or a transform admission requirement. When accepting a rebuild
of that same saved snapshot, explicitly require all reviewed uses and validate
their complete raw records:

```bash
poetry run python -m scripts.review_microbedecoder_curation \
    --source-dir data/transformed/microbedecoder \
    --output-dir data/microbedecoder-cohort-review-NEW \
    --require-reviewed-material-cohort \
    --reviewed-material-raw data/raw/database.csv
```

That closed-cohort check must fail for a different source snapshot, rather than
silently applying historical reviews by label. Ordinary partial inventories
report matched/missing counts without asserting complete acceptance. See
[the material disposition contract](microbedecoder_material_dispositions.md).

## Curation loop

The **per-run `unmapped_labels.tsv` → tracked curation TSV → target
tool → next run** loop:

```bash
# Preserve the old tracked queue and any curator annotations. The writer
# replaces its destination and initializes blank curator fields.
queue_dir=$(mktemp -d data/microbedecoder-curation.XXXXXX)
poetry run python scripts/dump_unmapped_microbedecoder_labels.py \
    --min-occurrences 0 --output "$queue_dir/all.tsv"

# Separate facets into different files, without dropping low-frequency rows.
poetry run python scripts/dump_unmapped_microbedecoder_labels.py \
    --prefix pathway --min-occurrences 0 --output "$queue_dir/pathway.tsv"
poetry run python scripts/dump_unmapped_microbedecoder_labels.py \
    --prefix compound --min-occurrences 0 --output "$queue_dir/compound.tsv"
poetry run python scripts/dump_unmapped_microbedecoder_labels.py \
    --prefix source_attribute --min-occurrences 0 --output "$queue_dir/source_attribute.tsv"
```

The default output, when `--output` is omitted, is the tracked
`mappings/microbedecoder_unmapped_labels_to_curate.tsv`. Review a newly generated
queue before deliberately updating that historical curation asset. The default
threshold is 10; it is useful for prioritization, not a complete inventory.
Columns:

| Column | Meaning |
|---|---|
| `placeholder_curie` | The unchanged pathway, compound or column-scoped source-attribute ID from the last run |
| `category` | Biolink category the placeholder carried |
| `label` | Raw source label |
| `source_columns` | Pipe-set of source columns this label appeared under |
| `occurrences` | Producer emission attempts before finalized edge deduplication; not necessarily distinct edge rows |
| `target_curie` | *(empty, curator fills)* — CHEBI / METPO / GO / EC |
| `target_label` | *(empty)* — human-readable target name |
| `mapping_status` | `UNMAPPED` at emit; curator sets `MAPPED` / `PROPOSED` / `SKIP` |
| `curator_notes` | Free-text |

Curator workflow by facet:

- **pathway** — review the exact source field and process definition against an
  existing ontology class. Add supported rules to the source-scoped process
  table, with evidence, authoritative target metadata and boundary tests. Do
  not turn source-specific evidence into a global synonym, use a predicate as
  a process object, or upgrade a FAPROTAX prediction to experimental evidence.
- **compound** — review identity evidence through
  [the supported MIM / unified mapping workflow](MIM_REVIEWED_RELEASE.md).
  A curation queue row is not by itself an active resolver mapping.
- **source_attribute** — review the BacDive-snapshot field together with its
  exact token and coding scheme. Preserve column context and do not interpret
  a numeric code, zero, assay token or preparation as a generic phenotype or
  chemical identity merely because its label matches an ontology synonym.
  The legacy `--prefix trait` filter remains compatible with both old
  `kgmicrobe.trait:` reports and current source-attribute reports; it does
  not rewrite IDs or categories.

## Verification

```bash
# Quick shape check
wc -l data/transformed/microbedecoder/nodes.tsv \
      data/transformed/microbedecoder/edges.tsv \
      data/transformed/microbedecoder/unmapped_labels.tsv

# Separate source-edge distributions and producer report counts
poetry run python scripts/generate_coverage_report.py -s microbedecoder

# Category / predicate / prefix validation
poetry run python .claude/skills/kg-model-review/kg_model_review.py \
    --transform microbedecoder
```

The coverage report does **not** calculate a mapping-success percentage. Source
edge rows include crosswalks, resolved and unresolved materials, pathways and
reported Attributes; queue counts are a separate producer measure. Repeated
labels in different columns/facets retain their context. A missing queue means
unknown report totals, whereas a valid header-only queue records zero rows.
For MetaTraits modes, each unresolved trait/taxon report row remains separate
and `num_observations` is reported independently of the number of report rows.
Ontology prefixes and lexical matches do not establish chemical identity or
decode an assay's meaning.

## Merge

Included in `merge.yaml` by default. To rebuild the merged KG:

```bash
poetry run kg merge -y merge.yaml
```

Most biological assertions attach to `lpsn:<LPSN_ID>` subjects; BacDive strain
hierarchy links use the reverse endpoint roles described above. LPSN supplies
authoritative nodes where available, while MicrobeDecoder's source-backed stubs
cover referenced IDs missing from that dependency. Merge aggregates shared IDs;
it does not turn a source stub into independently established LPSN evidence.

## Follow-ups (out of scope for the initial ingest)

- `gene_functions_database.rds` (R-serialized KEGG-KO gene→function)
  — its own transform if KEGG is re-activated in `merge.yaml`.
- 16S rRNA sequences (`LPSN_16S_Ribosomal_sequence`) — sequence-oriented
  transform (BLAST-able) can pull them later.
- FAPROTAX as its own full transform — this ingest only carries the
  joined `FAPROTAX_Type_of_metabolism` labels per source name record.
- Bergey as its own full ingest — this ingest only carries the
  Bergey-derived edges MicrobeDecoder pre-joins.
- Further METPO/GO process grounding — nineteen native rules are implemented;
  forty-five source-local meanings are reviewed but retain explicit native
  identity holds. Additional global synonyms are not a prerequisite or a safe
  substitute for checking source roles and target definitions.
- Further ambiguous multi-value parsing. Bracketed separators and numeric
  chemical locants such as `2,3-butanediol` are already preserved; the parser
  is not a general chemical-name interpreter.

## Related

- Add-transform skill: `.claude/skills/add-transform/SKILL.md`
- Postprocess-report skill: `.claude/skills/kg-postprocess-report/`
- Original PR: [#648](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/648)
- Encoding fix: [#649](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/649)
- Unmapped-labels report: [#652](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/652)
- Curation-gap tracking: [#650](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/650)
- Row-grain confirmation: [#651](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/651)
