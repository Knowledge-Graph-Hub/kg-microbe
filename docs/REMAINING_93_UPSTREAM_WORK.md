# Remaining 93 diagnostics: upstream implementation and acceptance boundary

This work continues the finite reference assessment in `VALIDATION_CONTRACT.md`.
The number 93 denotes distinct KGXVal diagnostic patterns, not individual edges,
independently confirmed scientific errors, or 93 GitHub issues. The original
reference catalog and validation results remain immutable. New implementations
do not retrospectively close that reference epoch or authorize a release.

## Implemented producer changes

| Work package | Upstream correction | Conservation boundary |
| --- | --- | --- |
| GTDB assembly assignment | Emit `biolink:in_taxon` / `RO:0002162`, not taxon-class subsumption, for assembly-to-species assignments. | Keep assembly IDs, Genome typing, paired-accession aliases, and independent taxon hierarchy/NCBI close/broad mappings. The complete source audit accounts for all 901,341 assignments. |
| FOODON declarations and imports | Classify asserted organism, process, quality and information-content branches, retaining the existing food-material fallback elsewhere. Non-biological processing uses Activity, not an invented biological process. | Keep all assertions and native relations. The 460 selected endpoint occurrences split into 366 quality, 93 process, and one information-content claim; the last is not a quality merely because its incoming relation says `has_attribute`. |
| Generic ontology imports | Replace OntologyClass only where a selected local authority supplies live class declarations and supported native ancestry. | No blanket category deletion, label inference, predicate-driven typing, identity acceptance, remote lookup, or union of different ontology releases. Unknown IDs retain their original category. |
| Two imported gene endpoints | Use the finite pinned NCBI Gene records for NCBIGene:26468 and NCBIGene:55553 to provide Gene category and blank labels/descriptions. | Preserve UBERON expression assertions and supplier provenance. Do not invent taxon edges or classify unknown NCBIGene identifiers by prefix alone. |
| FOODON schema-only leakage | Exclude three individually reviewed, live native object-property declarations from ontology entity output, with original-row audits. | Preserve their predicate/relation usage, unrelated object properties and class/individual punning. Importers that attempt to reintroduce them fail the live-class category contract. |
| Retired Madin plant-structure reference | Replace FOODON:03420174 with its unique native FOODON OWL replacement PO:0009011 within the exact source habitat's identifier list. | Preserve the companion UBERON:0002049 reference and label, and retain original source evidence; the corrected target receives PO's live plant-structure label. No label-derived identity or merge-time repair. |

The source-finalization resolver reads native inputs through immutable consumed
snapshots, records their exact identities, and keeps original/normalized row
audits. A missing, empty or malformed selected authority aborts; an unknown ID
in the generic authority remains unresolved. FOODON instead requires a live class
declaration and rejects missing, retired or schema-only IDs. Gene curation checks
the exact pinned native response hash, identifiers and projected fields, not just
the shape of a manually curated file. Both OBOGraph obsolete encodings are
recognized, and malformed or contradictory retirement flags abort. FOODON's early ontology-file category
handlers defer authority-dependent decisions until preprocessing finishes, so
an alternate raw directory cannot inherit a process-global cached decision.
The policy runs again after external endpoint declaration and **before** GO's
final byte checkpoint. Merge does not run the category resolver or repair
finalized graph rows.

The canonical merge configuration and all five generated variants keep their
descriptive source names outside the strict finalized-TSV input contract.
Relocating the five legacy metadata fields preserves every effective KGX input,
source order, destination and preservation option; it does not expand permitted
merge-time overrides. A manifest-derived regression covers all six configs.

Madin's finite environment-correction table is a declared producer dependency
and is consumed through an immutable snapshot. A table-only edit invalidates
the producer; a mid-run table change prevents finalization rather than being
silently fingerprinted after use.

An independent, complete FOODON audit checked all 28,378 relevant merged IDs
against both processed JSON and unfiltered native OWL. It found exactly the
three isolated schema properties and the retired ID above; the latter supplies
four Madin location assertions. No other retained obsolete FOODON ID was hidden
by preprocessing in this cohort.

A complete isolated GTDB producer build passed a multiset conservation check:
all 1,148,712 finalized nodes are byte-identical to the existing source, all
901,341 assembly assignments receive only the intended predicate/relation
change, and all remaining 569,693 edges and the pooling report are preserved.
There are no missing endpoints when declared NCBI dependencies are included.
The actual model/path skill reports retain taxonomy house conventions separately
from strict pinned-Biolink results; they are source-candidate reviews, not a
fresh merged-graph acceptance claim.

