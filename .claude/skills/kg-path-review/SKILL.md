---
name: kg-path-review
description: Walk and validate multi-hop semantic paths in KG-Microbe transform outputs. Use to uncover modeling bugs where the KG does not accurately represent the raw data — cross-contamination, self-loops, phantom intermediates, false-majority emission, missing expected paths, cardinality outliers — by combining open-ended path exploration with built-in archetype checks calibrated against the raw source data.
---

# KG-Microbe Path Review

## Purpose

`kg-model-review` validates **single-edge** conformance (KGX/Biolink/METPO/prefix). This skill focuses on **multi-hop path semantics**: does the path from a subject through one or more predicates accurately represent the underlying source data? Most of the load-bearing claims in KG-Microbe are paths, not single edges:

- `organism → grown_in → medium → has_part → solution → has_part → ingredient → has_role → role`
- `organism → has_phenotype → trait` *(routed through majority-label logic)*
- `subclass_of` chains through ontology terms

When the modeling diverges from the raw data, single-edge checks pass and the path silently lies. This skill is for catching that.

## Bug archetypes this skill targets

Each archetype below has a real fix in the recent history; the skill ships a check for each.

| Archetype | Real example | Symptom in the KG |
|---|---|---|
| **Cross-contamination** | mediadive medium 92a (solutions [162, 5629 vitamin, 161]) leaked vitamin compounds onto `solution:161` because `ingredients_dict` accumulated across solutions but edges were emitted with the *current* iteration's solution_curie. | A solution's outgoing `has_part` set is a strict superset of its raw recipe; or two sibling intermediates share the same downstream set. |
| **Phantom self-loop** | Same bug — `solution:161 → solution:161` because solution 162's recipe references 161 as a sub-solution and that reference accumulated into 161's iteration. | `subject == object` on edges where the predicate semantics forbid it (`has_part`, `produces`). |
| **Phantom child** | Same bug — `solution:161 → solution:5629` even though 161's raw recipe never references 5629. | An intermediate links to another intermediate it has no source-data justification for. |
| **False-majority positive** | Tier-2 metatraits resolver copied `pred = micro_mapping["biolink_predicate"]` and emitted a positive edge for false-majority rows (catalase-negative organisms got `biolink:has_phenotype catalase`). Tier-3 routed via `_apply_majority_label_to_predicate`; Tier-2 had no equivalent guard. | `org has_phenotype X` for organisms whose underlying observation is `false`. Only detectable by joining edges back to the metatraits source counts. |
| **Predicate semantic mismatch** | `kg_microbe/transform_utils/.../metatraits.py` previously emitted `biolink:capable_of` for carbon-source rows; corrected to `METPO:2000006` (carbon source). | A predicate appears with subject/object pairs that are correct in isolation but wrong in domain — e.g. organism `capable_of` an *ingredient*. |
| **Cardinality outlier** | A solution claiming 200 ingredients (raw recipe has 8) usually means cross-contamination. A medium with zero ingredients usually means a join failure. | Degree-distribution outliers per `(subject_prefix, predicate)` versus the raw-data baseline. |
| **Cycle in a DAG predicate** | `biolink:subclass_of` is asserted to be acyclic; a cycle means the post-process closure has a bug. | A reachability cycle on `subclass_of` or other tree predicates. |
| **Gap (missing expected path)** | Organism known from BacDive to grow on medium X, but no `is_grown_in` edge in the merged KG — usually a strain→species join failure. | Raw evidence of a relation exists but the KG path does not. |

## Authoritative artifacts

| File | Format | Role |
|---|---|---|
| `.claude/skills/kg-path-review/kg_path_review.py` | CLI | Path walker + archetype checker |
| `data/transformed/<source>/edges.tsv` | KGX | Per-source edge index walked by the script |
| `data/transformed/<source>/nodes.tsv` | KGX | Used to resolve labels and categories |
| `data/raw/mediadive/solutions.json` | source ground truth | Cross-checked by the `recipe-vs-raw` archetype |
| `data/raw/mediadive/media_detailed.json` | source ground truth | Cross-checked for medium → solution coverage |
| `data/raw/bacdive_strains.json` | source ground truth | Cross-checked for organism → trait observations and majority labels |
| `kg_microbe/transform_utils/custom_curies.yaml` | prefix registry | Used to label novel CURIEs in path reports |

