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
| `mappings/metpo_proposal_classes_robot.tsv` | **ROBOT template** (two header rows) | Class declarations submittable to METPO maintainers |
| `mappings/metpo_proposal_properties_robot.tsv` | ROBOT template | Property declarations submittable to METPO maintainers |
| `kg_microbe/transform_utils/metatraits/mappings/metpo_alias_mappings.tsv` | Tier-2 override | Consumed by metatraits transform to use existing METPO IDs |

The `*_robot.tsv` files are the upstream-submittable artifacts. The plain `metpo_proposal_*.tsv` files are the curation/audit ledger.

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
- [ ] `pytest tests/test_extract_metpo_proposals.py` passes
- [ ] `*_robot.tsv` files have two header rows, consistent column counts
- [ ] Every row has a `definition_source` (no `TODO:add_citation` if submitting)
- [ ] Every row has a `subset` cohort tag
- [ ] `robot template` succeeds for both class + property TSVs
- [ ] `robot merge` produces a single OWL
- [ ] `robot reason --reasoner ELK` exits clean with no UNSAT classes
- [ ] No mass `SC METPO:1000000` (>3 rows) without curator review

## See also

- `metpo-ontology` skill — for *using* existing METPO terms in transforms (the inverse direction)
- `scripts/extract_metpo_proposals.py` — proposal generation source
- [berkeleybop/metpo](https://github.com/berkeleybop/metpo) — upstream repository
- [ROBOT template docs](http://robot.obolibrary.org/template) — full directive reference
