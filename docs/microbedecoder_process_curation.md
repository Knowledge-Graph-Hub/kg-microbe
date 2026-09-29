# MicrobeDecoder process curation (#650)

The [curated table](../mappings/canonical/microbedecoder_process_mappings.tsv)
normalizes nineteen exact source-column/literal pairs to existing METPO or GO
process classes: the original eight METPO routes and eleven FAPROTAX-only GO routes.
It does not declare global synonyms or independently verify each organism's
experimental phenotype. Original source records, literals and citations remain
on the source assertions; the table's evidence describes the term normalization.

| Source column | Exact literal | Process target |
| --- | --- | --- |
| Bergey_Type_of_metabolism | Fermentation | METPO:1002005 |
| FAPROTAX_Type_of_metabolism | fermentation | METPO:1002005 |
| VPI_Type_of_metabolism | Fermentation | METPO:1002005 |
| Literature_Type_of_metabolism | Fermentation | METPO:1002005 |
| FAPROTAX_Type_of_metabolism | nitrogen_fixation | METPO:1005039 |
| FAPROTAX_Type_of_metabolism | methanogenesis | METPO:1000844 |
| Bergey_Type_of_metabolism | Methanogenesis | METPO:1000844 |
| Literature_Type_of_metabolism | Methanogenesis | METPO:1000844 |
| FAPROTAX_Type_of_metabolism | nitrate_denitrification | GO:0019333 |
| FAPROTAX_Type_of_metabolism | aerobic_nitrite_oxidation | GO:0019332 |
| FAPROTAX_Type_of_metabolism | acetoclastic_methanogenesis | GO:0019385 |
| FAPROTAX_Type_of_metabolism | ureolysis | GO:0043419 |
| FAPROTAX_Type_of_metabolism | xylanolysis | GO:0045493 |
| FAPROTAX_Type_of_metabolism | cellulolysis | GO:0030245 |
| FAPROTAX_Type_of_metabolism | chitinolysis | GO:0006032 |
| FAPROTAX_Type_of_metabolism | ligninolysis | GO:0046274 |
| FAPROTAX_Type_of_metabolism | hydrocarbon_degradation | GO:0120253 |
| FAPROTAX_Type_of_metabolism | knallgas_bacteria | GO:0019412 |
| FAPROTAX_Type_of_metabolism | methanotrophy | GO:0046188 |

## Source evidence and limits

The prior saved review examined the FAPROTAX 1.2.12 definitions and the
MicrobeDecoder vocabulary/assembly at commit
`872726c257b39d14ffb1827df09127b5c8ef72bb`. Each rule carries its primary evidence
links and rationale. That upstream commit documents vocabulary and assembly;
it is not proven to have produced the saved local CSV.

- FAPROTAX defines fermentation without an external electron acceptor,
  methanogenesis as methane-producing pathways, and nitrogen fixation with
  nitrogen as acceptor. The cited Pontibacter nitrogenase experiment supports
  dinitrogen fixation rather than nitrate reduction or nitrogen assimilation.
  Organism assignments remain taxonomic **predictions**, with
  `knowledge_level=prediction` and `agent_type=computational_model`.
