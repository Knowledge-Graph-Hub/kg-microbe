# GOLD unresolved native referents (#1316)

The selected native GOLD export supplies organism IDs, names, category,
provider and taxon xrefs. It contains metagenomes, binned genomes and a blank
name as well as strain-like labels. A name differing from the taxon's name
does not independently establish a named strain. The reviewed current cohort
has no independently accepted structured strain-evidence records.

The fold-restoration cohort retains 531,324 unverified referents surviving the
pre-alias trim (471,702 previously retained plus 59,622 formerly folded) as
`biolink:NamedThing`, preserving their literal IDs, names, xrefs and providers.
This does not create new database-record entities: the original referent's
specific type remains unresolved. Each native taxon field is retained as
`biolink:related_to`, with its original
`gold:organism_v2.ncbi_taxonomy_id` relation. The mandatory
`gold_taxon_dispositions.tsv` preserves complete native declarations and
parent claims, source hashes and row coordinates, remap witnesses, rejected
taxon-class proposals, and emitted declarations/associations.

Consumers must join the selected sibling GOLD's finalized, current-code
bundle and verified native audit. Before the separate finite alias repair, the reviewed MicrobeDecoder scope comprises
10,554 current crosswalk observations to 10,552 such IDs (5,317 observations
plus 5,237 restored original GOLD field references), as `biolink:related_to` in both
predicate and relation. Its mandatory `gold_crosswalk_dispositions.tsv`
preserves the complete CSV record, original column/cell/token and source
hash/ordinal, original identity proposal, emitted association, and admitted
GOLD declaration/native witness. Contradiction quarantine precedes this route.

Queries must explicitly traverse these associations, not treat them as
taxonomic inheritance or identity. Neither labels nor xrefs justify copying
taxon phenotypes onto unresolved referents. The repository's independently
evidenced named-strain convention (#834) is unchanged for other producers.

The 59,622 historical normalized-label folds are disabled. Their original
source IDs and 32,537 retained record-level environment assertions are restored.
The latter replace 31,933 collapsed taxon-level environment assertions: 604
distinct source observations were previously lost to fold-induced deduplication.
Exactly 560 source names differ literally despite normalized equality; names
are never replaced by the selected taxon's label. All 154,693 original incident
claims, including excluded Study/sample contexts and 6,662 root-only habitats,
remain in `gold_lexical_fold_restorations.tsv` with complete native declarations,
hierarchies, original/retired ID witnesses and old-versus-restored projections.
The compatibility `organism_folds.tsv` is header-only and is not consumed by
MicrobeDecoder. Its 2,523 contradicted folded-ID proposals remain quarantined;
only 5,237 noncontradicted source crosswalk observations are restored.
Existing taxid remapping, trim behavior, non-folded environment observations, and the
seven independently reviewed Abscess crosswalk quarantines are unchanged.
An excluded GOLD reference is not restored from raw data merely because its
identifier is present in another producer.

The separate #1327 policy resolves exactly three retired taxon identifiers using
actual selected NCBI alternative-ID assertions and their taxdump witnesses. It
restores eleven additional native source referents, preserving all 27 original
incident claims in `gold_selected_taxon_aliases.tsv`. Eleven taxon associations
and seven non-root environment observations are retained; the four root-only
habitats and five Study links remain excluded, with original evidence intact.
The original pre-alias parent target remains separate in historical fold
diagnostics, so these records are not counted as formerly folded. A missing
native replacement taxon declaration uses the exact admitted selected-authority
declaration, never the retired taxon's label attached to a new ID. The original
native taxon declaration stays in the mandatory alias audit. All other taxon
resolution and excluded-branch decisions retain their existing behavior.

This finite extension predicts 531,335 unresolved source referents and
637,297 nodes / 765,987 edges for the complete GOLD source. It also admits the
original MicrobeDecoder claim to `gold:Go0028995`, previously rejected because
the selected ontology used a different retained taxon ID. Whole-source and
consumer replay must confirm exact rows and multiplicity, not only these totals.

The one native blank name (`gold:Go0531699`) is retained literally. Its narrow
merge admission exception requires an independently rejoined, exact semantic
declaration, not a prefix/ID allowlist. All category and predicate changes
occur in source transforms/finalization. Merge verifies unchanged admitted
bytes; it performs no new identity resolution or graph rewriting.

The independently reviewed same-stage prediction, before the separate selected
taxon-alias extension, is 637,286 GOLD nodes and 765,969 edges. Relative to the
552,376/705,743 unresolved-referent baseline, this adds 59,622 source records
and revives 25,288 native taxon declarations previously left without edges,
adds 59,622 audited taxon associations, and restores 604 environment observations.
All other rows are conserved. Producer replay and acceptance status are reported
separately; these counts do not claim the production merged archive was rebuilt.
