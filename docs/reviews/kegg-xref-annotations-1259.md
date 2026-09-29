# KEGG compound annotation syntax (#1259)

The shared chemical reader now emits `kegg.compound:Cnnnnn` instead of the exact
historical `kegg.compound:cpd:Cnnnnn` spelling in node xref annotations. The rule
requires uppercase `C` and exactly five ASCII digits. It deduplicates and sorts
emitted xrefs, including optional ingredient-bundle enrichment. Other KEGG
subspaces, identifiers and malformed forms are unchanged. KEGG documents `cpd`
as the compound database abbreviation and `C` plus five digits as the entry
format. [Official KEGG API manual](https://www.kegg.jp/kegg/rest/keggapi.html).

This is an annotation-only repair. Original unified SSSOM rows, their provenance
and multiplicity, literal identity lookup keys, query behavior, supported MIM
export and immutable pin are unchanged. Canonical and historical alias queries
can therefore still have different historical targets; this change neither
endorses those equivalences nor resolves their scientific conflicts.

The accepted unified artifact with SHA-256
`67c48e1bf6bed1f1fef03a0da1d7d1b56af9fc72374dddd703c222fb36df3cd4`
contains 15,370 affected rows. Of these, 15,355 have exact full-row canonical
counterparts after subject normalization, while 15 do not. Blind normalization
before lookup indexing would change five canonical choices; routing aliases
through canonical choices would change 35 historical alias-query choices and
alias-only fallback would newly resolve two canonical keys. None of those
lookup changes is part of this fix.

The current native ChEBI JSON and node TSV have no such double-prefixed compound
xrefs; each has 17,446 canonical compound xref values. The primary-mapping
importer already removes the `cpd:` abbreviation before prefixing new entries.
The malformed retained rows can be reproduced by historical seed paths; no
exporter or physical SSSOM cleanup is claimed here. Such cleanup needs its own
reviewed, stable identity-precedence contract, because existing exporters sort
by target and simple row relocation cannot preserve canonical precedence.

The full original-row inventory, counterpart ordinals, five canonical conflicts,
35 alias-query differences and native-byte evidence are retained under
`data/issue1224-quarantine-20260929.xjuS9H/issue1259-diagnosis.7T9Jn8/`.
Hermetic tests cover conflicting rows in either order, reloads, alias-only
unresolved canonical queries, weak-relation exclusion and actual MediaDive
producer enrichment through unified, legacy and embedded identity routes.
The chemical-mapping skill and reviewed-MIM runbook governed this bounded scope;
no MIM regeneration or mapping promotion is required for this code change.
