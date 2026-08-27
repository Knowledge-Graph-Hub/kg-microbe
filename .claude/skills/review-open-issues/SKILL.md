---
name: review-open-issues
description: Sweep and prioritize kg-microbe's complete open GitHub issue queue using current code, transform/merge freshness, and graph evidence. Fetches every open issue (the queue is large and `--limit` truncates silently), builds a pipeline-stage dependency graph, checks each claim against the code AND against the on-disk data's freshness state, groups known root-cause families, and assigns a priority tier plus a separate rerun-cost class. Use for full backlog triage or deciding what is genuinely urgent; do not use as permission to close issues, re-run transforms, or implement fixes.
metadata:
  category: workflow
  requires_database: false
  requires_internet: true
  version: 1.1.0
---

# Review and prioritize open issues

Produce a complete, dependency-aware triage of kg-microbe's open issues. The
issue queue, `NEXT_TASKS.md`, and the graph on disk are three different
surfaces: sweep the queue itself, then test every claim against the current
repository, the authoritative contracts, and the *freshness* of any data you
measure.

This is a read-only review by default. It does not implement fixes, run
transforms or merges, close or edit issues, change labels, or maintain a
tracker unless the user separately authorizes that exact mutation.

**When to use**: the user asks to review, triage, or prioritize issues or the
backlog; asks what is genuinely urgent; or a review pass has just filed a batch
of issues that need sorting.

**When NOT to use**: `NEXT_TASKS.md` upkeep or picking the next unit of work —
that is `next-tasks`. This skill produces a ranking, not a fix, and is
expensive enough that it should not run on every "what's next" question.

## Sources of truth

Use these before relying on an issue title or an old planning note:

- `CLAUDE.md` — repository-wide invariants, operational traps, transform contract;
- `download.yaml` — pinned upstream URLs and versions; the only place they live;
- `merge.yaml` + `config/merge_variants.yaml` — canonical merge spec and variant
  deltas. Generated `merge*.yaml` files are outputs, never edit them;
- `kg_microbe/transform_utils/transform.py` — standard headers, `DATA_INPUTS`,
  `TRANSFORM_INPUTS`;
- `.env.example` — canonical inventory of env vars, defaults, and risk warnings;
- `docs/runbooks/` and the measured docs (`PREGO_SCORE_VALIDATION.md`,
  `BIOLINK_4_4_2_REVALIDATION.md`, `DATA_HOSTING.md`) — dated evidence and the
  corrections that supersede it;
- current source, tests, CI, and the freshness state of committed artifacts.

Treat issue bodies and titles as claims, not current status. Read comments:
this repository records corrections, withdrawals, and narrowed residual scope
there. A merged PR is evidence only after its code and acceptance criteria are
checked.

## What makes this repo different

This is a **knowledge-graph construction** repo, and that changes triage in two
ways a generic issue sweep gets wrong.

**1. Most issues are about data, and the data on disk is usually stale.**
An issue saying "5,242 LPSN ids have no node" is a claim about
`data/transformed/`. Reading those TSVs answers *what the last run produced*,
which may predate the fix by weeks. This has produced repeated wrong
conclusions: a "still broken" verdict on #811 measured output built before the
fix merged, and taxon-conflict counts of 78 vs 187, root-only edge counts of
58,091 vs 58,340, and LPSN id counts of 5,242 vs 5,763 all came from stale
artifacts. **Always establish freshness before believing a measurement.**

**2. "Fixed in code" and "fixed in the graph" are different states.**
A merged PR fixes the transform; the merged KG keeps the old shape until the
transform *and* the merge re-run. Both can be legitimately open questions, so
always say which one an issue is about.

## Workflow

### 1. Fetch the entire queue

Confirm the repository, current count, labels, and full queue. Never silently
accept `gh`'s default limit.

```bash
queue_file="${TMPDIR:-/tmp}/kg-microbe-open-issues.json"
gh repo view --json nameWithOwner,url,defaultBranchRef
gh issue list --state open --limit 5000 \
  --json number,title,body,labels,comments,createdAt,updatedAt,author > "$queue_file"
jq length "$queue_file"
jq -r '.[] | [.number, .createdAt[:10], .title] | @tsv' "$queue_file"
gh label list --limit 200
```

**`--limit` silently caps and there is no warning.** `--limit 100` on this repo
returns exactly 100 of ~268 and looks like a complete answer; a triage was once
reported against "100 open issues" on that basis. Always print `jq length` and
compare it against the limit before claiming full coverage. If the array length
equals the limit, re-run higher.

Read and group from the saved JSON, not the TSV overview — the bodies, labels,
and comments are all needed below. State the exact number reviewed and whether
coverage was complete.

