# Semantic modeling decisions — 2026-09-14

These decisions address #642–#645 and the ChEBI-role/FOODON findings in the September 14 review. They change producer semantics and narrowly documented validation conventions; they do not declare the archived graph corrected. Rebuild affected sources and merge before a release review.

## Assays (#642)

Assay-kit wells denote **procedure classes**, not molecular reaction events. Keep `biolink:Procedure` and their `subclass_of MICRO:0000903` hierarchy. Replace misleading assay `has_output` activity edges with `MICRO:0001206` (is an assay for the enzymatic activity of), and assay `has_input` chemical edges with `MICRO:0000065` (is an assay using the chemical reagent). Use the same native CURIE in `relation`.

Primary local evidence: `data/raw/micro.owl` declares MICRO:0001206 with assay domain OBI:0000070 and molecular-function range GO:0003674; MICRO:0000065 has the same assay domain and chemical-entity range CHEBI:24431. `data/raw/biolink-model.yaml` 4.4.2 gives biological-process-or-activity domain to `has_input`/`has_output`; adding BiologicalProcess to a test procedure would misrepresent the node.

The built-in reviewer uses explicit Procedure→MolecularActivity and Procedure→ChemicalEntity/MacromolecularComplex tables. KGXVal's native-property failures remain visible as expected **project extensions**, not strict Biolink passes. Unknown MICRO predicates remain actionable.

## Curated Rhea cross-references (#645)

Both `rhea2ec.tsv` and `rhea2go.tsv` explicitly map `RHEA_ID` to `ID`. Emit `biolink:close_match`, relation `oboInOwl:hasDbXref`, primary source `infores:rhea`, knowledge assertion/manual agent. Apply this to the TSV and PyOBO activity-cross-reference paths. Do not infer physical gene-product `enables`/`enabled_by`, strict equivalence, or a gene product's identity from these curated classification mappings.

Pinned Biolink 4.4.2 lists `oboInOwl:hasDbXref` as a narrow mapping of `close_match`. Existing EC→GO `enables` conventions elsewhere are unchanged, but reviewer allowance is now limited to EC-namespace Protein-typed enzyme classes and GO MolecularActivity objects; it cannot suppress unrelated Protein or RHEA subject errors.

## ChEBI roles

Classify a term as ChemicalRole only through asserted `rdfs:subClassOf` ancestry under CHEBI:50906 (including the root). This includes indirect role descendants such as CHEBI:75767, animal metabolite. A chemical's `has_role` relationship is **not** class ancestry; label suffixes such as “inhibitor” are insufficient evidence. Keep the existing asserted macromolecule-branch convention under CHEBI:33839.

Map only `has_attribute` assertions whose retained source relation is RO:0000087 to `has_chemical_role`; preserve quality attributes such as RO:0000086 unchanged. The reviewer no longer excuses arbitrary OntologyClass role targets. A narrow counted convention covers CHEBI macromolecule-class→CHEBI ChemicalRole assertions where the repository's MacromolecularComplex category is the only mismatch.

## FOODON organism classes and source defects

The previous all-FOODON-is-Food rule was wrong for whole-organism classes. Use asserted subclass descendants of COB:0000022 (organism), PO:0000003 (whole plant), and NCBITaxon:1 as OrganismTaxon. Apply the same authoritative policy to imports and merge inputs, removing stale Food/anatomical fallbacks from these organism classes. Food materials remain Food; `in_taxon` range alone never determines a node's category.

In the pinned raw FOODON graph, this covers 2,221 of 2,227 distinct `in_taxon` target IDs. The six reviewed exceptions are maintained in `mappings/foodon_model_dispositions.tsv`, not inferred from an open-world absence of ancestry:

- FOODON:03411744, kelp, has raw synonym “laminariales”; pinned NCBITaxon:2886 is labeled Laminariales. Categorize this organism class without asserting a same-as or adding an NCBI mapping edge.
- FOODON:00003662 is explicitly a Chinese-cabbage **rosette**, FOODON:00003673 a watermelon **pepo fruit**, and FOODON:03309697 a **raw fillet** (whose in_taxon is self-referential).
- FOODON:03411632 and FOODON:03411645 explicitly denote **fungal fruitbodies**, despite the former's misleading “genus” label. Their own raw in_taxon assertions point to NCBITaxon:5320 and NCBITaxon:28992 respectively; those valid assertions are retained.

Only FOODON `biolink:in_taxon` / RO:0002162 assertions targeting those five affirmatively incompatible part/material classes are quarantined. Preserve all original KGX row columns, original provenance and evidence in atomic LF `foodon_model_quarantine.tsv`; raw ontology files are untouched. Uncertain/unclassified targets and other relations to these same nodes are retained. No replacement taxon is invented.

## Explicit class-level conventions (#643/#644)

Biolink semantic categories describe what ontology classes are *about*; they are not a claim that the graph contains instances instead of classes. Preserve meaningful ontology `subclass_of` axioms, including chemical, anatomical, food, quality and procedure classes, without adding OntologyClass indiscriminately or weakening predicates to related_to.

The counted INFO allowance requires `rdfs:subClassOf`, different endpoints, known ontology namespaces, and substantive class categories at both ends. Explicitly scoped assay-procedure and recipe-solution class hierarchies are also allowed. It excludes arbitrary instance namespaces, NamedThing fallbacks, wrong originating relations, and self-loops. The separate #834 OrganismTaxon strain/subclass convention is preserved.

Taxon phenotype assertions may target METPO/PATO/OMP phenotype classes, including their PhenotypicQuality/OntologyClass representation. Arbitrary Attribute/chemical targets are not accepted merely because `has_phenotype` is involved. All house-only passes remain separately counted from strict model conformance; native MICRO properties remain separately typed project extensions.

## Reviewed query-graph self-loops (2026-09-17)

Quarantine the two exact assertions reviewed in the September 17 merged graph: `PR:000000001 biolink:has_part PR:000000001` with relation `BFO:0000051`, and `FOODON:02021808 biolink:subclass_of FOODON:02021808` with relation `rdfs:subClassOf`. The policy lives in `mappings/ontology_self_loop_exclusions.tsv` and is applied after identifier compaction to every ontology output, including imported copies.

These are query-graph exclusions, not a blanket declaration that reflexive OWL assertions or class-level partonomy are invalid. Other self-references, different source relations, and all node declarations remain unchanged. Atomic LF `<ontology>_self_loop_exclusions.tsv` reports retain the original pre-projection row as JSON, provenance, and the exclusion reason. A clean run replaces a stale report with a header-only file; malformed curation aborts instead of silently changing the exclusion scope.

The policy is a declared ontology transform input and participates in its freshness fingerprint. Regression coverage is in `tests/test_ontology_self_loops.py`. Raw ontologies and existing transformed/merged artifacts are not rewritten by this code change; rebuild before reporting the released graph corrected.

## Verification and freshness

Regression coverage is in `tests/test_semantic_model_decisions.py`, `tests/test_ontology_resolution.py`, `tests/test_assay_generation.py`, and `tests/test_kg_model_review_domain_range.py`. Negative controls cover non-class endpoints, relation mismatches, self-loops, unexpected assay ranges, chemical role-label false positives, uncertain FOODON targets, unrelated attributes/proteins, and unknown MICRO predicates.

The FOODON disposition file is declared by the ontology transform and content-hashed as shared curation input for all transform freshness checks. In-process ontology/disposition lookup caches use path/size/mtime invalidation only, not cryptographic release fingerprints. Existing transformed and archived graph data have not been rewritten by this change.
