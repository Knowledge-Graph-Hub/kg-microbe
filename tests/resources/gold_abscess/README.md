# GOLD Abscess identity quarantine — native excerpt (#1294)

These are bounded, unchanged records, not synthetic successful mapping examples.
`GOLD_nodes.tsv` retains all 23 ecosystem context declarations and the 34 named
organism declarations for the reviewed native assignments, plus their native
taxon declarations. `GOLD_edges.tsv` retains the complete selected multi-level
hierarchy, all 34 native `occurs_in` assertions, and actual native organism-to-taxon
links. `ncbitaxon_nodes.tsv` contains the corresponding actual transformed labels:
11 observations therefore exercise the existing organism-fold behavior exactly.
Four assignments target descendant `gold.ecosystem:6347` and retain
that `original_object` after the existing transform's resolution.

The seven source Abscess concepts are qualified by distinct human anatomy
contexts. This supports retaining the source site assertions, but does not
establish exact identity with generic MeSH `D000038`. No substitute identity or
broader relation is introduced. The original curation relied on the old BacDive
mapping, not independently demonstrated identity, and is preserved in the policy.

`native_selection.json` is the sorted complete selection, independently pinned
in executable code by SHA-256
`8d0e356858c05093bd150bee2f69a9b99e4bb2b136f2b69bd0440d3f4bcb79d6`
(canonical JSON: sorted keys, ASCII, compact separators). The immutable full
snapshot hashes, seven previous crosswalk rows with original physical lines,
34 previous transformed location rows, and original full curation row are in
`mappings/gold_abscess_crosswalk_policy.json`. Its canonical digest is also
independently pinned in code. The production run checks the selected rows, not
just a policy-provided digest; unreviewed cohort/context changes fail closed.

Full input snapshots used to create the excerpts:

- GOLD nodes: `c13c21bdd04619c75ce16e63b05e51577b0cefec5b61765d383313f654ab3fae`
- GOLD edges: `54982c25de9d2c820eeebc1452aeac0b034595921d04d55b810bf1d2b1e127e0`
- Native MeSH 2026 gzip: `6997c24530cfbc698690e3d85ba5436e5ee56708f7f77073cbf8f502f3de7c5e`

`mesh.nt` contains 53 verbatim N-Triples statements for the descriptor and its
preferred native concept. Its sorted statements plus terminal LF have SHA-256
`3a96fde4801dd9b6e4018dc38ff0b0adde0b73972ca26b64828237380670ea3a`.
`mesh_nodes.tsv` is the exact historical transformed target declaration and is
not a new scientific category decision. Test-created gzip files and excerpt
physical lines are deliberately distinguished from the full production files;
their exact consumed hashes and line positions appear in the producer audit.

Tests compare the current transform stage with the same source logic admitting
the previous SITE decision as a counterfactual. This isolates the seven withheld
crosswalks from unrelated shared finalization/category repairs. These bounded
fixtures are not a claim that the complete source or merge was rebuilt.
