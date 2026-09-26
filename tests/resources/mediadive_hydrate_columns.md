# Supplied hydrate column evidence (#1168)

This immutable excerpt was captured on 2026-09-25 from independently native
ChEBI output and already-supplied MicroMediaParam mapping rows. Line numbers
include the header. Native edge assertions all have the hydrated ID as subject,
`biolink:has_part` as predicate, the supplied base ID as object,
`BFO:0000051` as relation, `infores:chebi` as primary knowledge source,
`knowledge_assertion` as knowledge level, and `manual_agent` as agent type.
They do not assert exact identity between a hydrate and its base.

Input SHA256 fingerprints:

- `data/transformed/ontologies/chebi_nodes.tsv`:
  `c161f8aea7ffeb1a2557f24100b3b3b67bfd62196d484b33c675921154c8b152`
- `data/transformed/ontologies/chebi_edges.tsv`:
  `9a74dd1a3d92a5f82fd7361c58d1ba971abde1f8ebb5c8f2ed0c77990544e1e1`
- `data/raw/compound_mappings_strict_hydrate.tsv`:
  `d2bc349ae31990cf54ef308a14826c756be0e0ee874d35a0a6068d75ef04b3a3`

The excerpt records the supplied original name, base ID and hydrated ID,
alongside the independent native preferred label and original source line.
The source line identifies the supplied `hydrated_chebi_label`, which may be
a native synonym rather than the preferred label. These are the same
hydrated IDs that the guarded loader evaluates; no new target was inferred
from a name or water count. Several mapping rows repeat an identity across
media; one representative source line is retained for each pair.

The ten pairs correspond to eleven formerly-local unique route transitions
(two distinct MediaDive ingredient IDs share the magnesium sulfate spelling),
covering 2,628 compound/recipe routes in the all-MediaDive before/after replay.
Tests add deliberately synthetic contradictions separately; they are not
represented as native ontology facts in this fixture.