## Complete generic-category inventory, not just sampled witnesses

The read-only inventory selected all 59 generic patterns plus the separate
two-gene pattern: 2,498 IDs and 213,606 endpoint-side occurrences. Counts below
are not unique edges and are not counts of independently validated assertions.

| Authority assessment | Endpoint sides |
| --- | ---: |
| Native categories supplied | 173,661 |
| Of those, satisfy the saved diagnostic's category-range list | 173,109 |
| Of those, still incompatible with that list | 552 |
| No supported native category decision | 39,945 |

The generic helper alone makes 25 of the 60 selected **historical signatures**
fully category-supported. This is a prediction from the complete saved cohort,
not a new merged KGXVal result. The independent finite gene correction is not
counted in those helper totals. Other graph assertions involving reclassified
nodes can reveal additional diagnostic patterns on rebuild.

Unresolved sides comprise 22,921 with no selected native authority, 14,752 whose
IDs are absent from the selected declaration set, 2,203 without a supported
ancestor, and 69 obsolete/non-class declarations. Ten missing ENVO identifiers
account for 14,662 sides. An ignored-file-inclusive raw inventory found local
MeSH and NCIT sources, but no filename-matched PRIDE or GAZ authority. Two PCO
IDs have alternate pinned PATO declarations; adopting another authority requires
a separately tested selection rule, not silently combining import versions.

Follow-up native review establishes that the ten missing ENVO IDs were explicitly
retired in the selected upstream release, not lost by an arbitrary subset. Five
have unique declared replacements (9,237 endpoint sides); five have only
`consider` suggestions or no successor (5,425 sides). The processed JSON has
removed that retirement evidence. Resolving this safely requires an immutable
unfiltered authority and audited node/edge identity handling upstream, not a
category-only patch or automatic use of `consider`. The finite PREGO producer
policy now migrates only the five unique replacements, preserves the other five
as unresolved deprecated declarations, and writes a mandatory source-row audit.
The selected archive's exact regular member and decompressed bytes authenticate
each payload; a matching cache receipt alone is not authority. Independent
review includes consistently forged cache/receipt pairs and member locators.
Full native-cohort replay and fresh merged acceptance remain required.

Two BacDive Cat1 field headings were incorrectly mapped to PRIDE sample identities.
The producer now retains each heading occurrence as a record-scoped Attribute,
with an explicit local source-schema attribute type, original source context,
native BacDive identifier and citation. Its required audit preserves the rejected
PRIDE projection. Exact native PRIDE stanzas and the immutable upstream pin were
independently checked. All 19,905 raw heading occurrences and all 229,327 other
category values were conserved; the audit covers the 18,747 distinct historical
PRIDE assertions. This is a producer replay, not new merged-graph validation.

MediaDive's 1,012 generic ingredient-side occurrences and GOLD's 413 mapping-side
occurrences are inventoried separately. Better endpoint typing does not approve
chemical identity or GOLD `exact_match` claims.

## Native projection decisions remain separate

The complete reference join for participant, temporal, PATO `towards`, and
FOODON organism-class taxon patterns covers 22 diagnostics, 2,509 endpoint sides,
and 2,356 distinct graph assertions. Independent native review accounts for
2,354 exact native triples and two explicitly traced GO replacement projections.
Native provenance does not itself establish correct Biolink projection.

- Participant family: 178 `RO:0002216` capability-of-part restrictions are not
  evidence of actual participation. The other 323 assertions use participant,
  input/output or movement relations. The pinned Biolink model's
  continuant/occurrent constraint discrepancy remains visible.
  The [finite participation disposition](PARTICIPATION_DISPOSITION.md) records
  61 exact and 262 broader historical projections; the two separate GO
  quarantines leave 321 supplier assertions / 240 distinct triples. Thirteen
  original documentation/conservation tests were extended after independent
  review: 38 checks now pass, including nine permanent evidence-corruption
  controls. Fresh-producer conservation remains required. No runtime waiver
  was added.
- Temporal family: 170 distinct assertions split into 98 existence-boundary,
  10 developmental-replacement and 62 stage/order/synchrony links. Native
  evidence identified 35 UBERON life-stage descendants in the original cohort,
  plus four other misclassified temporal/life-cycle nodes. The complete finite
  native closure includes 19 additional stages. Upstream authority now classifies
  all 58 terms: 54 LifeStage, one Activity (life cycle), and three explicitly
  unresolved OntologyClass boundaries. It applies to imports as well as native
  declarations. Retyping anatomy as a process is not an acceptable correction.
  LifeStage alone does not satisfy the model's Occurrent-only temporal constraints.
