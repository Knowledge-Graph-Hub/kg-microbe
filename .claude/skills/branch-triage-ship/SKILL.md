---
name: branch-triage-ship
description: Ship a messy topic branch as a set of clean, focused PRs. Walks through triage of committed commits + working-tree modifications + untracked files, extracts misfiled commits to their own branches, splits orthogonal changes into separate PRs, gitignores build noise, opens follow-up issues for deferred items, and merges in the correct dependency order. Use when a working branch has accumulated mixed commits, uncommitted work, and dozens of untracked scratch files and needs to reach master.
---

# branch-triage-ship

## Purpose

Take a topic branch that has drifted — mislabeled commits, uncommitted work on multiple orthogonal topics, dozens of untracked files, and possibly tox failing on master already — and land its intended changes as a set of clean, focused PRs.

The end state:
- The topic branch's declared purpose is exactly what its PR contains.
- Anything unrelated is either on its own branch/PR, in its own follow-up issue, or explicitly deleted.
- Working tree is quiet (`git status --short` shows only files you meant to keep).
- Master CI is green.

## When to use

Trigger this when *any* of these hold:
- Branch name doesn't describe its actual commits.
- `git status` shows more than ~5 untracked entries you can't immediately account for.
- Working tree has tracked-file modifications that clearly belong to different topics.
- Pre-existing tox / CI failures on master would block the branch's PR.
- You want to open a PR but "there's a lot going on in here" is the first thing you'd say.

Skip if the branch is single-topic and the working tree is clean — just PR normally.

## Prerequisites

- `gh` CLI authenticated for the target repo.
- Write access to the branch and the ability to push new branches.
- If admin-merging: repo admin rights AND explicit user authorization to bypass branch-protection review requirements.
- Familiarity with the repo's test / lint gate. This skill runs it, not skips it.

## The workflow

Run every phase before starting the next. Each ends with an explicit checkpoint.

### Phase 1 — Diagnose

Collect the raw picture before proposing anything.

```bash
git status --porcelain          # includes untracked
git log --oneline origin/master..HEAD
git diff --stat origin/master..HEAD
git diff --stat                 # unstaged
git diff --cached --stat        # staged
```

Also fetch to make sure `origin/master` is current:

```bash
git fetch origin master
```

Produce a classification table with three columns per row:
- **Path**
- **Category** — one of: `on-this-branch`, `own-branch`, `gitignore`, `delete`, `needs-decision`
- **Reason**

For every modified tracked file: read the diff. Classify each into:
- **on-this-branch** — matches the branch's declared purpose.
- **own-branch** — orthogonal change; needs its own topic branch.
- **formatter-only** — pure whitespace / autoformatter output; discard or bundle into a chore commit.
- **build-artifact** — file that a pipeline / test rewrites; probably should be `git rm --cached`ed and gitignored.

For every commit ahead of master: check whether it belongs on this branch by name (`git show <sha> --stat`).

For every untracked entry: classify by pattern (see the patterns library below), and note anything ambiguous as **needs-decision**.

**Checkpoint 1**: A single classification table exists that covers every path in `git status`. Nothing is unaccounted for.

### Phase 2 — Extract misfiled commits

If any commit ahead of master doesn't belong to this branch:

1. Create a fresh branch off master, cherry-pick the misfiled commits onto it.
   ```bash
   git checkout -b feat/<accurate-name> origin/master
   git cherry-pick <sha1> <sha2> ...
   ```
2. Leave the topic branch alone for now — reset comes in phase 3.

Never `git reset --hard` before you've verified the cherry-picks succeeded.

**Checkpoint 2**: All misfiled commits exist on a correctly-named branch. `git log --oneline` on that branch shows only the extracted commits.

### Phase 3 — Preserve working-tree work, then reset

**Only if the topic branch has commits ahead of master that need to go away.** If the branch is clean (no misfiled commits), skip to Phase 4.

Working-tree modifications are lost by `git reset --hard`. Save them first.

```bash
mkdir -p /tmp/branch-triage
for f in <files you want to keep>; do
  cp -p "$f" /tmp/branch-triage/
done
```

Then reset:

```bash
git reset --hard origin/master
```

Restore the files you saved:

```bash
for f in /tmp/branch-triage/*; do
  cp -p "$f" "$(git rev-parse --show-toplevel)/<original-path>"
done
```

**Checkpoint 3**: The topic branch is at `origin/master` with only the files you intentionally restored appearing as modifications in `git status`.

### Phase 4 — Split into focused topic branches

Every group in your classification table that is **on-this-branch** stays on this branch. Every group that is **own-branch** goes to a new branch off master:

```bash
git checkout -b <accurate-topic-name> origin/master
# restore just the files that belong to that topic
# stage, commit
```

Repeat for each orthogonal group.

For **formatter-only** modifications: discard them (`git checkout -- <file>`) unless the user has explicitly asked for a "apply formatter" commit. Formatter noise is inherited from master when master itself fails the formatter; the fix lives on a "chore: apply formatter" branch or in the CI hardening PR.

