# Shared: fetching and understanding the PR

Applies to every review, whatever the stack.

## 1. Resolve the PR coordinates

You need `owner`, `repo`, and `pullNumber` for every GitHub MCP call.

| Input | How to resolve |
| --- | --- |
| Full URL | Parse `github.com/<owner>/<repo>/pull/<number>`. |
| Bare number | Take `owner`/`repo` from the git remote: `git remote get-url origin`. |
| Nothing | `gh pr view --json number,url,headRepositoryOwner,headRepository` for the current branch. |

If the remote is an enterprise host (not `github.com`), say so and confirm the
GitHub MCP Prod server points at that host before continuing — otherwise every
call 404s against the wrong instance.

## 2. Pull the PR context

Preferred: `mcp__claude_ai_GitHub-MCP-Prod__pull_request_read`. If that server is
not available in this session (the tool is missing, unauthenticated, or 403s on a
private repo), fall back to the `gh` CLI rather than stopping — everything except
posting the review works the same way:

| Need | MCP `method` | `gh` fallback |
| --- | --- | --- |
| Title, body, base/head refs, head SHA, state | `get` | `gh pr view <n> --json title,body,baseRefName,headRefName,headRefOid,state` |
| The unified diff | `get_diff` | `gh pr diff <n>` |
| Changed file list with per-file add/delete counts | `get_files` (paginate, `perPage: 100`) | `gh pr view <n> --json files` |
| Commits, to see how the PR evolved | `get_commits` | `gh pr view <n> --json commits` |
| CI status — a red build changes the review | `get_check_runs` | `gh pr checks <n>` |
| Existing review threads from earlier rounds | `get_review_comments` | `gh api repos/<owner>/<repo>/pulls/<n>/comments` |
| Earlier review summaries | `get_reviews` | `gh api repos/<owner>/<repo>/pulls/<n>/reviews` |

Say which path you used in the summary, and check `gh auth status` before
concluding a repo is inaccessible. Posting the review has its own fallback — see
[`github-review.md`](github-review.md).

**The PR diff from the API is the source of truth for what changed.** Do not
substitute `git diff main...HEAD` — the local checkout may be stale, and the local
merge base can differ from the one GitHub computed.

Read the PR description carefully for stated intent. The most common real defect
in a PR is that it does not fully do what its own description claims.

## 3. Read changed files in full

Diff hunks hide the context that makes a change wrong: the field initialised
elsewhere, the early return above the hunk, the overload that also needed updating.

- If the repo is checked out locally and the branch matches the PR head SHA, read
  from disk — faster, and it lets you grep.
- Otherwise use `mcp__claude_ai_GitHub-MCP-Prod__get_file_contents` with
  `ref: "refs/pull/<number>/head"`, or without the MCP server
  `gh api repos/<owner>/<repo>/contents/<path>?ref=<headSha> --jq .content | base64 -d`.
- Skip generated files, lockfiles, snapshots, and vendored code unless the diff is
  *about* them. Reviewing a regenerated lockfile line by line is waste.

## 4. Trace internal imports two levels deep

For each internal (first-party) import in a changed file, read that file. For each
internal import in *that* file, read it too. Stop there.

This is where the real findings come from — the type contract that no longer holds,
the sibling method with the same bug, the caller that passes null. External library
imports do not need tracing; check their docs only when the change hinges on
library semantics.

## 5. Look for the sibling change that was missed

The highest-value pattern in PR review: the author fixed one instance of something
and left the others. Once you understand the change, grep for the pattern.

- A guard added to one method — do the sibling methods need it?
- A field added to one DTO or mock — do the other mocks now produce unrealistic data?
- A renamed file — are dynamic, lazy, and reflective references updated too?
  String-based imports, `Class.forName`, DI component scans, route configs, i18n keys.
- A removed utility — is every reference gone?
- A changed enum or constant — is every `switch`, map key, and persisted value updated?

## 6. Handle re-reviews

If `get_reviews` / `get_review_comments` shows prior rounds from this account:

- **Still-valid prior findings** — re-raise them as normal findings, noting they were
  raised before and remain unaddressed.
- **Resolved prior findings** — do not re-post them inline. Give them one line each
  in a "Previously raised" table in the summary body (Fixed / Partially fixed).
- **New findings** — post normally.

The goal of a re-review is to shorten the path to merge, not to restate the first
review.

## 7. Know when to stop and ask

- The PR is a large mechanical refactor (thousands of lines, one transformation) —
  ask whether they want spot-checks or a full sweep.
- The diff depends on something you cannot see: an external API contract, a schema
  owned by another repo, a feature flag's runtime value.
- MCP calls fail twice for the same reason.
