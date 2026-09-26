# MIM consumer integration and conservative candidate review

This is an agent-assisted, independently adversarially reviewed engineering and
mapping-admission review. It is **not human curator signoff**, a production
artifact promotion, or evidence that a new merged KG has been built.

## Integrated work

Prerequisites #1120, #1130 and #1131 were merged first. PR #1152 consolidates
the remaining #1139 / #1141 / #1144 / #1149 consumer stack, together with:

- Original-query admission after normalized/fuzzy lookup; case-sensitive
  negative-cache keys; finite reviewed COCl2/CoCl2 query scopes.
- Target-scoped recipe, salt/dye, hydrate and fallback exclusions. Rejected
  mappings preserve MediaDive ingredient IDs rather than guessing chemistry.
- Native authority restoration when a sole bad historical assertion is
  quarantined; explicit reporting when no independent declaration is available.
- Nine exact source-trait patterns preserving three local compound IDs, with
  worker tests for both MetaTraits producers, both polarities, percentages and
  provenance. No external chemical equivalences are added for these compounds.
- Nonblocking exporter-provenance diagnostics, portable candidate code/config
  fingerprints and actual package-version inventories, stable synonym spelling,
  main-level dry-run write-suppression tests, and corrected mapping documentation.

Newly reproduced defects are tracked in #1150 (native authority loss) and #1151
(false fallback identities). The original overly broad Berberine source-ID
exclusion was removed during review: an upstream WITHHOLD is not proof that a
chloride-specific source record is globally false. The unqualified-name guard
against assigning generic berberine to its chloride remains target-scoped.

## Independent engineering review

The first fully tested code/policy revision is
`f2a938ee090c205104090c2feb8f649a1e518e1a`. A separate adversarial reviewer
reproduced the authority-loss and punctuation/fallback bypasses, then approved
the fixes at that revision. Its final focused suite passed 159 tests; a separate
expanded chemical-mapping regression run passed 293 tests. The source-local
worker tests were also independently rerun (four passing tests).

Formatting, Ruff lint, spell checking and docstring coverage passed without
modifying that frozen source tree. Both standalone pytest and full tox passed
2,573 tests, with 55 deliberate skips. Subsequent artifact audits exposed #1153
and #1154, described below; the final revision must pass those checks again.
Final revision/test/candidate hashes are recorded in PR #1152's validation
record. Engineering approval is not chemical curator signoff or production
artifact approval.

The #1153/#1154 follow-up is committed as `6f52fa2ad`. Its expanded focused
suite passed 175 tests; the independent reviewer passed 128 tests and found no
remaining blocking code findings. This includes stale-loader exact/fuzzy
lookups, both real producer workers, and native-label repair for retained
identity and nonidentity assertions, with full original-row quarantine.

## Candidate input, not a new published release

The diagnostic export was reproduced from immutable upstream commit
`a8b26f007cdf5bdc7529ab13888d611f359e6aad`, not a floating sibling checkout.

| Input | SHA-256 |
| --- | --- |
| Upstream commit archive | `48d18e4f02bfdcfb3982b5ed43625dba2f76b89470ae0e99f5986c66149973dc` |
| Reviewed export manifest | `c37e075743b52f614a78c2ddd7ec47e1e8ea35b53e0a66c5886007947105a64b` |
| Supported SSSOM | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| Withheld SSSOM | `c37491ed4191889d375b02510137a178ee9b44a341131e42afec07d7953e8405` |
| Dispositions | `87b4a72969681e4b808c526552c84c36daa17c6697970735a4e0ba0270523154` |

The source partition is 1,747 supported and 1,252 withheld rows, totaling 2,999.
Upstream review assembly, export validation and SSSOM structural validation
passed locally. This reproduction used KGM's Python 3.10 environment, not the
upstream project's locked Python 3.13 environment. Do not describe the generated
manifest as a newly published upstream GitHub release.

The diagnostic candidates exposed additional fallback defects. Their old
counts/hashes are not acceptance evidence for subsequent fixes. Rebuild and
audit the final candidate under the frozen code/policy context, including a
second generation to check convergence.

## Coverage decisions

