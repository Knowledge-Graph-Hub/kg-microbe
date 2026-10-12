# Reviewed release inputs

Several transforms apply reviewed policies under `mappings/` that bind the
upstream data they were checked against. Until #1420 some of those bindings were
whole-file digests of files no download could reproduce: JSON converted by
ROBOT, a `mondo.json` an older transform rewrote in place, a locally built
`go.db`, a gunzipped `ncit.db`, and inputs fetched from rolling URLs. A fresh
checkout therefore failed, often hours into a run. This runbook says how each
input is now fetched and bound, and how to stage a raw directory for a rebuild.

## How each input is bound

| Input | How it is fetched | What the policies bind |
| --- | --- | --- |
| `ro.owl`, `pato.owl`, `uberon.owl`, `foodon.owl`, `po.owl`, `upa.owl`, `go.owl`, `envo.json`, `mondo.json` | `kg download -t ontologies`, from URLs that each name one release (`tests/test_reviewed_release_urls.py`) | The file's SHA-256 |
| `ro.json`, `pato.json`, `uberon.json`, `foodon.json`, `upa.json` | Converted from the OWL release by the pinned ROBOT during `kg transform` | The release the JSON declares (`meta.version`), the OWL release file's digest, and a canonical digest of the reviewed content only |
| `go.db` | Built by SemSQL from `go.owl` during `kg transform` | The GO release it records (`owl:versionInfo`), the `go.owl` digest, and the selected statements |
| `mesh2026.nt.gz`, `ncit.db` | `kg download -t stubs`; neither has an immutable URL | The reviewed statements only. Any export or release with them unchanged is accepted, and each run's receipt records the bytes it read (and the NCIT release). |
| Rhea `rhea-directions.tsv`, `rhea.rdf.gz` | `kg download -t rhea` fetches the archived release 142; `stage_snapshot --source-archive` extracts the pair | Both files' digests, which equal the archive members |
| MicrobeDecoder `database.csv` | `kg download -t microbedecoder`, from a commit; extracted on the first run | The file's digest |
| `lpsn_gss.csv` | Manual, account-gated download | The six accepted rows the BacDive join decisions name, each compared in full |
| MicrO import modules | `kg download -t ontologies`, from a commit, into `micro_imports/` | Checked by the `ontologies_stubs` preflight |

Moving any of these to a newer upstream release means re-reviewing every policy
that binds it, then updating the URL, the policies and their tests together.

## The preflight

Before any source runs, `kg transform` asks each selected source for missing
prerequisites. When `ontologies` is selected, that includes every file in the
first row of the table: each must exist in the raw directory and match the
digest every policy that pins it agrees on (`kg_microbe/utils/release_preflight.py`).
Nothing runs until they all match, so a stale download fails in seconds rather
than after NCBITaxon and ChEBI. A message names the file, its digest, the
policies that pin it and the command that fetches it.

A file that does not match is usually one of these:

- **A rolling download from before #1420.** When the download manifest
  (`data/raw/.download_manifest.json`) recorded the old URL, `kg download -t
  ontologies` re-fetches the file from its release URL. A file with no record is
  left alone, so move it aside first.
- **A file rewritten in place.** Older transforms rewrote `mondo.json` after
  dropping deprecated terms. Its recorded URL can be the current one, so
  `kg download` will not replace it. Move the file aside, then run
  `kg download -t ontologies`.
- **A hand-copied or hand-edited file.** Treat it like a rewritten one.

Never edit a policy's digest to match a file on disk: the digest records what
was reviewed.

## External prerequisites

- **ROBOT and Java.** `kg download -t tools` installs the pinned ROBOT; Java
  must be on `PATH`. The `ontologies_stubs` preflight checks both.
- **rdftab and relation-graph.** SemSQL builds (`go.db`, `chebi.db` and others)
  run both from `PATH`, and no preflight checks them. Install rdftab v0.1.1,
  the version SemSQL itself uses, from the
  [rdftab.rs release](https://github.com/ontodev/rdftab.rs/releases/tag/v0.1.1).
  On Apple silicon the `x86_64-apple-darwin` binary runs under Rosetta. The
  repository has no lock file for building it from source, so a source build
  may not reproduce the same databases.

## Staging a raw directory for a rebuild

1. Run `kg download` for the tags you need, and stage the manual inputs: Rhea
   with `stage_snapshot --source-archive` (see the
   [Rhea runbook](../RHEA_DIRECTIONS.md)), and `lpsn_gss.csv` by hand (see
   [Data hosting](../DATA_HOSTING.md)).
2. Run `kg transform -s ontologies` and read the preflight messages before
   anything else runs. Fix each one as above and repeat until there are none.
3. If `ncit.db.gz` or `mesh2026.nt.gz` has moved upstream, the stub sources still
   accept it as long as the reviewed statements are unchanged. If one changed,
   the source fails closed: re-review that policy before changing it.
