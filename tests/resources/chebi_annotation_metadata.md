# ChEBI annotation-only regression fixture

`chebi_annotation_metadata.json` is an intentionally minimal OBOJSON fixture.
The six annotation declarations preserve the identifiers, labels where present,
and `PROPERTY` / `ANNOTATION` types found in both selected production ChEBI and
UBERON authorities on 2026-09-30. It is not an ontology release or graph export.

| Selected authority | SHA-256 |
| --- | --- |
| chebi.json | a5d40380ab78bde0e8b5a704dbee3cba2bcaa7608be46eebc2f4a92932516c9b |
| chebi.owl | f0a91ba0cfc60e252a2bd08e85d953991df07c500725b56c1e52d7eba61f98ab |
| uberon.json | 87a892da0544a82f41f0a8b2b52f7ee705ec6d5ca2c102e7d439a7086d79f428 |
| uberon.owl | 938f51e7c3fc9fcbe5a2863eb346da8033737e568af5836958891c4c6bfb1192 |

Each exact slash-form IRI is explicitly an `owl:AnnotationProperty` in both
RDF/XML authorities. `BRAND_NAME`, `INN`, and `IUPAC_NAME` are subproperties of
`oboInOwl:SynonymTypeProperty`; `1_STAR`, `2_STAR`, and `3_STAR` are subproperties
of `oboInOwl:SubsetProperty`. None is a chemical class declaration.

The water term/synonym and the three extra genuine-class/object-property nodes
are synthetic positive controls. They test preservation of synonym metadata,
real terms, misleading labels and unrelated OBO identifiers. Punning controls
are added to isolated fixture copies by the tests, never to this authority
fixture or production data.
