# Native authority excerpt for historical mapping repairs

`chemical_grounding_authorities.tsv` is an immutable projection of `id` and
`name`, copied without lexical normalization on 2026-09-25 from the native
namespace rows of these existing transformed authority files:

| Input | SHA-256 |
| --- | --- |
| `data/transformed/ontologies/chebi_nodes.tsv` | `c161f8aea7ffeb1a2557f24100b3b3b67bfd62196d484b33c675921154c8b152` |
| `data/transformed/ontologies_stubs/ncit_nodes.tsv` | `8f288cf5f8b4a91c933de1c7741edede359919162963487c0c8ac6d7e331060c` |

The excerpt supports rejecting the reviewed mistakes, not choosing a replacement
identity for a recipe string. In particular, `Nano` must remain a valid NCIT
label, even though upper-case `NaNO` was propagated as a chemical name.

The 25 rows in `recipe_instruction_names.tsv` are the 15 original CHEBI-target
assertions listed in KG-Microbe #1009 plus ten assertions for those same forms
propagated to non-CHEBI targets. They were reproduced from unified SSSOM SHA-256
`0f8c148fb6f8386daee19b8e3a5af4725d4841b02b9125e64f39497e51ea00c3`.
The targeted policy keeps preparation text in historical quarantine/source
occurrences; it does not treat that text as a global chemical synonym. No
general rule rejects parenthesized names or all names containing preparation
words. CAS-target labels in that fixture document the historical registry
record, not a new exact identity endorsement.

Native ChEBI pages independently inspected for #788:

- https://www.ebi.ac.uk/chebi/CHEBI:16118 — berberine cation.
- https://www.ebi.ac.uk/chebi/CHEBI:31271 — berberine chloride.
- https://www.ebi.ac.uk/chebi/CHEBI:91247 — L-cysteine hydrochloride.
- https://www.ebi.ac.uk/chebi/CHEBI:52259 — QSY9 succinimidyl ester, with
  `has_part` CHEBI:52891 (the cation).

`chemical_grounding_retirements.tsv` separately records obsolete native records,
not labels fabricated for absent current primary nodes. On 2026-09-25 the
read-only `data/raw/chebi.db` (SHA-256
`081d065c12487e567fac48ab8c5ee87cc533b2ac89e22f47c119be4ee37ff0b7`)
supplied their `owl:deprecated`, `IAO:0100001`, and replacement `rdfs:label`
statements. The historical KGM names Soytone, Sulfur (powder), and HEPES buffer
do not describe those replacements. The finite exclusions prevent restoration
of these bad ingredient/identifier pairs; they do not endorse substituting an
ontology replacement for an unrelated recipe chemical.

The current native phosgene record CHEBI:29365 contains `COCl2`, whereas cobalt
dichloride CHEBI:35696 contains `CoCl2`. The finite #1151 guard rejects only the
observed hydrated-cobalt query `CoCl2 x 2 H2O` against phosgene and preserves its
native uppercase-O formula. `chemical_formula_aliases.tsv` records these two
native exact-case aliases from the same fingerprinted ChEBI TSV. Their finite
`case_sensitive_name` query scopes distinguish COCl2 from CoCl2 and reject an
unreviewed spelling such as cocl2; they do not implement general formula parsing.
Observed CoCl2 x 2 H2O, FeCl2 x 6 H2O, Na2HPO4 x 6 H2O, and NiCl2 x 2 H2O
source labels are separately guarded against their anhydrous targets. These
exclusions preserve source ingredients without guessing hydrate replacements.
Native UDP CHEBI:17659 does not justify the historical
`potassium 5-dehydro-D-gluconate` alias; rejecting it does not infer a replacement
salt identity from a generic anion.

For #1153 the same immutable native ChEBI TSV declares CHEBI:8612 as
`psicofuranin`, with synonyms `6-amino-9-D-psicofuranosylpurine`,
`Angustmycin C`, `Psicofuranin`, and `psicofuranine`. CHEBI:223718 is
`Rubradirin B`; its native aliases do not include the generic `rubradirin`.
These declarations are copied as labels in `chemical_grounding_authorities.tsv`.
The specific names remain valid: the finite policy rejects only unqualified
`angustmycin` / `rubradirin` and their observed `produces:` source phrases.

Upstream reviewed export at immutable commit
`a8b26f007cdf5bdc7529ab13888d611f359e6aad`, manifest SHA-256
`c37e075743b52f614a78c2ddd7ec47e1e8ea35b53e0a66c5886007947105a64b`,
independently withholds both generic-to-specific assertions in its
`mapping-dispositions.tsv`:

- Source position 386: `MIM:Angustmycin` exact CHEBI:8612, row SHA-256
  `e7aaa856c1ae738835d158e22fc5b104fd9664c9210a6fb0dc2a1bcafff8a371`.
  Generic Angustmycin does not distinguish A/decoyinine from C/psicofuranin.
- Source position 2471: `MIM:Rubradirin` exact CHEBI:223718, row SHA-256
  `3ae670058aefdf10ec85cae6705cfbd6bfc20d3bffddbddd9b16a07363a42ded`.
  The source record does not justify selecting Rubradirin B.

These withheld records do not prove a universal scientific inequality. The
consumer preserves the original generic observations using their historical
`kgmicrobe.compound:` IDs rather than asserting either external identity.

The complete original #788 fallback review (#1155) additionally reproduced
generic `D-Glucose` mapped to CHEBI:42758 (`aldehydo-D-glucose`, specifically
the open-chain form); `Sodium citrate` / `Sodiumcitrate` mapped to CHEBI:32142
(`sodium citrate dihydrate`); and `0.2% Thiamine pyrophosphate` mapped to
CHEBI:9532 (`thiamine(1+) diphosphate`, a pure chemical rather than a preparation).
Their native labels are projected from the same fingerprinted ChEBI TSV above.
The finite exclusions leave explicit linear glucose, citrate dihydrate, and
charged diphosphate names usable. No replacement chemical is inferred.

The same native ChEBI table also lists `D-Glucose` as an alias of CHEBI:4167,
`D-glucopyranose`. For the context-free ingredient query the consumer admits
neither that ring form nor open-chain CHEBI:42758 merely by alias order; native
generic CHEBI:17634 remains usable when independently declared.

The exact context-free ingredient query `thiamine pyrophosphate` occurs as a
native alias of three distinct current records: CHEBI:18290
`thiamine(1+) diphosphate chloride` (CAS 154-87-0), CHEBI:45931
`thiamine(1+) diphosphate(1-)` (CAS 136-09-4), and CHEBI:9532
`thiamine(1+) diphosphate` (CAS 136-08-3). Its finite admission hold covers all
three to prevent order-dependent salt/charge selection. This does not declare
the native synonyms scientifically false, and explicit native names still
resolve. The unrelated native peptide abbreviation `TPP` and literal unmatched
`Co-carboxylase` are outside this hold. No supported MIM assertion was changed.
