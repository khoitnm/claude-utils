# Shared: posting the review with GitHub MCP Prod

All tools below are prefixed `mcp__claude_ai_GitHub-MCP-Prod__`.

## The sequence

Three steps. Do them in this order — inline comments require a pending review to
already exist.

### 1. Create the pending review

```
pull_request_review_write
  method:     "create"
  owner:      <owner>
  repo:       <repo>
  pullNumber: <number>
```

Omit `event` and `body`. Supplying `event` here submits immediately and you lose
the chance to attach inline comments.

If this errors because a pending review already exists from an abandoned run,
either finish it or clear it with `method: "delete_pending"` — check what is in it
first, and do not delete a pending review you did not create in this session
without asking.

### 2. Attach each finding

```
add_comment_to_pending_review
  owner, repo, pullNumber
  path:        "src/main/java/com/acme/QuoteService.java"   // repo-relative, exactly as in the diff
  body:        <the finding, formatted per severity-and-output.md>
  subjectType: "LINE"
  line:        142          // for a range, the LAST line
  side:        "RIGHT"      // RIGHT = the new state; LEFT = the removed state
  startLine:   138          // only for multi-line
  startSide:   "RIGHT"      // only for multi-line
```

Anchoring rules that decide whether the call succeeds:

- **The line must be part of the diff.** GitHub rejects comments on lines outside
  the changed hunks (including their context lines). If the real problem is in
  untouched code, anchor to the nearest changed line that the problem flows
  through, and name the true location in the body.
- **`side: "RIGHT"`** for added or unchanged lines — this is almost always what you
  want. Use `"LEFT"` only to comment on a line the PR deleted.
- **`subjectType: "FILE"`** with no `line` for a finding about the file as a whole
  (a missing test file, a whole-file concern). For a finding about the PR as a
  whole, put it in the summary body instead of forcing it onto a line.
- Line numbers are the **new file's** numbering for `RIGHT`, the **old file's** for
  `LEFT`. Take them from the diff hunk headers, not from a local file that may
  differ from the PR head.

If a comment call fails with an "invalid line" style error, do not retry the same
coordinates. Re-anchor to a line you can verify is in a hunk, or move the finding
to the summary body.

### 3. Submit once

```
pull_request_review_write
  method:     "submit_pending"
  owner, repo, pullNumber
  body:       <the summary from severity-and-output.md>
  event:      "COMMENT"
```

**Default to `event: "COMMENT"`.** `APPROVE` and `REQUEST_CHANGES` are formal review
states carrying the user's authority in the repo's merge rules — they can unblock a
merge or block a teammate. Use them only when the user explicitly asked
("approve it if it's clean", "request changes"). Otherwise state the recommendation
in the body and let the human click the button.

## Confirm before submitting when

- The review has more than ~15 inline comments. That volume reads as hostile and
  usually means the PR needs a conversation. Offer to post the top findings inline
  and the rest as a summary.
- The PR is authored by someone other than the user and the review is harsh.
- The user asked for `APPROVE` or `REQUEST_CHANGES`.
- The PR is already merged or closed — ask whether a post-hoc review is wanted.

A submitted review notifies the author and is visible to the whole repo. Editing it
afterwards does not un-send the notification. Treat submission as the
point of no return.

## Replying to existing threads

To respond to a reviewer's or author's existing comment rather than opening a new
thread, use `add_reply_to_pull_request_comment` with the target comment's ID from
`pull_request_read` / `get_review_comments`. Replying keeps the discussion in one
thread instead of fragmenting it.

## When a summary-only comment is right

Use `add_issue_comment` (with `issue_number` = the PR number) instead of a review
when:

- The user asked for a single comment rather than a review.
- There are no line-anchorable findings.
- A pending review cannot be created (permissions, or the PR is closed).

One comment, the full summary in the body.

## Dry run

With `--dry-run`, or whenever the user has not clearly asked for the findings to be
posted, print the review in chat — summary table first, then the inline comments
with their intended `path:line` anchors — and ask before posting. Posting to a
shared PR is outward-facing and not easily undone.
