# Reviewed MIM releases in KGM

## Status and scope

The authorized update in [#1788](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1788)
selects immutable upstream commit
[`0dac278466699129a083343a921c2e0ca18a9ab4`](https://github.com/CultureBotAI/MediaIngredientMech/commit/0dac278466699129a083343a921c2e0ca18a9ab4).
Its [locked-runtime validation run](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/41900248437)
passed native review reproduction, complete export validation and SSSOM schema checks.
The [source and actual-product review](reviews/mim-upgrade-1788-20261107/README.md)
retains independent review and a local reproduction whose four products match the
official artifact byte-for-byte. This is an immutable-commit export, not a newly
published release tag or human curator signoff.

**The reviewed supported/unified pair is accepted and installed in the isolated
worktree. All 15 genuine worktree producers, producer canaries, final code/CI gates,
and the new graph/archive validation remain pending.** The
[acceptance record](reviews/mim-upgrade-1788-20261107/ACCEPTANCE.md) binds the actual
candidate, independent reviews, second-cycle reproduction, historical runtime
controls and completed paired installation. The old pair and failed first attempt
remain preserved. That attempt exposed the existing P3556 downstream hold;
[#1799](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1799) now records its
finite, full-row disposition without weakening identity admission.

The installed native supported table has SHA256
`7e68fea7fd788928f29c7671156198af101baaa3b3051f19bab78a5479d2a940`.
The installed unified candidate has SHA256
`f1314a41ede9b143c595399ada5178e52306364e69b467810cf71e7cdc4be23d`
(591,914 rows and 120,173 targets). These exact bytes are the accepted pair for
commit `0dac278466699129a083343a921c2e0ca18a9ab4`; their installation does not certify
production outputs or a release.

The native export contains **1,739 supported assertions: 1,737 exact matches and
two directed broader matches**, plus **1,275 withheld rows** (3,014 source rows).
Supported and withheld subset versions are their actual maximum mapping dates,
2026-11-01 and 2026-11-03 respectively. They are bound to the same immutable source,
review and complete partition; equal version strings are not a release contract.
The separate opt-in ingredient-scope/history bundle has not been activated.

Native support remains distinct from downstream transport eligibility. The exact
unchanged `MIM:L-alpha-Phosphatidylcholine` claim remains native SUPPORTED but is
held by the existing [P3556 review](reviews/mediadive-p3556-scope-1241.md). Its full
original payload must remain audit evidence; it cannot establish positive identity,
aliases, cross-references or a sibling identity for broader projection. A finite
held disposition does not permit skipping changed or unfamiliar policy conflicts.
The native product is never rewritten to make its decision agree with KGM policy.
The accepted partition therefore retains all 1,739 native supported rows, with
one downstream-held claim and 1,738 eligible claims: 1,736 exact and two broader.
The two broader source claims yield four directed relations through their reviewed
CAS and local identity siblings; the held claim licenses none of these routes.

Independent acceptance accounts for every baseline row and every reconstructed
payload, with direct native or selected independent evidence and explicit category
defaults. The real second build reproduces the unified bytes exactly. Fresh reader
probes preserve the finite material, invalid-CAS, Potato and P3556 controls, the
four Catalase metadata-only annotations, and all 13 withdrawn target dispositions.
The complete 55-row historical override cohort was replayed against the actual
candidate with unchanged observed outcomes. This does not re-curate all unchanged
historical assertions or replace whole-producer review.

The existing [#1253 native-alternative review](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1253)
remains applicable: one exact structured synonym selects CHEBI:196822 with
synonyms enabled, while the reviewed canonical label selects CHEBI:86658.
Current complete native structure evidence and all 19 competing mapping rows were
rechecked; the lookup outcomes are unchanged. Generic L-alpha queries may select
the distinct CHEBI:16110 class only in synonym mode. None of these routes identifies
the whole supplier P3556 product. The overstrict intermediate reviewer checks and
their explicit corrections remain in the acceptance evidence.

The withheld table is a review backlog, **not a set of globally false assertions**.
An independent ontology/source can still support a claim absent from the supported
table. This update does not approve ingredient roles, components or wholesale media
regeneration. The previous immutable pin `1848b0fe521bc2462f165912fcf92d09ad9a8cec`
and its consumed graph are preserved comparison evidence. Historical
[Potato scope](reviews/mediadive-potato-scope-20260929/PROMOTION.md),
[invalid-CAS](reviews/mim-invalid-cas-20260927/PROMOTION.md),
[native-category](reviews/mim-native-category-20260927/PROMOTION.md) and
[September acceptance](reviews/mim-admission-20260925/PROMOTION.md) records retain
their actual inputs, checks and remaining limits. They are not acceptance of this
new candidate. Earlier hydration replay failures (#1169) also remain history.

## Build a candidate

From the repository root, download the exact source archive and complete validated
bundle to new evidence locations under `data/`:

```bash
curl --fail --location \
  --output data/mim-source-0dac2784.tar.gz \
  https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/0dac278466699129a083343a921c2e0ca18a9ab4

gh run download 41900248437 \
  --repo CultureBotAI/MediaIngredientMech \
  --name mim-reviewed-sssom \
  --dir data/mim-reviewed-0dac2784

poetry run python -m scripts.refresh_reviewed_mim \
  --source-archive data/mim-source-0dac2784.tar.gz \
  --release-directory data/mim-reviewed-0dac2784 \
  --output-directory data/mim-candidate-0dac2784
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
commit-named archive root, safe unique members, the original
source SSSOM and review bytes against the manifest, and the pinned lock/workflow
bytes. The source archive is streamed without extracting or executing its code.
Only two reviewed metadata links are permitted: `.agents/skills` to
`../.claude/skills`, and `CLAUDE.md` to `AGENTS.md`. They are recorded but never
followed or materialized; their exact targets/types and every ancestor are checked.
Consumed provenance members must remain regular files. Other links, unsafe paths,
duplicate members and linked ancestors still fail.
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
`51c6029b88a2d1d73ca1cbe13029c9cf60991dc65af2556cec6b1413ee52eb9d`.
Pinned complete manifest SHA256:
`b02a92446e8a613fd0d96b0dd8147d439733fcf73e731b363a6388e95d616703`.

The CI artifact is a convenient copy, not the sole durable origin: it expires.
If unavailable, retrieve the same commit-addressed source archive, verify its
SHA256 against the independently committed pin **before extraction/execution**,
and extract into a new directory beneath `data/`. Do not accept a different
archive hash, floating main checkout or silently regenerated review. Extraction must skip the two metadata links under the reviewed policy above.
Current form reviews also require real historical Git commits; an archive alone
fails native provenance checking ([#1793](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1793)).
Fetch the exact selected commit and history from the official HTTPS repository
into a separate bare object store with Git object checking enabled. Verify the
required base commits `e568dbf0e0f759431ed317b973675680f031dd1d` and
`330d9e34c5cf69bb355d4d242977eb1a78dbe374` there. Supply that store through explicit
`GIT_DIR` and set `GIT_NO_LAZY_FETCH=1`; clear unrelated inherited Git overrides.
Do not edit native review/source files or disable provenance checks. These reviews
retain their declared working-tree attestations, not committed-byte proof.
The retained reproduction packet records the exact fetch, object identities,
failed archive-only attempt and successful unchanged four-command reproduction.

Within the verified source root and isolated frozen Python 3.13 environment,
`reviewed_sssom_v1` means the following exact workflow:

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

Native `xref` annotations also do not expand the identity-connected quarantine
scope. A newly supplied database reference is not evidence that historical
synonyms propagated between its owners. Native `same_as`, admitted independent
identity evidence, and supported MIM identities do participate before the first
build. Native `same_as` tokens have surrounding whitespace stripped consistently
before both scope calculation and reconstruction; malformed or excluded tokens
remain inadmissible. Historical nonlexical `skos:exactMatch` edges still connect the reset
scope, including shared external identifiers and reversed edges: even a
questionable old identity may have carried copied names. Retaining that
historical contamination check does not endorse the old identity scientifically.
Mappings outside this scope remain historical assertions, not newly validated
claims. Scope-independent reviewed identity/hydration exclusions still apply.

CAS syntax and checksum validity are also required before a mapping row can
contribute any active identity, name, formula, category, parent or hydrate index.
The same structural rule covers lexical/xref lookups and MediaDive's unified,
legacy and embedded fallbacks, including the legacy `CAS-RN` spelling. It does
not guess a replacement digit or establish chemical equivalence. A rejected
MediaDive grounding keeps the existing local ingredient/solution ID and complete
recipe occurrence context. Raw source claims are not rewritten. The conservative
candidate's quarantine retains every rejected baseline row, all columns and
multiplicity, with reason `invalid_cas_identifier`. Historical exactMatch links
still participate in quarantine scope even when their CAS endpoint is invalid:
they may have propagated copied names, but cannot be reasserted as active claims.
The older full consolidator and identity-only refresh also reject invalid active
endpoints; they leave their source files intact, rather than producing the
conservative candidate's separate full-row quarantine. A valid checksum alone
does not establish that a source's chemical assignment is scientifically correct.

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
constitute a MIM refresh. That bounded operation names its actual writer,
`scripts/consolidate_chemical_mappings.py`, and its code SHA-256 in the tool/version
metadata. It preserves the description's meaning and adds one current identity
policy fingerprint. Original reconstruction provenance is retained through the
reviewed baseline hash and prior record, not a mismatched old tool/new version.
Unrelated metadata and retained mapping rows remain unchanged.

The earlier input-schema repair added explicit empty `verified_date` cells to
two canonical chemical rows. That formatting-only repair did not install the
reviewed MIM input and its old two-source rerun advice is not the closure for
the subsequent shared-runtime/policy changes. Never overwrite transform
receipts to hide input or code drift.

## Promotion, transforms, and merge

Candidate generation does not publish files or run production transforms. Once
the final delta and consumer behavior are accepted, verify and promote the
reviewed unified candidate and the byte-exact supported MIM table **together** at
their canonical mapping paths in one reviewed change:

- `mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz`
- `mappings/ingredient_mappings.sssom.tsv`

The supported file must match the committed pin's supported-product hash; the
unified file must match the final accepted candidate hash. Do not install the
upstream source SSSOM, the withheld product, a floating sibling checkout, or
an unverified counterpart. If the supported table already has the pinned bytes,
retain it unchanged; paired review does not require a meaningless rewrite or a
new MIM release pin. `mode=candidate_only` remains the CLI's publication
boundary: paired installation is an explicit reviewed repository operation,
not permission for future automatic refreshes.

Keep release hashes, input fingerprints, quarantine disposition, second-cycle
stability, full fallback/whole-MediaDive review, and runtime regression evidence
with that change. Record final code/test/CI results and installation status in
the acceptance record. Update the vendored-set shape test to
bind the actual reviewed supported counts and predicates. The two supported
broader claims are projected only through affirmative, explicitly supported exact
identities for the same source subject; each derived relation binds both full-row
hashes. They must not contribute parent names, formulas or identity cross-references.
Nonblank supported predicate modifiers are rejected before any positive route.
The new unified header declares SKOS direction explicitly; an unmarked baseline
with existing asymmetric rows cannot be silently relabeled. Preserve the separate
legacy asymmetric-semantics controls. Do not stamp freshness receipts to
make existing outputs appear current.

**Direct fallback coverage:** 55 of the 194 historical special-chemical overrides have explicit MIM
lineage (17 from commit `4617f84b6`, 38 from `0444faf1e`). MetaTraits and its GTDB
variant read this table directly, independently of the unified artifact. Excluding
it from candidate generation does not remove those runtime routes. The complete
55-row lineage ledger was reviewed and replayed, including source-local
angustmycin/rubradirin fixes. This is not an unresolved generic 55-row curation
gate, nor approval of all future overrides: repeat the exact cohort and runtime
probes against the final candidate/code and retain their fingerprints. Appearing
in a withheld target list alone is not grounds for removal.

MediaDive still reads independent runtime strict/hydrate/embedded inputs.
Hydrated ingredient identity is not the water-free parent. A separately supplied
`hydrated_chebi_id` may be admitted only with native target-label/scope evidence,
the correctly directed native hydrate-to-supplied-base part assertion, and all
identity policies; this does not turn that part relation into exact equivalence.
Lookups use original source names; punctuation normalization is display-only.
Ambiguous salts, malformed formulas and wrong derivative matches stay local
unless an independently supported identity is supplied. Whole-source replay is
required because a lookup fix can expose an older bad fallback (#1167–#1169).

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

This accepted pair is installed in a new isolated worktree, so the current run
requires **all 15 genuine canonical producers** under that worktree's actual
code, pin, mapping pair and input bindings. Prior-worktree completion records
remain historical evidence; they cannot certify producers in the new execution
context. The nine-producer command above describes the conditional mappings-only
closure, not the present run. A bounded one-medium canary also cannot certify a
complete MediaDive source.

The candidate's nine native authority tables were selected from the frozen prior
worktree. The consumed stub-ID cohort is unchanged, although the full upstream
source adds four withheld NCIT claims. After genuine worktree ontology/stub
production, compare the actual authority tables and selected native claims with
those candidate-bound inputs before dependent consumers proceed. Any difference
requires an explicit reviewed lineage disposition, not a new fingerprint applied
to an old claim. MediaDive's 632 unknown endpoint outcomes and incomplete
association coverage remain qualifications throughout this run.

After merge, run KG model/path reviews and release validation on the newly built
archive. A successful candidate build, green code CI, or a successful merge alone
does not certify the resulting KG for release.
