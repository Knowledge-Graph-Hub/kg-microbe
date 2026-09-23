# MIM integration feedback: bounded fixes and remaining gate

Addresses [#1127](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1127),
[#1128](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1128), and
[#1129](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1129).
[#1123](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1123) remains open.

- Chemical prime locants survive both runtime normalization and lexical subject
  serialization. ASCII/Unicode prime forms agree; unprimed and double-prime
  positions stay distinct. The real candidate now resolves 4-hydroxychalcone
  to CHEBI:34423, not the 4-prime isomer CHEBI:34360. The 3-prime fucosyllactose
  lookup also reaches its existing release-supported CAS target; this resolves
  a runtime disagreement, without establishing equivalence to CHEBI:90065.
- The target-scoped identity policy rejects the obsolete CHEBI:18309 acid/anion
  association and CHEBI:37081 cross-reference. It does not follow the obsolete
  replacement into an unrelated glycosylated asparagine. Canonical labels,
  aliases, xrefs and the standalone identity-policy refresh obey the exclusion.
- Rhodomycin A, Pluramycin A and Racemomycin E special overrides use their
  specific local identifiers, already explicitly supported by the pinned MIM
  release. Their withheld MeSH parent assertions stay separate. Both MetaTraits
  routes, including GTDB inheritance and stale-loader fallback, have regressions.

`identity-evidence.json` contains selected ChEBI statements and the exact three
supported registry assertions. `candidate-runtime-audit.json` records the fresh
candidate hash, build counts and input digests. `runtime-disagreements.tsv`
accounts for all original 22 disagreements: **3 runtime fixes, 19 remaining
identity/scope reviews**. All **1,698/1,698** explicit MIM subject lookups still
reach a supported target. The candidate uses the original **1,763-row** published
bundle, not floating MIM main.

The 19 remaining disagreements are not resolved by giving MIM blanket priority.
Polymyxin B/component, rifamycin/class and xanthine/tautomer need source scope;
other material/form and cross-identifier cases need explicit evidence. Lysozyme
also has an invalid upstream CAS check digit, tracked in
[MIM #753](https://github.com/CultureBotAI/MediaIngredientMech/issues/753).

The upstream [PR #754](https://github.com/CultureBotAI/MediaIngredientMech/pull/754)
reconsiders the 17 withheld-only fallback assertions: ten identities receive new
mapping-only support, seven remain withheld with current reasons. Three of the
seven have the independent supported registry route implemented here. That does
not mean the remaining four downstream fallback claims are false: narrower trait
claims require their own evidence. Consume changed upstream approvals only after
a newly reviewed release is published and explicitly pinned. The immutable old
release still reports the original dispositions.

## Coverage exposure

`coverage-current-graph.tsv` enumerates all 476 identifiers missing from the
original candidate-v2, including zero-reference rows. The ignored-inclusive scan
of 31 existing producer edge tables covered **18,784,312 rows**. It found **504
edge rows referencing 63 identifiers**: MediaDive 304, MetaTraits 48,
MetaTraits-GTDB 30, MicrobeDecoder 122. These are existing references, not
predicted deletions or results from rebuilt producers. The other 413 identifiers
have no endpoint references in those scanned tables; this does not rule out
future name/formula/xref resolution losses.

`coverage-current-graph.json` pins every scanned input. Highest exposure includes
PYG (114 rows), trace minerals (88), trace mineral solution (63), and
3-O-methyl-alpha-D-glucopyranoside (38). Review source identities and replacement
or quarantine decisions before accepting these losses. The separate 5,697 lost
name/entity pairs, 13,606 xref/entity pairs and 299 formula/entity pairs still
need consumer-level acceptance.

Reproduce the exposure scan with the original candidate report and local current
producer tables:

```bash
python mappings/reviews/mim-feedback-20260922/audit_current_graph.py \
  --data-root data \
  --candidate-report data/mim-integration-20260922.l2lOPT/candidate-v2/report.json \
  --output-directory data/mim-feedback-coverage
```

## Production gate

These fixes do not install the unified candidate or repin MIM. Promotion still
requires the 19 disagreement dispositions, remaining fallback evidence, coverage
acceptance, a coordinated supported/unified artifact update, recomputed producer
freshness, affected transforms, merge, and review of the new graph/archive.
Shared runtime changes can expand the producer closure. Existing graph reviews
do not certify outputs regenerated from these changes.
