# MetaTraits inference provenance fixture

These three lines are complete, byte-preserved records from
`data/raw/ncbi_species_summary.jsonl.gz` (plain JSONL despite the suffix).
`origin.json` binds original physical lines, raw-line hashes, the complete
915,078,003-byte export hash, and each historical hierarchy assertion.
No summaries were pruned, changed, or relabelled.

The full historical MetaTraits edge file contains 195 inferred hierarchy
assertions and no ordinary `rdfs:subClassOf` hierarchy assertions. These
fixtures establish source-name provenance, not authoritative taxonomic parents.
The remaining parser branches, including a successfully resolved parsed
species parent, use explicitly synthetic test records and controlled lookups.

The tests exercise real serial and reconstructed-worker writers. They preserve
the current hierarchy endpoints, native records, and trait provenance, changing
only inferred hierarchy metadata. Separate existing GTDB historical/current
mapping policies and trait interpretation are not broadened by this repair.
