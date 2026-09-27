# Invalid-CAS paired mapping review — 2026-09-27

## Status: proposed staging change; remaining gates separate

This record proposes the reviewed candidate pair below on code revision
`409caa076db725ea0dc7c925d133ad61b22d8bfe`. The original fixed55/67-cohort
replays passed on this exact code/candidate pair, retaining their original
scientific expectations. Independent review, new paired-change full tests and
CI belong to the promotion PR/build records and are required before integration.
This record
does not establish production installation, fresh source outputs, a rebuilt KG
or release approval.

| Canonical artifact | Proposed SHA256 |
|---|---|
| `mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz` | `f1545663016b3871d2176ccbdc76caffdefa472838b716956e8d722aaa2caff9` |
| `mappings/ingredient_mappings.sssom.tsv` | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |

Only the unified artifact changes. The supported table is already byte-identical
and is verified as the other member of the pair. The release pin remains
`f082c05656a0910c85176eec7b41deeb77c27967aecb80393fddc262819b6d97`,
including its immutable upstream selection and `candidate_only` mode. The
[previous native-category record](../mim-native-category-20260927/PROMOTION.md)
retains its original scope and results.

## Exact reviewed delta

Relative to unified artifact
`fe54cd1a1dc14123b41bd8f08c9c42096cf2815b2ae5a5bb4ce4bd349041c98d`,
the complete full-row/multiplicity comparison removes exactly 33 original
invalid-CAS endpoint assertions, all retained in quarantine with reason
`invalid_cas_identifier`. No invalid CAS subject/object endpoint remains in
the candidate. Syntax/checksum validity does not prove chemical identity, and
no replacement check digit or substitute CAS identity is invented.

The builder also adds 90 native-provenance assertions for the 32 affected ChEBI
targets: 32 canonical exact matches and 58 synonym close matches. Each already
has one unchanged prior lexical assertion equal on the other 11 fields; only
`source=native_ontology:chebi` and `mapping_date=2026-09-24` distinguish the new
rows. These are not 90 new lexical identities. All other full rows and their
multiplicities remain unchanged. Existing competing names are not resolved.

The net change is 591,893 to 591,950 rows, with 120,184 targets, 336,050 exact
and 255,900 close matches, and no broad/narrow matches. The only metadata change
is the builder fingerprint:
`sha256:58ec62b9b01a28f4f3b6b47ff319a11396617d4a07ada409acc2742bcb77ae6a`.
Historical unified version/direction metadata and the five reviewed Sugar/Mucin
native-category cells remain unchanged.

## Completed checks and limits

The unchanged fixed55 replay passed all 55 scientific dispositions, 330 resolver
probes and 55 manual dictionary routes. The separate fixed67 supplement passed
all 356 routes (308 MediaDive, 26 MetaTraits, 17 MetaTraits-GTDB and five
MicrobeDecoder), 67 three-mode name queries, 110 manual-admission observations
and the original three parent-withdrawal controls, with no findings. It retained
all 510 historical assertion contexts but did not claim to rebuild those source
rows. Both actual processes exited zero with complete unchanged input guards
and closed output/log identities. Neither replay altered its historical oracle.

| Closed artifact | SHA256 |
|---|---|
| Fixed55 report | `19f81633a8daf87bd4de0b4ae7a88c46cd7179935685001cc38ab8ee74084d49` |
| Fixed55 execution receipt | `f59eef93b30eec6d2c0e21653221413cc411086d359c6e4042b63123bd837323` |
| Fixed67 supplement report | `1432550729dcf7ad18784a40ccd8e5ce7c61a5ed7f1aa641bef6391a618e4822` |
| Fixed67 execution receipt | `954239c228162040496ed8a0cc8f19e7147515e3f4d624685bca0a6749ac235c` |

Closed guarded candidate checks include complete delta/quarantine review,
unchanged native graph tables and stub selection, finite identity, supported
mapping and ingredient-policy audits, zero remaining supported-name/subject
disagreements, and all six second-cycle checks including identical candidate
bytes. Three separate runtime roles distinguish code-only rejection from the
candidate mapping change; they do not infer mapping-only causality for a
combined old-code/old-mapping versus new-code/new-mapping comparison.

Whole-MediaDive replay preserves all 1,213 compound records and 39,879 ordered
recipe occurrences, including typed source records, quantities, provenance and
multiplicity. Exactly three identifiers change: compound 1603 and occurrence
`mediadive.solution:3640#recipe/2` use `mediadive.ingredient:1603`; the distinct
nested-solution occurrence `mediadive.solution:1727#recipe/14` uses
`mediadive.solution:1729`. No other payload fields change. The two optional raw
mapping reads retain their real input snapshots;
this partial resolver audit is not full-producer freshness or admission.

Historical scientific caveats and original cohorts remain unchanged. Withheld
MIM claims are not globally false; independent native evidence does not approve
every historical alias. Review is agent-assisted with independent adversarial
review, not human curator signoff. The old 234-CAS cohort and broad curation
backlog are not replaced by the fixed 33-row inventory.

After reviewed integration, repeat actual producer freshness/admission and the
dependency-ordered source closure, including post-install stub feedback. Do not
restamp existing receipts. A fresh all-source merge, archive/member validation,
model/path/finite observation reviews and release approval remain separate.
Neither #1203 nor #1205 output acceptance is completed by this mapping PR alone.
