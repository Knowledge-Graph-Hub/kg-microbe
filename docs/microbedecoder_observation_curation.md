# MicrobeDecoder observation curation (#650)

## Report-only textual phenotype groundings

The canonical `microbedecoder_phenotype_mappings.tsv` contains 22 exact
field/literal rules: three Gram-stain values, nine oxygen-tolerance values and
ten cell-shape values. Each target was reviewed against a native active METPO
class with a textual definition, phenotype ancestry, and the exact literal as
a BacDive-attributed related synonym. This is source-scoped term normalization,
not promotion of related synonyms to global identity.

Native version and fixture provenance are in
[the authority note](../tests/resources/microbedecoder/phenotype_curation_authority.md).
Runtime admission checks exact active target declarations and tracks the
actual METPO export and mapping table through consumed-input finalization.

The producer retains every original `has_attribute` edge. It writes reviewed
matches separately to `phenotype_normalizations.tsv`, retaining subject,
source-record digest/ordinal, source column, literal/backslash encoding,
primary source and evidence tier. Target metadata, evidence URI, rationale
and `reviewed_literal_grounding_not_graph_assertion` make the report's limited
meaning explicit. Join using subject, source_record, source_column and value;
do not join on the label alone or propagate observations to a taxon's members.
Rows are source token observations, not distinct organisms or independent tests.

The schema limitation is deliberate: pinned Biolink 4.4.2 `has_phenotype` has
domain BiologicalEntity and range PhenotypicFeature. LPSN's OrganismTaxon and
METPO's current OntologyClass exports do not satisfy those endpoint types.
Neither retyping authority-owned nodes nor substituting a vague predicate is
justified. The report is not a merge input, and source graph finalization does
not certify the sidecar as a graph member. Acceptance must fingerprint and
compare that report separately. A valid graph phenotype route requires a
reviewed taxon/phenotype model and ontology-owner category handling upstream.

Positive plus negative Gram observations are preserved separately; they are
not a newly observed variable result. Broad and obligate oxygen terms are not
interchanged. Nine other shape synonyms lack native textual definitions;
`other` is ambiguous. Flagellation does not automatically establish motility.
Numeric codes and signed assays require an independently established coding
scheme for the actual saved source fields and remain unconverted.

## One record-specific chemical correction

The saved Ilyobacter tartaricus record (LPSN 777027, strain GraTa2/DSM 2382)
reports `tartate` in its Bergey substrate field. The original
[Schink 1984 paper](https://d-nb.info/1105570576/34), including its fermentation
products, independently supports tartrate. The exact complete raw record is
pinned by canonical JSON SHA-256
`de979939d39a74aad45a0edffe59cde4e11b6d294ee9fb22e848a12bd0dda13f`.

Only that authenticated record/field resolves to native `CHEBI:132950`
(`tartrate`). The broad native class does not invent a counterion or narrower
stereoisomer. The graph retains the original misspelling, source citation and
record locator, and records the withdrawn local placeholder as original_object.
It does not create a new ChEBI stub or a global `tartate` synonym. The constructor
validates the native ChEBI declaration and fingerprints the consumed authority.

Admission runs before empty-field/token filtering. Whitespace-normalized IDs
identify the guarded record as the producer would, but changed original IDs,
citations, fields or full-row bytes fail closed; they are not admitted by
normalizing away the difference. A new source snapshot requires reviewing any
changed guarded record. The two earlier record-scoped unresolved `sugar`
observations are unchanged.

The chemical-mapping skill's reviewed-release policy was followed: no floating
MIM aliases, vendor changes or manual unified-map edits. Independent native and
source evidence can support a scoped correction without converting it to a
globally supported MIM alias. Peptones, culture-medium abbreviations, combined
substrates and the ambiguous `3-methylacetate` name remain distinct curation work.

## Acceptance limits

These changes do not close every interpretation in #650. Separate the process
mapping queue, local materials, undecoded assays/codes and the phenotype graph
model blocker. Historical label totals are not a present-day acceptance target.
Use the complete current source inventory and independent full-field comparison;
then review a freshly merged graph before making release claims.