## Workflow

### 1. Pick a target

Three entry points, in increasing scope:

1. **Single-CURIE walk** — start from a node, walk N hops, render as a tree. Cheapest. Use when investigating one concrete report (e.g. "why does medium:92 look like a vitamin solution?").
2. **Archetype check** — run a named archetype across all matching subjects in a transform's `edges.tsv`. Use when sweeping for one bug class (e.g. "find all cross-contamination").
3. **Predicate sweep** — degree-distribution + category-pair audit for one predicate. Use to discover unfamiliar bug shapes.

### 2. Run the script

```bash
# Single-CURIE outgoing walk, depth 3
poetry run python .claude/skills/kg-path-review/kg_path_review.py walk \
    --start "mediadive.solution:161" \
    --transform mediadive \
    --depth 3

# Recipe-vs-raw archetype: every solution in mediadive vs solutions.json
poetry run python .claude/skills/kg-path-review/kg_path_review.py archetype recipe-vs-raw \
    --transform mediadive

# Self-loop sweep across all sources, restricted to has_part / produces / consumes
poetry run python .claude/skills/kg-path-review/kg_path_review.py archetype self-loops \
    --predicate biolink:has_part --predicate biolink:produces --predicate biolink:consumes

# Tier-2 false-majority detection: flag has_phenotype / capable_of edges whose
# underlying metatraits row has majority_label=false
poetry run python .claude/skills/kg-path-review/kg_path_review.py archetype false-majority \
    --transform metatraits

# Cardinality outliers for organism → medium
poetry run python .claude/skills/kg-path-review/kg_path_review.py archetype cardinality \
    --subject-prefix NCBITaxon: --predicate biolink:located_in --top 20

# Subclass-of cycle detection in the ontologies transform
poetry run python .claude/skills/kg-path-review/kg_path_review.py archetype subclass-cycles \
    --transform ontologies
```

### 3. Triage findings

Findings are grouped by **archetype** and emitted with severity:

| Severity | Meaning | Action |
|---|---|---|
| **CRITICAL** | KG path contradicts raw source data (e.g. solution:X has ingredients absent from `solutions.json[X].recipe`). | File a transform bug. Almost always a code defect. |
| **WARNING** | KG path is internally inconsistent (self-loop on `has_part`, subclass cycle). | Investigate; usually a code defect, occasionally an upstream ontology issue. |
| **INFO** | Cardinality outlier or unusual but legal pattern. | Manual review; sometimes legitimate (e.g. a complex undefined medium genuinely has 200 ingredients). |

Always check whether the symptom recurs across the source — a single CRITICAL on one row is sometimes a data quirk; the same CRITICAL across thousands of rows is always a transform bug.

### 4. Write a regression test

If a CRITICAL pattern is confirmed as a transform bug, add a regression test under `tests/` *before* fixing — the test should fail on current code and pass on the fix. Pattern to follow:

- Build the smallest possible source-data fixture that reproduces the path bug.
- Assert the path *property* (no self-loops on has_part, recipe-vs-raw equality, etc.), not the literal output, so the test survives unrelated transform refactors.

The mediadive cross-contamination fix is the canonical worked example — see `kg_microbe/transform_utils/mediadive/mediadive.py:943-966` for the fix and the commit message for the diagnosis.

## Archetypes shipped

### `recipe-vs-raw` (mediadive)

Walks every `mediadive.solution:N` in `data/transformed/mediadive/edges.tsv`, collects outgoing `has_part` objects, and diffs against `data/raw/mediadive/solutions.json[N].recipe`. Reports:

- **CRITICAL** ingredients in KG but not in raw recipe (cross-contamination, the mediadive bug)
- **WARNING** ingredients in raw recipe but not in KG (ID-resolution failure)
- **WARNING** self-loops `solution:N → solution:N`

