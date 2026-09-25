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
