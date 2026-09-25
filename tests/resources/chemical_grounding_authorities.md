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
native uppercase-O formula. It does not solve general case-folded formula
index collisions. Native UDP CHEBI:17659 does not justify the historical
`potassium 5-dehydro-D-gluconate` alias; rejecting it does not infer a replacement
salt identity from a generic anion.
