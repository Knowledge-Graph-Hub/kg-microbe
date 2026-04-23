---
name: resolve-copilot
description: Address unresolved Copilot review threads on a GitHub PR and mark each one resolved (equivalent to clicking the "Resolve conversation" button in the GitHub UI). Use when the user asks to "address copilot", "fix copilot comments", "resolve copilot conversations", or similar on a PR.
---

# Resolve Copilot PR Review Threads

## Purpose

GitHub PR review comments live in "threads" that can be marked resolved independently of the comment itself. The `gh pr comment` CLI and the `reviews` REST endpoint don't expose thread resolution — it is only available through GraphQL. This skill takes a PR URL or number, fetches **unresolved** Copilot threads, addresses each one in the code, pushes the fix, then calls the GraphQL `resolveReviewThread` mutation to mark the thread resolved.

"Resolve the conversation" in the GitHub UI = GraphQL `resolveReviewThread` mutation. This skill automates that last step — the user has been repeating the phrase because the model keeps skipping it.

## Instructions

When invoked, do the following in order. Do not skip the resolve step at the end.

### 1. Determine the PR

Parse the argument or most recent user message for a PR URL or number. Accept forms like:
- `https://github.com/OWNER/REPO/pull/NNN`
- `#NNN` (use `gh repo view` to discover owner/repo)
- `OWNER/REPO#NNN`

Set `$OWNER`, `$REPO`, `$NUM` for the rest of the session.

### 2. Fetch unresolved review threads

```bash
gh api graphql -f query='
{
  repository(owner: "OWNER", name: "REPO") {
    pullRequest(number: NUM) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          path
          line
          comments(first: 1) {
            nodes {
              databaseId
              author { login }
              body
            }
          }
        }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[]
  | select(.isResolved == false)
  | select(.comments.nodes[0].author.login | test("[Cc]opilot"))
  | {thread_id: .id, path, line, comment_id: .comments.nodes[0].databaseId, body: .comments.nodes[0].body}'
```

`author.login` for Copilot's PR reviewer bot is `copilot-pull-request-reviewer` or `Copilot`; the regex `[Cc]opilot` catches both.

Save the `thread_id` for each unresolved thread — you need it for step 4.

### 3. Address each comment

For every unresolved thread, **actually make the code change Copilot asked for** and verify it works (run tests or `tox -e lint` as appropriate). Do not just acknowledge the comment.

- Edit the flagged file, targeting `.line` from the thread query result.
- If the comment is a suggestion (`\`\`\`suggestion ... \`\`\`` block in body), apply the suggestion literally unless it's wrong — in which case flag that to the user before proceeding.
- If multiple threads flag the same file, batch them into a single commit.
- Run `poetry run tox -e lint` and the affected test files before pushing.

Commit with a message referencing the PR number and Copilot, e.g.:

```
Fix <short description> (Copilot #NNN)

<one-paragraph why>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

Push to the PR's head branch.

### 4. Resolve the thread(s)

For each thread addressed, call:

```bash
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "PRRT_xxxxxxxxxx"}) {
    thread { id isResolved }
  }
}'
```

The response `isResolved: true` confirms the thread is now marked resolved in the GitHub UI — equivalent to the user clicking **Resolve conversation**.

If you want to resolve a thread without a code change (e.g. you disagree with Copilot and the user explicitly says so), you should first post a reply explaining the rationale, then resolve:

```bash
# Optional: reply first
gh api repos/OWNER/REPO/pulls/NUM/comments/COMMENT_ID/replies \
  -f body='We are keeping the current behavior because ...'

# Then resolve
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "PRRT_..."}) { thread { isResolved } } }'
```

### 5. Report

Tell the user:
- Number of threads resolved and the commit SHAs that fixed them
- Any threads you intentionally did not resolve (and why)
- A link to the PR so they can verify

## Common mistakes to avoid

- **Do not call `gh pr comment` and consider it done.** That posts a new top-level PR comment; it does not mark the thread resolved.
- **Do not rely on `gh api /pulls/.../comments`.** That REST endpoint returns review comments but has no `isResolved` field and no resolve mutation.
- **Do not batch the resolve mutation with the code push.** Push first, verify the commit landed, then resolve. Resolving before pushing leaves the thread resolved but the fix not deployed.
- **Do not skip the resolve call.** This is the whole reason the skill exists. If you address the comment but don't run the GraphQL mutation, the UI still shows the thread as unresolved and the user will ask again.

## Quick reference

| Action | Command shape |
|---|---|
| List unresolved Copilot threads | GraphQL `repository(...).pullRequest(...).reviewThreads` + `--jq` filter on `isResolved == false` and author login matching `[Cc]opilot` |
| Resolve a thread | GraphQL `resolveReviewThread(input: {threadId: "PRRT_..."})` |
| Unresolve (rarely needed) | GraphQL `unresolveReviewThread(input: {threadId: "PRRT_..."})` |
| Reply to a thread | REST `POST /repos/{owner}/{repo}/pulls/{num}/comments/{comment_id}/replies` |
