---
name: add-transform
description: Add a new data source transform to KG-Microbe end-to-end — from "should we even ingest this?" through deep research, cross-reference analysis, semantic design, code scaffold, integration, verification, and shipping the PR. Bakes in the CLAUDE.md 7-step checklist plus the research + analysis + verify phases that keep the KG coherent. Use whenever the ask is "ingest X", "add source Y", or "integrate a new database into kg-microbe".
---

# add-transform

## Purpose

Adding a data source to KG-Microbe is a semantic modeling decision as much as a code change: the wrong entity model or a duplicate CURIE prefix propagates to every downstream consumer of the merged KG. This skill enforces a research → analysis → design → implement → integrate → verify → ship pipeline so that every new transform lands with:

- A clear statement of *what value the source adds* beyond existing transforms.
- All cross-references (GTDB, NCBITaxon, BacDive, ChEBI, MONDO, etc.) modeled explicitly rather than reinvented.
- Category / predicate assignments that pass `kg-model-review`.
- Prefix registration in `custom_curies.yaml` before any node is emitted.
- Tests + tox pass on the same commit that adds the transform.

## When to use

- User says any of: "ingest X", "add source Y", "integrate database Z", "pull in <name> taxonomy / mappings / annotations".
- You are about to create a new directory under `kg_microbe/transform_utils/`.
- You caught a source cited in the paper or in an existing issue that isn't yet in `DATA_SOURCES`.

Skip if: the ingest is a one-off analysis (do it in a notebook), or the source is a small mapping table that fits into `mappings/` without a transform.

## Prerequisites

- Repo checked out at a clean master (or a fresh feature branch off master — run `branch-triage-ship` first if the working tree is messy).
- `gh` and `poetry` available.
- If the source is licensed or auth-gated: credentials handy or a plan to vendor a snapshot.
- Companion skills available in this session: `deep-research`, `kg-model-review`, `kg-path-review`, `audit-mappings`, `chemical-mapping`, `metpo-ontology`, `metpo-proposal`, `branch-triage-ship`.

## The workflow

Run the phases in order. Each has an explicit gate — do not proceed past a gate until the checklist is satisfied.

### Phase 1 — Research the source

Goal: know what the source *is*, what it *contains*, and what it *costs to ingest* before touching code.

**Delegate to `deep-research`** with a scoped question, e.g.:

> Research the "<source-name>" database for potential ingestion into KG-Microbe. What is its scope (organisms / chemicals / traits / other)? Access modalities (bulk download URL, REST API, API-key required, licensed CSV)? License and redistribution terms? Approximate size (rows / GB) and update cadence? Native identifier scheme(s) and CURIE-friendly prefix if any? What cross-references does it publish natively (to NCBI Taxonomy, GTDB, ChEBI, MONDO, OBO, UniProt, etc.)? Are there existing OBO ontology imports of the source? Where do downstream KGs / studies cite it? Anything about it that is deprecated, moved, or paywall-gated as of this year?

Capture the report; do not synthesize from memory.

**Also, in parallel:**

```bash
# Is the source already partially in this repo?
grep -rIn -i "<source-name>" --include="*.py" --include="*.yaml" --include="*.md" \
  kg_microbe scripts mappings docs notes | head -40

# Do we already have raw data from the source vendored anywhere?
find data -maxdepth 4 -iname "*<source-name>*" 2>/dev/null | head
```

**Gate 1 — you can answer:**
- What single sentence describes what this source uniquely provides?
- Is the data accessible from a script (yes/vendor/no)?
- What license? Any redistribution constraint that affects `data/raw/` commits?
- Native ID prefix (existing CURIE, or one to register)?
- Native cross-refs? Which of them does KG-Microbe already carry?

### Phase 2 — Analyze the delta vs existing transforms

Goal: prove the source adds value that isn't already covered.

