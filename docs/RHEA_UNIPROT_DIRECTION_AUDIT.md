# Direction-aware local Rhea-UniProt reader

This small extraction from `uniprot&metanetx` preserves the original reaction
member rather than copying each protein mapping onto its master reaction.
It is an **offline source-association audit**, not a new production transform.

```bash
poetry run python -m scripts.adhoc.audit_rhea_uniprot_directions \
  --mapping data/reviewed/rhea2uniprot.tsv \
  --mapping-sha256 'REPLACE_WITH_REVIEWED_SHA256' \
  --directions data/raw/rhea/rhea-directions.tsv \
  --release-policy mappings/rhea_release.json \
  --output data/reports/rhea-uniprot-direction-audit
```

Select the mapping and expected byte hash deliberately. The existing native
Rhea policy pins **only RDF and directions**, not this auxiliary protein mapping.
A cache directory named `142` is not release provenance. Passing these checks
does not make an auxiliary mapping an approved same-release dataset.

The mapping must have exactly these four tab-delimited columns, in this order:
`RHEA_ID`, `DIRECTION`, `MASTER_ID`, `ID`. Headerless legacy fixtures are rejected;
the first association is never silently consumed as a header. Reaction numbers
must be canonical positive ASCII integers. Directions must be `UN`, `LR`, `RL`,
or `BI`. Protein identifiers must be single uppercase ASCII alphanumeric tokens,
optionally ending in a positive numeric hyphen suffix; whitespace, lists and
empty values are rejected. This lexical check is **not** UniProt accession or
isoform existence validation. Original tokens are retained without case changes.

The reader reuses the current native `load_reaction_families` contract. The
chosen directions file must match the selected policy's byte size and SHA-256.
Each association's actual reaction, direction and master must then match one
unambiguous family. Direction is not guessed from numerical ID offsets.
`UN` remains unspecified, distinct from bidirectional `BI`.

`associations.tsv` retains one row per source observation, including duplicates,
the exact original four cells as JSON, source line, canonical reaction CURIE,
direction, master, and the matching directions-table row/line as evidence.
No extra master association or unconditional catalytic edge is emitted.
`manifest.json` records selected input hashes, row counts and limitations.

The mapping is streamed. Memory holds the smaller directions-family index and
one protein-mapping row, not the complete mapping. Reports are staged in a
sibling temporary directory and published only after successful EOF and
input-stability checks. Existing output paths, including symlinks, are never
overwritten. Inputs and KG files are not edited. No network or cache discovery
occurs, and no generated report belongs in Git.

## Still required before production integration

Review and pin the auxiliary mapping's actual release provenance; validate its
coherence with the full native RDF snapshot; define protein/isoform and reference
proteome or organism scope; choose an evidence-backed KG predicate and complete
source-finalization contract. This reader does not verify reaction statuses,
participants, flux, organism-specific capability, or source coverage, and it
does not use MetaNetX identifiers as chemical or reaction identity replacements.
