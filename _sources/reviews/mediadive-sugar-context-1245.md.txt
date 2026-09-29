# MediaDive's qualified mixed-sugar stock (#1245)

The original JCM 537 recipe describes a stock solution containing xylose,
maltose and cellobiose, each at 250 mM. The saved MediaDive record at
`mediadive.solution:4338#recipe/16` names `Sugar`, compound 1795, and preserves
that exact qualifier with an addition of `0.1 ml`. It supplies no CAS field.
Primary source: https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=537;
MediaDive display: https://mediadive.dsmz.de/medium/J537.

The immutable generic MIM Sugar assertion targets NCIT:C71939. Its native
Food semantics do not demonstrate that this specific three-sugar solution
is equivalent to that identity. This is a finite withheld grounding, not
proof that NCIT excludes every nonsucrose substance, a regulatory food-grade
claim, or a global Sugar/NCIT prohibition.

## Source decision and evidence

`mappings/canonical/mediadive_material_context_dispositions.tsv` has one exact
source-name/attribute decision, with case/whitespace-only recognition.
The withheld target is an example explaining the review, not a global ban.
The source occurrence remains on its existing local MediaDive ingredient
(or nested-solution) ID before unified, legacy or embedded fallback. An
explicit empty occurrence never borrows the cached compound's qualifier.
Unqualified or differently qualified Sugar observations retain normal lookup.
No component assertions, replacement molecular/CAS identity, or inferred
utilization are added. The existing broad ChemicalEntity category is retained;
this patch does not claim newly implemented mixture-specific categorization.

The selected decision is consumed as `material_scope_context_policy` before
graph output and guarded with the existing SourceAdmission/snapshot contract.
Missing, duplicate or changed decision content fails closed. Finalization's
existing consumed-input ledger and finalization-input fingerprint include the
exact selected file. Sugar audit rows name this actual policy and hash;
Potato and P3556 retain their original identity-exclusion policy bindings.
Conditional supported-MIM evidence applies to both P3556 and Sugar, including
selected-context/header-only cases after all grounding candidates disappear.

The existing material audit retains complete eligible unified, supported,
legacy and real embedded candidate rows, their physical ordinals, source raw
JSON, quantity, provenance and assertion position. Duplicate physical input
rows remain distinct. These are available original claims, not claims that
the held source invoked each lookup. The supported MIM table, release pin,
unified artifact and raw inputs are unchanged.

## Verification boundary

The immutable `tests/resources/mediadive/sugar_context.json` records the saved
raw observation and all three original mapping rows with origin digests.
Tests use only that fixture and temporary inputs. They exercise ordinary
generic Sugar lookups, every current fallback namespace, explicit empty and
other contexts, physical claim/occurrence multiplicity, selected file drift,
actual new policy origin, coexistence with Potato/P3556, and a tiny real
source graph through finalization/repeat/public admission.

Full code gates, independent review, actual source replay, source-to-merged
preservation and final KG release checks remain separate. This document is
not a claim of completed production rebuild or release acceptance. The local
chemical-mapping skill and reviewed MIM runbook required retaining immutable
upstream inputs rather than refreshing or rewriting their generic evidence.
