# Native process-category evidence (#1216)

The node labels and named subclass assertions in `nodes.tsv` and `edges.tsv`
are an immutable excerpt of METPO release **2026-06-12**, projected into the
existing KGX columns. These are category-projection test inputs, not newly
curated scientific mappings.

Authority: <https://github.com/berkeleybop/metpo/blob/2026-06-12/metpo.owl>.
The inspected local native OWL SHA-256 was
`32663b55d2e3ebd58010901431f8d5b5fb7d5528d304cd2856214711969717ae`;
its local JSON SHA-256 was
`fbef7ad9b436b28c59d142876eac3d98ffcf1777edab33a67e35fabd841d391a`.

- `METPO:1000630` is explicitly named biological process and defines the
  execution of a genetically encoded biological module/program.
- `METPO:1000060` metabolism is directly a subclass of that root.
- `METPO:1002005` Fermentation and `METPO:1000844` Methanogenesis are directly
  subclasses of metabolism.
- `METPO:1005039` nitrogen fixation is directly a subclass of biological process.
- The separate phenotype, trophic-type and Gram-stain branch is a negative
  control. The ferments property is also not a process class.

The full inspected current biological-process branch has 18 active classes;
this small excerpt intentionally contains five. No test infers a class from
words in its label or definition. Malformed, cyclic, deprecated, imported and
metadata-edge adversaries are generated only within test temporary directories.

`biolink-4.4.2-processes.yaml` retains the relevant exact ancestry and predicate
fields from the pinned Biolink 4.4.2 source linked in that file. `capable_of`
has range Occurrent; BiologicalProcess includes that mixin, whereas the
generic OntologyClass mixin alone does not.
