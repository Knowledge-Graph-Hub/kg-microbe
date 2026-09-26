# Reviewed MIM releases in KGM

## Status and scope

The selected upstream input is the validated immutable export of
[commit `1848b0fe521bc2462f165912fcf92d09ad9a8cec`](https://github.com/CultureBotAI/MediaIngredientMech/commit/1848b0fe521bc2462f165912fcf92d09ad9a8cec),
not a newly published release tag. Its [locked-runtime validation run](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/36109949250)
passed review reproduction, complete export validation and SSSOM schema checks.
The user explicitly selected immutable-commit/export consumption; the schema-v2
`mappings/mim_reviewed_release.json` records that origin without relabeling the
old September 21 release. Its `candidate_only` mode controls candidate generation,
not permission to publish or silently replace production mappings. Paired
production promotion remains the separate reviewed step below.

The complete export contains 1,747 supported exact mappings and 1,252 withheld
rows (2,999 source assertions). Its three product files are byte-identical to the
previously reviewed `a8b26f007cdf5bdc7529ab13888d611f359e6aad` export; the manifest's
review hash changed with later upstream verifier provenance. Do not confuse this
full table with the separate opt-in 20-case ingredient-scope/history bundle.
The supported table is the only approved MIM mapping input. The withheld table
is a review backlog, **not a set of globally false assertions**. An independent
ontology/source can still support a claim absent from the supported table.
The release does not approve ingredient roles, components, or media regeneration.
Its review is agent-assisted/adversarial; do not label it human curator signoff.

## Build a candidate

From the repository root, download the exact source archive and complete validated
bundle to new evidence locations under `data/`:

```bash
curl --fail --location \
  --output data/mim-source-1848b0fe.tar.gz \
  https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/1848b0fe521bc2462f165912fcf92d09ad9a8cec

gh run download 36109949250 \
  --repo CultureBotAI/MediaIngredientMech \
  --name mim-reviewed-sssom \
  --dir data/mim-reviewed-1848b0fe

poetry run python -m scripts.refresh_reviewed_mim \
  --source-archive data/mim-source-1848b0fe.tar.gz \
  --release-directory data/mim-reviewed-1848b0fe \
  --output-directory data/mim-candidate-1848b0fe
```

The output directory must not exist. No sibling checkout or live ontology service
is consulted. Use `--data-root /path/to/current/data` only when intentionally
reviewing another raw/transformed snapshot, such as from an isolated worktree.
Every selected evidence file is required; absent inputs fail rather than silently
falling back to historical MIM exports.

Validation checks manifest/product hashes, SSSOM structure and CURIE prefixes,
supported-only predicate scope, counts, and the lossless supported/withheld
partition against complete-row hashes in `mapping-dispositions.tsv`.
For schema-v2 pins, validation additionally checks the entire source archive hash,
commit-named archive root, safe unique regular-file/directory members, the original
source SSSOM and review bytes against the manifest, and the pinned lock/workflow
bytes. The source archive is streamed without extracting or executing its code.
Malformed, missing, unsafe, floating or mismatched provenance aborts before
candidate output. Pin, source archive and CLI-code hashes are added to the atomic
candidate report's before/after input checks; verified provenance is retained in
`report.json` under `upstream_provenance`. This verifies source binding, not a new
scientific review or an online assertion that CI remains current.

## Immutable origin and reproducible export recipe

The versioned pin keeps strict legacy schema-v1 tagged-release support unchanged.
Schema v2 requires `origin=immutable_commit_export`, an exact 40-hex commit,
commit-addressed archive URL/SHA256, manifest and all three product SHA256 values,
the `reviewed_sssom_v1` recipe, Python 3.13, pinned `uv.lock` and workflow hashes,
and the upstream validation-run URL. Unknown fields, duplicate JSON keys,
unrecognized recipes and publication modes fail closed. Schema v1 does not accept
`--source-archive`; schema v2 requires it. The legacy additive consolidator remains
disabled while either version of the pin exists.

Pinned archive SHA256:
`33ff549d7a2bf34e943156e800e00149736a30dfc0a974f3ca9a9884358bfef2`.
Pinned complete manifest SHA256:
`9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af`.

The CI artifact is a convenient copy, not the sole durable origin: it expires.
If unavailable, retrieve the same commit-addressed source archive, verify its
SHA256 against the independently committed pin **before extraction/execution**,
and extract into a new directory beneath `data/`. Do not accept a different
archive hash, floating main checkout or silently regenerated review. Within the
verified source root, `reviewed_sssom_v1` means the following exact workflow:

```bash
env UV_PYTHON=3.13 uv sync --frozen
uv run --frozen python reports/sssom_completion_20260921/assemble_review.py --check
uv run --frozen python -m mediaingredientmech.export.reviewed_sssom \
  --review reports/sssom_completion_20260921/review.json \
  --output output/mim-reviewed-sssom
uv run --frozen python -m mediaingredientmech.export.reviewed_sssom \
  --review reports/sssom_completion_20260921/review.json \
  --output output/mim-reviewed-sssom --validate-only
uv run --frozen python scripts/validate_reviewed_sssom_schema.py output/mim-reviewed-sssom
```

Pass that complete output directory and the original archive to the KGM candidate
CLI. Its independently committed hashes must still match; the exporter does not
get permission to rewrite a pin based on newly generated bytes. Source and review
files are present in this exact immutable archive, so their binding is checked
locally rather than assumed from CI metadata. Do not reuse the September 21
release URL or swap the separate scoped ingredient bundle into this workflow.

## Why a simple file replacement is unsafe

The old unified artifact merges source tags per entity, then repeats the combined
tags on every alias and cross-reference. These tags cannot establish independent
support for individual claims. Historical synonym propagation also copied names
without copying source tags. Removing only stale `MIM:` identifiers leaves old
lexical matches active.

The conservative candidate reconstructs the affected exact-equivalence-connected
entities from current native ontology/stub records, explicitly selected independent
inputs, and the supported MIM table. Unknown historical claims go to quarantine,
not a global exclusion policy. Unrelated mappings and independently sourced
nonidentity relations must survive. Raw `UNIFIED_INGREDIENT_MAPPING.tsv` and
`complex_ingredients.tsv.gz` are deliberately not replayed.

Current reconstruction evidence is selected explicitly in
`scripts/refresh_reviewed_mim.py`: BacDive metabolite mappings,
Madin manual annotations, canonical chemical
mappings, and nine native ontology/stub node tables. The special-chemical table is
excluded because its history includes MIM-derived reconciliation, so it cannot
serve as blanket independent evidence for retaining old MIM claims. The raw
MicroMediaParam strict/hydrate tables are also excluded: their production history
includes KG-Microbe feedback, so they are not blanket independent evidence for
this migration. Existing non-MIM weak hydrate/recipe-equivalence relations remain
historical assertions, not newly scientifically validated. Hydration-incompatible
lexical identity claims are quarantined; stripping a water count never establishes
identity. Independently native labels/synonyms must support an existing hydrate
mapping's stated scope. Missing historical primary
and ChEBI-xref exports are not invented as additional evidence.

The retained repository inputs are historical KGM curation, not freshly reviewed
scientific evidence: the small canonical chemical table has local MetaTraits
curation history, Madin annotations predate or independently extend it, and the
BacDive metabolite table restores its archived pre-2026 manual input. Native
ontology names/aliases and explicit `same_as` identities can be reconstructed;
ordinary ontology `xref` annotations are not automatically promoted to exact
identity assertions.

Review `report.json`, the candidate, and quarantine before promotion. Check lost
entities, changed canonical names, identity cross-references, name collisions,
and actual runtime lookups. Repeat the build with the candidate as baseline to
check stability. Historical propagation across an already-removed identity edge
cannot be reconstructed perfectly from the lossy seed; the report is not a
claim of exhaustive scientific recuration.

The legacy full consolidator now refuses to run while the release pin is present,
including with `--dry-run` or `--allow-stale-vendored`: its additive seed and raw
companion paths would undo the migration. Its narrowly scoped
`--identity-policy-only --output ...` operation remains available; it does not
constitute a MIM refresh.

The input schema check also repairs two short rows in the canonical chemical
table by explicitly including the empty final `verified_date` cell. This changes
file bytes, not mapping content. Fingerprint-based consumers may nevertheless
require a rerun; do not overwrite their receipts to suppress that signal.
For this formatting-only change, the direct consumer is `ontologies_stubs`,
followed by its dependent GOLD transform. If rebuilding the current, still
pre-migration graph after this PR, run the following. This does **not** install
the new MIM release.

```bash
poetry run kg transform -s ontologies_stubs -s gold
poetry run kg merge -y merge.yaml
```

## Promotion, transforms, and merge

Candidate generation does not publish files or run production transforms. Once
the delta is accepted, promote **both** the reviewed unified candidate and the
supported MIM table to their canonical mapping paths in a reviewed change:

- `mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz`
- `mappings/ingredient_mappings.sssom.tsv`

Keep release hashes, input fingerprints, quarantine disposition, and runtime
regression evidence with that review. Update the vendored-set shape test to
expect the intentionally exact-only supported release; preserve the separate
legacy asymmetric-semantics mechanism tests. Do not stamp freshness receipts to
make existing outputs appear current.

**Fallback gate:** 55 of the 194 special-chemical overrides have explicit MIM
lineage (17 from commit `4617f84b6`, 38 from `0444faf1e`). MetaTraits and its GTDB
variant read this table directly, independently of the unified artifact. Excluding
it from candidate generation does not remove those runtime routes. Review the
exact assertions and fallback behavior before claiming supported-only production
integration; appearing in a withheld target list alone is not grounds for removal.

If only these mapping artifacts change and other inputs/code remain fresh, the
canonical transform closure is nine producers:

```bash
poetry run kg transform \
  -s ontologies_stubs -s bacdive -s mediadive -s madin_etal \
  -s metatraits -s metatraits_gtdb -s bactotraits -s gold -s microbedecoder

poetry run kg merge -y merge.yaml
```

`ontologies_stubs` reads the vendored MIM table as well as the unified artifact.
GOLD depends on those stub outputs; BactoTraits and MediaDive consume BacDive
outputs. Changes to shared runtime utilities, identity policy, ontology outputs,
or other inputs can expand the closure, including all 15 canonical producers.
Run the freshness check against the actual checkout and data before deciding.

After merge, run KG model/path reviews and release validation on the newly built
archive. A successful candidate build, green code CI, or a successful merge alone
does not certify the resulting KG for release.
