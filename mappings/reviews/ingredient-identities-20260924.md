# Twelve remaining ingredient reviews

Eleven MIM records now use the reviewed ontology identity below. Lysozyme remains a local unresolved material. Original source rows, full before-records, native authorities, FDA GSRS extracts with exact code statuses, PubChem structure results and seven BSA recipe extracts are archived in [MIM PR #754](https://github.com/CultureBotAI/MediaIngredientMech/pull/754) under `reports/sssom_completion_20260921/mapping_review/identity-review-20260924/`. Tracking: [MIM #762](https://github.com/CultureBotAI/MediaIngredientMech/issues/762), [Lysozyme #753](https://github.com/CultureBotAI/MediaIngredientMech/issues/753), [promotion #1123](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1123).

| Ingredient | Primary identity | CAS node xref |
| --- | --- | --- |
| Anabasine Hydrochloride | NCIT:C216370 | cas:53912-89-3 |
| Cotarnine Chloride | NCIT:C79997 | cas:10018-19-6 |
| Pretomanid | NCIT:C166606 | cas:187235-37-6 |
| Sutezolid | NCIT:C152482 | cas:168828-58-8 |
| Bovine Serum Albumin | NCIT:C85253 | cas:9048-46-8 |
| Sunflower Oil | NCIT:C1241 | cas:8001-21-6 |
| Zymosan | NCIT:C183132 | cas:9010-72-4 |
| Locust Bean Gum | FOODON:03413132 | cas:9000-40-2 |
| Tara Gum | FOODON:03413299 | cas:39300-88-4 |
| Sodium Adipate | FOODON:03413240 | cas:7486-38-6 |
| Acriflavine | NCIT:C76253 | cas:65589-70-0 |
| Lysozyme | kgmicrobe.ingredient:lysozyme | None assigned |

Anabasine retains its stereospecific monohydrochloride and Cotarnine its 1:1 chloride salt. Pretomanid and Sutezolid retain the S stereoisomers. The original CAS values, NCIT and FDA records agree, and current PubChem InChIs exactly match the MIM structures. Sodium adipate retains disodium stoichiometry and no unreported hydrate. Sunflower oil and Zymosan retain their named material scope, without inferring a processing grade or general beta-glucan equivalence.

The source's Sigma A7030 BSA is one supplied form of the generic ingredient, independently supported by [the supplier](https://www.sigmaaldrich.com/US/en/product/sigma/a7030) and [FDA](https://precision.fda.gov/uniisearch/srs/unii/27432CM55Q). FDA qualifies the BSA CAS as GENERIC (FAMILY). Seven recipes keep their own preparation details, including fraction V and A9647/A7409 alternatives; they are not all assigned A7030. The original locust bean gum [Sigma G0753](https://www.sigmaaldrich.com/US/en/product/sigma/g0753) agrees with [JECFA INS 410](https://apps.who.int/food-additives-contaminants-jecfa-database/Home/Chemical/940), and tara gum [Biosynth YT58656](https://www.biosynth.com/p/YT58656/39300-88-4-tara-gum) with [JECFA INS 417](https://www.fao.org/fileadmin/user_upload/jecfa_additives/docs/Monograph1/Additive-455.pdf). [JECFA INS 356](https://apps.who.int/food-additives-contaminants-jecfa-database/Home/Chemical/2972) supplies the sodium adipate CAS bridge to FoodOn. Product and preparation text does not enter exact synonyms.

[FDA GSRS Acriflavine 1T3A50395T](https://precision.fda.gov/ginas/app/api/v1/substances/1T3A50395T?view=full) lists NCIT:C76253, both mixture components, PRIMARY CAS 65589-70-0 and SUPERSEDED CAS 8048-52-0. Preserve the original RN and its source status in `ingredient-identities-20260924/registry-history.tsv`. Do not publish it as a current annotation or propagate it through exactMatch. This review does not assert a global CAS withdrawal.

Lysozyme's original row has no supplier or preparation evidence. Its invalid CAS 2650-88-3 has been removed from all active MIM fields and the reviewed exporter now checks CAS annotations, including `other`. The corrected source keeps a local material identity. The generic name route requires that local target to be present; it cannot silently fall back to the FoodOn food-additive scope. Exact FoodOn/hen-egg equivalence and the plausible CAS 12650-88-3 remain unapproved. Native ontology identifiers and declarations remain available for explicitly supported contexts.

`ingredient_name_scopes.tsv` transports the eleven independently verified current CAS values as KGX node xrefs through `get_node_enrichment`; the annotations do not become consolidator equivalence xrefs, SSSOM exactMatch or same_as. Policy exclusions prevent stale Lysozyme and Acriflavine identity claims from reintroducing rejected or historical CAS into their current nodes. General NCIT P210 extraction remains in [PR #1131](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1131).

The candidate must consume the newly reviewed MIM bundle; the immutable production pin remains unchanged. Producer closure and coverage checks remain part of promotion.

## Candidate verification

The full candidate has 591,655 rows and SHA-256 `c4942b92a7e7af42cc63dbfa6f59f81eae192ef706f687c9613b113b23e9ad0e`. It consumes 1,747 supported MIM assertions. All 1,696 explicit subjects resolve to an approved target. There are **zero unresolved name disagreements**, with the previously reviewed Xanthine context distinction accepted separately. Eleven current CAS annotations, local Lysozyme without CAS, the earlier four chemical scopes and the native Xanthine parent edge pass actual runtime checks. A complete scan finds no invalid Lysozyme CAS in active candidate identity, label or annotation fields.

The candidate retires 22 additional redundant CAS/local identifiers, bringing unreconstructed identifiers from 485 to 507. `retired-identifiers.tsv` records each disposition; the current CAS values remain queryable node annotations, while Acriflavine's old RN remains history. None of the 22 newly retired identifiers occurs in the 31 existing producer edge tables examined (18,784,312 rows, including ignored files). Existing coverage exposure is unchanged: 63 identifiers referenced by 504 edge rows. This is an audit of existing files, not a claim of successful producer rebuild or promotion closure.

Full pytest and full tox both pass **2,293 tests, 55 skipped**. Tox formatting, lint, spelling and docstring checks pass; Poetry lock and generated merge configuration checks pass. See `ingredient-identities-20260924/validation.json`, `runtime-audit.json`, `identity-audit.json`, `coverage-current-graph.json`, `coverage-delta.json` and `candidate-build.json` for the results and input fingerprints.

The general runtime and graph-exposure audits reuse `chemical-scopes-20260923/audit.py` and `chemical-scopes-20260923/audit_current_graph.py` with this candidate and supported bundle. The additional identity audit is reproducible with:

```bash
PYTHONPATH=. poetry run python mappings/reviews/ingredient-identities-20260924/audit.py \
  --candidate /path/to/candidate.sssom.tsv.gz \
  --output /path/to/identity-audit.json
```

The candidate and complete builder report remain local derived artifacts; the committed reports fingerprint them. The production unified mapping and immutable release pin are unchanged.