### `self-loops`

Generic. Loads edges, filters by predicate, emits any row where `subject == object`. For most predicates (`has_part`, `produces`, `subclass_of`, `located_in`) self-loops are semantically invalid.

### `false-majority` (metatraits)

Label-based proxy for the Tier-2 false-majority bug. Scans every `has_phenotype` / `capable_of` edge whose subject is `NCBITaxon:*` and flags ones whose object **label** contains explicit negation phrases (`absent`, `no growth`, `does not`, `fails to`, `lacks`, `unable to`).

A canonical-polarity exclusion list (`gram negative`, `catalase positive`, `oxidase variable`, etc.) prevents false positives where the trait NAME contains "negative"/"positive" as part of the canonical label rather than as a polarity flag — without this, ~36k legitimate gram-negative organism edges flooded the report. The `skipped_canonical_polarity` stat exposes how many such edges the proxy correctly ignored.

The proxy is **label-shaped only**. A true ground-truth check requires joining to `bacdive_strains.json` majority counts; e.g. an organism incorrectly emitted as `has_phenotype catalase` (no negation in label) when its source row says `majority_label=false` would slip through. Zero hits here does NOT prove absence of false-majority bugs.

### `family-mismatch`

Flags edges whose subject is from a quality / role / unit ontology while the predicate semantics demand a substrate-like subject. Concretely catches:

- BacDive isolation-source rows where `PATO:0000383 'female'` ended up as `location_of` of an organism (fixed 2026-05-02 via trust-policy in `kg_microbe/utils/isolation_source_mapping_utils.py`).
- Madin et al compositional-habitat rows where `PATO:0001596 'increased depth'` became a substrate (fixed 2026-05-03 via substrate/quality partition in `kg_microbe/transform_utils/madin_etal/madin_etal.py`).

Disallowed subject prefixes: `PATO:`, `UO:`, `METPO:`. Substrate-shaped predicates: `biolink:location_of`, `biolink:has_part`. Override either set with `--predicate`. Catches a different bug class from `self-loops` (cycles) and `cardinality` (fanout): this is about the *kind* of subject vs the *meaning* of the predicate.

### `orphan-edges`

For each transform, scan `edges.tsv` and assert every endpoint has a node row in the same `nodes.tsv`. Orphan edges break Neo4j loaders and KGX validators, and they're the canonical symptom of a transform that emits an edge without emitting the node it references. Example fix: BacDive emits `mesh:D000001` as an isolation-source target via the SSSOM, so the bacdive transform must also emit a stub `mesh:D000001` node row (handled by `STUB_ONTOLOGY_PREFIXES` in `isolation_source_mapping_utils.py`).

### `cardinality`

Per `(subject_prefix, predicate)` pair, emits the top-K subjects by out-degree. Compare against expected envelopes:

| Pair | Expected envelope | Anomaly |
|---|---|---|
| `mediadive.solution → has_part` | 1–20 ingredients | >50 = likely cross-contamination |
| `mediadive.medium → has_part` | 1–8 solutions | >20 = likely accumulator bug |
| `NCBITaxon → has_phenotype` | 1–500 traits | >2000 = likely false-majority leak |
| `NCBITaxon → located_in` (medium) | 1–30 media | >100 = likely strain dedup failure |

### `subclass-cycles`

DFS on `biolink:subclass_of` edges per transform. Reports any cycle — these break ELK and hierarchical queries.

### `predicate-domain` (cross-check with kg-model-review)

For each `(predicate, subject_category, object_category)` triple, count rows. The Biolink Model defines domain/range constraints; this archetype reports triples that are unusual *in distribution* (rare combinations that may indicate a routing bug like the carbon-source `capable_of` regression).

## Open-ended exploration

The `walk` subcommand is for ad-hoc investigation. **Note**: BacDive uses `kgmicrobe.strain:bacdive_<id>` (not `NCBITaxon:*`) as the strain-level subject — `NCBITaxon:*` rows in BacDive are usually parent species pointing *down* to strains via `biolink:location_of`, not the other way around. Walking from a species ID will return nothing useful; walk from a strain CURIE instead.

