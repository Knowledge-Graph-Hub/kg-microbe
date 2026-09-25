# Pinned FoodOn ancestor excerpt

`foodon-authority.json` contains the original three reviewed FoodOn nodes and all
of their asserted `is_a` / `rdfs:subClassOf` ancestors from the local KG-Microbe
`data/raw/foodon.json`. The full source identifies FoodOn release 2025-12-30. Its
whole-file SHA-256, byte count, original graph metadata, seed IDs, and excerpt
SHA-256 are recorded in `foodon-origin.json`. Eight nodes and seven original edges
are retained. No edge is synthesized, and this excerpt is not a full ontology.

To reproduce, verify the full input digest, stream `graphs.item.edges.item` with
ijson and repeatedly add parents of the recorded seed/ancestor set until no ID is
added. Retain each original matching edge once, then stream the original nodes
and retain IDs in that set. Copy the original graph `id` and `meta`; sort nodes by
ID and edges by their `json.dumps(edge, sort_keys=True)` key. Serialize the result
with `json.dumps(result, indent=2, sort_keys=True) + "\n"`. Check the input digest
again to reject changes during extraction and compare the recorded excerpt hash.

Tests copy these immutable bytes to the selected raw directory. They exercise
FoodOn category finalization without bypassing its required local authority.
