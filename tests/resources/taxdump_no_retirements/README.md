# Synthetic no-retirement lifecycle control

These four immutable files form a complete tiny test taxdump. `merged.dmp` and
`delnodes.dmp` are deliberately empty. `nodes.dmp` and `names.dmp` contain only an
explicit synthetic root; they provide no biological classification, lineage, or
current-status evidence for any source taxid.

This fixture lets a test of another source contract explicitly assume that its
already declared taxa have no recorded retirements. It is **not** an NCBI release
excerpt or proof that those taxa are currently live. It must not be used to test
retirement, replacement, deletion, or taxonomy classification. Those tests need
their own finite native evidence or explicit synthetic taxonomy context.

`tests.taxdump_controls.stage_no_retirements_taxdump(raw_dir)` packages exactly
these four members into the selected temporary raw directory, with deterministic
archive bytes and exclusive creation. No fixture is injected automatically;
the caller opts in before consumption and the real finalizer records its digest.
