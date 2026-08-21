# Transform modularization plan

This note defines dependency direction before the staged splits tracked in
#858, #859, and #860. The split is mechanical: public transform classes and TSV
output remain compatible, and each move needs focused tests plus a golden graph
comparison before the next layer moves.

## Dependency rule

Dependencies point inward in this order:

```text
entry point/orchestration -> domain services -> parsing + resolution + emission
                                              -> shared typed records/interfaces
```

Parsing and emission modules may use the standard library and shared record
types. They must not import a transform class, instantiate ontology adapters,
read repository-global data at import time, or perform network access. Domain
services receive paths, adapters, and mappings explicitly. Orchestrators own
configuration, lifecycle, multiprocessing, progress, and final deduplication.

Compatibility imports may re-export a moved symbol from its historical module,
but may not copy its implementation. They should be removed after internal and
external callers migrate.

## MetaTraits (#858)

Target package boundaries:

- `io.py`: tolerant JSONL/gzip readers and streaming TSV writers.
- `records.py`: typed normalized taxon, trait, and measurement records.
- `parsing.py`: JSONL-to-record parsing; no ontology or output concerns.
- `resolution.py`: microbial, chemical, METPO, and NCBITaxon resolution against
  injected mappings/adapters.
- `emission.py`: records/resolutions to KGX node and edge rows.
- `orchestration.py`: worker setup, chunking, merging, and output lifecycle.
- `metatraits.py`: stable `MetaTraitsTransform` entry point and temporary
  compatibility re-exports.

The first stage moves file I/O, whose behavior is covered for real gzip,
misnamed plain text, corrupt headers, streaming writes, and archive-independent
fixtures. Subsequent stages should establish a small golden JSONL fixture and
snapshot sorted node/edge rows before moving trait-resolution branches.

## BacDive (#859)

Target package boundaries:

- `parsing.py`: JSON path extraction and normalized BacDive record access.
- `taxonomy.py`: strain/LPSN/NCBITaxon normalization and provisional taxa.
- `resolution.py`: injected ontology and curated-mapping lookups.
- `traits.py`: phenotype, metabolite, medium, pathogenicity, and assay modeling.
- `emission.py`: row construction and provenance-aware writers.
- `bacdive.py`: configuration, orchestration, and compatibility imports.

The first stage moves the provenance writer, already covered by focused
fixture-based tests. Before moving the large `run()` branches, capture a tiny
BacDive record that exercises taxon, medium, metabolite, isolation, and assay
output and compare sorted output rows byte-for-byte.

## Ontology utilities (#860)

Current caller groups are transforms (`bacdive`, `bactotraits`, `bakta`,
`lpsn`, `madin_etal`, `metatraits`, `ontologies`, `rhea_mappings`, and UniProt),
plus `ner_utils`, `oak_utils`, and `uniprot_utils`. Tests also use private cache
helpers while validating rebuild recovery; compatibility exports are required
during migration.

Target boundaries:

- `ontology_cache.py`: release inspection, file/database validation, locking,
  atomic decompression, SemSQL building, and injectable command execution.
- `ontology_access.py`: adapter registry, lazy proxies, and typed access
  protocol; it depends on cache management, never the reverse.
- `ontology_resolution.py`: pure category/resolution policy over injected
  adapters and lookup results.
- `ontology_validation.py`: version gates and diagnostics.
- `ontology_utils.py`: compatibility exports during caller migration only.

The first policy extraction must keep cache and adapter creation in
`ontology_utils` while moving deterministic category decisions to
`ontology_resolution`. Later changes can move one ontology builder at a time,
starting with EC (smallest), and run the existing corruption, release-drift,
lock-contention, synonym, obsolete-term, ambiguity, and missing-term tests after
each move.

## Golden comparison gate

Each phase records the exact command, fixture version, environment, and sorted
node/edge hashes in its pull request. Only documented corrections may change
the hashes. Imports of each new low-level module are tested with sockets blocked
and without `data/raw` present.
