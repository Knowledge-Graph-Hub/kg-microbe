# Source finalization and merge responsibilities (#1082)

`kg transform` now runs each producer, explicitly finalizes its TSV bundle,
and only then writes `source_fingerprint.json`. A previous success marker is
invalidated before the producer starts. Failure leaves no success marker
claiming that the attempted build completed.

Finalization stages its own changes and reports beside the source outputs,
validates all of them, then publishes them. Existing producer output writes
are unchanged. This is **not** a whole-source transaction: producer output
may already be visible, and publishing several files is not one atomic
filesystem operation. Exact member hashes in `source_finalization.json`
prevent partially replaced or subsequently edited bundles from passing the
public merge gate.

## Semantic decisions occur upstream

- Known IRI/CURIE aliases and FOODON/PATO imported categories are normalized
  in source files. FOODON ancestry is read from the effective raw directory,
  not a hidden default checkout. Original changed rows are retained in
  `source_canonicalization.tsv`.
- Every referenced or declared GO identifier is checked against the selected
  local GO authority, including named but incorrectly categorized importer
  declarations. Exact replacements retain original endpoints; historical
  terms without a unique replacement remain historical evidence, not guessed
  identities. `go_reference_resolution.tsv` retains source evidence.
- External reference resolution is a source-bundle operation, with explicit
  local authority and lossless original-node/edge evidence in
  `source_reference_resolution.tsv`. A reference missing from one transform
  is not presumed missing from the graph: named dependency ontology
  declarations are recognized and fingerprinted. Unsupported references are
  reported, never guessed from labels or accession versions.
- Exact consumed authority/dependency bytes are recorded. The normal source
  fingerprint additionally records these dynamic inputs; freshness checking
  detects missing or changed inputs alongside static code/data dependencies.

## TSV representation is explicit

Legacy producers default to CSV-quoted TSV. A producer writing native KGX
TSV declares `TSV_QUOTING = csv.QUOTE_NONE`. Finalized files always use
literal unquoted KGX TSV, with LF terminators and no interpretation of
literal quotation marks. Downstream readers of finalized TSVs must use
`quoting=csv.QUOTE_NONE`.

Only free-text `name` and `description` controls are flattened, with the
original row retained in the canonicalization audit. Scalar assertion or
context controls require explicit producer encoding; finalization refuses
to silently flatten them. MicrobeDecoder uses `value_encoding=backslash`
for reversible observation-value encoding.

## Merge validates; it does not repair semantics

The public `load_and_merge`/`kg merge` entry requires versioned source
finalization records, exact configured graph member sizes and SHA256 hashes,
mandatory audit-report hashes, current producer/finalizer code, and unchanged
consumed authorities/declared inputs. There is no path-based fixture exemption.
`configuration.allow_unfinalized_sources: true` is an explicit **diagnostic
opt-out**, printed prominently and recorded as
`provenance.source_finalization.diagnostic_opt_out` in the resulting manifest.
Such an output is not a finalized release. The lower-level `merge` function
is a prepared-input KGX API; its caller owns preflight and publication.

KGX ingestion rejects noncanonical source identifiers, imported fallback
categories, and nonscalar relations rather than repairing them. After graph
union, required validation checks canonical representation and endpoint
closure, including unresolved authoritative anonymous endpoints. It does
not open ontology databases or retarget/drop biological assertions. The
legacy `*_reference_resolution.tsv` archive member now explicitly records
**validation with no semantic rewrites**; source disposition reports live
with the sources that made those decisions.

Residual merge operations are serialization and publication: union node
provenance, preserve independently keyed observation/context/evidence rows,
deduplicate exact normalized assertions, order/project KGX columns, remove
internal edge keys and known auxiliary columns, normalize transport CRLF,
recount final TSV statistics, and build a byte-accurate archive manifest.
Identical duplicate columns can coalesce; conflicting values and embedded
carriage returns now fail rather than being erased. Legacy
`knowledge_source` filling and finite known provenance aliases remain
explicit compatibility handling; neither licenses a category or identity
decision. Graph/statistics publication remains staged: required validation
failure preserves the previous release; optional stats failure withholds
only the failed stats output.

## Direct Python callers

Call `producer.run(...)` followed by `producer.finalize(fresh_run=True)`.
An exact repeat `producer.finalize()` validates prepared bytes/authorities
and returns without erasing earlier audit evidence. A single
ontology uses `producer.finalize(file_prefix="go_", fresh_run=True)`, matching the CLI's
scoped branch; it does not certify other ontology files. Use `kg transform`
for the complete success-marker/freshness workflow. Do not merge raw
producer files and rely on merge to make the semantic decisions later.

Bakta declares `finalization_output_dirs` for only the datasets produced in
the selected run. The base finalizer stages and validates every selected
dataset before publishing its own changes, without recursively discovering
stale dataset directories. Each selected dataset receives its own exact-byte
record; the parent transform success fingerprint follows all of them.
