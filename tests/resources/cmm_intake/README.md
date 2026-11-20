# Synthetic CMM intake fixture

These deliberately tiny, immutable TSVs model the *shape* of a historical CMM
export. They are not a scientifically validated or sampled biological dataset.
They include legacy identifiers/categories, missing assertion provenance fields,
a repeated assertion, a conflicting node declaration, a relative dangling
endpoint, a native predicate and a self-loop. Literal quote characters and all
duplicate claims must survive byte-for-byte in the retained input copies.

Tests copy these files to `tmp_path`; they never modify these originals.
