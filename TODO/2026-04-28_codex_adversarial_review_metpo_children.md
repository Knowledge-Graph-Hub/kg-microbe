# Codex Adversarial Review

**Date:** 2026-04-28
**Target:** branch `fix_metatraits` diff against `master`
**Verdict:** needs-attention

No-ship: several of the new METPO child classes are semantically inverted or not actually backed by the metatraits/BacDive evidence the proposal claims to use.

## Findings

### [high] Negative biochemical results are modeled as subclasses of enzyme activity
**Location:** `scripts/extract_metpo_proposals.py:758-848`

`catalase negative`, `oxidase negative`, and `urease negative` are all subclasses of `... activity`. That inverts the meaning: any ancestor/subclass query for catalase/oxidase/urease activity will also return taxa that explicitly tested negative. Existing METPO assay patterns use neutral test parents for +/- outcomes, not activity parents. The source mappings here also only expose generic activity traits (`enzyme activity: catalase/oxidase/urease` in the metatraits mapping files), so there is no source-level justification for collapsing negative assay results under positive biological capability.

**Recommendation:** Model these as assay/test terms with +/- children, or split activity capability from assay result and keep negative results out of the activity subclass tree.

### [high] `bile acid susceptible` is placed under a growth-capability parent with the opposite polarity
**Location:** `scripts/extract_metpo_proposals.py:565-583`

The proposal defines `bile acid susceptible` as growth being inhibited by bile acids, but makes it a child of `selective media growth capability`. That means a susceptibility phenotype will roll up as evidence of the ability to grow on selective media, which is the opposite of the mapped source semantics. The metatraits mapping row for this trait explicitly says `growth inhibited by bile acids`, and the same block even creates a separate `bile resistance` class without connecting susceptibility to it.

**Recommendation:** Reparent bile susceptibility under a bile-response hierarchy (`bile resistance` with positive/negative children, or a neutral bile tolerance parent) and keep `selective media growth capability` for actual growth-capable phenotypes only.

### [medium] A subset of the proposed children has no source-backed validation path at all
**Location:** `scripts/extract_metpo_proposals.py:166-175`

The extractor only validates four metatraits placeholders via `KGMICROBE_PLACEHOLDER_MIGRATION` and seven BacDive-derived morphology/flagellation counts. Children such as `growth on EMB agar`, `barophile phenotype`, and all six `catalase/oxidase/urease +/-` classes are generated outside both checks. I could not find matching source rows for those labels in the current metatraits unmapped-trait artifacts, metatraits mapping TSVs, or BacDive raw-data searches, and the regression test only checks byte-for-byte reproducibility of the committed outputs. That leaves room for speculative or dead proposal IDs to ship with no evidence trail and no failing guardrail.

**Recommendation:** Require every proposed child class to be backed by one of: a metatraits placeholder migration entry, explicit raw-data count logic, or a curated source file plus a targeted test proving the term exists in source data; otherwise remove it from this proposal batch.

## Next steps

- Fix the biochemical-test hierarchy before proposing these IDs downstream.
- Reclassify bile susceptibility so ontology rollups preserve the negative-growth semantics.
- Add evidence-based validation for every newly proposed child or trim the unsupported terms from the batch.
