# METPO proposals: current state

Regenerate the numbers below with:

```bash
poetry run python scripts/diff_metpo_proposals.py            # against METPO_VERSION
poetry run python scripts/diff_metpo_proposals.py --release 2026-06-12
```

The full report lives at [docs/metpo/metpo_proposal_release_diff.md](metpo/metpo_proposal_release_diff.md).
This file explains what the report means; it is not a second copy of it.

## Where the proposal lives

`scripts/extract_metpo_proposals.py` is the source of truth. It generates every
`mappings/metpo_proposal_*.tsv`, and `tests/test_extract_metpo_proposals.py`
fails if a committed artifact drifts from what the generator produces — so the
TSVs are never hand-edited.

Submitted upstream as [berkeleybop/metpo#424](https://github.com/berkeleybop/metpo/issues/424).

## What is outstanding

Everything that has landed upstream now matches the release exactly: 31 of 49
classes and 4 of 9 properties, with zero differences. What remains is what
upstream has not adopted:

- **6 classes** — the environmental-tolerance min/max pairs
  (`METPO:1007022/1007023/1007026/1007027/1007030/1007031`), all HIGH priority.
- **12 classes** — the 2026-08 PREGO cohort, environmental-niche and phenotype
  axes, MEDIUM and LOW priority.
- **5 properties** — including `METPO:2000717` and `METPO:2000719`
  (growth temperature and salinity optimum values), both CRITICAL: the
  MetaTraits transform has nowhere to attach numeric optima without them.

The first and third groups are the subject of
[berkeleybop/metpo#528](https://github.com/berkeleybop/metpo/issues/528), which
argues nine of them cannot be cleanly reused as specified. That is a substantive
objection and is the thing blocking adoption, not a process gap.

## Conventions the release imposes, which the generator now follows

- **Definitions are genus-differentia.** Upstream rewrites `"A phenotypic quality
  describing X"` into `"A phenotype characterized by X"`
  ([metpo#460](https://github.com/berkeleybop/metpo/pull/460)). The generator
  carries the released wording verbatim for every landed term.
- **Phenotype classes are parented at `METPO:1000059`, not the root.** Anything
  proposed under `METPO:1000000` was re-parented on ingest, so `_PHENO_PARENT`
  is `METPO:1000059`.
- **`oboInOwl:hasDbXref` does not survive.** Not a decision about our rows: **no
  term in the 2026-06-12 release carries an xref at all** — 1,619 of 1,619, and
  zero `GO:`/`PATO:` xrefs anywhere in the ontology. The `xrefs` column is kept
  as our own curation record of which GO/PATO term each proposal corresponds to,
  but it will not land, and cross-ontology mappings are moving to SSSOM upstream
  ([metpo#344](https://github.com/berkeleybop/metpo/issues/344)).

## Known gap

7 of the 9 proposed properties still carry `TODO:add_citation` in
`definition_source` — tracked as #750.