- PATO's six `RO:0002503` quality-to-quality assertions require a faithful
  `towards` projection, not a fabricated biological-process target.
- FOODON organism-class `in_taxon` comprises 1,663 FOODON-to-NCBITaxon and 16
  FOODON-to-FOODON restrictions. This corrects the older ledger's shorthand;
  these are not identity assertions or a blanket taxon-category waiver.
  The [finite class-restriction disposition](FOODON_TAXON_CONSTRAINT_DISPOSITION.md)
  retains all 1,679 historical assertions. Full native review confirms 1,679
  direct existential restrictions and 35 additional equivalent-intersection
  witnesses. The documentation/test implementation is independently cleared
  after #1330, with 27 checks including eight external adversarial controls.
  Fresh merged diagnostics remain required; the count is not a forecast of
  new validator findings.
- Taxonomy conventions remain finite: native taxon-parent links, named
  strain/isolate hierarchy, historical GTDB name bridges, and the 206 inferred
  subclass assertions have different evidence contracts. Fixing assembly
  membership does not automatically accept all remaining taxonomy diagnostics.

Exact native-parent evidence now supports all 925,219 NCBITaxon and 247,366 GTDB
taxon-parent pairs in the inspected source files. The separate NCBI taxdump is a
different epoch and is not substituted for the selected ontology's direct parent
assertions. The evidence join is undergoing independent review; these counts do
not approve other suppliers, historical bridges or strict Biolink conformance.
BacDive's genus/species name fallback now consistently uses the inferred relation
and prediction/automated-agent provenance, while supplied native parent IDs retain
observation/manual-agent provenance. Independent negative controls verify both
uncached and cached fallback without changing endpoints or other observations.

## Acceptance still required

### Subsequent bounded implementation/review status

The following evidence advances individual work packages; it does not close all
93 patterns or replace a fresh producer rebuild and exact-archive review.

