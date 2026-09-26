# BacDive explicit spore keyword projections (#1178)

These are immutable projections of four records from the local downloaded
`data/raw/bacdive_strains.json`, inspected on 2026-09-26, SHA-256
`57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2`.
The source record URLs are `https://bacdive.dsmz.de/strain/94`,
`https://bacdive.dsmz.de/strain/654`,
`https://bacdive.dsmz.de/strain/164622`, and
`https://bacdive.dsmz.de/strain/166227`.

The projections retain each original `General.BacDive-ID` and the complete,
ordered `General.keywords` array. Cell-morphology records retain their original
list/dictionary structure, `@ref`, and `motility` where present. The complete
structured spore-formation block is retained for 164622; it is absent in the
other three records. Reference lists are deliberately reduced to selected
original `@id` / `doi/url` pairs; unneeded metadata and unrelated phenotype
fields are omitted, not replaced. The General keywords have no individual
reference pointer. Their assertions use the BacDive record URL, not every
record-level DOI.

- 94: motility `no`, no explicit spore keyword or structured spore field;
  this must not imply a sporulation assertion.
- 654: explicit `spore-forming` keyword and motility `yes`, but no structured
  spore field. The keyword independently supports the positive spore trait.
- 164622: explicit positive keyword and structured spore `no` (`@ref` 69640).
  Both assertions must survive; neither field nor keyword wins the conflict.
- 166227: `spore-shaped` keyword without `spore-forming` or structured spore
  formation. Cell shape is not positive or negative sporulation.

Tests reuse the unchanged native METPO projections in
`../bacdive_phenotype_context/`. The native production template
`data/raw/metpo_sheet.tsv` (SHA-256
`ec9700569bf5e83d39fe4c29f525c06d3c396adfad2ce0bf33072b8b1a1b1409`)
declares sporulation parent `METPO:1000870`, positive child `METPO:1000871`
(`spore forming`, native BacDive value `yes`) and negative child
`METPO:1000872` (`non-spore forming`, native value `no`). The consumer's
existing contextual key `sporulation.yes` therefore supplies the target,
category, predicate, and ancestry for the exact observed positive keyword.
No new ontology alias or class is inserted into that fixture or shared loader.
An encountered exact keyword in its native sporulation route fails explicitly
if its required positive mapping, target, label/category/predicate metadata, or
acyclic sporulation ancestry is invalid. Ordinary out-of-axis fallback mappings
still return no match. The outer phenotype helper's pre-existing no-op for an entirely
absent route parent is unchanged; that broader routing contract is not repaired
by this finite alias.

Parameterized tests additionally vary source-field absence, positive/negative
structured values, and scalar/list keyword shape. Those variants are explicit
test perturbations, not claims that these four raw records had other values.
Negative spellings, case changes, naked yes/no, and `spore-shaped` are rejection
controls for this narrow positive alias, not a new negative mapping policy.
