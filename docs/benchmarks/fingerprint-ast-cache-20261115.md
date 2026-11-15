# Fingerprint AST reuse: measured test performance

Repeated source-fingerprint work was a concrete cost behind slow local development
and CI (#1862). The two admission modules measured here passed the same 20 cases
in 79.37 seconds before the change and 19.78 seconds afterward. No existing test,
assertion, marker, or CI environment was removed.

## What changed

`_behaviour_digest` still reads each requested Python file on every call. A bounded
process-local LRU now reuses only the pure calculation from **exact source bytes**
to the existing AST digest (or raw-byte fallback for invalid Python/UTF-8).
Directory enumeration and repo-relative filename folding remain uncached.

The cache retains at most 256 entries, each with at most 256 KiB of source bytes:
64 MiB of source payload plus cache/key/digest overhead. Larger files take the
original uncached calculation. Missing files are checked on each read and are not
cached. Cache eviction and concurrent duplicate misses affect cost, not identity.

The digest algorithm and fingerprint version remain unchanged for identical
inputs. This source edit itself still changes the checkout's shared-code
fingerprint, as any shared implementation edit does; normal source freshness and
release checks continue to apply.

## Evidence and comparison limits

Measurements used the same isolated M5 checkout, Python 3.10.11, locked Poetry
environment and test selectors. Baseline master was
`e3d1213a8bf7a4408204ebd48c19e42ec2e14b5e`. No dependency changed.

- Lock SHA256: `a9e8336e172faef6449ed79a2dde8df7932a5cfb9ba368e7a93a7c7ab83d7f6f`.
- Baseline fingerprint-module SHA256: `90272b22dfa0f4b0c690b28a3ef7591ac88f2b52a05925da1061eb5190937e9c`.
- Optimized module SHA256: `c122c85fdd738207ec0d836536f125573daa69dc30f0a15bb65903f05659ff65`.

| Measurement | Before | After |
| --- | ---: | ---: |
| Admission selection | 20 passed, 79.37 s | 20 passed, 19.78 s |
| Admission command wall time (`time -p`) | 79.81 s | 20.15 s |
| Profiled canary test-call phase | 6.15 s | 1.53 s |
| `_behaviour_digest` calls | 1,114 | 1,114 |
| `_behaviour_digest` cumulative profile time | 4.9826 s | 0.5544 s |
| AST dumps in the canary profile | 1,114 | 108 |

These are single before/after runs, not a statistical performance guarantee.
The canary's whole-process times include collection/import startup and different
filesystem/bytecode-cache warmth, so those totals are retained as evidence but
are not attributed wholly to AST reuse. Cumulative profile times overlap and
must not be summed. The unprofiled admission selection provides the end-to-end
comparison for unchanged tests.

The earlier full run at `dff4f9ddedbd72febacbb0ba197342c9a7658370` reported
9,959 passed and 20 skipped in 2,147.61 seconds. That feature branch has a different
test population from this master-based change. Its duration report identified
hotspots; it is not a matched full-suite benchmark. Final full-gate results belong
to the exact committed candidate recorded in the PR and gate ledger.

The [machine-readable evidence](fingerprint-ast-cache-20261115.json) retains
profile/log digests and individual measurements. Raw profiles and logs remain in
`data/validation/test-workflow/` in the retained benchmark checkout. The
[summary helper](../../scripts/adhoc/summarize_test_profile.py) is committed so
those inputs can be summarized again without exposing machine directory paths.

## Reproduction

Use a supported locked environment and an isolated checkout. Preserve each
version's output under a distinct filename. The before command must run on the
baseline code; the after command runs on the optimized code.

```bash
mkdir -p data/validation/test-workflow
.venv/bin/python -m cProfile -o data/validation/test-workflow/baseline-merge-missing-map.prof \
  -m pytest 'tests/test_merge_consumed_input_review.py::test_required_snapshot_cannot_be_omitted_from_current_metadata[missing_map]' \
  -q --durations=0 > data/validation/test-workflow/baseline-merge-missing-map.log 2>&1
/usr/bin/time -p .venv/bin/python -m pytest \
  tests/test_merge_consumed_input_review.py tests/test_merge_upstream_review.py \
  -q --durations=25 > data/validation/test-workflow/baseline-admission-selection.log 2>&1
```

Repeat with distinct `after-*` output paths, then run:

```bash
.venv/bin/python scripts/adhoc/summarize_test_profile.py \
  data/validation/test-workflow/baseline-merge-missing-map.prof \
  data/validation/test-workflow/after-merge-missing-map.prof \
  --pytest-log data/validation/test-workflow/baseline-admission-selection.log \
  --pytest-log data/validation/test-workflow/after-admission-selection.log \
  --output data/validation/test-workflow/comparison-new.json
```

Eight focused regression cases cover repeated reads with parse reuse, same-size
changes with restored mtimes, deletion/reappearance, directory membership and
renames, original digest semantics, invalid syntax/encoding, the source-size
boundary, and LRU eviction. Existing fingerprint, admission and real native
lifecycle tests remain the downstream checks; a benchmark pass alone is not full
validation or graph-release acceptance.
