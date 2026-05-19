---
name: metpo-proposal
description: Workflow for proposing new METPO terms from KG-Microbe transform output. Use when adding new METPO classes or properties, drafting an upstream submission to berkeleybop/metpo, or validating a proposal before sharing with curators.
---

# METPO Proposal Workflow

## Purpose

Produce a clean, ROBOT-validated, ELK-coherent METPO term proposal that can be filed against [berkeleybop/metpo](https://github.com/berkeleybop/metpo). A proposal must:

1. Not collide with any existing METPO term (label or exact synonym).
2. Use Aristotelian definitions (`<genus>: <differentia>`).
3. Cite the definition source (`IAO:0000119` axiom annotation).
4. Reuse appropriate parent classes from existing METPO (avoid jumping straight to `METPO:1000000` when a sibling parent exists).
5. Pass `robot template` ingestion and `robot reason --reasoner ELK` without unsatisfiable classes.
6. Be tagged with a stable subset identifier (`oboInOwl:inSubset`) so curators can filter by proposal cohort.

## Authoritative artifacts

| File | Format | Role |
|---|---|---|
| `mappings/metpo_proposal_categorical.tsv` | curation TSV (one header) | Human-edited proposal of categorical classes; emitted by `scripts/extract_metpo_proposals.py` |
| `mappings/metpo_proposal_quantitative.tsv` | curation TSV | Datatype properties + numeric tolerance class forms |
| `mappings/metpo_existing_aliases.tsv` | curation TSV | Proposed concepts that already exist in METPO (use these IDs instead) |
| `mappings/metpo_label_corrections.tsv` | curation TSV | Upstream label-fix requests for *existing* METPO terms whose `rdfs:label` disagrees with their numeric-threshold or other intrinsic synonyms. Each row cites a `berkeleybop/metpo` issue. Distinct from `metpo_existing_aliases.tsv`: aliases route a kg-microbe-side label to an existing METPO ID *as-is*; corrections request that the upstream record itself be amended. |
| `mappings/metpo_proposal_classes_robot.tsv` | **ROBOT template** (two header rows) | Class declarations submittable to METPO maintainers |
| `mappings/metpo_proposal_properties_robot.tsv` | ROBOT template | Property declarations submittable to METPO maintainers |
| `kg_microbe/transform_utils/metatraits/mappings/metpo_alias_mappings.tsv` | Tier-2 override | Consumed by metatraits transform to use existing METPO IDs |
| `mappings/kgmicrobe_proposal_placeholders.tsv` | curation TSV | Registry of `kgmicrobe.*:*` placeholder CURIEs that transforms emit while a METPO term is still under proposal — see "Placeholder policy" below |

The `*_robot.tsv` files are the upstream-submittable artifacts. The plain `metpo_proposal_*.tsv` files are the curation/audit ledger.

## Placeholder policy (transforms must not emit unminted METPO IDs)

Until a proposed METPO term is officially minted in the upstream
`berkeleybop/metpo` release, KG-Microbe transforms MUST NOT emit the proposed
METPO ID into `nodes.tsv` / `edges.tsv`. Instead the transform mapping points at
a `kgmicrobe.<sub>:<local_id>` placeholder CURIE.

- Per-CURIE label / category / description live in
  `kg_microbe/transform_utils/custom_curies.yaml` under one of the
  `kgmicrobe.activity` / `kgmicrobe.trait` / `kgmicrobe.compound` /
  `kgmicrobe.pathway` blocks.
- The placeholder ↔ proposed-METPO swap table lives in
  `mappings/kgmicrobe_proposal_placeholders.tsv`. Every kgmicrobe.* CURIE that
  *does* correspond to a row in `mappings/metpo_proposal_*.tsv` MUST be listed
  there with `status`, `used_by`, and target `proposed_metpo_id`.

When a proposal lands upstream and the METPO ID is minted, swap the
transform-side `object_id` from the kgmicrobe.* placeholder back to the METPO
ID and update `status=accepted` in the placeholder registry.

## Workflow

### 1. Generate / update curation TSVs

```bash
poetry run python scripts/extract_metpo_proposals.py
```

This:
- Validates against `data/transformed/ontologies/metpo_nodes.tsv` (no label/synonym collisions).
- Validates BacDive observation counts against `data/raw/bacdive_strains.json` if present (data-driven check, see `compute_bacdive_observations`).
- Emits the four curation TSVs above.

Run `poetry run pytest tests/test_extract_metpo_proposals.py` to confirm regenerate-and-diff cleanliness (artifact-as-source-of-truth gate).

### 2. Mirror into ROBOT-template format

After editing the curation TSVs, regenerate the ROBOT-shaped tables. Two header rows are required: row 1 is the human-readable column name; row 2 is the ROBOT directive.

#### Required ROBOT directives

**Classes** (`metpo_proposal_classes_robot.tsv`):

| Column | Directive | Effect |
|---|---|---|
| `proposed_id` | `ID` | subject IRI |
| `label` | `LABEL` | `rdfs:label` |
| `definition` | `A IAO:0000115` | textual definition annotation |
| `definition_source` | `>A IAO:0000119` | **axiom annotation** on the definition (proper OBO citation pattern) |
| `parent` | `SC %` | `rdfs:subClassOf` |
| `synonyms` | `A oboInOwl:hasExactSynonym SPLIT=\|` | exact synonyms (pipe-split) |
| `xrefs` | `A oboInOwl:hasDbXref SPLIT=\|` | dbxrefs (pipe-split) |
| `subset` | `A oboInOwl:inSubset` | proposal cohort tag (e.g. `metpo_proposal_2026_04`) |
| `priority`, `observations`, `traits_addressed` | (empty) | curation metadata, ignored by ROBOT |

**Properties** (`metpo_proposal_properties_robot.tsv`):

| Column | Directive | Effect |
|---|---|---|
| `proposed_id` | `ID` | subject IRI |
| `label` | `LABEL` | `rdfs:label` |
| `definition` | `A IAO:0000115` | definition |
| `definition_source` | `>A IAO:0000119` | citation |
| `type` | `TYPE` | `owl:DatatypeProperty` or `owl:ObjectProperty` |
| `domain` | `DOMAIN` | `rdfs:domain` |
| `range` | `RANGE` | `rdfs:range` |
| `xrefs` | `A oboInOwl:hasDbXref SPLIT=\|` | dbxrefs |
| `subset` | `A oboInOwl:inSubset` | cohort tag |

All rows must be padded to the same column count (trailing tabs for empty cells), or ROBOT will reject the template.

### 3. Validate with ROBOT (REQUIRED before sharing)

```bash
# 3a. Compile each template into OWL — fails on syntax errors
robot template \
  --template mappings/metpo_proposal_classes_robot.tsv \
  --prefix "METPO: http://purl.obolibrary.org/obo/METPO_" \
  --prefix "biolink: https://w3id.org/biolink/vocab/" \
  --output /tmp/metpo_classes.owl

robot template \
  --template mappings/metpo_proposal_properties_robot.tsv \
  --prefix "METPO: http://purl.obolibrary.org/obo/METPO_" \
  --prefix "biolink: https://w3id.org/biolink/vocab/" \
  --output /tmp/metpo_props.owl

# 3b. Merge classes + properties into a single proposal artifact
robot merge \
  --input /tmp/metpo_classes.owl \
  --input /tmp/metpo_props.owl \
  --output /tmp/metpo_proposal_merged.owl

# 3c. ELK reason — fails on inconsistencies / unsatisfiable classes
robot reason \
  --reasoner ELK \
  --input /tmp/metpo_proposal_merged.owl \
  --axiom-generators "SubClass EquivalentClass" \
  --output /tmp/metpo_proposal_reasoned.owl
```

**Pass criteria:**
- All three commands exit zero with no `UNSAT` / `inconsistent` warnings on stderr.
- The reasoned output line count is close to the merged input line count (a small delta is just inferred subclass redundancy; a large delta or new equivalent-class assertions indicates unintended collapses).

**Common failures and fixes:**

| Symptom | Cause | Fix |
|---|---|---|
| `Number of columns ... does not match` | directive row shorter than data rows | pad header row 2 with trailing tabs |
| `Could not parse: <directive>` | typo in directive (e.g. `A IAO 0000115`) | use space between directive code and CURIE: `A IAO:0000115` |
| `UNSAT class: <CURIE>` | conflicting parent/disjoint axioms | review parent chain; check if a sibling class is disjoint via PATO/OBI |
| `Inconsistent ontology` | conflicting domain/range vs. parent property | tighten domain/range or relax parent |
| New `EquivalentClasses` axiom in reasoned output | two children mapped to same parent + same definition pattern collapse | review definition uniqueness |

### 4. Submit upstream

The submittable artifacts are:
- `mappings/metpo_proposal_classes_robot.tsv`
- `mappings/metpo_proposal_properties_robot.tsv`
- `/tmp/metpo_proposal_reasoned.owl` (for reviewers who prefer OWL)

File a PR or issue at [berkeleybop/metpo](https://github.com/berkeleybop/metpo) with the TSVs attached. Reference the subset tag (e.g. `metpo_proposal_2026_04`) so reviewers can filter.

## Definition style

Aristotelian convention (genus + differentia):

```
<term>: <existing parent class> with <distinguishing feature>.
```

Examples in current proposal:
- `circular colony` = "Colony shape with a regular round outline."
- `fried-egg-shaped colony` = "Colony shape with a raised opaque centre and translucent peripheral zone, resembling a fried egg."
- `catalase positive` = "Catalase activity phenotype in which the catalase test yields a positive result, characterised by visible bubbling on H2O2."

Avoid:
- Bare phrases without a genus anchor (e.g. *"Multiple flagella per cell"* — what kind of thing? add `Flagellar arrangement in which ...`).
- Definitions that only repeat the label (e.g. *"polytrichous: polytrichous arrangement"*).
- References to other proposed siblings by ID (use labels — IDs may shift before publication).

## Definition source citations

Every term needs `IAO:0000119`. Acceptable forms:

| Source | CURIE pattern | Example |
|---|---|---|
| BacDive strain entry | `BacDive:strain/<id>` | `BacDive:strain/13245` |
| Bergey's Manual | `ISBN:<isbn>` | `ISBN:9780470654958` |
| Reused PATO/GO definition | the source CURIE itself | `PATO:0000052` |
| Peer-reviewed paper | `PMID:<id>` or `DOI:<doi>` | `PMID:31123456` |
| Working draft (placeholder) | `TODO:add_citation` | only acceptable in pre-submission drafts |

A proposal with only `TODO:add_citation` placeholders should NOT be submitted upstream.

## Parent class selection

Prefer the most specific existing METPO parent. Audit chain:
1. Search `data/transformed/ontologies/metpo_nodes.tsv` for sibling concepts.
2. If a sibling class exists (e.g. `METPO:1000332` = pH tolerance), use it as parent.
3. Only fall back to `METPO:1000000` for genuinely top-level new categories.

Mass `SC METPO:1000000` is a code smell — flag it during review.

## Numeric-ID range conventions

When you mint a new ID, place it in the range that already groups its kind. METPO splits into two families by leading digit:

| Range | What lives there | Example |
|---|---|---|
| `METPO:1000xxx` | Classes (organism, environment, phenotype, enzyme, growth medium, …) | `METPO:1000525` microbe, `METPO:1000526` chemical entity, `METPO:1000527` enzyme, `METPO:1004005` growth medium |
| `METPO:1004xxx` | Growth-medium classes | `METPO:1004005` growth medium and its children |
| `METPO:1005xxx` | Test-result / assay classes | `METPO:1005010` indole test, `METPO:1005011` indole test positive |
| `METPO:1007xxx` | KG-Microbe proposal classes (pre-mint cohort) | All proposed classes in this PR cohort |
| `METPO:2000001-2000020` | Object properties — chemical interaction, **positive** | `METPO:2000002` assimilates, `METPO:2000006` uses as carbon source |
| `METPO:2000021-2000056` | Object properties — chemical interaction, **negative** (paired with the matching positive ~25 IDs lower; gaps in 2000040-2000056 also hold *positive* extensions) | `METPO:2000027` does not assimilate, `METPO:2000031` does not use as carbon source |
| `METPO:2000057, 2000064-2000070` | Object-property gaps in the chemical-interaction range — use these for new pairs | `METPO:2000064` tolerates / `METPO:2000065` does not tolerate |
| `METPO:2000101-2000103` | High-level capability/phenotype predicates | `METPO:2000102` has phenotype, `METPO:2000103` capable of |
| `METPO:2000202, 2000222` | Production predicates | `METPO:2000202` produces / `METPO:2000222` does not produce |
| `METPO:2000302/2000303` | Enzyme-activity predicates | shows activity of / does not show activity of |
| `METPO:2000517/2000518` | Growth-medium predicates | grows in / does not grow in |
| `METPO:2000601-2000606` | Process predicates | denitrifies, ammonifies, oxidizes in darkness, … |
| `METPO:2000701-2000709, 2000711-2000716, 2000721+` | Datatype properties — observational values | `METPO:2000702` has minimum temperature value, `METPO:2000715` has GC percentage value |
| `METPO:2000717-2000720` | Datatype-property gaps in the value-property family — use these for new value/optimum properties | `METPO:2000717` has growth temperature optimum value |

**Rules of thumb:**

1. **Match the family.** A new chemical-interaction object property goes in the 2000001-2000056 range, not in 2000700+. A new optimum-value datatype property goes in 2000700+, not in 2000001+.
2. **Find the gap, don't fork.** Before minting, dump all ObjectProperty/DatatypeProperty IDs in the target family (`grep -nE "metpo/2000[0-9]{3}\"" data/raw/metpo.owl | grep -E "DatatypeProperty|ObjectProperty"`) and pick the next free slot in the conceptual range. The current gaps as of `metpo_proposal_2026_04`:
   - **Object-property gaps in the chemical-interaction range:** `2000057`, `2000064-2000070`. Adjacent positive/negative pairs are preferred over the legacy "+25 offset" pattern when the offset would push you outside the conceptual range.
   - **Datatype-property gaps in the value-property range:** `2000710`, `2000717-2000720`.
   - **Class gaps for proposal cohorts:** `1007xxx` is reserved for KG-Microbe proposals; pick the next unused `1007NNN` slot in the relevant subrange.
3. **Document the gap when you mint.** In the term's definition or the surrounding comment in `extract_metpo_proposals.py`, note WHY this ID was picked (`"placed in the 2000064-2000070 gap of the chemical-interaction object-property family because …"`). Keeps future curators from re-shuffling.

## Paired predicates: positive ↔ negative via shared synonym

The metatraits transform's `_build_metpo_lookups` (kg_microbe/transform_utils/metatraits/metatraits.py:919, helper `_get_negative_predicate` at metatraits.py:2103) auto-pairs METPO predicates so a downstream call like

```python
self._get_negative_predicate("METPO:2000064")  # tolerates
# → "METPO:2000065"  # does not tolerate
```

resolves the partner without any hardcoded table. The pairing rule:

1. The **negative** member's `rdfs:label` MUST start with `does not ` (lowercased). The loader uses this prefix to flag the entry as the negative half.
2. Both members MUST share at least one `oboInOwl:hasRelatedSynonym` (or label) so they end up under the same `metpo_pattern_to_predicate` key.

Worked example — METPO:2000002 / 2000027:

| | METPO:2000002 (positive) | METPO:2000027 (negative) |
|---|---|---|
| label | `assimilates` | `does not assimilate` |
| synonym | `assimilation` | `assimilation` |
| Builds key `assimilation` | `positive=METPO:2000002` | `negative=METPO:2000027` |

Result: `metpo_pattern_to_predicate["assimilation"] = {positive: METPO:2000002, negative: METPO:2000027}`. `_get_negative_predicate(METPO:2000002)` iterates the dict, finds the entry where `positive==METPO:2000002`, and returns its `negative`.

**Counter-example (broken pairing)** — METPO:2000517/2000518 in the current upstream release:

| | METPO:2000517 | METPO:2000518 |
|---|---|---|
| label | `grows in` | `does not grow in` |
| synonyms | (none) | (none) |
| Built keys | `positive["grows in"]=2000517` | `negative["does not grow in"]=2000518` |

No shared key → not paired → `_get_negative_predicate("METPO:2000517")` returns `None` → false-majority `grows in` observations are silently dropped. Fix: add a shared related synonym to both upstream (e.g. `growth medium relation` or `growth in medium`).

**When proposing a new paired predicate, always:**
- Use `does not <stem>` as the negative label.
- Give both members a shared `oboInOwl:hasRelatedSynonym` (a noun-form of the relation works well: `tolerance`, `assimilation`, `production`).
- Optionally give the negative additional synonyms for human readability (`is susceptible to`, `is sensitive to`) — these become extra entries in `metpo_pattern_to_predicate` keyed on those synonyms but, because they're only on the negative member, they don't interfere with the pairing.

## Predicate vs class: when to model with which

The proposal occasionally has a choice: encode an organism-chemical relationship as a **predicate-driven edge** (`organism --P--> chemical`) or as a **class-subdivision phenotype** (`organism --has phenotype--> "X-susceptible" class`). Default to the predicate, not the class.

| Modeling choice | Use when |
|---|---|
| **Predicate-driven** (mint or reuse a paired predicate; emit `org --P--> chem/medium/enzyme/process`) | The relationship is parametric over a chemical/medium/enzyme axis. New axis values shouldn't require new ontology mints. Examples: `tolerates(org, chem)`, `grows in(org, medium)`, `shows activity of(org, enzyme)`. |
| **Class-subdivision** (mint a phenotype class per outcome and use `biolink:has_phenotype` / `METPO:2000102`) | The "outcome" is qualitative and not a function of a chemical/medium/enzyme. Examples: cell shape (rod-shaped, coccus-shaped), colony morphology (circular, irregular, fried-egg-shaped), Gram stain (positive/negative). |

**Smell**: a class hierarchy whose name encodes a chemical or medium (`bile acid susceptible`, `growth on MacConkey agar`, `catalase positive`) is a candidate for collapse into a predicate-driven pattern. The METPO proposal in `metpo_proposal_2026_04` removed three such hierarchies (`growth on {MacConkey,blood,EMB} agar` and `bile acid response/susceptible`) in favour of the predicate-driven equivalents (`METPO:2000517 grows in` and `METPO:2000064/2000065 tolerates / does not tolerate`).

Test-outcome classes are a special case — they encode a **bench observation** (catalase test positive) that is downstream of the underlying enzyme activity. Keep the test-outcome class AND assert the underlying predicate edge in parallel; the class records "the assay was performed and yielded outcome X", the predicate records "the organism has activity Y".

## Subset tagging

All proposal rows must be tagged with a cohort identifier so curators can filter:

```
subset	A oboInOwl:inSubset
metpo_proposal_2026_04
```

Use a date-stamped string (`metpo_proposal_<YYYY>_<MM>`). On the next proposal cohort, mint a new value (don't reuse).

## Skill checklist

When this skill is invoked, run through:

- [ ] `scripts/extract_metpo_proposals.py` exits clean
- [ ] `pytest tests/test_extract_metpo_proposals.py tests/test_metatraits.py` passes
- [ ] `*_robot.tsv` files have two header rows, consistent column counts
- [ ] Every row has a `definition_source` (no `TODO:add_citation` if submitting)
- [ ] Every row has a `subset` cohort tag
- [ ] `robot template` succeeds for both class + property TSVs
- [ ] `robot merge` produces a single OWL
- [ ] `robot reason --reasoner ELK` exits clean with no UNSAT classes
- [ ] No mass `SC METPO:1000000` (>3 rows) without curator review
- [ ] Every minted ID lands in the conventional family range (see "Numeric-ID range conventions") and the choice of slot is documented in the surrounding source comment
- [ ] Every newly proposed paired predicate has the negative member labelled `does not <stem>` AND a shared `oboInOwl:hasRelatedSynonym` with its positive partner — verify by simulating `_build_metpo_lookups` against the proposal OWL
- [ ] Every class hierarchy whose name encodes a chemical / medium / enzyme has been audited against the "predicate vs class" rule; if a paired predicate already exists (or could be cheaply minted), prefer the predicate-driven edge
- [ ] Every entry in `METPO_LABEL_CORRECTIONS` cites a `berkeleybop/metpo` issue and the `validate_label_corrections()` freshness check passes (entries become stale once upstream fixes them — re-check before re-shipping)

## See also

- `metpo-ontology` skill — for *using* existing METPO terms in transforms (the inverse direction)
- `scripts/extract_metpo_proposals.py` — proposal generation source
- [berkeleybop/metpo](https://github.com/berkeleybop/metpo) — upstream repository
- [ROBOT template docs](http://robot.obolibrary.org/template) — full directive reference
