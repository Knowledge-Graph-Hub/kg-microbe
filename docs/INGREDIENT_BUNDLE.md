# Reviewed ingredient bundle consumer

The opt-in consumer validates the complete MIM scope/registry/occurrence bundle
before using its mappings. Supply the independently reviewed SHA-256 of
`manifest.json`; a hash read from an untrusted manifest does not establish trust.
The current fixture comes from MIM commit
`73f14f4a930249836b4c3eee9bae635c731d6c5e`, exported by its actual producer CLI.
It is a reviewed cohort, not a replacement for the full legacy ingredient release.

```python
from pathlib import Path
from kg_microbe.utils.ingredient_bundle import ReviewedIngredientBundle

bundle = ReviewedIngredientBundle(Path("candidate/ingredient_bundle"),
                                  manifest_sha256="<reviewed 64-hex digest>")
bundle.resolve_source("MIM:Xanthine")  # CHEBI:17712
bundle.active_xrefs("CHEBI:17712")     # ["cas:69-89-6"]
bundle.active_xrefs("CHEBI:15318")     # []
```

Source concepts and occurrences resolve before label or namespace preference.
`resolve_source` accepts a known scoped source ID and, optionally, its verified
occurrence ID. Native generic trait IDs are not reinterpreted as MIM ingredients.
A matching review can authorize canonical replacement; `xref` alone cannot.
Nonidentity mappings retain the source concept. Broader targets never inherit
specific-subject CAS claims through this API.

`identifier_owners` returns every annotation owner, rather than one identity
representative. BSA and its specifically reviewed A7030 material both refer to
CAS 9048-46-8. They remain distinct identifiers. `identifier_claims` preserves
complete owner/identifier/source/status/evidence tuples, including FDA SUPERSEDED
and original CultureBotHT claims for Acriflavine. Historical/unknown-currentness
and withheld/invalid claims are not active xrefs. No replacement CAS is inferred.

## Consolidation and lookup

`build_ingredient_lookup_bundle(consolidator, bundle, output_directory)` uses the
existing consolidator for explicitly selected native/legacy inputs and keeps the
reviewed scoped cohort as a separate required input. It requires a new output
directory and checks every authorized scoped target before export and again
against usable declarations in the serialized lookup. Annotation, broader-only,
and quarantined rows cannot satisfy that endpoint inventory.

The candidate includes the legacy SSSOM, unchanged producer bundle and evidence,
a graph-associated annotation JSON, an audit, and a common `lookup_manifest.json`
that binds them by content digest. Its mode is `candidate_only`. Reload with:

```python
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader

loader = ChemicalMappingLoader.from_ingredient_lookup_bundle(
    Path("candidate"), manifest_sha256="<reviewed lookup-manifest digest>")
loader.resolve_ingredient_source("MIM:Xanthine")  # CHEBI:17712
loader.find_chebi_by_name("Xanthine")              # generic CHEBI:15318
loader.get_identifier_annotation_owners("cas:9048-46-8")  # multiple owners
```

Neither the standalone TSV loader nor additive MIM consolidator accepts a bare
profiled TSV. This prevents loss of scope or review fields from becoming a silent
legacy fallback. The source-specific mappings are not flattened into global name
aliases. Existing legacy-only calls retain their established behavior. The
existing case policy remains in place; `policy_parity()` currently reports zero
differences across all 20 covered canonical targets. Removing that policy requires
separate migration evidence, especially for cases outside this cohort.

For a covered node, `get_node_enrichment` uses the bundle's reviewed active CAS
set. Other legacy CAS values are outside the selected bundle's active evidence;
this does not reject an independent source's claim globally. Original history
remains queryable. Supplier/catalog/preparation attributes are never added to a
generic ingredient's synonyms. Annotation xrefs never populate the legacy
identity-xref index. CAS query routes explicitly present in the older case policy
remain separate from this new annotation transport.

## Provenance, freshness and occurrence handoff

The portable schema/validator verifies member hashes, capability and profile
versions, complete owner-bound reviews and exact artifact reconstruction. Its
origin and hashes are recorded under `docs/reviews/ingredient-bundle-v1/`.
Rehashing a modified output cannot override its scientific proof or orphan a
required target.

`write_annotations` produces `ingredient_identifier_annotations.json` with each
original claim alongside its projected canonical owner, the source bundle pin,
and an evidence-URN-to-member map. Keep it with the unchanged `ingredient_bundle`
directory; the lookup exporter does this automatically. Flat node xrefs cannot
substitute for this graph-associated history artifact.

`bind_to_transform(transform)` records every validated bundle member in the
producer's consumed-input snapshots. Call it after `begin_consumed_inputs` and
before using the bundle. Changed or missing bytes then prevent source finalization;
failed binding latches a consumed-input error. A bundle instance is an immutable
in-process snapshot. Reconstruct or call `verify_current` at reuse boundaries;
there is no repeated filesystem scan in hot per-node lookup calls. Pinned legacy
lookup loads compare content digests before reusing a cached path. Profiled
loader accessors reselect their explicit lookup when another legacy caller
replaces the process cache; a different caller cannot silently replace their
name/category/xref results. The scope
profile, companion schema and case annotation policy also participate in shared
transform data fingerprints.

`products()` and `occurrences()` expose their full reviewed records and explicit
one-of groups. The audit counts retained records and all claim dispositions.
Their KGX ingestion/finalization/merge route is implemented under #1135; general
profile activation and the combined producer-to-merge acceptance gate are #1136.
This consumer does not change production download pins or bypass the existing
release-promotion gate in #1123.
