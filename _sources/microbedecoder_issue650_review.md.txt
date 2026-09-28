# MicrobeDecoder curation review (#650)

This change is a bounded, evidence-backed contribution to
[#650](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/650), not closure
of every remaining scientific interpretation. The historical 5,224-label figure
is not a reproduced current backlog or an acceptance target.

## Delivered scope

- Seventeen exact source-column/process rules normalize 7,152 assertions in
  the reviewed saved cohort; source citations and FAPROTAX prediction provenance
  remain intact.
- Seventeen finite group/unspecified-metabolism labels remain source Attributes,
  not asserted biological processes. Four `Not reported` substrate observations
  likewise remain reporting attributes rather than chemical consumption.
- One complete-record-pinned `tartate` observation is normalized to tartrate;
  this creates no global alias and does not alter the pinned MIM/unified export.
- Twenty-two reviewed textual phenotype groundings are report-only evidence
  covering 33,144 observations, not additional organism phenotype assertions.
- A full-source inventory separates identity crosswalks, processes, materials,
  and reported source attributes without a frequency cutoff.

See [process evidence and contracts](microbedecoder_process_curation.md),
[observation/chemical boundaries](microbedecoder_observation_curation.md), and
the [transform runbook](MICROBEDECODER_TRANSFORM_RUNBOOK.md).

## Independent adversarial findings

| Issue | Confirmed defect | Fix boundary |
| --- | --- | --- |
| [#1212](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1212) | GO audit hashed an intermediate header representation | Separate shared-infrastructure PR; canonical staging before checkpoint hashing, byte-verified legacy history only |
| [#1213](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1213) | Inventory accepted empty scientific endpoints | Reject blank/whitespace subjects and objects before classification |
| [#1214](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1214) | Fallback process routes skipped relation checks | Require the full capable_of predicate/relation pairing on all process routes |
| [#1215](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1215) | External IDs bypassed explicit material-category contradictions | Reject contradictory declared categories without inventing external declarations |
| [#1216](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1216) | METPO process objects were generic OntologyClass, incompatible with capable_of | Native asserted biological-process ancestry in the ontology producer, plus strict consumer category admission |

Reviews examined logic, consistency, robustness, bugs, bottlenecks and scaling.
The inventory negative cases are synthetic validation reproducers, not a claim
that those malformed rows occur in the saved production data. The ontology
category finding is a real modeling incompatibility: reviewed process identity
alone does not make a generic OntologyClass a valid Occurrent endpoint.

## Remaining scientific scope

The complete pre-shipping-review candidate inventory accounts for 521,217 edges,
including 84,244 crosswalks, and groups other assertions into 6,974 rows. It
retains 61 local process IDs (41,388 assertions), 10 queued material IDs
(225 assertions), and three additional registry-local materials (15 assertions).
These counts identify the reviewed snapshot; they are not runtime constants.

The 6,592 field-scoped source-attribute IDs represent measurements, units,
isolation context, classifications and assay observations. They are not all
missing chemicals. Numeric/signed assay interpretation still needs source
coding and observation context. Report-only phenotype grounding does not
resolve the pinned graph model's endpoint-category constraints.

The issue remains open for those explicit scientific tasks. Merging this code
does not refresh production sources or certify a merged release: rebuild native
ontology output before its consumers, respect source freshness, then merge and
perform graph-level acceptance. Prior isolated candidate receipts are evidence
for their exact code/input hashes, not acceptance for later code changes.
