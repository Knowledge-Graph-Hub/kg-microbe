# NCIT CAS annotations

`ncit_cas_annotations.tsv` is a fixed excerpt of the local NCIT SemSQL
snapshot inspected during the September 2026 MIM integration review (#1123).
`cas_rn` comes directly from each subject's `NCIT:P210` annotation; `name`
comes from `rdfs:label`. The property is NCIT's CAS Registry Number field,
not `oio:hasDbXref` or an asserted equivalence.

Source concept pages are available at
`https://evsexplore.semantics.cancer.gov/evsexplore/concept/ncit/{code}`.
For example, [Pretomanid (C166606)](https://evsexplore.semantics.cancer.gov/evsexplore/concept/ncit/C166606).

`mim_cas_rn` records the corresponding identity in the pinned MIM release
`mim-sssom-2026-09-21`. Seven values agree. Acriflavine deliberately records
the discrepancy: NCIT supplies `65589-70-0`, while MIM supplies `8048-52-0`.
The export must preserve NCIT's own annotation without copying MIM's
different CAS onto that node or asserting `same_as`.

These are regression inputs, not decisions to upgrade MIM's broader
relationships. FoodOn cases have no NCIT P210 source and are not covered
by this extraction. MIM's invalid lysozyme CAS (`2650-88-3`,
[MIM #753](https://github.com/CultureBotAI/MediaIngredientMech/issues/753))
must not be republished as a validated CAS cross-reference.
