# MetaTraits dependency closure fixtures (#1188)

These three tiny canonical tables exercise positive recursive discovery and
actual reader outputs. They are dependency-mechanism controls, not a proposed
scientific mapping release. Tests copy and mutate them only under `tmp_path`.

The registered ontology, GTDB, MetaTraits, MetaTraits-GTDB, and unrelated COG
classes finalize the existing immutable `merge_source_freshness` graph without
calling a producer or ontology adapter. The unified mapping declaration uses a
temporary gzip of the existing immutable manual-identity SSSOM fixture; it is
not parsed by a chemical resolver in these tests. A tiny tar archive supplies
the taxdump declaration without invoking taxonomy. The real publication,
finalizer, diagnostic, and public freshness paths run against an isolated copy
of the implementation and curated shared inputs.