```bash
# List currently active transforms
grep -nE "^\s+[A-Z_]+:.*Transform," kg_microbe/transform.py | head -30

# For each candidate overlapping transform, list what it emits
poetry run python .claude/skills/kgm-freshness-check/kgm_freshness_check.py --source <candidate>

# Check the audit-mappings skill for any hardcoded references that hint the source is already partially in-code
python3 .claude/skills/audit-mappings/audit_mappings.py --format md | head -60
```

Write a short **delta note** with three bullets:

1. What overlapping content already exists in KG-Microbe (which transform, which entity types).
2. What THIS source adds that the overlap doesn't cover (new predicates, richer synonyms, deeper taxonomy, additional cross-refs).
3. What overlap should we resolve (close_match edges? Prefer the incumbent? Prefer the new source?).

**Gate 2 — you can answer:**
- If we ingest this and someone asks "why do we need it when we have X?", the delta-note bullet 2 is your one-line answer.
- Have you decided the merge policy for any overlapping entities (close_match vs deduplicate vs pick winner)?

### Phase 3 — Design the entity model

Goal: draft the biolink categories, predicates, and CURIE prefixes BEFORE the first line of transform code.

Pick a candidate entity model:

- **Which biolink categories** each row maps to. See `kg_microbe/transform_utils/constants.py` for the canonical set already in use.
- **Which predicates** relate them. Prefer existing biolink predicates. If a phenotype-style predicate is needed, check METPO first (`.claude/skills/metpo-ontology/`).
- **Which CURIE prefix(es)** for the new source. Check `kg_microbe/transform_utils/custom_curies.yaml` — if the prefix isn't there, add it in this same PR.
- **Cross-reference edges** (usually `biolink:close_match` or `biolink:exact_match`) — one edge per known cross-ref that lands as its own edge in `edges.tsv`.

Draft a small **entity model table** in the design note:

| Row type from source | Biolink category | Node id pattern | Emitted edges | Predicate |
|---|---|---|---|---|

If the source has phenotypes that don't fit any existing biolink or METPO predicate, spawn `/metpo-proposal` to propose new terms rather than inventing local ones.

#### Reuse existing prefix constants before inventing new ones

`kg_microbe/transform_utils/constants.py` already ships **facet-typed placeholder prefixes** for common unmatched-label cases; do NOT mint a new `kgmicrobe.<something>:` prefix when one of these fits:

| Placeholder facet | Prefix constant | String | Category typically paired |
|---|---|---|---|
| Pathway / metabolism | `PATHWAY_PREFIX` | `kgmicrobe.pathway:` | `METABOLISM_CATEGORY` / `PATHWAY_CATEGORY` |
| Chemical entity | `COMPOUND_PREFIX` | `kgmicrobe.compound:` | `SMALL_MOLECULE_CATEGORY` / `CHEBI_CATEGORY` |
| Phenotypic quality / trait | `TRAIT_PREFIX` | `kgmicrobe.trait:` | `PHENOTYPIC_CATEGORY` |
| Carbon substrate specifically | `CARBON_SUBSTRATE_PREFIX` | `kgmicrobe.carbon_substrate:` | `CARBON_SUBSTRATE_CATEGORY` |
| Growth medium | (yaml section `kgmicrobe.medium`) | `kgmicrobe.medium:` | `MEDIUM_CATEGORY` |
| Molecular activity | (yaml section `kgmicrobe.activity`) | `kgmicrobe.activity:` | `MOLECULAR_ACTIVITY_CATEGORY` |
| Cell shape | `SHAPE_PREFIX` | `cell_shape:` | (madin-specific) |

Route unmatched labels by their semantic role to the correct one of these; do NOT create a source-specific placeholder prefix (`kgmicrobe.<mysource>:`) unless the concept genuinely doesn't fit any of the above (rare — reviewed case-by-case in the PR).

#### Reuse existing predicate constants before hardcoding

`constants.py` also carries predicate/relation constants every transform routes through so the merged KG stays queryable:

