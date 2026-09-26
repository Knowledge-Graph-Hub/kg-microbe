# Hydration identity regression evidence (#1158 / #337)

The TSV is a verbatim label and selected-synonym projection of the existing native
`data/transformed/ontologies/chebi_nodes.tsv`, SHA-256
`c161f8aea7ffeb1a2557f24100b3b3b67bfd62196d484b33c675921154c8b152`,
read on 2026-09-25. No live ontology request is needed in tests.

The read-only source replay recorded these ingredient queries:

| Source query | Unsafe selected target | Independently supplied fallback |
| --- | --- | --- |
| FeCl3 x 6 H2O | CHEBI:30808, iron trichloride | CHEBI:86254, iron trichloride hexahydrate |
| CoCl2 x 6 H2O | CHEBI:35696, cobalt dichloride | No replacement inferred |
| Na2WO4 x 2 H2O | CHEBI:63940, sodium tungstate | No replacement inferred |
| NiCl2 x 6 H2O | CHEBI:34887, nickel dichloride | No replacement inferred |

Native CHEBI:86254 additionally describes itself as “A hydrate that is the
hexahydrate form of iron trichloride.” Its native CAS annotation is 10025-77-1;
the anhydrous CHEBI:30808 annotation is 7705-08-0. Tests do not invent a CAS
replacement or derive chemical equivalence merely by comparing water counts.

Hydration compatibility is an admission restriction on an independently supplied
mapping. Equal water counts alone do not create a new mapping. Unknown hydration
scope cannot choose a numeric hydrate; an existing unspecified-hydrate identity
may retain that unspecified scope. Recipe-equivalent links remain nonidentity.

Three supported-release positive controls use the same pinned native TSV:

- CHEBI:74779, aluminium sulfate octadecahydrate, explicitly carries
  `Al2(SO4)3.18H2O`.
- CHEBI:51799, imipenem hydrate, independently carries the synonym
  `N-formimidoyl thienamycin monohydrate`. The pinned native `chebi.db`, SHA-256
  `081d065c12487e567fac48ab8c5ee87cc533b2ac89e22f47c119be4ee37ff0b7`,
  corroborates `chemrof:generalized_empirical_formula` = `C12H17N3O4S.H2O`.
  Only independently native evidence may refine the unspecified preferred label;
  the ingredient query or a historical source alias is not evidence for itself.
- CHEBI:87020, vanadyl sulfate hydrate, has `VOSO4.nH2O` and defines a hydrate
  with an unspecified number of water molecules. This supports unspecified to
  unspecified scope, never selecting a particular hydrate count.