For **build-artifact** files that are already tracked: reserve for the `git rm --cached` branch in phase 5.

**Checkpoint 4**: You have N branches, each with exactly one topic's commit(s). Each branch is at `origin/master + 1..few commits`.

### Phase 5 — Cleanup branch(es)

Two common cleanup branches (each on its own — do not bundle):

#### 5a. Gitignore build artifacts

For untracked scratch that will keep re-appearing on every run:

```bash
git checkout -b chore/gitignore-build-artifacts origin/master
# append to .gitignore
git add .gitignore
git commit -m "Gitignore local build artifacts and dated snapshot dirs"
```

Include only patterns you are confident about. Prefer anchored globs (`/*.out`, `notebooks/*.html`) over wildcards that could catch authored content. See "Patterns library" below.

#### 5b. Untrack regenerable pipeline outputs

For files currently tracked that a pipeline rewrites every run:

```bash
git checkout -b chore/untrack-regenerable-outputs origin/master
git rm --cached <file1> <file2> ...
git commit -m "Untrack regenerable pipeline outputs"
```

Verify the files remain on disk after `git rm --cached` — the flag is index-only. The gitignore rule from 5a must already exist (or land in the same PR) or the files will re-appear as untracked immediately.

**Checkpoint 5**: Cleanup branches exist. `git status` on the topic branch shows only files that need per-file decisions, which will become a follow-up issue in Phase 8.

### Phase 6 — Verify each branch

Run the repo's test / lint gate on every branch. In a Python + tox repo:

```bash
for br in <list of branches>; do
  git checkout "$br"
  git checkout -- $(git diff --name-only)   # discard tox format leftovers
  poetry run tox
done
```

Common failure modes and what they mean:

- **All branches fail the same test** → the failure is on master, unrelated to any of your branches. Identify which branch fixes it and merge that one first. Note in the other PRs' bodies that CI is inherited-broken until the fix lands.
- **Format check leaves files dirty** → master's code fails the current formatter. Discard the changes with `git checkout --` before switching branches. Do NOT commit the auto-format changes to your topic branches; they belong in a separate "chore: apply formatter" PR.
- **Only one branch fails** → real breakage on that branch. Fix before proceeding.

**Checkpoint 6**: You know exactly which branches pass, which fail, and why. Failure reasons are documented and non-blocking (either fixed, or inherited-broken with a clear owner).

### Phase 7 — Push and open PRs

Sequential per branch:

