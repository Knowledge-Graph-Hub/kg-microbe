---
name: review-open-issues
description: Sweep and triage the full open-issue queue for kg-microbe — not just NEXT_TASKS.md. Fetches every open issue, checks each against the current code AND against transform/merge output freshness (a KG repo's issues are often about data, and the on-disk data is routinely stale), flags likely duplicates, and assigns a priority tier (P0 wrong-data/blocking, P1 real-but-schedulable, P2 low-severity/process/doc). Produces a short, ranked report; only touches GitHub when asked. Use when the user asks to "review issues", "prioritize the backlog", "triage open issues", or after a review pass has filed a batch of new issues.
category: workflow
requires_database: false
requires_internet: true
version: 1.0.0
---

# Review & Prioritize Open Issues

## Overview

**Purpose**: the raw GitHub issue queue and `NEXT_TASKS.md` are different
surfaces. `next-tasks` reconciles a small, curated backlog file. This skill
sweeps the *entire* open-issue queue — which in this repo is large (263 open as
of 2026-08-22) and drifts independently — and produces an honest, current
priority ranking.

**When NOT to use**: for `NEXT_TASKS.md` upkeep or picking the next unit of
work — that's `next-tasks`. This skill ranks; it does not implement fixes.

## What makes this repo different

This is a **knowledge-graph construction** repo, and that changes triage in two
ways a generic issue sweep gets wrong.

**1. Most issues are about data, and the data on disk is usually stale.**
An issue saying "5,242 LPSN ids have no node" is a claim about
`data/transformed/`. Checking it by reading those TSVs answers *what the last
run produced*, which may predate the fix by weeks. This has produced repeated
wrong conclusions: a "still broken" verdict on #811 measured output built
before the fix merged, and taxon-conflict counts of 78 vs 187, root-only edge
counts of 58,091 vs 58,340, and LPSN id counts of 5,242 vs 5,763 all came from
stale artifacts. **Always establish freshness before believing a measurement.**

**2. "Fixed in code" and "fixed in the graph" are different states.**
A merged PR fixes the transform; the merged KG keeps the old shape until the
transform *and* the merge re-run. Both can be legitimately open questions, so
say which one an issue is about.

## Workflow

### Step 1 — Fetch the full open-issue queue

```bash
queue_file="${TMPDIR:-/tmp}/kg-microbe-open-issues.json"
gh issue list --state open --limit 5000 \
  --json number,title,body,labels,comments,createdAt,updatedAt > "$queue_file"
jq -r '.[] | [.number, .createdAt[:10], .title] | @tsv' "$queue_file"
jq length "$queue_file"
```

**`--limit` silently caps and there is no warning.** `--limit 100` on this repo
returns exactly 100 of 263 and looks like a complete answer; a triage was
reported against "100 open issues" on that basis. Always print `jq length` and
compare it against a limit-free count before claiming full coverage. If the
array length equals the limit, re-run higher.

Read and group from the saved JSON, not the TSV overview — the bodies, labels
and comments are needed below.

### Step 2 — Establish what is measurable right now

Before checking any data-shaped issue, get the freshness picture once:

```bash
poetry run python .claude/skills/kgm-freshness-check/kgm_freshness_check.py
```

Record which sources are `FRESH` vs `STALE_*` vs `MISSING_OUTPUT`, and whether
the merge is stale. Then for each data-shaped issue, classify the evidence:

- **Verifiable now** — the relevant source is FRESH, so measuring
  `data/transformed/<source>/` answers the question.
- **Not verifiable without a re-run** — the source is stale. Say so explicitly
  and do not report a number from it as current. A cheap re-run
  (`kg transform -s gold` is ~1 min) may be worth doing; a `bacdive` or
  `metatraits` run is not, and the merge certainly is not.
- **Code-only** — the issue is about transform logic, so read the code and
  ignore the output entirely.

Freshness is content-based (`transform_fingerprint`, #844): a `FRESH` verdict
means the output was produced by the current code and declared inputs, not that
its mtime is recent.

### Step 3 — Group and dedupe

Issues filed from one review pass often overlap. Group by shared PR/commit
reference, same file/function, or near-identical failure scenario. Note groups
explicitly; do not silently merge them.

Watch for the recurring **families** in this repo, where several issue numbers
are one root cause:
- undeclared `DATA_INPUTS` / silent staleness (#812, #839, #845, #876)
- timestamp-based freshness (#797, #836)
- family mismatch — "is this CURIE the right *kind* of thing" (#783, #790,
  #823, and `DISALLOWED_OBJECT_SOURCES`)
- Biolink domain/range violations (#642–#645)

A family is worth reporting as one item with a shared fix, not four.

### Step 4 — Check each issue against current reality

- **Already fixed on master?** `git fetch origin master`, then
  `git log --oneline origin/master --perl-regexp --grep "#<N>\b"`. The `\b` is
  required — plain `--grep "#48"` also matches `#480`. Do not use `--all`:
  a commit on an unmerged branch is work in progress, not a fix.
  This repo squash-merges, so the PR number reliably appears in the subject.
- **Closed by a merged PR?**
  `gh issue view <N> --json closedByPullRequestsReferences`, then verify
  `mergedAt` per candidate. Note that `Closes #A and #B` only auto-closes `#A` —
  GitHub needs a keyword per issue — so an issue can be genuinely fixed and
  still open.
- **Still reproducible in code?** If the issue cites a file/function, confirm it
  still exists in that shape. Large refactors move things.
- **Still reproducible in data?** Only if Step 2 said the source is FRESH.
- **Superseded?** Check whether a later issue or merged PR replaced it.

### Step 5 — Assign priority

- **P0 — wrong data shipped, or blocking.** Edges/nodes that are wrong or
  silently missing in the merged graph; anything that makes a stale or
  incorrect artifact look correct; a defect that blocks the pipeline or a
  release. The distinctive P0 here is *silent* wrongness — a graph that looks
  fine and is not.
- **P1 — real, schedulable.** A genuine defect or gap that should be fixed soon
  but is visible when it bites: a transform that crashes loudly, a curation gap
  with a known count, a test-coverage hole over risky code.
- **P2 — low-severity/process/doc.** Doc drift, stale comments, cleanups,
  convention issues, new-source requests with no committed timeline.

Do not default everything to P1. Use P0 sparingly — if more than ~10% land P0,
recalibrate. A backlog item that has been open 6 months and hurts nobody is P2
no matter how it is worded.

### Step 6 — Present the report

- Ranked list, P0 first, one line per issue/group with number + one-sentence why.
- **Separate "fixed in code" from "fixed in the graph"** where they differ.
- Explicitly list issues recommended for closing, each with its evidence
  (commit, PR, or code location) — never "this looks done".
- **Recommend a top 2–3** to act on next, with reasoning.
- State how many issues were reviewed and whether coverage was complete.
- Do not silently drop old issues; a 6-month-old open issue is itself a signal.

### Step 7 — Act only when asked

Read-only by default. A general "yes" is not blanket approval for an unattended
close loop:

- **Closing**: confirm the specific numbers first, then
  `gh issue close <N> --comment "<evidence>"`, one at a time.
- **Tracker issues**: this repo has two open as of 2026-08-22 — **#861**
  ("Tracking: August 2026 repository review remediation") and **#555**
  ("Tracking: kg-microbe governance & cleanup backlog from 2026-04-17 audit").
  Verify state before trusting either; update in place rather than opening a
  third.

## Conventions this skill enforces

- **Full-queue coverage, not first-page sampling.** State the count and say
  whether it was complete. `--limit` truncation is the known failure here.
- **Freshness before measurement.** Any number taken from `data/transformed/`
  or `data/merged/` is reported with the freshness state of its source, or not
  reported.
- **Evidence over vibes.** Every CLOSE/STALE/duplicate recommendation cites a
  commit, PR, or code location.
- **P0 is rare**, and in this repo usually means "silently wrong", not "loudly
  broken".
- **Read-only by default.**

## Notes & limitations

- Keep `comments` in Step 1's `--json` list — a "fixed already" note is often
  buried in a comment thread.
- Some issues are blocked on an external repo (the MIM SSSOM, #822/#837) or on
  a held re-run. Mark them blocked rather than ranking them as actionable.
- No @-mentions in comments without explicit per-mention authorization
  (standing rule).
- This skill ranks; it does not merge, push, or edit files under review.

## Related

- `next-tasks` — lighter, `NEXT_TASKS.md`-scoped; run that during active work.
- `kgm-freshness-check` — Step 2 depends on it.
- `kg-model-review` — for issues alleging Biolink/KGX modelling violations,
  this is the tool that answers them; note its sampling caveat (#810).
- `kg-postprocess-report` — for "what is left to ship" framing.