The initial audit traced all 63 exposed historical IDs and 504 existing producer
edge rows. Those are exposure counts, not measured edge losses in a rebuilt KG.
At the first fully tested revision the absent-entity cohort was 508; a separate
lexical reconstruction counter was 509 because NCIT:C29406 retained scoped
native aliases without a canonical display name. CHEBI:18309 was the additional
absent entity relative to the earlier 507-ID audit. Neither ID had producer
exposure in the four audited sources. All 349 distinct tested resolver routes
in the exposed cohort had evidence-backed or explicit local dispositions;
none had unresolved trait lookup or rejected-identity reintroduction.

Conservative dispositions include:

- Preserve unknown recipe/preparation/hydrate occurrences as source-specific
  ingredients; do not strengthen them to a molecular identity.
- Preserve 3-O-methyl alpha-D-glucopyranoside, L-alanine 4-nitroanilide and
  potassium 5-dehydro-D-gluconate trait observations as local compounds. The old
  exposed producer rows total 38, six and six respectively. Actual final counts
  still require producer runs.
- Use the selected supported SSSOM's explicit aliases for sulfur powder,
  iso-valeric acid, butyl vinyl ether and the local Na-phosphate buffer record.
- Prefer native canonical L-xylose (CHEBI:65328) over the same string occurring
  as an alias of ring-opened aldehydo-L-xylose (CHEBI:17979).
- The betaine hydrochloride route to pubchem.compound:11545 has independent
  support in the [primary PubChem record](https://pubchem.ncbi.nlm.nih.gov/compound/11545),
  which supplies that name and CAS 590-46-5. It is not approval of the withheld
  MIM parent mapping to generic glycine betaine.

These finite decisions are not a general chemical-formula parser, comprehensive
scientific recuration of all legacy mappings, or activation of the separate
20-case ingredient occurrence/product profile.

## Additional complete-cohort findings

The missing-ID audit covered none of the 55 historically MIM-derived special
override targets. A separate ledger reconstructed all 55 original target-changing
rows from commits `4617f84b6` and `0444faf1e`, then checked current mappings,
supported/withheld dispositions, native records, raw observations and both
actual transform classes (220 special-resolver probes plus 55 manual entries).
Fifty-three routes had finite support. Two generic-to-specific routes did not:

- `produces: angustmycin` now retains `kgmicrobe.compound:angustmycin`, not the
  specific psicofuranin / Angustmycin C target CHEBI:8612.
- `produces: rubradirin` now retains `kgmicrobe.compound:rubradirin`, not the
  specific Rubradirin B target CHEBI:223718.

These #1153 dispositions reuse historical local IDs. Target-scoped guards protect
stale unified/fallback routes while retaining explicit native member names.
The raw sources contain four positive records total across the two producers;
these are not counts from a newly built KG.

The full identity audit also found six otherwise-admissible CHEBI:8309 rows
carrying the rejected generic object label `polymyxin b`. #1154 quarantines the
complete original rows and repairs descriptive metadata from admitted native
labels, without falsely attributing their retained identities to that authority.
When no safe native label exists, the unsafe label is cleared and reported, not
replaced by a guessed identity. Case-only preferred-label differences for
CHEBI:29673 and FOODON:03413132 were audit false positives; NCIT:C29406's
scope-blocked preferred label is a disclosed exception, not an erased identifier.

## Original 38-issue queue

| Disposition | Issues |
| --- | --- |
| Prerequisite fixes merged | #1127, #1128, #1129, #1132 |
| Original observations verified resolved and closed | #506, #514, #381, #952, #297, #299, #822 |
| Implemented by consolidated PR #1152, subject to its final tests/CI | #1133, #1134, #1135, #1136, #1137, #1138, #1140, #1142, #1143, #1145, #1146, #1147, #1148, #973, #974, #979, #515, #954 |
| Keep production/artifact gates open | #1123, #788, #1009 |
| Separate narrower curation or feature scope; not automatic MIM promotion gates | #837, #650, #385, #386, #536, #905 |

In particular, ingredient-occurrence support is not general CultureMech KGX
adoption (#905); recipe amount/unit support is not a proof of normalized
concentration computation (#536); and obsolete MicrobeDecoder label counts are
not permission to import a historical MIM label index indiscriminately.

## Remaining production gate

Keep #1123 open until immutable production-input selection and coordinated
promotion of both mapping artifacts are reviewed, the final candidate and its
coverage dispositions pass, and the actual producer closure is rebuilt and
merged. Recompute freshness on the final checkout: the shared utility changes
can invalidate all 15 canonical producers, not just the older nine-source
mapping-only closure. Then review the new archive's model, paths and manifest.

No existing transform receipt or merged artifact is made fresh by this PR.
