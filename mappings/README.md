# Chemical Mappings

This directory contains unified chemical mapping resources for KG-Microbe.

**MIM input and publication boundary:** `mim_reviewed_release.json` pins the
validated export from immutable upstream commit
`1848b0fe521bc2462f165912fcf92d09ad9a8cec`, not a floating sibling checkout or a
new release tag. Its complete product partition is 1,747 supported exact mappings
and 1,252 withheld rows. Only the supported table is admitted as MIM mapping
input; withheld rows are a review backlog, not a global scientific denylist.

Use the [reviewed-release workflow](../docs/MIM_REVIEWED_RELEASE.md) to validate
the source archive, manifest, review and supported/withheld/disposition hashes,
then build a candidate in a new `data/` directory. Review the candidate,
quarantine, convergence and real consumer routes before an explicit paired
change to the unified artifact and `ingredient_mappings.sssom.tsv`. The
[dated acceptance record](../docs/reviews/mim-admission-20260925/PROMOTION.md)
tracks pending/final checks and installation separately. Neither the pin nor
candidate generation automatically installs mappings, runs transforms, or
certifies a merged KG for release.

The legacy additive consolidator is blocked while the pin exists, including
`--dry-run` and `--allow-stale-vendored`, because historical seeding, sibling
sync and alias propagation can reintroduce unreviewed claims. Do not use those
old paths as a production refresh. Legacy architecture below is retained for
interpreting older artifacts, not as new scientific approval of their aliases.

To check the committed artifact's exporter provenance without regenerating it:

```bash
make mapping-provenance
# Include the current code/config and installed-library inventory:
poetry run python -m scripts.mapping_provenance --context
```

