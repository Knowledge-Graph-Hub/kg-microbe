# MediaDive Transform

The MediaDive transform converts cultivation-media records from
[MediaDive](https://mediadive.dsmz.de/) into source nodes and edges. Production
transforms require downloaded, admitted JSON inputs; they do not reconstruct
missing records from live API calls or old YAML/SQLite caches.

## Download and transform

```bash
# Download the MediaDive list and its associated bulk data.
poetry run kg download -t mediadive

# Wait for the download to finish before starting the transform.
poetry run kg transform -s mediadive
```

The required inputs under the selected raw directory are:

- `mediadive.json`, or an explicitly selected media-list file;
- `mediadive/media_detailed.json`;
- `mediadive/media_strains.json`;
- `mediadive/solutions.json`;
- `mediadive/compounds.json`.

The selected media list and four bulk files are retained as consumed-input
evidence. Missing, malformed or changed inputs fail closed. The constructor and
finalization bind the selected raw paths and actual file bytes, rather than
silently using files from another raw directory. BacDive taxon lookup and native
ontology prerequisites must also be available.

Before graph emission, the transform checks requested medium details and
first-level solution records. A missing detail is an error; a present public
medium whose metadata contains no `solutions` key is a different case and is
not filled from a cache. It remains a medium declaration without invented
recipe assertions. Recipe occurrences retain their source order, multiplicity,
quantity fields and source evidence.

## Refreshing downloaded data

An ordinary download may skip bulk retrieval when the four files already exist
and pass its size check. That check does not establish complete medium coverage.
To explicitly refresh the selected source, use the public CLI's `-i` flag:

```bash
poetry run kg download -t mediadive -i
```

`-i` is the download force-refresh option; `--ignore-cache` is not a public
option alias. Downloading is a separate operation with its own HTTP cache and
refresh policy. A forced download refreshes that downloader cache. It can take
substantial time and changes the raw-data epoch: do not run it concurrently with
a transform or its admission checks. Preserve any input epoch needed for
comparison before refreshing, wait for completion, and use a new transform
instance afterward. Do not delete historical caches to repair an active graph.

`KG_MEDIADIVE_ALLOW_STALE_CACHE` is retired and cannot bypass required bulk
evidence. There is no API-only or cache-only production transform mode.

## Explicit API helpers

Deliberate nonbulk helper calls fetch through a lazy, transform-owned plain
`requests.Session`, with no persistent response caching or global requests
patch. Medium, medium-strain and solution lookups therefore request fresh
responses on repeated calls. These diagnostic calls do not substitute for
admitted production inputs or authorize a graph build.

The historical `download_yaml_and_get_json(url, target_dir)` and
`get_json_object(fn, url_extension, target_dir)` signatures remain callable.
Their legacy YAML path arguments are ignored: no old YAML is read, no YAML
file/directory is created, and no persistent cache is updated. Existing
`mediadive_cache.sqlite`, `mediadive_transform_cache.sqlite` and YAML files
remain untouched; they are not adopted, moved, overwritten or deleted.

The API helper retains its timeout/retry behavior and returns the response's
`data` value. Exhausted request failures retain the existing `{}` result rather
than returning stale data. Failed sessions are closed; unexpected errors and
interruptions propagate after cleanup. Successful explicit helper users should
call `_close_http()` when done. `run()` always closes its owned session in a
`finally` block, although normal production lookups use only bulk JSONs.

## Ingredient identities

Name resolution tries the reviewed unified mapping first, then the guarded
legacy MicroMediaParam hydrate/strict mappings. Embedded compound identifiers
must pass the same ingredient-identity checks. A hydrated ingredient is not
collapsed to its anhydrous chemical merely because the names are related;
without an admitted identity, the source-local `mediadive.ingredient:` identifier
is retained.

Explicit nested `solution_id` references always retain their native
`mediadive.solution:` identity, before every lexical mapping route (#1319).
A stock solution is not the chemical whose name resembles its label. Present
child records retain their source-owned mixture declarations; a child absent
from the selected export retains its native identifier and literal name as an
unresolved `biolink:NamedThing`. No composition, external identity, or online
replacement is invented. Repeated references, including different amounts,
remain distinct source occurrences.

Two finite reviewed material cohorts are intercepted before unified, legacy,
and embedded candidates: the five native compound-471 Oatmeal observations
(#1317) and the compound-672 Substrate observation (#1318). They remain
`mediadive.ingredient:471` and `mediadive.ingredient:672`, respectively. The
native product and preparation evidence does not establish NCIT's colloidal
Oatmeal Powder identity or one specific substrate material. These decisions
do not globally disable NCIT classes or reinterpret other ingredient records.
New or changed occurrences of those reviewed IDs require renewed evidence
review; label similarity alone does not extend the finite policy.

Every selected recipe observation retains its complete native JSON record,
source coordinate, quantities and qualifiers. Four mandatory sidecars preserve
the nested-reference, missing-child, Oatmeal and Substrate dispositions:

- `mediadive_nested_solution_identity.tsv`;
- `mediadive_missing_solution_references.tsv`;
- `mediadive_oatmeal_identity.tsv`;
- `mediadive_substrate_identity.tsv`.

The version-2 native-input contract binds those sidecars to actual immutable
raw reads and code-pinned policy/evidence. Source finalization and public
admission independently reconstruct their complete contents; changing only
outer file hashes cannot hide partial audit loss. A zero-cohort source still
emits honest header-only sidecars. Fresh-instance checkpoint reuse re-reads
recorded inputs and compares the exact native contract before accepting the
existing graph; it does not run a new transformation or replace missing
evidence. This adds source-validation work, not post-merge graph edits.

## Tests and maintenance

Keep bulk missing-record failures, metadata-only media, source admission and
recipe-occurrence preservation covered. Explicit-helper tests use immutable
offline fixtures and mocked responses, including contradictory old YAML, old
SQLite files, repeated changed responses, retry errors and session closure.
The #624 invariant remains: constructing or using this transform must never
replace `requests.Session` process-wide.

The separate bulk downloader's caching and `-i` behavior are tested independently;
retiring transform caches does not remove downloader caching. No current media
count, network timing, or cache-hit estimate is an acceptance criterion.

## References

- [MediaDive database](https://mediadive.dsmz.de/)
- [MediaDive API](https://mediadive.dsmz.de/rest)
- [DSMZ](https://www.dsmz.de/)