| Semantic role | Predicate constant | Relation constant |
|---|---|---|
| Organism consumes a substrate | `NCBI_TO_SUBSTRATE_EDGE` (== `"biolink:consumes"`) | `TROPHICALLY_INTERACTS_WITH` |
| Organism uses as carbon source | `NCBI_TO_CARBON_SUBSTRATE_EDGE` (== `"METPO:2000006"`) | (source-specific) |
| Organism produces a chemical | `PRODUCES_PREDICATE` | `HAS_OUTPUT_RELATION` / `PRODUCES_RELATION` |
| Organism has a phenotype | `HAS_PHENOTYPE_PREDICATE` | `HAS_PHENOTYPE` |
| Organism is capable of | `CAPABLE_OF_PREDICATE` | `CAPABLE_OF` |
| Cross-reference | `CLOSE_MATCH_PREDICATE` / `SAME_AS_PREDICATE` | `CLOSE_MATCH_RELATION` / `EXACT_MATCH` |

Never hardcode strings like `"biolink:consumes"` — grep for the constant first.

#### Reuse canonical mapping loaders

`kg_microbe/utils/mapping_file_utils.py` and `kg_microbe/utils/chemical_mapping_utils.py` expose the **only** blessed paths from a raw source label to an ontology CURIE. New transforms MUST attempt these before minting placeholders:

- **`load_metpo_mappings(synonym_column)`** — canonical label → METPO alias resolution. Pass a source-specific synonym column name (e.g. `"madin synonym or field"`, `"bacdive keyword synonym"`); the METPO ROBOT template at `https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/<tag>/src/templates/metpo_sheet.tsv` carries the columns. Adding a new source almost always means adding a new synonym column to that upstream template — file the METPO PR early in Phase 3 so the mapping is queryable by Phase 6.
- **`ChemicalMappingLoader.find_chebi_by_name(label)`** — unified CHEBI resolution (unified mappings + special_chemical_mappings + manual overrides). Reads the mappings gzip file; instantiate once per transform.
- **`kg_microbe.utils.ner_utils.annotate(df, prefix, exclusion_list, outfile, llm, chemical_loader)`** — OAK-based NER fallback against CHEBI or GO. Cache-gated by `cache_is_complete` on the output TSV; call only when the mapping tables miss.
- **Ontology adapters** — `kg_microbe.utils.ontology_utils.get_ontology_adapter("chebi" | "go" | "ec" | "ncbitaxon")` returns a lazy, drift-realigned adapter for label / ancestor / relationship lookups. `_NCBILabelIndex`-style direct-sqlite indices (see `lpsn.py:196-243`) are the pattern when label lookups dominate the transform's hot path.

Every canonical mapping the source could produce should also land in the shared **`mappings/canonical/`** hub — `phenotype_mappings.tsv`, `pathway_mappings.tsv`, `chemical_mappings.tsv`, `enzyme_mappings.tsv`, `metpo_alias_mappings.tsv` — rather than being hidden in per-transform TSVs. The `chemical-mapping` skill enumerates the schema.

**Gate 3 — the model is written down and:**
- Every category is in the biolink model.
- Every predicate is either biolink or a currently-registered METPO predicate (or a queued proposal).
- Every prefix used exists in `custom_curies.yaml` OR is added in the same PR (add first, then reference).
- No local CURIEs like `kgmicrobe.strain:` outside the two prefixes already reserved for that purpose.
- **Placeholders route by facet** into `PATHWAY_PREFIX` / `COMPOUND_PREFIX` / `TRAIT_PREFIX` / `CARBON_SUBSTRATE_PREFIX` — no new `kgmicrobe.<source>:` prefix unless the concept truly doesn't fit any existing facet.
- **Constants over hardcoded strings** for every predicate, relation, category, and infores knowledge-source (`grep` `kg_microbe/transform_utils/constants.py` first).
- **Canonical mapping loaders attempted** for every label the transform tries to resolve (METPO alias, chemical mapping, ner fallback) — falling back to placeholders only after the mapping paths return None.

