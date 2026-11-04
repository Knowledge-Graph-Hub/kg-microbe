# Repository instructions

KG-Microbe is a Python 3.10–3.12 Poetry project. Its pipeline is
`download.yaml -> data/raw -> transforms -> data/transformed -> merge.yaml ->
data/merged/merged-kg.tar.gz`.

## Before handing off a change

Follow [the testing policy](docs/TESTING.md). While editing, run affected tests,
downstream contract tests and previous failures; a full suite is not required
for every commit. Before final PR validation, prepare formatting and spelling:

```bash
poetry run tox -e format,codespell-write
```

Review and commit any intended fixes, then validate the clean tracked candidate:

```bash
poetry run python scripts/run_pr_gates.py <label>
```

The runner checks lock/config and code quality before running the full test suite
once, with duration reporting. Do not add a separate full `pytest` run. Default
tox checks do not rewrite source files. Preserve unrelated work and never discard
all diffs to obtain a clean candidate.

Unit tests are offline and hermetic. Add immutable fixtures under
`tests/resources`, write output under `tmp_path`, and mark deliberate
live-service tests `integration`.

## Repository invariants

- Keep CLI-only imports local to their command; basic help must work offline.
- Use the local pinned Biolink schema and predicate map in `data/raw` for
  KGX/BMT. Do not rely on BMT's remote default.
- `merge.yaml` is canonical. Edit variant deltas in
  `config/merge_variants.yaml`, then regenerate variants with
  `python scripts/generate_merge_configs.py`.
- Use constants from `kg_microbe/transform_utils/constants.py` for KGX columns,
  predicates, categories, and source names.
- Edge output includes `subject`, `predicate`, `object`, `relation`,
  `primary_knowledge_source`, `knowledge_level`, and `agent_type`.
- A named strain/isolate under an NCBITaxon uses `biolink:subclass_of` and is
  typed `biolink:OrganismTaxon` (the repository convention documented in #834).
- Stream graph-scale files. Never load complete merged TSVs into Pandas.
- Fingerprint derived-database inputs and build replacements atomically.
- Let ontology infrastructure failures abort; do not absorb them in broad
  per-record exception handling or resolve adapters inside pool workers.
- Generated inputs and outputs belong under `data/`; curated mappings belong
  under `mappings/`.
- Keep credentials in environment variables only. Never rewrite Git remotes or
  create token files.
- Preserve unrelated user changes and avoid broad cleanup globs.

Configuration and warnings live in [.env.example](.env.example). Claude-specific
orientation and runbook links live in [CLAUDE.md](CLAUDE.md).
