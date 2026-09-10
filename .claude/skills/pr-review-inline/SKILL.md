---
name: pr-review-inline
description: >
  Review a GitHub pull request and post the findings back to the PR itself as
  line-anchored inline review comments plus one summary verdict, via the GitHub
  MCP server (it does not write a review file to disk). Detects the tech stack of
  the changed code from the repo's own manifests (pom.xml, build.gradle,
  package.json) and applies only the checklists that match what actually changed -
  Java/Spring on the backend, React/TypeScript on the frontend - and defers to the
  reviewed repo's own CLAUDE.md, .claude/rules, and topic docs where they disagree.
  Use when asked to review a PR, review a pull request, comment on a PR, post
  review comments, critique a diff before merge, or re-review a PR after new
  commits land.
---

# PR Review

Review a pull request against stack-appropriate checklists and post the findings
to GitHub as an inline review.

**You are a principal engineer for this repo's stack. Recommend changes; do not make them.**

## Arguments

`$ARGUMENTS` may contain, in any order:

- A PR number (`548`), a full URL (`https://github.com/<owner>/<repo>/pull/548`),
  or nothing (then resolve the PR for the current branch with `gh pr view --json number,url`).
- Optional extra focus areas, e.g. `548 focus on the caching layer`.
- `--dry-run` — produce the review in chat but post nothing to GitHub.

## Step 1 — Resolve and fetch the PR

Read **[pr-review-shared/workflow.md](pr-review-shared/workflow.md)** and follow it.
It covers resolving `owner`/`repo`/`pullNumber`, pulling the diff and file list
through the GitHub MCP server, reading changed files in full, tracing internal
imports two levels deep, and picking up prior review rounds so a re-review does
not re-litigate settled findings.

To read the changed files from disk instead of one MCP call each, run
`python <skill-dir>/scripts/prepare-local-checkout.py --pr <number> --repo-dir <clone>`
and use the `path` it prints. It is safe against a clone with work in progress.

## Step 2 — Detect the stack

Read **[pr-review-shared/stack-detection.md](pr-review-shared/stack-detection.md)** and follow it.

It resolves two things:

1. **Which stacks are in the diff** — Java, React/TypeScript, or both. A PR that
   touches `src/main/java/**` and `webapp/src/**` gets both sets of checklists.
2. **Which frameworks and libraries this repo actually uses** — parsed from
   `pom.xml` / `build.gradle[.kts]` / `package.json`, not assumed. Every checklist
   below is gated on real dependencies. Do not raise a Spring Data finding on a
   repo with no Spring Data, or a React Query finding on a repo using plain `fetch`.

## Step 3 — Load only the relevant checklists

| Detected in the diff | Load |
| --- | --- |
| Java / Kotlin-JVM sources, `pom.xml`, `build.gradle` | **[pr-review-java/INDEX.md](pr-review-java/INDEX.md)** |
| `.ts` / `.tsx` / `.js` / `.jsx`, `package.json` | **[pr-review-react/INDEX.md](pr-review-react/INDEX.md)** |
| Any PR | **[pr-review-shared/cross-cutting.md](pr-review-shared/cross-cutting.md)** |

Each `INDEX.md` is a dispatch table: it lists the aspect files in its folder with
the condition that makes each one relevant. Read the index first, then read only
the aspect files whose condition the diff actually meets. A three-line CSS fix
does not need the concurrency checklist.

Also read **[pr-review-shared/project-context.md](pr-review-shared/project-context.md)**
— it says when to pull in the reviewed repo's own `CLAUDE.md`, skills, architecture
docs, and linked requirements, and when that is a waste of context.

## Step 3b — Run the mechanical scan

```bash
python <skill-dir>/scripts/scan-mechanical-rules.py --pr <number>
# or: gh pr diff <number> | python <skill-dir>/scripts/scan-mechanical-rules.py
```

It regex-scans **added diff lines only** — never the existing tree — for the ~24
rules a script can decide: `var`, mapped associations, `@Enumerated` by ordinal,
concatenated SQL, empty catch blocks, `.only(` left in a test, `as any`,
`dangerouslySetInnerHTML`, index-as-key, hardcoded credentials. Spend your own
attention on the judgement calls instead.

Every hit is a **candidate, not a finding**. Before any of them reaches the PR:
read it in context, confirm the repo's own rules let you object to it, and drop
what does not survive. Do not paste the scan output into a review.

## Step 4 — Review

Work through the loaded checklists against the diff. For every finding:

- Cite `path:line` and anchor it to a line that exists in the diff.
- State the concrete failure: the input or state that triggers it, and the wrong
  result. A finding you cannot make concrete is a question, not a finding.
- Assign a severity from **[pr-review-shared/severity-and-output.md](pr-review-shared/severity-and-output.md)**.
- Verify before reporting. Read the surrounding code, the callers, and the tests.
  Most plausible-looking findings die on contact with the actual call site — drop
  those rather than hedging them into the review.

Scale depth to the diff: a 20-line change gets a focused pass, a 2000-line change
gets the full checklist sweep. Prefer a short review of real defects over a long
one padded with style opinions.

## Step 5 — Post to GitHub

Read **[pr-review-shared/github-review.md](pr-review-shared/github-review.md)** and follow it.

The shape: create a pending review, attach each finding as a line-anchored comment,
then submit once with a summary body. Never post a comment per finding as separate
top-level comments — that spams the PR and sends one notification each.

**The review is submitted with `event: "COMMENT"` by default.** Do not
`APPROVE` or `REQUEST_CHANGES` on the user's behalf unless they explicitly ask;
those carry review authority the user did not delegate. State the recommended
verdict in the summary body instead.

Confirm with the user before submitting if the review contains more than ~15
inline comments — that is usually a sign the diff needs a conversation, not a wall
of comments.

With `--dry-run`, stop here and print the review instead.

## Step 6 — Report back

Print the submitted review URL and a one-paragraph summary: blocker count,
the single most important finding, and the recommended verdict.