### Phase 4 — Design the cross-reference strategy

Goal: every native cross-ref the source publishes must land as an edge.

For each cross-ref the source provides:

| Source native ID | Target CURIE | Target already in KG? | Edge predicate | Notes |
|---|---|---|---|---|
| `NCBI:12345` | `NCBITaxon:12345` | yes (ncbitaxon transform) | `biolink:close_match` | trivial |
| `GTDB s__X` | `gtdb.species:X` | yes (gtdb transform) | `biolink:close_match` | strip s__ per repo convention (see [[feedback_gtdb_prefix]] if noted) |
| `BacDive 12345` | `kgmicrobe.strain:bacdive_12345` | yes (bacdive transform) | `biolink:close_match` | this is the merge glue. **Not** `bacdive:12345` — no transform emits that as a node, so edges to it dangle and KGX turns them into empty `biolink:NamedThing` stubs |

Cross-refs that point to entities NOT in KG-Microbe: emit the edge anyway if you're confident downstream analyses will use it. Note it in the design and stub-node it appropriately.

**Gate 4 — every native cross-ref in the source has a decided target CURIE and predicate.**

### Phase 5 — Scaffold the transform

Only now touch code. Follow the CLAUDE.md 7-step checklist:

1. Create the directory:
   ```bash
   mkdir -p kg_microbe/transform_utils/<source_name>
   touch kg_microbe/transform_utils/<source_name>/__init__.py
   ```

2. Create the transform class. Start from `kg_microbe/transform_utils/example_transform/example_transform.py` as a template:
   ```bash
   cp kg_microbe/transform_utils/example_transform/example_transform.py \
      kg_microbe/transform_utils/<source_name>/<source_name>.py
   ```
   Rename `ExampleTransform` → `<SourceName>Transform`, wire it to the `Transform` base class, and stub `run()`.

3. Add the source-name constant to `kg_microbe/transform_utils/constants.py`:
   ```python
   <SOURCE_UPPER> = "<source_name>"
   ```

4. Register in `DATA_SOURCES` in `kg_microbe/transform.py`. Import the class and add the entry — put it near a semantically-similar existing entry (taxonomic source → near NCBITaxon, phenotype source → near BacDive).

5. Add a download entry to `download.yaml`. Include the full URL, expected `local_name`, and a `# NOTE:` block explaining any TLS / auth / rate-limit special handling.

6. Add a merge entry to `merge.yaml` — include the new source's `data/transformed/<source_name>/nodes.tsv|edges.tsv` under the appropriate section.

7. Add a prefix entry to `kg_microbe/transform_utils/custom_curies.yaml` if the CURIE prefix is new.

**Gate 5 — `poetry run kg transform -s <source_name>` runs (even if it emits zero rows).**

### Phase 6 — Implement parsing + row emission

Now write the actual transform logic:

- Read raw data from `self.input_base_dir / <input_file>` — the base class provides the path helper.
- Emit nodes via `self.node_writer.writerow([id, category, name, ...])` using the header keys in `constants.py`.
- Emit edges via `self.edge_writer.writerow([subj, pred, obj, rel, prov, ...])`.
- Every emitted node MUST include: `id`, `category`, `name`, `provided_by`.
- Every emitted edge MUST include: `subject`, `predicate`, `object`, `relation`, `primary_knowledge_source`.

**Patterns to follow (not copy blindly):**

- **BacDive** — good reference for large-per-record JSON, multi-category emission, cross-refs.
- **MediaDive** — good reference for REST-API-with-caching, ingredient decomposition.
- **BactoTraits** — good reference for a curated CSV with column-oriented traits.
- **Rhea** — good reference for a mapping file (many-to-many edges, no rich nodes).
- **GTDB / MetaTraits GTDB** — good reference for large-scale taxonomy with parallelizable chunks.

**Anti-patterns to avoid** (all previously landed as bugs):

