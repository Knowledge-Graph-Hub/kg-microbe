# Bare Potato is not an evidenced extract identity (#1236)

The [official EINECS inventory](https://www.mhsr.sk/uploads/files/Zwx10C5G.pdf)
(PDF page 21, checked 2026-09-29) pairs CAS 93348-51-7 and EC 297-194-4 with
`zemiak, Solanum tuberosum aegrotans, extrakt`. Its described scope is extractives
and physically modified derivatives. Preserve the `aegrotans` qualifier; this
is not a declaration that every potato extract or starting tuber is identical.

The historical nine MediaDive ingredient-1606 observations are retained in
`tests/resources/mediadive/potato_scope.json`, including their exact original
recipe JSON and immutable historical witness/archive hashes. Five say peeled
and cut, one says fresh/washed/peeled/sliced, and three say only Potato. The six
explicit starting-material descriptions do not establish the extract identity;
the three unqualified observations lack the specificity to choose it. Neither
group proves that every eventual prepared extract is chemically different.
All nine observations, including amounts and optional concentration fields,
remain valuable source data and must survive withholding this grounding.

The source recipe JSON contains no CAS property. The imported unified lexical
claim and both legacy MicroMediaParam rows are separate evidence layers. The
fixture preserves the complete unified row and identifies the legacy rows;
the producer audit must preserve full original mapping rows/input identities,
not invent a CAS assertion inside the unchanged raw recipe record. MediaDive's
[ingredient page](https://bacmedia.dsmz.de/ingredients/1606) also cautions that
identifiers are largely automatically matched. Its
[recipe 3653](https://bacmedia.dsmz.de/solutions/3653) boils and strains the starting
material, which does not establish ingredient-to-extract identity by itself.

The finite policy therefore withholds **bare Potato → cas:93348-51-7** through
the existing shared name/target guard. It does not ban the CAS identifier,
reject arbitrary strings containing potato, select a replacement identity, or
approve other extract names. Explicit authority labels and direct registry
queries remain eligible for separately supplied evidence. Potato flour,
starch, and other named preparations remain distinct; none is an inferred
replacement for these records.

The same guard covers the unified reader, strict/hydrate fallback parsing,
embedded CAS-RN aliases, and nested solution-name lookup. With no independent
exact target, MediaDive retains its existing source-local ingredient identity;
no pure compound, botanical taxon, or flour identity is invented. Rebuilding
from a stale synonym or legacy file must not resurrect the held claim.
Candidate quarantine and producer-bound audit retain imported claims separately
from active graph identity. Audit reasons distinguish
`unsupported_material_form_identity` from `insufficient_material_specificity`.

This code change does not replace the pinned supported MIM product, release pin,
or unified artifact. Candidate generation and reviewed paired promotion follow
`docs/MIM_REVIEWED_RELEASE.md`; changing a shared policy can stale consumers and
requires fresh producer/merge admission. The historical nine-record fixture is
not an expected count or release acceptance for a future rebuilt graph.

The primary inventory was read directly, but the fixture is a small cited
transcription, not a retained complete PDF or CAS Registry response. Failed
Common Chemistry/PubChem retrievals supplied no evidence of registry absence.
See [#1236](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1236), linked
to the broader [#286](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/286).
