# KG-Microbe validation contract v1

Machine identifier: `kgm-validation-contract-v1`, exposed by
`kg_microbe.utils.kgm_validation_profile.validation_contract()`.
This contract distinguishes evidence layers; it does not replace their implementations
or introduce a graph repair, strict-validator suppression, or automatic release gate.
The original validators and their findings remain authoritative for their own scopes.

## Separate layers and verdicts

| Layer | Checks and evidence | Does not establish |
| --- | --- | --- |
| Source finalization | Canonical source TSVs; explicit upstream identifier/category/reference decisions; original-row audits; consumed-input identities | Atomic rollback of all producer writes; global graph completeness |
| Source admission | Configured producer files, current finalization/fingerprint and consumed dependency bytes | Correct biological interpretation from byte equality alone |
| Merge representation | Canonical serializer output and declared cross-source endpoint closure | Strict Biolink conformance, all-predicate acyclicity, chemical identity |
| KGM model | Pinned local Biolink checks plus separately counted project rules and native-property tables | Strict external-model pass when a house rule was used |
| External KGXVal | Predicate and subject/object category diagnostics against the selected local model | Original graph-row counts or complete edge-signature reconstruction from the CSV |
| Strict KGX | Original installed-validator callbacks, types, required fields and context | Biological correctness; graph rewriting; automatic exemption for project extensions |
| Paths | Named structural tests, exact checks or explicitly bounded proxies | Every possible path, all-predicate self-loop freedom, ingredient utilization |
| Scientific disposition | Exact source/native evidence and independently reviewed interpretation | A replacement machine status or publication authority |

Record each validator's scope, input/model/code hashes, completion status and limitations.
Process exit 0, a present report, unchanged counts or a successful archive write is not a
scientific pass. Source/merge validation is mandatory; optional diagnostics retain their
separate behavior. A model-review allowance is never silently transferred to strict KGX.
No layer in this module grants release approval. See `SOURCE_MERGE_CONTRACTS.md`,
`PREMERGE_SOURCE_FINALIZATION.md`, `SEMANTIC_MODEL_DECISIONS_20260914.md` and the model/path
review skills for the actual rules and their evidence requirements.

### Canonical transport is not the strict validator's object schema

KGM's mandatory edge TSV columns are `subject`, `predicate`, `object`, `relation`,
`primary_knowledge_source`, `knowledge_level`, and `agent_type`. Edge `id` and KGX's
internal `key` are deliberately absent. The installed strict KGX validator requires an
edge identifier and currently emits that missing-ID callback twice per edge. Retain those
errors; do not fabricate identifiers or reinsert serializer internals to disguise them.

Canonical TSV cells are strings. Pipe-delimited category/provenance/xref tokens in this
transport are not Python lists in a validator's in-memory object schema. Report conversion
rules explicitly and separate genuine scalar-field violations from transport/type
callbacks. Native METPO/MICRO and local source namespaces also need the appropriate prefix
context; a missing registry prefix is neither evidence of an invalid biological identity
nor permission to silently alias its spelling.

The reviewed candidate's original **76,611,293 strict callbacks** remain recorded as errors,
not unique invalid rows. The 17,637,435 repeated `unit` logger warnings are a different
stream, not additional callback findings. The source/category disposition report does not
suppress either stream, change the pinned schema/context, or claim a strict pass. Strict
delta reconciliation must retain original totals and full source attribution limits.

### The legacy-named merge report

`merged-kg_reference_resolution.tsv` now contains a validation summary, not a list of
semantic edits. Its columns are `check`, `status`, `nodes`, `edges`, and
`audited_native_nameless_nodes`; its successful
check is `canonical_representation_and_endpoint_closure_no_semantic_rewrites`.
`write_merge_validation_report()` validates the original pair before writing that receipt.
Failures abort rather than repair graph bytes. Semantic audit files belong beside each
source output: `source_canonicalization.tsv`, `source_reference_resolution.tsv` and
`go_reference_resolution.tsv` (possibly ontology-prefixed), bound by source finalization.

The additional nameless-node count distinguishes a verified original native
declaration from an anonymous endpoint invented during graph loading. Under
#1316 a native GOLD referent can genuinely have no name. Such a row must match
an exact declaration already verified during source admission, including its
native taxon/audit evidence and admitted metadata. Neither an identifier alone
nor a GOLD prefix grants an exception. Missing or changed proof aborts; merge
does not invent a name, infer a category, resolve a new identity, or modify the
row. The count is zero when no such declaration is used. The full GOLD producer
and late-admission integration still require their separate candidate tests.

## Finite KGXVal disposition profile

`mappings/kgxval_dispositions_v1.json` is `kgm-kgxval-dispositions-4.4.2-v1`.
It classifies every exact diagnostic in the reviewed candidate CSV, retaining all six
literal fields, occurrence counts, the Biolink/predicate-map reference hashes, source
evidence locators and remaining verification. Its reference epoch is candidate archive
`158e7131025c7941ae98d70af5ca14d6efb69857ed019f7f61fa9b44279b2345`, production commit
`1408e7099d039026d7611c240938d8e177753406`; this does not replace the archive's literal
`1408e7099-dirty` manifest value. The input CSV hash is
`20ef42bf0eaf4683066f9bdcc9e2e26d7cdee1f98b4f0b4db7a2fe98877a8a6c`.

