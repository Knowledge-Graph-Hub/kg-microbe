# MediaDive targeted retry for #1734 — 2026-11-05

Historical retry checkpoint: this report and its blocked receipt are preserved.
The subsequent [resolution report](MEDIADIVE_RESOLUTION_1734_20261105.md) records
the new production outcome contract and qualified source admission.

The targeted production retry recovered **zero associations**. All 632 strain
endpoints remain unresolved: **583 final documented HTTP 404 responses and 49
final connection errors**. Complete association admission remains false; dependent
transforms and the final graph merge remain held by
[#1734](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1734).
This work updates [PR #1750](https://github.com/Knowledge-Graph-Hub/kg-microbe/pull/1750)
in the existing isolated M5 worktree. The old backlog goal remains paused.

## Official semantics and failed identifiers

The [official API reference](https://mediadive.dsmz.de/doc/index.html) describes
`medium-strains/{id}` DataNotFound as a missing medium or unavailable composition.
That ambiguous error does not establish an empty association list or biological
absence. The [medium 32 page](https://mediadive.dsmz.de/medium/32) contains a recipe
and composition, but its lack of displayed strains does not turn an API error
into a successful empty response. The [builder manual](https://mediadive.dsmz.de/docs/medium-builder)
also explains that submitted recipes are not linked to the entered strain data.

The catalogue contains 1,910 DSMZ, 1,313 JCM, 110 CCAP and 11 public media. The
unresolved groups contain 215 numeric/suffixed, 359 J-prefixed, 47 C-prefixed and
11 P-prefixed identifiers. The retry preserved every identifier literally.
All 632 original histories contained HTTP 404, including the 31 whose final
attempt was a connection error. There was no purely transient-only cohort.

The documented inverse strain route can provide positive associations but lacks
a verified complete strain enumeration. The official SPARQL service was identified;
its association coverage and freshness were not established. No alternate bulk
crawl or completeness claim was substituted for the reviewed REST contract.
Official fetches and their identities are retained in
[the semantics review](reviews/mediadive-retry-1734-20261105/official-semantics.json).

## Production execution and result

The saved [retry helper](../scripts/adhoc/kgm_mediadive_retry_20261105.py) derives
exactly the 632 unresolved endpoints from the preserved full-run ledger and cache.
It uses the existing production request, retry and SQLite functions with five
workers, three attempts and a two-second retry delay. Selected targets must be
absent from the cache; prior successes are preserved and are never refetched or
substituted as failed-target responses.

Medium **1366** was retried first through the saved launcher, isolated interpreter,
actual production environment and `data/raw/mediadive` output path. All three
fresh attempts returned the exact documented 404 body. Retained bytes, persisted
cache and output checks verified the retry mechanics. The canary recorded
`verified_unknown`, zero recovered endpoints and admission false. Only after that
verification did the same process retry the remaining 631 targets.

The run completed in **681.589 seconds**, making exactly **1,896** attempts:
1,773 HTTP 404 responses and 123 connection errors. Every received body had the
same documented error identity, and every target returned that 404 at least once.
Connection-error logs report the remote end closing the connection without a
response. There were no fresh valid nonempty or empty lists.

| Previous final outcome | New final 404 / unknown | New final transport error |
| --- | ---: | ---: |
| HTTP 404 (601 endpoints) | 554 | 47 |
| Connection error (31 endpoints) | 29 | 2 |
| Total (632 endpoints) | 583 | 49 |

Combined validated coverage remains **6,056 of 6,688 endpoints**: 3,344 medium
details and 2,712 nonempty strain responses. A valid HTTP 200 list with body status
200 and count equal to its length would be accepted, including an explicit empty
list. Unknown 404s, invalid payloads and transport failures remain distinct and
unresolved. No negative-growth or no-association statement is inferred.

The retained [final receipt](reviews/mediadive-retry-1734-20261105/live/receipt.json)
records `status: blocked` and `association_admission: false`; launcher exit **2**
is the expected unresolved-source hold, not a hidden integrity failure. Receipt
SHA-256: `5050778364c925cedec323b78c9ef80787a9f01405ed42cf92c828be389da0c9`.

## Preservation, controls and review

Before retrying, independent copies preserved the raw artifacts, SQLite database
and sidecars, previous failure receipt, full ledger and selected catalogue.
The helper binds those originals plus 51 protected ontology and review artifacts.
The final checks require all 6,056 original serialized cache entries and their
request keys to remain unchanged, forbid redirect entries, and require cache
coverage to equal the exact accepted response set. Both active and retained final
generations are reopened before admission is assigned.

All four active JSON files and the original download log remained byte-identical.
The before/after standalone SQLite snapshots also have the same hash. Prior raw
artifacts, the previous failure ledger and ontology evidence remain retained.
The launcher verified eight loaded KG module origins in the owned worktree;
the shared Poetry environment was not changed. Reviewed pins and graph scope
remain unchanged, and no completion digest was restamped.

The [independent post-run audit](reviews/mediadive-retry-1734-20261105/post-run/audit.json)
passed all **56 checks**, independently reconstructing the exact endpoint partition
and validating 1,904 recorded input identities. It confirmed preservation of all
18 original records and all 51 protected artifacts. This integrity result does
not change the blocked association status.

Two independent read-only code reviews found no remaining blocking admission or
wrong-target coverage defect in helper SHA-256
`c4ef41f2aabb847404249f59dfc4be39f2fa4f58ba7a03af4dc8a05bf8908a9c`.
The [saved code review](reviews/mediadive-retry-1734-20261105/independent-code-review.json)
binds the exact implementation and test identities; it is not source admission.
The [second review](reviews/mediadive-retry-1734-20261105/independent-admission-code-review.json)
records the pre-live admission review separately and states when its written
record was created.

| Finding | Disposition |
| --- | --- |
| [#1751](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1751): generic missing/error versus empty contract | Follow-up. The retry helper enforces the distinction; the general downloader and consumer contract is not changed here. |
| [#1752](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1752): contradictory or malformed response envelopes | Fixed in the retry helper. Strict JSON, status/count/list/native-ID checks and independent raw-body classification prevent false empty success. |
| [#1753](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1753): cache identity and final coverage gaps | Fixed in the retry helper. Exact blob/key preservation, fresh-response union and final active/retained cache checks are required. |
| [#1754](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1754): interrupted-generation recovery | Follow-up. No automatic resume or atomic multi-file transaction is claimed. Failed or incomplete verification cannot grant admission; a changed baseline is refused. |
| [#1755](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1755): catalogue-order validation | Fixed. The initial read-only plan exposed SQLite iteration order changing first-occurrence compound selection. Validation now reconstructs original catalogue order; production compound bytes were not changed. |
| [#1756](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1756): missing nested-test docstrings | Fixed with documentation-only additions; executable AST equality is checked. The initial cheap gate is retained and did not start the full suite. |

## Validation and retained evidence

Initial focused production/refresh/retry checks passed **80 tests, 4 skipped**.
After the final cache-boundary and catalogue-order repairs, all **29 retry tests**
passed. They use immutable synthetic fixtures and real production request/cache
code with only transport replaced. Controls cover explicit empty success,
unknown/transport separation, forbidden requests, cache and body mutation,
interruption, final receipt failure and order-sensitive extraction.

The corrected read-only plan passed through the actual saved launcher. Required
`poetry run tox -e format,codespell-write` preparation passed without changing
reviewed code bytes. The first final gate on `ff11e479` passed lock/config,
formatting, lint and spelling, then stopped before the full suite for seven missing
nested-test docstrings (#1756). The added docstrings do not change the executable
AST; the production helper and all live-run evidence retain their original bytes.
The repaired clean candidate is validated once through
`poetry run python scripts/run_pr_gates.py mediadive-retry-1734-20261105-r2`; its actual
result and candidate SHA are recorded in the PR after execution. No separate full
pytest run is used, and earlier evidence is not relabeled for this candidate.

Compact exact copies and their manifest are in
[the evidence packet](reviews/mediadive-retry-1734-20261105/README.md).
Full ledgers, all bodies, cache/JSON generations, official fetches and run logs stay
under `data/rebuild-evidence/20261105/mediadive-retry-1734/`, with launcher evidence
under `data/rebuild-evidence/20261105/stages/mediadive-retry-1734-*`.
Historical pre-run proposals remain historical: the private-cache suggestion and
inherited loose validators were superseded by the approved production path and
retry-local strict checks.

The remaining blocker requires reviewable successful upstream associations or a
separately evidenced complete source contract. Reclassifying the current 404s as
empty, dropping these media or accepting partial coverage would waive the current
admission requirement. No such change, GitHub merge or release publication was
performed.
