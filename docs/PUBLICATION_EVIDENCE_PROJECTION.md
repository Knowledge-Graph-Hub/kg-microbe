# Portable locators in reviewed evidence

Eight reviewed evidence artifacts use descriptive relative locator namespaces instead of private machine paths. This is a finite publication projection, not a transform, an identity mapping, or a rewrite of any raw, transformed, or merged graph.

- `source-repository/` identifies the historical original repository root.
- `candidate-worktree/` identifies the separately reviewed candidate worktree root.
- `review-evidence/` identifies historical local review evidence.

These are evidence-locator namespaces, not paths to resolve against the active checkout and not promises of public download availability. Source content hashes retain their original meaning. Do not replace them with hashes of the published evidence containers.

## Exact scope

The publication manifest, [publication_locator_projection.json](../tests/resources/publication_locator_projection.json), records the exact original and published artifact hashes, allowlisted field positions, and full scientific-remainder hashes for this projection.

| Evidence artifact | Metadata locators | Historical field strings |
| --- | ---: | ---: |
| `mappings/kgxval_reference_dispositions_v1.json` | 6 | 0 |
| `mappings/mediadive_recipe_identity_evidence.json` | 15 | 0 |
| `tests/resources/gold_selected_taxon_aliases/native_evidence.json` | 8 | 0 |
| `tests/resources/gold_selected_taxon_aliases/producer_contexts.json` | 2 | 0 |
| `tests/resources/gold_taxonomy/microbedecoder_native_context.json` | 4 | 0 |
| `tests/resources/gold_taxonomy/native_contexts.json` | 4 | 0 |
| `tests/resources/native_ro_retention/temporal62_native.json` | 16 | 0 |
| `tests/resources/participation_disposition/historical_claims.json` | 0 | 2 |
| Total | 55 | 2 |

Every biological identifier, native row, coordinate, citation, source-content hash, quantity, replacement chain, complete XML stanza, and annotation remains unchanged. The projection does not reinterpret the original evidence. Ordinary code, policy, and evidence fingerprints still apply; updating the published containers invalidates affected previously finalized producers as usual.

## Two explicitly projected historical fields

The participation fixture retains all 323 historical claim records in their original order. Two PATO-supplied claims, with original subjects `GO:0006082` and `GO:0043603`, were separately quarantined because their native existential restrictions do not transfer to broad `GO:0008152`. Their historical `go_reference_context` strings contain a private authority locator.

Only that locator is projected in the two public field views. Those two strings are **not byte-identical unprojected originals**. Their original string and field-map hashes, published hashes, original triples, supplier, and historical line coordinates are explicitly recorded in the publication manifest. The authority content hash and every other context field remain unchanged. The other 321 historical field maps are unaffected, and the 321 retained / two quarantined disposition split is unchanged.

Byte-exact original artifacts and a reversible locator map are retained in private review evidence, outside the deliverable. Independent local review verifies full inverse reconstruction against those originals. The portable tests verify the declared projection and its scientific remainder; they do not claim to reconstruct unavailable private path values from hashes.

## Verification boundary

`tests/test_publication_locator_projection.py` pins the exact eight-file projection and rejects scientific changes, extra or missing projections, changed roots or suffixes, unsafe locators, and changed original-hash declarations even when public container hashes are recomputed. Existing native-evidence and transform tests remain authoritative for the underlying scientific decisions. No generic path normalization or graph-validation exception is introduced.