| Explicit disposition | Distinct diagnostic rows | CSV records, including repeats |
| --- | ---: | ---: |
| Registered native predicate extension (67 METPO + 3 MICRO) | 70 | 190 |
| Class subsumption: exact row evidence required | 14 | 49 |
| Growth-medium class: exact row evidence required | 1 | 1 |
| Taxon phenotype: exact row evidence required | 2 | 3 |
| ChEBI macromolecule role: exact row evidence required | 1 | 2 |
| Food-material `in_taxon`: exact row evidence required | 1 | 1 |
| OntologyClass-containing category: source review required | 60 | 132 |
| Other domain/range category: source review required | 27 | 34 |
| Total | **176** | **412** |

The 70 native-property findings are registered project-extension diagnostics, **not strict
Biolink passes** and not validation of their actual assertions. Only the explicit native
CURIEs in this finite profile qualify, and each is checked against the production registry
or the three exact assay-property constants. A `METPO:`/`MICRO:` prefix is insufficient.
The fallback Biolink map is not permission to replace a native predicate, particularly a
negative observation, with a broader positive predicate.

The complete, read-only join of all **106 category diagnostics** against the original
3,354,500 nodes / 17,637,435 edges is recorded in
`data/validation-upstream-20260930.DbltzT/kgxval-category-join-01.json`, SHA-256
`1f303c86cacf136e59a9c2f5215d63c38c06c50dade1f0cc903e9421dd10e415`.
Inputs were hashed before/after; each matched cohort has complete supplier/relation and
existing precise-rule counters plus bounded original row/node witnesses. The committed
`mappings/kgxval_reference_dispositions_v1.json` records these finite reference dispositions:

| Evidence-backed category disposition | Exact diagnostics | Remaining action |
| --- | ---: | --- |
| Documented precise row convention supported throughout | 13 | Keep as reference project conventions, not strict passes |
| GTDB phenotype bearer declaration gap | 2 | Declare the actual named source taxa; 25 assertions affect both sides |
| BacDive recipe class/relation/provenance conflict | 1 | Upstream emitter corrected; rebuild the full 1,575-recipe cohort |
| Chemical subclass exceptions | 2 | Trace solution:6257 material category; retain independent finite NCIT Mucin disposition |
| Mixed taxon/strain/genome hierarchy | 2 | Verify exact paired categories, inferred relations and #834 scope |
| FOODON process/quality classes typed Food | 4 | Authoritative branch-based categorization, not label inference |
| FOODON organism-class `in_taxon` | 1 | Decide exact class restriction/mapping semantics, not equality |
| Participant/continuant versus pinned-model occurrent range | 13 | Native-relation projection/model review; no schema replacement |
| Anatomical/cellular temporal assertions | 7 | Native existence/developmental relation projection review |
| PATO relational quality `towards` | 1 | Review RO:0002503 projection to `actively_involved_in` |
| UBERON-imported gene endpoints typed OntologyClass | 1 | Ground the two native gene declarations before source correction |
| Generic/union OntologyClass endpoint declarations | 59 | Per-supplier/relation authoritative ancestry/category review |
| Total | **106** | **13 supported reference conventions; 93 still require action** |

Together with the 70 registered native-predicate extensions, this gives 83 explicitly
supported project-scope dispositions and 93 action-required diagnostics. It does **not**
mean the graph passes strict or scientific validation. The 59 generic endpoint cohorts
now have exact source/relation ownership and witnesses; complete authoritative semantic
ancestry is still missing, so they are not accepted or silently deleted. The finite catalog
states the concrete action for each signature and retains the original strict finding.

The CSV omits subject/object identifiers,
the opposite category set, original relation and provenance. Several graph signatures can
therefore serialize to the same diagnostic row. None of the CSV repetition counts can be
interpreted as graph-edge counts, and identical signatures cannot establish preservation.

To finish an individual category acceptance, retain exact source assertions and both
endpoint declarations, test the precise documented rule (including relation and namespace
conditions), bind selected authorities, and record incompatible/unattributed cases as
upstream work. Do not infer an exact class, taxon, compound or assay meaning from a label or
category alone. The finite classifier deliberately has no function that turns a category
signature into a house-rule pass. Reference evidence is attached only when the complete
original CSV hash, all occurrence counts **and an explicitly supplied graph archive hash**
match the pinned reference epoch. Byte-identical CSVs alone do not identify their graph.
With no supplied archive, classification still runs, but `reference_evidence_applies`
is false and no historical row assessments are attached. The output always identifies
the historical `reference_epoch` separately.

### Run without changing original evidence

