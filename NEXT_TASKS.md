# NEXT_TASKS.md — untracked entries that need a per-file decision

Snapshot of the "needs your call" pile from the branch triage on
`chore/refresh-unified-chemical-mappings` (working-tree state as of
2026-07-02). Each entry is either real work that should be committed
(and to which branch), or scratch that should be gitignored / deleted.

> **Last reconciled: 2026-08-12.** Status: **28 of 36 resolved** — the
> 2026-07-21 note claiming "all items still PENDING" is no longer true. 17 entries
> are now committed, 11 are gone from the worktree, and **8 remain**, of which 4
> are `_bak` files already marked *delete*. Resolved rows are ticked below with
> how they resolved. Still tracked as issue #579.
>
> Reconciled by checking each path against `git ls-files` and the working tree,
> not by reading the previous note.

Legend:
- **commit** — keep and stage on some branch (which one to decide per row)
- **ignore** — add to `.gitignore`, leave on disk
- **delete** — remove from working tree
- **?** — needs inspection before deciding

## New utility modules

Nothing in the branch topic (mappings refresh) references any of these,
so they're either dead scratch or belong to a different feature branch.
Open each and decide.

- [x] `kg_microbe/utils/biohub_converter.py` — ?  ← **gone from the worktree**
- [x] `kg_microbe/utils/diagnose_duplicates.py` — ?  ← **gone from the worktree**
- [x] `kg_microbe/utils/extract_taxon_strain_nodes.py` — ?  ← **gone from the worktree**
- [x] `kg_microbe/utils/nlp_utils.py` — ?  ← **gone from the worktree**
- [x] `kg_microbe/utils/parse_taxon_rank.py` — ? (there's also a `.py_bak` sibling → delete the bak regardless)  ← **committed**
- [x] `kg_microbe/utils/transform_utils.py` — ? (name collides with the top-level `transform_utils/` package; check for shadowing bugs)  ← **gone from the worktree**

## Scripts at repo root

Root-level scripts are almost always one-offs. If any are permanent,
move under `kg_microbe/` or `scripts/`.

- [x] `run.py` — ? (suspicious — `poetry run kg` is the canonical entry point)  ← **gone from the worktree**
- [x] `analyze_categories.py` — ?  ← **gone from the worktree**
- [x] `download_mediadive_bulk.py` — likely belongs alongside `download.yaml` MediaDive work; if permanent, move under `kg_microbe/`  ← **gone from the worktree**
- [x] `convert_merged_to_nt.yaml` — one-off config; if permanent, move under a config dir  ← **gone from the worktree**

## Unknown directories

Peek inside before deciding.

- [ ] `kg_microbe/transform_utils/data/` — ?
- [x] `kg_microbe/transform_utils/ontology/` — ? (possibly a typo of the existing `ontologies/` package)  ← **gone from the worktree**

## Data / mapping / xref files

- [x] `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` — ?  ← **committed**
- [x] `kg_microbe/transform_utils/bactotraits/BactoTraits.tsv` — per the `download.yaml` note, BactoTraits V2 is now vendored because the upstream TLS is broken. **This file probably needs to be committed** together with the `download.yaml` change on its own PR.  ← **gone from the worktree**
- [x] `kg_microbe/transform_utils/ontologies/xrefs/mondo_xrefs.tsv` — ?  ← **committed**
- [x] `kg_microbe/transform_utils/ontologies/xrefs/unipathways_xrefs.tsv` — ?  ← **committed**

## Docs

- [x] `docs/MERGE_CLEANUP.md` — likely real; belongs on a docs / merge branch  ← **committed**
- [x] `docs/metatraits/unmapped_compounds.tsv` — ?  ← **committed**
- [ ] `docs/metpo/` — likely belongs with the METPO commits (`b2b6c57f`, `a237751b`) that are currently misfiled on this branch

## Mappings

- [x] `mappings/mediadive_unmapped_ingredients_to_curate.tsv` — probably **THIS branch** (matches mappings-refresh topic). Confirm and stage.  ← **committed**

## Notebooks

Rule of thumb: notebooks with named outputs and a clear analytical
purpose can be committed; anything with `_bak`, `_withoutput`,
`catboost_info/`, or that's obviously scratch should be ignored or
deleted.

- [x] `notebooks/bacdive-api-summary-table.ipynb` — ?  ← **committed**
- [x] `notebooks/bacdive-process-errors-with-genus.ipynb` — ?  ← **committed**
- [x] `notebooks/bacdive-summary-counts.ipynb` — ?  ← **committed**
- [ ] `notebooks/bacdive_mapping_resource.ipynb_bak` — **delete** (`_bak`)
- [ ] `notebooks/bacdive_reformat.ipynb` — ?
- [x] `notebooks/evaluate_link_pred.ipynb` — ?  ← **committed**
- [ ] `notebooks/feba.ipynb_bak` — **delete** (`_bak`)
- [x] `notebooks/kg_bacdive.ipynb` — ?  ← **committed**
- [x] `notebooks/kg_microbe_embedding.ipynb` — ?  ← **committed**
- [ ] `notebooks/kg_microbe_embedding.ipynb_bak` — **delete**
- [x] `notebooks/kg_microbe_embedding_withoutput.ipynb` — **delete** (output variant)  ← **committed**
- [ ] `notebooks/kg_microbe_embedding.html` — **delete** or gitignore (rendered output)
- [x] `notebooks/kg_microbe_train_taxa_to_media.ipynb` — ?  ← **committed**
- [x] `notebooks/load_feba.ipynb` — ? (duplicate at repo root `load_feba.ipynb` — pick one location)  ← **committed**
- [x] `notebooks/train_taxa_to_media.ipynb` — ?  ← **committed**
- [ ] `notebooks/train_taxa_to_media.ipynb_bak` — **delete**

---

## Questions to ask yourself for the ambiguous rows

For each `?` above:
1. Is anything in the repo already importing/referencing this file?
   `grep -r 'basename' .` — if no hits, it's not wired in.
2. When was it last touched? `git log --all --follow -- <path>` (returns
   nothing if never committed anywhere).
3. Is there a matching PR or issue you remember opening?
4. Would losing it be a problem tomorrow? If not, delete.
