# Eight inherited MediaDive material alias defects (#1262)

## Evidence and finite scope

The actual finalized MediaDive source at `02f6e128dce6c16a95230266cd9123a69530b9e1`
contains 289 recipe observations assigned to eight unrelated native ChEBI
identities. Every complete `source_record` matches its saved raw recipe object.
These assignments predate the annotation-only #1259 correction; passing that
comparison did not approve their chemical identity.

| Source material | Incorrect target and native identity | Observations |
| --- | --- | ---: |
| SL10 | CHEBI:1387, 3,4-dihydroxyphenylethyleneglycol | 1 |
| Trace vitamins (see Medium No. 197) | CHEBI:1784, biphenyl-4-amine | 21 |
| Mueller-Hinton broth | CHEBI:748, 12alpha-Hydroxyamoorstatin | 1 |
| Difco Marine Broth 2216 | CHEBI:2216, 6-Methylpenicillin | 1 |
| Malted wheat meal | CHEBI:1881, 4-Hydroxypheoxyacetate | 1 |
| K2HSO4 | CHEBI:1895, 4-methylbenzyl alcohol | 1 |
| Leibovitz's L-15 medium | CHEBI:1941, 4-(trimethylammonio)butanoic acid | 3 |
| Selenite-tungstate solution | CHEBI:88, (S)-(-)-citronellol | 260 |

The active unified baseline contains 13 false lexical synonym rows, each with
aggregate ontology/MediaDive/KEGG source tags. Aggregate tags do not establish
native support for each alias. The strict/hydrate source tables retain local
`ingredient:` identifiers, not evidence for these native accessions. The pattern
is consistent with historical first-digit extraction from local IDs, including
the marine-broth product suffix. The current writer's prefix-preserving parser
is not newly accused of that conversion.

The evidence is stronger than a preferred-label disagreement:

- [DSMZ medium 1521](https://www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium1521.pdf)
  uses SL10 as a solution; the [SL-10 recipe in medium 320](https://www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium320.pdf)
  contains multiple trace salts, not the native catechol/tetrol.
- [JCM medium 197](https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=197)
  defines the trace vitamins as a multicomponent preparation, not an aminobiphenyl.
- MediaDive identifies [Mueller-Hinton broth](https://mediadive.dsmz.de/ingredients/748)
  and [marine broth](https://mediadive.dsmz.de/ingredients/1379) as complex
  substances, not the unrelated limonoid or penicillin molecule.
- [JCM medium 730](https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=730)
  names malted wheat meal. [JCM medium 788](https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=788)
  repeats literal K2HSO4. Its unresolved formula is not permission to substitute
  K2HPO4, KHSO4, or another guessed salt, much less methylbenzyl alcohol.
- [JCM medium 930](https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=930)
  names Leibovitz's L-15 medium, a formulation rather than butyrobetaine.
- The saved [selenite-tungstate solution](https://mediadive.dsmz.de/solutions/777)
  and six other source solution records contain selenite, tungstate, alkali and
  water, not citronellol. Their quantities/formulations are not all identical.

Live primary pages corroborate the saved source; they are not claimed to be
hash-pinned downloads. Raw, native and graph witnesses are hash-bound in the
immutable fixture. Ontology declarations for all eight native chemicals remain
valid and must not be globally removed.

## Resolution boundary

Eight anchored target-scoped name exclusions reject only the reviewed false
pairs, including observed punctuation and spacing variants. Existing shared
reader, export and MediaDive unified/legacy/embedded/nested-solution guards
enforce them. Direct native IDs, native names and synonyms remain eligible.
There is no unconditional source-name ban, no invented replacement, and no
new positive entry in `ingredient_name_scopes.tsv`. An independently supported
alternative must be evaluated on its own evidence; it is not rejected merely
because the old target was wrong.

When no supported identity survives, the existing source-local ingredient or
solution ID is retained. The 260 selenite observations include four ingredient
uses and 256 nested solution references: 777 (179), 4172 (72), and 1725, 1915,
2804, 3177, 5543 (one each). Never collapse those seven solution identities
into one ingredient. Quantities, ordinals, qualifiers and full original source
records must survive the actual rebuild.

The reviewed non-lookup catalogue
`mappings/mediadive_material_grounding_review.json` retains all 13 original
SSSOM records, complete columns and original data-row ordinals, tied to baseline
SHA-256 `67c48e1bf6bed1f1fef03a0da1d7d1b56af9fc72374dddd703c222fb36df3cd4`.
Removing an active alias must not erase this historical evidence. Producer
audits distinguish those archived claims from current unified, legacy or
embedded candidates; the catalogue is not an identity lookup input. Current
candidate records are audited only for the rejected name/target pair, not
unrelated local IDs or alternative identities.

## Positive controls and acceptance

The chelator node CHEBI:38161 has five genuine native `has_chemical_role`
assertions in this source and no recipe ingredient assertion. Its broad label
or KEGG xrefs are not grounds to quarantine those roles. CHEBI:27407 Kinetin
and CHEBI:7070 tetramethylammonium chloride are retained positive controls.
Legitimate native role edges belonging to the eight wrongly used chemical IDs
also remain native ontology facts; correcting the ingredient links removes the
inappropriate recipe paths without deleting ontology assertions globally.

`tests/resources/mediadive/material_aliases_1262.json` retains the 289 complete
original observations, all seven nested solution records, native nodes/edges,
all original unified target rows and positive controls. SHA-256:
`e6db6174173a12101875104c33478f1868f4454ddd296db8e46b47ab6119f126`.
Catalogue SHA-256:
`b94ecaa4935082a6ed79faddfa448ed3a1768a858a572bc63306d20f43701e03`.
Counts describe this snapshot, not future allowlists.

Targeted tests, adversarial review, finite full-artifact delta and reader
comparison, second-cycle stability, actual isolated MediaDive replay, full
repository gates and CI are required before landing. All-source transforms
and candidate-merge/model/path acceptance follow separately. At the time of
this evidence record those gates have not completed. The supported MIM table
and immutable release pin remain unchanged. This is not a release approval or
closure of umbrella issues #650 / #286.

## Adversarial audit findings (#1263)

Independent synthetic producer tests found two evidence-completeness gaps in
the initial implementation: policy-covered separator variants such as `SL-10`
could omit archived claims, and current reader-eligible rows with whitespace
around `object_id` could be absent from the audit. Neither test allowed the
incorrect chemical identity through. The original failing review remains
historical evidence, not a passing result for the repaired implementation.

The repair associates each finite disposition only with the selected policy's
target/native-label-matching name patterns that cover its saved source names.
It uses the same policy spelling forms, rejects ambiguous dispositions, and
checks agreement with runtime identity admission. Catalogue and identity policy
are consumed even for an empty cohort. Current candidate target comparison
strips boundary whitespace as the reader does; the full original candidate
record and its raw target spelling remain unchanged in the audit. No new
identity rule, replacement mapping, or expansion of the eight-pair scientific
scope is introduced. Independent re-review and the later acceptance gates
remain separate requirements.