`MATCH`, `DRIFT`, and `UNRECOGNIZED_EXPORTER` are nonblocking observations, not
scientific mapping validation. Malformed or missing inputs still fail. Do not
rebuild through the legacy additive route merely to silence drift (#973).
New conservative candidate reports also record a portable code/config hash set,
the dependency lock and actual installed library versions, and reject changes
during generation. This is an explicit conservative superset, not a claim to
capture every operating-system dependency (#974).

## Unified Chemical Mappings

`mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` is the primary shared SSSOM mapping product read by transforms via `kg_microbe.utils.chemical_mapping_utils`. Producer-specific scoped fallback tables also exist and must be reviewed; replacing this file alone does not disable their lookups. Row types include:

1. xref-CURIE → primary-CURIE (`skos:exactMatch`)
2. canonical-name → primary-CURIE via `kgm.name:<slug>` (`skos:exactMatch`, `semapv:LexicalMatching`)
3. free-text synonym → primary-CURIE via `kgm.name:<slug>` (`skos:closeMatch`, `semapv:LexicalMatching`)
4. separately typed nonidentity assertions, including retained historical hydrate/recipe-equivalence relations; these must not be upgraded to exact ingredient identity

Per-entity attributes (`object_label`, `object_formula`, `object_category`, `source`) ride on every row as SSSOM extension columns and are reconstructed at read time by grouping on `object_id`. Validated with the `sssom` Python package on every write (LinkML JSON-schema + `check_all_prefixes_in_curie_map`).

Synonym rows use a synthetic `kgm.name:<slug>` subject namespace so free-text names have a CURIE subject (SSSOM requires this). Slugs are deterministic via `normalize_name` with spaces → `_`. The file covers CHEBI chemicals plus non-CHEBI ingredients (FOODON foods, UBERON anatomy, ENVO environments).

### Legacy primary-ID prefix preference

When an entity could be keyed by multiple CURIEs, the consolidator picks the highest-ranked prefix (see `_PRIMARY_PREFIX_RANK` in `scripts/consolidate_chemical_mappings.py`):

```
CHEBI = FOODON = ENVO = UBERON  (ontology-scoped, tied top)
  > PubChem                      (structured public registry)
  > CAS-RN = mediadive.ingredient (flat registry + mediadive fallback)
  > kgmicrobe.compound           (last-resort in-house mint)
```

The ontology tier is tied because the four prefixes cover disjoint scopes (chemicals, foods, anatomy, environments). `pubchem.compound:*` is preferred over `cas:*` because PubChem CIDs resolve to a structured chemistry record; CAS-RN is a flat registry code. `mediadive.ingredient:N` is the fallback minted by the MediaDive transform when nothing else resolves; `kgmicrobe.compound:*` is reserved for secondary metabolites and antibiotics with no public ID. See `best_primary()` in the consolidator for the exact selection logic.

### Per-entity attributes (SSSOM extension columns)

Every row carries the same per-entity values, reconstructed at read time by grouping on `object_id`:

| Column | Description |
|--------|-------------|
| `object_id` | Primary key — picked from the per-row candidates using the prefix preference above. `CHEBI:*` for chemicals; `FOODON:*`, `UBERON:*`, `ENVO:*` for foods, anatomy, and environmental substrates; `pubchem.compound:*` / `cas:*` / `mediadive.ingredient:*` / `kgmicrobe.compound:*` as progressively lower-ranked fallbacks. |
| `object_label` | The entity's canonical name (priority-resolved). |
| `object_formula` | Chemical formula when available (chemicals only); priority-gated. |
| `object_category` | Biolink category. Downstream transforms read it instead of deriving it from the CURIE prefix. Values: `biolink:ChemicalSubstance`, `biolink:Food`, `biolink:AnatomicalEntity`, `biolink:EnvironmentalFeature`, etc. |
| `source` | Pipe-delimited provenance tags (one per contributing loader). |

Synonyms emit one row each (subject `kgm.name:<slug>` + `comment="synonym"`). Xrefs emit one row each (subject = the equivalent CURIE).

### Legacy priority system

Multiple sources may assert a name or formula for the same `id`. Higher priority wins outright; within the same priority band, the first-loaded non-empty value is retained. Synonyms, xrefs, and sources **always** accumulate (set union).

| Priority | Source tag(s) | Meaning |
|---|---|---|
| 11 | `mediaingredientmech_reviewed` | Historical MIM loader priority and asymmetric-match mechanism. The current refresh admits only the immutable export's supported exact rows and checks native scope; the source tag is not human-curator signoff or proof of every propagated alias. |
| 10 | `culturebotai_reviewed` | Evidence-based, manually reviewed media-ingredient mappings from the CultureBotAI project. |
| 5 | `manual_annotation*`, `manual_corrections*`, `metatraits_manual*`, `metatraits_chemical_synonyms*`, `metatraits_special_chemicals*` | Expert in-repo curation. |
| 2 | `chebi_xrefs` | ChEBI ontology's own xref table. Authoritative for xrefs but not preferred for names. |
| 1 | Everything else (BacDive, MediaDive, KEGG, etc.) | Automatic mappings. |

Normalized-name collisions do not merge records by name; instead, the name lookup index chooses a single winner deterministically. The winner is picked by highest source priority, then by the primary-ID prefix rank described above, and if still tied, by first insertion. Non-CHEBI categories are ontologically disjoint from CHEBI and from each other, so a FOODON food and a CHEBI chemical with the same label remain distinct rows.

### Historical inputs and current admission boundaries

This inventory explains the old additive artifact. File presence alone is not
independent claim provenance or approval to replay it in a conservative refresh.
The selected reconstruction inputs and their exact hashes are reported by
`scripts/refresh_reviewed_mim.py`; native ordinary xrefs are not automatically
converted to exact identity.

| # | Source | Priority | Present on disk? | Notes |
|---|---|---|---|---|
| 1 | `mappings/chemical_mappings.tsv` | 1 | removed (seeded from unified baseline) | Legacy KEGG/BacDive primary mappings. |
| 2 | `data/raw/compound_mappings_strict.tsv` | 1 | runtime input | MediaDive fallback input; excluded as blanket independent candidate-reconstruction evidence because of historical KGM feedback. |
| 3 | `data/raw/compound_mappings_strict_hydrate.tsv` | 1 | runtime input | Supplied hydrate candidates require native chemical-parent and water-scope evidence, not water stripping or exact hydrate/base equivalence. Also excluded from blanket candidate reconstruction. |
| 4 | `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` | 1 | present | BacDive antibiotic/metabolite mappings (~197). |
| 5 | `kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv` | 2 | removed (seeded from unified baseline) | ChEBI xref table (CAS, KEGG, PubChem, …). |
| 6 | `kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv` | 5 | present | Trait-dataset expert corrections. |
| 7 | `mappings/culturebotai_reviewed_ingredients.tsv` | 10 | present | **Authoritative.** CultureBotAI reviewed ingredients. |
| 8 | `mappings/ingredient_mappings.sssom.tsv` | 11 | paired promotion target | Install only the byte-exact supported product pinned by `mim_reviewed_release.json`, together with the accepted unified candidate. Expected reviewed product: 1,747 exact rows. No sibling auto-sync or withheld/source-table substitution is permitted by the current workflow. Check the acceptance record for installation status. |

Historically, missing priority-1/2/5 inputs could be skipped while the additive
loader re-ingested its own baseline with priority inferred from source tags.
That lossy provenance is precisely why the reviewed workflow reconstructs
affected claims from explicit current evidence and quarantines unsupported
history. Every selected reconstruction input is now required; a missing input
fails the candidate build.

### Historical additive regeneration (not a production procedure)

The following describes older exporter behavior only. Full consolidation,
including preview and stale-vendored fallback, refuses to run while the reviewed
pin exists. Use the immutable candidate/paired-promotion workflow above, not
the old script invocation or sibling auto-sync mechanism.

`--dry-run` exports to a scratch path rather than skipping the write, so the
`sssom` round-trip validation still runs and the preview reports a real delta —
added and removed counts separately, with samples. A net row count hides the
shape of a change: the #946 refresh was +1,814 net, which was 2,093 added
against 279 removed, and the removals were the half worth checking. Measure
against the artifact you are about to ship, not an earlier run of it — the
figures here were first written from run 1 and were each off by the 2 rows the
convergence note below predicts.

Historical pipeline order (disabled for pinned refreshes):
1. Seed from the existing `mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` (priority reconstructed per row from `source` labels).
2. Layer in any still-present legacy inputs (absent ones are skipped).
3. Load `mappings/culturebotai_reviewed_ingredients.tsv` (priority=10).
4. The old `sync_mim_sssom()` read `$MEDIAINGREDIENTMECH_ROOT` or a sibling checkout and could use a stale vendored fallback (#947). **Neither path is used or permitted by the current pinned refresh.** The exact supported bytes now come from the validated immutable bundle, and installation is explicit and paired.
5. Load `mappings/ingredient_mappings.sssom.tsv` (priority=11) — parsed and validated with the `sssom` Python package before any row is ingested.
6. Enrich from `data/raw/chebi.db` via OAK (labels only fill when no higher-priority name already exists; aliases always accumulate).
7. **Harvest CHEBI xref labels via OAK** — for every CHEBI CURIE that appears as an xref but has no primary row of its own, pull its label + aliases into the owning record's synonyms. Closes the gap where a non-CHEBI primary (or a secondary CHEBI ID) carries an xref whose preferred term would otherwise be lost.
8. **Propagate names across equivalent-CURIE records via xrefs** — for every record, any xref that is itself a primary key of another record contributes that record's `canonical_name` + synonyms into this record's synonyms. Symmetric (both sides pick up each other's names), snapshot-based (no feedback), no record merge or deletion.
9. Resolve name-index conflicts by priority (highest-priority name mapping wins); no cross-CURIE merge pass is performed.
10. Write `kgmicrobe_unified_entity_mappings.sssom.tsv.gz` and round-trip-validate it with the `sssom` package.

Note that step 1 seeds from the script's own previous output, so the artifact is
not a pure function of its inputs: a run can derive names that the previous run
created, and re-running immediately may add a handful of rows. This converges
rather than growing without bound — in the #947 refresh, run 2 added 2 rows over
run 1 and run 3 was byte-identical to run 2.

**The run now tells you which state you are in** (#948). It ends with either
`Converged: identical to the seed (N triples). This is the fixed point.` or
`Not yet converged: N added, M removed ... re-run to reach the fixed point
before committing.` Before that, regenerating to check a committed artifact
produced a non-empty diff that looked exactly like non-determinism, and nothing
said whether what had been committed was the fixed point or one step short.

For current acceptance, build a second conservative candidate using the first
as baseline under unchanged pinned inputs/code and compare semantic rows and
SHA256 of the entire gzip file. Do not run the blocked additive consolidator
to chase its historical fixed-point message.

Everything else in the artifact is a pure function of its inputs. Each row keeps
the `mapping_date` it was first published with, so a refresh diffs only the rows
that changed rather than all of them; `mapping_set_version` and the header
`mapping_date` are the newest row date, not the clock; and the gzip archive is
written with `mtime=0`, so identical content always compresses to identical
bytes. `mapping_tool_version` now carries the SHA-256 of
`scripts/consolidate_chemical_mappings.py` itself rather than the commit the
checkout sat on (#961) — a commit named code that may not be the code that ran,
since the run necessarily precedes the commit carrying its output, and it moved
on every commit that touched anything. The hash covers that one script, not the
modules it imports (#974). The tool's name stays in `mapping_tool`, where SSSOM
puts it (#971).

A content hash is exact but not a lookup: `git show <sha>:path` works for a
commit, and nothing equivalent works here (it is not the git blob hash either,
which is taken over `blob <len>\0` + content). To find the commits whose copy
of the exporter produced an artifact (#972):

```bash
TARGET=$(gunzip -c mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz |
  sed -n 's/^# mapping_tool_version: "sha256:\(.*\)"/\1/p')
git log --all --format=%H -- scripts/consolidate_chemical_mappings.py | while read -r c; do
  h=$(git show "$c:scripts/consolidate_chemical_mappings.py" | shasum -a 256 | cut -d' ' -f1)
  [ "$h" = "$TARGET" ] && echo "$c"
done
```

### Usage Examples

```bash
# Find an ingredient by name (skipping the YAML metadata block)
gunzip -c mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz | grep -v '^#' | grep -i "glucose"

# All rows for an id
gunzip -c mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz | grep -v '^#' | awk -F'\t' '$2=="CHEBI:42758" || $4=="CHEBI:42758"'

# Ingredients carrying the MediaIngredientMech provenance tag
gunzip -c mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz | grep -v '^#' | grep mediaingredientmech_reviewed | head

# All FOODON foods (object_id is the 4th column)
gunzip -c mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz | grep -v '^#' | awk -F'\t' '$4 ~ /^FOODON:/'
```

Prefer the Python reader API (`kg_microbe.utils.chemical_mapping_utils.find_chebi_by_name`, `find_chebi_by_xref`, `find_chebi_by_formula`, `get_canonical_name`, `get_category`) inside transforms — it loads the file once per process and serves O(1) lookups. `find_chebi_by_name` is a legacy name; it returns any supported CURIE, including FOODON / UBERON / ENVO.

### Known Limitations

- **CAS format.** Stored as `cas:<dash-separated>` xrefs (e.g. `cas:7647-14-5`). Consumers must include the `cas:` prefix.
- **Native xref scope.** A native CAS annotation does not by itself authorize a new exact equivalence or a replacement for a source salt/mixture/preparation. The conservative builder admits explicit identities separately from ordinary ontology xrefs.
- **Historical priority inference.** The blocked additive reseed reconstructs priority from source-label prefixes; those aggregate labels cannot establish independent support for each alias. The conservative reconstruction and direct fallback audit address separate parts of that problem.

### Reviewed ingredient identity exclusions

`ingredient_identity_exclusions.tsv` rejects specific ingredient-name/target
groundings and symmetric false cross-reference pairs. It does not ban or remap
the ontology identifiers: `CHEBI:78018` remains dodecylphosphocholine and
`FOODON:03302071` remains green kidney bean, and `CHEBI:78020` remains
heptacosanoate, with their native ontology assertions untouched. The latter target
also rejects casamino-acid names, preventing a fallback from one false chemical
identity to another. Casein digests, peptones, and broths must not resolve to
these unrelated targets.
Further false fallbacks to the acylcarnitine `CHEBI:84843` and the sausage
`FOODON:00002992` are excluded under the same scoped policy. A mapping record
containing only rejected rows is removed from the unified mapping artifact;
this never removes its legitimate native ontology node or assertions.
The policy is enforced by the unified reader, consolidation (including reseeding,
propagation, and export), MediaDive legacy/embedded/solution fallbacks, and
MetaTraits special overrides. Other supported groundings can still resolve;
otherwise MediaDive preserves an ingredient/solution ID and MicrobeDecoder its
normal unresolved compound placeholder. MetaTraits preserves explicitly reviewed
source-local compounds where declared; other unresolved observations do not
receive an unrelated external chemical identity.

The supported MIM product is not hand-edited. Correct upstream claims in their
own repository and validate a newly pinned complete export. Local target-scoped
guards protect stale unified and producer fallback routes; they do not authorize
rewriting a supported upstream assertion while claiming byte-exact consumption.

For a bounded refresh that does not synchronize siblings or invoke OAK:

```bash
poetry run python scripts/consolidate_chemical_mappings.py \
  --identity-policy-only --output data/identity-candidate.sssom.tsv.gz
```

Review the candidate before replacing the published mapping artifact. This mode
streams the existing unified artifact, retains unrelated serialized rows and
asymmetric/hydrate assertions, and changes only reviewed lexical/xref groundings
and poisoned labels. Output is atomically published only after SSSOM validation;
rejected canonical-name assertions are removed, not rewritten into new triples
carrying historical dates. Surviving native aliases/xrefs carry the corrected
`object_label`, which also feeds the runtime canonical-name index. All retained
triple dates remain unchanged; a later full export dates new canonical assertions.
input and output cannot be the same path. The mapping-set description records a
SHA-256 of the policy and shared implementation. Reapplying
`refresh_identity_policy(candidate, second_candidate)` is byte-idempotent with
unchanged exporter/policy code. The full consolidator enforces the same policy.

### Validation

```bash
poetry run python mappings/validate_manual_mappings.py
```

Checks every manually curated ChEBI ID (priority-5 and priority-10 rows that are not `chebi_xrefs`) against OLS4 labels. Output: `mappings/manual_mapping_audit_report.tsv`.

### Skill

A legacy Claude Code skill (`.claude/skills/chemical-mapping/SKILL.md`) contains
mapping architecture and debugging guidance. For current refresh, publication
boundaries and acceptance, use the reviewed-release runbook above; historical
skill text does not override immutable pinning or authorize sibling auto-sync.

## Maintenance

Last updated: 2026-09-25

Maintainer: KG-Microbe team

For mapping errors or questions, open an issue on the KG-Microbe GitHub repository.