```bash
# Outgoing paths from a BacDive strain, depth 3
poetry run python .claude/skills/kg-path-review/kg_path_review.py walk \
    --start "kgmicrobe.strain:bacdive_7249" \
    --transform bacdive \
    --depth 3 \
    --max-fanout 8

# Reverse walk: who points at this medium?
poetry run python .claude/skills/kg-path-review/kg_path_review.py walk \
    --start "mediadive.medium:92" \
    --transform mediadive \
    --reverse \
    --depth 2
```

Output is a labeled tree. Nodes are decorated with category and (where available) source-data attestation (`✓ in raw recipe`, `✗ not in raw recipe`).

## Skill checklist

Before declaring a path review clean:

- [ ] `recipe-vs-raw` reports zero CRITICAL on mediadive
- [ ] `self-loops` reports zero on `has_part`, `produces`, `consumes`, `subclass_of`, `has_attribute`
- [ ] `false-majority` reports zero on metatraits (the proxy is label-shaped only — see archetype docstring for limits)
- [ ] `family-mismatch` reports zero on PATO/UO/METPO subjects of `location_of` / `has_part`
- [ ] `subclass-cycles` reports zero
- [ ] `cardinality` outliers reviewed manually; none indicate accumulator-style bugs
- [ ] `orphan-edges` reports zero per transform (every edge endpoint has a node row)
- [ ] No `⚠️ data/merged/merged-kg.tar.gz is older than transform output(s)` warning printed by the script — if present, re-merge before drawing conclusions about the merged KG
- [ ] Spot-checked at least one organism end-to-end via `walk`

## Operational gotchas

These have all bitten in interactive review sessions. Worth pinning:

1. **Snapshot dirs under `data/transformed/`**. Old merge snapshots like `merged_20260423_nometatraits/` get treated as transforms by every aggregate archetype unless the script filters them out (see `_list_transform_dirs()` and `NON_TRANSFORM_DIR_PREFIXES`). The same subject ID then triple-counts across the live transform plus each snapshot — most visible in `cardinality`. Either prune the snapshots or always pass `--transform <name>` for a clean scope.
2. **Stale-build mismatch**. The merged tar.gz can lag behind the transform outputs by minutes if you re-ran transforms but forgot `kg merge`. The script prints a warning at the top of every archetype run when it detects this (see `warn_if_stale_merge`), but archetype results read from `data/transformed/*/edges.tsv` so they will be fresh; merged-content checks (orphan integrity at merge layer, distribution stats) are NOT.
3. **Gram negative is a positive trait.** The `false-majority` proxy used to flag every `has_phenotype gram-negative` edge as suspicious because the substring matched "negative". `gram negative`, `catalase positive`, `oxidase variable` etc. are canonical taxonomic descriptors; the regex `_CANONICAL_POLARITY_TRAIT_RE` excludes them. If you add new polarity-bearing trait labels upstream (e.g., a new METPO `nitrate-reductase positive`), the regex's prefix list may need expansion.
4. **PATO 'female'/'increased depth' is not a location.** Both BacDive (host_sex) and madin_etal (compositional habitats) used to emit organisms `location_of` PATO qualities. The `family-mismatch` archetype catches this regression class. Same defense pattern lives in `kg_microbe/utils/isolation_source_mapping_utils.py:DISALLOWED_OBJECT_SOURCES`.

## See also

- `kg-model-review` — single-edge KGX/Biolink/METPO conformance (the layer below this skill)
- `kg-query` — interactive organism queries (consumer of validated paths)
- `audit-mappings` — finds hardcoded transform-side CURIE mappings (root cause of many path bugs)
- `kg_microbe/transform_utils/mediadive/mediadive.py:943-966` — the canonical fix the `recipe-vs-raw` archetype is calibrated against
- `kg_microbe/transform_utils/metatraits/metatraits.py:_apply_majority_label_to_predicate` — the routing the `false-majority` archetype validates
