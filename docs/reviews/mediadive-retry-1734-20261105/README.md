# MediaDive #1734 retry evidence

These are exact copies of selected evidence from the existing M5 run. The
[copy manifest](copy-manifest.json) maps each copy to its retained original path,
size and SHA-256. The full evidence remains under
`data/rebuild-evidence/20261105/mediadive-retry-1734/`; no original artifact was
rewritten to produce this packet.

Read the [task report](../../MEDIADIVE_RETRY_1734_20261105.md),
[final blocked receipt](live/receipt.json),
[independent post-run audit](post-run/audit.json), and
[independent code review](independent-code-review.json).
The post-run audit passed all 56 integrity/coverage checks while source admission
remained false. Zero endpoints recovered: 583 final documented 404s and 49 final
connection errors still block complete coverage.

The original failed full-run receipt, baseline audit/cohorts, preservation
manifest and official semantics review retain their original execution epochs.
The first read-only plan failure and corrected result are both preserved. Focused
logs describe their actual code epoch; the final committed candidate gate is
recorded separately in the PR and `data/validation/pr-gates/`.

The canary body files are exact official responses, not synthetic empty lists.
The separate test fixture is explicitly synthetic. No current or historical 404
is relabeled as valid-empty success. A verified unknown canary established retry
mechanics only; the final source receipt records the incomplete coverage hold.

The copied post-run audit manifest binds the full local audit bundle, including
large per-endpoint/cache/input identity tables retained locally. Only its summary,
preservation review, manifest and read-only audit driver are copied here. Their
absence from this compact packet is not absence from the run evidence. All fresh
bodies, full ledgers, active/preserved SQLite and JSON generations, and official
fetches remain local and are identified by the retained audit tables.

Earlier private-generation and inherited-validator proposals were superseded by
the approved actual production path and strict retry-local validators. The
interruption recovery limitation is tracked in #1754; no automatic recovery or
atomic multi-file transaction is asserted. The broader downloader/consumer
outcome contract remains #1751. No graph or release admission follows from this
code/evidence packet.
