# Merge integrity repairs (#1049–#1055)

These fixes change the pipeline code, not previously generated TSVs or archives.
Do not treat a successful unit test as evidence that an existing archive was
rebuilt. Preserve the previous archive separately if it is needed for comparison.

## Corrected contracts

| Finding | Contract |
| --- | --- |
| #1049 | Graph export preserves each node's explicit `provided_by` values, including multiple providers. A synthetic endpoint has no invented provider. |
| #1050 | MicrobeDecoder uses `ncbi.assembly:GCF_*` / `GCA_*` for assembly accessions, retaining accession versions; GTDB taxonomy strings remain `GTDB:`. |
| #1051 | GOLD identifiers use `gold:`. Its explicit fold report reconnects collapsed organism IDs to the final taxon IDs. Unknown or trimmed references remain visible gaps. |
| #1052 | FOODON/PATO categories are normalized by node namespace, including imported terms. The generic `OntologyClass` category is removed without discarding substantive additional categories. |
| #1053 | Synthetic MetaTraits mappings reuse the canonical GTDB pair's `broad_match` or `close_match`; they never assert `same_as`. |
| #1054 | Edge identity includes its scalar original relation before provenance aggregation. Registered IRIs compact consistently in nodes and endpoints; declared annotation properties do not become entity nodes. |
| #1055 | Stats name the archive and member that survive cleanup, or a loose file when that is the destination. The reviewed merged METPO fraction was 50.09%, not the pre-merge fraction. |

The KGX compatibility layer is local to a merge invocation and restored on
failure. Source parsing remains a top-level callable for spawned workers.
Normalizing an existing merged relation list cannot recover which source
asserted which relation: rebuild from the source TSVs instead.

## Rebuilding and acceptance

At minimum regenerate `ontologies`, `gold`, `microbedecoder`, and
`metatraits_gtdb`, in dependency order. GTDB's canonical transformed mappings
must be present. GOLD's new `organism_folds.tsv` must exist before MicrobeDecoder
runs, even when it contains only its header. Shared-code fingerprint changes
may require further source reruns; inspect freshness rather than relabeling old
outputs as current.

Run the focused regressions and the repository's normal checks before merging.
Then build with the canonical configuration:

```bash
poetry run kg merge -y merge.yaml
```

Check the resulting archive, not an old extracted pair:

- Node provider values include actual source provenance, not a single `Graph`.
- No legacy assembly-shaped `GTDB:RS_GCF_*` or uppercase `GOLD:` crosswalks.
- Missing assembly/organism IDs are unexpected in `merged_stub_nodes.tsv`;
  neither namespace is wholly exempted.
- No FOODON/PATO `OntologyClass` token and no remaining metadata-IRI nodes.
- No synthetic MetaTraits GTDB `same_as` edges or pipe-valued scalar relations.
- Stats raw predicate counts sum to the new edge total; the archive/member
  locator resolves after loose TSV cleanup.

Do not require the old edge count: retaining distinct original relations can
increase it. Do not require every stub to disappear: the namespace audit found
60 assembly accessions absent from the current GTDB transformed release, and
fold resolution does not restore organisms deliberately removed by GOLD's trim.
