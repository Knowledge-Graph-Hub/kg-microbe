# Source finalization and canonical merge serialization

The September 20 review identified two ingredient identity defects and transport
work that belonged before merge. The boundary is now:

`raw inputs → transform → audited source finalization → KGX aggregation → canonical TSV serialization → cross-source validation → statistics/manifest → one archive → guarded publication`

## Chemical identity belongs upstream

`mappings/ingredient_identity_exclusions.tsv` rejects specific ingredient-name
groundings and false cross-reference pairs. It does not blacklist ontology IDs:
`CHEBI:78018` still means dodecylphosphocholine, and `FOODON:03302071` still means
green kidney bean. Neither is a replacement for a casein digest or peptone broth.
Legitimate ontology declarations and chemical-role edges remain intact.
The audit also covers the erroneous Casamino-acid fallback to `CHEBI:78020`
(heptacosanoate), and names that had leaked from that entity onto `CHEBI:78018`.
Correct heptacosanoate/carbocerate identities remain available on `CHEBI:78020`.
Further checks of the actual next-choice mappings rejected Tryptone on
`CHEBI:84843` ((R)-2,6-dimethylheptanoylcarnitine) and proteose peptone on
`FOODON:00002992` (fresh bratwurst). These exclusions are likewise scoped to
incorrect ingredient groundings; the legitimate authority entities are retained.

The shared policy applies to unified mapping lookup and consolidation, and to
MediaDive's legacy/embedded fallback paths. Unsupported groundings retain an
ingredient-specific unresolved identity; no replacement chemical is invented.
The policy is a shared content dependency in transform fingerprints and the
source-finalization input ledger.

Vendored MediaIngredientMech mapping inputs are not hand-edited. A bounded
candidate refresh is available without sibling synchronization or OAK enrichment:

```bash
poetry run python scripts/consolidate_chemical_mappings.py \
  --identity-policy-only --output data/identity-policy-candidate.sssom.tsv.gz
```

Review that candidate before replacing the unified artifact. This mode retains
unrelated rows, including asymmetric and hydrate relationships, records the policy
fingerprint, and validates SSSOM before publishing its candidate. The ordinary full
consolidation also enforces the policy so reseeding cannot restore rejected mappings.

## Source-finalization contract

Source finalization version 2 emits deterministic canonical headers and literal LF
TSVs. Every edge has `subject`, `predicate`, `object`, `relation`,
`primary_knowledge_source`, `knowledge_level`, and `agent_type` columns. Missing
knowledge-level/agent-type values remain explicitly empty rather than fabricated.
Extensions and meaningful source metadata are retained.

Legacy provider aliases and `knowledge_source` migrate here, with the original and
normalized row retained in `source_canonicalization.tsv`. BacDive record IDs become
publication evidence under the BacDive provider. Supplied edge IDs become
`source_assertion_id`; conflicting provider/ID cells, multiple providers, and missing
providers fail before the finalization success record is published. Node provider
collections can be unioned at merge; blank provenance is not invented for stubs.

Source finalization continues to own ontology identity/category/reference decisions.
It may rewrite its staged source outputs. Merge must not repair these semantics.

## Merge responsibilities

The KGX sink emits the canonical schema directly, excluding its private `id`/`key`
and legacy `knowledge_source` edge columns. Literal quotes, backslashes, scalar
extension values, original assertion IDs, and evidence pairings survive export.
Identical complete observations can aggregate; shared triples alone do not make
independent observations identical.

For a configured `tar.gz` destination, only the private staging configuration asks
KGX for loose TSVs. The user's merge configuration remains unchanged. Merge then
validates canonical representation and cross-source endpoint closure, computes
final statistics and manifests, and builds the archive once. The production path
does not compress, extract, normalize, and recompress the graph.

Source admission/freshness is checked before processing and rechecked before
publication. Required serializer, validation, or manifest failures preserve the prior
published archive. Optional diagnostic/statistics failures remain isolated; failed
statistics are withheld. Publication is staged, with completion artifacts last, not
claimed to be an atomic transaction across every output file. Stale sibling artifacts
are warned about, not deleted.

Compatibility helpers for explicit legacy callers remain available, but the public
merge workflow does not use post-merge TSV normalizers to fix current source rows.

## Rebuilding existing data

These code changes do not modify the existing merged archive or certify old source
outputs under version 2. Shared finalization/schema and mapping code changes make
old producer fingerprints stale. Rerun all sources selected by the intended merge
configuration, then merge and review the new artifact. Do not bypass the freshness
gate or merely restamp markers. A new raw download is not inherently required.