| Package | Current bounded evidence | Remaining acceptance |
| --- | --- | --- |
| Native RO capability/towards/temporal (#1277) | All 326 explicitly approved supplier assertions retain native predicates. Independent replay verifies 326 predicate-only changes and 93,436 unchanged rows, including 28 exact BFO projections and eight outside-cohort GO controls. The 34-assertion extension preserves every prior policy record; 90 permanent and 21 independent controls pass after the test-only RDF witness repair (#1344). Actual PATO and UBERON fresh/repeat/admission checks pass. Strict-Biolink predicate nonconformance remains explicit. | Full canonical producer rebuild and exact-merge review pending. |
| Finite PCO/GAZ/COB imports (#1291) | All 80 native ancestry decisions independently reproduced; importer and negative controls pass. | New merged diagnostics still required; PCO Attribute typing alone does not invent attribute-type links. |
| LPSN ambiguous parents (#1292) | Independent full 34,301-row reconciliation and adversarial controls support quarantine of 47 ambiguous claims, preserving 29,648 unambiguous parents. | Full producer rebuild and taxonomy dispositions remain separate. |
| Clinical BacDive tags (#270) | All 2,288 native occurrences independently reconciled. Escaped-IRI authority-selection defect #1295 is fixed and independently cleared. | Fresh finalized source and merged review pending. |
| Generic Catalase (#1290) | Full-native ingredient replay preserves 39,871 other occurrences while retaining eight Catalase observations on source-owned material IDs. Canonical-identifier bypass #1297 and read-bound parsed-cache defect #1299 are fixed and independently cleared. An additional actual-read replay preserves all 39,879 occurrence dictionaries. | Fresh finalized producer and merged review pending. |
| GOLD Abscess crosswalks (#1294) | Independently reconciled full source replay quarantines only seven unsupported exact identities; all 552,376 node rows and every other edge row remain byte-identical. All 34 location observations remain. Evidence-selection/binding findings #1300/#1301 are independently cleared. | Fresh finalized producer and merged review pending. |
| FOODON kernel/plant contradiction (#1296) | Implementation independently cleared: actual offline KGX producer and original-role/admission controls pass. Complete helper-free source replay confirms one parent quarantine, 22 category changes and 55,371 other rows byte-identical, including 30 retained incident assertions. | Fresh finalized producer and exact merged review pending. |
| GO imported subject restrictions (#1302) | Independently cleared after #1305–#1307: 60 tests include ten external adversarial controls. All 18,910 current PATO rows are reconciled: two complete quarantines and 18,908 unselected rows; original and historical-normalized routes repeat identically. | Full producer rebuild and exact-merge review pending; the separate 141 historical obsolete-subject audit rows are not covered by this finite decision. |
| Finite ENVO/PO categories (#1303) | Three definition-backed decisions cover four current source declarations and 18 unchanged incident source assertions. Native XML (#1309), original-role binding (#1310), and exact selected-member scope (#1313) fixes pass independent review. The subsequent pristine-input repair #1338 passes 158 independent checks: exactly two ENVO authority pins and their policy anchor change, supporting PREGO retirement evidence without changing categories, paths, PO or lifecycle guards. | Complete finalized producer rebuild and new merged diagnostics remain required. Native retirement evidence stays in the original authority; filtering occurs only in a private conversion member. |
| Finite NCIT imports (#1308) | Independently cleared after #1312–#1315: 135 tests include 20 external adversarial controls. Primary SQL independently reproduces 35 classes and 539 statements. Actual full-native runtime replay changes only categories on 14 declarations and preserves 19 incident assertions. The deprecated Mammal projection was explicitly rejected. | Complete integration gates, source rebuild and exact merged review remain required. |
| Nonclinical MeSH imports (#1311) | Independently cleared in 92 tests, including actual full-native public finalization, fresh repeat and late-drift controls. Complete current-source evidence covers 27 declarations and 1,499 incident occurrences. Built Environment uses PhysicalEntity; Sphagnopsida uses its preferred class concept, not a nonpreferred genus concept. | Fresh canonical producer rebuild remains required. Identity and native hierarchy projections are not approved by category repair. |
| GOLD taxonomy counterexamples (#1316) | Complete native reconciliation accounts for 605,885 records. The approved restoration preserves all 59,622 formerly folded source IDs, 32,537 source-owned environmental observations and 25,288 required taxon declarations. Subsequent selected-alias integration preserves all 637,286 baseline nodes and 765,969 baseline edges, adding exactly eleven source-record declarations, eleven audited taxon associations and seven record-owned environmental observations. The complete MicrobeDecoder native crosswalk replay independently rejoins all 10,555 selected GOLD claim payloads and 10,553 declarations. The lifecycle repair (#1342) passes 126 independent checks; all original scientific audit rows are conserved. | This full GOLD replay precedes shared source finalization. The MicrobeDecoder proof covers selected GOLD crosswalks, not its complete trait transform. The final canonical rebuild and exact-archive review remain required. Names do not establish record/taxon identity. |
| MediaDive native recipe identity (#1317–#1319) | Complete native replay conserves 39,879 recipe assertions, with only the reviewed endpoint changes: 998 nested-solution assertions, five Oatmeal observations, one Substrate observation and eight previously reviewed Catalase observations. All 38,867 other assertions and auxiliary edges are unchanged. Strict native metadata/JSON fixes and genuine fixture updates pass the broad independent gate: 840 passed, four skipped. | Fresh finalized producer and exact merged review remain required; this is not release acceptance. |

The artifact-manifest integration fixtures now use the real Transform lifecycle
instead of directory-only namespaces. All original adversarial publication,
closure and statistics assertions are retained. An independently executed
77-test artifact-manifest/source-finalization/canonical-serialization/direct-export
gate passes. This repairs eight fixture failures in the ongoing diagnostic full
suite; that already-imported run must be repeated against the final snapshot.

The remaining NCIT source-context inventory now covers all 55 canonical files,
24 declarations and 202 incident occurrences. It exposes identity questions
separate from category typing: generic Oatmeal versus colloidal oatmeal,
Substrate's withheld MIM identity restored by a native-name alias, nested
phosphate-buffer recipe identities, and clinical plant-infection/parasite
labels interpreted as locations. Those routes are being reviewed using exact
native contexts; the category inventory is not scientific acceptance of them.

The MediaDive cases above have now completed bounded implementation and
independent regression review. The four finite BacDive Lesion/Parasite category
claims likewise have an independently reconciled native replay: all 99,392
records and 227,035 other field leaves are conserved. Full integration and
fresh-source acceptance remain separate from these scoped replay results.

The separately approved 108 existence-boundary/developmental-replacement and
34 ordering/synchrony assertions extend native retention from 184 to 326.
Each extension preserves every previously approved policy record exactly.
The latest full source replay preserves 93,436 rows and changes only 326
predicates. All 28 exact BFO projections and eight unrelated GO-to-GO assertions
remain unchanged. The test-only RDF witness issue #1344 is independently cleared:
parsed subject identity/type and linked blank-node identity/type are verified
against literal native stanzas, not trusted dictionary keys. Actual nonempty
PATO and UBERON producer runs, fresh finalization, byte-identical repeat and
recorded admission pass. Full canonical producer rebuild and merged acceptance
remain pending.
Strict-Biolink nonconformance
remains explicit for every retained native predicate. Participation
generalizations, the two broad GO subject replacements, temporal model limits,
and the remaining FOODON class restrictions retain separate scientific review
boundaries. Do not infer acceptance merely from a native witness or a category
that satisfies a validator.

### Six approved conservative dispositions

The user approved the following finite dispositions on 2026-10-01. They change
upstream source handling, not merged TSVs. Historical counts describe the saved
review cohorts; they are not counts from a newly rebuilt merged graph.

| Scope | Approved graph treatment | Evidence retained |
| --- | --- | --- |
| BacDive Agriculture: 1,148 positions on 1,147 records | Source-record category observations, not organism locations at a land-use process | Original field path, value and citations |
| FOODON: 22 pod classes and two whole-tail classes | `biolink:GrossAnatomicalStructure` for native and imported declarations | Exact native identity and sound hierarchy; separate kernel and meat controls are unchanged |
| UPA: 449 historically retained unverified computed GO projections | Audit only, not `part_of` assertions | Complete candidate witnesses and original selected rows, including multiplicity; the seven contradicted routes retain their distinct reason and direct weak xrefs remain |
| MicrobeDecoder: 195 snapshot values behind six rejected joins | Five source-record `InformationContentEntity` nodes; no node for the zero-value record | Original records/values, former subject association and dependent phenotype audits; independent FAPROTAX evidence stays on its original subject |
| BacDive: 97 reviewed ambiguous taxid sets | Withhold their taxonomic parent proposals | Every supplied taxid and former selection; independently supported deposit contributors remain |
| Three additional imported GO restrictions | Withhold the exact transferred assertions, extending the finite policy from 12 to 15 | Original row, would-be candidate row, native restriction and identifier history |

**Follow-up rule, added 2026-10-12 (#1421), after the approval above.** The
withheld candidates of these 97 BacDive records still contest the parent of any
deposit a withheld record shares with another record:

- The deposit keeps a parent only if every candidate is, or lies beneath, the
  parent its other records support.
- Otherwise it gets no parent and no record links, and it is listed in the
  deposit-claims report as `suppressed_withheld_unresolved`.

The three additional GO decisions are `GO:0006903 / RO:0002162 / NCBITaxon:2759`,
`GO:0048199 / RO:0004009 / GO:0005798`, and
`GO:0055108 / BFO:0000066 / GO:0005737`, all supplied by PATO. These are
conservative exclusions of unsupported transfers, not claims of biological
falsity. Other suppliers and sibling relations are outside the finite scope.
The spatial claim on GO:0055108 is distinct from its earlier destination
quarantine; both occurrences keep their own audit records.

These approvals resolve the corresponding pending policy choices, not the
remaining integration/native-replay/rebuild/merged-review gates. Source
fingerprints must reflect the new policies; old finalized outputs cannot be
re-stamped as fresh. The exact two tail-meat FOODON controls and six ambiguous
meat controls remain unchanged by the 24-class anatomy decision; unchanged does
not imply independent approval of their historical classification.

1. Keep the standalone tests, default Tox environments, lockfile and generated
   merge-config checks green for the final code snapshot.
2. Independently review each changed source contract and its negative controls.
3. Resolve remaining native-authority/projection decisions without changing the
   pinned model merely to suppress warnings.
4. Rebuild affected producers and admitted dependents in dependency order. Shared
   finalization changes invalidate prior source receipts; do not re-label old
   transformed files as freshly produced.
5. Create a fresh merge with no semantic edits after serialization. Reconcile
   source observations, category unions, archive/member identities and manifests.
6. Run fresh model, external KGXVal, strict KGX and path reviews on that exact
   candidate. Keep project conventions distinct from strict conformance and
   scientific acceptance.

Complete source/native inventories and independent review evidence for this
work package are under `data/resolve93-20260930.2qMze1/`. The original reference
archive, producer outputs and frozen diagnostic catalogs were not modified.