```bash
git push -u origin <branch>
gh pr create --base master --head <branch> --title "<title>" --body "$(cat <<'EOF'
## Summary
<what changed, in bullet points>

## Test plan
- [x] `poetry run tox` on this branch — passes / shows only pre-existing master failures fixed by #<companion-pr>.
- [ ] <manual verification if applicable>

## Related
- **Blocked on CI:** #<companion-pr>  (only for branches inheriting master fails)
- Follow-up: #<issue for deferred items>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Rules for PR bodies:
- Every PR references its blocker PR if it inherits master failures.
- Every PR references any follow-up issue it defers work to.
- Test plan bullets are honest about what was run vs what still needs manual verification.
- Never include a "Test plan" checkbox that was neither run nor is planned. Delete it.

**Checkpoint 7**: One PR per topic branch. Every PR body has: summary, test plan reflecting real coverage, related PRs / issues cross-referenced.

### Phase 8 — File follow-up issues

For every `needs-decision` group in the phase-1 table that didn't become a PR: file a GitHub issue that:
- Lists each path with a checkbox.
- Explains the classification prompt ("belongs on which branch, or gitignore, or delete").
- Cross-links to the PRs that did land.

```bash
gh issue create --title "..." --body "..."
```

**Checkpoint 8**: Every deferred item has a GitHub-native home. `NEXT_TASKS.md` or a local checklist file can now be deleted — the durable record is the issue.

### Phase 9 — Merge in dependency order

Merge order matters. Identify the dependency:
- A branch that fixes master's CI must merge first, or the others will show red CI (annoying to reviewers) even if the actual diff is fine.
- Anything else can merge in any order after that.

```bash
gh pr merge <n> --merge      # or --admin --merge  ONLY if explicitly authorized to bypass reviews
```

Branch protection rules are checked with:

```bash
gh api repos/<owner>/<repo>/branches/master/protection
```

If `required_approving_review_count > 0` and you're the sole author, you cannot self-approve. Options:
- Ask a collaborator to review.
- If you're admin AND the user has explicitly authorized bypass, use `--admin`.
- Otherwise, stop here and hand off.

After each merge, update local master:

```bash
git fetch origin master
git checkout master
git merge --ff-only origin/master
```

**Checkpoint 9**: All PRs are merged. Master is at the expected new tip.

### Phase 10 — Local cleanup

Delete merged local branches:

```bash
git branch -d <br1> <br2> ...   # -d (safe) refuses if not fully merged
```

The `-d` flag will refuse to delete a branch that isn't fully merged. If you get an error, do NOT jump to `-D` — investigate first; you probably missed a commit.

Do NOT auto-delete unrelated stale local branches. Their existence is often intentional (work-in-progress that wasn't part of this triage).

**Checkpoint 10**: Only master and pre-existing unrelated branches remain locally. `git status --short` matches the expected residual (typically the follow-up-issue's checklist items).

## Patterns library

### Untracked file classification cheatsheet

| Pattern | Category | Default action |
|---|---|---|
| `data/raw_20*/`, `data/raw_last[0-9]*/`, `data/transformed_20*/`, `data/merged_20*/` | build-artifact | gitignore |
| `*.out`, `*.log`, `*.tmp` at repo root | build-artifact | gitignore |
| `download.yaml_*`, `merge.yaml_*`, `*.yaml.bak` | build-artifact | gitignore |
| `*.ipynb_bak`, `*.py_bak`, `**/*.bak` | backup | gitignore |
| `notebooks/catboost_info/`, `notebooks/*.html`, `notebooks/*_output.tsv` | build-artifact | gitignore |
| `<name>*.png` / `<name>*.psd` at repo root (mockups) | build-artifact | gitignore |
| new `.py` in `<pkg>/utils/` with no in-repo references | needs-decision | issue |
| root-level `.py` (`run.py`, `analyze_*.py`) | needs-decision | issue |
| new `.py` in a package with a name that collides with an existing package | needs-decision (shadowing risk) | issue with explicit shadowing note |
| `<pkg>/**/tmp/*.tsv` opened with `"w"` mode by a transform | build-artifact | gitignore + `git rm --cached` |
| `<pkg>/**/tmp/*.csv` that is < 100 KB and has curated content | reference data | keep tracked |
| SSSOM `mappings/*.tsv` with new authored rows | on-this-branch | stage on the mappings branch |
| `download.yaml` with comment-out blocks | own-branch | own branch (with rationale in commit body) |
| `merged_graph_stats.yaml`, `merged-kg_stats.yaml` diffs | on-a-release-branch | only commit as part of an explicit release |
| `*.docx`, `*.pdf`, `*.psd` for a paper submission | out-of-scope | ignore / move to `paper_*/` |

### Modified tracked file "smells"

| Symptom | Likely cause | Handling |
|---|---|---|
| Diff is only whitespace / line-wrap changes | Formatter run against code that pre-dates the current formatter config | Discard, do not commit into a topic branch |
| Big binary diff (`Bin` in `git diff --stat`) | Regenerated cache / index | If it's a genuine content refresh (SSSOM `.gz`, embedding index), keep; if it's a byproduct, discard |
| One-line yaml value change | Config drift | Own commit; likely own branch |
| Whole-file rewrite of a stats yaml | Rebuild of a merged/stats snapshot | Only commit if this is a release cut; otherwise discard |

## Failure modes to watch for

- **`git reset --hard` before saving working-tree state** — permanent data loss. Phase 3's "preserve then reset" order is mandatory.
- **Force-pushing to a branch that others have based work on** — check `git ls-remote origin refs/heads/<branch>` and remote tracking before force-pushing.
- **Admin-merging without explicit authorization** — branch-protection bypass is a sensitive action. If you weren't told, ask.
- **Bundling formatter changes into a topic PR** — those changes get inherited on every branch off master; do not add them to your topic branches or you'll rebase them into every future PR.
- **Committing a build artifact that's now gitignored** — if you add a file that matches your new `.gitignore`, git will accept the add (explicit-add wins over ignore). Verify with `git status` after the gitignore commit that only intended files remain.
- **Closing an issue by merging a PR that doesn't fully address it** — use `Closes #N` only when the PR fully closes the issue. For partial fixes use `Refs #N`.

## Output artifacts

After running this workflow end-to-end, you should have:
- N merged PRs, one per topic.
- M open follow-up issues, each with a triage checklist.
- A commit history on master that reads like a clear sequence of small, focused changes.
- No local branches left over from the triage.
- Clean `git status` (or only the intentional untracked residual documented in the follow-up issues).

## Companion skills

- **`kgm-freshness-check`** (kg-microbe-specific) — before touching pipeline outputs, verify what's stale vs master.
- **`kg-release`** (kg-microbe-specific) — if the triage is release-adjacent, gate the release on the review skills the release cutter looks for.
- **`resolve-copilot`** — if a Copilot review is already open on the messy branch, address it before or during Phase 6.

## Notes on this repo (kg-microbe)

- Tests run via `poetry run tox`. Full run is ~3-5 minutes.
- Format step (`tox -e format`) is included in the default tox run and will leave master-inherited whitespace changes in your working tree; discard before switching branches.
- Branch protection on `master` requires 1 approving review. Admin bypass available; requires explicit user opt-in.
- Merged branches on GitHub are not auto-deleted; local branches must be deleted with `git branch -d`.
- The three most common "misfiled commit" targets are (a) METPO snapshot integration commits, (b) SSSOM mapping refresh commits, (c) download.yaml source-disable commits. Each has its own conventional branch prefix.