### 2. Establish what is measurable right now

Before checking any data-shaped issue, get the freshness picture once:

```bash
poetry run python .claude/skills/kgm-freshness-check/kgm_freshness_check.py
```

**Run it under `poetry run`, never bare `python`.** Bare `python` cannot import
`kg_microbe` (the package `__init__` pulls in `kghub_downloader`), so the
fingerprint and `DATA_INPUTS` lookups silently degrade to "nothing declared"
and the whole report becomes *optimistic* — six sources drop from
`STALE_VS_CODE_AND_DATA` to `STALE_VS_CODE` with no indication (#884).

Record which sources are `FRESH` vs `STALE_*` vs `MISSING_OUTPUT`, and whether
the merge is stale. Then classify each data-shaped issue's evidence:

- **Verifiable now** — the source is `FRESH`, so measuring
  `data/transformed/<source>/` answers the question.
- **Not verifiable without a re-run** — the source is stale. Say so explicitly
  and do not report a number from it as current.
- **Code-only** — the issue is about transform logic; read the code and ignore
  the output entirely.

Freshness is content-based (`transform_fingerprint`, #844): `FRESH` means the
output was produced by the current code and declared inputs, not that its mtime
is recent. Two caveats that decide whether a `STALE_*` verdict is real:

- **A marker only exists for sources run since the mechanism landed.** Sources
  without `source_fingerprint.json` fall back to timestamps and will report
  stale on a formatting-only commit (#879). Distinguish behaviour change from
  formatting by comparing ASTs, not bytes, before recommending an expensive
  rerun.
- **A stale verdict is not automatically a rerun.** Check whether the source has
  downstream consumers in `TRANSFORM_INPUTS` first — see step 3.

### 3. Build the dependency graph before assigning rank

Place each issue at the earliest affected stage:

```text
download.yaml pin / upstream release
  -> data/raw/
  -> transform (per source; ordering constrained by TRANSFORM_INPUTS)
  -> declared curation inputs (DATA_INPUTS) and mappings/
  -> node/edge referential integrity, CURIE prefixes, categories
  -> predicate family, domain/range, Biolink conformance
  -> merge.yaml / variants -> data/merged/merged-kg.tar.gz
  -> merged_graph_stats.yaml, release claim, downstream consumer
```

The cross-transform dependencies are machine-readable; derive them rather than
guessing:

```bash
poetry run python -c "
from kg_microbe.transform import DATA_SOURCES
for s, c in DATA_SOURCES.items():
    ti = tuple(getattr(c, 'TRANSFORM_INPUTS', ()) or ())
    if ti: print(f'{s} <- {\", \".join(ti)}')
"
```

An upstream correctness or identity problem blocks every downstream consumer.
Recommend fixing or auditing that root problem before polishing downstream
output. Group issues that share a root cause, but never hide the individual
issue numbers.

For each issue, record when applicable:

- pipeline stage and owning source/module;
- affected transform output and its freshness state;
- schema, predicate, category, CURIE prefix, domain, and range assumptions;
- node/edge counts and the freshness state they were measured under;
- downstream consumers (`TRANSFORM_INPUTS`) and which merge configs read it;
- prerequisites, blockers, duplicates, and superseding issues;
- cheapest decisive evidence and the acceptance test;
- **rerun cost class** (see step 5).

### 4. Group, dedupe, and check the known families

Issues filed from one review pass often overlap. Group by shared PR/commit
reference, same file/function, or near-identical failure scenario.

Watch for the recurring **families** in this repo, where several issue numbers
are one root cause:

- undeclared `DATA_INPUTS` / silent staleness — #812, #839, #845, #876
- timestamp-based freshness — #797, #836, #879
- family mismatch, "is this CURIE the right *kind* of thing" — #783, #790,
  #823, and `DISALLOWED_OBJECT_SOURCES`
- Biolink domain/range violations — #642–#645
- **a config or path whose name is the only thing asserting its content** —
  #847, #885

A family is worth reporting as one item with a shared fix, not four.

### 5. Check current reality and staleness

For each issue or group representative:

- Search history for the issue reference:

  ```bash
  git fetch origin master
  git log --oneline origin/master --perl-regexp --grep '#<N>\b'
  gh issue view <N> --json closedByPullRequestsReferences
  ```

  The word boundary is required: `#48` must not match `#480`. Do **not** use
  `--all` — a commit on an unmerged branch is work in progress, not a fix. This
  repo squash-merges, so the PR number reliably appears in the subject.

  `Closes #A and #B` **only auto-closes `#A`** — GitHub needs a keyword per
  issue. An issue can therefore be genuinely fixed and still open; this has
  happened twice (#836, #879). Check the PR body before believing the state.

- Use `rg` to confirm that named paths, functions, flags, and constants still
  exist and behave as described. Read the surrounding context, not just the
  matching line — an issue was once filed claiming `DATA_INPUTS` was
  undocumented, from a grep that started below its twelve-line docstring.
- Compare acceptance criteria with the merged change. If only part is fixed,
  retain the issue with a narrowed residual; do not recommend closure merely
  because a related PR merged.
- Distinguish an observation from its action issue. Prefer closing a fully
  recorded observation as superseded when a separate open issue owns the only
  remaining work.
- Verify artifacts by content and provenance, not filenames or prose. A count
  without its source, freshness state, and the config that produced it is not
  a result.

### 6. Apply KG stop-the-line checks

Treat these as P0 when they affect a shipped or imminently shipping graph:

- silent node/edge loss, or a transform that exits 0 having written nothing;
- wrong predicate, direction, domain/range, or endpoint category — including a
  predicate asserting more than the data supports (a `close_match` across a
  3,695:1 collapse, #883);
- identifier collisions, dangling endpoints, or a CURIE indexed under only one
  of its valid prefixes (#882);
- a cache or output whose *existence* is taken to imply completeness when it
  was written partially, or a stale cache published as current;
- mixed provenance — outputs from different transform generations merged
  together, or a merge config reading a directory that no longer holds what its
  name says (#885);
- a freshness or provenance defect that makes stale output look current, or
  makes an expensive planned rebuild produce an unusable result;
- an outward-facing release claim resting on any of the above.

The distinctive P0 in this repo is **silent wrongness** — a graph that looks
fine and is not. A transform that crashes loudly is P1.

### 7. Assign priority and execution order

Use priority for consequence and a separate **rerun-cost class** for ordering:

| class | meaning | examples |
|---|---|---|
| `read-only` | answerable from code/git alone | modelling, docs, contract questions |
| `cheap` | seconds to a few minutes | `gold`, `madin_etal`, `rhea_mappings` |
| `expensive` | tens of minutes to hours | `ontologies` (SemSQL build), `bacdive`, `metatraits`, `gtdb` |
| `full-merge` | whole-graph rebuild | anything requiring `data/merged/` to be current |

- **P0 — stop the line.** Wrong or silently missing data in the shipped graph;
  anything that makes a stale or incorrect artifact look correct; a blocker for
  an already-planned expensive rebuild.
- **P1 — important and schedulable.** A genuine defect or gap that is visible
  when it bites: a transform that fails loudly, a curation gap with a known
  count, a test-coverage hole over risky code.
- **P2 — low-risk or historical.** Doc drift, stale comments, refactors,
  theoretical edge cases, convention issues, new-source requests with no
  committed timeline.
- **CLOSE/UPDATE.** Fixed, superseded, duplicate, no longer applicable, or a
  title materially broader than the remaining work. Cite the exact commit, PR,
  code location, or comment.

Calibrate P0 sparingly — if more than ~10% of the queue lands P0, recheck. A
backlog item open six months that hurts nobody is P2 no matter how it is
worded. Do not prioritize by age, by sunk effort, or by a `P0` string in a stale
title.

Then order work within and across tiers:

1. upstream unblockers before downstream consumers (use the `TRANSFORM_INPUTS`
   graph, not intuition);
2. correctness of the standard graph before experimental merge variants;
3. recover evidence already on disk before re-running anything;
4. `read-only` falsifiers before `cheap` reruns, and `cheap` before `expensive`;
5. batch everything that needs the same expensive rerun into one rebuild —
   a source with no marker will report stale until it runs once regardless;
6. combine issues only when one patch or one rerun genuinely satisfies each
   issue's acceptance criteria.

### 8. Report

Return a compact report with:

1. coverage — repository, timestamp, number reviewed, completeness;
2. top 2–3 next actions and why they unblock later work;
3. a dependency-ordered P0/P1/P2 table with issue number, current status,
   evidence, blockers, rerun-cost class, and next acceptance test;
4. CLOSE/UPDATE candidates with specific evidence;
5. unresolved evidence gaps and cross-repository ownership;
6. a short sequence showing which costly work must wait on what.

**Separate "fixed in code" from "fixed in the graph"** wherever they differ.
Call out old issues explicitly rather than silently dropping them; a six-month
open issue is itself a signal. Separate measured findings, code inspection,
inference, and proposed-but-untested work.

## Conventions this skill enforces

- **Full-queue coverage, not first-page sampling.** State exactly how many
  issues were reviewed and whether coverage was complete. `--limit` truncation
  is the known failure here.
- **Freshness before measurement.** Any number taken from `data/transformed/`
  or `data/merged/` is reported with the freshness state of its source, or not
  reported at all.
- **Evidence over vibes.** Every CLOSE/UPDATE/duplicate recommendation cites a
  specific commit, PR, artifact, or code location — never "this looks done".
- **P0 is rare**, and here it usually means *silently wrong*, not *loudly broken*.
- **Titles are claims and they drift.** Issues get retitled mid-life, including
  to `[WITHDRAWN/RESOLVED]`, while staying open. Re-read titles at report time
  rather than trusting the ones fetched at the start of the sweep.
- **The queue moves during the sweep.** Parallel PRs can resolve issues while
  triage is in progress. Re-check the open set immediately before reporting,
  and say so if it changed.
- **Read-only by default.**

## Measurement discipline

The recurring failure here is not misreading evidence, it is mismeasuring it.
Before citing any of the following, confirm how it was obtained:

- **The interpreter decides the answer.** `python` and `poetry run python`
  produce different freshness reports from the same script, and the bare one is
  optimistic (#884). This generalizes: any tool that degrades on ImportError can
  report a clean run because it checked nothing.
- **A directory name is not evidence of its contents.**
  `data/transformed/prego/` and `data/transformed/prego_habitat/` are
  byte-identical habitat builds; only `cut -f2 edges.tsv | sort | uniq -c`
  showed that the "full" path holds habitat-only output (#885).
- **A stale verdict may be formatting.** Compare ASTs, not bytes, before
  recommending an expensive rerun (#879).
- **Exit codes through pipes.** `cmd | tail -3; echo $?` reports `tail`'s
  status, not `cmd`'s, so a fail-closed tool looks like it succeeded. Use
  `cmd >/tmp/o 2>/tmp/e; echo $?`, or `${PIPESTATUS[0]}`.
- **Merge-conflict previews under-report.** `git merge-tree` in its three-arg
  form has reported zero conflicts for a merge that then conflicted. Do not call
  a PR conflict-free on that basis.
- **Truncated tool output.** `gh` and several checkers elide long lines and long
  lists. Re-read the cited file at the cited line, and print counts, before
  acting.
- **Grep starting mid-context.** A match at line 51 says nothing about the
  twelve comment lines above it. Read the block, not the line.
- **Backticks in a double-quoted `-m`.** `git commit -m "...`cmd`..."` executes
  the backticked text. Write reports, issue bodies, and commit messages
  containing shell examples via `-F <file>` or a quoted heredoc (`<<'EOF'`),
  then read the result back before pushing.
- **Whitespace-splitting file lists.** `git status --porcelain | awk '{print $2}'`
  turns one path containing spaces into several bogus entries. Use
  `--porcelain -z | tr '\0' '\n'`.

## Notes and limitations

- `gh issue list --json` omits `comments` unless explicitly requested. This
  repository records corrections and narrowed scope in comments, so a body-only
  fetch will systematically overstate what is open.
- `gh pr list --search "<N>"` matches the number anywhere in indexed text and
  returns unrelated PRs. Treat every hit as a lead and open it before citing it.
- An issue may be fully addressed in code while its acceptance criteria are not.
  Partial fixes keep the issue open with a narrowed residual; say which part is
  done and which is not.
- Some issues are blocked on an external repo (the MIM SSSOM, #822/#837) or on a
  held re-run. Mark them blocked rather than ranking them as actionable.
- Evidence recovery is sometimes impossible. When an issue's residual asks for
  an artifact the repository records as absent, say so and recommend superseding
  it rather than leaving it open indefinitely.
- Two tracker issues are open — **#861** ("Tracking: August 2026 repository
  review remediation") and **#555** ("Tracking: kg-microbe governance & cleanup
  backlog from 2026-04-17 audit"). Verify state before trusting either; update
  in place rather than opening a third.
- No @-mentions in issue comments or reports without explicit per-mention
  authorization (standing rule).

## Mutation boundary

Do not close, comment on, relabel, retitle, or create issues or trackers during
the review. If the user later asks to act, present the exact issue numbers and
the proposed mutation first. Apply closures one at a time with cited evidence;
never treat general approval as authorization for an unattended bulk close.

Do not run `kg download`, `kg transform`, or `kg merge` as part of triage. A
recommended rerun is a proposal, not permission — and a full rebuild is hours.
Do not open cross-repository issues without explicit authorization.

## Related

- `next-tasks` — lighter, `NEXT_TASKS.md`-scoped; run that during active work.
- `kgm-freshness-check` — step 2 depends on it; run it under `poetry run`.
- `kg-model-review` — answers issues alleging Biolink/KGX modelling violations;
  note its sampling caveat (#810).
- `kg-postprocess-report` — for "what is left to ship" framing.
- `branch-triage-ship` — for acting on the result once triage is agreed.