```bash
poetry run python scripts/classify_kgxval_report.py \
  --report data/<actual-review>/model/model-kgxval-errors.csv \
  --report-sha256 20ef42bf0eaf4683066f9bdcc9e2e26d7cdee1f98b4f0b4db7a2fe98877a8a6c \
  --require-reference-cohort \
  --graph-archive data/<actual-candidate>/merged-kg.tar.gz \
  --output data/<new-evidence-directory>/kgxval-dispositions.json
```

Use the exact local report selected by the caller, not an implicit latest archive. The
output parent must already exist and the output file must be new. No ontology service or
graph TSV is read. The original CSV remains byte-identical; the output binds its input,
profile, optional archive and implementation/registry identities before and after
classification. Archive bytes are streamed for hashing, not extracted or revalidated.
Supplying the matching archive and CSV does not prove that a validator produced that CSV
from that archive; original run receipts remain necessary. The model hashes identify the
reference epoch, not proof that an arbitrary CSV was generated by that model. With
`--require-reference-cohort`, a supplied archive differing from the reference aborts;
otherwise it is classified without attaching historical assessments.

The finite catalog requires a join locator, digest and byte size, paired endpoint
declarations matching witness identifiers/categories, and each original full-row digest.
These are local integrity/shape guards, not authentication of the external saved join.
Portable witness assertions omit original columns, so their full-row digests cannot be
recomputed from that reduced projection. Independent review checked all retained
counters, witnesses, endpoint declarations and full-row digests against the original
saved join, without rescanning the graph.

Exit codes: 0 means only registered native-extension diagnostics were classified (still not
a strict/scientific pass); 2 means classified findings require additional review; 3 means
an unregistered exact diagnostic was encountered. Invalid headers/profiles/input digests
abort. The complete reference run intentionally exits **2**. Omitting
`--require-reference-cohort` allows a supplied subset or a later report to be classified,
but does not certify completeness of its originating validator run. Empty reports do not
certify completion. Unknown diagnostics remain visible and cannot inherit a prefix or
category waiver; a newly reviewed cohort requires explicit curation and a profile revision.

The classifier never changes `strict_conformance`, `scientific_acceptance` or
`release_authorized` to true. Do not use `classification_complete` as an acceptance verdict.

## Regression coverage

`tests/test_kgm_validation_profile.py` uses committed tiny immutable diagnostic and graph
fixtures. It tests every finite entry, all six signature fields, new native IDs, report
multiplicity, corruption/partial-cohort controls, conservative exit statuses, and actual
merge-validation success/failure with byte-preserved graph files. The existing canonical
serializer, source-finalization, admission and semantic-model tests remain separate;
passing the new classification tests does not replace them.

## BacDive recipe-class correction from this review

The 16 assertions matching the `GrowthMedium` subclass diagnostic are not the whole emitter scope. A complete
read-only source inventory found **1,575 distinct recipe-class assertions** emitted by
BacDive with `subclass_of`, original relation `rdf:type`, and supplier `infores:metpo`.
They were generated by BacDive code, not native METPO axioms. METPO defines the parent
`METPO:1004005` (growth medium); catalogue recipes are named recipe classes, consistent
with the existing MediaDive hierarchy, not individual culture batches.

The upstream emitter now uses `rdfs:subClassOf` and `infores:bacdive`. Subject, predicate,
object, knowledge level and agent type remain unchanged. This does not change the parent
ontology declaration's own provenance. Positive and negative growth assertions retain
their exact native predicates and evidence; ambiguous values still produce no observation.
The prospective full-row difference and unchanged-input guards are retained in
`data/validation-upstream-20260930.DbltzT/bacdive-recipe-source-inventory-01.json`.
The original source and candidate remain untouched. An actual BacDive rebuild, complete
assertion conservation check and fresh model/path review are still required; this code
change is not a post-merge repair or a new KGXVal waiver.

## Other producer corrections from this review

The shared MetaTraits worker now declares a taxon when its first quantitative
phenotype assertion is emitted, even without a mapped categorical trait. Exact
fixtures cover all 25 affected GTDB records and all six quantitative emission
routes; empty or deferred records do not acquire edgeless taxon declarations.
The phenotype observations are unchanged. The existing GTDB hierarchy pass will
also see these newly declared taxa: 17 have current accession-based species
bridges, so the rebuild can add existing-policy hierarchy and NCBI crosswalk
edges. This is not a promise of exactly 25 changed graph rows or permission for
new identity assertions.

MediaDive's explicit retained solution identifiers now receive the solution
category (`ChemicalMixture`) before generic ingredient category lookup. The
current source inventory identifies solutions 6257, 6420 and 6572 as affected.
Only 6257 has a downloaded child formulation; the latter two have explicit
`solution_id` references but missing child recipes. Correcting their source role
does not invent composition, identity or subclass assertions.

These fixes remain upstream implementations awaiting production rebuild and
conservation checks. The finite reference catalog describes the original pinned
epoch, not a retrospective acceptance of repaired output. Ontology metadata
exclusion also occurs only upstream: exact annotation-property evidence is
required, true semantic punning is preserved, and mandatory exclusion audits
and consumed authority hashes accompany finalization.
