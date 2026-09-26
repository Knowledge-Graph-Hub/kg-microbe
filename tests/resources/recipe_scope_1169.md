# Three observed recipe-scope holds (#1169)

The JSON file is an immutable excerpt of actual local MediaDive and native
ChEBI inputs, with SHA256 fingerprints and native/mapping line numbers. The
complete raw occurrences were inspected: source 331 occurs in solution 500,
source 104 in solutions 81 and 486, and source 1902 in solution 4785. None
has an embedded external identifier. Only 331 supplies molecular concentration.
Both legacy mapping files assert the same three reviewed targets.

- Source 331 explicitly says `Tris(hydroxymethyl)methylamine`. Its 6 g/L and
  49.5295 mmol/L imply approximately 121.14 g/mol. Native CHEBI:44356 is TES,
  the sulfonic-acid derivative with CAS 7365-44-8; native CHEBI:9754 is Tris,
  CAS 77-86-1. The finite hold rejects the TES identity without automatically
  installing a replacement chemical mapping.
- Source 104 says `(NH4) citrate`, without a counterion count, CAS, external
  identifier or mmol value in either occurrence. Native CHEBI:63037 is the
  triammonium salt. The hold does not assert that every generic ammonium
  citrate is a different compound; it withholds an unsupported narrowing.
- Source 1902 says `(NH4)2S4`, not the native sulfate formula `(NH4)2SO4`.
  No source evidence licenses adding oxygen or treating it as a typo. The
  ingredient remains source-local rather than receiving an inferred identity.

The review was performed on the original-name-preserving consumer at
`64babb4913c51c956b79d174bc30f0b69a22295a`, with diagnostic candidate SHA256
`9e481e31f23b7a2414537f967ea513a7b494824799a002ca4300765f5acea0f1`.
It found four newly exposed recipe routes, in addition to the three existing
direct compound lookups. These are finite lexical/target exclusions, not
target-wide bans, blanket rules for parentheses, or changes to native ontology
assertions. Tests add normalized spellings and stale/fallback arrangements as
synthetic adversarial cases, separately from the native evidence excerpt.
