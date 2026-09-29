# Source-qualified Sigma P3556 material scope (#1241)

## Evidence and scientific limit

The saved MediaDive observation `mediadive.solution:629#recipe/1` names
`L-α-Phosphatidylcholine`, compound 2082, and explicitly supplies
`attribute: SIGMA P3556`. Its amount is 5 mg and its source `g_l` value is 5.
Those original values are retained, not recalculated or silently corrected.
The source does **not** assert a CAS identifier.

The [supplier product sheet](https://www.sigmaaldrich.com/deepweb/assets/sigmaaldrich/product/documents/152/475/p3556pis.pdf)
describes an egg-yolk material with several fatty-acid constituents, not one
pure acyl species. The supplier's [drug-delivery brochure](https://b2b.sigmaaldrich.com/deepweb/assets/sigmaaldrich/marketing/global/documents/709/352/polymeric-drug-delivery-techniques-web.pdf)
also depicts variable fatty-acid residues for P3556 (PDF page index 18,
printed page 17). The [product page](https://www.sigmaaldrich.com/US/en/product/sigma/p3556)
additionally supplies a fixed structure. That catalog structure is not proof
of whole-product molecular purity; its stereolayer differs from the native
ChEBI witness. These primary documents were read online. Local PDF downloads
failed, so no local PDF checksum is claimed.

Native `CHEBI:86658` has a generic preferred label but explicit synonyms,
SMILES and InChI identifying a particular 16:0/(9E,12E)-18:2 structure.
The immutable fixture `tests/resources/mediadive/p3556_scope.json` preserves
that structured witness, all eight selected full original mapping rows,
the exact raw occurrence, and hashes of the original raw/mapping inputs.
The error is assigning the **whole product quantity** to that molecule.
This is not a claim that the molecule cannot occur in the material.

## Transform and mapping behavior

- Two finite existing-policy exclusions reject generic `L-alpha`/`L-α`
  phosphatidylcholine names and the exact `MIM:L-alpha-Phosphatidylcholine`
  pair for `CHEBI:86658`. The policy authority label is an actual native
  structured synonym, not the misleadingly generic preferred label.
- The explicit source qualifier `SIGMA P3556` (case and whitespace only)
  keeps a recipe occurrence on its existing MediaDive ingredient/solution
  ID before unified, legacy or embedded identity selection. The current
  observation therefore remains `mediadive.ingredient:2082` with its raw
  source record, assertion ID, quantities and observation/manual provenance.
  Neither ingredient number, recipe number, a generic name nor a fuzzy
  catalog-code match triggers this product decision.
- A supplied occurrence, including `{}`, never inherits another recipe's
  embedded product qualifier. Direct calls without an occurrence can use an
  explicit qualifier in the embedded source compound record.
- Local category remains the existing broad `biolink:ChemicalEntity` for
  the current source name. This change does not assert new native mixture
  typing, a replacement ChEBI charge/class, CAS or other molecular identity.
- Explicitly structured native molecular routes and unrelated generic
  phosphatidylcholine classification claims remain eligible. There is no
  global ban on `CHEBI:86658`, `CHEBI:16110`, `CHEBI:49183` or CAS 8002-43-5.
  Eligibility alone is not new identity approval.

## Reversible candidate evidence

The existing required producer sidecar
`mediadive_material_scope_quarantine.tsv` retains available candidate rows
separately from graph identity. Its schema, producer-time byte snapshot,
source-finalization copying and public-admission checks are unchanged.
Potato/extract and P3556 candidates are separate finite profiles.

For a P3556 observation, the audit preserves applicable current unified and
legacy rows (matching the actual occurrence spelling), the original exact
generic MIM claim, and actual embedded identifiers when present. Duplicate
input rows have separate locators. Full original row columns, raw record,
source/candidate path and hash, retained local target, qualifier, authority
URI and reason are retained. A contradictory structure-specific display
name cannot override the product qualifier; its applicable mapping claims
are still auditable. These rows are **available candidates**, not assertions
that every lookup was attempted, and are never fabricated raw CAS claims.

Review #1243 corrected canonical object-label coverage: eligible identity,
attribute, canonical-name and synonym rows can supply the reader's object
label; synonym rows additionally supply the subject label. A row matching
both fields is retained once per original locator, while duplicate physical
rows remain distinct. Broader, hydrate and annotation rows do not become
grounding candidates. The old fixture's four structured-synonym rows also
carry the generic object label, so they remain auditable until a reviewed
derived export relabels that metadata. Audit row counts are not historical
constants.

Conditional consumed-input role `material_scope_supported` binds the
canonical unchanged `mappings/ingredient_mappings.sssom.tsv` only when the
selected source contains P3556. It is audit evidence, not an active grounding
source. It preserves the complete original imported assertion after a future
derived unified export removes the held pair. The supported MIM table and
release pin remain immutable. Empty source cohorts or removed candidates
are valid; a genuinely empty audit retains its header.

## Verification and deployment boundary

Hermetic tests cover native reader/direct-pair denial, explicit structure
controls, legacy and bounded/conservative regeneration, all occurrence
fallbacks, raw quantities, duplicate full-row audit evidence, profile
isolation, input-origin/drift protection, and real source finalization/reuse/
public admission. The tiny identity-only refresh removes three generic rows
and replaces the misleading object label on four retained structural rows;
its second cycle is byte-identical. Conservative regeneration preserves full
quarantined originals and multiplicity.

This source change alone is not a rebuilt graph or release acceptance.
A separate reviewed derived-mapping candidate, source replay, transform
freshness checks and merged-graph reviews remain required. No immutable
supported MIM release, production raw data or production archive is modified
by this implementation stage.
