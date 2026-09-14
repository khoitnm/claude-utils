---
name: handle-review-comments
description: Work through the code review comments on a pull request — verify each one is actually right, fix the ones that are, and reply to every thread in plain language. Use when asked to handle, address, respond to, or go through PR review comments or reviewer feedback.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, ToolSearch
---

# handle-pr-review-comments

Three jobs, in order: **check whether the comment is right**, **fix it if it is**, **reply so the
reviewer knows what happened**. Skipping the first is how a working script gets "fixed" into a
broken one.

Takes an optional PR number. Without one, find it from the current branch.

## Load the tools

Prefer to use the GitHub MCP tools (if there's no GitHub MCP tool, use `gh`)

```
ToolSearch: select:mcp__claude_ai_GitHub-MCP-Prod__pull_request_read,mcp__claude_ai_GitHub-MCP-Prod__add_reply_to_pull_request_comment,mcp__claude_ai_GitHub-MCP-Prod__list_pull_requests
```

- Find the PR: `list_pull_requests` with `head: <owner>:<branch>`, `state: all`.
- Read threads: `pull_request_read` with `method: get_review_comments` — these are the line-level
  comments, the ones that matter.
- `method: get_comments` is the PR conversation tab, which is mostly bots (Sonar, dependency
  review, Dependabot summaries). Skim it, don't reply to it.

## Triage each comment before touching anything

Sort every comment into one of three buckets. Do this **before** editing, because the buckets get
handled differently.

**Right** — reproduce it or trace the code path, then fix it.

**Wrong** — prove it, then say so and change nothing.

**Opinion** — a preference, a naming idea, "have you considered X". No single correct answer.
Acknowledge it, give the tradeoff, and only change things if you agree or the developer says to.

### Verify before you act on it

**Never apply a fix just because a reviewer suggested it.** Bot reviewers state wrong things with
total confidence, and a suggestion that sounds authoritative can break working code.

Watch for these:

- **A wrong comment can still point at a real bug.** Check what it was reacting to before dismissing it.
- **`is_outdated: true` does not mean resolved.** It means the lines moved. The bug may still be
  there — the file path in an old thread may even be a pre-rename path. Check current code, not
  the quoted snippet.
- **A human asking "should we double check this?" wants verification, not a change.** Answer the
  question.
- **A wrong premise inside a fair point** still needs correcting, or someone builds on it later.
  Agree with the point, fix the premise, keep it friendly.

## Fix

Normal workflow: make the change, test it, commit, **push**. Reference the reviewer in the commit
body so the reason survives (`Review catch (<reviewer>). <what was wrong>`).

One commit per distinct issue where you can. Keep the sha — the reply cites it.

**Push before you reply, not after.** The reply says "Fixed in `abc1234`", and until that sha is
on the remote the reviewer clicking it gets nothing, the PR still shows the code they objected
to, and a fix that exists only in your working copy is indistinguishable from no fix at all.
Pushing once at the end is fine; pushing per commit is fine. Never finishing without pushing is
not.

If a comment asks for something you think is wrong, don't silently skip it and don't silently do
it. Say what you'd do instead and why, and let the developer decide.

## Reply to every thread
If a thread is already concluded, don't need to reply anymore.
Other than that, reply to all of them, including the ones you're not changing. Silence reads as "ignored".

Use `add_reply_to_pull_request_comment`. The `commentId` is the **number** from the
`#discussion_r<number>` anchor — not the `PRRT_...` id.

### How to write it

Write like you're explaining it to a teammate at their desk. A junior developer should get it on
one read. Make it concise and simple.

- **Lead with the verdict.** "Fixed in `abc1234`." / "This one's a false alarm." / "Fair point,
  here's the tradeoff."
- **Then why, in a sentence or two.** Not a paragraph. 
- Sentences must have full subject and verb.
- **Show evidence when you disagree.** A three-line command output beats an argument.
- **Plain words.** Say "the popup" not "the toast notification subsystem". If a technical term is
  genuinely needed, explain it in half a sentence.
- **Say it once.** Making the same point again in different words doesn't make it clearer, only
  longer. Keep the best version and delete the rest.
- **Stop when the point is made.** If a line doesn't change what the reader thinks or does, cut it.

**Pick evidence that will still be true later.** Some facts never change, like what values a
setting accepts. Others are only true today. If you win an argument with a temporary fact, you
lose it the day that fact changes — and you have quietly agreed that the reviewer's worry was the
right way to judge it. When a temporary fact is all you have, explain the rule you follow instead.

Don't: open every reply with "Great catch!", apologise repeatedly, restate their comment back at
them, paste full diffs, or explain your entire debugging journey.

## Before posting

Post the straightforward replies. **Show the developer any reply that disagrees with a human
reviewer before it goes out** — pushback is fine and often necessary, but they should see the
wording first, since it's their name on it.

Leave threads unresolved. The reviewer resolves their own.

## Wrap up

Tell the developer, per comment: what it said, whether it was right, what you did. Call out
anything you deliberately didn't change and why.
