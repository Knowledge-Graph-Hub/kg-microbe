# Authenticated LPSN continuation: implementation checkpoint

The user explicitly authorized reading only `LPSN_USERNAME` and `LPSN_PASSWORD` from the original checkout's `.env` into the owned run's process environment. Values must not be printed, saved, passed as command arguments, or included in persisted fingerprints. This supersedes the earlier credential-read rejection; the earlier blocked reports remain historical evidence.

This checkpoint records implementation and focused controls **before live authentication**. No credential value has been loaded for these changes. Later actual canary, producer, source-admission, merge and CI results belong in the same run evidence and PR #1750; none is implied by this checkpoint.

## Execution boundary

- The allowlisted non-executing parser accepts only the two requested single-line assignments, without interpolation, shell sourcing or evaluation. Missing, duplicate, multiline and linked inputs fail without echoing their contents. Generic dotenv discovery is disabled in the controlled process; the native LPSN factory also skips dotenv when both environment values are supplied.
- The launcher's environment fingerprint now has an explicit versioned allowlist of nonsecret execution settings. Credential values and arbitrary inherited environment entries are neither serialized nor hashed. The safe command digest is computed only after secret-bearing arguments have been refused, and is bound in both the plan and completed execution result.
- The first credential-bearing interpreter and its worker have stdout/stderr suppressed before startup. Authenticated execution suppresses Python/native output and logging, including exception and exit paths. Receipts retain fixed failure categories, actual exit status and verified module origins. Native request provenance contains only fixed route kinds, numeric public record IDs, HTTP status, timing and fixed failure categories.
- The canary permits one official authentication POST and one fresh exact-ID fetch for LPSN record 35300 (Dryocola), with no transport retries or redirects and a total deadline. Authentication tokens remain in memory. Before retaining the scientific response, duplicate JSON keys are refused and raw bytes plus all decoded keys/values are checked against the two credentials and client token values. The actual completed canary command, result, module identities and public record are required before the remaining source phase.
- Every preexisting staged LPSN cache file is independently preserved using traversal that propagates errors. Its original manifest identity and all original member identities must remain unchanged through acquisition. New successful responses can be retained without modifying that cohort.
- Only the remaining `lpsn_api` source is selected through the native dispatcher. The complete canonical plan and saved preceding admissions remain bound. MicrobeDecoder is not selected for a redundant rerun. Native LPSN refuses a tokenless authentication client and aborts before atomic graph publication when retrieval errors occurred. Source-declared API misses and existing reviewed linked-record/web-stub semantics remain distinct.

## Findings and controls

| Issue | Finding | Candidate disposition |
|---|---|---|
| #1780 | Whole-environment fingerprint included secret-bearing inputs | Explicit nonsecret allowlist and secret-rotation controls |
| #1781 | Supplied environment still triggered broader dotenv reads | Environment-first factory and missing-key controls |
| #1782 | Authentication/API errors could reach logs and persisted exceptions | Complete protected execution boundary and synthetic disclosure controls |
| #1783 | Failed authentication or retrieval could still complete a source | Token initialization and atomic failure controls |
| #1784 | Authenticated command withholding broke canary admission | Validated nonsecret command digests in actual plan/result |
| #1785 | Shadowed JSON values, keys or token echoes could enter scientific evidence | Duplicate-key refusal and complete pre-write secret scan |
| #1786 | Cache preservation cohort could shrink or omit an unreadable subtree | Bound manifest identity, exhaustive inventory and mutation controls |
| #1787 | First credential-bearing interpreter inherited output streams | Parent-level suppression before interpreter startup |

The corrected focused selection passed **157 tests, 4 warnings, 2.45 seconds**. Independent baseline review and all failed/earlier attempts remain retained. Final independent re-review and the new candidate's full gate/CI are still pending at this checkpoint. The previous candidate's green suite/CI are not relabeled as evidence for these changes.

The remaining authorized sequence is authenticated canary, remaining LPSN producer, full canonical source admission, local canonical merge, native archive admission, MediaDive qualification admission and preserved-October comparison. Each actual stage must finish successfully before its dependent step. Original inputs/checkouts and the 632 MediaDive unknown associations remain preserved; association coverage remains explicitly incomplete. No GitHub PR merge or release publication is authorized, and the old backlog goal remains paused.
