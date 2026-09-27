# Native-category paired mapping acceptance — 2026-09-27

## Status: candidate accepted for staging; integration and release gates separate

Candidate and consumer review accept the pair below for a reviewed repository
change based on `09c6ca52ec07315b818117def4b345a4bb5c7583`. This is staging
acceptance, not production integration or approval of a newly built KG. At
preparation, the new paired-change tests and CI had not run; their exact-head
results belong to the promotion PR and build records. Full local tests,
independent review and CI are required before integration. This record does not
establish production integration, post-promotion fresh sources, merge or
archive/release validation.

| Canonical artifact | Accepted SHA256 |
|---|---|
| `mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` | `fe54cd1a1dc14123b41bd8f08c9c42096cf2815b2ae5a5bb4ce4bd349041c98d` |
| `mappings/ingredient_mappings.sssom.tsv` | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |

The supported TSV is already byte-identical and remains unchanged; both members
are accepted and verified together. The immutable upstream selection, complete
manifest and `mappings/mim_reviewed_release.json` remain unchanged, including
`mode=candidate_only`. Neither the withheld product nor the original upstream
source table is installed. The [September 25 record](../mim-admission-20260925/PROMOTION.md)
retains its original results and limitations.

## Exact artifact delta

Relative to the installed unified artifact `9e481e31f23b7a2414537f967ea513a7b494824799a002ca4300765f5acea0f1`,
the complete literal/full-row comparisons identify exactly five category-cell
changes:

- `MIM:Mucin`, `kgm.name:mucin` and `kgm.name:mucus_glycoprotein`, all targeting
  `NCIT:C16883`: `biolink:OntologyClass` becomes `biolink:ChemicalEntity`.
- `MIM:Sugar` and `kgm.name:sugar`, both targeting `NCIT:C71939`:
  `biolink:OntologyClass` becomes `biolink:Food`.

The only SSSOM metadata change is the builder fingerprint:
`mapping_tool_version: sha256:a6cbacfba8bc9dc02d7f328ef7bfd86041c56c0988dee621df4ea4d536a7f8f8`.
Names, endpoints, predicates, other row fields and multiplicities are unchanged.
Both the installed and candidate unified artifacts contain 591,893 rows and
120,185 target entities, with 336,050 exact and 255,843 close matches and no
broad/narrow matches. The unified artifact retains its historical version and
absent `predicate_semantics` declaration;
the supported product independently declares SKOS semantics.

These finite native category projections do not approve a new chemical identity,
change an observation endpoint or endorse every historical alias. The builder
retains historical exact-identity connectivity while ordinary native `xref`
annotations do not expand that scope. Explicit native `same_as`, admitted
independent evidence, supported MIM identities and existing policy exclusions
remain distinct inputs to reconstruction.

## Completed candidate checks

The candidate was built and replayed with frozen source revision
`0b054bcb37b6ef07b1589ba73f245a14c3db8aef`. Closed executions retained unchanged
input/code guards; their accepted scope includes:

- Native category evidence, report/quarantine review, complete artifact delta,
  unchanged stub selection and a second build passing all six convergence checks,
  including identical complete candidate bytes.
- Supported-product, finite ingredient/identity and runtime lookup checks.
- All 55 original special-override dispositions, 330 target/predicate probes and
  55 manual dictionary routes, plus actual manual admission for both producers.
- The fixed 67-ID cohort's 356 routes, including 308 complete typed MediaDive
  occurrence joins; the 510 original edge rows remain historical exposure
  evidence, not counts from a new graph.
- Whole-MediaDive preservation of all 39,879 ordered occurrences and their typed
  payloads/quantities against the original occurrence oracle. This is not a claim
  of quantity normalization or general medium-formulation equivalence.

These checks preserve their original cohorts and scientific caveats. Review is
agent-assisted with independent adversarial review, not human curator signoff.
Preserved historical assertions are not newly curated; withheld upstream rows
are not a global prohibition on independently supported claims.

## Remaining boundary

Run full pytest, all tox environments, lock and generated-config checks for the
new paired-change revision, then exact-head review and CI before integration.
Earlier code-only gates do not substitute for these artifact-change gates.

After integration, recompute actual freshness for all canonical producers and
run the dependency-ordered closure, including post-install stub feedback. Never
restamp old receipts. Review the newly merged archive's finite observations,
model, paths and release validation separately. Neither candidate acceptance
nor a successful merge alone establishes graph-release readiness.
