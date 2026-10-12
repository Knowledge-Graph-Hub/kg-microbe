# Merge boundary: validate and package, never repair

`poetry run kg merge -y merge.yaml` consumes finalized source TSVs. Biological
and semantic corrections belong in source transforms or their audited
[source finalization](PREMERGE_SOURCE_FINALIZATION.md), **not after graph
union and not in a post-merge TSV editor**.

The historical log line
`[merge-cleanup] extracting merged-kg.tar.gz to normalize TSVs in place`
describes a retired standard path. Current public merges write canonical
TSVs first and construct each archive once. They do not extract, rewrite,
and recompress a newly generated graph.

## Responsibilities

| Stage | Allowed work |
|---|---|
| Source transforms/finalization | Identifier and chemical mapping decisions; exclusions and incident-edge removal; category assignment; provenance and schema migration; self-loop prevention; original-record audit trails and dependency fingerprints. |
| Graph union | Combine source declarations; aggregate node properties and provenance; deduplicate identical **complete** edge observations, preserving different evidence/context. |
| First-write serializer | Canonical column ordering, literal LF TSV transport, representation of already-finalized multivalued values; omit internal graph keys. Embedded controls and ambiguous scalar values fail instead of being silently repaired. |
| After serialization | Read-only cross-source validation, reports and statistics; hash verification; manifest/archive construction; guarded publication. No changes to graph TSV bytes. |

Aggregation is not biological inference. Repeated nonempty node descriptions
from independent declarations remain repeated; the serializer omits empty
description list entries but does not deduplicate meaningful descriptions.
Different predicates, references, categories or endpoints must not be invented
or repaired by the merge.

## Enforced configuration contract

`merge_utils/merge_contract.py` rejects active prefix/predicate remapping,
filters, schema projection and provenance overrides before source admission
or expensive graph loading. Sources must be TSVs. These restrictions also
apply when the explicit diagnostic `allow_unfinalized_sources` option is used;
that option bypasses freshness admission, not the no-edit contract.
Checkpoint writes are disabled. Statistics and graph destinations cannot
overlap configured inputs, admitted dependency/code paths, configuration, or
each other; a statistics filename is not permission to overwrite a source.

Arbitrary KGX operation callbacks are not a release escape hatch. The only
allowed operation is graph-level
`kgx.graph_operations.summarize_graph.generate_graph_stats`, with its inspected
finite argument set. Source/input/destination operations are rejected. Put
semantic changes in the upstream producer and rebuild its output. Empty
legacy mapping placeholders in the canonical YAML remain harmless.

The direct-export optimization has separate eligibility checks. Falling back
to the supported KGX exporter does **not** bypass this release contract.

## Standard public merge sequence

1. Validate all destinations and the no-edit configuration contract. Check
   finalized source bundles and their current producer dependencies.
2. Stage output privately, preserving prior published artifacts. Read admitted
   sources, combine observations and serialize canonical loose TSVs once.
3. Stream SHA-256, byte size and row-count identities for **all** first-write
   node/edge pairs before any downstream report runs. This adds one bounded
   sequential read, not another graph copy in memory.
4. Validate canonical TSV contracts and cross-source endpoint closure. Write
   `<base>_reference_resolution.tsv` as a validation report, not a list of
   repairs applied to the merged graph. Required failures abort publication.
5. Run read-only invariant diagnostics and final statistics. An optional
   diagnostic failure is reported separately; failed statistics are withheld.
   An optional callback cannot edit graph bytes and then escape the contract
   by raising an otherwise nonfatal exception.
6. Finish reports and provenance preparation for **all** destinations before
   packaging any of them. Package each TSV pair and reference report, plus
   `manifest.json`, once.
   Hashes calculated while writing archive members must equal the captured
   first-write graph identities **before atomic archive replacement**. Loose
   TSV publication performs the same comparison during manifest generation.
   Any mismatch is a required failure, even if the edited TSV is still valid.
7. Recheck source admission and publish completed staged artifacts. For an
   archive destination, discard only its private loose transport copies.
   Older unrelated public artifacts are warned about, never deleted.

The manifest records the exact shipped bytes and counts. It is an integrity
record, not proof that all scientific findings are accepted or that strict
KGX validation passes. See [validation contracts](VALIDATION_CONTRACT.md).

## Compatibility and publication limits

The legacy private helper `_cleanup_merged_outputs` can still inspect an
already-existing archive by copying only its two regular TSV members into
private files. It validates and repackages those **unchanged** graph bytes;
it is not the public rebuild path. The historical `_normalize_nodes_tsv` and
`_normalize_edges_tsv` names now refer to validators, not rewriting functions.

Required serialization, validation, identity and packaging failures preserve
the previous public archive. Publication uses per-file atomic replacements;
multiple destinations or a loose TSV pair are not a cross-file transaction.
The first-write checks guard in-process post-serialization report/packaging
edits, not hostile external modification of a private staging directory.

## Logs and regression tests

- `[merge-validation] ...; no semantic rewrites`: required representation and
  endpoint checks completed without repairing the graph.
- `Post-serialization graph mutation detected`: abort; correct the producer
  or the offending report callback, never repair the merged artifact.
- `[merge-invariants] check skipped`: optional diagnostic failed; investigate
  separately from required validation.
- `[merge-stats] annotation skipped`: statistics are withheld, not silently
  presented as complete.

`tests/test_merge_immutability.py` checks rejected mutation routes, exact
first-write/archive equality, and injected report edits (including edits
followed by exceptions) for compressed and loose publication.
`test_merge_canonical_serialization.py`, `test_upstream_merge_contracts.py`
and `test_merge_node_descriptions.py` cover one-time packaging, source-byte
preservation, evidence retention and the explicit aggregation behavior.
