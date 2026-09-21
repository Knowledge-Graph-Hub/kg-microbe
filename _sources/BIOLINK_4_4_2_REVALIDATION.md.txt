# Biolink 4.4.2 modeling revalidation

**Checked:** 2026-08-21  
**Source:** the exact `v4.4.2` `biolink-model.yaml` pinned in `download.yaml`

This is the current-model follow-up to the dated Biolink 4.2.2 GOLD review. It
checks only the assumptions called out during repository review; it does not
reinterpret the historical measurements in those documents.

## Taxon hierarchy convention

In 4.4.2, `organism taxon` is directly a `named thing`; its definition explicitly
says it can represent strains or subspecies. It is not a descendant of `ontology
class`. The `subclass of` slot still has `ontology class` as both domain and
range.

Therefore KG-Microbe's `OrganismTaxon -subclass_of-> OrganismTaxon` strain
hierarchy remains a deliberate project convention and a strict Biolink
domain/range exception. It means “this named strain or isolate sits under this
taxon,” preserves traversal of the taxonomic backbone, and is tracked in #834.
Do not describe it as strict 4.4.2 conformance or remove it without a project
modeling decision.

GOLD ecosystem class hierarchies are different: their endpoints also carry
`biolink:OntologyClass`, so their `subclass_of` edges satisfy the 4.4.2 domain
and range.

## `located_in` and `occurs_in`

Both slots remain children of `related to at instance level` and declare no
additional machine-readable domain or range in 4.4.2.

- `located in`: “holds between a material entity and a material entity or site
  within which it is located.” Use this for a material entity's location.
- `occurs in`: “holds between a process and a material entity or site within
  which the process occurs.” Use this for the site of a process.

The semantic distinction in the existing GOLD review therefore remains valid:
do not exchange these predicates merely because strict domain/range validation
does not reject either one.

## Reproduction

Inspect the pinned schema after `poetry run kg download -t schema`, or fetch the
same immutable tag from
`https://github.com/biolink/biolink-model/tree/v4.4.2`. The model-review skill
now refuses BMT's remote default and uses the two pinned files under `data/raw`.
