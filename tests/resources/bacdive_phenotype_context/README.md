# Native BacDive phenotype-context fixture

These are compact row/column projections of the project's pinned native METPO
ROBOT templates, inspected on 2026-09-26. No class, synonym, category, predicate,
parent, JSON path, or ROBOT directive was invented or changed. Selected rows
retain native order, including motility before sporulation: the ambiguous bare
`yes` and `no` keys consequently expose the real last-row-wins consumer defect.

Source paths and SHA256:

- `data/raw/metpo_sheet.tsv`:
  `ec9700569bf5e83d39fe4c29f525c06d3c396adfad2ce0bf33072b8b1a1b1409`
- `data/raw/metpo-properties.tsv`:
  `8ef8929f3f8d3ed61ba41f062548a3d4d2e058932c522b7ddb3a01d1e06cef63`

The retained class columns are exactly those read by `_build_metpo_tree`,
`load_metpo_mappings`, and their category/parent traversal: ID, label, parent
classes, both native Biolink category columns, Madin synonyms, and BacDive
synonyms/JSON paths. Property columns preserve ID, label, RANGE, parent property,
and Biolink equivalent. Both files retain the projected header and ROBOT row.
Omitted definitions/editor/source annotations are not required by these loaders.
Omitted classes and properties are outside this finite regression fixture;
these files are not replacement production ontologies.

Selected class IDs:

- Shared ancestors: `METPO:1000188` (quality), `METPO:1000059` (phenotype).
- Route parents: `METPO:1000601`, `METPO:1000870`, `METPO:1000631`,
  `METPO:1000666`, `METPO:1000697`, `METPO:1000701`, `METPO:1000629`,
  `METPO:1001101`.
- Leaves: `METPO:1000602`, `METPO:1000702`, `METPO:1000703`,
  `METPO:1000871`, `METPO:1000872`, `METPO:1000632`, `METPO:1000681`,
  `METPO:1000698`, `METPO:1000620`, `METPO:1001102`.

Selected property IDs: `METPO:2000101` (has quality) and `METPO:2000102`
(has phenotype). The former has a blank native Biolink-equivalent field; the
real project predicate table supplies `biolink:has_attribute`. All selected
leaves resolve to `biolink:PhenotypicQuality`; phenotype descendants inherit
the native class annotation and biosafety uses the existing quality fallback.

| Route | Native BacDive value | Expected target | Expected predicate |
| --- | --- | --- | --- |
| oxygen_tolerance | aerobe | METPO:1000602 (aerobic) | biolink:has_phenotype |
| motility | yes | METPO:1000702 (motile) | biolink:has_phenotype |
| motility | no | METPO:1000703 (non motile) | biolink:has_phenotype |
| spore_formation | yes | METPO:1000871 (spore forming) | biolink:has_phenotype |
| spore_formation | no | METPO:1000872 (non-spore forming) | biolink:has_phenotype |
| nutrition_type | autotroph | METPO:1000632 (autotrophic) | biolink:has_phenotype |
| cell_shape | rod-shaped | METPO:1000681 (rod shaped) | biolink:has_phenotype |
| gram_stain | positive | METPO:1000698 (gram positive) | biolink:has_phenotype |
| halophily | halophilic | METPO:1000620 (halophilic) | biolink:has_phenotype |
| biosafety_level | 1 | METPO:1001102 (biosafety level 1) | biolink:has_attribute |

The oxygen source synonym is `aerobe`, while its class label is `aerobic`.
The native sporulation parent includes both its dedicated spore-formation path
and `General.keywords`; that second path is deliberately preserved, not silently
removed to simplify the tests. Every selected parent and ancestor resolves
within the fixture, so context checks can traverse the actual native hierarchy.
