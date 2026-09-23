# Chemical scope decisions for the MIM integration

The reviewed source observations distinguish a mixture, an unspecified antibiotic family, a generic chemical class and a recipe material from more specific molecular identifiers. These decisions apply to query resolution and complete MIM subjects; they do not change the native ontology hierarchy.

| Query/context | Target | CAS annotation |
| --- | --- | --- |
| Polymyxin B | NCIT:C61894 (B1/B2 mixture) | cas:1404-26-8 |
| Explicit polymyxin B1 | CHEBI:8309 | cas:4135-11-9 |
| Polymyxin B sulfate | Its separate native term (CHEBI:8310 / NCIT:C61895) | Never inherit mixture/B1 CAS |
| Unqualified rifamycin | CHEBI:26580 (rifamycins) | None on family |
| Explicit rifamycin SV | CHEBI:29673 | cas:6998-60-3 |
| Generic xanthine | CHEBI:15318 | Do not infer the 9H ingredient CAS |
| Explicit 9H, MIM:Xanthine or reviewed CAS | CHEBI:17712 | cas:69-89-6 |
| Sorbitan Monooleate recipe material | kgmicrobe.ingredient:sorbitan_monooleate | Withheld pending product evidence |

[NCI defines Polymyxin B as the B1/B2 mixture](https://www.cancer.gov/publications/dictionaries/cancer-drug/def/polymyxin-b); [ChEBI:8309 identifies B1](https://www.ebi.ac.uk/chebi/CHEBI:8309). NCIT P210 supplies the mixture CAS. Keep sulfate separate.

Three original MicrobeDecoder fields contain the bare rifamycin token: BacDive 16969 and 13220 report production; 166282 reports resistance. None specifies SV. [ChEBI:29673](https://www.ebi.ac.uk/chebi/CHEBI:29673) explicitly belongs to the rifamycin family and carries the SV CAS. Family indexing retains unspecified source scope and must not be expanded to claims about every member.

[CHEBI:17712](https://www.ebi.ac.uk/chebi/CHEBI:17712) is the 9H child of generic CHEBI:15318. The existing CAS-grounded MIM ingredient retains that representation, but a bare trait label selects the generic parent. The candidate audit accepts this distinction only for MIM:Xanthine when its explicit subject still resolves to CHEBI:17712 and its generic name resolves to CHEBI:15318. Missing or incorrect routes remain conflicts. Standard InChI does not prove tautomer purity.

[ATCC 416](https://www.atcc.org/-/media/product-assets/documents/microbial-media-formulations/4/1/6/atcc-medium-416.pdf?rev=b4280b8582cc4389a3bdf40c98a7fa03) supplies only the generic Sorbitan Monooleate ingredient name (1 g/L). [JECFA](https://www.fao.org/fileadmin/user_upload/jecfa_additives/docs/Monograph1/Additive-432.pdf) describes a commercial mixture. CultureMech:008837 and CultureMech:008839 retain the local material identity; molecular equivalence and CAS 1338-43-8 are held pending supplier/product confirmation. The imported FoodOn CHEBI:53426 class incorrectly offers this bare alias alongside polysorbate 80 and additive codes 433/494. Reject that lexical route and any exact equivalence to the local material; preserve native ontology declarations and valid Tween 80 routes.

`ingredient_name_scopes.tsv` contains reviewed query routes and verified CAS annotations. A route is usable only when its target is present in the loaded mapping. `ingredient_identity_exclusions.tsv` blocks known false aliases/equivalences in runtime indexing, consolidation and synonym propagation. CAS node annotations emitted by `get_node_enrichment` do not create SSSOM exactMatch or same_as rows. General native NCIT CAS extraction remains in [PR #1131](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1131).

The five changed MIM records, source extracts, complete-row decisions and two restored recipe membership links are in [MIM PR #754](https://github.com/CultureBotAI/MediaIngredientMech/pull/754), under `reports/sssom_completion_20260921/mapping_review/chemical-scope-review.md`. The candidate must consume its newly reviewed bundle. The existing immutable release pin and production mappings are not changed by this implementation. Promotion remains tracked in [#1123](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1123).

Implementation tracking: [KG-Microbe #1132](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1132) and [MIM #760](https://github.com/CultureBotAI/MediaIngredientMech/issues/760). Sorbitan product evidence remains open in [MIM #761](https://github.com/CultureBotAI/MediaIngredientMech/issues/761).

The full candidate built from the newly reviewed local MIM export contains 591711 rows. Actual runtime checks pass for all four dispositions and all **1,696 / 1,696** explicit MIM subject lookups. There are **12 unresolved name disagreements** and **one separately accepted Xanthine scope distinction**. The input has 1,758 supported assertions; name audits allow any approved target for subjects with multiple supported targets. See [`runtime-audit.json`](chemical-scopes-20260923/runtime-audit.json) for the full remaining list and [`candidate-build.json`](chemical-scopes-20260923/candidate-build.json) for input fingerprints.

Candidate SHA-256: `cb2b6f4f0e6bcc60f0ee76f76c1c8c4bf0030d529ea4d5452d28a29ba5767078`. This is a local integration candidate; no immutable release has been published or production pin advanced.

Reproduce the read-only runtime audit with `PYTHONPATH=. poetry run python mappings/reviews/chemical-scopes-20260923/audit.py --candidate <candidate.sssom.tsv.gz> --supported <reviewed-MIM/ingredient_mappings.sssom.tsv> --chebi-edges <native-chebi_edges.tsv> --output <audit.json>`.
