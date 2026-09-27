# Canonical destination export

The normal KGM merge may serialize its completed assertion graph directly to
the existing canonical TSV sink. This removes KGX's populated intermediate
destination `GraphSink`; it does **not** remove the in-memory merged graph or
the source stores retained by KGX.

Eligibility is scoped to one actual KGM merge call and the exact object returned
by its assertion merger. It requires the inspected **KGX 2.7.0** / `NxGraph` interface, TSV
source ingestion, full node/edge property inventories, and only the inspected
read-only statistics operation (or no operations) in selected source and merged
configuration. An arbitrary graph passed to `Transformer`, mutating operation,
destination filter/remapping, missing inventory, unsupported output/compression
or unknown installed KGX version takes the existing intermediate-graph path.
That fallback preserves existing behavior; it is not a general compatibility
claim for other KGX versions (the broader contract remains tracked in #1066).

Checking destination `operations=[]` alone would be unsafe: KGX has already
applied source/merged operations before destination export. Such operations can
leave differently keyed observations that only the intermediate graph's
normalization/deduplication coalesces. The optimization must not authorize those
graphs. The normal source sinks already coalesce only fully identical normalized
observations; distinct evidence, provider, context, relation and polarity remain
separate. Node provider/category unions are not scalar edge-provenance unions.

Both export paths keep `RelationAwareGraphSource` and `RelationAwareTsvSink`
validation and canonical full-field serialization. Header inventories include
all declared extensions even if every value is blank. No source loading,
scientific identity resolution, public input admission, validation, manifest,
single-archive packaging or per-artifact atomic publication gate is bypassed.
Progress messages contain flushed phase/counters and elapsed time, not record
contents or a guessed ETA. Direct serialization reports every 100,000 records;
archive member streaming reports every 64 MiB. Validation announces entry and
completion/counts without inserting a new graph scan.

## Bounded offline benchmark

Run with the existing project interpreter, from this checkout, into a **new**
evidence directory whose parent exists:

```bash
PYTHONDONTWRITEBYTECODE=1 poetry run python scripts/benchmark_merge_export.py \
  --edges 20000 --repeats 3 --output /absolute/new/benchmark-output
```

The script uses immutable synthetic fixture/schema templates, deterministic
generated observations with exact duplicate controls, and separate fresh
interpreters for alternating baseline/direct runs. It exercises real public
merge/export, required validation and one archive, with the explicitly declared
diagnostic unfinalized-source option. It does not read production sources or
claim source freshness. External network access is forbidden. Both the complete
TSV/audit member byte hashes and generated input hashes must match across every
run; mismatches cannot produce an accepted timing report. The fast-path call
count must prove the optimization actually ran.

Export-call wall time is measured separately from whole-public-call time. Peak
process RSS includes imports, ingestion and export and is not isolated export
memory. Concurrent host load is uncontrolled; report individual repetitions,
not an extrapolated production speedup. No timing or memory threshold belongs
in the unit-test gate. The benchmark is bounded to at most 200,000 unique edges
and ten paired repetitions, writes only its new output directory, and preserves
logs and exact fixture/code/interpreter before/after hashes.