- Do NOT hardcode inline CURIEs for the same concept at more than 2 call sites — the `audit-mappings` skill flags this. Route through a small mapping file or a dispatch dict.
- Do NOT open output files with plain `open("w")` if the transform can be interrupted — use the writers the base class provides so the header + provenance are consistent.
- Do NOT skip provenance. Every edge needs `primary_knowledge_source` set; leaving it blank shows up in `kg-model-review` as ERROR.
- Do NOT emit stub nodes for cross-referenced entities that already exist in KG-Microbe — emit the edge, and rely on merge-time reconciliation. This includes the transform's own *subject* nodes when they belong to another transform's namespace (e.g. a transform keyed on `lpsn:*` must NOT emit `lpsn:*` node stubs; the `lpsn` transform is the authoritative source, and the new transform's edges just reference those subjects).
- Do NOT hardcode predicate / relation / category strings. Import the constant from `kg_microbe/transform_utils/constants.py` — the same reason: consistent typing across every transform makes the merged KG queryable.
- Do NOT invent a new `kgmicrobe.<source>:` placeholder prefix without checking Phase 3's placeholder-prefix table first. `pathway` / `compound` / `trait` / `carbon_substrate` / `medium` / `activity` / `ingredient` are already registered — route to the one that matches your facet.
- Do NOT bypass the canonical mapping loaders. Every unmatched label MUST have tried `load_metpo_mappings` and `ChemicalMappingLoader.find_chebi_by_name` (and NER when appropriate) before a placeholder is minted. Placeholders should be the exception, not the rule; the `kg-model-review` output makes it easy to see how many placeholders you're producing per run.

**Gate 6 — `poetry run kg transform -s <source_name>` produces non-zero rows and the header matches `constants.py`.**

### Phase 7 — Verify the transform output

```bash
# quick shape check
wc -l data/transformed/<source_name>/nodes.tsv data/transformed/<source_name>/edges.tsv

# category / predicate / prefix check
poetry run python .claude/skills/kg-model-review/kg_model_review.py --transform <source_name>

# multi-hop path integrity check
# (Only if the transform emits cross-ref edges — kg-path-review needs a merge to walk)
poetry run kg merge -y merge.yaml
poetry run python .claude/skills/kg-path-review/kg_path_review.py  # if available as CLI
```

Findings expectations:
- kg-model-review: 0 ERRORs.
- WARNINGs are OK if they're for known-cross-ref stubs; not OK if they're for the source's own emission.
- kg-path-review: no cross-contamination, no self-loops.

**Gate 7 — kg-model-review reports 0 ERRORs on this transform's outputs.**

### Phase 8 — Add tests

```bash
# unit test at minimum
mkdir -p tests/resources/<source_name>
# vendor a tiny fixture (5-20 rows) representative of the source shape
touch tests/test_<source_name>_transform.py
```

Test at least:
- Fixture-in → known node count / edge count out.
- One representative row's fields all present with the expected CURIE format.
- One cross-ref edge produced with the expected target CURIE.
- Absent optional columns handled without raising.

```bash
poetry run pytest tests/test_<source_name>_transform.py -v
poetry run tox  # runs the full gate; must pass
```

**Gate 8 — the new tests pass; `tox` passes (or fails only on pre-existing master issues you didn't introduce).**

### Phase 9 — Ship

Use the `branch-triage-ship` playbook to land the PR cleanly:

- Branch name: `feat/add-<source_name>-transform`.
- PR title: `Add <SourceName> transform: <one-line what-it-brings>`.
- PR body: paste the delta note from Phase 2, the entity model table from Phase 3, and the cross-ref table from Phase 4. Reviewers can see the *design* alongside the code.
- Link the tracking issue (`Closes #NNN`) if there is one.

**Gate 9 — PR merged into master.**

### Phase 10 — Post-merge

- Bump the merged KG (if this is release-adjacent): re-run merge and follow `kg-release`.
- If the transform introduces a new CURIE prefix, add a docstring or note in `docs/` for future consumers.
- Close the tracking issue and any related sub-issues.
- If the new transform belongs in `download.yaml`'s active set (not commented out), verify the CI download / transform smoke test path.

**Gate 10 — issue closed; a downstream release run (or CI merge run) exercises the new transform without error.**

## Templates

### Design note skeleton

```markdown
# Design note — add <SourceName> transform

## What it uniquely provides
<one paragraph>

## Delta vs existing transforms
- Overlaps with: <existing sources>
- Adds beyond overlap: <bullets>
- Merge policy for overlap: <close_match / prefer this / prefer incumbent>

## Entity model
<table from Phase 3>

## Cross-refs
<table from Phase 4>

## Open questions
<bullets>
```

### Transform scaffold checklist (parallel to CLAUDE.md)

```
[ ] kg_microbe/transform_utils/<name>/__init__.py
[ ] kg_microbe/transform_utils/<name>/<name>.py                 (class, run())
[ ] kg_microbe/transform_utils/constants.py                    (<UPPER> = "<name>")
[ ] kg_microbe/transform.py                                    (DATA_SOURCES entry)
[ ] download.yaml                                              (source entry)
[ ] merge.yaml                                                 (nodes/edges paths)
[ ] kg_microbe/transform_utils/custom_curies.yaml              (if new prefix)
[ ] tests/test_<name>_transform.py                             (fixture + assertions)
[ ] tests/resources/<name>/                                    (fixture data)
```

## Companion skills

- `deep-research` — Phase 1 research
- `audit-mappings` — Phase 2 detection of already-hardcoded CURIEs for the source
- `kgm-freshness-check` — Phase 2 overlap analysis
- `metpo-ontology` / `metpo-proposal` — Phase 3 if new phenotype predicates needed
- `chemical-mapping` — Phase 4 if the source has chemical cross-refs
- `kg-model-review` — Phase 7 verify
- `kg-path-review` — Phase 7 verify
- `branch-triage-ship` — Phase 9 ship

## Failure modes to watch for

- **Skipped Phase 2** — ingesting a source that duplicates an existing one, adding noise without value.
- **Prefix collision** — using a CURIE prefix that's already registered to another source. Every use of the prefix in the codebase must resolve to the same authoritative source.
- **Local phenotype predicates** — inventing `kgmicrobe.trait:*` local predicates instead of routing through METPO. Every trait predicate needs a home in the METPO ontology or a formal proposal.
- **Skipped cross-refs** — ingesting the source's rows but ignoring its native cross-refs. The merge won't magically discover them; every cross-ref lands as an explicit edge or it doesn't exist.
- **Hidden hardcoded mappings** — a hardcoded `if "keyword" in name: return "CHEBI:xxxx"` in the transform is a curation file in disguise. Move it to `mappings/` before the PR lands.
- **Ingesting non-standard licenses without vetting** — some sources (e.g. KEGG partial data) are restricted from redistribution. Check the license in Phase 1, decide the vendored-vs-download strategy accordingly, and record the choice in the `download.yaml` NOTE.

## Notes on this repo (kg-microbe)

- The base `Transform` class in `kg_microbe/transform_utils/transform.py` provides node/edge writer objects and consistent headers; use them.
- The three most useful reference transforms:
  - `bacdive/` — large per-record JSON, multi-category, cross-refs.
  - `mediadive/` — REST-API-with-caching + ingredient decomposition.
  - `bactotraits/` — curated CSV with wide column-oriented traits.
- `data/transformed/<name>/` is the canonical output location. It's not currently blanket-gitignored — decide during Phase 8 whether the outputs are small enough to commit for CI fixtures or should be gitignored (they usually should).
- Multiprocessing is auto-enabled for `metatraits` and `metatraits_gtdb`; if the new source is > 50 K rows, mirror that pattern (see `metatraits_gtdb/` for a working example).
