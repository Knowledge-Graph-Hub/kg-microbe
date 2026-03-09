# Metatraits Unmapped Traits

This directory contains a curated list of unique unmapped relationship types from the metatraits transform, as described in [GitHub Issue #493](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/493).

## Source

- **unmapped_traits.tsv** — traits that could not be mapped to ontology terms
- **unresolved_taxa.tsv** — taxa that could not be resolved
- **Location**: `data/transformed/metatraits/` (created when running the metatraits transform)

## Downloading Data Files

The large TSV files (`unmapped_traits.tsv`, `unresolved_taxa.tsv`, `edges.tsv`, `nodes.tsv`) are not stored in version control due to their size.

To download these files:

1. Visit the Google Drive folder: https://drive.google.com/drive/folders/1oOqxKWnpue15QHvI3Viqk7mPag7E4jHY
2. Download the required files to `data/transformed/metatraits/`

**Note**: This Google Drive folder is currently not world-writable. If you need access or have permission issues, please contact Anthea at antheaguo@berkeley.edu.

## Regeneration (Optional)

If you need to regenerate `unmapped_traits_unique.tsv` from the source data:

```bash
cd data/transformed/metatraits/
cut -f1 unmapped_traits.tsv | sort | uniq > unmapped_traits_unique.tsv
cut -f1 -d ':' unmapped_traits_unique.tsv | sort | uniq
```

The second command outputs the unique relationship types (one per line). Save that output to `docs/metatraits/unmapped_traits_unique.tsv`.

## METPO Skill

The `.cursor/skills/metpo-ontology/` skill helps ensure metatraits output follows KGX format and METPO semantics without adding extra terms. Use it when working with unmapped traits or trait ontology mapping.
