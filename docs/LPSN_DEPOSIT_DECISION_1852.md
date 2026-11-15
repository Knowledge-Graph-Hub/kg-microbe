# LPSN deposit placement decision — 2026-11-14 PST

The owner approved the narrow correction in [#1852](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1852), implemented in [PR #1849](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1849). Existing `kgmicrobe.strain:*` deposit identities remain `biolink:OrganismTaxon`. Only their LPSN deposit-to-taxon edges change from `biolink:in_taxon` / `RO:0002162` to `biolink:subclass_of` / `rdfs:subClassOf`.

This follows the named-strain taxonomy convention in [#834](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/834), preserving shared BacDive identities, native type-deposit evidence, direction and provenance. INSDC sequence membership remains `in_taxon`; publication references remain `mentions` / `IAO:0000142`. BacDive's safe identity links and conflicting-deposit suppression are unchanged. Individual culture-material or aliquot modeling would require a separate identity migration and is outside this correction.

This decision does **not** establish strict Biolink 4.4.2 domain/range conformance: `subclass_of` still declares `OntologyClass` endpoints, while these nodes retain `OrganismTaxon`. The repository's documented exception remains visible; no global category change or validator relaxation is introduced. The original #1852 finding remains valid historical evidence.

## Reproduction and evidence

Run the existing bounded native helper in plan mode first, then repeat with `--execute`:

```bash
poetry run python -B -m scripts.adhoc.audit_lpsn_domain_edges_20261110 \
  --gss data/raw/lpsn_gss.csv \
  --cache data/edge-quality-20261110/lpsn-native-canary-r2/raw/lpsn/api_cache \
  --output data/edge-quality-20261110/lpsn-1852-native-r2
```

The M5 run used its existing isolated Poetry environment, disabled dotenv loading and bytecode writes, unset LPSN credentials, and selected the local pinned Biolink schema/predicate map. It succeeded with five native GSS rows and eleven preserved cached API records, producing GSS **8 nodes / 8 edges** and API **24 node rows / 24 edges**, with zero network requests. Receipt SHA256: `f77360c9774408103e243d692020b17cf5de2f8fc0ffb8a4ed456353c0390095`.

The helper calls both real production `run()` methods and exercises native input guards. It deliberately disables NCBI/GTDB enrichment and does not run source finalization. This establishes bounded source behavior, not a full rebuild, source admission, merged-graph validation or release readiness.

Compare the preserved original and new canaries with:

```bash
poetry run python scripts/adhoc/compare_lpsn_1852_canaries.py \
  --before data/edge-quality-20261110/lpsn-native-canary-r2 \
  --after data/edge-quality-20261110/lpsn-1852-native-r2 \
  --output data/edge-quality-20261110/lpsn-1852-delta-r2.json
```

The expected change is exactly four deposit predicate/relation pairs: JCM-33998 and KCTC-25006 to `lpsn:18880`, plus LMG-31064 to the historical/current-name controls `lpsn:10674` and `lpsn:5244`. Every other GSS edge cell, node, selected source record and API edge must remain unchanged. The selected GSS sibling edge digest is regenerated rather than restamped. Current GSS edge SHA256 is `abb6dbeac939f62e6d272161c200e7d783b1a5b7154adab032d6af5b51e57e52`; unchanged API edges are `09ab628ea2d07a5ebdda23183a7a38a6c69f4aeff7da063a2fd4dfd784b8e7c3`.

Independent adversarial review found and resolved an evidence-helper gap ([#1861](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1861)): comparing mutually identical artifacts without checking their original receipt hashes could accept identical later alterations. The repaired comparison validates each run's recorded input/output bindings before checking the scientific delta and rechecks for drift afterward. All **39 comparison regression tests passed** (4 warnings, 2.51 seconds), including identical altered copies, missing bindings, unexpected records and changes beyond the four approved pairs. Independent read-only re-review found no further material issue. Historical receipts are preserved; the helper does not claim externally authenticated receipts.

The real before/after comparison passed with exactly four changed deposit edges. Delta receipt SHA256: `4f0b0043d17b8343cd3b4257cdb03edb76682addc71700aeede9f6707fc03f55`. Its input/output verification binds both native receipts and selections; API input reports retain their legitimate run-location and sibling-digest differences. The formatting/spelling preparation passed without changing source files.

The new cross-source regression runs both real offline LPSN and BacDive producers. It checks shared node identity/category, identity-plus-hierarchy traversal and preservation of suppressed conflicting BacDive claims after graph union. It does not add cross-source parent reconciliation or claim that synthetic test taxa identify a real deposit. The affected nine-module selection passed **329 tests** (125 warnings, 66.43 seconds), recorded in `data/edge-quality-20261110/lpsn-1852-focused-r1.log`; it includes LPSN parent/API identity, sibling-binding and BacDive cross-reference/taxonomy controls.

Prepare formatting/spelling, review and commit the candidate, then run the required repository gate once:

```bash
poetry run tox -e format,codespell-write
poetry run python scripts/run_pr_gates.py lpsn-1852-20261115-r2
```

Gate r1 on `33fa2b8e1abba2b3769f9beba3627818de9ba8a6` stopped before the full suite on two helper-only lint errors (a 123-character string and module docstring layout). The corrections preserve runtime behavior and passed independent read-only review. Native canary/comparison r1 evidence remains preserved; r2 regenerated it using the corrected helper hashes. Formatting, spelling and all-source lint then passed.

The replacement gate ledger belongs at `data/validation/pr-gates/kgm-lpsn-1852-20261115-r2-gates.json`; its outcome and exact commit will be recorded on the PR without editing the validated candidate. Earlier gate/CI receipts remain evidence for their original commits. Fresh CI is required for the pushed correction. Merge is not authorized by this decision.