- The [Fermentation Explorer methods](https://doi.org/10.1126/sciadv.adg8687)
  define the Bergey/Literature fermentation vocabulary using organic donors
  and acceptors and distinguish it from nitrate respiration. The source
  assembly keeps metabolism fields separate from substrates and products.
- Bergey and Literature source vocabulary records explicitly label
  methanogenesis and record methane as a major product. Reviewed Literature
  descriptions support methanogenic growth; this does not license methane
  oxidation or substrate-use assertions. Original citations remain intact.
- The VPI vocabulary explicitly labels metabolism Fermentation separately
  from PYG products. Its source is the Anaerobe Laboratory Manual (Holdeman,
  Cato and Moore, 1977). Saved rows lack page-level citations; none are invented.

Most organism-specific reports were not independently revalidated. The saved
1958 *M. ruminantium* citation was located, but its scanned experimental text
was not independently read. These limitations apply to organism-level
verification; the rules implement normalization of explicit source terms.

## Ontology authority

The reviewed current `metpo.json` declared release **2026-06-12**, with SHA-256
`fbef7ad9b436b28c59d142876eac3d98ffcf1777edab33a67e35fabd841d391a`.
Its declarations place fermentation and methanogenesis under metabolism,
which is a biological process, and nitrogen fixation under biological process.
Expected labels are `Fermentation`, `Methanogenesis`, and `nitrogen fixation`.
`METPO:2000011` is the *ferments* property, not a process object.

The earlier ontology export typed these nodes only as
`biolink:OntologyClass`, which is not compatible with the pinned
`capable_of` range, Occurrent. Review issue #1216 fixes their category upstream:
the ontology transform follows only active named METPO subclass assertions
from `METPO:1000630` (biological process) in its emitted node/edge pair.
Fermentation and Methanogenesis reach that root through `METPO:1000060`
(metabolism); nitrogen fixation is a direct child. The current native branch
contains 18 active classes, not the separate phenotype or property branches.
Missing/malformed supporting files, a missing or changed root declaration,
and cycles in the selected branch abort rather than guessing a category.

The resolver requires `biolink:BiologicalProcess` for both METPO and GO rules
and checks the supplied `metpo_nodes.tsv` at each run for one declaration per
target, exact expected label/category, and nondeprecated status. Missing,
duplicate, changed, deprecated, or still-generically-typed declarations abort.
MicrobeDecoder creates no METPO stub or category override. **Rerun the ontology
transform before MicrobeDecoder** when upgrading from the generic export.
The immutable native ancestry excerpt and pinned Biolink contract test live in
`tests/resources/metpo_process_categories/`; no mapping is inferred from words
in labels or definitions, `part_of`, equivalence, or metadata edges.

GO rules require a separate authoritative `go_nodes.tsv` input and retain its
`biolink:BiologicalProcess` category. A GO-targeting table without that input
fails closed; a METPO-only custom table does not require it. GO declarations
receive the same uniqueness, label/category and deprecation checks, without
falling back to another ontology's export. A GO molecular-function declaration
cannot serve as a process object. Reviewed GO targets also have local
`subclass_of` paths to `GO:0008150`; these paths and complete definitions were
captured with the source evidence.

## Implementation boundaries

The resolver binds internal keys such as `bergey:type_of_metabolism` to the
recorded raw columns. It matches the tokens returned by the existing source
parser (which already trims token whitespace). The resolver performs no
additional lowercasing, whitespace trimming, fuzzy matching, or global label
aliasing. Table schema, evidence, key uniqueness,
predicate/relation, and source evidence provenance are validated before use.
Caller-owned consumed-input streams remain open for fingerprinting.

Unreviewed case variants, negative/narrower labels, product/substrate fields,
FAPROTAX2, and labels outside the finite mapping, annotation and local-scope
tables keep the transform's existing fallback.
The nineteen routes retain `biolink:capable_of` / `RO:0002215`; no additional oxygen,
chemical-use, assay, or taxonomy claim follows from the normalization.

The initial eight-route saved cohort contained 5,611 assertions, not distinct organisms or a
current output count. The review was bound to raw CSV SHA-256
`0c6ff730a108720a5d6972400f2bccf2eca8621713b62736abdf5df0fb188c95`
and saved ledger SHA-256
`82848eb0ff016094f10448a0e4c9d696b7790955268cd0ff81a7a6a2dfef3a4c`.
Those historical counts are evidence context and are not runtime expectations.

Offline resolver tests use tiny local declarations and cover the nineteen routes,
excluded scopes, malformed/duplicate rules, authority failures, caller-owned
streams, source prediction provenance, and fresh validation on subsequent loads.

## Initial eight-route source replay and remaining scope

The 2026-09-28 isolated replay of the raw CSV above retained all **521,217**
finalized edges. An independent full-field multiset comparison found exactly
5,611 process-object substitutions and four reporting-status corrections;
the other 515,602 edges were unchanged. The new source has 20,365 nodes and
edge SHA-256 `fb102e2f08fe0cfb4cf41acaefeb34586450266bd03ec770bb16a36c4aa9ca7a`.
This is source-level evidence, not merged-graph or release acceptance.

The legacy unmapped report mixed different kinds of work. Its current baseline
contained 6,676 rows, not a reproduced historical 5,224-label cohort:

| Facet | Baseline queue entries | Finalized assertions | Interpretation |
| --- | ---: | ---: | --- |
| Source attributes | 6,574 | 367,050 | Preserved field values, not automatically missing ontology terms |
| Local processes | 90 | 61,614 | Three process IDs / eight exact routes normalized by this change |
| Queued local materials | 12 | 230 | Four assertions say only `Not reported`; other identities remain unresolved |

The attribute queue's producer count is 367,056 token occurrences, six more
than finalized edges because duplicate tokens deduplicate. Of its 6,574
field-scoped entries, 5,179 describe measurements, units or isolation context.
The other 1,395 describe phenotype text/codes and assay values; interpretation
still requires the source coding scheme and observation context. Neither group
is a count of absent source data.

After that initial replay, **87 local process IDs / 56,003 assertions** still
needed definition-level curation. The chemical queue retained **11 IDs / 226
assertions**, including ambiguous mixtures, medium abbreviations and the two
record-scoped `sugar` observations. Three additional supported-registry local
IDs (`aminovalerate`, `isopropionate`, `sugars`) contribute 15 assertions outside
that unmapped queue. Thus the complete retained-local-material count is 241,
not 226; registry registration is not ontology grounding.

The four `Not reported` observations remain as field-scoped reporting
attributes, with their original source records, labels and citations. They
establish neither consumption nor inability to use a substrate. Negative,
mixed-sign and multivalued snapshot reports are preserved, not silently decoded
or collapsed to one phenotype. FAPROTAX functional-group definitions also
require care: for example, a union of single-step nitrifiers does not establish
the pinned METPO class's complete two-step nitrification definition.

Issue #650 is therefore **not fully resolved by this cohort**. Remaining
scientific curation must be evaluated on these current, role-separated queues;
the historical label total is not an acceptance target. The inventory command
in the runbook reproduces the complete source-level accounting without a
frequency cutoff or an implied mapping-success percentage.

## Continuation: nine GO process routes

The additional nine rules cover **1,541 saved assertions**: ureolysis 600,
hydrocarbon degradation 406, xylanolysis 200, cellulolysis 152, chitinolysis 82,
nitrate denitrification 73, ligninolysis 21, acetoclastic methanogenesis 4, and
aerobic nitrite oxidation 3. Raw-record counts independently agree with the
frozen finalized-edge inventory. These counts do not establish a subsequent
replay result or distinct-organism count.

The official [FAPROTAX 1.2.12 archive](https://pages.uoregon.edu/slouca/LoucaLab/archive/FAPROTAX/SECTION_Download/MODULE_Downloads/CLASS_Latest%20release/UNIT_FAPROTAX_1.2.12/FAPROTAX_1.2.12.zip)
was independently downloaded with SHA-256
`87e229e5201c23f8286aeb5f092f50a95bfe6281c7746d89a50c0aac11a5923c`.
Its `FAPROTAX.txt` member hashes to
`e5b9eead9f936316410c1a3d58aaa5fe4c2fafb8e859d250796ac70486c12963`.
This documents source vocabulary, not proof of the local CSV's generating
version. GO declarations were bound to local nodes SHA-256
`c9a81d79a8249865c6d43b76415195ffd4576fd69dc24cedab4085d353aa88f0`
and edges SHA-256
`dfa175a58b2317e112b3d920aee93eab4046bb76af2a3b03b3e4f28b3a180125`.

The source specifically describes nitrate-to-dinitrogen reduction; the
[GO denitrification pathway](https://amigo.geneontology.org/amigo/term/GO:0019333)
has that complete sequence. The source's [Steroidobacter experiment](https://doi.org/10.1099/ijs.0.65342-0)
supports its meaning. In contrast, generic `denitrification`, nitrite
denitrification and nitrous-oxide denitrification do not establish the full
nitrate-entry pathway, so are not aliases for that target.

The polymer-degradation groups align with substrate-specific catabolic
processes, supported by the cited [Saccharophagus degradation study](https://doi.org/10.1099/ijs.0.63627-0)
and [radiolabeled-lignin study](https://doi.org/10.1099/00221287-130-11-2905).
Hydrocarbon degradation combines methane, aliphatic and aromatic hydrocarbons;
ureolysis describes urea breakdown; acetoclastic methanogenesis specifies
acetate. These normalize reported process capabilities, not molecular-function
assays, substrate-use edges, or independent observations of every organism.

Specific exclusions remain important:

- Generic `nitrification` is the union of ammonia and nitrite oxidizers, not a
  complete two-step process. The 11 saved rows divide into eight ammonia-only
  and three nitrite-only group assignments.
- `aerobic_ammonia_oxidation` has a close GO candidate, but the pinned
  `GO:0019409` definition names hydrazine as its intermediate. That definition
  discrepancy needs reconciliation; it is not silently corrected here.
- `reductive_acetogenesis` describes CO2/CO conversion to acetate. METPO's
  candidate adds a primary-end-product constraint, while GO's acetyl-CoA
  pathway has a different endpoint. The cited [Alkalibaculum primary paper](https://doi.org/10.1099/ijs.0.018507-0)
  reports acetate and ethanol together, supporting acetogenic activity but
  not that universal product constraint. The 39 assertions remain unresolved.
- `aromatic_compound_degradation` explicitly excludes lignin and xylan;
  `methanol_oxidation` is broader than GO's same-label methyl-Coenzyme-M
  process; GO thiosulfate oxidation has a specific tetrathionate endpoint.
  Label similarity is not identity.

This process-only cohort would leave 78 IDs / 54,462 assertions from the initial
87-ID process queue. Concurrent phenotype and reporting-annotation dispositions
are separate and must be included in any current source census. These numbers
are not a whole-issue closure claim.

## Finite reported non-process annotations

The initial seventeen exact source-column/literal pairs are retained as field-scoped
reported annotations rather than process objects. Bergey's `Other` is an
unspecified report. Sixteen FAPROTAX groups describe source group membership:
`photosynthetic_cyanobacteria`, `animal_parasites_or_symbionts`,
`human_associated`, `human_pathogens_all`, `intracellular_parasites`,
`mammal_gut`, `human_gut`, `invertebrate_parasites`,
`human_pathogens_meningitis`, `human_pathogens_septicemia`,
`human_pathogens_gastroenteritis`, `predatory_or_exoparasitic`,
`human_pathogens_pneumonia`, `human_pathogens_diarrhea`,
`human_pathogens_nosocomia`, and `fish_parasites`.

These dispositions were reviewed against the same pinned FAPROTAX member;
they are not ontology identity mappings or newly inferred infection, host,
habitat, or taxonomy relationships. The original literal, source record and
prediction provenance remain intact. The finite list does not classify unseen
terms by spelling, and it excludes `knallgas_bacteria`, whose definition
describes hydrogen/oxygen metabolism and now has a separately reviewed GO route.
Process tables are rejected if they try to shadow one of these exact
non-process dispositions.

## Complete review of the remaining 61 process labels

The saved continuation inventory contained 61 remaining FAPROTAX labels and
41,388 assertions. Each was reviewed against native GO/METPO definitions and
the complete FAPROTAX 1.2.12 source group, not just its label. Independent raw
record/token counts agree for every label. This is a count of assertions, not
distinct organisms, current merged rows, or new experimental observations.

| Representation after this review | Labels | Saved assertions |
| --- | ---: | ---: |
| Additional native GO process routes | 2 | 133 |
| Source Attributes with reviewed native type | 4 | 16,059 |
| Source Attributes preserving an untyped compound/application label | 10 | 18,997 |
| Source-local processes with explicit reviewed definitions | 45 | 6,199 |

`knallgas_bacteria` maps to `GO:0019412`: the source specifies hydrogen donor,
oxygen acceptor and aerobic metabolism. Its cited [Hydrogenothermus culture
study](https://doi.org/10.1099/00207713-51-5-1853) supports that meaning. The
broader `dark_hydrogen_oxidation` group permits other acceptors and is not an
alias. `methanotrophy` maps to `GO:0046188` methane catabolism: source members
include [nitrate-dependent anaerobic methane oxidation](https://doi.org/10.1038/nature12375),
so neither oxygen dependence nor methane-monooxygenase activity is inferred.
The study's [published equation correction](https://doi.org/10.1038/nature12619)
is included in the evidence. The two rules retain prediction/computational-model
provenance and preserve original source tokens and record citations.

Four exact source labels have a trait interpretation: `chemoheterotrophy`
(`METPO:1000636`), `photoautotrophy` (`METPO:1000656`), `photoheterotrophy`
(`METPO:1000657`) and `plant_pathogen` (`METPO:1004003`). The native declarations
remain `OntologyClass`. The source-column/literal Attribute receives the class
in its **has_attribute_type node slot**; original use edges retain record-level
provenance. This is not an edge predicate, a direct organism-to-class phenotype
assertion, a class-category override, or evidence that every strain shares a
reported species-level characteristic.

Ten other labels retain their complete meanings as source Attributes without
native types: `aerobic_anoxygenic_phototrophy`, `aerobic_chemoheterotrophy`,
`anoxygenic_photoautotrophy`, its `Fe_oxidizing`, `H2_oxidizing` and `S_oxidizing`
subtypes, `oxygenic_photoautotrophy`, `phototrophy`, `methylotrophy` and
`oil_bioremediation`. These are finite representation decisions, not claims of
exact ontology grounding. Native related synonyms do not authorize removal of
oxygen/donor qualifiers. In particular, `METPO:1000660` requires light as the
primary energy source, whereas the source's phototrophy union includes aerobic
anoxygenic phototrophs using light to [supplement organic-energy
metabolism](https://doi.org/10.1038/ismej.2017.79). The original literal remains
queryable even when its native type is unresolved. The reported-annotation set
therefore contains 27 exact pairs, counting the original 17.

The [45-row local scope table](../mappings/canonical/microbedecoder_process_scope_definitions.tsv)
preserves actual process meanings, including compound acceptor/donor and
pathway-entry scope, without inventing ontology equivalence. Every row binds an
exact source column/literal to a paraphrased definition, HTTPS evidence, reviewed
version, archive/member SHA-256 and source start line. The loader rejects malformed,
duplicate, incomplete or non-process rows and exposes immutable declarations;
it neither downloads a new vocabulary nor classifies unknown labels by spelling.
The consumer preserves source-specific identity rather than reusing an unscoped
global label node for definitions from different fields.

`sulfate_respiration` remains local despite the promising `GO:0019420` label.
The pinned authority explicitly places it under `GO:0000103` sulfate assimilation,
whose definition requires incorporation into sulfated compounds; that is not
the respiratory process. Its terminal-acceptor wording also needs correction.
[Experimental energy-conservation evidence](https://doi.org/10.1126/science.aad3558)
supports the source meaning but does not repair native GO ancestry. Neither
the authority nor the source process is silently rewritten. Other held targets
similarly retain exact source meaning rather than collapsing to generic respiration,
replacing an entire process with an enzyme activity, or asserting a complete
pathway from one step.

The immutable [MicrobeDecoder assembly instructions](https://github.com/thackmann/MicrobeDecoder/blob/872726c257b39d14ffb1827df09127b5c8ef72bb/Database/FAPROTAX/getFAPROTAXpredictions.R#L69-L75)
explicitly name FAPROTAX 1.2.12, matching the reviewed archive. That strengthens
vocabulary-version compatibility but still does not prove that this commit
generated the saved local CSV or revalidate individual taxonomic assignments.
The local definitions are reviewed semantic context, not refreshed FAPROTAX
predictions. Native grounding remains open for the 45 local processes and 10
untyped source groups; source data coverage and valid representation are separate
acceptance dimensions.
