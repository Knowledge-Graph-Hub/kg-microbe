# Source and observation provenance (#1070, #1061)

## Model decision

`primary_knowledge_source` contains one information-resource identifier, never
a pipe list of providers or a mixture of providers and records. BacDive and
MediaDive growth edges identify `infores:bacdive` as their primary resource.
Their BacDive record attribution is retained in `publications`, for example
`https://bacdive.dsmz.de/strain/160227`. Other supplied publications are retained.

This uses the pinned Biolink 4.4.2 model directly: `publications` is a
multivalued association slot whose definition explicitly includes public web
pages. `supporting_documents` is deprecated, `supporting_data_source` identifies
an InformationResource rather than an individual record, and `source_record_urls`
belongs on a nested RetrievalSource rather than directly on an association.
No new evidence slot or blanket primary provider is introduced.

The finite migration table recognizes existing ontology filenames and
MediaDive/BacDive producer aliases. It does not infer resources from arbitrary
filenames. Legacy BacDive Python-list or pipe notation migrates into scalar
resource plus publication evidence. A field containing multiple distinct
primary providers fails with a rebuild instruction: separating an already
pooled field cannot reconstruct which provider supported which observation.

## Observation identity, within and across sources

Edge identity is the SHA-256 of the complete normalized assertion payload:
subject, predicate, object, scalar relation, primary resource, measurement,
unit, knowledge level, agent type, contextual metadata, and attached evidence.
Declared multivalued properties normalize to sorted unique lists. Unknown
extension properties stay scalar; literal pipes in free text remain literal.

Two assertions collapse only when their complete normalized payloads match.
Different primary sources, records, publications, measurements, contexts, or
knowledge/agent classifications produce separate edges. A missing value is
also distinct from an explicitly supplied value; later records do not fill or
overwrite earlier observations. Evidence is never copied between these edges.
Even two equal temperatures stay separate when they have different evidence.

The cross-source merge preserves KGX's existing node merge policy but uses
the same exact-assertion edge identity. It no longer calls KGX's scalar-pooling
edge merge. Export does not inject `knowledge_source=Graph` or a filename.

The edge `id`/internal `key` are deterministic transport hashes, not additional
evidence. An explicit upstream edge ID is retained as `source_assertion_id`
and participates in identity. Re-exporting and reading the generated edge ID
does not manufacture a new upstream ID or change observation identity.

This supersedes the temporary last-row scalar policy. All distinguishable
observations survive; repeated source rows that are identical in every supplied
field collapse. The pipeline cannot invent observation identifiers or recover
distinctions that upstream never supplied. Queries must not assume one edge per
subject/predicate/object triple, and should aggregate observations explicitly.

## Rebuild and acceptance

Previously generated TSVs and archives are unchanged. Regenerate BacDive and
MediaDive to emit the new schema directly, regenerate ontology outputs to
replace filename source placeholders, then merge fresh source TSVs. The finite
legacy migration supports older unmerged source files, not reconstruction of
already pooled observations in an old merged graph. Preserve the old archive
for comparison. Edge counts can increase substantially because observations
previously overwritten or pooled are now retained.

```bash
poetry run pytest tests/test_bacdive_provenance.py tests/test_bacdive_lpsn_crossref.py \
  tests/test_provenance_serialization.py tests/test_kgx_relation_source.py
```

The tests exercise both real producers, positive/negative growth, KGX source
ingestion, cross-source merging, compressed export and re-ingestion. They
preserve all seven PREGO-style rows and four temperature rows with their exact
evidence and scalar metadata; a separate two-source fixture verifies exact
duplicate collapse, same-provider conflicts, missing units, explicit upstream
IDs, and literal pipe text. Thread, spawn and fork tests cover worker adapters.

Production acceptance should verify scalar information-resource PKS values,
record URLs in publications, stable repeated exports, and preservation of
source observation/evidence bundles. Passing fixtures does not establish that
an existing production archive has been rebuilt.
