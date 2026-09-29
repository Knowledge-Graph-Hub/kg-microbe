# Two finite peptone material identity holds (#1248)

## Scientific scope

`Soy peptone` and `Vitamin-free casamino acids` do not establish exact identity
with the particular structural record PubChem:167312541. Keep the original
material observations and imported lookup claims separately. No replacement
CAS, ChEBI, PubChem or inferred constituent identity is approved here.

The [PubChem record](https://pubchem.ncbi.nlm.nih.gov/compound/167312541) really
does carry soybean-peptone annotations and casein-digest synonyms; preferred
name disagreement alone is not the exclusion criterion. It also describes a
specific multicomponent structure, formula C290H252N8O72. Its annotations do not
demonstrate that either variable digest is exactly that structure.
[PubChem distinguishes](https://pubchem.ncbi.nlm.nih.gov/docs/glossary) unique
compound structures from deposited substances.

The manufacturer's [vitamin-assay casamino acids](https://www.thermofisher.com/order/catalog/product/228820)
is an acid hydrolysate of casein; [Bacto Soytone](https://www.thermofisher.com/order/catalog/product/kr/en/243620)
is an enzymatic soybean digest. Two saved soy occurrences name Bacto/BD Soytone;
these qualifiers remain specific to their own records, not inferred for the
other 23. The evidence supports distinct source materials, not an exact
supplier or composition for every occurrence, and not a global ban on the CID
or its registry annotations.

## Implementation boundary

Two anchored `name_pattern` rules in `ingredient_identity_exclusions.tsv`
reject only the reviewed name/target combinations. Existing case, punctuation
and separator normalization is retained, including the `PubChem` and
`pubchem.compound` prefix spellings. Direct CID references, unrelated material
names and independently supported other targets remain eligible. There is no
new raw compound-ID rule or unconditional supplier/product override.

The existing MediaDive ingredient checks enforce these rules on unified names,
legacy strict/hydrate lookups, embedded identifiers and adjacent solution-name
resolution. A missing identity retains the existing source-local ID. The two
observed compound IDs 75 and 654 describe this saved cohort; they are not
hardcoded policy keys.

The existing producer-owned `mediadive_material_scope_quarantine.tsv` gains a
finite peptone profile. It records only eligible claims to the reviewed CID,
not unrelated alternative targets or weak/nonidentity rows. It preserves
complete original mapping columns, duplicate row ordinals, source records,
locators, original qualifiers, selected retained targets and consumed-input
hashes. The reason is `digest_material_not_demonstrated_structural_identity`.
Repeated visits do not duplicate evidence; distinct recipe positions remain
distinct. No historical row is invented when the current input lacks it.

The canonical shared policy and unified input remain required audit origins.
Producer-time audit binding, source finalization and public merge admission
continue to enforce the existing mandatory audit contract. No audit schema,
merge rewriting or additional finalizer behavior is introduced.

## Immutable fixture and regression scope

`tests/resources/mediadive/peptone_scope.json`, SHA-256
`41a556f70cc0ae696d01895371214af7f25bb62c9d7a7b9a73c0fe589fed1fa3`,
retains all 26 saved observations (25 soy, one vitamin-free), their complete
old edge rows, and all ten original matching strict/hydrate claims (four soy
and one vitamin-free in each table). It preserves source-file hashes and exact
original physical rows; unrelated multi-line source cells were parsed with
the actual CSV dialect during extraction. This is a bounded fixture, not a
complete source snapshot or a newly accepted rebuild.

Tests exercise actual cold lookup, both target-prefix spellings, unified and
legacy fallback, embedded IDs, nested solution names, unaffected direct CID
and other-name routes, original quantities, duplicate observations, current
policy origins, immutable audit bytes and real finalization/admission. A tiny
identity-only exporter regression verifies stable second-cycle behavior; it
does not regenerate the real candidate.

The unified archive, supported MIM TSV and immutable MIM release pin are not
changed by this source patch. Derived candidate review, actual MediaDive replay,
full tests/CI, all-source freshness/rebuild and merged-KG review remain separate
gates. This does not close umbrella #286 or certify a release.
