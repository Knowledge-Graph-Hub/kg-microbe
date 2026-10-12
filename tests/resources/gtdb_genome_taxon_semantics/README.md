# Native assembly-to-taxon evidence

These immutable excerpts were selected on 2026-09-30 from the existing local
`data/raw/gtdb` downloads. `taxonomy.tsv` contains four unchanged source lines;
`metadata.tsv` projects six named columns from the corresponding actual records,
without changing their values. The files deliberately include bacterial and
archaeal accessions, GenBank and RefSeq assemblies, an assembly-to-assembly paired
accession, and two assemblies assigned to the same taxon.

| Source file | SHA-256 | Selected physical lines (header included) |
| --- | --- | --- |
| `bac120_taxonomy.tsv` | `12de91fa3b1267cc2aeec843d6b9382aa98175b1e1d64804095eb09db80b3c4f` | 11, 236626 |
| `ar53_taxonomy.tsv` | `f20b8005ba2e0363ae00a3169211155f6b869787f6053a43e2558ced18acd844` | 1, 2 |
| `bac120_metadata.tsv.gz` | `1650d3164666e5839c20ee15d82511909a5bbd5269035a7b564b9048dd777893` | 302597, 699774 (decompressed) |
| `ar53_metadata.tsv.gz` | `d6ddc0f95d269a6e31af8329e0c3c2af0d90d5dad48f5b3e9d820f340951d8c3` | 4439, 10820 (decompressed) |

The configured download URLs are
`https://data.gtdb.ecogenomic.org/releases/latest/{source filename}`.
The hashes identify the inspected bytes; the mutable `latest` URL is not a
release pin. No release identity is inferred from the URL or local file date.

GTDB's [native methods](https://gtdb.ecogenomic.org/faq#how-are-gtdb-species-clusters-formed)
explain that genomes are assigned to species clusters using representative
genomes, nucleotide similarity and alignment fraction. This is assembly
classification. It does not assert that a genome is a subclass of an organism
taxon. The actual source values also show why a display name is not taxonomy
authority: the K-12 assembly is assigned to `s__G047199095 sp047199095` in these
bytes, while a Shigella-labelled assembly is assigned to `s__Escherichia coli`.
The fixture retains those assignments exactly.

The inspected pinned `data/raw/biolink-model.yaml` is version **4.4.2**, SHA-256
`b6a1320772a92d69e84b8c700cd6386dffe45ed635c8197d61e22b6a6fa3b35e`:

- `in taxon` (lines 5852–5868) has domain `thing with taxon`, range
  `organism taxon`, and exact mapping `RO:0002162`.
- `genome` (lines 9546–9561) inherits `biological entity`; that class has the
  `thing with taxon` mixin (lines 8095–8103).
- `organism taxon` (lines 7280–7285) describes organism classifications,
  including strains and subspecies. This does not make assemblies taxa.

The producer therefore emits `biolink:in_taxon` / `RO:0002162` only for
assembly-to-GTDB taxon assignments. Taxon-parent `subclass_of`, assembly identity
and paired-accession `same_as`, and GTDB–NCBI close/broad mappings keep their
separate existing contracts. This source correction is not a blanket exception
for OrganismTaxon diagnostics and does not authorize a release.
