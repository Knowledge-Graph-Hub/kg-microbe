# NEXT_TASKS.md — untracked entries that need a per-file decision

Snapshot of the "needs your call" pile from the branch triage on
`chore/refresh-unified-chemical-mappings` (working-tree state as of
2026-07-02). Each entry is either real work that should be committed
(and to which branch), or scratch that should be gitignored / deleted.

> **Last reconciled: 2026-07-21.** Status: **all items below still PENDING**
> — none of these untracked files were resolved (36 untracked entries remain
> in the worktree). Tracked as issue #579. The 2026-07-20/21 work threads
> (LPSN download+transform+merge, chemical-mapping retraction, kgxval review
> integration, ontology metamodel-edge drop, GO `go.db` rebuild, `ontologies_stubs`
> regen) were all shipped in PRs #596–#603, #605 and are unrelated to this
> cleanup backlog. New deferred follow-ups from that work live as GitHub issues:
> **#599** (harden apply_retractions), **#600** (merge lpsn_api credential
> coupling), **#604** (ontology .owl/.json/.db version alignment).

Legend:
- **commit** — keep and stage on some branch (which one to decide per row)
- **ignore** — add to `.gitignore`, leave on disk
- **delete** — remove from working tree
- **?** — needs inspection before deciding

## New utility modules

Nothing in the branch topic (mappings refresh) references any of these,
so they're either dead scratch or belong to a different feature branch.
Open each and decide.

- [ ] `kg_microbe/utils/biohub_converter.py` — ?
- [ ] `kg_microbe/utils/diagnose_duplicates.py` — ?
- [ ] `kg_microbe/utils/extract_taxon_strain_nodes.py` — ?
- [ ] `kg_microbe/utils/nlp_utils.py` — ?
- [ ] `kg_microbe/utils/parse_taxon_rank.py` — ? (there's also a `.py_bak` sibling → delete the bak regardless)
- [ ] `kg_microbe/utils/transform_utils.py` — ? (name collides with the top-level `transform_utils/` package; check for shadowing bugs)

## Scripts at repo root

Root-level scripts are almost always one-offs. If any are permanent,
move under `kg_microbe/` or `scripts/`.

- [ ] `run.py` — ? (suspicious — `poetry run kg` is the canonical entry point)
- [ ] `analyze_categories.py` — ?
- [ ] `download_mediadive_bulk.py` — likely belongs alongside `download.yaml` MediaDive work; if permanent, move under `kg_microbe/`
- [ ] `convert_merged_to_nt.yaml` — one-off config; if permanent, move under a config dir

## Unknown directories

Peek inside before deciding.

- [ ] `kg_microbe/transform_utils/data/` — ?
- [ ] `kg_microbe/transform_utils/ontology/` — ? (possibly a typo of the existing `ontologies/` package)

## Data / mapping / xref files

- [ ] `kg_microbe/transform_utils/bacdive/metabolite_mapping.json` — ?
- [ ] `kg_microbe/transform_utils/bactotraits/BactoTraits.tsv` — per the `download.yaml` note, BactoTraits V2 is now vendored because the upstream TLS is broken. **This file probably needs to be committed** together with the `download.yaml` change on its own PR.
- [ ] `kg_microbe/transform_utils/ontologies/xrefs/mondo_xrefs.tsv` — ?
- [ ] `kg_microbe/transform_utils/ontologies/xrefs/unipathways_xrefs.tsv` — ?

## Docs

- [ ] `docs/MERGE_CLEANUP.md` — likely real; belongs on a docs / merge branch
- [ ] `docs/metatraits/unmapped_compounds.tsv` — ?
- [ ] `docs/metpo/` — likely belongs with the METPO commits (`b2b6c57f`, `a237751b`) that are currently misfiled on this branch

## Mappings

- [ ] `mappings/mediadive_unmapped_ingredients_to_curate.tsv` — probably **THIS branch** (matches mappings-refresh topic). Confirm and stage.

## Notebooks

Rule of thumb: notebooks with named outputs and a clear analytical
purpose can be committed; anything with `_bak`, `_withoutput`,
`catboost_info/`, or that's obviously scratch should be ignored or
deleted.

- [ ] `notebooks/bacdive-api-summary-table.ipynb` — ?
- [ ] `notebooks/bacdive-process-errors-with-genus.ipynb` — ?
- [ ] `notebooks/bacdive-summary-counts.ipynb` — ?
- [ ] `notebooks/bacdive_mapping_resource.ipynb_bak` — **delete** (`_bak`)
- [ ] `notebooks/bacdive_reformat.ipynb` — ?
- [ ] `notebooks/evaluate_link_pred.ipynb` — ?
- [ ] `notebooks/feba.ipynb_bak` — **delete** (`_bak`)
- [ ] `notebooks/kg_bacdive.ipynb` — ?
- [ ] `notebooks/kg_microbe_embedding.ipynb` — ?
- [ ] `notebooks/kg_microbe_embedding.ipynb_bak` — **delete**
- [ ] `notebooks/kg_microbe_embedding_withoutput.ipynb` — **delete** (output variant)
- [ ] `notebooks/kg_microbe_embedding.html` — **delete** or gitignore (rendered output)
- [ ] `notebooks/kg_microbe_train_taxa_to_media.ipynb` — ?
- [ ] `notebooks/load_feba.ipynb` — ? (duplicate at repo root `load_feba.ipynb` — pick one location)
- [ ] `notebooks/train_taxa_to_media.ipynb` — ?
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
