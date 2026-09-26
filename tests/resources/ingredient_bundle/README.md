# Actual MIM producer fixture

`reviewed-cases-v1.tar.gz` is a deterministic tar/gzip of the unmodified directory
exported from the exact MediaIngredientMech commit and CLI recorded in
`origin.json`. The archive and embedded manifest have independent recorded hashes.
No hand-written consumer TSV substitutes for the producer output.

To reproduce, check out the pinned producer commit, install its locked runtime,
run the recorded export command into a new directory, and tar each file in lexical
path order with relative names, UID/GID 0, blank owner/group names, mode 0644 and
mtime 0. Gzip uses mtime 0 and a blank filename. The reviewed scientific evidence
is inside the bundle and all reads are offline.

The 20 mappings, 18 identifier claims, three BSA products and ten occurrences are
source data. Synthetic test variants must be labeled as software fixtures and
must not be mistaken for new scientific evidence about those products.
