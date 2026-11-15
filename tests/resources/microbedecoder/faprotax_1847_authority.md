# Additional native FAPROTAX type declaration

`faprotax_1847_metpo_nodes.tsv` adds the exact selected native `METPO:1000651` (methylotrophic) declaration to copied synthetic authority tables. The historical `metpo_nodes.tsv` fixture stays byte-identical. The actual selected METPO JSON is SHA256 `fbef7ad9b436b28c59d142876eac3d98ffcf1777edab33a67e35fabd841d391a`; class declarations use the existing ontology producer category `biolink:OntologyClass`.

The other five reviewed classes are already present in the historical fixture. This tiny fixture is not a new ontology release, scientific observation, or an assertion that a complete source dataset was regenerated. See `docs/MICROBEDECODER_EDGE_QUALITY_1846.md` and issues1847/1850 for exact field/value semantics and the schema-compatible Attribute representation.
